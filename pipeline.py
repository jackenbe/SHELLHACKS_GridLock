"""Runs the whole data pipeline once and caches the result.

parse PDFs -> split endpoints (Gemini) -> locate substations -> find overlaps -> validate -> save to DB

The expensive part (parsing + Gemini + matching) is cached in pipeline_cache.json, so
uvicorn --reload restarts are instant. build(force=True) or POST /api/refresh re-runs it.

add_utility() handles PDFs uploaded from the frontend: parse (regex, or Gemini for an
unknown layout), locate, then recompute overlaps across every utility loaded so far.
"""
import json
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

import locate
from locate import STATES, fetch_substations, locate_records, sperry_known_points, summary
from impact import estimate_all
from overlap import find_overlaps, missing_coordinates
from read_pdf import read_pdf

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")
CACHE_FILE = BASE / "pipeline_cache.json"
CACHE_VERSION = 2
LOCK = threading.Lock()  # one pipeline change at a time (startup, refresh, uploads)

UTILITIES = {
    "DESC": {"name": "Dominion Energy South Carolina", "state": "SC",
             "pdf": "/data/using-data/notgeorgia.pdf"},
    "GPC": {"name": "Georgia Power", "state": "GA",
            "pdf": "/data/using-data/georgia.pdf"},
}
PRELOADED = set(UTILITIES)  # the demo utilities that load at startup


def _states():
    return tuple(sorted({u["state"] for u in UTILITIES.values() if u.get("state")}))


def _register(code, name, state, pdf):
    UTILITIES[code] = {"name": name, "state": state, "pdf": pdf}
    locate.UTILITY_STATE[code] = state


def _load_substations():
    """Substations for every loaded utility's state. Falls back to the cache if offline."""
    try:
        return fetch_substations(_states())
    except Exception as err:  # offline or Overpass down: use what we have
        print(f"[pipeline] substation download failed ({err}); using cached states only")
        subs = []
        for state in _states():
            f = BASE / "geocode_cache" / f"substations_{state.lower()}.json"
            if f.exists():
                subs += json.loads(f.read_text())
        return subs


def _split_endpoints(records):
    if not os.getenv("GEMINI_API_KEY"):
        print("[pipeline] no GEMINI_API_KEY, using regex endpoint split")
        return "regex"
    try:
        from gemini_agent import GeminiAgent
        GeminiAgent().split_endpoints(records)
        return "gemini"
    except Exception as err:
        print(f"[pipeline] Gemini split failed ({err}); using regex endpoint split")
        for r in records:
            r.pop("endpoint_a", None)
            r.pop("endpoint_b", None)
        return "regex"


def _parse(pdf, progress=lambda pct, msg: None):
    """Known layouts via regex templates; anything else via Gemini. Returns (records, method)."""
    records = read_pdf(pdf)
    if records:
        return records, "regex"
    if not os.getenv("GEMINI_API_KEY"):
        return [], "none"
    from gemini_agent import GeminiAgent
    progress(15, "Unknown layout, reading it with Gemini")
    found = GeminiAgent().extract_projects(
        BASE / pdf.lstrip("/"),
        progress=lambda d, t: progress(15 + int(50 * d / t), f"Gemini: batch {d} of {t}"))
    for r in found:  # Gemini field names -> pipeline field names
        r["in_service"] = r.pop("in_service_date", None)
        r["page"] = r.pop("source_page", None)
    return found, "gemini"


def validate(records):
    """Per-record data-quality checks for the validation report."""
    results = []
    for r in records:
        def add(check, passed, detail=None):
            results.append({"utility": r["utility"], "project_id": r.get("project_id"),
                            "check": check, "passed": bool(passed), "detail": detail})

        add("name", r.get("name"), None if r.get("name") else "no project name found")
        add("in_service_date", r.get("in_service"),
            r.get("in_service") or "no in-service / need date found")
        add("endpoints_found", r.get("endpoint_a"),
            " / ".join(x for x in (r.get("endpoint_a"), r.get("endpoint_b")) if x) or
            "could not read substation names from the project name")
        for end in ("a", "b"):
            if not r.get(f"endpoint_{end}"):
                continue
            conf = r.get(f"conf_{end}", "missing")
            detail = f"{conf}: {r.get(f'endpoint_{end}')}"
            if r.get(f"match_{end}"):
                detail += f" -> {r[f'match_{end}']}"
            add(f"coords_{end}", conf in ("high", "low"), detail)
        located = r.get("lat_a") is not None or r.get("lat_b") is not None
        add("located", located, None if located else "no trusted coordinates, excluded from overlaps")
    return results


