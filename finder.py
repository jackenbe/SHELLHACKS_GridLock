"""Find a utility's public planning PDFs online.

Two sources, merged and ranked:
  1. Known regional planning portals (no API key): crawl the page, keep PDF links, and score
     them on words like "project descriptions", "expansion plan", "IRP", recent years, and
     the utility's name. FERC orders, NDAs, tariffs and forms are pushed down.
  2. Gemini with Google Search (needs GEMINI_API_KEY): asks for direct PDF links for any
     utility, then follows Google's redirect links to the real URLs.
Every candidate is then probed: it only counts as "verified" if the server returns a PDF.

download_pdf() fetches the chosen file safely (http/https only, no private/internal
addresses, size limit, must start with %PDF) so it can go through the normal upload pipeline.
"""
import ipaddress
import json
import os
import re
import socket
from datetime import date
from html import unescape
from urllib.parse import urljoin, urlparse

import httpx

USER_AGENT = "Mozilla/5.0 (GridLock planning-data finder; ShellHacks 2026)"
TIMEOUT = httpx.Timeout(15, connect=8)
MAX_PDF_MB = 60

PORTALS = [
    {"name": "SCRTP", "url": "https://www.scrtp.com/",
     "covers": ["dominion", "desc", "santee", "sceg", "south carolina electric"]},
    {"name": "SERTP reference library", "url": "https://www.southeasternrtp.com/reference_library.cshtml",
     "covers": ["georgia power", "southern", "gpc", "duke", "tva", "tennessee valley", "gtc",
                "georgia transmission", "meag", "powersouth", "dalton", "lg&e", "aeci", "dominion", "santee"]},
    {"name": "SERTP home", "url": "https://www.southeasternrtp.com/home.cshtml",
     "covers": ["georgia power", "southern", "gpc", "duke", "tva", "gtc", "meag", "powersouth"]},
]

# Utilities whose plans live at predictable URLs (the portal pages are JavaScript-only, so
# there is nothing to crawl). Candidates are generated for recent years and only kept if the
# URL really returns a PDF.
FL_PSC_TYSP = ("https://www.floridapsc.com/pscfiles/website-files/PDF/Utilities/Electricgas/"
               "TenYearSitePlans/{year}/{file}.pdf")
KNOWN_DOCS = [
    {"state": "FL", "aliases": ["fpl", "florida power & light", "florida power and light", "nextera"],
     "source": "Florida PSC Ten-Year Site Plans",
     "title": "FPL Ten Year Site Plan {year}",
     "templates": [FL_PSC_TYSP.replace("{file}", "Florida%20Power%20and%20Light%20Company")],
     "fixed": [("FPL Ten Year Site Plan (fpl.com)",
                "https://www.fpl.com/content/dam/fplgp/us/en/about/pdf/ten-year-site-plan.pdf")]},
    {"state": "FL", "aliases": ["duke energy florida"], "source": "Florida PSC Ten-Year Site Plans",
     "title": "Duke Energy Florida Ten Year Site Plan {year}",
     "templates": [FL_PSC_TYSP.replace("{file}", "Duke%20Energy%20Florida")]},
    {"state": "FL", "aliases": ["tampa electric", "teco"], "source": "Florida PSC Ten-Year Site Plans",
     "title": "Tampa Electric Ten Year Site Plan {year}",
     "templates": [FL_PSC_TYSP.replace("{file}", "Tampa%20Electric%20Company")]},
    {"state": "FL", "aliases": ["fmpa", "florida municipal power"], "source": "Florida PSC Ten-Year Site Plans",
     "title": "FMPA Ten Year Site Plan {year}",
     "templates": [FL_PSC_TYSP.replace("{file}", "FMPA%20Municipal%20Power")]},
]

