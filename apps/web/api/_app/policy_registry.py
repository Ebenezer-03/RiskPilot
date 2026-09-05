"""Persistence for the policy registry (ticket 09). Business-rule
enforcement (which transitions are legal from which status) lives in
routers/policies.py, same division as transactions.py/audit.py: this
module is a dumb CRUD + conditional-transition layer over Postgres.

The three lifecycle-transition functions below use `WHERE status = ...` in
their UPDATE so a transition from the wrong status is a no-op (0 rows
affected) rather than a race condition silently clobbering a policy that
moved on between the caller's read and write - the router distinguishes
"not found" from "found but in the wrong status" with its own prior lookup
and reports the right 404 vs 409.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from . import db

_COLUMNS = """
    policy_id, name, status, cost_assumptions, review_capacity,
    baseline_policy_id, replay_result, guardrail_violations,
    created_at, updated_at, simulated_at, activated_at,
    canary_replay_result, superseded_policy_id
"""

_INSERT_SQL = f"""
INSERT INTO policies (policy_id, name, status, cost_assumptions, review_capacity)
VALUES (%(policy_id)s, %(name)s, 'DRAFT', %(cost_assumptions)s, %(review_capacity)s)
RETURNING {_COLUMNS};
"""

_SELECT_SQL = f"SELECT {_COLUMNS} FROM policies WHERE policy_id = %(policy_id)s;"

_LIST_SQL_TEMPLATE = f"""
SELECT {_COLUMNS} FROM policies
{{status_filter}}
ORDER BY created_at DESC;
"""

_UPDATE_DRAFT_SQL = f"""
UPDATE policies
SET name = %(name)s, cost_assumptions = %(cost_assumptions)s, review_capacity = %(review_capacity)s,
    updated_at = now()
WHERE policy_id = %(policy_id)s AND status = 'DRAFT'
RETURNING {_COLUMNS};
"""

_DELETE_DRAFT_SQL = "DELETE FROM policies WHERE policy_id = %(policy_id)s AND status = 'DRAFT' RETURNING policy_id;"

_TRANSITION_TO_SIMULATED_SQL = f"""
UPDATE policies
SET status = 'SIMULATED', baseline_policy_id = %(baseline_policy_id)s, replay_result = %(replay_result)s,
    guardrail_violations = NULL, simulated_at = now(), updated_at = now()
WHERE policy_id = %(policy_id)s AND status = 'DRAFT'
RETURNING {_COLUMNS};
"""

_TRANSITION_TO_ACTIVE_SQL = f"""
UPDATE policies
SET status = 'ACTIVE', guardrail_violations = NULL, activated_at = now(), updated_at = now(),
    superseded_policy_id = %(superseded_policy_id)s
WHERE policy_id = %(policy_id)s AND status IN ('SIMULATED', 'CANARY')
RETURNING {_COLUMNS};
"""

_TRANSITION_TO_CANARY_SQL = f"""
UPDATE policies
SET status = 'CANARY', canary_replay_result = %(canary_replay_result)s, guardrail_violations = NULL, updated_at = now()
WHERE policy_id = %(policy_id)s AND status = 'SIMULATED'
RETURNING {_COLUMNS};
"""

_TRANSITION_TO_ROLLED_BACK_SQL = f"""
UPDATE policies
SET status = 'ROLLED_BACK', updated_at = now()
WHERE policy_id = %(policy_id)s AND status IN ('ACTIVE', 'CANARY')
RETURNING {_COLUMNS};
"""

_REACTIVATE_SQL = f"""
UPDATE policies
SET status = 'ACTIVE', activated_at = now(), updated_at = now()
WHERE policy_id = %(policy_id)s
RETURNING {_COLUMNS};
"""

# A candidate's own /simulate-time guardrail rejection can happen while
# SIMULATED or CANARY (the canary-vetting step reuses this same recorder -
# ticket 16's "no new evaluation logic" acceptance criterion).
_RECORD_REJECTION_SQL = f"""
UPDATE policies
SET guardrail_violations = %(guardrail_violations)s, updated_at = now()
WHERE policy_id = %(policy_id)s AND status IN ('SIMULATED', 'CANARY')
RETURNING {_COLUMNS};
"""

# Baseline for a /simulate call that doesn't name one explicitly - the most
# recently activated ACTIVE policy. Ticket 09 doesn't require enforcing
# "exactly one ACTIVE policy at a time" (out of its stated acceptance
# criteria), so more than one row can hold status='ACTIVE' over the
# system's lifetime; "the current one" is simply whichever activated most
# recently.
_CURRENT_ACTIVE_SQL = f"""
SELECT {_COLUMNS} FROM policies WHERE status = 'ACTIVE' ORDER BY activated_at DESC LIMIT 1;
"""


def insert_policy(conn: psycopg.Connection, *, policy_id: str, name: str, cost_assumptions: dict, review_capacity: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_SQL,
            {
                "policy_id": policy_id,
                "name": name,
                "cost_assumptions": Json(cost_assumptions),
                "review_capacity": review_capacity,
            },
        )
        row = db.row_to_dict(cur, cur.fetchone())
    conn.commit()
    return row


def get_policy(conn: psycopg.Connection, policy_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(_SELECT_SQL, {"policy_id": policy_id})
        row = cur.fetchone()
        if row is None:
            return None
        return db.row_to_dict(cur, row)


def list_policies(conn: psycopg.Connection, *, status: str | None = None) -> list[dict[str, Any]]:
    filter_clause = "WHERE status = %(status)s" if status else ""
    sql = _LIST_SQL_TEMPLATE.format(status_filter=filter_clause)
    params = {"status": status} if status else {}
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        return db.rows_to_dicts(cur, rows)


def get_current_active_policy(conn: psycopg.Connection) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(_CURRENT_ACTIVE_SQL)
        row = cur.fetchone()
        if row is None:
            return None
        return db.row_to_dict(cur, row)


def update_draft_policy(
    conn: psycopg.Connection, policy_id: str, *, name: str, cost_assumptions: dict, review_capacity: int
) -> dict[str, Any] | None:
    """Returns the updated row, or None if `policy_id` doesn't exist or
    isn't in DRAFT (caller distinguishes those with its own get_policy)."""
    with conn.cursor() as cur:
        cur.execute(
            _UPDATE_DRAFT_SQL,
            {
                "policy_id": policy_id,
                "name": name,
                "cost_assumptions": Json(cost_assumptions),
                "review_capacity": review_capacity,
            },
        )
        row = cur.fetchone()
        result = db.row_to_dict(cur, row) if row is not None else None
    conn.commit()
    return result


