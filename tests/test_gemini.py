"""Gemini quota handling and caching (fake client, no network)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gemini_agent as ga  # noqa: E402


class QuotaError(Exception):
    def __init__(self, msg, code=429):
        super().__init__(msg)
        self.code = code


class FakeModels:
    def __init__(self, behavior):
        self.behavior, self.calls = behavior, []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        result = self.behavior[model]
        if isinstance(result, Exception):
            raise result
        return result


class FakeClient:
    def __init__(self, behavior):
        self.models = FakeModels(behavior)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    ga._exhausted.clear()
    monkeypatch.delenv("GEMINI_MODELS", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(ga.time, "sleep", lambda s: None)


def test_daily_quota_moves_to_next_model_and_remembers():
    daily = QuotaError("429 RESOURCE_EXHAUSTED quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    client = FakeClient({"gemini-flash-lite-latest": daily, "gemini-flash-latest": "ok"})
    assert ga.generate(client, "hi", None) == "ok"
    assert ga.generate(client, "hi again", None) == "ok"
    # the exhausted model is not retried on the second call
    assert client.models.calls == ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-flash-latest"]


def test_all_models_exhausted_gives_clear_error():
    daily = QuotaError("PerDay quota exceeded")
    client = FakeClient({m: daily for m in ga.DEFAULT_MODELS})
    with pytest.raises(RuntimeError, match="out of free quota for today"):
        ga.generate(client, "hi", None)


def test_per_minute_limit_waits_and_retries_same_model():
    class Flaky(FakeModels):
        def generate_content(self, model, contents, config):
            self.calls.append(model)
            if len(self.calls) == 1:
                raise QuotaError("429 per minute. Please retry in 3.5s.")
            return "ok"
    client = FakeClient({})
    client.models = Flaky({})
    assert ga.generate(client, "hi", None) == "ok"
    assert client.models.calls == ["gemini-flash-lite-latest"] * 2


def test_split_endpoints_cache_skips_known_names(tmp_path, monkeypatch):
    agent = ga.GeminiAgent(api_key="test", cache_dir=tmp_path, request_gap=0)
    sent = []

    def fake_generate(prompt, schema):
        sent.append(prompt)
        return [ga.Endpoints(index=0, endpoint_a="EVANS PRIMARY", endpoint_b="THOMSON PRIMARY")]
    monkeypatch.setattr(agent, "_generate", fake_generate)

    name = "EVANS PRIMARY - THOMSON PRIMARY 115KV REBUILD"
    agent.split_endpoints([{"name": name}])
    again = agent.split_endpoints([{"name": name}])      # second run: served from cache
    assert len(sent) == 1
    assert (again[0]["endpoint_a"], again[0]["endpoint_b"]) == ("EVANS PRIMARY", "THOMSON PRIMARY")
