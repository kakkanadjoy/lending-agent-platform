"""The renewal workflow graph.

Wires the nodes into a LangGraph. The flow:

    gather -> rules -> (branch on routing)
        compliance_review  -> compliance_hold -> END
        otherwise          -> score -> retrieve -> draft -> END

The branch is the rules engine's routing decision becoming control flow: a
misrepresentation finding takes the compliance path and never drafts a normal
review. Everything else proceeds to score, retrieve citations, and draft.

Step 1 has no human gate yet — the graph runs start to finish. The interrupt
and checkpointing come in Step 2.
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agents.nodes import (compliance_hold, draft_review, gather_facts,
                          retrieve_policy, run_rules, score_ews)
from agents.state import RenewalState


def _route_after_rules(state: RenewalState) -> str:
    """Conditional edge: compliance findings divert; everything else proceeds."""
    if state.get("routing") == "compliance_review":
        return "compliance"
    return "proceed"


def build_renewal_graph():
    g = StateGraph(RenewalState)

    g.add_node("gather", gather_facts)
    g.add_node("rules", run_rules)
    g.add_node("score", score_ews)
    g.add_node("retrieve", retrieve_policy)
    g.add_node("draft", draft_review)
    g.add_node("compliance", compliance_hold)

    g.add_edge(START, "gather")
    g.add_edge("gather", "rules")
    g.add_conditional_edges("rules", _route_after_rules,
                            {"compliance": "compliance", "proceed": "score"})
    g.add_edge("score", "retrieve")
    g.add_edge("retrieve", "draft")
    g.add_edge("draft", END)
    g.add_edge("compliance", END)

    return g.compile()


def run_renewal(loan_id: str) -> RenewalState:
    """Convenience: run the whole graph for one loan and return final state."""
    graph = build_renewal_graph()
    return graph.invoke({"loan_id": loan_id, "trail": []})
