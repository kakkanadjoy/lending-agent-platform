"""Apply the mini-LOS schema to postgres.

Reads DATABASE_URL from the environment, falling back to the local compose
default. Idempotent — schema.sql uses CREATE TABLE IF NOT EXISTS, so running
this repeatedly is safe. Run from the project root:

    python db/apply_schema.py
"""
from __future__ import annotations

import os
import pathlib
import sys

import psycopg

DEFAULT_URL = "postgresql://lending:lending@localhost:5432/lending"
SCHEMA = pathlib.Path(__file__).parent / "schema.sql"


def main() -> int:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    sql = SCHEMA.read_text(encoding="utf-8")
    # connect_timeout: fail fast if the database is unreachable, rather than
    # hanging on a silent socket. (A lesson paid for in project 1.)
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
    except Exception as e:
        print(f"Schema apply failed: {type(e).__name__}: {e}")
        return 1

    # Report what now exists.
    with psycopg.connect(url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            tables = [r[0] for r in cur.fetchall()]
    print("Schema applied. Tables present:", ", ".join(tables))
    return 0


if __name__ == "__main__":
    sys.exit(main())
