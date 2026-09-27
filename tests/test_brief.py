"""Coordination memo: facts only, numbers checked, safe fallback."""
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brief  # noqa: E402


class O(NamedTuple):
    rank: int
    utility_a: str
    project_a: str
    utility_b: str
    project_b: str
    distance_km: float
    distance_mi: float
    tier: str
    time_gap_days: int
    time_overlap: bool


O1 = O(3, "DESC", "06367 D - G", "GPC", "20277", 5.46, 3.39, "site logistics", 152, True)
A = {"utility": "DESC", "project_id": "06367 D - G", "name": "Jasper - Okatie 230 kV #2: Construct",
     "in_service": "12/31/25", "start_date": None, "page": 9}
B = {"utility": "GPC", "project_id": "20277", "name": "SAV: MCINTOSH - PURRYSBURG 230KV REACTORS",
     "in_service": "06/01/2026", "start_date": "01/01/2024", "page": 262}
IMPACT = {"cost_a": 23.79, "cost_a_basis": "reported by the utility", "cost_b": 2.5,
          "cost_b_basis": "substation work at 230 kV (MISO)",
          "items": [{"key": "mobilization", "label": "One crew mobilization instead of two", "amount": 0.125,
                     "needs_alignment": False, "detail": "5% of the smaller project ($2.5M)"}],
          "savings": 0.125, "savings_if_aligned": 0.125, "resources": ["1 crew and equipment mobilization avoided"]}
NAMES = {"DESC": "Dominion Energy South Carolina", "GPC": "Georgia Power"}


@pytest.fixture(autouse=True)
def no_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(brief, "CACHE", tmp_path / "briefs.json")


def test_template_uses_only_numbers_from_the_facts():
    facts = brief.build_facts(O1, A, B, IMPACT, NAMES)
    memo = brief.template_memo(O1, A, B, IMPACT, NAMES)
    assert brief.unverified_numbers(memo, facts) == []
    assert "5.46 km" in memo and "$125K" in memo and "p. 262" in memo


def test_invented_numbers_are_caught():
    facts = brief.build_facts(O1, A, B, IMPACT, NAMES)
    assert brief.unverified_numbers("Savings of $4.2M over 18 months", facts) == ["18", "4.2"]
    assert brief.unverified_numbers("They are 5.46 km apart, saving $125K.", facts) == []


def test_no_key_falls_back_to_template(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    out = brief.coordination_brief(O1, A, B, IMPACT, NAMES)
    assert out["source"] == "template" and "Subject:" in out["memo"]


def test_gemini_draft_with_made_up_number_is_rejected(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    import gemini_agent

    class R:
        text = "Subject: Overlap\\nWe could save $9.9M by sharing crews."
    monkeypatch.setattr(gemini_agent, "generate", lambda *a, **k: R())
    out = brief.coordination_brief(O1, A, B, IMPACT, NAMES)
    assert out["source"] == "template" and "9.9" in out["note"]


def test_clean_gemini_draft_is_used_and_cached(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    import gemini_agent
    calls = []

    class R:
        text = "Subject: Jasper - Okatie / McIntosh\\nOur projects are 5.46 km apart; sharing one crew mobilization saves about $125K (planning-level). See DESC p. 9 and GPC p. 262."
    monkeypatch.setattr(gemini_agent, "generate", lambda *a, **k: calls.append(1) or R())
    first = brief.coordination_brief(O1, A, B, IMPACT, NAMES)
    second = brief.coordination_brief(O1, A, B, IMPACT, NAMES)
    assert first["source"] == "gemini" and second["memo"] == first["memo"] and len(calls) == 1
