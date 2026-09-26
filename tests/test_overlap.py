"""Reproduce Sperry's 6 answer-key overlaps from Projects_Overlaps.xlsx."""
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from overlap import find_overlaps  # noqa: E402

XLSX = ROOT / "data" / "Sperry-Tech-Challenge" / "Projects_Overlaps.xlsx"


def load_sheet(name):
    ws = openpyxl.load_workbook(XLSX, data_only=True)[name]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    return [dict(zip(header, r)) for r in rows if r[0]]


def sperry_records():
    return [{
        "project_id": r["project_id"], "name": r["project_name"], "utility": r["utility"],
        "lat_a": r["lat_a"], "lon_a": r["lon_a"], "lat_b": r["lat_b"], "lon_b": r["lon_b"],
        "in_service": r["in_service_date"],
    } for r in load_sheet("projects")]


def pair(a, b):
    return frozenset((a, b))


def test_reproduces_sperry_overlaps():
    expected = {pair(r["project_id_a"], r["project_id_b"]) for r in load_sheet("overlaps")}
    found = {pair(o.project_a, o.project_b) for o in find_overlaps(sperry_records())}
    assert found == expected


def test_shared_substation_is_touching():
    # DESC_2 and GPC_1 both end at Thurmond: Sperry's center method says 4.09 mi,
    # closest-point distance is 0.
    o = next(o for o in find_overlaps(sperry_records())
             if pair(o.project_a, o.project_b) == pair("DESC_2", "GPC_1"))
    assert o.tier == "touching" and o.rank == 1


def test_far_projects_not_flagged():
    ids = {x for o in find_overlaps(sperry_records()) for x in (o.project_a, o.project_b)}
    assert not ids & {"DESC_4", "GPC_4", "GPC_5"}
