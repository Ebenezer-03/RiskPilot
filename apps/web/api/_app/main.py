"""RiskPilot FastAPI backend.

Owns all database access, ML inference, and the cost/policy decision engine.
The Next.js frontend never talks to Postgres directly - it always goes
through this API.
"""

import os

import psycopg
from fastapi import FastAPI

app = FastAPI(title="RiskPilot API")


@app.get("/health")
async def health() -> dict:
    """Liveness check, including DB connectivity via Supabase Postgres."""
    # POSTGRES_URL (the pooled connection string) from the Vercel/Supabase Marketplace
    # integration ships with a malformed trailing query param (`&supa=base-pooler.x`)
    # that psycopg's URI parser rejects. POSTGRES_URL_NON_POOLING is well-formed;
    # switch back to the pooled URL once that upstream issue is confirmed fixed.
    db_url = os.environ.get("POSTGRES_URL_NON_POOLING") or os.environ.get("POSTGRES_URL")
    if not db_url:
        return {"status": "ok", "db": "not_configured"}
    try:
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ok", "db": "connected"}
    except Exception as exc:  # noqa: BLE001 - surfaced deliberately for a liveness check
        return {"status": "degraded", "db": "error", "detail": str(exc)}


@app.get("/")
async def root() -> dict:
    return {"service": "riskpilot-api"}
