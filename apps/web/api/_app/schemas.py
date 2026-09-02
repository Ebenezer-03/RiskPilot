"""Pydantic request/response models for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .cost_engine import ACTIONS, DEFAULT_COST_ASSUMPTIONS, Action, CostProfileSource
from .db import DataSource
from .policy import DEFAULT_REVIEW_CAPACITY
from .segments import AmountBand, MerchantCategory


class ScoreRequest(BaseModel):
    transaction_id: str | None = Field(
        default=None,
        description="Optional caller-supplied identifier, echoed back in the response.",
    )
    features: dict[str, float | str | None] = Field(
        default_factory=dict,
        description=(
            "Feature name -> value, using the IEEE-CIS column names in "
            "api/_app/ml/features.py (e.g. TransactionAmt, ProductCD, card4, "
            "V1..V339). Unrecognized keys are ignored; missing known columns "
            "are treated as missing/NaN, same as real-world partial data."
        ),
    )


class ScoreResponse(BaseModel):
    transaction_id: str | None
    fraud_probability_raw: float
    fraud_probability_calibrated: float
    model_version: str
    calibration_version: str
    feature_schema_version: str
    reason_codes: list[str]


class GenerateSyntheticRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=100, description="Number of synthetic transactions to generate and persist.")


class DecideRequest(BaseModel):
    transaction_id: str | None = Field(
        default=None,
        description=(
            "If given, segment fields (merchant_id/merchant_category/amount/"
            "is_returning_customer/is_known_device) default from the persisted "
            "transaction; any explicitly-supplied field below overrides it."
        ),
    )
    probability: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "The calibrated fraud probability to decide on. Not auto-sourced from "
            "/score - synthetic transactions have no real ML-compatible features, "
            "so the caller supplies whichever probability applies (a /score result "
            "for an IEEE-CIS-derived transaction, or the synthetic generator's own "
            "probability for a synthetic one)."
        ),
    )
    merchant_id: str | None = None
    merchant_category: MerchantCategory | None = None
    amount: float | None = Field(default=None, gt=0)
    is_returning_customer: bool | None = None
    is_known_device: bool | None = None
    model_version: str | None = Field(
        default=None,
        description=(
            "Version of the model that produced `probability`, if any - forward this "
            "from a prior /score call's response. Left null when the probability being "
            "decided on didn't come from the real detector (e.g. a synthetic "
            "transaction's own fabricated probability); recorded on the audit trail "
            "(ticket 07) exactly as given, not guessed."
        ),
    )
    calibration_version: str | None = Field(default=None, description="Same as model_version, for the calibrator.")
    feature_schema_version: str | None = Field(
        default=None, description="Same as model_version, for the feature schema the score was computed against."
    )


class DecideResponse(BaseModel):
    transaction_id: str | None
    decision: Action
    expected_costs: dict[Action, float]
    probability_used: float
    merchant_category: MerchantCategory
    amount_band: AmountBand
    is_returning_customer: bool
    is_known_device: bool
    cost_profile_source: CostProfileSource
    reason_codes: list[str]


class ReviewAllocationItem(BaseModel):
    transaction_id: str = Field(description="Identifies the candidate in the response; not looked up server-side.")
    expected_costs: dict[Action, float] = Field(
        description=(
            "All four expected costs for this REVIEW-eligible decision, as returned by "
            "POST /decide's expected_costs field."
        ),
    )

    @field_validator("expected_costs")
    @classmethod
    def _requires_all_four_actions(cls, value: dict[Action, float]) -> dict[Action, float]:
        # dict[Action, float] only validates that present keys are valid
        # Actions - it doesn't require all four. The allocator's savings
        # formula needs REVIEW plus every non-REVIEW action, so a partial
        # dict must fail loudly here (422) rather than KeyError deep inside
        # allocate_reviews (500).
        missing = set(ACTIONS) - set(value)
        if missing:
            raise ValueError(f"expected_costs is missing action(s): {sorted(missing)}")
        return value


class ReviewAllocationRequest(BaseModel):
    items: list[ReviewAllocationItem] = Field(
        description="A batch of REVIEW-eligible decisions (i.e. /decide already chose REVIEW for each).",
    )
    daily_capacity: int = Field(ge=0, description="Hard cap on how many of `items` may actually be routed to review.")


class ReviewAllocationResultItem(BaseModel):
    transaction_id: str
    expected_savings_from_review: float
    routed_to_review: bool
    final_action: Action


class ReviewAllocationResponse(BaseModel):
    daily_capacity: int
    total_candidates: int
    routed_to_review_count: int
    # Ordered by expected_savings_from_review descending - highest-value
    # review candidates first, ties broken by input order.
    results: list[ReviewAllocationResultItem]


class DecisionRecord(BaseModel):
    """One persisted /decide call (ticket 07's audit trail) - the full
    version metadata plus the same decision fields DecideResponse exposes,
    so an audit entry is exactly what a caller would have seen at the time."""

    id: int
    transaction_id: str
    decided_at: datetime
    data_source: DataSource
    probability_used: float
    action: Action
    expected_costs: dict[Action, float]
    reason_codes: list[str]
    merchant_category: MerchantCategory
    amount_band: AmountBand
    is_returning_customer: bool
    is_known_device: bool
    cost_profile_source: CostProfileSource
    model_version: str | None
    calibration_version: str | None
    feature_schema_version: str | None
    segment_definition_version: str
    policy_version: str
    cost_matrix_version: str


class TransactionRecord(BaseModel):
    transaction_id: str
    data_source: DataSource
    event_time: datetime
    amount: float
    currency: str
    merchant_id: str | None
    merchant_category: MerchantCategory
    amount_band: AmountBand
    is_returning_customer: bool
    is_known_device: bool
    is_fraud: bool | None
    raw_features: dict[str, Any]
    created_at: datetime


class AuditTraceResponse(BaseModel):
    transaction: TransactionRecord
    # Chronological (oldest first) - see audit.get_decisions_for_transaction.
    # Usually one entry; more than one means the transaction was decided on
    # more than once (e.g. re-decided after a policy change), which is a
    # legitimate, separately-auditable event, not deduplicated away.
    decisions: list[DecisionRecord]


class CostAssumptionsRequest(BaseModel):
    """The editable cost knobs behind a policy (cost_engine.CostAssumptions).
    Every field defaults to the day-1 global default, so a caller only
    needs to override what actually differs for their candidate policy."""

    fraud_loss_rate_base: float = DEFAULT_COST_ASSUMPTIONS.fraud_loss_rate_base
    fraud_loss_new_device_bonus: float = DEFAULT_COST_ASSUMPTIONS.fraud_loss_new_device_bonus
    false_decline_rate_base: float = DEFAULT_COST_ASSUMPTIONS.false_decline_rate_base
    false_decline_new_customer_bonus: float = DEFAULT_COST_ASSUMPTIONS.false_decline_new_customer_bonus
    false_decline_amount_band_bonus: dict[AmountBand, float] = Field(
        default_factory=lambda: dict(DEFAULT_COST_ASSUMPTIONS.false_decline_amount_band_bonus)
    )
    review_cost: float = DEFAULT_COST_ASSUMPTIONS.review_cost
    review_catch_rate: float = DEFAULT_COST_ASSUMPTIONS.review_catch_rate
    review_friction_rate: float = DEFAULT_COST_ASSUMPTIONS.review_friction_rate
    step_up_friction_cost: float = DEFAULT_COST_ASSUMPTIONS.step_up_friction_cost
    step_up_prevent_rate: float = DEFAULT_COST_ASSUMPTIONS.step_up_prevent_rate
    step_up_abandonment_rate: float = DEFAULT_COST_ASSUMPTIONS.step_up_abandonment_rate

    @field_validator("false_decline_amount_band_bonus")
    @classmethod
    def _fill_missing_amount_bands_from_default(cls, value: dict[AmountBand, float]) -> dict[AmountBand, float]:
        # A caller overriding just one band (e.g. {"low": 0.5}) means "change
        # low, leave the rest at their default" per this schema's own
        # docstring - merging (not requiring completeness) is what makes
        # that true. Left as a partial dict, cost_engine.default_cost_profile
        # KeyErrors on any amount_band not present (500, not a caller-facing
        # 422) the first time a transaction in that band is replayed.
        return {**DEFAULT_COST_ASSUMPTIONS.false_decline_amount_band_bonus, **value}


class PolicyDefinitionRequest(BaseModel):
    """A policy (tickets 08/09): cost assumptions + a daily review-capacity
    cap. `policy_id` is just a caller-supplied label echoed back in the
    response - the replay engine (ticket 08) doesn't look policies up in a
    registry; ticket 09's Policy Lab persists them under this same shape."""

    policy_id: str
    cost_assumptions: CostAssumptionsRequest = Field(default_factory=CostAssumptionsRequest)
    review_capacity: int = Field(default=DEFAULT_REVIEW_CAPACITY, ge=0)


class ReplayWindowRequest(BaseModel):
    data_source: DataSource | None = Field(
        default=None, description="Restrict the historical window to one data source; omit for any."
    )
    limit: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Max labeled (is_fraud IS NOT NULL) transactions to replay, most recent first.",
    )


