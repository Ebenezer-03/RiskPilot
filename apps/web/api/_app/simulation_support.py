"""Shared API-layer glue between Postgres/the scoring service and the pure
replay engine (replay.py) - used by both routers/simulation.py (ticket 08's
ad-hoc replay endpoint) and routers/policies.py (ticket 09's /simulate,
which runs the exact same kind of replay against a registered policy).
Kept out of replay.py itself so that module stays a pure function with no
DB/ML-scoring dependency, and out of either router so the two don't
duplicate it.
"""

from __future__ import annotations

from typing import Any

import psycopg

from .cost_engine import CostAssumptions
from .policy import Policy
from .replay import ReplayComparison, ReplayResult, ReplayTransaction, SegmentReplayMetrics, run_replay
from .schemas import (
    CostAssumptionsRequest,
    ReplayComparisonResponse,
    ReplayResponse,
    ReplayWindowRequest,
    SegmentReplayMetricsResponse,
)
from .scoring import get_scoring_service
from .transactions import get_labeled_transactions


def probability_for_record(record: dict[str, Any]) -> float | None:
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


def policy_from_request(cost_assumptions: CostAssumptionsRequest, review_capacity: int) -> Policy:
    return Policy(cost_assumptions=CostAssumptions(**cost_assumptions.model_dump()), review_capacity=review_capacity)


def fetch_replay_window(
    conn: psycopg.Connection, window: ReplayWindowRequest
) -> tuple[list[ReplayTransaction], int]:
    """Returns (transactions, skipped_count). Requires an already-open
    connection (callers hold it open across other queries in the same
    request - see routers/policies.py's /simulate)."""
    records = get_labeled_transactions(conn, data_source=window.data_source, limit=window.limit)

    transactions: list[ReplayTransaction] = []
    skipped = 0
    for record in records:
        probability = probability_for_record(record)
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
                event_time=record["event_time"],
            )
        )
    return transactions, skipped


def metrics_response(metrics: SegmentReplayMetrics) -> SegmentReplayMetricsResponse:
    return SegmentReplayMetricsResponse(
        transaction_count=metrics.transaction_count,
        fraud_count=metrics.fraud_count,
        allow_count=metrics.allow_count,
        fraud_loss=round(metrics.fraud_loss, 2),
        legitimate_gmv_blocked=round(metrics.legitimate_gmv_blocked, 2),
        legitimate_blocked_count=metrics.legitimate_blocked_count,
        transactions_caught=metrics.transactions_caught,
        review_count=metrics.review_count,
        review_eligible_count=metrics.review_eligible_count,
        net_expected_loss=round(metrics.net_expected_loss, 2),
    )


def comparison_response(comparison: ReplayComparison) -> ReplayComparisonResponse:
    return ReplayComparisonResponse(
        baseline=metrics_response(comparison.baseline),
        candidate=metrics_response(comparison.candidate),
        delta=metrics_response(comparison.delta),
    )


def replay_result_to_response(result: ReplayResult, *, transactions_skipped: int) -> ReplayResponse:
    return ReplayResponse(
        baseline_policy_id=result.baseline_policy_id,
        candidate_policy_id=result.candidate_policy_id,
        transactions_replayed=result.transactions_replayed,
        transactions_skipped=transactions_skipped,
        aggregate=comparison_response(result.aggregate),
        by_segment={seg: comparison_response(comparison) for seg, comparison in result.by_segment.items()},
        calibration_brier_score=round(result.calibration_brier_score, 6),
        window_days=result.window_days,
        disclaimer=result.disclaimer,
    )


__all__ = [
    "probability_for_record",
    "policy_from_request",
    "fetch_replay_window",
    "metrics_response",
    "comparison_response",
    "replay_result_to_response",
    "run_replay",
]
