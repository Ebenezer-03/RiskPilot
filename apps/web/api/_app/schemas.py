"""Pydantic request/response models for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .cost_engine import ACTIONS, Action, CostProfileSource
from .db import DataSource
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
    amount: float | None = None
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
