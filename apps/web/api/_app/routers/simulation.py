"""POST /simulation/replay - the counterfactual replay engine's API surface
(ticket 08). Sources the historical window from Postgres, resolves a
calibrated fraud probability per transaction, then hands off to the pure
replay.run_replay for the actual policy comparison. The DB/scoring/response
glue lives in simulation_support.py, shared with routers/policies.py's
/simulate (ticket 09).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import get_connection_or_503
from ..schemas import ReplayRequest, ReplayResponse
from ..simulation_support import fetch_replay_window, policy_from_request, replay_result_to_response, run_replay

router = APIRouter(tags=["simulation"])


@router.post("/simulation/replay", response_model=ReplayResponse)
async def replay(payload: ReplayRequest) -> ReplayResponse:
    conn = get_connection_or_503()

    with conn:
        transactions, skipped = fetch_replay_window(conn, payload.window)

    if not transactions:
        raise HTTPException(
            status_code=422,
            detail="No labeled, scoreable transactions found in the requested window - nothing to replay.",
        )

    result = run_replay(
        transactions,
        baseline_policy_id=payload.baseline_policy.policy_id,
        baseline_policy=policy_from_request(payload.baseline_policy.cost_assumptions, payload.baseline_policy.review_capacity),
        candidate_policy_id=payload.candidate_policy.policy_id,
        candidate_policy=policy_from_request(payload.candidate_policy.cost_assumptions, payload.candidate_policy.review_capacity),
    )

    return replay_result_to_response(result, transactions_skipped=skipped)
