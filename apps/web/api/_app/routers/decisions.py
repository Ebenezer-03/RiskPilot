"""POST /decide - the cost-aware decision engine's API surface (ticket 05).
Also persists every decision made against a known transaction_id for the
audit trail (ticket 07) - see ../audit.py.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db
from ..audit import insert_decision
from ..cost_engine import (
    COST_MATRIX_VERSION,
    POLICY_VERSION,
    build_reason_codes,
    choose_action,
    compute_expected_costs,
    resolve_cost_profile,
)
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

    # One connection for the whole request - not one for the transaction
    # lookup and a second for the audit-trail insert below. Left open (not
    # entered via `with`) until the single `with conn:` block further down,
    # which spans both the lookup and the insert.
    conn = None
    if payload.transaction_id:
        try:
            conn = db.get_connection()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
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
            )
            rounded_costs = {k: round(v, 2) for k, v in expected_costs.items()}

            insert_decision(
                conn,
                {
                    "transaction_id": payload.transaction_id,
                    "data_source": data_source,
                    "probability_used": payload.probability,
                    "action": action,
                    "expected_costs": rounded_costs,
                    "reason_codes": reason_codes,
                    "merchant_category": merchant_category,
                    "amount_band": amount_band,
                    "is_returning_customer": is_returning_customer,
                    "is_known_device": is_known_device,
                    "cost_profile_source": cost_profile_source,
                    "model_version": payload.model_version,
                    "calibration_version": payload.calibration_version,
                    "feature_schema_version": payload.feature_schema_version,
                    "segment_definition_version": SEGMENT_DEFINITION_VERSION,
                    "policy_version": POLICY_VERSION,
                    "cost_matrix_version": COST_MATRIX_VERSION,
                },
            )
    else:
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
        )
        rounded_costs = {k: round(v, 2) for k, v in expected_costs.items()}

    return DecideResponse(
        transaction_id=payload.transaction_id,
        decision=action,
        expected_costs=rounded_costs,
        probability_used=payload.probability,
        merchant_category=merchant_category,
        amount_band=amount_band,
        is_returning_customer=is_returning_customer,
        is_known_device=is_known_device,
        cost_profile_source=cost_profile_source,
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