GOOD_WORDS = {
    "project description": 6, "planned transmission": 6, "expansion plan": 6, "10 year": 5,
    "ten year": 5, "10-year": 5, "project list": 5, "integrated resource plan": 4, "irp": 4, "site plan": 4,
    "transmission plan": 4, "2million": 4, "planned": 2, "projects": 2, "transmission": 1,
}
BAD_WORDS = {
    "ferc order": -10, "ferc-order": -10, "nda": -8, "tariff": -8, "oatt": -8, "form": -6,
    "transmittal": -6, "attachment k": -5, "attachment-k": -5, "presentation": -2, "meeting": -1,
}


# ---------- scoring ----------

def _tokens(name):
    return [t for t in re.findall(r"[a-z0-9&]+", name.lower()) if len(t) > 2 and t not in
            ("energy", "power", "the", "company", "inc", "llc", "electric")]


def score(text, utility_name):
    t = text.lower().replace("_", " ").replace("%20", " ")
    s = sum(w for k, w in GOOD_WORDS.items() if k in t)
    s += sum(w for k, w in BAD_WORDS.items() if re.search(rf"\b{re.escape(k)}\b", t))
    s += 3 * sum(1 for tok in _tokens(utility_name) if tok in t)
    years = [int(y) for y in re.findall(r"20[1-3]\d", t)]
    if years:
        s += max(-4, min(4, max(years) - date.today().year + 2))  # newer filings rank higher
    return s


# ---------- 1. portals ----------

LINK_RE = re.compile(r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)


def pdf_links(html, base_url):
    out = []
    for href, text in LINK_RE.findall(html):
        url = urljoin(base_url, unescape(href.strip()))
        if ".pdf" in url.lower():
            label = " ".join(re.sub(r"<[^>]+>", " ", unescape(text)).split())
            out.append({"url": url, "title": label or url.rsplit("/", 1)[-1]})
    return out


def search_portals(utility_name, client):
    name = utility_name.lower()
    candidates = []
    for portal in PORTALS:
        if not any(k in name for k in portal["covers"]):
            continue
        try:
            html = client.get(portal["url"]).text
        except httpx.HTTPError as err:
            print(f"[finder] {portal['name']} unreachable: {err}")
            continue
        for link in pdf_links(html, portal["url"]):
            candidates.append({**link, "source": portal["name"],
                               "score": score(f"{link['title']} {link['url']}", utility_name),
                               "why": f"Linked from {portal['name']}"})
    return candidates


def search_known(utility_name):
    """Generated URLs for utilities with predictable filing locations (checked later)."""
    name = f" {utility_name.lower()} "
    year = date.today().year
    out = []
    for doc in KNOWN_DOCS:
        if not any(re.search(rf"\b{re.escape(a)}\b", name) for a in doc["aliases"]):
            continue
        for y in (year + 1, year, year - 1):  # plans are filed for the coming years
            for t in doc["templates"]:
                out.append({"url": t.format(year=y), "title": doc["title"].format(year=y),
                            "source": doc["source"], "why": "Official filing location",
                            "state": doc.get("state"),
                            "score": 12 + (y - year), "generated": True})
        for title, url in doc.get("fixed", []):
            out.append({"url": url, "title": title, "source": doc["source"], "state": doc.get("state"),
                        "why": "Utility's own copy", "score": 11, "generated": True})
    return out


# ---------- 2. Gemini + Google Search ----------

GEMINI_PROMPT = """Find direct links to PUBLIC PDF documents in which the electric utility "{name}"
({state}) lists its planned future transmission construction projects: for example a
10-year transmission expansion plan, a planned transmission project list, or the
transmission section of its integrated resource plan. Prefer the most recent filings.
Skip anything marked CEII / confidential.

Reply with ONLY a JSON array like
[{{"title": "...", "url": "https://....pdf", "why": "one short sentence"}}]"""


