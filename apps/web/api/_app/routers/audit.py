"""GET /audit/{transaction_id} - the decision audit trail's API surface
(ticket 07)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db
from ..audit import get_decisions_for_transaction
from ..schemas import AuditTraceResponse, DecisionRecord, TransactionRecord
from ..transactions import get_transaction

router = APIRouter(tags=["audit"])


@router.get("/audit/{transaction_id}", response_model=AuditTraceResponse)
async def get_audit_trace(transaction_id: str) -> AuditTraceResponse:
    try:
        conn = db.get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    with conn:
        transaction = get_transaction(conn, transaction_id)
        if transaction is None:
            raise HTTPException(status_code=404, detail=f"No transaction with id {transaction_id!r}")
        decisions = get_decisions_for_transaction(conn, transaction_id)

    return AuditTraceResponse(
        transaction=TransactionRecord(**transaction),
        decisions=[DecisionRecord(**row) for row in decisions],
    )
