"""Counterfactual replay engine (ticket 08). Replays a historical window of
*labeled* transactions (known is_fraud) through two policies - baseline and
candidate - and reports aggregate and per-segment deltas, per issue #1's
Implementation Decisions ("Counterfactual replay") and story 15/18.

This is a pure function over already-assembled `ReplayTransaction` rows -
sourcing those rows from Postgres and a fraud probability per transaction is
the API layer's job (routers/simulation.py), same division of
responsibility as cost_engine.py (pure formulas) vs routers/decisions.py
(DB/HTTP).

DISCLAIMER is issue #1's own required framing (story 19): a replay result is
an offline estimate under the historical labels and each policy's own cost
assumptions, not a causal claim about production impact - never omit it
from a response built on top of this module.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .cost_engine import Action, CostProfile, choose_action, compute_expected_costs, default_cost_profile
from .policy import Policy
from .review_allocation import ReviewCandidate, allocate_reviews
from .segments import AmountBand, MerchantCategory, segment_label

DISCLAIMER = (
    "Offline estimate computed by replaying historical labeled transactions through each "
    "policy's own stated cost assumptions. Not a causal guarantee of real production impact - "
    "see issue #1's Out of Scope notes."
)


@dataclass(frozen=True)
class ReplayTransaction:
    transaction_id: str
    amount: float
    merchant_category: MerchantCategory
    amount_band: AmountBand
    is_returning_customer: bool
    is_known_device: bool
    is_fraud: bool
    # The calibrated fraud probability the decision engine would have used
    # at the time - sourced by the caller (a real /score call for
    # ML-scoreable data, a documented proxy for synthetic data; see
    # routers/simulation.py).
    probability: float


@dataclass(frozen=True)
class SegmentReplayMetrics:
    transaction_count: int
    fraud_loss: float
    legitimate_gmv_blocked: float
    transactions_caught: int
    review_count: int
    net_expected_loss: float


_EMPTY_METRICS = SegmentReplayMetrics(
    transaction_count=0, fraud_loss=0.0, legitimate_gmv_blocked=0.0, transactions_caught=0, review_count=0,
    net_expected_loss=0.0,
)


@dataclass(frozen=True)
class PolicyReplayResult:
    aggregate: SegmentReplayMetrics
    by_segment: dict[str, SegmentReplayMetrics]


@dataclass(frozen=True)
class ReplayComparison:
    baseline: SegmentReplayMetrics
    candidate: SegmentReplayMetrics
    delta: SegmentReplayMetrics  # candidate - baseline, field-wise


@dataclass(frozen=True)
class ReplayResult:
    baseline_policy_id: str
    candidate_policy_id: str
    transactions_replayed: int
    aggregate: ReplayComparison
    by_segment: dict[str, ReplayComparison]
    disclaimer: str = DISCLAIMER


def _catch_probability(action: Action, cost_profile: CostProfile) -> float:
    """The fraction of fraud a given action is assumed to prevent, per the
    same catch/prevent rates the cost formulas use - REVIEW and STEP_UP
    catch it probabilistically, BLOCK fully, ALLOW never."""
    return {
        "ALLOW": 0.0,
        "STEP_UP": cost_profile.step_up_prevent_rate,
        "REVIEW": cost_profile.review_catch_rate,
        "BLOCK": 1.0,
    }[action]


def run_policy(transactions: list[ReplayTransaction], policy: Policy) -> PolicyReplayResult:
    """Decides every transaction under `policy` (same cost engine + review
    allocator as the live /decide and /review/allocate endpoints), then
    aggregates realized outcomes against each transaction's ground-truth
    `is_fraud` label - in aggregate and broken down by segment.
    """
    decided: list[tuple[ReplayTransaction, Action, dict[Action, float], CostProfile]] = []
    for txn in transactions:
        cost_profile = default_cost_profile(
            txn.amount_band, txn.is_returning_customer, txn.is_known_device, policy.cost_assumptions
        )
        expected_costs = compute_expected_costs(txn.probability, txn.amount, cost_profile)
        action = choose_action(expected_costs)
        decided.append((txn, action, expected_costs, cost_profile))

    # Review-capacity allocation (ticket 06): only transactions the cost
    # engine chose REVIEW for compete for the policy's daily cap; everything
    # else keeps its chosen action untouched.
    review_candidates = [
        ReviewCandidate(transaction_id=txn.transaction_id, expected_costs=expected_costs)
        for txn, action, expected_costs, _ in decided
        if action == "REVIEW"
    ]
    allocation_by_id = {
        result.transaction_id: result for result in allocate_reviews(review_candidates, policy.review_capacity)
    }

    aggregate = dict(vars(_EMPTY_METRICS))
    by_segment: dict[str, dict] = defaultdict(lambda: dict(vars(_EMPTY_METRICS)))

    for txn, action, expected_costs, cost_profile in decided:
        final_action = allocation_by_id[txn.transaction_id].final_action if action == "REVIEW" else action
        seg = segment_label(txn.merchant_category, txn.amount_band, txn.is_returning_customer, txn.is_known_device)

        for bucket in (aggregate, by_segment[seg]):
            bucket["transaction_count"] += 1
            bucket["net_expected_loss"] += expected_costs[final_action]
            if final_action == "REVIEW":
                bucket["review_count"] += 1
            if txn.is_fraud:
                catch_probability = _catch_probability(final_action, cost_profile)
                bucket["fraud_loss"] += txn.amount * cost_profile.fraud_loss_rate * (1 - catch_probability)
                if final_action != "ALLOW":
                    bucket["transactions_caught"] += 1
            elif final_action == "BLOCK":
                bucket["legitimate_gmv_blocked"] += txn.amount

    return PolicyReplayResult(
        aggregate=SegmentReplayMetrics(**aggregate),
        by_segment={seg: SegmentReplayMetrics(**values) for seg, values in by_segment.items()},
    )


def _delta(baseline: SegmentReplayMetrics, candidate: SegmentReplayMetrics) -> SegmentReplayMetrics:
    return SegmentReplayMetrics(
        transaction_count=candidate.transaction_count - baseline.transaction_count,
        fraud_loss=candidate.fraud_loss - baseline.fraud_loss,
        legitimate_gmv_blocked=candidate.legitimate_gmv_blocked - baseline.legitimate_gmv_blocked,
        transactions_caught=candidate.transactions_caught - baseline.transactions_caught,
        review_count=candidate.review_count - baseline.review_count,
        net_expected_loss=candidate.net_expected_loss - baseline.net_expected_loss,
    )


def run_replay(
    transactions: list[ReplayTransaction],
    *,
    baseline_policy_id: str,
    baseline_policy: Policy,
    candidate_policy_id: str,
    candidate_policy: Policy,
) -> ReplayResult:
    if not transactions:
        raise ValueError("transactions must be non-empty - nothing to replay.")

    baseline_result = run_policy(transactions, baseline_policy)
    candidate_result = run_policy(transactions, candidate_policy)

    segments = set(baseline_result.by_segment) | set(candidate_result.by_segment)
    by_segment = {
        seg: ReplayComparison(
            baseline=baseline_result.by_segment.get(seg, _EMPTY_METRICS),
            candidate=candidate_result.by_segment.get(seg, _EMPTY_METRICS),
            delta=_delta(
                baseline_result.by_segment.get(seg, _EMPTY_METRICS),
                candidate_result.by_segment.get(seg, _EMPTY_METRICS),
            ),
        )
        for seg in segments
    }

    return ReplayResult(
        baseline_policy_id=baseline_policy_id,
        candidate_policy_id=candidate_policy_id,
        transactions_replayed=len(transactions),
        aggregate=ReplayComparison(
            baseline=baseline_result.aggregate,
            candidate=candidate_result.aggregate,
            delta=_delta(baseline_result.aggregate, candidate_result.aggregate),
        ),
        by_segment=by_segment,
    )
