"""Transaction records: synthetic generation and the IEEE-CIS -> unified-
schema mapping, plus the Postgres persistence functions both go through.

Both data sources converge on the same shape (see db.py's SCHEMA_SQL) so
the decision engine (ticket 05) and replay engine (ticket 08) can treat
`transactions` as one table regardless of where a row came from - the
spec's `data_source` field is what tells them apart, not a different
table/shape per source.
"""

from __future__ import annotations

import math
import random
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Json

from .segments import MERCHANT_CATEGORIES, resolve_amount_band

# Illustrative per-category amount distributions (INR), log-normal so most
# transactions cluster below the median with a long high-value tail - not
# fitted to any real data, a documented demo assumption like everything
# else in the cost/segment model (see issue #1's Implementation Decisions).
_CATEGORY_MEDIAN_AMOUNT = {
    "electronics": 15_000,
    "travel": 20_000,
    "digital_goods": 800,
    "food_delivery": 400,
}
_LOGNORMAL_SIGMA = 0.9

# Baseline fraud rate and the multipliers a new customer, new device, and
# higher amount band each apply - loosely mirrors the "new account + new
# device + high amount -> higher fraud probability" narrative from the
# spec's grilling session, not a fitted model. This is what makes the
# generator's labels correlated with features rather than i.i.d. random,
# per this ticket's acceptance criterion.
_BASE_FRAUD_RATE = 0.02
_NEW_CUSTOMER_MULTIPLIER = 2.5
_NEW_DEVICE_MULTIPLIER = 2.5
_AMOUNT_BAND_MULTIPLIER = {"low": 1.0, "medium": 1.3, "high": 2.0}


def generate_synthetic_transaction(rng: random.Random | None = None) -> dict[str, Any]:
    """One synthetic transaction with realistic feature correlations. Not a
    real transaction, not derived from real data - explicitly `data_source:
    synthetic`."""
    rng = rng or random.Random()

    merchant_category = rng.choice(MERCHANT_CATEGORIES)
    median_amount = _CATEGORY_MEDIAN_AMOUNT[merchant_category]
    amount = round(rng.lognormvariate(math.log(median_amount), _LOGNORMAL_SIGMA), 2)
    amount_band = resolve_amount_band(amount)

    is_returning_customer = rng.random() < 0.7
    # A returning customer is more likely (but not certain) to be on a
    # known device too - device and customer familiarity are correlated,
    # not independent coin flips.
    is_known_device = rng.random() < (0.85 if is_returning_customer else 0.25)

    fraud_probability = _BASE_FRAUD_RATE
    if not is_returning_customer:
        fraud_probability *= _NEW_CUSTOMER_MULTIPLIER
    if not is_known_device:
        fraud_probability *= _NEW_DEVICE_MULTIPLIER
    fraud_probability *= _AMOUNT_BAND_MULTIPLIER[amount_band]
    fraud_probability = min(fraud_probability, 0.95)
    is_fraud = rng.random() < fraud_probability

    return {
        "transaction_id": f"txn_synthetic_{uuid.uuid4().hex[:12]}",
        "data_source": "synthetic",
        "event_time": datetime.now(timezone.utc),
        "amount": amount,
        "currency": "INR",
        "merchant_id": f"m_{merchant_category}_{rng.randint(1, 50):03d}",
        "merchant_category": merchant_category,
        "amount_band": amount_band,
        "is_returning_customer": is_returning_customer,
        "is_known_device": is_known_device,
        "is_fraud": is_fraud,
        "raw_features": {
            "generation_fraud_probability": round(fraud_probability, 4),
        },
    }


# Illustrative only - ProductCD's real meaning is undisclosed by the IEEE-CIS
# competition (see docs/data_assumptions.md). This is a fixed, documented
# assignment for demo purposes, not a claim about what Vesta's codes mean.
_PRODUCT_CD_TO_MERCHANT_CATEGORY = {
    "W": "digital_goods",
    "C": "travel",
    "R": "electronics",
    "H": "food_delivery",
    "S": "digital_goods",
}


