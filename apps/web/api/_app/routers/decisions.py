"""POST /decide - the cost-aware decision engine's API surface (ticket 05).
Also persists every decision made against a known transaction_id for the
audit trail (ticket 07) - see ../audit.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from fastapi import APIRouter, HTTPException

from . import get_connection_or_503
from .. import db
from ..audit import insert_decision
from ..cost_engine import (
    COST_MATRIX_VERSION,
    DEFAULT_COST_ASSUMPTIONS,
    POLICY_VERSION,
    CostAssumptions,
    build_reason_codes,
    choose_action,
    compute_expected_costs,
    resolve_cost_profile,
)
from ..policy_registry import get_current_active_policy
from ..schemas import DecideRequest, DecideResponse
from ..segments import SEGMENT_DEFINITION_VERSION, resolve_amount_band
from ..transactions import get_transaction

router = APIRouter(tags=["decisions"])


_RECORD_FIELD_BY_REQUEST_FIELD = {
    "merchant_id": "merchant_id",
    "merchant_category": "merchant_category",
    "amount": "amount",
    "is_returning_customer": "is_returning_customer",
    "is_known_device": "is_known_device",
}


@router.post("/decide", response_model=DecideResponse)
async def decide(payload: DecideRequest) -> DecideResponse:
    fields = {name: getattr(payload, name) for name in _RECORD_FIELD_BY_REQUEST_FIELD}
    data_source = None

    if payload.transaction_id:
        conn = get_connection_or_503()
        # One connection, one transaction, spanning both the lookup and the
        # audit-trail insert below - not a separate connection for each.
        with conn:
            record = get_transaction(conn, payload.transaction_id)
            if record is None:
                raise HTTPException(status_code=404, detail=f"No transaction with id {payload.transaction_id!r}")
            data_source = record["data_source"]
            # An explicitly-supplied request field always wins over the
            # persisted transaction's own value.
            for request_field, record_field in _RECORD_FIELD_BY_REQUEST_FIELD.items():
                if fields[request_field] is None:
                    fields[request_field] = record[record_field]
            if fields["amount"] is not None:
                fields["amount"] = float(fields["amount"])

            cost_assumptions, active_policy_id = _active_cost_assumptions_using(conn)
            outcome = _resolve_and_decide(payload, fields, cost_assumptions)

            insert_decision(
                conn,
                {
                    "transaction_id": payload.transaction_id,
                    "data_source": data_source,
                    "probability_used": payload.probability,
                    "action": outcome.action,
                    "expected_costs": outcome.rounded_costs,
                    "reason_codes": outcome.reason_codes,
                    "merchant_category": outcome.merchant_category,
                    "amount_band": outcome.amount_band,
                    "is_returning_customer": outcome.is_returning_customer,
                    "is_known_device": outcome.is_known_device,
                    "cost_profile_source": outcome.cost_profile_source,
                    "model_version": payload.model_version,
                    "calibration_version": payload.calibration_version,
                    "feature_schema_version": payload.feature_schema_version,
                    "segment_definition_version": SEGMENT_DEFINITION_VERSION,
                    # policy_version identifies the decision *mechanism*
                    # (which actions exist, the tie-break rule, the
                    # fallback chain - see cost_engine.py's comment); the
                    # registry only ever varies cost assumptions, so an
                    # active policy's id belongs on cost_matrix_version,
                    # not collapsed into both.
                    "policy_version": POLICY_VERSION,
                    "cost_matrix_version": active_policy_id or COST_MATRIX_VERSION,
                },
            )
    else:
        cost_assumptions, _active_policy_id = _active_cost_assumptions_standalone()
        outcome = _resolve_and_decide(payload, fields, cost_assumptions)

    return DecideResponse(
        transaction_id=payload.transaction_id,
        decision=outcome.action,
        expected_costs=outcome.rounded_costs,
        probability_used=payload.probability,
        merchant_category=outcome.merchant_category,
        amount_band=outcome.amount_band,
        is_returning_customer=outcome.is_returning_customer,
        is_known_device=outcome.is_known_device,
        cost_profile_source=outcome.cost_profile_source,
        reason_codes=outcome.reason_codes,
    )


@dataclass(frozen=True)
class _DecisionOutcome:
    merchant_category: str
    amount_band: str
    is_returning_customer: bool
    is_known_device: bool
    cost_profile_source: str
    rounded_costs: dict
    action: str
    reason_codes: list


def _active_cost_assumptions_using(conn: psycopg.Connection) -> tuple[CostAssumptions, str | None]:
    """The currently ACTIVE policy's cost assumptions, so promoting a
    candidate through the registry (ticket 09) actually changes live
    decisioning rather than only a database status - falls back to the
    day-1 default when no policy has ever been activated. `conn` is
    already open (the caller's own transaction_id lookup/audit-insert
    connection), so this issues one extra query on it rather than a
    second connection."""
    active = get_current_active_policy(conn)
    if active is None:
        return DEFAULT_COST_ASSUMPTIONS, None
    return CostAssumptions(**active["cost_assumptions"]), active["policy_id"]


def _active_cost_assumptions_standalone() -> tuple[CostAssumptions, str | None]:
    """Same as `_active_cost_assumptions_using`, but opens (and closes) its
    own connection - used only when /decide has no transaction_id and so no
    connection open yet. A policy-registry outage shouldn't take down
    decisioning entirely, so any failure to reach the database - not
    configured, or configured but unreachable - falls back to the day-1
    default rather than raising (see issue #1's reliability story on a
    defined fallback behavior)."""
    try:
        conn = db.get_connection()
    except (RuntimeError, psycopg.Error):
        # RuntimeError: no database URL configured at all.
        # psycopg.Error: a URL is configured but the connection attempt
        # itself failed (unreachable, timed out, refused) - the fallback
        # promised above needs to cover this too, not just "not configured".
        return DEFAULT_COST_ASSUMPTIONS, None
    try:
        with conn:
            return _active_cost_assumptions_using(conn)
    except psycopg.Error:
        return DEFAULT_COST_ASSUMPTIONS, None


def _resolve_and_decide(payload: DecideRequest, fields: dict, cost_assumptions: CostAssumptions) -> _DecisionOutcome:
    """The segment-validation + cost-engine pipeline shared by both the
    transaction_id and explicit-fields paths in `decide`, so persistence
    (which only applies to the transaction_id path) doesn't force two
    copies of this logic."""
    merchant_id = fields["merchant_id"]
    merchant_category = fields["merchant_category"]
    amount = fields["amount"]
    is_returning_customer = fields["is_returning_customer"]
    is_known_device = fields["is_known_device"]
    _require_segment_fields(merchant_category, amount, is_returning_customer, is_known_device)

    amount_band, cost_profile_source, expected_costs, action, reason_codes = _decide_action(
        payload=payload,
        merchant_id=merchant_id,
        merchant_category=merchant_category,
        amount=amount,
        is_returning_customer=is_returning_customer,
        is_known_device=is_known_device,
        cost_assumptions=cost_assumptions,
    )
    return _DecisionOutcome(
        merchant_category=merchant_category,
        amount_band=amount_band,
        is_returning_customer=is_returning_customer,
        is_known_device=is_known_device,
        cost_profile_source=cost_profile_source,
        rounded_costs={k: round(v, 2) for k, v in expected_costs.items()},
        action=action,
        reason_codes=reason_codes,
    )


def _require_segment_fields(merchant_category, amount, is_returning_customer, is_known_device) -> None:
    missing = [
        name
        for name, value in [
            ("merchant_category", merchant_category),
            ("amount", amount),
            ("is_returning_customer", is_returning_customer),
            ("is_known_device", is_known_device),
        ]
        if value is None
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required segment field(s) {missing} - supply them directly or via transaction_id.",
        )


def _decide_action(
    *,
    payload: DecideRequest,
    merchant_id: str | None,
    merchant_category: str,
    amount: float,
    is_returning_customer: bool,
    is_known_device: bool,
    cost_assumptions: CostAssumptions,
):
    """The pure cost-engine pipeline, shared by both the transaction_id and
    explicit-fields paths in `decide` so persistence (which only applies to
    the transaction_id path) doesn't force two copies of this logic."""
    amount_band = resolve_amount_band(amount)
    cost_profile, cost_profile_source = resolve_cost_profile(
        merchant_id=merchant_id,
        merchant_category=merchant_category,
        amount_band=amount_band,
        is_returning_customer=is_returning_customer,
        is_known_device=is_known_device,
        assumptions=cost_assumptions,
    )

    expected_costs = compute_expected_costs(payload.probability, amount, cost_profile)
    action = choose_action(expected_costs)
    reason_codes = build_reason_codes(
        action=action,
        expected_costs=expected_costs,
        probability=payload.probability,
        merchant_category=merchant_category,
        amount_band=amount_band,
        is_returning_customer=is_returning_customer,
        is_known_device=is_known_device,
        cost_profile_source=cost_profile_source,
    )
    return amount_band, cost_profile_source, expected_costs, action, reason_codes
