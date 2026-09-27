import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

from page_detect import find_project_pages

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")


class Project(BaseModel):
    source_page: int
    project_id: str | None
    name: str
    endpoint_a: str | None
    endpoint_b: str | None
    voltage_kv: int | None
    status: str | None
    in_service_date: str | None
    start_date: str | None
    total_cost: int | None


class Endpoints(BaseModel):
    index: int
    endpoint_a: str | None
    endpoint_b: str | None


EXTRACT_PROMPT = """You extract planned electric transmission projects from utility filings.

Pages are marked "=== PAGE n ===". Return one entry per planned project on these pages.

Rules:
- Only use values that literally appear in the text. Never guess.
- Use null for anything missing, blank, or REDACTED.
- source_page = the page number the project appears on.
- project_id = the utility's own ID (e.g. "Project ID", "Teams #", "TEAMS Number").
- name = the full project name. Table rows can wrap onto several lines; join the pieces.
- endpoint_a / endpoint_b = the two substations a line connects, taken from the name or from
  the listed terminals / "point of origin and termination" ("Sunbreak Substation to the new
  Clover Substation" -> "Sunbreak", "Clover")
  (e.g. "EVANS PRIMARY - THOMSON PRIMARY 115KV REBUILD" -> "EVANS PRIMARY", "THOMSON PRIMARY").
  A project at a single substation has endpoint_b null. Drop voltages and work descriptions.
- voltage_kv = the highest voltage in kV, as an integer.
- in_service_date = planned in-service or need date. start_date = construction start date.
  Format as YYYY-MM-DD when the day is known, YYYY-MM for month/year, YYYY for a year only.
- total_cost = total estimated cost in whole dollars, as an integer.
- Skip cancelled or completed projects, table headers, and anything that is not a planned project.
"""

SPLIT_PROMPT = """For each numbered transmission project name, return the two substations it connects.
Use the exact spelling from the name. Drop voltages (115KV, 230 kV), prefixes like "SAV:" or "GTC:",
and work words (REBUILD, RECONDUCTOR, CONSTRUCT, ...). If the project is at a single substation,
endpoint_b is null. If there is no substation name, both are null. Return the index you were given.
"""


# ---------- models + quota ----------
# Free-tier quotas are per model per day, so when one model runs out we move to the next.
# Flash-Lite first: much higher free daily limit, and plenty for splitting names / reading tables.
DEFAULT_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest"]
_exhausted = set()  # models that hit their daily quota in this process


def model_list():
    if os.getenv("GEMINI_MODELS"):
        models = [m.strip() for m in os.environ["GEMINI_MODELS"].split(",")]
    else:
        models = [os.getenv("GEMINI_MODEL")] + DEFAULT_MODELS
    return list(dict.fromkeys(m for m in models if m))


def _retry_seconds(message):
    m = re.search(r"retry in ([\d.]+)s", message)
    return min(float(m.group(1)) + 1, 30) if m else None


def generate(client, contents, config, retries=3):
    """generate_content with model fallback.

    Daily quota used up (429 ...PerDay...) -> skip that model for the rest of the run.
    Per-minute limit or server error -> wait (as long as Google says, max 30 s) and retry.
    """
    last = None
    for model in [m for m in model_list() if m not in _exhausted]:
        for attempt in range(retries):
            try:
                return client.models.generate_content(model=model, contents=contents, config=config)
            except Exception as err:
                last, code, msg = err, getattr(err, "code", None), str(err)
                if code == 429 and "PerDay" in msg:
                    print(f"[gemini] {model} is out of free daily quota, trying the next model")
                    _exhausted.add(model)
                    break
                if code in (429, 500, 503) and attempt < retries - 1:
                    time.sleep(_retry_seconds(msg) or 5 * 2 ** attempt)
                    continue
                raise
    raise RuntimeError(
        "All Gemini models are out of free quota for today (resets at midnight Pacific). "
        "Enable billing on the Google AI Studio project or set GEMINI_MODELS to other models."
    ) from last


def _squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _iso_date(value, year_only_day="12-31"):
    """Normalize to YYYY-MM-DD. Month-only dates -> the 1st; year-only -> year_only_day
    (end of year for in-service dates, since 'in service 2026' means by the end of 2026)."""
    if not value:
        return None
    v = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", v) or re.fullmatch(r"(\d{1,2})/(\d{4})", v)
    if m:
        y, mo = (m.group(1), m.group(2)) if len(m.group(1)) == 4 else (m.group(2), m.group(1))
        return f"{y}-{int(mo):02d}-01"
    if re.fullmatch(r"20\d{2}", v):
        return f"{v}-{year_only_day}"
    return None