class ReplayRequest(BaseModel):
    baseline_policy: PolicyDefinitionRequest
    candidate_policy: PolicyDefinitionRequest
    window: ReplayWindowRequest = Field(default_factory=ReplayWindowRequest)


class SegmentReplayMetricsResponse(BaseModel):
    transaction_count: int
    fraud_count: int
    allow_count: int
    fraud_loss: float
    legitimate_gmv_blocked: float
    legitimate_blocked_count: int
    transactions_caught: int
    review_count: int
    review_eligible_count: int
    net_expected_loss: float


class ReplayComparisonResponse(BaseModel):
    baseline: SegmentReplayMetricsResponse
    candidate: SegmentReplayMetricsResponse
    delta: SegmentReplayMetricsResponse  # candidate - baseline, field-wise


class ReplayResponse(BaseModel):
    baseline_policy_id: str
    candidate_policy_id: str
    transactions_replayed: int
    # Labeled transactions in the requested window that couldn't be scored
    # (e.g. a real-detector-scoreable row when the model artifact is
    # unavailable) - reported rather than silently dropped, per the
    # project's own "explicit about what it does not claim" stance.
    transactions_skipped: int
    aggregate: ReplayComparisonResponse
    by_segment: dict[str, ReplayComparisonResponse]
    # One value for the whole window (both policies decide from the same
    # probabilities) - see replay.compute_calibration_brier_score.
    calibration_brier_score: float
    # Calendar days spanned by the window - see replay.compute_window_days.
    window_days: int
    disclaimer: str


