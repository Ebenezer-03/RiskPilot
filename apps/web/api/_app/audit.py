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
        columns = [desc.name for desc in cur.description]
    return [dict(zip(columns, row)) for row in rows]
