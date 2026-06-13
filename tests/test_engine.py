"""Rules engine tests.

Two kinds. First, pure-logic checks that need no database — the engine is
just functions over dicts. Second, the payoff of Phase 0's groundwork: run
the engine across the whole generated portfolio and confirm its verdict for
every loan matches that loan's planted ground_truth. If the engine and the
answer key ever disagree, this catches it across all 124 loans at once.
"""
from db import repository as repo
from rules import engine
from synth import generate_portfolio as gen


# ── pure logic, no database ────────────────────────────────────────────────

def test_clean_loan_has_no_exceptions():
    v = engine.evaluate(dict(loan_id="x", dscr=1.5, leverage=2.0,
                             utilization=0.3, income_discrepancy_pct=0.0))
    assert v.is_clean
    assert v.routing == "clean"
    assert v.minimum_authority is None


def test_dscr_below_minimum_fires_high_severity():
    v = engine.evaluate(dict(loan_id="x", dscr=1.10, leverage=2.0,
                             utilization=0.3, income_discrepancy_pct=0.0))
    assert engine.codes(v) == ["DSCR-MIN"]
    assert v.exceptions[0].severity == "high"
    assert v.exceptions[0].observed == 1.10


def test_misrepresentation_is_unwaivable_and_routes_to_compliance():
    v = engine.evaluate(dict(loan_id="x", dscr=1.5, leverage=2.0,
                             utilization=0.3, income_discrepancy_pct=0.34))
    assert "INCOME-MISREP" in engine.codes(v)
    misrep = next(e for e in v.exceptions if e.code == "INCOME-MISREP")
    assert misrep.waiver_authority == "unwaivable"
    assert v.routes_to_compliance
    assert v.routing == "compliance_review"


def test_severest_exception_leads():
    v = engine.evaluate(dict(loan_id="x", dscr=1.10, leverage=4.5,
                             utilization=0.95, income_discrepancy_pct=0.34))
    # severe (misrep) must sort ahead of high (dscr), medium (leverage), low (util)
    assert v.exceptions[0].code == "INCOME-MISREP"


def test_missing_field_cannot_fire():
    # a term loan has no utilization; that rule simply can't fire, no guessing
    v = engine.evaluate(dict(loan_id="x", dscr=1.5, leverage=2.0,
                             utilization=None, income_discrepancy_pct=0.0))
    assert "UTILIZATION-HIGH" not in engine.codes(v)


# ── the grading run: engine vs the planted answer key ───────────────────────

def test_engine_matches_planted_ground_truth_across_portfolio():
    gen.generate(bulk=120, seed=42)
    mismatches = []
    with repo.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT loan_id, dscr, dscr_prior, leverage, utilization, "
                        "income_discrepancy_pct, ground_truth FROM loans")
            loans = cur.fetchall()

    for loan in loans:
        verdict = engine.evaluate(loan)
        got = engine.codes(verdict)
        expected = sorted(loan["ground_truth"].get("expected_exceptions", []))
        if got != expected:
            mismatches.append((loan["loan_id"], got, expected))

    assert not mismatches, f"engine disagreed with the answer key: {mismatches[:5]}"


def test_compliance_routing_matches_ground_truth():
    gen.generate(bulk=120, seed=42)
    with repo.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT loan_id, dscr, leverage, utilization, "
                        "income_discrepancy_pct, ground_truth FROM loans")
            loans = cur.fetchall()
    for loan in loans:
        verdict = engine.evaluate(loan)
        planted_route = loan["ground_truth"].get("routes_to")
        assert verdict.routes_to_compliance == (planted_route == "compliance"), loan["loan_id"]
