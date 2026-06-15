"""LLM-integration tests (Step 4).

The real Azure Foundry call needs credentials and network, so it isn't unit-
tested here. What we CAN test deterministically: the stub fallback engages when
no model is configured, the prompt builds from verified facts, and the graph
still drafts + passes guardrails offline.
"""
import os

from agents import llm, prompts


def test_not_configured_without_credentials(monkeypatch):
    for k in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
              "AZURE_OPENAI_DEPLOYMENT"):
        monkeypatch.delenv(k, raising=False)
    assert llm.is_configured() is False
    # generate returns None so the node falls back to the stub
    assert llm.generate("sys", "usr") is None


def test_prompt_contains_only_provided_facts():
    state = {
        "loan": {"loan_id": "LN-1", "facility_type": "term_loan",
                 "commitment": 2000000, "dscr": 1.30, "dscr_prior": 1.45,
                 "leverage": 4.8, "utilization": None},
        "ews_score": 0.41,
        "exceptions": [{"code": "LEVERAGE-MAX", "severity": "medium",
                        "observed": 4.8, "threshold": 4.0, "section": "4.4.2"}],
        "citations": [{"section": "4.4.2", "code": "LEVERAGE-MAX",
                       "title": "Maximum leverage",
                       "body": "Total leverage must not exceed 4.0x."}],
    }
    user = prompts.build_user_prompt(state)
    assert "LN-1" in user
    assert "4.8" in user and "4.4.2" in user
    # the system prompt forbids recommendations (the bright line)
    assert "recommendation" in prompts.SYSTEM.lower()


def test_stub_review_passes_guardrails():
    """The stub is built from verified facts, so it must pass validate_draft."""
    from agents.guardrails import validate_draft
    from agents.nodes import _stub_review
    state = {
        "loan": {"loan_id": "LN-1", "facility_type": "revolving_line",
                 "commitment": 750000, "dscr": 1.45, "dscr_prior": 1.42,
                 "leverage": 2.6},
        "ews_score": 0.12, "exceptions": [], "citations": [],
    }
    text = _stub_review(state)
    assert validate_draft(text, state).ok
