"""The renewal workflow graph.

Wires the nodes into a LangGraph. The flow:

    gather -> rules -> (branch on routing)
        compliance_review  -> compliance_hold -> END
        otherwise          -> score -> retrieve -> draft -> finalize -> END

The branch is the rules engine's routing decision becoming control flow: a
misrepresentation finding takes the compliance path and never drafts a normal
review. Everything else proceeds to score, retrieve, draft, and finalize.

`_build_builder()` returns the uncompiled graph so it can be compiled two ways:
  - plainly (no checkpointer) for a straight-through run, and
  - with a checkpointer + an interrupt before `finalize` for the human gate
    (see agents/runner.py).
The human gate sits between `draft` and `finalize`: the graph pauses after
drafting, waits for a human decision, then finalizes.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.nodes import (compliance_hold, draft_review, finalize,
                          gather_facts, retrieve_policy, run_rules, score_ews)
from agents.state import RenewalState


def _route_after_rules(state: RenewalState) -> str:
    """Conditional edge: compliance findings divert; everything else proceeds."""
    if state.get("routing") == "compliance_review":
        return "compliance"
    return "proceed"


def _build_builder() -> StateGraph:
    """The uncompiled graph. Shared by the plain and checkpointed compiles."""
    g = StateGraph(RenewalState)

    g.add_node("gather", gather_facts)
    g.add_node("rules", run_rules)
    g.add_node("score", score_ews)
    g.add_node("retrieve", retrieve_policy)
    g.add_node("draft", draft_review)
    g.add_node("finalize", finalize)
    g.add_node("compliance", compliance_hold)

    g.add_edge(START, "gather")
    g.add_edge("gather", "rules")
    g.add_conditional_edges("rules", _route_after_rules,
                            {"compliance": "compliance", "proceed": "score"})
    g.add_edge("score", "retrieve")
    g.add_edge("retrieve", "draft")
    g.add_edge("draft", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("compliance", END)
    return g


def build_renewal_graph():
    """Compile with no checkpointer: runs start to finish in one call."""
    return _build_builder().compile()


def run_renewal(loan_id: str) -> RenewalState:
    """Convenience: run the whole graph for one loan and return final state."""
    graph = build_renewal_graph()
    return graph.invoke({"loan_id": loan_id, "trail": []})
