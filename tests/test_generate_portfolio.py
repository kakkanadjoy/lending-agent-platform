"""Portfolio generator tests — verify the ground-truth-first promise:
the planted truth actually matches the generated data. This is the answer
key checking itself.

Generator tests commit (the portfolio must persist for inspection), so this
module CLEANS UP after itself by regenerating at the end is overkill; instead
we run against the real DB and assert on what generate() produced. Because
generate() clears+rebuilds deterministically, the DB ends in a known state.
"""
import datetime as dt

from db import repository as repo
from synth import generate_portfolio as gen


def test_generate_produces_cast_and_bulk():
    result = gen.generate(bulk=30, seed=42)
    assert result["cast"] == 4
    assert result["bulk"] == 30
    assert result["total_loans"] == 34


def test_planted_truth_matches_data():
    """The core ground-truth-first check: each cast member's stored numbers
    must actually reflect its declared profile."""
    gen.generate(bulk=10, seed=42)
    with repo.connect() as conn:
        clean = repo.get_loan(conn, "LN-DEMO-CLEAN")
        det = repo.get_loan(conn, "LN-DEMO-DETERIORATING")
        comp = repo.get_loan(conn, "LN-DEMO-COMPLIANCE")

    # clean: DSCR comfortably above the 1.20 minimum, no expected exceptions
    assert float(clean["dscr"]) >= 1.20
    assert clean["ground_truth"]["expected_exceptions"] == []
    assert clean["ground_truth"]["deteriorated"] is False

    # deteriorating: DSCR fell below minimum AND dropped year-over-year
    assert float(det["dscr"]) < 1.20
    assert float(det["dscr"]) < float(det["dscr_prior"])
    assert det["ground_truth"]["deteriorated"] is True
    assert "DSCR-MIN" in det["ground_truth"]["expected_exceptions"]

    # compliance: the unwaivable route is recorded, multiple exceptions planted
    assert comp["ground_truth"]["routes_to"] == "compliance"
    assert "INCOME-MISREP" in comp["ground_truth"]["expected_exceptions"]


def test_bulk_expected_exceptions_are_self_consistent():
    """For every bulk loan, the recorded expected_exceptions must match what
    its own numbers imply — the answer key must not lie."""
    gen.generate(bulk=60, seed=7)
    with repo.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT loan_id, dscr, leverage, ground_truth FROM loans "
                        "WHERE ground_truth->>'profile' = 'bulk'")
            rows = cur.fetchall()
    assert rows
    for r in rows:
        expected = set(r["ground_truth"]["expected_exceptions"])
        implied = set()
        if float(r["dscr"]) < 1.20:
            implied.add("DSCR-MIN")
        if float(r["leverage"]) > 4.0:
            implied.add("LEVERAGE-MAX")
        assert expected == implied, f"{r['loan_id']}: {expected} != {implied}"


def test_maturities_are_spread():
    """Revolver maturities should scatter, so the renewal queue has flow —
    not all clustered on one date."""
    gen.generate(bulk=80, seed=42)
    with repo.connect() as conn:
        soon = repo.loans_maturing_within(conn, 90)
        all_rev = repo.loans_maturing_within(conn, 400)
    # some due within 90 days, but not ALL of them (spread, not clustered)
    assert 0 < len(soon) < len(all_rev)


def test_regeneration_is_reproducible():
    """Same seed -> same portfolio size; the disposable-database principle."""
    a = gen.generate(bulk=25, seed=99)
    b = gen.generate(bulk=25, seed=99)
    assert a == b