def delete_draft_policy(conn: psycopg.Connection, policy_id: str) -> bool:
    """Returns True if a DRAFT policy was deleted, False otherwise (doesn't
    exist, or exists but isn't DRAFT)."""
    with conn.cursor() as cur:
        cur.execute(_DELETE_DRAFT_SQL, {"policy_id": policy_id})
        deleted = cur.fetchone() is not None
    conn.commit()
    return deleted


def transition_to_simulated(
    conn: psycopg.Connection, policy_id: str, *, baseline_policy_id: str, replay_result: dict
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            _TRANSITION_TO_SIMULATED_SQL,
            {"policy_id": policy_id, "baseline_policy_id": baseline_policy_id, "replay_result": Json(replay_result)},
        )
        row = cur.fetchone()
        result = db.row_to_dict(cur, row) if row is not None else None
    conn.commit()
    return result


def transition_to_active(conn: psycopg.Connection, policy_id: str) -> dict[str, Any] | None:
    """SIMULATED -> ACTIVE (the committed direct path) or CANARY -> ACTIVE
    (ticket 16's stretch path) - same SQL handles both source statuses.
    Captures whichever policy is current-ACTIVE right now as this row's
    `superseded_policy_id`, so a later ROLLED_BACK can revert to it."""
    superseded = get_current_active_policy(conn)
    superseded_policy_id = superseded["policy_id"] if superseded is not None else None
    with conn.cursor() as cur:
        cur.execute(_TRANSITION_TO_ACTIVE_SQL, {"policy_id": policy_id, "superseded_policy_id": superseded_policy_id})
        row = cur.fetchone()
        result = db.row_to_dict(cur, row) if row is not None else None
    conn.commit()
    return result


def transition_to_canary(conn: psycopg.Connection, policy_id: str, *, canary_replay_result: dict) -> dict[str, Any] | None:
    """SIMULATED -> CANARY (ticket 16's stretch path): an optional staging
    step before ACTIVE, gated by the same guardrails as a direct promotion
    but evaluated against a 95/5 historical-replay subsample rather than
    the full window - see routers/policies.py's /canary handler."""
    with conn.cursor() as cur:
        cur.execute(_TRANSITION_TO_CANARY_SQL, {"policy_id": policy_id, "canary_replay_result": Json(canary_replay_result)})
        row = cur.fetchone()
        result = db.row_to_dict(cur, row) if row is not None else None
    conn.commit()
    return result


def transition_to_rolled_back(conn: psycopg.Connection, policy_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """ACTIVE/CANARY -> ROLLED_BACK, reverting the active-policy pointer to
    whichever policy this one superseded (if any) by reactivating it -
    ticket 16's explicit acceptance criterion. Returns
    (rolled_back_row, reactivated_row_or_None)."""
    with conn.cursor() as cur:
        cur.execute(_TRANSITION_TO_ROLLED_BACK_SQL, {"policy_id": policy_id})
        row = cur.fetchone()
        rolled_back = db.row_to_dict(cur, row) if row is not None else None

    reactivated = None
    if rolled_back is not None and rolled_back["superseded_policy_id"]:
        with conn.cursor() as cur:
            cur.execute(_REACTIVATE_SQL, {"policy_id": rolled_back["superseded_policy_id"]})
            reactivated_row = cur.fetchone()
            reactivated = db.row_to_dict(cur, reactivated_row) if reactivated_row is not None else None

    conn.commit()
    return rolled_back, reactivated


def record_guardrail_rejection(
    conn: psycopg.Connection, policy_id: str, *, violations: list[dict]
) -> dict[str, Any] | None:
    """Stays in SIMULATED per issue #1: 'a rejected candidate policy stays
    in SIMULATED with the violated guardrail(s) reported.'"""
    with conn.cursor() as cur:
        cur.execute(_RECORD_REJECTION_SQL, {"policy_id": policy_id, "guardrail_violations": Json(violations)})
        row = cur.fetchone()
        result = db.row_to_dict(cur, row) if row is not None else None
    conn.commit()
    return result
