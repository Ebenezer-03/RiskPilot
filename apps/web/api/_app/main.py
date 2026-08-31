"""RiskPilot FastAPI backend.

Owns all database access, ML inference, and the cost/policy decision engine.
The Next.js frontend never talks to Postgres directly - it always goes
through this API.
"""

import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException

from .schemas import ScoreRequest, ScoreResponse
from .scoring import get_scoring_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Loads the model/calibrator artifacts once at cold start, not
    per-request. Deliberately not fatal on failure - a missing/corrupt
    artifact should degrade /score (see its own try/except) rather than
    take down /health and the rest of the API with it.
    """
    try:
        get_scoring_service()
    except Exception as exc:  # noqa: BLE001 - any artifact-loading failure (missing file,
        # corrupt joblib/LightGBM parse error, version mismatch) should degrade /score,
        # not take the whole app down at startup.
        print(f"[startup] scoring service unavailable: {exc}")
    yield


app = FastAPI(title="RiskPilot API", lifespan=lifespan)


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


@app.post("/score", response_model=ScoreResponse)
async def score(payload: ScoreRequest) -> ScoreResponse:
    try:
        service = get_scoring_service()
    except Exception as exc:  # noqa: BLE001 - see the lifespan handler's comment above
        # Model-unavailable fallback: fail loudly and explicitly rather than
        # guessing at a probability. The caller (decision engine, ticket 05)
        # is responsible for its own conservative default when this happens.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = service.score(payload.features)
    return ScoreResponse(transaction_id=payload.transaction_id, **result)
