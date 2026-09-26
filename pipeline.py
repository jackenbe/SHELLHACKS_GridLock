"""Runs the whole data pipeline once and caches the result.

parse PDFs -> split endpoints (Gemini) -> locate substations -> find overlaps -> validate -> save to DB

The expensive part (parsing + Gemini + matching) is cached in pipeline_cache.json, so
uvicorn --reload restarts are instant. build(force=True) or POST /rebuild re-runs it.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from locate import STATES, fetch_substations, locate_records, sperry_known_points, summary
from overlap import find_overlaps, missing_coordinates
from read_pdf import read_pdf

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")
CACHE_FILE = BASE / "pipeline_cache.json"
CACHE_VERSION = 1

UTILITIES = {
    "DESC": {"name": "Dominion Energy South Carolina", "state": "SC",
             "pdf": "/data/using-data/notgeorgia.pdf"},
    "GPC": {"name": "Georgia Power", "state": "GA",
            "pdf": "/data/using-data/georgia.pdf"},
}


def _load_substations():
    """All cached/downloadable substations. Falls back to whatever is cached if offline."""
    try:
        return fetch_substations()
    except Exception as err:  # offline or Overpass down: use what we have
        print(f"[pipeline] substation download failed ({err}); using cached states only")
        subs = []
        for state in STATES:
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
            recs = read_pdf(u["pdf"])
            for r in recs:
                r["utility"] = code
            print(f"[pipeline] {code}: {len(recs)} projects")
            records += recs
        split_method = _split_endpoints(records)
        substations = _load_substations()
        locate_records(records, substations, known=sperry_known_points())
        CACHE_FILE.write_text(json.dumps(
            {"version": CACHE_VERSION, "split_method": split_method, "records": records}))
    else:
        records, split_method, substations = cached["records"], cached["split_method"], None

    overlaps = find_overlaps(records)
    validations = validate(records)
    state = {
        "records": records,
        "overlaps": overlaps,
        "validations": validations,
        "split_method": split_method,
        "db": "not saved" if fresh else "unchanged (loaded from cache)",
    }
    print(f"[pipeline] {len(records)} projects, {len(overlaps)} overlaps "
          f"({len(records) - len(missing_coordinates(records))} located)")

    if save_to_db and fresh:
        state["db"] = save(records, overlaps, validations, substations)
    return state


def save(records, overlaps, validations, substations=None):
    """Write everything to Postgres. Never crashes the app if the DB is down."""
    try:
        import db
        db.init_db()
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
