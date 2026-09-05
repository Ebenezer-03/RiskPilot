# RiskPilot

Cost-aware fraud decisioning and policy-simulation platform, built solo as a
[Razorpay Buildathon](https://github.com/Ebenezer-03/RiskPilot/issues/1)
(Track 2: AI Risk Manager) submission. See [issue #1](https://github.com/Ebenezer-03/RiskPilot/issues/1)
for the full spec and [issues #2-#18](https://github.com/Ebenezer-03/RiskPilot/issues?q=is%3Aissue)
for the ticket breakdown.

## Problem statement

Fraud-risk models output a probability, but a payments platform has to make
a decision - and a fixed global cutoff (`if fraud_probability > 0.5: block`)
treats every transaction's error as equally costly. A ₹200 food order and a
₹50,000 electronics order don't carry the same cost when wrongly blocked,
and a missed ₹50,000 fraud loss isn't the same as a missed ₹200 one. Risk
teams need a way to turn a calibrated risk score into an economically
defensible action - Allow, Step-up, Review, or Block - that accounts for
transaction value, merchant segment, and the finite capacity of human
reviewers, and to safely test a change to that decision policy against
historical traffic before it goes live.

**What's actually new here** isn't dynamic thresholds in the abstract -
mature payment platforms already run risk engines and configurable rules.
It's the combination of an expected-cost decision framework, versioned/
replayable policy governance with guardrails, review-capacity-constrained
allocation, full decision auditability, and a real (Test Mode) downstream
auto-responder integration, in one system.

## Architecture

```
                    ┌─────────────────────────┐
   Browser  ───────▶│   Next.js (App Router)  │
                    │   apps/web/app/          │
                    └────────────┬─────────────┘
                                 │ /api/*  (next.config.ts rewrite
                                 │  in dev/Compose; Vercel routes
                                 │  it to the function directly
                                 │  in production)
                                 ▼
                    ┌─────────────────────────┐
                    │   FastAPI (Python 3.12) │
                    │   apps/web/api/_app/      │
                    │                          │
                    │  scoring (LightGBM +     │
                    │  isotonic calibration)   │
                    │  cost engine + segments  │
                    │  review-capacity alloc.  │
                    │  policy registry +       │
                    │    guardrails + replay   │
                    │  audit trail             │
                    │  Razorpay client         │
                    │  rate-limit middleware   │
                    └──────┬─────────┬─────────┘
                           │         │
                 SQL       │         │  Orders/Refunds API (real,
                           ▼         │  Test Mode) + verified webhook
                ┌────────────────┐   ▼
                │ Supabase       │  ┌──────────────┐
                │ Postgres       │  │  Razorpay    │
                │ (transactions, │  │  Test Mode   │
                │  decisions,    │  └──────────────┘
                │  policies)     │
                └────────────────┘
```

One Vercel project, one Root Directory (`apps/web`), one deployable tree -
see [issue #2](https://github.com/Ebenezer-03/RiskPilot/issues/2). The
frontend never talks to Postgres directly; it always goes through the
FastAPI backend. Three data sources converge on the same
transaction/decision schema, distinguished by a `data_source` field:
`synthetic` (a generator with realistic feature correlations), `ieee_cis`
(the labeled [IEEE-CIS Fraud Detection](https://www.kaggle.com/c/ieee-fraud-detection)
Kaggle dataset backing the detector), and `live_razorpay` (real Razorpay
Test Mode events via the auto-responder in ticket 14).

```
apps/web/
  app/               Next.js (App Router) frontend - 4 screens (below)
  lib/api.ts          Typed client for every backend endpoint - no mocks
  api/
    index.py          Vercel Python function entrypoint - imports the FastAPI app
    _app/             The actual FastAPI application:
      main.py          App wiring, /health, /score, rate-limit middleware
      scoring.py        LightGBM + isotonic calibration, SHAP reason codes
      cost_engine.py    Expected-cost formulas for the 4 actions
      segments.py       Merchant category x amount band x customer/device state
      policy.py, policy_registry.py, guardrails.py   Policy lifecycle + guardrails
      simulation_support.py, replay.py   Counterfactual replay engine
      review_allocation.py   Daily-cap-constrained review-queue ranking
      audit.py           Decision persistence + full-trace lookup
      razorpay_client.py, routers/razorpay.py   Test Mode auto-responder
      rate_limit.py       Per-client fixed-window rate limiting
      ml/train.py         Offline training script (not imported by the app)
      tests/             pytest suite - the API layer is the primary test seam
  Dockerfile.backend, Dockerfile.frontend   Docker Compose targets (below)
docker-compose.yml    Reviewer-runnable local environment
```

## Screens

1. **Live Decision Console** (`/console`) - submit or generate a
   transaction, see its score, segment, chosen action, all four expected
   costs, and reason codes. Calls the real `/score` and `/decide` endpoints.
2. **Policy Lab** (`/policy-lab`) - edit cost assumptions/segment
   thresholds/review capacity, save a candidate policy, run a replay
   against historical traffic, and view the baseline-vs-candidate
   comparison table (aggregate and by-segment). Guardrail rejections are
   surfaced with the specific violated guardrail(s).
3. **Audit & Monitoring** (`/audit`) - look up any transaction's full
   decision trace by ID, and watch approval-rate/false-decline-rate/
   realized-fraud-loss trends over a historical window.
4. **Razorpay Test Mode** (`/razorpay-demo`) - a checkout trigger page that
   creates a real Razorpay Test Mode order; paying it fires a real,
   signature-verified webhook that scores the payment through the same
   decision engine and, on BLOCK, issues a real Refunds API call. See
   "Razorpay integration" below for what this does and doesn't claim.

## Demo script

A ~5-minute walkthrough of the full story, in order:

1. **Landing page** (`/`) - click "Walk me through a decision" for a
   guided, click-through tour of one real transaction's Score → Decide →
   Audit journey (first call warms up the model, a few seconds).
2. **Live Decision Console** (`/console`) - click "Generate synthetic
   transaction", then "Run decision engine". Note the four expected costs
   shown side by side, not just the chosen action - open "Advanced: score
   against the real detector" to see the actual LightGBM call.
3. **Policy Lab** (`/policy-lab`) - pick "Conservative" or "Aggressive"
   under "How cautious should this policy be?", save it as a candidate,
   then "Run replay". The comparison table shows exactly what changed
   (fraud loss, legitimate GMV blocked, fraud caught, net expected loss)
   against the currently active policy, with the offline-estimate
   disclaimer visible. Try "Promote to ACTIVE" - a policy that would
   violate a guardrail is rejected with the specific guardrail named.
4. **Audit & Monitoring** (`/audit`) - paste the transaction ID from step 2
   (or any "Recent lookups" chip) to see its full decision trace: exact
   model/calibration/segment/policy/cost-matrix versions, expected costs,
   reason codes. Scroll to the trend charts for approval-rate/fraud-loss
   over time.
5. **Razorpay Test Mode** (`/razorpay-demo`) - pay a real Test Mode order
   with [Razorpay's documented test card/UPI details](https://razorpay.com/docs/payments/payments/test-card-upi-details/).
   The resulting webhook scores it through the same engine as every other
   screen; look the resulting transaction up in Audit to see
   `data_source: live_razorpay` and, if it decided BLOCK, that the payment
   was refunded.

## Detector

LightGBM (primary) + Logistic Regression (reported baseline, not the
production model), isotonic-calibrated, trained offline against the
IEEE-CIS dataset (`ml/train.py`, not imported by the running app - no
live retraining). Held-out test metrics ([full report](docs/evaluation_report.md)):

| Model | Precision | Recall | F1 | PR-AUC | ROC-AUC | Brier score |
|---|---|---|---|---|---|---|
| LightGBM (raw) | 0.4307 | 0.5524 | 0.484 | 0.5192 | 0.8825 | 0.0344 |
| LightGBM (isotonic-calibrated) | 0.7766 | 0.362 | 0.4938 | 0.5079 | 0.8819 | 0.0224 |
| Logistic Regression (baseline) | 0.1072 | 0.5933 | 0.1816 | 0.1303 | 0.79 | 0.1844 |

Precision/recall/F1 are reported at a fixed 0.5 threshold **for evaluation
only** - the actual decision engine never uses a fixed cutoff, it picks the
expected-cost-minimizing action per transaction. PR-AUC and Brier score
(threshold-independent) are the metrics that actually judge the detector.
Per-transaction SHAP values (top contributing features) back the reason
codes surfaced in the Live Decision Console and audit trail.

## Local development

### Frontend

```bash
cd apps/web
npm install
npm run dev
```

Runs at http://localhost:3000. In development, `next.config.ts` proxies
`/api/*` to the locally-running FastAPI process (`$BACKEND_URL`, default
`http://127.0.0.1:8000`) so routing behaves the same as production; on
Vercel itself, Vercel routes `/api/*` to the function directly instead.

### Backend

Requires Python 3.12 (pinned dependencies, and Vercel's own Python runtime,
don't yet have prebuilt wheels for 3.14 - see `apps/web/vercel.json`).

```bash
cd apps/web
py -V:Astral/CPython3.12.14 -m venv .venv   # or: python3.12 -m venv .venv
source .venv/Scripts/activate               # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cd api
uvicorn index:app --reload --port 8000
```

Runs at http://localhost:8000. `/health` checks real Supabase Postgres
connectivity and is exempt from rate limiting (the homepage polls it live).

### Docker Compose

The reviewer-runnable path - no local Python/Node toolchain setup needed:

```bash
cp apps/web/.env.example .env   # fill in real values - see that file's comments
docker compose up --build
```

Frontend at http://localhost:3000, backend at http://localhost:8000. The
stack starts successfully even with an empty `.env` - `/health` reports
`db: "not_configured"` and DB-backed endpoints return 503, the same
graceful-degradation behavior as the bare local setup above. Two things a
truly clean clone can't do out of the box, by design (see `.gitignore`):
- **`/score` against the real detector** needs the trained model artifacts
  (`api/_app/artifacts/*.joblib`/`*.txt`) or the raw IEEE-CIS dataset to
  retrain them - both are large/redistribution-restricted and intentionally
  not committed. Every other endpoint works without them.
- **`/razorpay/checkout` and the webhook** need real Razorpay Test Mode
  credentials in `.env` (free to create, no KYC) - see `.env.example`.

### Environment variables

See `apps/web/.env.example` for the authoritative list (every var there is
read directly by `db.py`/`razorpay_client.py`, nothing pulled-but-unused).
For the deployed Vercel project specifically: `vercel env pull .env.local --yes`
(run from `apps/web`, after `vercel link`) pulls the real Supabase
connection string, provisioned via the Vercel Marketplace integration.

**Known quirk**: `POSTGRES_URL` (the pooled connection string) from the
Supabase Marketplace integration currently ships with a malformed trailing
query parameter (`&supa=base-pooler.x`) that `psycopg`'s URI parser
rejects. The backend uses `POSTGRES_URL_NON_POOLING` instead, which is
well-formed.

## Razorpay integration

A real Razorpay **Test Mode** integration (ticket 14) - Orders API,
signature-verified webhook, Refunds API - not a simulation of one. Explicitly:

- **Post-capture enforcement, not pre-authorization interception.**
  Razorpay's own risk/authorization decision happens inside Razorpay's
  systems before any webhook fires; there is no hook point available to a
  webhook-based integration before capture. A BLOCK decision here refunds
  an already-captured Test Mode payment - it cannot prevent the charge.
- The webhook payload carries none of the IEEE-CIS-shaped ML features
  `/score` needs, so a live payment is priced using the same illustrative
  fraud-probability heuristic the synthetic generator uses (documented in
  `transactions.py`'s `estimate_fraud_probability`), not a real model score.
- No real Razorpay merchants, users, or production transaction/fraud data
  are involved anywhere in this system.

## Reliability

- **Rate limiting** (`api/_app/rate_limit.py`): a per-client, per-endpoint
  fixed-window limiter (tighter limits on `/score`, `/decide`,
  `/simulation/replay`, `/razorpay/checkout`; `/health` exempt). Deliberately
  simple - a process-local counter, not a distributed one - see that
  module's own docstring for the explicit scoping tradeoff.
- **Model fallback**: `/score` fails loudly (503) rather than guessing at a
  probability when the model artifact is unavailable. A policy-registry
  outage falls back to the day-1 default cost assumptions rather than
  taking down `/decide` entirely.
- **What this does not claim**: the rate limiter is abuse-resistant, not
  attack-resistant (a determined attacker distributing requests across many
  cold serverless instances could evade a process-local counter); a shared
  store (Upstash Redis) is the natural upgrade if that ever matters more
  than it does for a judged demo.

## Testing

`pytest`, run from `apps/web`:

```bash
pytest api/_app/tests
```

The primary seam is the FastAPI HTTP API layer (black-box, `TestClient` -
no reaching into internal module state); a secondary, narrow seam
unit-tests the pure cost-formula functions directly. Coverage includes
guardrail-rejection paths (each guardrail individually triggering a
rejected policy transition), replay's aggregate/segment deltas, the
review-capacity allocator under an oversubscribed input, the audit
endpoint's full-trace round-trip, Razorpay webhook signature verification
rejecting an unsigned/invalid payload, and the rate limiter's 429 path.
Tests requiring a real database are marked `@pytest.mark.integration` and
skip automatically when no `POSTGRES_URL*` is in the environment.

## What this system does not claim

- **No real Razorpay data.** All Razorpay activity is Test Mode; no
  production merchants, users, or transactions are involved.
- **No pre-authorization interception.** The Razorpay auto-responder is
  strictly post-capture enforcement (a refund), not a block before charge.
- **Offline replay is an estimate, not proof of causal production impact.**
  Counterfactual replay results are explicitly labeled as such in the UI.
- **Cost assumptions are illustrative**, not real Razorpay economics -
  editable in the Policy Lab, not hardcoded claims about true fraud/
  false-decline costs.
- **No live model retraining or self-deploying policy changes.** Every
  policy change goes through the Draft → Simulated → Active guardrail
  path; the detector is trained offline and its artifact is loaded at
  cold start, never retrained at runtime.
- **Not a replacement for Razorpay's SHIELD** or any commercial fraud
  platform, and out of scope entirely: AML/KYC/sanctions screening,
  account-takeover detection, merchant underwriting, a full payments
  gateway, and user authentication on the public demo (frictionless for
  judges; rate-limiting bounds abuse/cost risk instead).

## Deployment

One Vercel project (`riskpilot`), Next.js + a Python (3.12) serverless
function under `/api/*`, Supabase Postgres via the Marketplace. Deploy
with `vercel deploy` (preview) or `vercel deploy --prod` (production) from
`apps/web`.
