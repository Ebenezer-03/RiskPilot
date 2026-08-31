"""Pure-function tests for the replay engine (ticket 08), mirroring
test_cost_engine.py's and test_review_allocation.py's secondary-seam
testing decision: the replay aggregation/delta math is a pure function
worth unit-testing directly, on top of the API-seam test in
test_simulation_api.py.
"""

from datetime import datetime, timezone

from _app.cost_engine import DEFAULT_COST_ASSUMPTIONS, CostAssumptions
from _app.policy import DEFAULT_POLICY, Policy
from _app.replay import ReplayTransaction, run_replay


def test_identical_baseline_and_candidate_policies_produce_zero_delta():
    """A sanity invariant: replaying the same policy against itself must
    show no change anywhere."""
    transactions = [
        ReplayTransaction(
            transaction_id="txn_1",
            amount=500,
            merchant_category="food_delivery",
            amount_band="low",
            is_returning_customer=True,
            is_known_device=True,
            is_fraud=False,
            probability=0.02,
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        ReplayTransaction(
            transaction_id="txn_2",
            amount=20000,
            merchant_category="electronics",
            amount_band="high",
            is_returning_customer=False,
            is_known_device=False,
            is_fraud=True,
            probability=0.95,
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ]

    result = run_replay(
        transactions,
        baseline_policy_id="baseline",
        baseline_policy=DEFAULT_POLICY,
        candidate_policy_id="candidate",
        candidate_policy=DEFAULT_POLICY,
    )

    metrics_cls = type(result.aggregate.delta)
    zero_fields = {name: (0.0 if name in ("fraud_loss", "legitimate_gmv_blocked", "net_expected_loss") else 0)
                   for name in metrics_cls.__dataclass_fields__}
    assert result.aggregate.delta == metrics_cls(**zero_fields)
    for comparison in result.by_segment.values():
        assert comparison.baseline == comparison.candidate


def test_aggregate_metrics_match_hand_computed_arithmetic():
    """txn_1: p=0.02, low/returning/known, amount=500 -> ALLOW (E_allow=11,
    per test_decisions_api.py's identical case). txn_2: p=0.95, high/new/new,
    amount=20000 -> BLOCK (E_block=400) - see both tickets' own worked
    comments for the arithmetic.
    """
    transactions = [
        ReplayTransaction(
            transaction_id="txn_1",
            amount=500,
            merchant_category="food_delivery",
            amount_band="low",
            is_returning_customer=True,
            is_known_device=True,
            is_fraud=False,
            probability=0.02,
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        ReplayTransaction(
            transaction_id="txn_2",
            amount=20000,
            merchant_category="electronics",
            amount_band="high",
            is_returning_customer=False,
            is_known_device=False,
            is_fraud=True,
            probability=0.95,
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ]

    result = run_replay(
        transactions,
        baseline_policy_id="baseline",
        baseline_policy=DEFAULT_POLICY,
        candidate_policy_id="candidate",
        candidate_policy=DEFAULT_POLICY,
    )

    baseline = result.aggregate.baseline
    assert baseline.transaction_count == 2
    assert baseline.fraud_count == 1  # txn_2
    assert baseline.allow_count == 1  # txn_1
    # txn_2 is truly fraud and BLOCK's catch probability is 1.0 -> fully
    # prevented, contributes 0 realized fraud loss.
    assert baseline.fraud_loss == 0.0
    # Neither transaction is a legitimate one that got BLOCKed.
    assert baseline.legitimate_gmv_blocked == 0.0
    assert baseline.legitimate_blocked_count == 0
    assert baseline.transactions_caught == 1  # txn_2, BLOCK != ALLOW
    assert baseline.review_count == 0
    assert baseline.review_eligible_count == 0
    assert round(baseline.net_expected_loss, 2) == round(11.0 + 400.0, 2)
    # Brier score: (0.02-0)^2 + (0.95-1)^2, averaged over 2 transactions.
    assert round(result.calibration_brier_score, 6) == round(((0.02**2) + (0.05**2)) / 2, 6)
    # Both transactions share the same event_time -> a single-day window.
    assert result.window_days == 1


def test_downgrading_review_capacity_shows_correct_delta_direction():
    """Same transaction (p=0.3, medium/new_customer/known_device,
    amount=5000 -> REVIEW at E_review=369.5, next-best STEP_UP at 820 - see
    test_decisions_api.py's identical case) replayed under a policy with
    review capacity vs. one with none. Zero-capacity forces a downgrade to
    STEP_UP - a strictly worse (higher expected cost) outcome, since REVIEW
    was already the cost-minimizing action - so net_expected_loss must
    increase and review_count must drop by exactly one.
    """
    transactions = [
        ReplayTransaction(
            transaction_id="txn_1",
            amount=5000,
            merchant_category="digital_goods",
            amount_band="medium",
            is_returning_customer=False,
            is_known_device=True,
            is_fraud=False,
            probability=0.3,
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ]

    baseline_policy = Policy(cost_assumptions=DEFAULT_COST_ASSUMPTIONS, review_capacity=10)
    candidate_policy = Policy(cost_assumptions=DEFAULT_COST_ASSUMPTIONS, review_capacity=0)

    result = run_replay(
        transactions,
        baseline_policy_id="baseline",
        baseline_policy=baseline_policy,
        candidate_policy_id="candidate",
        candidate_policy=candidate_policy,
    )

    assert result.aggregate.baseline.review_count == 1
    assert result.aggregate.candidate.review_count == 0
    assert result.aggregate.delta.review_count == -1
    # Both policies chose REVIEW before the capacity cap applied -
    # review_eligible_count reflects that raw choice, unaffected by either
    # policy's own review_capacity.
    assert result.aggregate.baseline.review_eligible_count == 1
    assert result.aggregate.candidate.review_eligible_count == 1
    assert round(result.aggregate.baseline.net_expected_loss, 2) == 369.5
    assert round(result.aggregate.candidate.net_expected_loss, 2) == 820.0
    assert result.aggregate.delta.net_expected_loss > 0


def test_per_segment_breakdown_matches_aggregate():
    transactions = [
        ReplayTransaction(
            transaction_id="txn_1",
            amount=500,
            merchant_category="food_delivery",
            amount_band="low",
            is_returning_customer=True,
            is_known_device=True,
            is_fraud=False,
            probability=0.02,
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        ReplayTransaction(
            transaction_id="txn_2",
            amount=20000,
            merchant_category="electronics",
            amount_band="high",
            is_returning_customer=False,
            is_known_device=False,
            is_fraud=True,
            probability=0.95,
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ]

    result = run_replay(
        transactions,
        baseline_policy_id="baseline",
        baseline_policy=DEFAULT_POLICY,
        candidate_policy_id="candidate",
        candidate_policy=DEFAULT_POLICY,
    )

    assert len(result.by_segment) == 2  # two distinct segments, one txn each
    total_count = sum(c.baseline.transaction_count for c in result.by_segment.values())
    assert total_count == result.aggregate.baseline.transaction_count


def test_run_replay_rejects_empty_window():
    import pytest

    with pytest.raises(ValueError):
        run_replay(
            [],
            baseline_policy_id="baseline",
            baseline_policy=DEFAULT_POLICY,
            candidate_policy_id="candidate",
            candidate_policy=DEFAULT_POLICY,
        )


def test_disclaimer_is_always_present():
    transactions = [
        ReplayTransaction(
            transaction_id="txn_1",
            amount=500,
            merchant_category="food_delivery",
            amount_band="low",
            is_returning_customer=True,
            is_known_device=True,
            is_fraud=False,
            probability=0.02,
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    ]
    result = run_replay(
        transactions,
        baseline_policy_id="baseline",
        baseline_policy=DEFAULT_POLICY,
        candidate_policy_id="candidate",
        candidate_policy=DEFAULT_POLICY,
    )
    assert "offline estimate" in result.disclaimer.lower()
    assert "not a causal" in result.disclaimer.lower()


def test_window_days_spans_the_earliest_to_latest_event_time():
    transactions = [
        ReplayTransaction(
            transaction_id="txn_1",
            amount=500,
            merchant_category="food_delivery",
            amount_band="low",
            is_returning_customer=True,
            is_known_device=True,
            is_fraud=False,
            probability=0.02,
            event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        ReplayTransaction(
            transaction_id="txn_2",
            amount=500,
            merchant_category="food_delivery",
            amount_band="low",
            is_returning_customer=True,
            is_known_device=True,
            is_fraud=False,
            probability=0.02,
            event_time=datetime(2026, 1, 11, tzinfo=timezone.utc),
        ),
    ]
    result = run_replay(
        transactions,
        baseline_policy_id="baseline",
        baseline_policy=DEFAULT_POLICY,
        candidate_policy_id="candidate",
        candidate_policy=DEFAULT_POLICY,
    )
    # Jan 1 -> Jan 11 is 10 days apart, +1 to count both endpoint days.
    assert result.window_days == 11
