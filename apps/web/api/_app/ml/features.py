"""Authorization-time feature schema for the IEEE-CIS fraud detector.

Column categorization (categorical vs numeric) follows the IEEE-CIS
competition's own published data description, not a guess from column
names alone. See docs/data_assumptions.md for the full feature-time
contract and the leakage-check methodology for the V1-V339 block.

FEATURE_SCHEMA_VERSION is bumped whenever this schema changes, and is
recorded on every decision trace (per the spec's audit-trail design) so a
past decision can always be tied back to the exact feature set that
produced it.
"""

from __future__ import annotations

FEATURE_SCHEMA_VERSION = "features-v1.0"
MODEL_VERSION = "fraud-model-v1.0"
CALIBRATION_VERSION = "isotonic-v1.0"

# Canonical artifact filenames - shared between train.py (writes them) and
# scoring.py (reads them), so the two can never silently drift apart.
MODEL_ARTIFACT_FILENAME = f"fraud_model_{MODEL_VERSION}.txt"
CALIBRATOR_ARTIFACT_FILENAME = f"calibrator_{CALIBRATION_VERSION}.joblib"
LOGREG_ARTIFACT_FILENAME = f"logreg_baseline_{MODEL_VERSION}.joblib"
FEATURE_SCHEMA_ARTIFACT_FILENAME = f"feature_schema_{FEATURE_SCHEMA_VERSION}.json"

ID_COLUMN = "TransactionID"
TARGET_COLUMN = "isFraud"
TIME_COLUMN = "TransactionDT"  # not a feature itself; used for the time-based split
# and to derive TRANSACTION_HOUR below.

CATEGORICAL_COLUMNS: list[str] = [
    "ProductCD",
    "card1",
    "card2",
    "card3",
    "card4",
    "card5",
    "card6",
    "addr1",
    "addr2",
    "P_emaildomain",
    "R_emaildomain",
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
    "M7",
    "M8",
    "M9",
    "DeviceType",
    "DeviceInfo",
    *[f"id_{i:02d}" for i in range(12, 39)],
]

_NUMERIC_BASE: list[str] = [
    "TransactionAmt",
    "dist1",
    "dist2",
    *[f"C{i}" for i in range(1, 15)],
    *[f"D{i}" for i in range(1, 16)],
    *[f"V{i}" for i in range(1, 340)],
    *[f"id_{i:02d}" for i in range(1, 12)],
]

# Derived at-authorization-time feature: hour of day is knowable the instant
# a transaction is submitted (no leakage risk), and is a real fraud signal
# (IEEE-CIS write-ups consistently find time-of-day predictive).
DERIVED_NUMERIC_COLUMNS: list[str] = ["transaction_hour"]

NUMERIC_COLUMNS: list[str] = _NUMERIC_BASE + DERIVED_NUMERIC_COLUMNS

ALL_FEATURE_COLUMNS: list[str] = CATEGORICAL_COLUMNS + NUMERIC_COLUMNS


def add_derived_features(df):
    """Add derived-but-still-authorization-time-safe columns in place."""
    df["transaction_hour"] = (df[TIME_COLUMN] // 3600) % 24
    return df


def coerce_categorical_dtypes(df):
    """LightGBM's native categorical support requires pandas 'category' dtype."""
    for col in CATEGORICAL_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype("category")
    return df


def row_to_json_safe(row) -> dict:
    """A single pandas row (Series) -> plain-Python dict safe for
    json.dumps/psycopg's Json() - numpy scalars (float32, int64, category
    values) aren't natively JSON-serializable, and NaN needs to become None.
    Shared by the fixture generator and the IEEE-CIS sample loader so this
    bridging logic exists in exactly one place."""
    obj = row.astype(object).where(row.notna(), None)
    out = {}
    for key, value in obj.items():
        if hasattr(value, "item"):
            value = value.item()
        out[key] = value
    return out
