"""Repository tests — each runs in a transaction that is rolled back, so the
database is byte-identical before and after the whole suite (no trace).

The `conn` fixture below opens a connection, hands it to the test, and on
teardown ROLLS BACK instead of committing. Because every repository function
takes the connection as an argument, all their writes ride this same
transaction and vanish together.
"""
import os

import psycopg
import pytest

from db import repository as repo

URL = os.environ.get("DATABASE_URL", "postgresql://lending:lending@localhost:5432/lending")


@pytest.fixture()
def conn():
    c = psycopg.connect(URL, connect_timeout=5, row_factory=psycopg.rows.dict_row)
    try:
        yield c          # the test runs here, inside an open transaction
    finally:
        c.rollback()     # undo everything the test did
        c.close()


def _seed_loan(c, loan_id="LN-TEST-1"):
    repo.create_borrower(c, "BRW-TEST-1", "Acme Test LLC", "llc", annual_revenue=6_000_000)
    repo.create_loan(c, loan_id, "BRW-TEST-1", "revolving_line", 750_000,
                     maturity_date="2026-09-30")
    return loan_id


def test_add_event_returns_id_and_is_unprocessed(conn):
    loan_id = _seed_loan(conn)
    eid = repo.add_event(conn, "renewal.due", loan_id, {"days_to_maturity": 90})
    assert isinstance(eid, int)
    pending = repo.unprocessed_events(conn)
    assert any(e["event_id"] == eid and e["event_type"] == "renewal.due" for e in pending)
    # payload round-trips through JSONB
    row = next(e for e in pending if e["event_id"] == eid)
    assert row["payload"]["days_to_maturity"] == 90


def test_unprocessed_is_oldest_first(conn):
    loan_id = _seed_loan(conn)
    first = repo.add_event(conn, "renewal.due", loan_id)
    second = repo.add_event(conn, "document.received", loan_id)
    pending = repo.unprocessed_events(conn)
    ids = [e["event_id"] for e in pending]
    assert ids.index(first) < ids.index(second)


def test_mark_processed_removes_from_queue(conn):
    loan_id = _seed_loan(conn)
    eid = repo.add_event(conn, "spread.verified", loan_id)
    repo.mark_processed(conn, eid)
    pending_ids = [e["event_id"] for e in repo.unprocessed_events(conn)]
    assert eid not in pending_ids


def test_create_and_get_loan(conn):
    loan_id = _seed_loan(conn, "LN-TEST-2")
    got = repo.get_loan(conn, loan_id)
    assert got["loan_id"] == loan_id
    assert got["facility_type"] == "revolving_line"
    assert float(got["commitment"]) == 750_000.0


def test_rollback_leaves_no_trace(conn):
    # sanity: a fresh connection should not see another (rolled-back) test's rows
    with psycopg.connect(URL, connect_timeout=5, row_factory=psycopg.rows.dict_row) as other:
        with other.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM borrowers WHERE borrower_id = 'BRW-TEST-1'")
            # this test's own fixture hasn't inserted yet, and other tests rolled back
            assert cur.fetchone()["n"] == 0
