"""Fraud-scoring service: loads the trained artifacts once at process start
and scores individual transactions, producing a calibrated probability plus
SHAP-derived reason codes.

Deliberately does not import api._app.ml.train (training-only, pulls in
pandas-heavy offline tooling and is not meant to run inside the deployed
function - training is offline-only per the spec). This module only reads
the artifacts train.py already produced.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import pandas as pd
import shap

from .ml.features import (
    ALL_FEATURE_COLUMNS,
    CALIBRATION_VERSION,
    CALIBRATOR_ARTIFACT_FILENAME,
    FEATURE_SCHEMA_VERSION,
    MODEL_ARTIFACT_FILENAME,
    MODEL_VERSION,
    NUMERIC_COLUMNS,
    coerce_categorical_dtypes,
)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"

# Friendly labels for reason codes. IEEE-CIS's V1-V339 block is Vesta's own
# undisclosed engineered features (see docs/data_assumptions.md) - reported
# plainly as "engineered signal V<n>" rather than invented meaning, so the
# explanation stays honest about what is and isn't actually interpretable.
_FRIENDLY_NAMES: dict[str, str] = {
    "TransactionAmt": "transaction amount",
    "ProductCD": "product category",
    "card4": "card network",
    "card6": "card type",
    "addr1": "billing region code",
    "addr2": "billing country code",
    "dist1": "distance from billing address",
    "dist2": "distance from shipping address",
    "P_emaildomain": "purchaser email domain",
    "R_emaildomain": "recipient email domain",
    "DeviceType": "device type",
    "DeviceInfo": "device info",
    "transaction_hour": "hour of day",
}


def _friendly_name(column: str) -> str:
    if column in _FRIENDLY_NAMES:
        return _FRIENDLY_NAMES[column]
    if column.startswith("card"):
        return f"card attribute {column}"
    if column.startswith("C") and column[1:].isdigit():
        return f"transaction/address count signal {column}"
    if column.startswith("D") and column[1:].isdigit():
        return f"time-since-previous-transaction signal {column}"
    if column.startswith("M") and column[1:].isdigit():
        return f"identity match flag {column}"
    if column.startswith("V") and column[1:].isdigit():
        return f"engineered signal {column}"
    if column.startswith("id_"):
        return f"identity/device signal {column}"
    return column


class ScoringService:
    """Holds the loaded artifacts. Instantiated once at FastAPI startup
    (see main.py) - artifact loading is deliberately not per-request."""

    def __init__(self, artifacts_dir: Path = ARTIFACTS_DIR):
        model_path = artifacts_dir / MODEL_ARTIFACT_FILENAME
        calibrator_path = artifacts_dir / CALIBRATOR_ARTIFACT_FILENAME
        if not model_path.exists() or not calibrator_path.exists():
            raise FileNotFoundError(
                f"Missing model/calibrator artifacts under {artifacts_dir}. "
                f"Run `python -m api._app.ml.train` first (see docs/data_assumptions.md)."
            )
        self.booster = lgb.Booster(model_file=str(model_path))
        self.calibrator = joblib.load(calibrator_path)
        self.explainer = shap.TreeExplainer(self.booster)
        self.model_version = MODEL_VERSION
        self.calibration_version = CALIBRATION_VERSION
        self.feature_schema_version = FEATURE_SCHEMA_VERSION

    def _build_row(self, features: dict[str, Any]) -> pd.DataFrame:
        row = {col: features.get(col) for col in ALL_FEATURE_COLUMNS}
        df = pd.DataFrame([row], columns=ALL_FEATURE_COLUMNS)
        # A missing key -> Python None -> pandas builds an all-object column,
        # which LightGBM rejects outright ("pandas dtypes must be int, float
        # or bool"). Coerce numeric columns explicitly; anything unparseable
        # (including None) becomes a proper NaN, which LightGBM treats as
        # missing natively.
        df[NUMERIC_COLUMNS] = df[NUMERIC_COLUMNS].apply(pd.to_numeric, errors="coerce")
        return coerce_categorical_dtypes(df)

    def predict_probability(self, features: dict[str, Any]) -> float:
        """The calibrated probability alone, skipping TreeSHAP entirely -
        for callers (replay/simulation) that score hundreds or thousands of
        historical rows and only ever use the probability, never the
        per-row reason codes `score()` also computes. TreeSHAP is by far
        the most expensive part of `score()`; running it on every replayed
        row turns a simulation from milliseconds into minutes for no
        benefit, since the reason codes are discarded unread."""
        row = self._build_row(features)
        raw_prob = float(self.booster.predict(row)[0])
        return float(self.calibrator.predict([raw_prob])[0])

    def score(self, features: dict[str, Any]) -> dict[str, Any]:
        row = self._build_row(features)

        raw_prob = float(self.booster.predict(row)[0])
        calibrated_prob = float(self.calibrator.predict([raw_prob])[0])

        reason_codes = self._reason_codes(row)

        return {
            "fraud_probability_raw": round(raw_prob, 4),
            "fraud_probability_calibrated": round(calibrated_prob, 4),
            "model_version": self.model_version,
            "calibration_version": self.calibration_version,
            "feature_schema_version": self.feature_schema_version,
            "reason_codes": reason_codes,
        }

    def _reason_codes(self, row: pd.DataFrame, top_n: int = 3) -> list[str]:
        shap_values = self.explainer.shap_values(row)
        # Explaining self.booster directly (a raw LightGBM Booster, not an
        # sklearn-wrapped two-class classifier) makes TreeExplainer return
        # one array of shape (1, n_features) - contributions to the single
        # margin output, which *is* the fraud-class direction - not the
        # [class_0_values, class_1_values] list some SHAP versions return
        # for a wrapped binary classifier (confirmed empirically against
        # this module's pinned lightgbm/shap versions: shap_values here is
        # always a plain ndarray, never a list, despite the "output has
        # changed to a list of ndarray" UserWarning SHAP prints regardless -
        # that warning fires for the wrapped-classifier code path this
        # module doesn't take). Handled defensively anyway in case a future
        # SHAP upgrade changes that for the raw-booster path too - a list
        # here would otherwise silently score fraud-suppressing (class 0)
        # contributions as if they were fraud-driving ones.
        if isinstance(shap_values, list):
            values = shap_values[-1][0]  # last element is the positive (fraud) class
        else:
            values = shap_values[0] if hasattr(shap_values, "__len__") else shap_values
        contributions = list(zip(ALL_FEATURE_COLUMNS, values))
        contributions.sort(key=lambda pair: abs(pair[1]), reverse=True)

        codes = []
        for column, value in contributions[:top_n]:
            if abs(value) < 1e-9:
                continue
            sign = "+" if value >= 0 else "-"
            codes.append(f"{_friendly_name(column)} ({sign}{abs(value):.2f})")
        return codes


_service: ScoringService | None = None


def get_scoring_service() -> ScoringService:
    """Lazily instantiated singleton - loaded on first use (which in
    practice is triggered once at FastAPI startup, not per-request)."""
    global _service
    if _service is None:
        _service = ScoringService()
    return _service
