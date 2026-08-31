"""Review-capacity allocator (ticket 06). Given a batch of REVIEW-eligible
decisions and a daily capacity cap, ranks them by ExpectedSavingsFromReview
and routes only the top-N (up to the cap) to actual review; the rest are
deterministically downgraded to their next-best non-REVIEW action.

Per issue #1's Implementation Decisions: greedy top-K ranking is provably
optimal for a simple count-capped selection with no additional constraints
(no per-merchant quotas, no hourly buckets) - no ILP/constraint solver for
MVP.

    ExpectedSavingsFromReview = E[C_best_non_review_action] - E[C_review]
"""

from __future__ import annotations

from dataclasses import dataclass

from .cost_engine import ACTIONS, Action


@dataclass(frozen=True)
class ReviewCandidate:
    transaction_id: str
    expected_costs: dict[Action, float]  # all four expected costs, as computed by cost_engine


@dataclass(frozen=True)
class ReviewAllocationResult:
    transaction_id: str
    expected_savings_from_review: float
    routed_to_review: bool
    final_action: Action


_NON_REVIEW_ACTIONS: tuple[Action, ...] = tuple(a for a in ACTIONS if a != "REVIEW")


def best_non_review_action(expected_costs: dict[Action, float]) -> Action:
    """The minimum-expected-cost action among ALLOW/STEP_UP/BLOCK - what a
    REVIEW-eligible transaction gets downgraded to when it doesn't make the
    daily review cap. Ties broken deterministically by ACTIONS order, same
    as cost_engine.choose_action."""
    return min(_NON_REVIEW_ACTIONS, key=lambda action: expected_costs[action])


def expected_savings_from_review(expected_costs: dict[Action, float]) -> float:
    """E[C_best_non_review_action] - E[C_review]. Positive means review is
    expected to save money relative to the best alternative action; the
    higher this value, the more valuable it is to spend scarce review
    capacity on this transaction."""
    best_alternative_cost = expected_costs[best_non_review_action(expected_costs)]
    return best_alternative_cost - expected_costs["REVIEW"]


def allocate_reviews(
    candidates: list[ReviewCandidate], daily_capacity: int
) -> list[ReviewAllocationResult]:
    """Ranks `candidates` by ExpectedSavingsFromReview (descending) and
    routes only the top `daily_capacity` to REVIEW. Transactions beyond the
    cap are downgraded to their best non-REVIEW action instead.

    Ties in ExpectedSavingsFromReview are broken by input order: Python's
    sort is stable, and `reverse=True` preserves that stability for equal
    keys, so two candidates with identical savings keep their relative
    submission order rather than depending on arbitrary comparison order.
    """
    if daily_capacity < 0:
        raise ValueError("daily_capacity must be >= 0")

    scored = [(candidate, expected_savings_from_review(candidate.expected_costs)) for candidate in candidates]
    ranked = sorted(scored, key=lambda pair: pair[1], reverse=True)

    results = []
    for rank, (candidate, savings) in enumerate(ranked):
        routed = rank < daily_capacity
        final_action: Action = "REVIEW" if routed else best_non_review_action(candidate.expected_costs)
        results.append(
            ReviewAllocationResult(
                transaction_id=candidate.transaction_id,
                expected_savings_from_review=savings,
                routed_to_review=routed,
                final_action=final_action,
            )
        )
    return results
