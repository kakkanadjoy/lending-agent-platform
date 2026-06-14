"""Run a renewal with a human gate that survives across sessions.

The graph is compiled with a POSTGRES CHECKPOINTER and an interrupt before the
`finalize` node. That gives two halves a real workflow needs:

  start_renewal(loan_id)  -> runs gather..draft, then PAUSES at the gate.
                             The full state is saved to postgres under a
                             thread_id. The process can now end.
  resume_renewal(thread_id, decision)
                          -> opens a FRESH graph + connection (the original
                             process may be long gone), loads the saved state
                             from postgres, folds in the human's decision, and
                             runs `finalize` to completion.

This is the difference between a script (runs once, forgets) and an agent
(pauses, persists, resumes). LangGraph manages its own checkpoint tables in
the same postgres everything else uses; the thread_id is the renewal's handle.
"""
from __future__ import annotations

import os

from langgraph.checkpoint.postgres import PostgresSaver

from agents.renewal_graph import _build_builder

DB_URI = os.environ.get("DATABASE_URL",
                        "postgresql://lending:lending@localhost:5432/lending")


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def start_renewal(loan_id: str, thread_id: str | None = None):
    """Run up to the human gate. Returns (thread_id, paused_state).

    For a compliance case there is no gate (it ends at compliance_hold), so the
    run simply completes and `paused` is False.
    """
    thread_id = thread_id or loan_id
    with PostgresSaver.from_conn_string(DB_URI) as cp:
        cp.setup()  # idempotent: creates the checkpoint tables on first use
        graph = _build_builder().compile(checkpointer=cp,
                                         interrupt_before=["finalize"])
        state = graph.invoke({"loan_id": loan_id, "trail": []},
                             _config(thread_id))
        # If the next node is finalize, we paused at the gate.
        snapshot = graph.get_state(_config(thread_id))
        paused = "finalize" in snapshot.next
    return thread_id, state, paused


def resume_renewal(thread_id: str, decision: str):
    """Resume a paused renewal with the human's decision and finish it.

    Opens a brand-new graph and connection — the saved checkpoint in postgres
    is the only link to the earlier run, which proves the workflow survives the
    original process ending.
    """
    with PostgresSaver.from_conn_string(DB_URI) as cp:
        graph = _build_builder().compile(checkpointer=cp,
                                         interrupt_before=["finalize"])
        graph.update_state(_config(thread_id), {"human_decision": decision})
        state = graph.invoke(None, _config(thread_id))
    return state
