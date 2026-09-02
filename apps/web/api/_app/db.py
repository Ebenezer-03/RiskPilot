"""Shared Postgres access. Every DB-touching module goes through this -
one place that knows the connection-string quirk and owns the schema.
"""

from __future__ import annotations

import os
from typing import Literal

import psycopg

# Single source of truth for the values the CHECK constraint below also
# enumerates - a typo here (or in transactions.py) becomes a type error
# instead of only surfacing as a runtime constraint violation.
DataSource = Literal["synthetic", "ieee_cis", "live_razorpay"]


def get_database_url() -> str | None:
    # POSTGRES_URL (the pooled connection string) from the Vercel/Supabase
    # Marketplace integration ships with a malformed trailing query param
    # (`&supa=base-pooler.x`) that psycopg's URI parser rejects.
    # POSTGRES_URL_NON_POOLING is well-formed; switch back to the pooled URL
    # once that upstream issue is confirmed fixed.
    return os.environ.get("POSTGRES_URL_NON_POOLING") or os.environ.get("POSTGRES_URL")


def get_connection() -> psycopg.Connection:
    url = get_database_url()
    if not url:
        raise RuntimeError("No database URL configured (POSTGRES_URL_NON_POOLING / POSTGRES_URL).")
    return psycopg.connect(url, connect_timeout=5)


def row_to_dict(cur: psycopg.Cursor, row: tuple) -> dict:
    """Zips one fetched row with its cursor's column names. Every module
    that hand-writes SELECT/RETURNING SQL (transactions.py, audit.py,
    policy_registry.py) goes through this rather than each re-deriving
    `columns` locally."""
    columns = [desc.name for desc in cur.description]
    return dict(zip(columns, row))


def rows_to_dicts(cur: psycopg.Cursor, rows: list[tuple]) -> list[dict]:
    columns = [desc.name for desc in cur.description]
    return [dict(zip(columns, row)) for row in rows]


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
    id BIGSERIAL PRIMARY KEY,
    transaction_id TEXT NOT NULL UNIQUE,
    data_source TEXT NOT NULL CHECK (data_source IN ('synthetic', 'ieee_cis', 'live_razorpay')),
    event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    amount NUMERIC NOT NULL,
    currency TEXT NOT NULL DEFAULT 'INR',
    merchant_id TEXT,
    merchant_category TEXT NOT NULL,
    amount_band TEXT NOT NULL CHECK (amount_band IN ('low', 'medium', 'high')),
    is_returning_customer BOOLEAN NOT NULL,
    is_known_device BOOLEAN NOT NULL,
    is_fraud BOOLEAN,
    raw_features JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_transactions_data_source ON transactions (data_source);
CREATE INDEX IF NOT EXISTS idx_transactions_merchant_category ON transactions (merchant_category);

-- Decision audit trail (ticket 07). One row per /decide call made against a
-- known transaction_id (a decide call with no transaction_id has nothing to
-- audit by ID, so isn't persisted here - see routers/decisions.py). No
-- ON CONFLICT/upsert: re-deciding the same transaction is a legitimate,
-- separately-auditable event, not a duplicate to collapse away, so a
-- transaction can have more than one row here over time.
CREATE TABLE IF NOT EXISTS decisions (
    id BIGSERIAL PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions (transaction_id),
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_source TEXT NOT NULL CHECK (data_source IN ('synthetic', 'ieee_cis', 'live_razorpay')),
    probability_used DOUBLE PRECISION NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('ALLOW', 'STEP_UP', 'REVIEW', 'BLOCK')),
    expected_costs JSONB NOT NULL,
    reason_codes JSONB NOT NULL,
    merchant_category TEXT NOT NULL,
    amount_band TEXT NOT NULL CHECK (amount_band IN ('low', 'medium', 'high')),
    is_returning_customer BOOLEAN NOT NULL,
    is_known_device BOOLEAN NOT NULL,
    cost_profile_source TEXT NOT NULL CHECK (cost_profile_source IN ('merchant', 'merchant_category', 'global_default')),
    -- Nullable: the probability decided on isn't always the output of a real
    -- scored /score call (e.g. a synthetic transaction's own fabricated
    -- probability) - null here honestly records "not applicable" rather
    -- than a fabricated version string.
    model_version TEXT,
    calibration_version TEXT,
    feature_schema_version TEXT,
    segment_definition_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    cost_matrix_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_decisions_transaction_id ON decisions (transaction_id);

-- Policy registry (ticket 09). All six lifecycle values from issue #1's
-- Implementation Decisions are present in the CHECK constraint from day
-- one, but only DRAFT -> SIMULATED -> ACTIVE is ever written by this
-- system today - APPROVED/CANARY/ROLLED_BACK are reachable in the schema,
-- not yet in the API (see policy_registry.py/routers/policies.py).
CREATE TABLE IF NOT EXISTS policies (
    id BIGSERIAL PRIMARY KEY,
    policy_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'SIMULATED', 'APPROVED', 'CANARY', 'ACTIVE', 'ROLLED_BACK')),
    cost_assumptions JSONB NOT NULL,
    review_capacity INT NOT NULL,
    -- Populated by POST /policies/{id}/simulate; consumed (not recomputed)
    -- by POST /policies/{id}/promote's guardrail check, so a promotion
    -- decision is always traceable to the exact replay it was judged
    -- against.
    baseline_policy_id TEXT,
    replay_result JSONB,
    -- The most recent promotion attempt's guardrail violations, if any -
    -- null while DRAFT/never-attempted, or after a successful promotion.
    guardrail_violations JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    simulated_at TIMESTAMPTZ,
    activated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_policies_status ON policies (status);
"""


def ensure_schema(conn: psycopg.Connection) -> None:
    """Idempotent - safe to call on every startup. No migration framework
    yet (single-table, pre-launch project); revisit if the schema needs to
    evolve under real data rather than just gain new tables."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()
