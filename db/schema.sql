-- Mini-LOS schema — the system of record for the lending platform.
-- Applied by db/apply_schema.py. Idempotent: safe to run repeatedly.
-- Design notes live beside each table; the events table is the nervous system.

-- ── borrowers ────────────────────────────────────────────────────────────
-- The businesses we lend to, and (same table, flagged) their guarantors.
-- Small-business lending rides on owner guarantees, so a borrower row may be
-- a company OR an individual guarantor tied to one.
CREATE TABLE IF NOT EXISTS borrowers (
    borrower_id     TEXT PRIMARY KEY,            -- e.g. "BRW-00042"
    legal_name      TEXT NOT NULL,
    entity_type     TEXT NOT NULL,               -- llc | s_corp | c_corp | individual
    is_guarantor    BOOLEAN NOT NULL DEFAULT FALSE,
    guarantees_for  TEXT REFERENCES borrowers(borrower_id),  -- set when this row is a guarantor
    naics_code      TEXT,                         -- industry classification
    annual_revenue  NUMERIC(14,2),                -- most recent known, synthetic
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── loans ────────────────────────────────────────────────────────────────
-- The facilities. A revolver carries a maturity_date and renews annually;
-- a term loan amortizes and gets annual reviews (no renew/decline fork).
-- 'status' is the workflow position; 'risk_rating' is the human-owned grade.
CREATE TABLE IF NOT EXISTS loans (
    loan_id         TEXT PRIMARY KEY,            -- e.g. "LN-2024-0042"
    borrower_id     TEXT NOT NULL REFERENCES borrowers(borrower_id),
    facility_type   TEXT NOT NULL,               -- revolving_line | term_loan | owner_occ_cre | equipment
    commitment      NUMERIC(14,2) NOT NULL,      -- approved limit (revolver) or original amount (term)
    outstanding     NUMERIC(14,2) NOT NULL DEFAULT 0,  -- current drawn/owed
    origination_date DATE,
    maturity_date   DATE,                         -- the renewal clock; ~364 days out for revolvers
    status          TEXT NOT NULL DEFAULT 'active',    -- active | renewal_in_progress | renewed | review_in_progress | reviewed | declined
    risk_rating     INTEGER,                      -- 1..10 grade; human/scorecard owned, never LLM
    interest_rate   NUMERIC(6,4),
    -- Headline financials carried on the loan for Phase 0/1 (rules + EWS).
    -- Full statement line-items come later, when the spreading agent needs them.
    dscr            NUMERIC(6,3),                 -- debt service coverage (current cycle)
    dscr_prior      NUMERIC(6,3),                 -- prior cycle, for year-over-year delta (EWS)
    leverage        NUMERIC(6,3),                 -- debt / EBITDA
    utilization     NUMERIC(5,4),                 -- revolver: drawn / commitment
    income_discrepancy_pct NUMERIC(5,4),           -- |stated - documented| / documented; misrep check
    -- Ground truth, planted at generation, the answer key for everything
    -- downstream (rules verdicts, EWS labels). JSONB so it can hold flags,
    -- expected exception codes, and the deterioration label together.
    ground_truth    JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── documents ────────────────────────────────────────────────────────────
-- The checklist + what arrived. One row per required document per loan/cycle.
-- 'cycle' ties a document to an origination or a specific renewal year, so
-- the same loan can request "2025 tax return" this year and "2026" next.
CREATE TABLE IF NOT EXISTS documents (
    document_id     TEXT PRIMARY KEY,            -- e.g. "DOC-00917"
    loan_id         TEXT NOT NULL REFERENCES loans(loan_id),
    cycle           TEXT NOT NULL,               -- "origination" | "renewal-2026" | "review-2026"
    doc_type        TEXT NOT NULL,               -- business_tax_return | financial_statement | debt_schedule | guarantor_pfs | ...
    fiscal_year     INTEGER,                      -- the year the document covers, when applicable
    status          TEXT NOT NULL DEFAULT 'requested',  -- requested | received | classified | rejected
    file_path       TEXT,                         -- where the uploaded/generated PDF lives, once received
    received_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── policy_chunks — the RAG corpus (semantic + lexical in one table) ──────
-- Generated from rules/policy.yaml. Each row is one policy section, carrying
-- BOTH an embedding (for semantic search via pgvector) and a tsvector (for
-- lexical search via postgres full-text). The two retrieval halves live in
-- the same table, the same database — no separate search engine.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS policy_chunks (
    chunk_id        TEXT PRIMARY KEY,            -- e.g. "policy-DSCR-MIN"
    code            TEXT NOT NULL,               -- exception code this section governs
    section         TEXT NOT NULL,               -- "4.3.1" — citable
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,               -- the retrievable policy text
    embedding       vector(384),                 -- all-MiniLM-L6-v2 dimensionality
    -- tsv is derived from body for full-text search; GENERATED keeps it in
    -- sync automatically on every insert/update.
    tsv             tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED
);

-- Lexical search rides this GIN index over the tsvector.
CREATE INDEX IF NOT EXISTS idx_policy_chunks_tsv ON policy_chunks USING GIN (tsv);
-- Semantic search rides an IVFFlat index over the embedding (cosine distance).
-- (For a corpus this small a sequential scan is fine; the index is here for
-- correctness of approach and to scale without code changes.)
-- CREATE INDEX IF NOT EXISTS idx_policy_chunks_embedding
--     ON policy_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- ── events — THE OUTBOX (the nervous system) ─────────────────────────────
-- Append-only journal of everything that happens. The dispatcher worker
-- reads unprocessed rows in order and acts on them (starts/resumes agents).
-- Durable by construction: a crash leaves the row processed_at = NULL, so it
-- is simply picked up on restart. This table doubles as the audit spine and
-- the desk's activity feed.
CREATE TABLE IF NOT EXISTS events (
    event_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type      TEXT NOT NULL,               -- renewal.due | document.received | spread.verified | ...
    loan_id         TEXT REFERENCES loans(loan_id),
    payload         JSONB NOT NULL DEFAULT '{}', -- event-specific detail
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),   -- when it happened
    processed_at    TIMESTAMPTZ                   -- NULL = not yet handled by the worker
);

-- The worker's hot query is "give me the oldest unprocessed events," so index
-- exactly that. Partial index: only unprocessed rows, kept small and fast.
CREATE INDEX IF NOT EXISTS idx_events_unprocessed
    ON events (created_at)
    WHERE processed_at IS NULL;
