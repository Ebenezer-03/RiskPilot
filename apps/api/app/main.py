"""RiskPilot FastAPI backend.

Owns all database access, ML inference, and the cost/policy decision engine.
The Next.js frontend never talks to Postgres directly - it always goes
through this API.
"""

from fastapi import FastAPI

app = FastAPI(title="RiskPilot API")


@app.get("/health")
async def health() -> dict:
    """Liveness check. DB connectivity is added once the database is wired up (ticket 01c/01d)."""
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {"service": "riskpilot-api"}
