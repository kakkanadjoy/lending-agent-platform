"""Metrics for the platform — what's worth watching in an AI lending system.

Prometheus uses a PULL model: it scrapes a /metrics endpoint on a schedule. We
define the instruments here and let the service expose them. The choice of
instrument type matters:

  Counter   — only goes up (totals): renewals started, LLM calls, guardrail
              flags. You graph the RATE of a counter ("flags per minute").
  Gauge     — goes up and down (current level): renewal queue depth, unprocessed
              outbox events. You graph the VALUE.
  Histogram — distribution of measurements (durations, token counts): node
              latency, LLM tokens per call. You graph quantiles (p50, p95).

The metrics chosen are the ones a real team actually watches for an AI system:
throughput, latency, LLM COST, and the guardrail FLAG RATE (is the model
misbehaving?).
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── throughput ────────────────────────────────────────────────────────────
renewals_started = Counter(
    "renewals_started_total", "Renewal workflows started")
renewals_completed = Counter(
    "renewals_completed_total", "Renewal workflows finished",
    ["outcome"])               # approve | decline | compliance

# ── latency ───────────────────────────────────────────────────────────────
node_duration = Histogram(
    "renewal_node_duration_seconds", "Time spent in each agent node",
    ["node"], buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10))

# ── LLM cost / usage ──────────────────────────────────────────────────────
llm_calls = Counter(
    "llm_calls_total", "LLM generation calls", ["source"])  # llm | stub
llm_tokens = Counter(
    "llm_tokens_total", "Tokens consumed by the LLM", ["kind"])  # prompt|completion
llm_cost_cents = Counter(
    "llm_cost_cents_total", "Estimated LLM spend in cents")

# ── safety ────────────────────────────────────────────────────────────────
guardrail_flags = Counter(
    "guardrail_flags_total", "Draft guardrail findings", ["kind"])
# kind: unverified_number | bad_citation | out_of_scope | injection

# ── live levels (gauges) ──────────────────────────────────────────────────
queue_depth = Gauge(
    "renewal_queue_depth", "Loans awaiting review, by EWS priority")
outbox_unprocessed = Gauge(
    "outbox_unprocessed_events", "Events in the outbox not yet handled")


# rough price table for the deployment (USD per 1K tokens) -> cents estimate
_PRICE_PER_1K = {"prompt": 0.015, "completion": 0.060}  # gpt-4.1-mini-ish


def record_llm_usage(prompt_tokens: int, completion_tokens: int) -> None:
    """Record token counts and a cents estimate from one LLM call."""
    llm_tokens.labels(kind="prompt").inc(prompt_tokens)
    llm_tokens.labels(kind="completion").inc(completion_tokens)
    cents = (prompt_tokens / 1000 * _PRICE_PER_1K["prompt"]
             + completion_tokens / 1000 * _PRICE_PER_1K["completion"]) * 100
    llm_cost_cents.inc(cents)


def classify_flag(finding: str) -> str:
    """Map a guardrail finding string to a metric label."""
    f = finding.lower()
    if "unverified number" in f:
        return "unverified_number"
    if "citation" in f:
        return "bad_citation"
    if "out-of-scope" in f:
        return "out_of_scope"
    if "injection" in f:
        return "injection"
    return "other"
