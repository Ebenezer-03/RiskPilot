"""Pydantic request/response models for the public API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

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
