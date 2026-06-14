"""Renewal graph tests (Step 1 — no interrupt yet).

These run the full graph against the live database and real modules, so they
need the portfolio generated and the EWS model available. They verify the
graph flows, the state accumulates, and — the key behavior — the compliance
branch diverts misrepresentation cases away from normal drafting.
"""
import pytest

from agents.renewal_graph import run_renewal


@pytest.mark.slow
def test_clean_loan_proceeds_through_draft():
    state = run_renewal("LN-DEMO-CLEAN")
    assert state["routing"] == "clean"
    # took the proceed path: scored, retrieved, drafted
    assert "ews_score" in state
    assert "review_text" in state
    assert "Annual renewal review" in state["review_text"]
    # the trail records each node it passed through
    assert any("drafted review" in t for t in state["trail"])
    assert not any("compliance hold" in t for t in state["trail"])


@pytest.mark.slow
def test_compliance_loan_diverts_to_hold():
    state = run_renewal("LN-DEMO-COMPLIANCE")
    assert state["routing"] == "compliance_review"
    # took the bright-line path: referred, not drafted
    assert "Referred to compliance" in state["review_text"]
    assert any("compliance hold" in t for t in state["trail"])
    # it should NOT have drafted a normal review or scored
    assert not any("drafted review" in t for t in state["trail"])


@pytest.mark.slow
def test_state_accumulates_through_nodes():
    state = run_renewal("LN-DEMO-DETERIORATING")
    # by the end the state holds the whole case
    assert state["loan"]["loan_id"] == "LN-DEMO-DETERIORATING"
    assert "exceptions" in state
    assert "ews_score" in state
    assert isinstance(state["trail"], list) and len(state["trail"]) >= 4
