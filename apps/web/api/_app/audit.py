"""Decision audit trail persistence (ticket 07). Every /decide call made
against a known transaction_id is stored with the full model/calibration/
segment/policy/cost-matrix version metadata behind it, so GET
/audit/{transaction_id} can reconstruct exactly which model, calibration,
segment definition, policy, and cost matrix produced a given decision - see
issue #1's Implementation Decisions ("Audit trail").

Decisions made without a transaction_id (an ad-hoc probability/segment
input, not tied to a persisted transaction) aren't persisted here - there
is nothing to look them up by, since the audit endpoint is keyed on
transaction_id.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from . import db

_INSERT_SQL = """
INSERT INTO decisions (
    transaction_id, data_source, probability_used, action, expected_costs,
    reason_codes, merchant_category, amount_band, is_returning_customer,
    is_known_device, cost_profile_source, model_version, calibration_version,
    feature_schema_version, segment_definition_version, policy_version,
    cost_matrix_version
) VALUES (
    %(transaction_id)s, %(data_source)s, %(probability_used)s, %(action)s,
    %(expected_costs)s, %(reason_codes)s, %(merchant_category)s, %(amount_band)s,
    %(is_returning_customer)s, %(is_known_device)s, %(cost_profile_source)s,
    %(model_version)s, %(calibration_version)s, %(feature_schema_version)s,
    %(segment_definition_version)s, %(policy_version)s, %(cost_matrix_version)s
)
RETURNING id;
"""

_SELECT_BY_TRANSACTION_SQL = """
SELECT id, transaction_id, decided_at, data_source, probability_used, action,
       expected_costs, reason_codes, merchant_category, amount_band,
       is_returning_customer, is_known_device, cost_profile_source,
       model_version, calibration_version, feature_schema_version,
       segment_definition_version, policy_version, cost_matrix_version
FROM decisions
WHERE transaction_id = %(transaction_id)s
ORDER BY decided_at ASC, id ASC;
"""


def insert_decision(conn: psycopg.Connection, record: dict[str, Any]) -> int:
    """Persists one decision, returning its new row id. Always inserts
    (no ON CONFLICT/upsert) - see module docstring on why a transaction can
    have more than one decision row over time."""
    params = {
        **record,
        "expected_costs": Json(record["expected_costs"]),
        "reason_codes": Json(record["reason_codes"]),
    }
    with conn.cursor() as cur:
        cur.execute(_INSERT_SQL, params)
        (new_id,) = cur.fetchone()
    conn.commit()
    return new_id


def get_decisions_for_transaction(conn: psycopg.Connection, transaction_id: str) -> list[dict[str, Any]]:
    """Oldest first - a chronological trail, matching how a human would
    read "what happened to this transaction over time"."""
    with conn.cursor() as cur:
        cur.execute(_SELECT_BY_TRANSACTION_SQL, {"transaction_id": transaction_id})
        rows = cur.fetchall()
        return db.rows_to_dicts(cur, rows)


# Ticket 12's Audit & Monitoring dashboard needs an approval-rate/fraud-loss/
# false-positive trend, not just a single transaction's trace. This is the
# only aggregate query in the module (everything else here is keyed on one
# transaction_id) - it joins decisions back to transactions for is_fraud/
# amount, since neither is duplicated onto the decisions row itself.
# false_positive_count/fraud_loss are only meaningful over *labeled*
# transactions (is_fraud IS NOT NULL) - live Razorpay events have no label
# and are silently excluded from those two columns rather than treated as
# known-legitimate, which would understate both.
_DAILY_TRENDS_SQL = """
SELECT
    date_trunc('day', d.decided_at) AS day,
    count(*) AS total_decisions,
    count(*) FILTER (WHERE d.action = 'ALLOW') AS allow_count,
    count(*) FILTER (WHERE d.action = 'BLOCK' AND t.is_fraud = false) AS false_positive_count,
    count(*) FILTER (WHERE t.is_fraud IS NOT NULL) AS labeled_count,
    coalesce(sum(t.amount) FILTER (WHERE d.action = 'ALLOW' AND t.is_fraud = true), 0) AS fraud_loss
FROM decisions d
JOIN transactions t ON t.transaction_id = d.transaction_id
WHERE d.decided_at >= now() - (%(days)s * interval '1 day')
GROUP BY 1
ORDER BY 1;
"""


def get_daily_trends(conn: psycopg.Connection, days: int) -> list[dict[str, Any]]:
    """Oldest day first, one row per day that had at least one decision in
    the requested window - days with zero decisions simply don't appear
    (not zero-filled), since a trend chart can space gaps itself."""
    with conn.cursor() as cur:
        cur.execute(_DAILY_TRENDS_SQL, {"days": days})
        rows = cur.fetchall()
        return db.rows_to_dicts(cur, rows)
