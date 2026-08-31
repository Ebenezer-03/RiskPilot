"""The five promotion guardrails (ticket 09) that gate a policy's
SIMULATED -> ACTIVE transition, evaluated against a stored replay.ReplayResult
(candidate vs. the baseline it was simulated against). Per issue #1's
Implementation Decisions: "approval-rate drop beyond a configured threshold,
review-queue overflow beyond capacity, a segment falling below the minimum
historical sample-size floor, false-positive-rate increase beyond a
configured threshold, and calibration degradation beyond a configured
threshold." A rejected candidate stays in SIMULATED with the violated
guardrail(s) reported - see routers/policies.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .replay import ReplayResult, SegmentReplayMetrics

GuardrailName = Literal[
    "approval_rate_drop",
    "review_queue_overflow",
    "sample_size_floor",
    "false_positive_rate_increase",
    "calibration_degradation",
]

GUARDRAIL_NAMES: tuple[GuardrailName, ...] = (
    "approval_rate_drop",
    "review_queue_overflow",
    "sample_size_floor",
    "false_positive_rate_increase",
    "calibration_degradation",
)


@dataclass(frozen=True)
class GuardrailThresholds:
    """Not spec-specified as exact numbers (issue #1 names the five
    guardrail *concepts*, not thresholds) - documented illustrative
    defaults, overridable per promotion request, same posture as the cost
    constants in cost_engine.py."""

    max_approval_rate_drop: float = 0.10  # 10 percentage points
    min_segment_sample_size: int = 30
    max_false_positive_rate_increase: float = 0.05  # 5 percentage points
    # docs/evaluation_report.md's held-out calibrated Brier score is 0.0224;
    # generous headroom before flagging drift on a replay window.
    max_calibration_brier_score: float = 0.08


DEFAULT_GUARDRAIL_THRESHOLDS = GuardrailThresholds()


@dataclass(frozen=True)
class GuardrailViolation:
    guardrail: GuardrailName
    detail: str


def _approval_rate(metrics: SegmentReplayMetrics) -> float:
    return metrics.allow_count / metrics.transaction_count if metrics.transaction_count else 0.0


def _false_positive_rate(metrics: SegmentReplayMetrics) -> float:
    legit_count = metrics.transaction_count - metrics.fraud_count
    return metrics.legitimate_blocked_count / legit_count if legit_count else 0.0


def evaluate_guardrails(
    replay_result: ReplayResult,
    *,
    candidate_review_capacity: int,
    thresholds: GuardrailThresholds = DEFAULT_GUARDRAIL_THRESHOLDS,
) -> list[GuardrailViolation]:
    """Pure function - all inputs are numbers already computed by the
    replay engine; no I/O, no policy-registry lookups."""
    violations: list[GuardrailViolation] = []
    baseline = replay_result.aggregate.baseline
    candidate = replay_result.aggregate.candidate

    approval_rate_drop = _approval_rate(baseline) - _approval_rate(candidate)
    if approval_rate_drop > thresholds.max_approval_rate_drop:
        violations.append(
            GuardrailViolation(
                "approval_rate_drop",
                f"approval rate dropped {approval_rate_drop:.1%} "
                f"(baseline {_approval_rate(baseline):.1%} -> candidate {_approval_rate(candidate):.1%}), "
                f"exceeding the {thresholds.max_approval_rate_drop:.0%} threshold",
            )
        )

    # review_eligible_count is a *window-total*; review_capacity is a
    # *daily* cap (see policy.py) - normalize by the window's own day-span
    # before comparing, so a multi-day window doesn't get penalized for
    # volume a single day never actually saw, and a sub-day window doesn't
    # get a free pass on a rate it would in fact exceed daily.
    daily_review_eligible_rate = candidate.review_eligible_count / replay_result.window_days
    if daily_review_eligible_rate > candidate_review_capacity:
        violations.append(
            GuardrailViolation(
                "review_queue_overflow",
                f"~{daily_review_eligible_rate:.1f} review-eligible transactions/day "
                f"({candidate.review_eligible_count} over {replay_result.window_days} day(s)) exceed the "
                f"candidate policy's daily capacity of {candidate_review_capacity}",
            )
        )

    undersized_segments = sorted(
        seg
        for seg, comparison in replay_result.by_segment.items()
        if comparison.candidate.transaction_count < thresholds.min_segment_sample_size
    )
    if undersized_segments:
        violations.append(
            GuardrailViolation(
                "sample_size_floor",
                f"segment(s) below the minimum sample size of {thresholds.min_segment_sample_size}: "
                f"{undersized_segments}",
            )
        )

    fpr_increase = _false_positive_rate(candidate) - _false_positive_rate(baseline)
    if fpr_increase > thresholds.max_false_positive_rate_increase:
        violations.append(
            GuardrailViolation(
                "false_positive_rate_increase",
                f"false-positive rate increased {fpr_increase:.1%} "
                f"(baseline {_false_positive_rate(baseline):.1%} -> candidate {_false_positive_rate(candidate):.1%}), "
                f"exceeding the {thresholds.max_false_positive_rate_increase:.0%} threshold",
            )
        )

    if replay_result.calibration_brier_score > thresholds.max_calibration_brier_score:
        violations.append(
            GuardrailViolation(
                "calibration_degradation",
                f"replay-window Brier score {replay_result.calibration_brier_score:.4f} exceeds the "
                f"{thresholds.max_calibration_brier_score:.4f} threshold",
            )
        )

    return violations