def record_from_ieee_cis_row(row: dict[str, Any]) -> dict[str, Any]:
    """Maps one raw IEEE-CIS transaction (see api/_app/ml/features.py's
    schema) onto the same unified record shape synthetic transactions use.
    `amount` reuses TransactionAmt as a magnitude proxy for banding even
    though the dataset isn't actually INR-denominated - a documented
    simplification, not a currency conversion claim.
    """
    amount = float(row["TransactionAmt"])
    product_cd = row.get("ProductCD")
    merchant_category = _PRODUCT_CD_TO_MERCHANT_CATEGORY.get(product_cd, "digital_goods")

    # D1's exact semantics are undisclosed by the competition (commonly
    # read informally as "days since this card was first seen"); used here
    # only as a rough returning-customer proxy, not asserted as ground
    # truth - see docs/data_assumptions.md.
    d1 = row.get("D1")
    is_returning_customer = bool(d1 is not None and d1 > 30)
    is_known_device = row.get("DeviceType") is not None

    return {
        "transaction_id": f"txn_ieee_{row['TransactionID']}",
        "data_source": "ieee_cis",
        "event_time": datetime.now(timezone.utc),
        "amount": amount,
        "currency": "INR",
        "merchant_id": None,
        "merchant_category": merchant_category,
        "amount_band": resolve_amount_band(amount),
        "is_returning_customer": is_returning_customer,
        "is_known_device": is_known_device,
        "is_fraud": bool(row["isFraud"]) if row.get("isFraud") is not None else None,
        "raw_features": row,
    }


_INSERT_SQL = """
INSERT INTO transactions (
    transaction_id, data_source, event_time, amount, currency, merchant_id,
    merchant_category, amount_band, is_returning_customer, is_known_device,
    is_fraud, raw_features
) VALUES (
    %(transaction_id)s, %(data_source)s, %(event_time)s, %(amount)s, %(currency)s,
    %(merchant_id)s, %(merchant_category)s, %(amount_band)s,
    %(is_returning_customer)s, %(is_known_device)s, %(is_fraud)s, %(raw_features)s
)
ON CONFLICT (transaction_id) DO NOTHING
RETURNING id;
"""

_SELECT_SQL = """
SELECT transaction_id, data_source, event_time, amount, currency, merchant_id,
       merchant_category, amount_band, is_returning_customer, is_known_device,
       is_fraud, raw_features, created_at
FROM transactions
WHERE transaction_id = %(transaction_id)s;
"""


def insert_transaction(conn: psycopg.Connection, record: dict[str, Any]) -> bool:
    """Returns True if a new row was inserted, False if transaction_id
    already existed (idempotent - safe to retry)."""
    params = {**record, "raw_features": Json(record.get("raw_features") or {})}
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, params)
        inserted = cur.fetchone() is not None
    conn.commit()
    return inserted


def get_transaction(conn: psycopg.Connection, transaction_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(_SELECT_SQL, {"transaction_id": transaction_id})
        row = cur.fetchone()
        if row is None:
            return None
        columns = [desc.name for desc in cur.description]
    return dict(zip(columns, row))


_SELECT_LABELED_SQL_TEMPLATE = """
SELECT transaction_id, data_source, event_time, amount, currency, merchant_id,
       merchant_category, amount_band, is_returning_customer, is_known_device,
       is_fraud, raw_features, created_at
FROM transactions
WHERE is_fraud IS NOT NULL
{data_source_filter}
ORDER BY event_time DESC
LIMIT %(limit)s;
"""


def get_labeled_transactions(
    conn: psycopg.Connection, *, data_source: str | None = None, limit: int = 500
) -> list[dict[str, Any]]:
    """The replay engine's historical window (ticket 08): only transactions
    with a known ground-truth `is_fraud` label are replayable at all, most
    recent `event_time` first. `data_source` narrows to one source; omit
    for any."""
    filter_clause = "AND data_source = %(data_source)s" if data_source else ""
    sql = _SELECT_LABELED_SQL_TEMPLATE.format(data_source_filter=filter_clause)
    params: dict[str, Any] = {"limit": limit}
    if data_source:
        params["data_source"] = data_source

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        columns = [desc.name for desc in cur.description]
    return [dict(zip(columns, row)) for row in rows]
