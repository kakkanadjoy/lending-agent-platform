"""Synthetic portfolio generator — ground-truth-first.

Philosophy: we DECIDE each loan's truth, then generate numbers to match, and
record that truth in loans.ground_truth. Downstream code (rules engine, EWS)
is then GRADED against a known answer key rather than guessed at.

Two parts:
  1. A planted cast of named characters with specific, known conditions
     (clean / deteriorating / policy-exception / misrepresentation).
  2. A reproducible bulk of "normal" loans (fixed seed) so the portfolio
     feels real and the EWS has enough rows to train on.

Run from the project root (schema already applied):
    python -m synth.generate_portfolio            # default size
    python -m synth.generate_portfolio --bulk 120 --seed 42

Idempotent-ish: it clears the three tables first, so re-running yields the
same portfolio (disposable-database principle).
"""
from __future__ import annotations

import argparse
import datetime as dt
import random

from db import repository as repo

# Policy thresholds the planted truth is defined against (these mirror what
# the Phase 1 rules engine will enforce; kept here so the cast is meaningful).
DSCR_MIN = 1.20
LEVERAGE_MAX = 4.0
UTILIZATION_MAX = 0.90
INCOME_DISCREPANCY_COMPLIANCE = 0.25

INDUSTRIES = [  # (naics, label)
    ("423840", "industrial supplies distributor"),
    ("238220", "plumbing & HVAC contractor"),
    ("722511", "full-service restaurant group"),
    ("621111", "physician practice"),
    ("332710", "machine shop"),
    ("541330", "engineering services firm"),
]
DOC_TYPES_REVOLVER = ["business_tax_return", "financial_statement",
                      "debt_schedule", "ar_ap_aging", "guarantor_pfs"]


