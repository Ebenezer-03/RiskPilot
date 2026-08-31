"""POST /review/allocate - the review-capacity allocator's API surface
(ticket 06)."""

from __future__ import annotations

from fastapi import APIRouter

from ..review_allocation import ReviewCandidate, allocate_reviews
from ..schemas import ReviewAllocationRequest, ReviewAllocationResponse, ReviewAllocationResultItem

router = APIRouter(tags=["review-allocation"])


@router.post("/review/allocate", response_model=ReviewAllocationResponse)
async def allocate(payload: ReviewAllocationRequest) -> ReviewAllocationResponse:
    candidates = [ReviewCandidate(item.transaction_id, item.expected_costs) for item in payload.items]
    results = allocate_reviews(candidates, payload.daily_capacity)

    result_items = [
        ReviewAllocationResultItem(
            transaction_id=r.transaction_id,
            expected_savings_from_review=round(r.expected_savings_from_review, 2),
            routed_to_review=r.routed_to_review,
            final_action=r.final_action,
        )
        for r in results
    ]

    return ReviewAllocationResponse(
        daily_capacity=payload.daily_capacity,
        total_candidates=len(result_items),
        routed_to_review_count=sum(1 for r in result_items if r.routed_to_review),
        results=result_items,
    )
