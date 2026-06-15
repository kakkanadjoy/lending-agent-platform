"""The FastAPI service — the platform's HTTP face.

It does three jobs:
  1. Wraps the agent: start a renewal (runs to the human gate), resume it
     (with a decision). This is what the React desk will call in Phase 5.
  2. Serves the renewal queue, ordered by EWS deterioration score.
  3. Exposes /metrics for Prometheus to scrape (the pull model).

Metrics are recorded as the agent runs — throughput, node latency, LLM
usage/cost, guardrail flags, queue depth — so Grafana can draw the live view.

Run locally:
    uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from starlette.responses import Response

from agents.runner import resume_renewal, start_renewal
from api import metrics

try:
    from dotenv import load_dotenv
    load_dotenv()                      # pick up Azure creds if a .env exists
except Exception:
    pass

app = FastAPI(title="Lending Agent Platform", version="0.1.0")


# ── request/response models ───────────────────────────────────────────────
class StartRequest(BaseModel):
    loan_id: str
    thread_id: str | None = None


class ResumeRequest(BaseModel):
    thread_id: str
    decision: str                      # approve | decline


# ── agent endpoints ───────────────────────────────────────────────────────
@app.post("/renewals/start")
def start(req: StartRequest):
    metrics.renewals_started.inc()
    t0 = time.perf_counter()
    thread_id, state, paused = start_renewal(req.loan_id, req.thread_id)
    metrics.node_duration.labels(node="full_start").observe(time.perf_counter() - t0)

    # count guardrail flags by kind
    for finding in state.get("draft_flags", []):
        metrics.guardrail_flags.labels(kind=metrics.classify_flag(finding)).inc()

    if not paused:                     # compliance path completes immediately
        metrics.renewals_completed.labels(outcome="compliance").inc()

    return {"thread_id": thread_id, "paused": paused,
            "routing": state.get("routing"),
            "review_text": state.get("review_text"),
            "draft_flags": state.get("draft_flags", []),
            "trail": state.get("trail", [])}


@app.post("/renewals/resume")
def resume(req: ResumeRequest):
    if req.decision not in ("approve", "decline"):
        raise HTTPException(400, "decision must be approve or decline")
    state = resume_renewal(req.thread_id, req.decision)
    metrics.renewals_completed.labels(outcome=req.decision).inc()
    return {"human_decision": state.get("human_decision"),
            "trail": state.get("trail", [])}


# ── queue endpoint (EWS-ordered) ──────────────────────────────────────────
@app.get("/queue")
def queue(limit: int = 20):
    from db import repository as repo
    from ews.score import score_many

    with repo.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT loan_id, facility_type, dscr, dscr_prior, "
                        "leverage, utilization, ground_truth FROM loans")
            loans = cur.fetchall()
    ranked = score_many(loans)[:limit]
    metrics.queue_depth.set(len(loans))
    return [{"loan_id": lid, "ews_score": round(score, 4)}
            for lid, score in ranked]


# ── health + metrics ──────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def prometheus_metrics():
    """The endpoint Prometheus scrapes (pull model)."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
