"""RiskPilot FastAPI backend.

Owns all database access, ML inference, and the cost/policy decision engine.
The Next.js frontend never talks to Postgres directly - it always goes
through this API.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

# apps/web/.env.local, pulled via `vercel env pull` - `vercel dev`/the deployed
# platform inject these automatically, but a plain `uvicorn`/`pytest` run
# doesn't, so load it explicitly (silently does nothing if absent).
load_dotenv(Path(__file__).resolve().parents[2] / ".env.local")

from . import db
from .routers.transactions import router as transactions_router
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

    try:
        with db.get_connection() as conn:
            db.ensure_schema(conn)
    except Exception as exc:  # noqa: BLE001 - schema creation is best-effort at startup;
        # /health and /transactions both surface their own DB errors per-request either way.
        print(f"[startup] schema setup skipped: {exc}")

    yield


app = FastAPI(title="RiskPilot API", lifespan=lifespan)
app.include_router(transactions_router)


@app.get("/health")
async def health() -> dict:
    """Liveness check, including DB connectivity via Supabase Postgres."""
    if not db.get_database_url():
        return {"status": "ok", "db": "not_configured"}
    try:
        with db.get_connection() as conn:
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