def _clear(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM events")
        cur.execute("DELETE FROM documents")
        cur.execute("DELETE FROM loans")
        cur.execute("DELETE FROM borrowers")


def _spread_maturity(rng: random.Random, today: dt.date) -> dt.date:
    """Scatter revolver maturities across the next ~year so the renewal queue
    always has a natural flow of work (some near their T-90 tickler)."""
    return today + dt.timedelta(days=rng.randint(15, 360))


def _make_borrower_with_guarantor(conn, rng, idx) -> tuple[str, str]:
    naics, label = rng.choice(INDUSTRIES)
    rev = rng.randint(1_500_000, 9_000_000)
    bid = f"BRW-{idx:05d}"
    repo.create_borrower(conn, bid, f"{label.title()} {idx}", rng.choice(["llc", "s_corp", "c_corp"]),
                         naics_code=naics, annual_revenue=rev)
    gid = f"BRW-{idx:05d}-G"
    repo.create_borrower(conn, gid, f"Owner of {bid}", "individual",
                         is_guarantor=True, guarantees_for=bid)
    return bid, gid


def _docs_for(conn, loan_id, cycle, year, received_fraction, rng):
    for i, dt_ in enumerate(DOC_TYPES_REVOLVER):
        status = "received" if rng.random() < received_fraction else "requested"
        repo.create_document(conn, f"{loan_id}-{cycle}-{i}", loan_id, cycle, dt_,
                            fiscal_year=year, status=status)


# ── the planted cast ──────────────────────────────────────────────────────

def _plant_cast(conn, today):
    """Four named loans with known truth — the answer key & demo characters."""
    rng = random.Random(0)

    # 1) CLEAN revolver — healthy, sails through, EWS should stay calm.
    b, _ = _make_borrower_with_guarantor(conn, rng, 1001)
    repo.create_loan(conn, "LN-DEMO-CLEAN", b, "revolving_line", 750_000,
                     outstanding=300_000, maturity_date=str(today + dt.timedelta(days=75)),
                     status="active", risk_rating=4)
    repo.upsert_loan_financials(conn, "LN-DEMO-CLEAN",
        dscr=1.45, dscr_prior=1.42, leverage=2.6, utilization=0.40,
        ground_truth={"profile": "clean", "expected_exceptions": [],
                      "deteriorated": False})
    _docs_for(conn, "LN-DEMO-CLEAN", "renewal-2026", 2025, 1.0, rng)

    # 2) DETERIORATING — DSCR slipped below minimum YoY; EWS should flag; one
    #    waivable policy exception (DSCR).
    b, _ = _make_borrower_with_guarantor(conn, rng, 1002)
    repo.create_loan(conn, "LN-DEMO-DETERIORATING", b, "revolving_line", 1_000_000,
                     outstanding=910_000, maturity_date=str(today + dt.timedelta(days=60)),
                     status="active", risk_rating=6)
    repo.upsert_loan_financials(conn, "LN-DEMO-DETERIORATING",
        dscr=1.12, dscr_prior=1.38, leverage=3.4, utilization=0.91,
        ground_truth={"profile": "deteriorating",
                      "expected_exceptions": ["DSCR-MIN", "UTILIZATION-HIGH"],
                      "deteriorated": True})
    _docs_for(conn, "LN-DEMO-DETERIORATING", "renewal-2026", 2025, 0.6, rng)

    # 3) POLICY EXCEPTION — leverage over the cap (waivable, higher authority).
    b, _ = _make_borrower_with_guarantor(conn, rng, 1003)
    repo.create_loan(conn, "LN-DEMO-LEVERAGE", b, "term_loan", 2_200_000,
                     outstanding=2_050_000, maturity_date=str(today + dt.timedelta(days=300)),
                     status="active", risk_rating=6)
    repo.upsert_loan_financials(conn, "LN-DEMO-LEVERAGE",
        dscr=1.28, dscr_prior=1.30, leverage=4.8, utilization=None,
        ground_truth={"profile": "leverage_exception", "expected_exceptions": ["LEVERAGE-MAX"],
                      "deteriorated": False})
    _docs_for(conn, "LN-DEMO-LEVERAGE", "review-2026", 2025, 1.0, rng)

    # 4) MISREPRESENTATION — income discrepancy beyond the compliance line;
    #    UNWAIVABLE; must route to compliance.
    b, _ = _make_borrower_with_guarantor(conn, rng, 1004)
    repo.create_loan(conn, "LN-DEMO-COMPLIANCE", b, "revolving_line", 1_250_000,
                     outstanding=1_180_000, maturity_date=str(today + dt.timedelta(days=45)),
                     status="active", risk_rating=8)
    repo.upsert_loan_financials(conn, "LN-DEMO-COMPLIANCE",
        dscr=1.05, dscr_prior=1.20, leverage=4.5, utilization=0.94,
        income_discrepancy_pct=0.34,
        ground_truth={"profile": "misrepresentation",
                      "expected_exceptions": ["DSCR-MIN", "LEVERAGE-MAX", "UTILIZATION-HIGH", "INCOME-MISREP"],
                      "income_discrepancy_pct": 0.34, "deteriorated": True,
                      "routes_to": "compliance"})
    _docs_for(conn, "LN-DEMO-COMPLIANCE", "renewal-2026", 2025, 0.8, rng)

    return 4


# ── the reproducible bulk ───────────────────────────────────────────────────

def _plant_bulk(conn, today, n, seed):
    rng = random.Random(seed)
    for k in range(n):
        idx = 2000 + k
        b, _ = _make_borrower_with_guarantor(conn, rng, idx)
        is_revolver = rng.random() < 0.6
        ftype = "revolving_line" if is_revolver else rng.choice(["term_loan", "owner_occ_cre", "equipment"])
        commitment = rng.choice([250_000, 500_000, 750_000, 1_000_000, 1_500_000, 2_500_000])

        # Decide truth first: is this credit healthy or deteriorating?
        deteriorated = rng.random() < 0.22
        if deteriorated:
            dscr = round(rng.uniform(0.95, 1.22), 3)
            dscr_prior = round(dscr + rng.uniform(0.15, 0.45), 3)
            leverage = round(rng.uniform(3.6, 5.2), 3)
        else:
            dscr = round(rng.uniform(1.25, 2.10), 3)
            dscr_prior = round(dscr + rng.uniform(-0.15, 0.15), 3)
            leverage = round(rng.uniform(1.8, 3.8), 3)

        util = round(rng.uniform(0.2, 0.97), 4) if is_revolver else None

        # Most loans have clean income verification; a small slice carries a
        # discrepancy, and a sliver of those cross the misrepresentation line.
        income_disc = 0.0
        roll = rng.random()
        if roll < 0.06:
            income_disc = round(rng.uniform(0.26, 0.45), 4)   # over the compliance line
        elif roll < 0.18:
            income_disc = round(rng.uniform(0.05, 0.20), 4)   # present but within tolerance

        expected = []
        if dscr < DSCR_MIN:
            expected.append("DSCR-MIN")
        if leverage > LEVERAGE_MAX:
            expected.append("LEVERAGE-MAX")
        if util is not None and util > UTILIZATION_MAX:
            expected.append("UTILIZATION-HIGH")
        if income_disc > INCOME_DISCREPANCY_COMPLIANCE:
            expected.append("INCOME-MISREP")

        loan_id = f"LN-{2026}-{idx:05d}"
        mat = str(_spread_maturity(rng, today)) if is_revolver else str(today + dt.timedelta(days=rng.randint(200, 1400)))
        repo.create_loan(conn, loan_id, b, ftype, commitment,
                         outstanding=int(commitment * rng.uniform(0.3, 0.95)),
                         maturity_date=mat, status="active",
                         risk_rating=rng.randint(3, 8))
        repo.upsert_loan_financials(conn, loan_id,
            dscr=dscr, dscr_prior=dscr_prior, leverage=leverage, utilization=util,
            income_discrepancy_pct=income_disc,
            ground_truth={"profile": "bulk", "expected_exceptions": expected,
                          "deteriorated": deteriorated,
                          "routes_to": "compliance" if "INCOME-MISREP" in expected else None})
        cycle = "renewal-2026" if is_revolver else "review-2026"
        _docs_for(conn, loan_id, cycle, 2025, rng.uniform(0.4, 1.0), rng)
    return n


def generate(bulk: int = 120, seed: int = 42, url: str | None = None) -> dict:
    today = dt.date.today()
    with repo.connect(url) as conn:
        _clear(conn)
        n_cast = _plant_cast(conn, today)
        n_bulk = _plant_bulk(conn, today, bulk, seed)
        conn.commit()
        total = repo.count_loans(conn)
        soon = len(repo.loans_maturing_within(conn, 90))
    return {"cast": n_cast, "bulk": n_bulk, "total_loans": total, "maturing_90d": soon}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bulk", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    result = generate(bulk=args.bulk, seed=args.seed)
    print(f"Portfolio generated: {result['total_loans']} loans "
          f"({result['cast']} cast + {result['bulk']} bulk), "
          f"{result['maturing_90d']} maturing within 90 days.")
