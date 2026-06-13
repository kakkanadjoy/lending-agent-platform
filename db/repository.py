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
