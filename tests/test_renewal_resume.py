"""Pause-and-resume tests (Step 2).

These exercise the marquee capability: a renewal runs to the human gate,
persists its state to postgres, and resumes — in a fresh graph and connection,
simulating the original process ending — with the human's decision folded in.

Marked slow: they need postgres (the checkpointer) and the live modules. Each
test uses a unique thread_id so re-runs don't collide with old checkpoints.
"""
import uuid

import pytest

from agents.runner import resume_renewal, start_renewal


@pytest.mark.slow
def test_renewal_pauses_at_gate_then_resumes():
    tid = f"test-{uuid.uuid4()}"
    thread_id, state, paused = start_renewal("LN-DEMO-CLEAN", thread_id=tid)

    # paused at the gate: drafted, but not finalized
    assert paused is True
    assert "review_text" in state
    assert not any("finalized" in t for t in state["trail"])

    # resume in a fresh graph/connection (process-death simulation) and approve
    final = resume_renewal(thread_id, "approve")
    assert final["human_decision"] == "approve"
    assert any("finalized" in t for t in final["trail"])
    assert "approved by reviewer" in final["trail"][-1]


@pytest.mark.slow
def test_decline_decision_is_recorded():
    tid = f"test-{uuid.uuid4()}"
    thread_id, _, paused = start_renewal("LN-DEMO-CLEAN", thread_id=tid)
    assert paused is True
    final = resume_renewal(thread_id, "decline")
    assert "declined by reviewer" in final["trail"][-1]


@pytest.mark.slow
def test_compliance_case_has_no_gate():
    """A misrepresentation case ends at compliance_hold — no human gate, so the
    run completes without pausing."""
    tid = f"test-{uuid.uuid4()}"
    _, state, paused = start_renewal("LN-DEMO-COMPLIANCE", thread_id=tid)
    assert paused is False
    assert "Referred to compliance" in state["review_text"]