class GeminiAgent:
    def __init__(self, api_key=None, model=None, pages_per_call=8, names_per_call=60,
                 request_gap=4.0, cache_dir=BASE / "gemini_cache"):
        self.client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self.model = model or model_list()[0]  # used for cache file names
        self.pages_per_call = pages_per_call
        self.names_per_call = names_per_call
        self.request_gap = request_gap
        self.cache_dir = Path(cache_dir)

    def extract_projects(self, pdf_path, progress=None):
        """Extract every planned project from any utility PDF. Cached by file hash."""
        cache = self._cache_path(pdf_path)
        if cache.exists():
            cached = json.loads(cache.read_text())
            if cached:  # an empty result is not trusted: retry (the page finder may have improved)
                return cached

        pages = find_project_pages(str(pdf_path))
        n = self.pages_per_call
        batches = [pages[i:i + n] for i in range(0, len(pages), n)]
        results, seen = [], set()

        for b, batch in enumerate(batches, 1):
            page_nums = [num for num, _, _ in batch]
            batch_text = "\n\n".join(f"=== PAGE {num} ===\n{t[:8000]}" for num, t, _ in batch)

            for p in self._generate(EXTRACT_PROMPT + "\n\n" + batch_text, list[Project]):
                rec = p.model_dump()
                if not self._grounded(rec, batch_text):
                    continue
                if rec["source_page"] not in page_nums:
                    rec["source_page"] = page_nums[0]
                rec["in_service_date"] = _iso_date(rec["in_service_date"])
                rec["start_date"] = _iso_date(rec["start_date"], year_only_day="01-01")
                key = rec["project_id"] or rec["name"].upper()
                if key not in seen:
                    seen.add(key)
                    results.append(rec)

            if progress:
                progress(b, len(batches))
            if b < len(batches):
                time.sleep(self.request_gap)

        if results:  # only cache real answers
            self.cache_dir.mkdir(exist_ok=True)
            cache.write_text(json.dumps(results, indent=2))
        return results

    def split_endpoints(self, records):
        """Fill endpoint_a / endpoint_b from each record's name. Returns the same list.

        Answers are cached by project name in gemini_cache/split_endpoints.json, so the same
        names never cost quota twice (rebuilds, restarts, re-uploads).
        """
        cache_file = self.cache_dir / "split_endpoints.json"
        cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        for r in records:
            if r.get("name") in cache and not r.get("endpoint_a"):
                r["endpoint_a"], r["endpoint_b"] = cache[r["name"]]

        todo = [r for r in records if r.get("name") and r["name"] not in cache and not r.get("endpoint_a")]
        n = self.names_per_call
        chunks = [todo[i:i + n] for i in range(0, len(todo), n)]

        for c, chunk in enumerate(chunks, 1):
            prompt = SPLIT_PROMPT + "\n\n" + "\n".join(f"{i}. {r['name']}" for i, r in enumerate(chunk))
            for e in self._generate(prompt, list[Endpoints]):
                if not 0 <= e.index < len(chunk):
                    continue
                rec = chunk[e.index]
                name = _squash(rec["name"])
                for field in ("endpoint_a", "endpoint_b"):
                    value = getattr(e, field)
                    ok = value and _squash(value) and _squash(value) in name
                    rec[field] = value.strip() if ok else None
                cache[rec["name"]] = [rec.get("endpoint_a"), rec.get("endpoint_b")]
            self.cache_dir.mkdir(exist_ok=True)
            cache_file.write_text(json.dumps(cache, indent=1))  # save progress after each call
            if c < len(chunks):
                time.sleep(self.request_gap)

        for r in records:
            r.setdefault("endpoint_a", None)
            r.setdefault("endpoint_b", None)
        return records

    def _generate(self, prompt, schema):
        resp = generate(self.client, prompt, types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=schema, temperature=0))
        return resp.parsed or []

    @staticmethod
    def _grounded(rec, source_text):
        """Drop anything made up: the ID and every word of the name must be in the source."""
        text = _squash(source_text)
        if rec.get("project_id") and _squash(rec["project_id"]) not in text:
            return False
        words = [w for w in re.findall(r"[a-z0-9]+", rec["name"].lower()) if len(w) > 1]
        return bool(words) and all(w in text for w in words)

    def _cache_path(self, pdf_path):
        digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()[:16]
        return self.cache_dir / f"{digest}_{self.model}.json"