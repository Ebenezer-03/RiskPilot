# Data Assumptions

## Status

**Blocked**: acquiring the actual IEEE-CIS Fraud Detection dataset (ticket #23 / `02a`)
requires Kaggle API credentials (a `kaggle.json` with a username and API key), which
aren't available in this environment. This document covers the parts of `02a` that
don't need the raw files — the feature-time contract — written from the dataset's
publicly documented schema. **It must be revalidated against the actual columns once
the data is downloaded**, since some of it (particularly the `V1`-`V339` block) is
provisional until then.

To unblock: a human needs to create a free Kaggle account, join the
[IEEE-CIS Fraud Detection competition](https://www.kaggle.com/competitions/ieee-fraud-detection)
(accepting its rules is required before download), generate an API token at
`kaggle.com/settings` → API → "Create New Token", and provide the resulting
`kaggle.json`. Once available, ticket `02a` continues with `kaggle competitions
download -c ieee-fraud-detection`.

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

Until the `V1`-`V339` verification above is done, the training pipeline should:

1. Compute per-column correlation with `isFraud` for the `V` block.
2. Flag any `V` column whose predictive power looks disproportionate relative to its
   documented category (Vesta groups `V` columns loosely by rank/count/entity-relation
   type in the competition's data description).
3. Exclude flagged columns from the authorization-time feature set, or hold them out
   for a separate "with vs. without" PR-AUC comparison so the eval report can show
   the effect explicitly rather than silently dropping signal.

No columns are hard-excluded yet — this is a check to run once the real data is
available, not a conclusion reachable from the schema alone.

## Time-based split

Held-out evaluation (precision/recall/PR-AUC/calibration, per ticket `02c`) uses a
split on `TransactionDT`: train on the earliest ~80% by time, evaluate on the most
recent ~20%. This mirrors how the detector will actually be used (predicting forward
in time) and avoids the optimistic-metric trap of a random split on this dataset.
