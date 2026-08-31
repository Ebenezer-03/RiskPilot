"""Generates the /score test fixtures from real held-out data.

Not run automatically (needs data/raw/ieee-fraud-detection/ + requirements-train.txt,
neither available in CI/a fresh clone) - this is a one-off, reproducible
generator; the JSON it produces is what's actually committed and used by
test_score.py. Rerun only if the model/feature schema changes meaningfully.

Run from apps/web/api:  python -m _app.tests.fixtures.generate_fixtures
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import joblib

from ...ml.features import (
    ALL_FEATURE_COLUMNS,
    CALIBRATOR_ARTIFACT_FILENAME,
    MODEL_ARTIFACT_FILENAME,
    add_derived_features,
    coerce_categorical_dtypes,
    row_to_json_safe,
)
from ...ml.train import ARTIFACTS_DIR, load_data, time_ordered_split

FIXTURES_DIR = Path(__file__).resolve().parent


def main() -> None:
    booster = lgb.Booster(model_file=str(ARTIFACTS_DIR / MODEL_ARTIFACT_FILENAME))
    calibrator = joblib.load(ARTIFACTS_DIR / CALIBRATOR_ARTIFACT_FILENAME)

    df = load_data()
    df = add_derived_features(df)
    df = coerce_categorical_dtypes(df)
    _, _, test_df = time_ordered_split(df)

    X_test = test_df[ALL_FEATURE_COLUMNS]
    raw = booster.predict(X_test)
    calibrated = calibrator.predict(raw)
    test_df = test_df.assign(_calibrated_prob=calibrated)

    fraud_rows = test_df[test_df["isFraud"] == 1].sort_values("_calibrated_prob", ascending=False)
    legit_rows = test_df[test_df["isFraud"] == 0].sort_values("_calibrated_prob", ascending=True)

    fraud_example = fraud_rows.iloc[0]
    legit_example = legit_rows.iloc[0]

    for name, row in [("fraud_example", fraud_example), ("legitimate_example", legit_example)]:
        payload = {
            "source": "IEEE-CIS held-out test split, real TransactionID (see below)",
            "transaction_id": int(row["TransactionID"]),
            "true_label": int(row["isFraud"]),
            "calibrated_probability_at_generation_time": round(float(row["_calibrated_prob"]), 4),
            "features": row_to_json_safe(row[ALL_FEATURE_COLUMNS]),
        }
        out_path = FIXTURES_DIR / f"{name}.json"
        out_path.write_text(json.dumps(payload, indent=2))
        print(f"Wrote {out_path} (calibrated_prob={payload['calibrated_probability_at_generation_time']})")


if __name__ == "__main__":
    main()
