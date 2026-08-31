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
"""


def ensure_schema(conn: psycopg.Connection) -> None:
    """Idempotent - safe to call on every startup. No migration framework
    yet (single-table, pre-launch project); revisit if the schema needs to
    evolve under real data rather than just gain new tables."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()
