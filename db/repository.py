"""Repository — the single seam for all database access.

Every database operation in the platform goes through a function here; no
other module writes SQL. When the database moves (local -> Azure) or a query
needs tuning, this is the one file that changes.

Design choice: functions take an open `conn` as their first argument rather
than opening their own. This hands transaction control to the caller, which
(1) lets tests wrap everything in a transaction they roll back, leaving no
trace, and (2) lets the worker do 'process event + mark done' atomically.
"""
from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

DEFAULT_URL = "postgresql://lending:lending@localhost:5432/lending"


def connect(url: str | None = None) -> psycopg.Connection:
    """Open a connection. connect_timeout=5 so an unreachable database fails
    fast instead of hanging on a silent socket (project-1 Silent Door lesson).
    rows as dicts so callers get column names, not positional tuples."""
    return psycopg.connect(
        url or os.environ.get("DATABASE_URL", DEFAULT_URL),
        connect_timeout=5,
        row_factory=dict_row,
    )


# ── outbox nerves ─────────────────────────────────────────────────────────

def add_event(conn: psycopg.Connection, event_type: str,
              loan_id: str | None = None, payload: dict | None = None) -> int:
    """Announce that something happened: insert one row into the outbox.
    Returns the new event_id."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (event_type, loan_id, payload) "
            "VALUES (%s, %s, %s) RETURNING event_id",
            (event_type, loan_id, psycopg.types.json.Jsonb(payload or {})),
        )
        return cur.fetchone()["event_id"]


def unprocessed_events(conn: psycopg.Connection, limit: int = 50) -> list[dict[str, Any]]:
    """The worker's heartbeat: oldest unhandled events first. Rides the
    partial index idx_events_unprocessed (WHERE processed_at IS NULL)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id, event_type, loan_id, payload, created_at "
            "FROM events WHERE processed_at IS NULL "
            "ORDER BY created_at, event_id LIMIT %s",
            (limit,),
        )
        return cur.fetchall()


def mark_processed(conn: psycopg.Connection, event_id: int) -> None:
    """Stamp an event handled so the worker won't pick it up again."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE events SET processed_at = now() WHERE event_id = %s",
            (event_id,),
        )


# ── creators (enough for tests and, later, the generator) ─────────────────

def create_borrower(conn: psycopg.Connection, borrower_id: str, legal_name: str,
                    entity_type: str, *, is_guarantor: bool = False,
                    guarantees_for: str | None = None, naics_code: str | None = None,
                    annual_revenue: float | None = None) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO borrowers (borrower_id, legal_name, entity_type, "
            "is_guarantor, guarantees_for, naics_code, annual_revenue) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING borrower_id",
            (borrower_id, legal_name, entity_type, is_guarantor,
             guarantees_for, naics_code, annual_revenue),
        )
        return cur.fetchone()["borrower_id"]


def create_loan(conn: psycopg.Connection, loan_id: str, borrower_id: str,
               facility_type: str, commitment: float, *,
               outstanding: float = 0, maturity_date: str | None = None,
               status: str = "active", risk_rating: int | None = None) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO loans (loan_id, borrower_id, facility_type, commitment, "
            "outstanding, maturity_date, status, risk_rating) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING loan_id",
            (loan_id, borrower_id, facility_type, commitment, outstanding,
             maturity_date, status, risk_rating),
        )
        return cur.fetchone()["loan_id"]


def get_loan(conn: psycopg.Connection, loan_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM loans WHERE loan_id = %s", (loan_id,))
        return cur.fetchone()


def upsert_loan_financials(conn: psycopg.Connection, loan_id: str, *,
                          dscr: float | None = None, dscr_prior: float | None = None,
                          leverage: float | None = None, utilization: float | None = None,
                          ground_truth: dict | None = None) -> None:
    """Attach headline financials and the planted ground truth to a loan.
    Separate from create_loan so the core insert stays simple."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE loans SET dscr=%s, dscr_prior=%s, leverage=%s, utilization=%s, "
            "ground_truth=%s WHERE loan_id=%s",
            (dscr, dscr_prior, leverage, utilization,
             psycopg.types.json.Jsonb(ground_truth or {}), loan_id),
        )


def create_document(conn: psycopg.Connection, document_id: str, loan_id: str,
                   cycle: str, doc_type: str, *, fiscal_year: int | None = None,
                   status: str = "requested") -> str:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (document_id, loan_id, cycle, doc_type, "
            "fiscal_year, status) VALUES (%s, %s, %s, %s, %s, %s) "
            "RETURNING document_id",
            (document_id, loan_id, cycle, doc_type, fiscal_year, status),
        )
        return cur.fetchone()["document_id"]


def count_loans(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM loans")
        return cur.fetchone()["n"]


def loans_maturing_within(conn: psycopg.Connection, days: int) -> list[dict[str, Any]]:
    """Revolvers whose maturity falls within `days` of today — the tickler's
    future query, useful now for verifying the maturity spread."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT loan_id, maturity_date FROM loans "
            "WHERE facility_type = 'revolving_line' AND maturity_date IS NOT NULL "
            "AND maturity_date <= (CURRENT_DATE + make_interval(days => %s)) "
            "ORDER BY maturity_date",
            (days,),
        )
        return cur.fetchall()
