"""Pure-function tests for the five promotion guardrails (ticket 09),
constructing ReplayResult objects directly rather than running a real
replay - isolates each guardrail's own threshold logic from the replay
engine already covered by test_replay.py.
"""

from _app.guardrails import GuardrailThresholds, evaluate_guardrails
from _app.replay import ReplayComparison, ReplayResult, SegmentReplayMetrics


def _metrics(**overrides) -> SegmentReplayMetrics:
    defaults = dict(
        transaction_count=100,
        fraud_count=10,
        allow_count=80,
        fraud_loss=0.0,
        legitimate_gmv_blocked=0.0,
        legitimate_blocked_count=0,
        transactions_caught=10,
        review_count=5,
        review_eligible_count=5,
        net_expected_loss=1000.0,
    )
    defaults.update(overrides)
    return SegmentReplayMetrics(**defaults)


def _result(
    *, baseline: SegmentReplayMetrics, candidate: SegmentReplayMetrics, calibration_brier_score=0.02, by_segment=None,
    window_days=1,
) -> ReplayResult:
    by_segment = by_segment or {"seg_1": ReplayComparison(baseline=baseline, candidate=candidate, delta=candidate)}
    return ReplayResult(
        baseline_policy_id="baseline",
        candidate_policy_id="candidate",
        transactions_replayed=baseline.transaction_count,
        aggregate=ReplayComparison(baseline=baseline, candidate=candidate, delta=candidate),
        by_segment=by_segment,
        calibration_brier_score=calibration_brier_score,
        window_days=window_days,
    )


def test_no_violations_for_an_identical_candidate():
    metrics = _metrics()
    result = _result(baseline=metrics, candidate=metrics)
    violations = evaluate_guardrails(result, candidate_review_capacity=1000)
    assert violations == []


def test_approval_rate_drop_is_flagged():
    baseline = _metrics(allow_count=80, transaction_count=100)
    # Approval rate drops from 80% to 50% - a 30pt drop, past the 10pt default.
    candidate = _metrics(allow_count=50, transaction_count=100)
    result = _result(baseline=baseline, candidate=candidate)
    violations = evaluate_guardrails(result, candidate_review_capacity=1000)
    assert any(v.guardrail == "approval_rate_drop" for v in violations)


def test_approval_rate_drop_within_threshold_is_not_flagged():
    baseline = _metrics(allow_count=80, transaction_count=100)
    candidate = _metrics(allow_count=75, transaction_count=100)  # 5pt drop, under the 10pt default
    result = _result(baseline=baseline, candidate=candidate)
    violations = evaluate_guardrails(result, candidate_review_capacity=1000)
    assert not any(v.guardrail == "approval_rate_drop" for v in violations)


def test_review_queue_overflow_is_flagged_when_eligible_exceeds_capacity():
    metrics = _metrics(review_eligible_count=50)
    result = _result(baseline=metrics, candidate=metrics)
    violations = evaluate_guardrails(result, candidate_review_capacity=10)
    assert any(v.guardrail == "review_queue_overflow" for v in violations)


def test_review_queue_overflow_is_not_flagged_within_capacity():
    metrics = _metrics(review_eligible_count=5)
    result = _result(baseline=metrics, candidate=metrics)
    violations = evaluate_guardrails(result, candidate_review_capacity=10)
    assert not any(v.guardrail == "review_queue_overflow" for v in violations)


def test_review_queue_overflow_normalizes_by_window_days():
    """100 review-eligible transactions over a 10-day window is 10/day -
    within a daily capacity of 20 - even though the window *total* (100)
    exceeds it; the reverse (a short window inflating a rate) must also not
    falsely pass."""
    metrics = _metrics(review_eligible_count=100)
    result = _result(baseline=metrics, candidate=metrics, window_days=10)
    violations = evaluate_guardrails(result, candidate_review_capacity=20)
    assert not any(v.guardrail == "review_queue_overflow" for v in violations)

    result_single_day = _result(baseline=metrics, candidate=metrics, window_days=1)
    violations_single_day = evaluate_guardrails(result_single_day, candidate_review_capacity=20)
    assert any(v.guardrail == "review_queue_overflow" for v in violations_single_day)


def test_sample_size_floor_is_flagged_for_an_undersized_segment():
    metrics = _metrics()
    small_segment_candidate = _metrics(transaction_count=5)
    result = _result(
        baseline=metrics,
        candidate=metrics,
        by_segment={"tiny_segment": ReplayComparison(baseline=metrics, candidate=small_segment_candidate, delta=metrics)},
    )
    violations = evaluate_guardrails(result, candidate_review_capacity=1000)
    violation = next(v for v in violations if v.guardrail == "sample_size_floor")
    assert "tiny_segment" in violation.detail


def test_false_positive_rate_increase_is_flagged():
    baseline = _metrics(transaction_count=100, fraud_count=10, legitimate_blocked_count=0)
    # legit_count = 90; 20/90 ~= 22% FPR vs baseline's 0% - past the 5pt default.
    candidate = _metrics(transaction_count=100, fraud_count=10, legitimate_blocked_count=20)
    result = _result(baseline=baseline, candidate=candidate)
    violations = evaluate_guardrails(result, candidate_review_capacity=1000)
    assert any(v.guardrail == "false_positive_rate_increase" for v in violations)


def test_calibration_degradation_is_flagged_beyond_threshold():
    metrics = _metrics()
    result = _result(baseline=metrics, candidate=metrics, calibration_brier_score=0.5)
    violations = evaluate_guardrails(result, candidate_review_capacity=1000)
    assert any(v.guardrail == "calibration_degradation" for v in violations)


def test_calibration_within_threshold_is_not_flagged():
    metrics = _metrics()
    result = _result(baseline=metrics, candidate=metrics, calibration_brier_score=0.02)
    violations = evaluate_guardrails(result, candidate_review_capacity=1000)
    assert not any(v.guardrail == "calibration_degradation" for v in violations)


def test_custom_thresholds_override_defaults():
    baseline = _metrics(allow_count=80, transaction_count=100)
    candidate = _metrics(allow_count=75, transaction_count=100)  # 5pt drop
    result = _result(baseline=baseline, candidate=candidate)
    # Default threshold (10pt) wouldn't flag a 5pt drop; a stricter custom
    # threshold does.
    violations = evaluate_guardrails(
        result, candidate_review_capacity=1000, thresholds=GuardrailThresholds(max_approval_rate_drop=0.01)
    )
    assert any(v.guardrail == "approval_rate_drop" for v in violations)