def search_gemini(utility_name, state, client, errors):
    if not os.getenv("GEMINI_API_KEY"):
        return []
    try:
        from google import genai
        from google.genai import types
        from gemini_agent import generate
        gclient = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = generate(gclient, GEMINI_PROMPT.format(name=utility_name, state=state),
                        types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())], temperature=0))
    except Exception as err:
        print(f"[finder] Gemini search failed: {err}")
        errors.append(f"Gemini search failed: {str(err)[:200]}")
        return []

    found = []
    text = resp.text or ""
    match = re.search(r"\[.*\]", text, re.S)
    if match:
        try:
            for item in json.loads(match.group(0)):
                if isinstance(item, dict) and str(item.get("url", "")).startswith("http"):
                    found.append({"url": item["url"], "title": item.get("title") or item["url"],
                                  "why": item.get("why") or "Found by Gemini search"})
        except json.JSONDecodeError:
            pass
    # the grounding sources Gemini actually used (Google redirect links -> real URLs)
    try:
        for chunk in resp.candidates[0].grounding_metadata.grounding_chunks or []:
            if chunk.web and chunk.web.uri:
                found.append({"url": chunk.web.uri, "title": chunk.web.title or chunk.web.uri,
                              "why": "Source Gemini cited"})
    except (AttributeError, IndexError, TypeError):
        pass
    if not found:
        errors.append("Gemini search returned no links")

    out = []
    for f in found:
        url = _resolve(f["url"], client)
        out.append({**f, "url": url, "source": "Gemini + Google Search",
                    "score": score(f"{f['title']} {url}", utility_name) + 2})
    return out


def _resolve(url, client):
    """Follow Google's grounding redirect links to the real document URL."""
    if "grounding-api-redirect" not in url:
        return url
    try:
        return str(client.head(url, follow_redirects=True).url)
    except httpx.HTTPError:
        return url


# ---------- safety + probing ----------

def check_public_url(url):
    """Only public http(s) hosts: no localhost, private networks or cloud metadata IPs."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Only http(s) links are allowed")
    for info in socket.getaddrinfo(parts.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("That address is not a public website")


def probe(url, client):
    """(is_pdf, size_mb) by reading only the first bytes."""
    try:
        check_public_url(url)
        with client.stream("GET", url, follow_redirects=True) as r:
            if r.status_code >= 400:
                return False, None
            head = next(r.iter_bytes(1024), b"")
            size = r.headers.get("content-length")
            return head.startswith(b"%PDF"), round(int(size) / 1e6, 1) if size else None
    except (httpx.HTTPError, ValueError, OSError):
        return False, None


def find_plans(utility_name, state, limit=8):
    """Ranked, deduplicated, probed candidates."""
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
                      follow_redirects=True) as client:
        errors = []
        raw = (search_known(utility_name) + search_portals(utility_name, client)
               + search_gemini(utility_name, state, client, errors))
        best = {}
        for c in raw:
            key = c["url"].split("#")[0]
            if key not in best or c["score"] > best[key]["score"]:
                best[key] = {**c, "url": key}
        generated = [c for c in best.values() if c.get("generated")]
        others = sorted((c for c in best.values() if not c.get("generated")),
                        key=lambda c: -c["score"])[:limit]
        for c in generated + others:
            c["verified"], c["size_mb"] = probe(c["url"], client)
    # generated guesses only count if they really exist
    ranked = [c for c in generated if c["verified"]] + others
    ranked.sort(key=lambda c: (not c["verified"], -c["score"]))
    for c in ranked:
        c.pop("generated", None)
    return {"candidates": ranked[:limit], "used_gemini": bool(os.getenv("GEMINI_API_KEY")),
            "errors": errors}


def download_pdf(url):
    """Download a chosen PDF with the same checks as a manual upload. Returns bytes."""
    check_public_url(url)
    limit = MAX_PDF_MB * 1024 * 1024
    chunks, total = [], 0
    with httpx.Client(timeout=httpx.Timeout(60, connect=10), headers={"User-Agent": USER_AGENT},
                      follow_redirects=True) as client:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            check_public_url(str(r.url))  # the redirect target must be public too
            for chunk in r.iter_bytes():
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"PDF is larger than {MAX_PDF_MB} MB")
                chunks.append(chunk)
    data = b"".join(chunks)
    if not data.startswith(b"%PDF"):
        raise ValueError("That link did not return a PDF")
    return data
