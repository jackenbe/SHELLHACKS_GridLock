"""Projects without IDs (FPL) and utility codes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import _ensure_ids  # noqa: E402


def test_missing_ids_become_unique_and_stable():
    recs = [{"utility": "FPL", "name": "Oasis / Quarry", "page": 110, "project_id": None},
            {"utility": "FPL", "name": "Oasis / Quarry", "page": 110, "project_id": ""},
            {"utility": "GPC", "name": "X", "project_id": 20793}]
    ids = [r["project_id"] for r in _ensure_ids(recs)]
    assert ids[0] != ids[1] and ids[2] == "20793"
    again = _ensure_ids([{"utility": "FPL", "name": "Oasis / Quarry", "page": 110, "project_id": None}])
    assert again[0]["project_id"] == ids[0]   # same project -> same ID on every run