def build(force=False, save_to_db=True):
    """Return the pipeline state dict. Uses pipeline_cache.json unless force=True."""
    cached = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else None
    fresh = force or not cached or cached.get("version") != CACHE_VERSION

    if fresh:
        print("[pipeline] building from PDFs ...")
        records = []
        for code, u in UTILITIES.items():
            recs, method = _parse(u["pdf"])
            for r in recs:
                r["utility"] = code
            print(f"[pipeline] {code}: {len(recs)} projects ({method})")
            records += recs
        split_method = _split_endpoints(records)
        substations = _load_substations()
        locate_records(records, substations, known=sperry_known_points())
        _write_cache(records, split_method)
    else:
        for code, u in cached.get("utilities", {}).items():  # restore uploaded utilities
            _register(code, u["name"], u["state"], u["pdf"])
        records, split_method, substations = cached["records"], cached["split_method"], None

    overlaps = find_overlaps(records)
    validations = validate(records)
    state = {
        "records": records,
        "overlaps": overlaps,
        "impact": estimate_all(records, overlaps),
        "validations": validations,
        "split_method": split_method,
        "db": "not saved" if fresh else "unchanged (loaded from cache)",
    }
    print(f"[pipeline] {len(records)} projects, {len(overlaps)} overlaps "
          f"({len(records) - len(missing_coordinates(records))} located)")

    if save_to_db and fresh:
        state["db"] = save(records, overlaps, validations, substations)
    return state


def _write_cache(records, split_method):
    CACHE_FILE.write_text(json.dumps({"version": CACHE_VERSION, "split_method": split_method,
                                      "utilities": UTILITIES, "records": records}))


def add_utility(state, code, name, us_state, pdf, progress=lambda pct, msg: None):
    """Parse an uploaded PDF and merge it into the running state.

    Same code as an existing utility -> its projects are replaced (re-uploading the demo PDF
    gives the same result). New code -> added, and overlaps are recomputed across all utilities.
    """
    progress(5, "Reading the PDF")
    records, method = _parse(pdf, progress)
    if not records:
        raise ValueError("No planned projects found in this PDF" +
                         ("" if os.getenv("GEMINI_API_KEY") else " (set GEMINI_API_KEY to read new layouts)"))
    for r in records:
        r["utility"] = code

    if method == "regex":
        progress(68, "Splitting line names into substations")
        _split_endpoints(records)
    _register(code, name, us_state, pdf)
    progress(75, f"Matching substations in {us_state} (first time for a new state takes ~1 min)")
    locate_records(records, _load_substations(), known=sperry_known_points())

    progress(90, "Finding overlaps with the other utilities")
    merged = [r for r in state["records"] if r["utility"] != code] + records
    overlaps = find_overlaps(merged)
    validations = validate(merged)
    state.update(records=merged, overlaps=overlaps, validations=validations,
                 impact=estimate_all(merged, overlaps))
    _write_cache(merged, state.get("split_method"))

    progress(95, "Saving to the database")
    state["db"] = save(merged, overlaps, validations)
    return {
        "utility": code,
        "count": len(records),
        "method": method,
        "located": sum(1 for r in records if r.get("lat_a") is not None or r.get("lat_b") is not None),
        "overlaps": sum(1 for o in overlaps if code in (o.utility_a, o.utility_b)),
    }


def remove_utility(state, code):
    """Drop an uploaded utility and recompute overlaps. Preloaded demo utilities stay."""
    if code in PRELOADED:
        raise ValueError(f"{code} is a preloaded demo utility and can't be removed")
    if code not in UTILITIES:
        raise KeyError(code)
    UTILITIES.pop(code)
    locate.UTILITY_STATE.pop(code, None)
    merged = [r for r in state["records"] if r["utility"] != code]
    overlaps = find_overlaps(merged)
    validations = validate(merged)
    state.update(records=merged, overlaps=overlaps, validations=validations,
                 impact=estimate_all(merged, overlaps))
    _write_cache(merged, state.get("split_method"))
    state["db"] = save(merged, overlaps, validations, drop_utilities=[code])


def save(records, overlaps, validations, substations=None, drop_utilities=()):
    """Write everything to Postgres. Never crashes the app if the DB is down."""
    try:
        import db
        db.init_db()
        for code in drop_utilities:
            db.delete_utility(code)
        ids = db.save_projects(records)
        if substations:
            db.save_substations(substations)
        n = db.save_overlaps(overlaps, ids)
        db.save_validations(validations, ids)
        print(f"[pipeline] saved to database ({len(ids)} projects, {n} overlaps)")
        return "saved"
    except Exception as err:
        print(f"[pipeline] database save failed: {err}")
        return f"error: {type(err).__name__}"


def location_summary(records):
    return summary(records)
