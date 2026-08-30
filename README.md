# RiskPilot

Cost-aware fraud decisioning and policy-simulation platform. See [issue #1](https://github.com/Ebenezer-03/RiskPilot/issues/1) for the full spec, and the ticket breakdown in issues #2-#18.

> This is a work-in-progress Buildathon submission. The sections below cover what's built so far; the full README (problem statement, architecture diagram, demo script, "what this system does not claim") lands as part of [ticket #16](https://github.com/Ebenezer-03/RiskPilot/issues/16).

## Structure

```
apps/web/
  app/           Next.js (App Router) frontend
  api/
    index.py     Vercel Python function entrypoint - imports the FastAPI app
    _app/        The actual FastAPI application (routes, DB access, decision engine)
  vercel.json    Pins the Python function runtime to 3.12
```

Both apps live under `apps/web` on purpose: Vercel's Root Directory setting scopes exactly what a deployment can see, so a Python function can't import code from outside its own app's directory. One Vercel project, one Root Directory, one deployable tree - see [issue #2](https://github.com/Ebenezer-03/RiskPilot/issues/2) for how this was worked out. The frontend never talks to Postgres directly; it always goes through the FastAPI backend.

## Local development

### Frontend

```bash
cd apps/web
npm install
npm run dev
```

Runs at http://localhost:3000. In development, `next.config.ts` proxies `/api/*` to the locally-running FastAPI process (`http://127.0.0.1:8000`) so routing behaves the same as production.

### Backend

Requires Python 3.12 (pinned dependencies, and Vercel's own Python runtime, don't yet have prebuilt wheels for 3.14 - see `apps/web/vercel.json`).

```bash
cd apps/web
py -V:Astral/CPython3.12.14 -m venv .venv   # or: python3.12 -m venv .venv
source .venv/Scripts/activate               # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cd api
uvicorn index:app --reload --port 8000
```

Runs at http://localhost:8000. `/health` checks real Supabase Postgres connectivity.

### Environment variables

Pulled from Vercel: `vercel env pull .env.local --yes` (run from `apps/web`, after `vercel link`). Supabase Postgres is provisioned via the Vercel Marketplace; the pulled `.env.local` includes `POSTGRES_URL`, `POSTGRES_URL_NON_POOLING`, and the `SUPABASE_*` keys.

**Known quirk**: `POSTGRES_URL` (the pooled connection string) from the Supabase Marketplace integration currently ships with a malformed trailing query parameter (`&supa=base-pooler.x`) that `psycopg`'s URI parser rejects. The backend uses `POSTGRES_URL_NON_POOLING` instead, which is well-formed. Revisit if the pooled URL is needed for scale later.

## Deployment

One Vercel project (`riskpilot`), Next.js + a Python (3.12) serverless function under `/api/*`, Supabase Postgres via the Marketplace. Deploy with `vercel deploy` (preview) or `vercel deploy --prod` (production) from `apps/web`.
