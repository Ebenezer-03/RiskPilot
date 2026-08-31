"""Pure-function tests for the review-capacity allocator (ticket 06) - the
same secondary seam pattern as test_cost_engine.py, since routing every
ranking/tie-break case through HTTP plumbing would add noise without
confidence.
"""

import pytest

from _app.review_allocation import (
    ReviewCandidate,
    allocate_reviews,
    best_non_review_action,
    expected_savings_from_review,
)

# ALLOW=50, STEP_UP=30, REVIEW=10, BLOCK=100 -> best non-review is STEP_UP (30),
# savings = 30 - 10 = 20.
COSTS_A = {"ALLOW": 50.0, "STEP_UP": 30.0, "REVIEW": 10.0, "BLOCK": 100.0}
# ALLOW=200, STEP_UP=150, REVIEW=140, BLOCK=90 -> best non-review is BLOCK (90),
# savings = 90 - 140 = -50 (review is *worse* than the best alternative here).
COSTS_B = {"ALLOW": 200.0, "STEP_UP": 150.0, "REVIEW": 140.0, "BLOCK": 90.0}


def test_best_non_review_action_picks_minimum_among_the_other_three():
    assert best_non_review_action(COSTS_A) == "STEP_UP"
    assert best_non_review_action(COSTS_B) == "BLOCK"


def test_best_non_review_action_ties_break_deterministically_by_action_order():
    # ALLOW comes before STEP_UP/BLOCK in ACTIONS.
    costs = {"ALLOW": 10.0, "STEP_UP": 10.0, "REVIEW": 999.0, "BLOCK": 10.0}
    assert best_non_review_action(costs) == "ALLOW"


def test_expected_savings_from_review_positive_when_review_beats_alternative():
    assert expected_savings_from_review(COSTS_A) == pytest.approx(20.0)


def test_expected_savings_from_review_negative_when_alternative_beats_review():
    assert expected_savings_from_review(COSTS_B) == pytest.approx(-50.0)


def test_allocate_reviews_routes_all_when_under_capacity():
    candidates = [
        ReviewCandidate("txn_1", COSTS_A),
        ReviewCandidate("txn_2", COSTS_B),
    ]
    results = allocate_reviews(candidates, daily_capacity=5)
    assert all(r.routed_to_review for r in results)
    assert all(r.final_action == "REVIEW" for r in results)


def test_allocate_reviews_ranks_by_savings_descending():
    high_savings = ReviewCandidate("txn_high", {"ALLOW": 1000.0, "STEP_UP": 500.0, "REVIEW": 10.0, "BLOCK": 900.0})
    low_savings = ReviewCandidate("txn_low", {"ALLOW": 50.0, "STEP_UP": 40.0, "REVIEW": 35.0, "BLOCK": 60.0})
    mid_savings = ReviewCandidate("txn_mid", COSTS_A)  # savings = 20.0

    results = allocate_reviews([low_savings, high_savings, mid_savings], daily_capacity=3)

    assert [r.transaction_id for r in results] == ["txn_high", "txn_mid", "txn_low"]
    assert results[0].expected_savings_from_review > results[1].expected_savings_from_review > results[2].expected_savings_from_review


def test_allocate_reviews_oversubscribed_batch_caps_and_downgrades():
    """The acceptance-criterion case: more REVIEW-eligible candidates than
    daily capacity. Only the top-N by savings stay routed to REVIEW; the
    rest are deterministically downgraded to their best non-review action,
    not silently dropped or left as REVIEW."""
    top = ReviewCandidate("txn_top", {"ALLOW": 1000.0, "STEP_UP": 500.0, "REVIEW": 10.0, "BLOCK": 900.0})  # savings=490
    mid = ReviewCandidate("txn_mid", COSTS_A)  # savings=20
    bottom = ReviewCandidate("txn_bottom", {"ALLOW": 50.0, "STEP_UP": 45.0, "REVIEW": 44.0, "BLOCK": 60.0})  # savings=1

    results = allocate_reviews([bottom, top, mid], daily_capacity=2)
    by_id = {r.transaction_id: r for r in results}

    assert by_id["txn_top"].routed_to_review is True
    assert by_id["txn_top"].final_action == "REVIEW"
    assert by_id["txn_mid"].routed_to_review is True
    assert by_id["txn_mid"].final_action == "REVIEW"

    assert by_id["txn_bottom"].routed_to_review is False
    assert by_id["txn_bottom"].final_action == best_non_review_action(bottom.expected_costs)
    assert by_id["txn_bottom"].final_action == "STEP_UP"


def test_allocate_reviews_zero_capacity_downgrades_everyone():
    candidates = [ReviewCandidate("txn_1", COSTS_A), ReviewCandidate("txn_2", COSTS_B)]
    results = allocate_reviews(candidates, daily_capacity=0)
    assert all(not r.routed_to_review for r in results)
    assert all(r.final_action != "REVIEW" for r in results)


def test_allocate_reviews_ties_broken_by_input_order():
    tied_1 = ReviewCandidate("txn_first", COSTS_A)
    tied_2 = ReviewCandidate("txn_second", dict(COSTS_A))  # identical savings
    results = allocate_reviews([tied_1, tied_2], daily_capacity=1)
    assert results[0].transaction_id == "txn_first"
    assert results[0].routed_to_review is True
    assert results[1].transaction_id == "txn_second"
    assert results[1].routed_to_review is False


def test_allocate_reviews_negative_capacity_raises():
    with pytest.raises(ValueError):
        allocate_reviews([ReviewCandidate("txn_1", COSTS_A)], daily_capacity=-1)


def test_allocate_reviews_empty_batch_returns_empty():
    assert allocate_reviews([], daily_capacity=10) == []