# --- Policy registry (ticket 09) --------------------------------------------------

# All six values from issue #1's Implementation Decisions, though only
# DRAFT -> SIMULATED -> ACTIVE is ever produced by this API today -
# APPROVED/CANARY/ROLLED_BACK are valid values the DB CHECK constraint
# already allows, kept here so the type doesn't lie about the DB schema,
# per this repo's stated day-1 scope for ticket 09.
PolicyStatus = Literal["DRAFT", "SIMULATED", "APPROVED", "CANARY", "ACTIVE", "ROLLED_BACK"]


class PolicyWriteRequest(BaseModel):
    """Shared shape for create and update - a full replacement of the
    editable fields, not a partial PATCH-merge (simpler and unambiguous for
    a policy that's still DRAFT and has no other readers yet)."""

    name: str
    cost_assumptions: CostAssumptionsRequest = Field(default_factory=CostAssumptionsRequest)
    review_capacity: int = Field(default=DEFAULT_REVIEW_CAPACITY, ge=0)


class PolicyCreateRequest(PolicyWriteRequest):
    policy_id: str = Field(description="Caller-chosen unique slug, e.g. 'policy-2026-09-conservative'.")


class PolicyRecord(BaseModel):
    policy_id: str
    name: str
    status: PolicyStatus
    cost_assumptions: CostAssumptionsRequest
    review_capacity: int
    baseline_policy_id: str | None
    replay_result: dict[str, Any] | None
    guardrail_violations: list[dict[str, Any]] | None
    created_at: datetime
    updated_at: datetime
    simulated_at: datetime | None
    activated_at: datetime | None


class PolicySimulateRequest(BaseModel):
    baseline_policy_id: str | None = Field(
        default=None,
        description=(
            "Policy to replay this candidate against. Defaults to the most recently "
            "activated ACTIVE policy, or the day-1 default policy (cost_engine's own "
            "constants) if no policy has ever been activated yet."
        ),
    )
    window: ReplayWindowRequest = Field(default_factory=ReplayWindowRequest)


class GuardrailThresholdsRequest(BaseModel):
    """All optional - unset fields fall back to guardrails.DEFAULT_GUARDRAIL_THRESHOLDS."""

    max_approval_rate_drop: float | None = Field(default=None, ge=0)
    min_segment_sample_size: int | None = Field(default=None, ge=0)
    max_false_positive_rate_increase: float | None = Field(default=None, ge=0)
    max_calibration_brier_score: float | None = Field(default=None, ge=0)


class PolicyPromoteRequest(BaseModel):
    thresholds: GuardrailThresholdsRequest = Field(default_factory=GuardrailThresholdsRequest)


class GuardrailViolationResponse(BaseModel):
    guardrail: str
    detail: str


class PolicyPromotionResponse(BaseModel):
    policy: PolicyRecord
    approved: bool
    # Empty when approved=True. Non-empty (and the policy stays SIMULATED)
    # when approved=False - issue #1: "a rejected candidate policy stays in
    # SIMULATED with the violated guardrail(s) reported."
    violations: list[GuardrailViolationResponse]
