"""CRUD + DRAFT -> SIMULATED -> ACTIVE lifecycle + guardrails for the
policy registry (ticket 09). APPROVED/CANARY/ROLLED_BACK are valid DB/type
values but unreachable through this router - see db.py's schema comment.
"""

from __future__ import annotations

from dataclasses import asdict

import psycopg
from fastapi import APIRouter, HTTPException

from .. import db, policy_registry
from ..guardrails import GuardrailThresholds, evaluate_guardrails
from ..policy import DEFAULT_POLICY
from ..replay import ReplayComparison, ReplayResult, SegmentReplayMetrics
from ..schemas import (
    CostAssumptionsRequest,
    GuardrailViolationResponse,
    PolicyCreateRequest,
    PolicyPromoteRequest,
    PolicyPromotionResponse,
    PolicyRecord,
    PolicySimulateRequest,
    PolicyWriteRequest,
)
from ..simulation_support import fetch_replay_window, policy_from_request, run_replay

router = APIRouter(prefix="/policies", tags=["policies"])


def _record_to_schema(row: dict) -> PolicyRecord:
    return PolicyRecord(
        policy_id=row["policy_id"],
        name=row["name"],
        status=row["status"],
        cost_assumptions=CostAssumptionsRequest(**row["cost_assumptions"]),
        review_capacity=row["review_capacity"],
        baseline_policy_id=row["baseline_policy_id"],
        replay_result=row["replay_result"],
        guardrail_violations=row["guardrail_violations"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        simulated_at=row["simulated_at"],
        activated_at=row["activated_at"],
    )


def _get_connection() -> psycopg.Connection:
    try:
        return db.get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _get_or_404(conn, policy_id: str) -> dict:
    row = policy_registry.get_policy(conn, policy_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No policy with id {policy_id!r}")
    return row


def _or_409_lost_race(row: dict | None, policy_id: str, action: str) -> dict:
    """The three lifecycle-transition queries in policy_registry.py are all
    conditional UPDATEs (`WHERE status = '<expected>'`), so a concurrent
    request that changes `policy_id`'s status between this handler's own
    status check and its UPDATE makes that UPDATE match zero rows - `row`
    comes back None instead of raising. Surface that race as a 409 (the
    same status the caller would have gotten if their own check had run a
    moment later) rather than crashing on `row["..."]` against None.
    """
    if row is None:
        raise HTTPException(
            status_code=409,
            detail=f"policy {policy_id!r}'s status changed concurrently - could not {action}, please retry",
        )
    return row


@router.post("", response_model=PolicyRecord, status_code=201)
async def create_policy(payload: PolicyCreateRequest) -> PolicyRecord:
    conn = _get_connection()
    with conn:
        if policy_registry.get_policy(conn, payload.policy_id) is not None:
            raise HTTPException(status_code=409, detail=f"policy_id {payload.policy_id!r} already exists")
        try:
            row = policy_registry.insert_policy(
                conn,
                policy_id=payload.policy_id,
                name=payload.name,
                cost_assumptions=payload.cost_assumptions.model_dump(),
                review_capacity=payload.review_capacity,
            )
        except psycopg.errors.UniqueViolation as exc:
            # A concurrent POST with the same policy_id won the check-then-insert
            # race above - the UNIQUE constraint is the real source of truth.
            raise HTTPException(status_code=409, detail=f"policy_id {payload.policy_id!r} already exists") from exc
    return _record_to_schema(row)


@router.get("", response_model=list[PolicyRecord])
async def list_policies(status: str | None = None) -> list[PolicyRecord]:
    conn = _get_connection()
    with conn:
        rows = policy_registry.list_policies(conn, status=status)
    return [_record_to_schema(row) for row in rows]


@router.get("/{policy_id}", response_model=PolicyRecord)
async def get_policy(policy_id: str) -> PolicyRecord:
    conn = _get_connection()
    with conn:
        row = _get_or_404(conn, policy_id)
    return _record_to_schema(row)


@router.put("/{policy_id}", response_model=PolicyRecord)
async def update_policy(policy_id: str, payload: PolicyWriteRequest) -> PolicyRecord:
    conn = _get_connection()
    with conn:
        existing = _get_or_404(conn, policy_id)
        if existing["status"] != "DRAFT":
            raise HTTPException(
                status_code=409, detail=f"policy {policy_id!r} is {existing['status']}, not DRAFT - cannot edit"
            )
        row = policy_registry.update_draft_policy(
            conn,
            policy_id,
            name=payload.name,
            cost_assumptions=payload.cost_assumptions.model_dump(),
            review_capacity=payload.review_capacity,
        )
        row = _or_409_lost_race(row, policy_id, "update")
    return _record_to_schema(row)


@router.delete("/{policy_id}", status_code=204, response_model=None)
async def delete_policy(policy_id: str) -> None:
    conn = _get_connection()
    with conn:
        existing = _get_or_404(conn, policy_id)
        if existing["status"] != "DRAFT":
            raise HTTPException(
                status_code=409, detail=f"policy {policy_id!r} is {existing['status']}, not DRAFT - cannot delete"
            )
        deleted = policy_registry.delete_draft_policy(conn, policy_id)
        if not deleted:
            raise HTTPException(
                status_code=409,
                detail=f"policy {policy_id!r}'s status changed concurrently - could not delete, please retry",
            )


@router.post("/{policy_id}/simulate", response_model=PolicyRecord)
async def simulate_policy(policy_id: str, payload: PolicySimulateRequest) -> PolicyRecord:
    """DRAFT -> SIMULATED: replays this policy (as candidate) against a
    baseline (an explicit `baseline_policy_id`, else the current ACTIVE
    policy, else the day-1 default policy) over the given historical
    window, and stores the replay output for /promote to judge later."""
    conn = _get_connection()
    with conn:
        candidate_row = _get_or_404(conn, policy_id)
        if candidate_row["status"] != "DRAFT":
            raise HTTPException(
                status_code=409, detail=f"policy {policy_id!r} is {candidate_row['status']}, not DRAFT - cannot simulate"
            )

        if payload.baseline_policy_id:
            baseline_row = policy_registry.get_policy(conn, payload.baseline_policy_id)
            if baseline_row is None:
                raise HTTPException(
                    status_code=404, detail=f"No baseline policy with id {payload.baseline_policy_id!r}"
                )
            baseline_policy_id = baseline_row["policy_id"]
            baseline_policy = policy_from_request(
                CostAssumptionsRequest(**baseline_row["cost_assumptions"]), baseline_row["review_capacity"]
            )
        else:
            active_row = policy_registry.get_current_active_policy(conn)
            if active_row is not None:
                baseline_policy_id = active_row["policy_id"]
                baseline_policy = policy_from_request(
                    CostAssumptionsRequest(**active_row["cost_assumptions"]), active_row["review_capacity"]
                )
            else:
                baseline_policy_id = "default-day1-policy"
                baseline_policy = DEFAULT_POLICY

        candidate_policy = policy_from_request(
            CostAssumptionsRequest(**candidate_row["cost_assumptions"]), candidate_row["review_capacity"]
        )

        transactions, _skipped = fetch_replay_window(conn, payload.window)
        if not transactions:
            raise HTTPException(
                status_code=422,
                detail="No labeled, scoreable transactions found in the requested window - nothing to simulate.",
            )

        replay_result = run_replay(
            transactions,
            baseline_policy_id=baseline_policy_id,
            baseline_policy=baseline_policy,
            candidate_policy_id=policy_id,
            candidate_policy=candidate_policy,
        )

        row = policy_registry.transition_to_simulated(
            conn, policy_id, baseline_policy_id=baseline_policy_id, replay_result=_replay_result_to_dict(replay_result)
        )
        row = _or_409_lost_race(row, policy_id, "simulate")
    return _record_to_schema(row)


@router.post("/{policy_id}/promote", response_model=PolicyPromotionResponse)
async def promote_policy(policy_id: str, payload: PolicyPromoteRequest) -> PolicyPromotionResponse:
    """SIMULATED -> ACTIVE, gated by the five guardrails (ticket 09)
    evaluated against the replay output stored by /simulate - not
    recomputed, so a promotion decision is always traceable to the exact
    replay it was judged against."""
    conn = _get_connection()
    with conn:
        row = _get_or_404(conn, policy_id)
        if row["status"] != "SIMULATED":
            raise HTTPException(
                status_code=409, detail=f"policy {policy_id!r} is {row['status']}, not SIMULATED - cannot promote"
            )

        replay_result = _replay_result_from_dict(row["replay_result"])
        thresholds = GuardrailThresholds(
            **{
                field: value
                for field, value in payload.thresholds.model_dump().items()
                if value is not None
            }
        )
        violations = evaluate_guardrails(
            replay_result, candidate_review_capacity=row["review_capacity"], thresholds=thresholds
        )

        if violations:
            updated = policy_registry.record_guardrail_rejection(
                conn, policy_id, violations=[{"guardrail": v.guardrail, "detail": v.detail} for v in violations]
            )
            updated = _or_409_lost_race(updated, policy_id, "record the rejected promotion")
            return PolicyPromotionResponse(
                policy=_record_to_schema(updated),
                approved=False,
                violations=[GuardrailViolationResponse(guardrail=v.guardrail, detail=v.detail) for v in violations],
            )

        updated = policy_registry.transition_to_active(conn, policy_id)
        updated = _or_409_lost_race(updated, policy_id, "promote")
    return PolicyPromotionResponse(policy=_record_to_schema(updated), approved=True, violations=[])


def _replay_result_to_dict(result: ReplayResult) -> dict:
    """JSONB-storable snapshot of the replay output /promote later judges
    guardrails against - dataclasses aren't JSON-serializable directly."""
    return asdict(result)


def _replay_result_from_dict(data: dict) -> ReplayResult:
    return ReplayResult(
        baseline_policy_id=data["baseline_policy_id"],
        candidate_policy_id=data["candidate_policy_id"],
        transactions_replayed=data["transactions_replayed"],
        aggregate=ReplayComparison(
            baseline=SegmentReplayMetrics(**data["aggregate"]["baseline"]),
            candidate=SegmentReplayMetrics(**data["aggregate"]["candidate"]),
            delta=SegmentReplayMetrics(**data["aggregate"]["delta"]),
        ),
        by_segment={
            seg: ReplayComparison(
                baseline=SegmentReplayMetrics(**comparison["baseline"]),
                candidate=SegmentReplayMetrics(**comparison["candidate"]),
                delta=SegmentReplayMetrics(**comparison["delta"]),
            )
            for seg, comparison in data["by_segment"].items()
        },
        calibration_brier_score=data["calibration_brier_score"],
        window_days=data["window_days"],
        disclaimer=data["disclaimer"],
    )
