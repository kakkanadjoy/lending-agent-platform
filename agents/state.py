"""State for the renewal workflow.

One object flows through every node in the graph. Each node reads what it
needs and writes its result back, so by the end the state holds the whole
case: the loan, the rules verdict, the risk score, the policy citations, the
drafted review, and (once a human acts) their decision.

Keeping everything on this one object is deliberate — no node reaches back
into the database for something an earlier node already computed. The state
IS the working memory of the run.
"""
from __future__ import annotations

from typing import Any, Optional

from typing_extensions import TypedDict


class RenewalState(TypedDict, total=False):
    # set at the start
    loan_id: str

    # filled by gather_facts
    loan: dict[str, Any]

    # filled by run_rules
    exceptions: list[dict[str, Any]]
    routing: str                      # clean | exception_review | compliance_review
    minimum_authority: Optional[str]

    # filled by score_ews
    ews_score: float

    # filled by retrieve_policy
    citations: list[dict[str, Any]]   # the policy sections behind the exceptions

    # filled by draft_review (stub for now, LLM later)
    review_text: str

    # filled when a human acts at the gate
    human_decision: Optional[str]     # approve | decline | None while pending

    # a running log of what each node did, handy for the activity feed/trace
    trail: list[str]
