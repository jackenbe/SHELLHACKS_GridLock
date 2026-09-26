"""Substation matching: turn project endpoint names into coordinates.

1. fetch_substations()  Every substation in Georgia + South Carolina from OpenStreetMap
                        (Overpass API), cached to geocode_cache/ so it's fetched once.
2. locate_records()     Fuzzy-matches each record's endpoint_a / endpoint_b to those
                        substations with rapidfuzz and adds:
                          lat_a, lon_a, lat_b, lon_b        -> what overlap.find_overlaps() reads
                          match_a, match_b                  -> the OSM name it matched
                          conf_a, conf_b                    -> "high" / "low" / "missing"
                          loc_source_a, loc_source_b        -> "known" / "osm" / "nominatim"

Lookup order per endpoint: known coordinates (e.g. Sperry's xlsx) -> OSM fuzzy match
-> Nominatim search -> missing. When both endpoints have several candidates, it picks
the pair that is closest together, since one transmission line rarely spans > 80 km.
"""
import json
import math
import re
import time
from pathlib import Path

import httpx
from rapidfuzz import fuzz, process

BASE = Path(__file__).parent
CACHE_DIR = BASE / "geocode_cache"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_READ_TIMEOUT = 90   # seconds per mirror before trying the next one
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "gridlock-shellhacks/1.0"

# (south, west, north, east)
STATES = {
    "GA": (30.35, -85.61, 35.00, -80.84),
    "SC": (32.03, -83.36, 35.22, -78.54),
}
STATE_NAMES = {"GA": "Georgia", "SC": "South Carolina"}
UTILITY_STATE = {
    "DESC": "SC", "Dominion Energy South Carolina": "SC",
    "GPC": "GA", "Georgia Power": "GA",
}

HIGH, LOW = 90, 75       # confidence thresholds (0-100 fuzzy score)
MAX_LINE_KM = 80         # endpoints farther apart than this get penalized
STATE_BONUS = 3          # small tiebreak for candidates in the utility's own state

ABBREV = {
    "FT": "FORT", "MT": "MOUNT", "ST": "SAINT", "JCT": "JUNCTION", "HWY": "HIGHWAY",
    "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST", "CO": "COUNTY", "CTR": "CENTER",
}
DROP = {
    # facility words
    "SUBSTATION", "SUB", "SS", "PRIMARY", "STATION", "SWITCHING", "SWITCHYARD", "SWITCH",
    "SW", "TRANSMISSION", "DISTRIBUTION", "ELECTRIC", "POWER", "KV", "THE", "OF", "AND",
    # owners
    "GEORGIA", "DOMINION", "ENERGY", "SCE", "SCEG", "GPC", "DESC", "GTC", "MEAG", "SAV",
    # work words (so full project names still normalize to the place name)
    "REBUILD", "RECONDUCTOR", "CONSTRUCT", "CONSTRUCTION", "LINE", "TIE", "UPGRADE",
    "UPGRADES", "INSTALL", "INSTALLATION", "NEW", "TAP", "FOLD", "IN", "REACTORS",
    "REACTOR", "BANK", "BUS", "BREAKER", "CAPACITOR", "REPLACEMENT", "EXPANSION",
}


# ---------- names ----------

def normalize(name):
    """'SAV: GOSHEN (SAV) #5 115KV Sub' -> 'GOSHEN'. Applied to both sides of every match."""
    s = (name or "").upper()
    s = re.sub(r"\(.*?\)", " ", s)                               # (SAV), (USA), (GPC OWNED)
    s = re.sub(r"^[A-Z]{2,4}:\s*", " ", s)                        # SAV: / GTC: prefixes
    s = re.sub(r"\b\d+(\.\d+)?(/\d+(\.\d+)?)*\s*KV\b", " ", s)    # 115KV, 230/115 kV
    s = re.sub(r"#\s*\d+", " ", s)                               # #5
    s = s.replace("&", " AND ")
    tokens = re.sub(r"[^A-Z0-9 ]", " ", s).split()
    tokens = [ABBREV.get(t, t) for t in tokens]
    return " ".join(t for t in tokens if t not in DROP and not t.isdigit())


def guess_endpoints(project_name):
    """Fallback when endpoint_a/b weren't split by Gemini: 'A - B 115kV Rebuild' -> ('A', 'B')."""
    name = re.sub(r"^[A-Z]{2,4}:\s*", "", project_name or "")
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", name) if p.strip()]
    if not parts:
        return None, None
    return parts[0], (parts[1] if len(parts) > 1 else None)


