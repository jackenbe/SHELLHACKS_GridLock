"""Matcher tests with a fake substation list (no network needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from locate import guess_endpoints, locate_records, normalize  # noqa: E402

# OSM-style names, real coordinates, plus decoys with the same names far away
SUBS = [
    {"id": "n/1", "name": "Thurmond Dam Substation", "lat": 33.660127, "lon": -82.195931},
    {"id": "n/2", "name": "Evans Primary", "lat": 33.543994, "lon": -82.168648},
    {"id": "n/3", "name": "Evans", "lat": 34.95, "lon": -84.10},              # decoy, north GA
    {"id": "n/4", "name": "McIntosh Substation", "lat": 32.352116, "lon": -81.175112},
    {"id": "n/5", "name": "Goshen", "lat": 32.248701, "lon": -81.209472},
    {"id": "n/6", "name": "Jasper Substation", "lat": 32.35912, "lon": -81.1246},
    {"id": "n/7", "name": "Jasper", "lat": 34.47, "lon": -84.43},             # decoy, Jasper GA
    {"id": "n/8", "name": "Okatie", "lat": 32.333758, "lon": -81.032495},
    {"id": "n/9", "name": "Hooks Crossing", "lat": 33.0, "lon": -80.0},       # near-miss name
]


def test_normalize():
    assert normalize("SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD") == "GOSHEN MCINTOSH"
    assert normalize("THURMOND DAM (USA) #5") == "THURMOND DAM"
    assert normalize("Ft Johnson Sub") == "FORT JOHNSON"


def test_guess_endpoints():
    assert guess_endpoints("EVANS PRIMARY - THOMSON PRIMARY 115KV REBUILD") == ("EVANS PRIMARY", "THOMSON PRIMARY 115KV REBUILD")
    assert guess_endpoints("SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD")[0] == "GOSHEN (SAV)"


def test_matches_and_confidence():
    recs = locate_records([
        {"name": "EVANS PRIMARY - THURMOND DAM (USA) #5 115KV REBUILD", "source": "GPC"},
        {"name": "Jasper - Okatie 230 kV #2: Construct", "source": "DESC"},
        {"name": "Hooks - Thurmond 115 kV Tie: Rebuild", "source": "DESC"},
        {"name": "Nowhere Real - Also Fake 115kV", "source": "GPC"},
    ], SUBS, use_nominatim=False)
    evans, jasper, hooks, fake = recs

    # picks the Evans next to Thurmond, not the same-named decoy 150 km away
    assert (evans["lat_a"], evans["conf_a"]) == (33.543994, "high")
    assert evans["match_b"] == "Thurmond Dam Substation"
    # picks the SC Jasper next to Okatie, not Jasper GA
    assert jasper["lat_a"] == 32.35912 and jasper["conf_b"] == "high"
    # 'Hooks' vs 'Hooks Crossing' is only a partial match -> low, not high
    assert hooks["conf_a"] == "low"
    assert fake["conf_a"] == fake["conf_b"] == "missing" and fake["lat_a"] is None


def test_known_points_win():
    recs = locate_records([{"name": "Hooks - Thurmond", "source": "DESC"}], SUBS,
                          known={"HOOKS": (33.5, -82.0)}, use_nominatim=False)
    assert (recs[0]["lat_a"], recs[0]["loc_source_a"], recs[0]["conf_a"]) == (33.5, "known", "high")
