"""API + metrics tests.

The FastAPI service is tested with TestClient and stubbed agent calls, so these
run without a database or models. They confirm the endpoints work and that
metrics are recorded and exposed in Prometheus format.
"""
import sys
import types

import pytest


@pytest.fixture
def client(monkeypatch):
    # stub the agent runner so the API tests don't pull the whole graph/db
    runner = types.ModuleType("agents.runner")
    runner.start_renewal = lambda lid, tid=None: (
        tid or lid,
        {"routing": "clean", "review_text": "review for " + lid,
         "draft_flags": [], "trail": ["gathered", "drafted (stub)"]},
        True,
    )
    runner.resume_renewal = lambda tid, d: {"human_decision": d,
                                            "trail": ["finalized: " + d]}
    monkeypatch.setitem(sys.modules, "agents.runner", runner)
    monkeypatch.setitem(sys.modules, "agents", types.ModuleType("agents"))

    from fastapi.testclient import TestClient
    import importlib
    import api.main
    importlib.reload(api.main)
    return TestClient(api.main.app)


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_start_returns_paused_state(client):
    r = client.post("/renewals/start", json={"loan_id": "LN-DEMO-CLEAN"})
    assert r.status_code == 200
    body = r.json()
    assert body["paused"] is True
    assert "review for LN-DEMO-CLEAN" in body["review_text"]


def test_resume_rejects_bad_decision(client):
    r = client.post("/renewals/resume",
                    json={"thread_id": "t1", "decision": "maybe"})
    assert r.status_code == 400


def test_resume_accepts_approve(client):
    r = client.post("/renewals/resume",
                    json={"thread_id": "t1", "decision": "approve"})
    assert r.status_code == 200
    assert r.json()["human_decision"] == "approve"


def test_metrics_endpoint_exposes_prometheus_format(client):
    # generate some activity first
    client.post("/renewals/start", json={"loan_id": "LN-1"})
    m = client.get("/metrics")
    assert m.status_code == 200
    assert "renewals_started_total" in m.text


def test_llm_cost_estimate():
    from api import metrics
    before = metrics.llm_cost_cents._value.get()
    metrics.record_llm_usage(1000, 1000)   # 1k prompt + 1k completion
    after = metrics.llm_cost_cents._value.get()
    # (1000/1000*0.015 + 1000/1000*0.060) * 100 = 7.5 cents
    assert round(after - before, 2) == 7.5