def _score(q, c):
    """Exact = 100. Otherwise blend: token_set forgives extra words, token_sort punishes them,
    so 'HOOKS' vs 'HOOKS CROSSING' lands in 'low' instead of a false 100."""
    if q == c:
        return 100.0
    return 0.5 * fuzz.token_set_ratio(q, c) + 0.5 * fuzz.token_sort_ratio(q, c)


def _confidence(score):
    return "high" if score >= HIGH else "low" if score >= LOW else "missing"


# ---------- geometry ----------

def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def _in_state(sub, state):
    if state not in STATES:
        return False
    s, w, n, e = STATES[state]
    return s <= sub["lat"] <= n and w <= sub["lon"] <= e


# ---------- data sources ----------

def _overpass(query, label):
    """POST a query to Overpass. Waits and retries on 'busy' answers, then tries the next mirror."""
    errors = []
    for url in OVERPASS_URLS:
        host = url.split("/")[2]
        for attempt in range(2):
            print(f"  {label}: asking {host} ...", flush=True)
            t0 = time.time()
            try:
                resp = httpx.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT},
                                  timeout=httpx.Timeout(10, read=OVERPASS_READ_TIMEOUT))
                if resp.status_code in (429, 504) and attempt == 0:
                    # 429 = too many requests, 504 = server busy: both mean "wait a bit"
                    print(f"  {label}: {host} busy ({resp.status_code}), waiting 20s", flush=True)
                    time.sleep(20)
                    continue
                resp.raise_for_status()
                print(f"  {label}: got {len(resp.content) // 1024} KB in {time.time() - t0:.0f}s", flush=True)
                return resp.json()
            except httpx.HTTPStatusError as err:
                reason = f"HTTP {err.response.status_code}"
            except httpx.HTTPError as err:
                reason = type(err).__name__
            print(f"  {label}: {host} failed ({reason}), trying next mirror", flush=True)
            errors.append(f"{host}: {reason}")
            break
    raise RuntimeError(f"All Overpass mirrors failed for {label}: {errors}. Try again in a few minutes.")


def fetch_substations(states=("GA", "SC"), refresh=False):
    """All named substations in the given states from OpenStreetMap.

    One small query per state, cached per state in geocode_cache/, so it only
    downloads once and a failed state can be retried without redoing the others.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    subs, downloaded = [], False
    for state in states:
        cache = CACHE_DIR / f"substations_{state.lower()}.json"
        if cache.exists() and not refresh:
            subs += json.loads(cache.read_text())
            continue

        if downloaded:
            time.sleep(5)  # be polite between back-to-back queries
        # named substations inside the state's real boundary; out center = one point each
        query = (f'[out:json][timeout:{OVERPASS_READ_TIMEOUT - 10}];'
                 f'area["ISO3166-2"="US-{state}"]["admin_level"="4"]->.st;'
                 f'nwr["power"="substation"]["name"](area.st);'
                 f'out center tags;')
        data = _overpass(query, f"substations {state}")
        downloaded = True

        found = []
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            lat = el.get("lat", el.get("center", {}).get("lat"))
            lon = el.get("lon", el.get("center", {}).get("lon"))
            if tags.get("name") and lat is not None and lon is not None:
                found.append({
                    "id": f"{el['type']}/{el['id']}", "name": tags["name"], "lat": lat, "lon": lon,
                    "operator": tags.get("operator"), "voltage": tags.get("voltage"), "state": state,
                })
        cache.write_text(json.dumps(found))
        print(f"  substations {state}: {len(found)} saved to {cache.name}", flush=True)
        subs += found

    # the GA and SC boxes overlap along the Savannah River, so drop duplicates
    unique = {x["id"]: x for x in subs}
    return list(unique.values())


def nominatim_lookup(name, state=None):
    """Last-resort search on OSM's place search. Cached; respects the 1 request/second rule."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / "nominatim.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    q = f"{name} substation, {STATE_NAMES.get(state, '')}".strip(", ")
    if q not in cache:
        time.sleep(1.1)
        try:
            resp = httpx.get(NOMINATIM_URL, timeout=20, headers={"User-Agent": USER_AGENT},
                             params={"q": q, "format": "json", "limit": 1, "countrycodes": "us"})
            resp.raise_for_status()
            hits = resp.json()
            cache[q] = {"name": hits[0]["display_name"], "lat": float(hits[0]["lat"]),
                        "lon": float(hits[0]["lon"])} if hits else None
        except httpx.HTTPError:
            return None  # offline or blocked: don't cache, just skip
        cache_file.write_text(json.dumps(cache, indent=2))
    return cache[q]


# ---------- matching ----------

