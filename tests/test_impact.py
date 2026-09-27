"""Cost / savings estimates."""
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from impact import estimate, estimate_all, project_cost  # noqa: E402


class O(NamedTuple):
    utility_a: str
    project_a: str
    utility_b: str
    project_b: str
    tier: str
    time_overlap: bool


def line(pid, util, name, lat1, lon1, lat2, lon2, cost=None):
    return {"project_id": pid, "utility": util, "name": name, "total_cost": cost,
            "lat_a": lat1, "lon_a": lon1, "lat_b": lat2, "lon_b": lon2}


A = line("1", "DESC", "Okatie - Bluffton 115kV: Rebuild", 32.33, -81.03, 32.24, -80.85, cost=11_000_000)
B = line("2", "GPC", "GOSHEN - MCINTOSH 115KV LINE REBUILD", 32.25, -81.21, 32.35, -81.18)
C = line("3", "GPC", "MCINTOSH 230KV REACTORS", 32.35, -81.17, None, None)


def test_project_cost_uses_reported_then_miso():
    assert project_cost(A) == (11.0, "reported by the utility")
    cost, basis = project_cost(B)
    assert basis.startswith("rebuild") and "115 kV" in basis and 8 < cost < 15   # ~7 mi x $1.5M
    assert project_cost(C) == (2.5, "substation work at 230 kV (MISO)")


def test_mobilization_needs_same_window():
    same = estimate(A, B, O("DESC", "1", "GPC", "2", "crews", True))
    later = estimate(A, B, O("DESC", "1", "GPC", "2", "crews", False))
    assert same["savings"] > 0 and same["savings"] == same["savings_if_aligned"]
    assert later["savings"] == 0 and later["savings_if_aligned"] == same["savings"]


def test_total_counts_each_project_once():
    records = [A, B, C]
    overlaps = [O("DESC", "1", "GPC", "2", "crews", True), O("DESC", "1", "GPC", "3", "crews", True)]
    per_pair, summary = estimate_all(records, overlaps)
    pair_sum = sum(e["savings"] for e in per_pair.values())
    # DESC project 1 can only share one mobilization, so the total is less than the pair sum
    assert summary["current_schedules"]["savings_musd"] < round(pair_sum, 2)
    assert summary["current_schedules"]["mobilizations_avoided"] == 1


def test_timeline_adds_up_to_totals():
    records = [A, B, C]
    overlaps = [O("DESC", "1", "GPC", "2", "crews", True), O("DESC", "1", "GPC", "3", "crews", False)]
    _, summary = estimate_all(records, overlaps)
    tl = summary["timeline"]
    today = sum(y["today_musd"] for y in tl["by_year"]) + tl["undated"]["today_musd"]
    aligned = sum(y["aligned_musd"] for y in tl["by_year"]) + tl["undated"]["aligned_musd"]
    assert round(today, 2) == summary["current_schedules"]["savings_musd"]
    assert round(aligned, 2) == summary["if_schedules_aligned"]["savings_musd"]
