# RiskPilot

Cost-aware fraud decisioning and policy-simulation platform. See [issue #1](https://github.com/Ebenezer-03/RiskPilot/issues/1) for the full spec, and the ticket breakdown in issues #2-#18.

> This is a work-in-progress Buildathon submission. The sections below cover what's built so far; the full README (problem statement, architecture diagram, demo script, "what this system does not claim") lands as part of [ticket #16](https://github.com/Ebenezer-03/RiskPilot/issues/16).

## Structure

```
apps/
  web/   Next.js (App Router) frontend
  api/   Python FastAPI backend - owns all DB access, ML inference, decision/policy engine
```

The frontend never talks to the database directly; it always goes through the API.

## Local development

### Frontend (`apps/web`)

```bash
cd apps/web
npm install
npm run dev
```

Runs at http://localhost:3000.

### Backend (`apps/api`)

Requires Python 3.12 (pinned dependencies don't yet have prebuilt wheels for 3.14).

```bash
cd apps/api
py -V:Astral/CPython3.12.14 -m venv .venv   # or: python3.12 -m venv .venv
source .venv/Scripts/activate               # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Runs at http://localhost:8000. `/health` is a liveness check (DB connectivity check is wired up once Supabase is provisioned - see ticket #21).

### Environment variables

None required yet. Once Supabase is provisioned (ticket #21), the connection string will be documented here and in `docs/agents/domain.md`.

## Deployment

Deployed as one Vercel project (Next.js + FastAPI via Fluid Compute) - see ticket #20 for the Vercel linking setup.
