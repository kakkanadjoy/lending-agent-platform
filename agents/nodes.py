"""Nodes for the renewal graph.

Each node is a function: state in, state out (it returns the keys it wants to
add). They're deliberately thin — the real work was built in earlier phases
(the rules engine, the EWS, RAG). A node's job is to call the right module
and drop the result on the shared state.

The draft node is a STUB for now: it assembles a templated review from the
verified facts. Phase 3 Step 4 swaps it for a real LLM call behind the same
interface, so nothing else in the graph changes.
"""
from __future__ import annotations

from db import repository as repo
from ews.score import score_loan
from rules import engine

from agents.state import RenewalState


def _log(state: RenewalState, msg: str) -> list[str]:
    return state.get("trail", []) + [msg]


def gather_facts(state: RenewalState) -> RenewalState:
    """Load the loan and its financials onto the state."""
    with repo.connect() as conn:
        loan = repo.get_loan(conn, state["loan_id"])
    if loan is None:
        raise ValueError(f"loan not found: {state['loan_id']}")
    return {"loan": loan, "trail": _log(state, f"gathered facts for {loan['loan_id']}")}


def run_rules(state: RenewalState) -> RenewalState:
    """Evaluate policy. The verdict's routing later steers the graph."""
    verdict = engine.evaluate(state["loan"])
    exceptions = [
        {"code": e.code, "title": e.title, "section": e.section,
         "severity": e.severity, "observed": e.observed,
         "threshold": e.threshold, "waiver_authority": e.waiver_authority,
         "routes_to": e.routes_to}
        for e in verdict.exceptions
    ]
    return {
        "exceptions": exceptions,
        "routing": verdict.routing,
        "minimum_authority": verdict.minimum_authority,
        "trail": _log(state, f"rules: {verdict.routing} ({len(exceptions)} exceptions)"),
    }


def score_ews(state: RenewalState) -> RenewalState:
    """Attach the deterioration score that orders the renewal queue."""
    score = score_loan(state["loan"])
    return {"ews_score": score, "trail": _log(state, f"ews score {score:.3f}")}


def retrieve_policy(state: RenewalState) -> RenewalState:
    """Pull the policy sections behind each fired exception, for citation.
    Imported lazily so the heavy RAG models only load when this node runs."""
    from rag.search import search

    citations: list[dict] = []
    seen = set()
    for exc in state.get("exceptions", []):
        hits = search(exc["title"], k=1)
        for h in hits:
            if h.section not in seen:
                seen.add(h.section)
                citations.append({"code": h.code, "section": h.section,
                                  "title": h.title, "body": h.body})
    return {"citations": citations,
            "trail": _log(state, f"retrieved {len(citations)} citations")}


def draft_review(state: RenewalState) -> RenewalState:
    """STUB: assemble a templated review from verified facts. Swapped for a
    real LLM call in Step 4 — same inputs, same output key."""
    loan = state["loan"]
    lines = [
        f"Annual renewal review for {loan['loan_id']}.",
        f"Facility: {loan['facility_type']}, commitment {loan['commitment']}.",
        f"DSCR {loan.get('dscr')} (prior {loan.get('dscr_prior')}), "
        f"leverage {loan.get('leverage')}.",
        f"Early-warning score: {state.get('ews_score', 0):.2f}.",
    ]
    if state.get("exceptions"):
        lines.append("Policy exceptions noted:")
        for exc in state["exceptions"]:
            lines.append(f"  - {exc['code']} ({exc['severity']}): observed "
                         f"{exc['observed']} vs threshold {exc['threshold']}, "
                         f"per section {exc['section']}.")
    else:
        lines.append("No policy exceptions. Credit within guidelines.")
    lines.append("Recommendation: [to be completed by the underwriter].")
    return {"review_text": "\n".join(lines),
            "trail": _log(state, "drafted review (stub)")}


def compliance_hold(state: RenewalState) -> RenewalState:
    """The bright-line branch: a misrepresentation finding routes here instead
    of drafting a normal review. The case goes to the compliance queue."""
    return {"review_text": "Referred to compliance: suspected misrepresentation. "
                           "Not waivable; pending compliance officer review.",
            "trail": _log(state, "routed to compliance hold")}
