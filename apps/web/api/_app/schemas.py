"""Pydantic request/response models for the public API."""

from __future__ import annotations

from pydantic import BaseModel, Field


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
