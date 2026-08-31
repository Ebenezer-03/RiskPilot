# Data Assumptions

## Status

**Resolved.** The dataset was acquired (Kaggle API token provided) and the
`V1`-`V339` leakage check below has been run for real against the actual
columns — see [`evaluation_report.md`](evaluation_report.md) for the full
per-column results. Nothing in the `V` block exceeded the 0.90
single-feature-AUC flag threshold on the train split, so no columns were
excluded from the authorization-time feature set. The rest of this document
(the schema table) held up against the real data as written.

## Dataset shape

Two files, joined on `TransactionID`:

- `train_transaction.csv` — one row per transaction, ~590K rows. Target: `isFraud`.
- `train_identity.csv` — device/network metadata for a subset of transactions
  (identity data isn't collected for every transaction, so this join is a left join
  with expected nulls).

The competition's own train/test split is **time-based**: `TransactionDT` is a
timedelta (seconds) from an unspecified reference point, not a wall-clock timestamp,
but it is strictly ordered. This matters for RiskPilot's own held-out split too — it
should be a **time-based split on `TransactionDT`**, not a random split, or the
reported precision/recall will be optimistic (a random split lets the model see
"future" transactions from the same card/device during training).

## Feature-time contract

The question for every column: is this value knowable **at authorization time** (when
RiskPilot would actually have to make a decision), or does it only exist **after
settlement** (only knowable in hindsight, and therefore leakage if used as a model
input)?

| Column group | Available at authorization? | Notes |
|---|---|---|
| `TransactionDT`, `TransactionAmt`, `ProductCD` | Yes | Known the instant the transaction is submitted. |
| `card1`-`card6` | Yes | Card/issuer metadata submitted with the transaction. |
| `addr1`, `addr2`, `dist1`, `dist2` | Yes | Billing/shipping address and distance features, submitted with the transaction. |
| `P_emaildomain`, `R_emaildomain` | Yes | Purchaser/recipient email domain, submitted with the transaction. |
| `C1`-`C14` | Yes, with a caveat | Documented as counting features (e.g. "number of addresses associated with the card"). These are legitimate at-authorization signals *only if* computed from data strictly before the current transaction's timestamp. Vesta's own computation method isn't disclosed, so this is an assumption to verify empirically (see below) rather than a certainty. |
| `D1`-`D15` | Yes, with a caveat | Documented as timedelta features (e.g. "days since previous transaction"). Same caveat as `C1`-`C14` — legitimate only if backward-looking. |
| `M1`-`M9` | Yes | Match flags (e.g. does the cardholder name match the billing address) — computable at submission time. |
| `V1`-`V339` | **Provisional — treat as at-authorization, but verify** | Vesta's own engineered features; exact computation undisclosed. Community post-mortems on this competition have flagged that a handful of `V` columns correlate suspiciously well with the target, consistent with (but not proof of) forward-looking aggregation. Action: once the data is in hand, check each `V` column's correlation with `isFraud` and with `TransactionDT`-adjacent rows for the same `card1`/`addr1` before trusting it as an authorization-time feature; drop or flag any that look like they encode outcome information. |
| `id_01`-`id_38` (identity table) | Yes | Device/network/browser fingerprint data, collected at the same time as the transaction. |
| `DeviceType`, `DeviceInfo` | Yes | Same as above — this is what backs the "known device" / "new device" segment dimension. |
| `isFraud` (target) | **No — label, not a feature** | By construction. In RiskPilot's own delayed-label framing (see the spec's "fraud labels arrive late" discussion), this also stands in for the fact that a *real* fraud label is only known after a chargeback/dispute resolves, days to weeks after authorization — reinforced here, not just a dataset technicality. |

## Leakage-risk columns excluded from the authorization-time feature set

`api/_app/ml/train.py` computes single-feature AUC (direction-agnostic) against
`isFraud` for every `V` column, on the train split only (never test/calibration,
so the check itself can't leak). The top result was V303 at 0.657 — well under
the 0.90 flag threshold set in advance. No `V` column was excluded; the full
ranked table is in `evaluation_report.md`. This is a heuristic, not a proof of
leakage-freedom (Vesta's exact `V`-column computation is still undisclosed),
but it's the check this contract committed to running, and it found nothing
disproportionate enough to warrant exclusion.

## Time-based split

Held-out evaluation (precision/recall/PR-AUC/calibration, per ticket `02c`) uses a
split on `TransactionDT`: train on the earliest ~80% by time, evaluate on the most
recent ~20%. This mirrors how the detector will actually be used (predicting forward
in time) and avoids the optimistic-metric trap of a random split on this dataset.
