"""GET /audit/{transaction_id} - the decision audit trail's API surface
(ticket 07). Also GET /audit/trends/daily - the approval-rate/fraud-loss/
false-positive trend behind the Audit & Monitoring dashboard (ticket 12).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from . import get_connection_or_503
from ..audit import get_daily_trends, get_decisions_for_transaction
from ..schemas import AuditTraceResponse, AuditTrendsResponse, DecisionRecord, TransactionRecord, TrendPoint
from ..transactions import get_transaction

router = APIRouter(tags=["audit"])


# Registered before /audit/{transaction_id} so "trends" doesn't get
# swallowed by the transaction_id path parameter.
@router.get("/audit/trends/daily", response_model=AuditTrendsResponse)
async def get_audit_trends(days: int = Query(default=30, ge=1, le=365)) -> AuditTrendsResponse:
    conn = get_connection_or_503()
    with conn:
        rows = get_daily_trends(conn, days)

    points = [
        TrendPoint(
            day=row["day"],
            total_decisions=row["total_decisions"],
            approval_rate=row["allow_count"] / row["total_decisions"] if row["total_decisions"] else 0.0,
            false_positive_rate=(row["false_positive_count"] / row["legitimate_count"])
            if row["legitimate_count"]
            else None,
            fraud_loss=row["fraud_loss"],
        )
        for row in rows
    ]
    return AuditTrendsResponse(window_days=days, points=points)


@router.get("/audit/{transaction_id}", response_model=AuditTraceResponse)
async def get_audit_trace(transaction_id: str) -> AuditTraceResponse:
    conn = get_connection_or_503()

    with conn:
        transaction = get_transaction(conn, transaction_id)
        if transaction is None:
            raise HTTPException(status_code=404, detail=f"No transaction with id {transaction_id!r}")
        decisions = get_decisions_for_transaction(conn, transaction_id)

    return AuditTraceResponse(
        transaction=TransactionRecord(**transaction),
        decisions=[DecisionRecord(**row) for row in decisions],
    )
