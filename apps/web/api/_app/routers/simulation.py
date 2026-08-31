"""POST /simulation/replay - the counterfactual replay engine's API surface
(ticket 08). Sources the historical window from Postgres, resolves a
calibrated fraud probability per transaction, then hands off to the pure
replay.run_replay for the actual policy comparison.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .. import db
from ..cost_engine import CostAssumptions
from ..policy import Policy
from ..replay import ReplayTransaction, run_replay
from ..schemas import (
    PolicyDefinitionRequest,
    ReplayComparisonResponse,
    ReplayRequest,
    ReplayResponse,
    SegmentReplayMetricsResponse,
)
from ..scoring import get_scoring_service
from ..transactions import get_labeled_transactions

router = APIRouter(tags=["simulation"])


def _probability_for_record(record: dict[str, Any]) -> float | None:
    """Sources the calibrated fraud probability the live decision engine
    would have used at the time. Synthetic transactions were never scored
    by the real detector - their own generation-time probability
    (transactions.generate_synthetic_transaction) is the documented proxy.
    Everything else is assumed ML-scoreable from its stored raw_features;
    returns None (skip, not fabricate) if scoring is unavailable or fails -
    see ScoreResponse's own model-unavailable fallback for the same
    reasoning.
    """
    if record["data_source"] == "synthetic":
        proxy = (record.get("raw_features") or {}).get("generation_fraud_probability")
        return float(proxy) if proxy is not None else None

    try:
        service = get_scoring_service()
        result = service.score(record.get("raw_features") or {})
    except Exception:  # noqa: BLE001 - any artifact/scoring failure just skips this row,
        # tallied as transactions_skipped rather than failing the whole replay.
        return None
    return result["fraud_probability_calibrated"]


def _policy_from_request(policy: PolicyDefinitionRequest) -> Policy:
    return Policy(
        cost_assumptions=CostAssumptions(**policy.cost_assumptions.model_dump()),
        review_capacity=policy.review_capacity,
    )


def _metrics_response(metrics) -> SegmentReplayMetricsResponse:
    return SegmentReplayMetricsResponse(
        transaction_count=metrics.transaction_count,
        fraud_loss=round(metrics.fraud_loss, 2),
        legitimate_gmv_blocked=round(metrics.legitimate_gmv_blocked, 2),
        transactions_caught=metrics.transactions_caught,
        review_count=metrics.review_count,
        net_expected_loss=round(metrics.net_expected_loss, 2),
    )


def _comparison_response(comparison) -> ReplayComparisonResponse:
    return ReplayComparisonResponse(
        baseline=_metrics_response(comparison.baseline),
        candidate=_metrics_response(comparison.candidate),
        delta=_metrics_response(comparison.delta),
    )


@router.post("/simulation/replay", response_model=ReplayResponse)
async def replay(payload: ReplayRequest) -> ReplayResponse:
    try:
        conn = db.get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    with conn:
        records = get_labeled_transactions(
            conn, data_source=payload.window.data_source, limit=payload.window.limit
        )

    transactions: list[ReplayTransaction] = []
    skipped = 0
    for record in records:
        probability = _probability_for_record(record)
        if probability is None:
            skipped += 1
            continue
        transactions.append(
            ReplayTransaction(
                transaction_id=record["transaction_id"],
                amount=float(record["amount"]),
                merchant_category=record["merchant_category"],
                amount_band=record["amount_band"],
                is_returning_customer=record["is_returning_customer"],
                is_known_device=record["is_known_device"],
                is_fraud=bool(record["is_fraud"]),
                probability=probability,
            )
        )

    if not transactions:
        raise HTTPException(
            status_code=422,
            detail="No labeled, scoreable transactions found in the requested window - nothing to replay.",
        )

    result = run_replay(
        transactions,
        baseline_policy_id=payload.baseline_policy.policy_id,
        baseline_policy=_policy_from_request(payload.baseline_policy),
        candidate_policy_id=payload.candidate_policy.policy_id,
        candidate_policy=_policy_from_request(payload.candidate_policy),
    )

    return ReplayResponse(
        baseline_policy_id=result.baseline_policy_id,
        candidate_policy_id=result.candidate_policy_id,
        transactions_replayed=result.transactions_replayed,
        transactions_skipped=skipped,
        aggregate=_comparison_response(result.aggregate),
        by_segment={seg: _comparison_response(comparison) for seg, comparison in result.by_segment.items()},
        disclaimer=result.disclaimer,
    )