class SubstationIndex:
    def __init__(self, substations):
        self.subs = substations
        self.norms = [normalize(s["name"]) for s in substations]

    def candidates(self, name, limit=10):
        """[(score, substation)] best first, only scores >= LOW."""
        q = normalize(name)
        if not q:
            return []
        rough = process.extract(q, self.norms, scorer=fuzz.token_set_ratio,
                                limit=40, score_cutoff=LOW)
        scored = [(_score(q, self.norms[i]), self.subs[i]) for _, _, i in rough]
        scored = [x for x in scored if x[0] >= LOW]
        scored.sort(key=lambda x: -x[0])
        return scored[:limit]


def _pick(cands_a, cands_b, state):
    """Best (score_a, sub_a, score_b, sub_b). Prefers own-state candidates and short lines."""
    def rank(score, sub):
        return score + (STATE_BONUS if _in_state(sub, state) else 0)

    best_a = max(cands_a, key=lambda x: rank(*x), default=None)
    best_b = max(cands_b, key=lambda x: rank(*x), default=None)
    if not (cands_a and cands_b):
        return best_a, best_b

    best, best_total = (best_a, best_b), -math.inf
    for sa, ca in cands_a:
        for sb, cb in cands_b:
            if ca["id"] == cb["id"]:
                continue
            penalty = max(0.0, _km(ca, cb) - MAX_LINE_KM) / 5
            total = rank(sa, ca) + rank(sb, cb) - penalty
            if total > best_total:
                best, best_total = ((sa, ca), (sb, cb)), total
    return best


def locate_records(records, substations=None, known=None, use_nominatim=True):
    """Add coordinates + confidence to every record. Returns the same list.

    known: optional {normalized name: (lat, lon)} of verified points, e.g. sperry_known_points().
    """
    index = SubstationIndex(substations if substations is not None else fetch_substations())
    known = known or {}

    for rec in records:
        state = UTILITY_STATE.get(rec.get("utility") or rec.get("source"))
        a, b = rec.get("endpoint_a"), rec.get("endpoint_b")
        if not a and not b:
            a, b = guess_endpoints(rec.get("name"))

        cands = {"a": index.candidates(a) if a else [], "b": index.candidates(b) if b else []}
        picked = dict(zip("ab", _pick(cands["a"], cands["b"], state)))

        for end, name in (("a", a), ("b", b)):
            lat = lon = match = None
            conf, source = "missing", None
            if name and normalize(name) in known:
                (lat, lon), match, conf, source = known[normalize(name)], name, "high", "known"
            elif picked[end]:
                score, sub = picked[end]
                lat, lon, match, conf, source = sub["lat"], sub["lon"], sub["name"], _confidence(score), "osm"
            elif name and use_nominatim:
                hit = nominatim_lookup(normalize(name) or name, state)
                if hit:
                    lat, lon, match, conf, source = hit["lat"], hit["lon"], hit["name"], "low", "nominatim"
            rec.update({
                f"lat_{end}": lat, f"lon_{end}": lon, f"match_{end}": match,
                f"conf_{end}": conf, f"loc_source_{end}": source,
            })
    return records


def sperry_known_points(xlsx=BASE / "data" / "Sperry-Tech-Challenge" / "Projects_Overlaps.xlsx"):
    """{normalized substation name: (lat, lon)} from Sperry's answer key, used as verified points."""
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, data_only=True)["projects"]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    known = {}
    for row in rows:
        r = dict(zip(header, row))
        for end in ("a", "b"):
            name, lat, lon = r.get(f"name_{end}"), r.get(f"lat_{end}"), r.get(f"lon_{end}")
            if name and lat is not None and lon is not None:
                known[normalize(name)] = (float(lat), float(lon))
    return known


def summary(records):
    """Counts of high / low / missing endpoints, for the validation report."""
    out = {"high": 0, "low": 0, "missing": 0}
    for r in records:
        for end in ("a", "b"):
            if r.get(f"endpoint_{end}") or r.get(f"match_{end}") or end == "a":
                out[r.get(f"conf_{end}", "missing")] += 1
    return out


if __name__ == "__main__":
    from read_pdf import read_pdf

    print("Loading substations (downloads once, then cached in geocode_cache/)")
    subs = fetch_substations()
    print(f"{len(subs)} named substations in GA + SC")
    known = sperry_known_points()
    for pdf in ("/data/using-data/notgeorgia.pdf", "/data/using-data/georgia.pdf"):
        recs = locate_records(read_pdf(pdf), subs, known)
        print(pdf, summary(recs))
        for r in recs[:5]:
            print("  ", r["name"], "|", r["match_a"], r["conf_a"], "|", r["match_b"], r["conf_b"])
