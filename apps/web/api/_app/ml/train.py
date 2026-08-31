"""Offline training script for the RiskPilot fraud detector.

Run from apps/web/api:  python -m _app.ml.train
(needs requirements-train.txt installed, and data/raw/ieee-fraud-detection/
populated - see docs/data_assumptions.md for how to acquire it.)

Produces (all under api/_app/artifacts/, gitignored except .gitkeep):
  - fraud_model_<MODEL_VERSION>.txt        LightGBM booster (native format)
  - calibrator_<CALIBRATION_VERSION>.joblib Isotonic regression calibrator
  - logreg_baseline_<MODEL_VERSION>.joblib  Logistic Regression baseline (reporting only)
  - feature_schema_<FEATURE_SCHEMA_VERSION>.json

And a committed evaluation report at docs/evaluation_report.md.

This script is intentionally not imported by the FastAPI app - training is
offline-only per the spec (no live-retrain endpoint). The scoring endpoint
(ticket 03) loads the artifacts this script produces.
"""

from __future__ import annotations

import gc
import json
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder, StandardScaler

from .features import (
    ALL_FEATURE_COLUMNS,
    CALIBRATION_VERSION,
    CALIBRATOR_ARTIFACT_FILENAME,
    CATEGORICAL_COLUMNS,
    FEATURE_SCHEMA_ARTIFACT_FILENAME,
    FEATURE_SCHEMA_VERSION,
    ID_COLUMN,
    LOGREG_ARTIFACT_FILENAME,
    MODEL_ARTIFACT_FILENAME,
    MODEL_VERSION,
    NUMERIC_COLUMNS,
    TARGET_COLUMN,
    TIME_COLUMN,
    _NUMERIC_BASE,
    add_derived_features,
    coerce_categorical_dtypes,
)

DECISION_THRESHOLD_FOR_REPORT = 0.5  # reporting only - the real system uses expected-cost, not a fixed cutoff (ticket 05)

REPO_ROOT = Path(__file__).resolve().parents[5]
DATA_DIR = REPO_ROOT / "data" / "raw" / "ieee-fraud-detection"
ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "artifacts"
DOCS_DIR = REPO_ROOT / "docs"


def _downcast_numeric(frame: pd.DataFrame) -> pd.DataFrame:
    """Downcast the numeric feature block to float32 right after loading,
    before merge/sort - float64 across ~380 columns x 590K rows was enough
    to exhaust available memory during later pandas block-consolidation
    steps. Done column-by-column post-read rather than via read_csv's dtype=
    kwarg, which triggered an unrelated pandas construction failure on this
    dataset's column mix."""
    for col in _NUMERIC_BASE:
        if col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], downcast="float")
    return frame


def load_data() -> pd.DataFrame:
    print("Loading train_transaction.csv + train_identity.csv ...")
    tx = pd.read_csv(DATA_DIR / "train_transaction.csv")
    tx = _downcast_numeric(tx)
    identity = pd.read_csv(DATA_DIR / "train_identity.csv")
    identity = _downcast_numeric(identity)
    identity_n = identity[ID_COLUMN].nunique()
    df = tx.merge(identity, on=ID_COLUMN, how="left")
    del tx, identity
    gc.collect()
    print(f"Loaded {len(df):,} transactions ({identity_n:,} with identity data).")
    return df


def time_ordered_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """70/15/15 split ordered by TransactionDT - not random. This dataset's
    own train/test split is time-based (see docs/data_assumptions.md); a
    random split here would let the model see 'future' transactions from the
    same card/device during training and report optimistic metrics."""
    df = df.sort_values(TIME_COLUMN).reset_index(drop=True)
    n = len(df)
    train_end = int(n * 0.70)
    calib_end = int(n * 0.85)
    return df.iloc[:train_end], df.iloc[train_end:calib_end], df.iloc[calib_end:]


def check_v_column_leakage(train_df: pd.DataFrame) -> list[dict]:
    """Single-column AUC for each V-column, computed on the TRAIN split only
    (never test) so this check itself can't leak. A column whose single-feature
    AUC alone approaches the whole model's AUC would be a leakage red flag
    per docs/data_assumptions.md - report actual numbers, don't assume."""
    y = train_df[TARGET_COLUMN]
    results = []
    for i in range(1, 340):
        col = f"V{i}"
        if col not in train_df.columns:
            continue
        values = train_df[col]
        if values.notna().sum() < 100:
            continue
        filled = values.fillna(values.median())
        try:
            auc = roc_auc_score(y, filled)
            auc = max(auc, 1 - auc)  # direction-agnostic
        except ValueError:
            continue
        results.append({"column": col, "single_feature_auc": round(float(auc), 4)})
    results.sort(key=lambda r: r["single_feature_auc"], reverse=True)
    return results


def stringify_categoricals(frame: pd.DataFrame) -> pd.DataFrame:
    """LightGBM's native categorical columns hold numeric codes under the
    hood (pandas 'category' dtype over int/float categories). sklearn's
    OneHotEncoder chokes on a column mixing numeric categories with a
    string fill value for missing entries - coerce to a uniform string
    dtype (with an explicit missing marker) for the Logistic Regression
    baseline only; LightGBM keeps the native category dtype."""
    frame = frame.copy()
    for col in CATEGORICAL_COLUMNS:
        frame[col] = frame[col].astype(str).replace("nan", "__missing__")
    return frame


def build_logreg_pipeline() -> Pipeline:
    numeric_transform = Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    # Ordinal, not one-hot: one-hot across ~57 categorical columns (some with
    # thousands of unique values, e.g. card1) blew up to 1000+ columns and a
    # multi-GB dense array. LightGBM (the primary model) already gets proper
    # native categorical splits; this baseline trades encoding sophistication
    # for tractability, which is a fair simplification for a comparison
    # baseline, documented as such in the evaluation report.
    categorical_transform = Pipeline([
        ("ordinal", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1, dtype=np.float32)),
    ])
    preprocessor = ColumnTransformer([
        ("num", numeric_transform, NUMERIC_COLUMNS),
        ("cat", categorical_transform, CATEGORICAL_COLUMNS),
    ])
    return Pipeline([
        ("preprocess", preprocessor),
        ("classify", LogisticRegression(max_iter=200, class_weight="balanced", n_jobs=-1)),
    ])


def compute_metrics(y_true, y_prob, threshold=DECISION_THRESHOLD_FOR_REPORT) -> dict:
    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    return {
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "pr_auc": round(float(average_precision_score(y_true, y_prob)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4),
        "brier_score": round(float(brier_score_loss(y_true, y_prob)), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "threshold_used_for_report": threshold,
    }


def calibration_curve_bins(y_true, y_prob, n_bins=10) -> list[dict]:
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_ids = np.digitize(y_prob, bins) - 1
    bin_ids = np.clip(bin_ids, 0, n_bins - 1)
    rows = []
    y_true = np.asarray(y_true)
    for b in range(n_bins):
        mask = bin_ids == b
        if mask.sum() == 0:
            continue
        rows.append({
            "bin": f"{bins[b]:.1f}-{bins[b + 1]:.1f}",
            "n": int(mask.sum()),
            "mean_predicted": round(float(y_prob[mask].mean()), 4),
            "empirical_fraud_rate": round(float(y_true[mask].mean()), 4),
        })
    return rows


def main() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_data()
    df = add_derived_features(df)
    df = coerce_categorical_dtypes(df)

    train_df, calib_df, test_df = time_ordered_split(df)
    train_n, calib_n, test_n = len(train_df), len(calib_df), len(test_df)
    print(f"Split: train={train_n:,} calib={calib_n:,} test={test_n:,}")

    print("Running V-column leakage check on the train split...")
    leakage_report = check_v_column_leakage(train_df)
    top_leakage = leakage_report[:15]
    suspicious = [r for r in leakage_report if r["single_feature_auc"] > 0.90]

    X_train, y_train = train_df[ALL_FEATURE_COLUMNS].copy(), train_df[TARGET_COLUMN]
    X_calib, y_calib = calib_df[ALL_FEATURE_COLUMNS].copy(), calib_df[TARGET_COLUMN]
    X_test, y_test = test_df[ALL_FEATURE_COLUMNS].copy(), test_df[TARGET_COLUMN]
    # float32 instead of pandas' default float64 roughly halves memory for the
    # ~380-column numeric block (matters at 590K rows on a modest machine).
    for frame in (X_train, X_calib, X_test):
        frame[NUMERIC_COLUMNS] = frame[NUMERIC_COLUMNS].astype("float32")
    del df, train_df, calib_df, test_df
    gc.collect()

    print("Training LightGBM...")
    lgb_train = lgb.Dataset(X_train, label=y_train, categorical_feature=CATEGORICAL_COLUMNS, free_raw_data=False)
    booster = lgb.train(
        params={
            "objective": "binary",
            "metric": "auc",
            "num_leaves": 63,
            "learning_rate": 0.05,
            "is_unbalance": True,
            "verbosity": -1,
            "seed": 42,
        },
        train_set=lgb_train,
        num_boost_round=300,
    )

    raw_prob_calib = booster.predict(X_calib)
    raw_prob_test = booster.predict(X_test)
    del lgb_train
    gc.collect()

    print("Fitting isotonic calibration on the calibration split...")
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_prob_calib, y_calib)
    calibrated_prob_test = calibrator.predict(raw_prob_test)

    metrics_raw = compute_metrics(y_test, raw_prob_test)
    metrics_calibrated = compute_metrics(y_test, calibrated_prob_test)
    calib_curve_raw = calibration_curve_bins(y_test, raw_prob_test)
    calib_curve_calibrated = calibration_curve_bins(y_test, calibrated_prob_test)

    print("Training Logistic Regression baseline...")
    logreg = build_logreg_pipeline()
    logreg.fit(stringify_categoricals(X_train), y_train)
    logreg_prob_test = logreg.predict_proba(stringify_categoricals(X_test))[:, 1]
    metrics_logreg = compute_metrics(y_test, logreg_prob_test)

    print("Saving artifacts...")
    model_path = ARTIFACTS_DIR / MODEL_ARTIFACT_FILENAME
    booster.save_model(str(model_path))
    calibrator_path = ARTIFACTS_DIR / CALIBRATOR_ARTIFACT_FILENAME
    joblib.dump(calibrator, calibrator_path)
    logreg_path = ARTIFACTS_DIR / LOGREG_ARTIFACT_FILENAME
    joblib.dump(logreg, logreg_path)
    schema_path = ARTIFACTS_DIR / FEATURE_SCHEMA_ARTIFACT_FILENAME
    schema_path.write_text(json.dumps({
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "categorical_columns": CATEGORICAL_COLUMNS,
        "numeric_columns": NUMERIC_COLUMNS,
    }, indent=2))

    print("Writing evaluation report...")
    write_report(
        train_n=train_n, calib_n=calib_n, test_n=test_n,
        train_fraud_rate=float(y_train.mean()), test_fraud_rate=float(y_test.mean()),
        metrics_raw=metrics_raw, metrics_calibrated=metrics_calibrated, metrics_logreg=metrics_logreg,
        calib_curve_raw=calib_curve_raw, calib_curve_calibrated=calib_curve_calibrated,
        top_leakage=top_leakage, suspicious=suspicious,
    )
    print("Done.")
    print(f"  LightGBM (calibrated) test PR-AUC: {metrics_calibrated['pr_auc']}")
    print(f"  Logistic Regression   test PR-AUC: {metrics_logreg['pr_auc']}")


def write_report(*, train_n, calib_n, test_n, train_fraud_rate, test_fraud_rate,
                  metrics_raw, metrics_calibrated, metrics_logreg,
                  calib_curve_raw, calib_curve_calibrated, top_leakage, suspicious) -> None:
    def metrics_row(name, m):
        return f"| {name} | {m['precision']} | {m['recall']} | {m['f1']} | {m['pr_auc']} | {m['roc_auc']} | {m['brier_score']} |"

    def confusion_block(name, m):
        cm = m["confusion_matrix"]
        return (f"**{name}** (threshold={m['threshold_used_for_report']}, reporting only - "
                f"the deployed system uses expected-cost decisioning, not a fixed cutoff): "
                f"TP={cm['tp']} FP={cm['fp']} FN={cm['fn']} TN={cm['tn']}")

    def curve_table(rows):
        lines = ["| Bin | n | Mean predicted | Empirical fraud rate |", "|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['bin']} | {r['n']:,} | {r['mean_predicted']} | {r['empirical_fraud_rate']} |")
        return "\n".join(lines)

    leakage_lines = ["| V-column | Single-feature AUC (train split) |", "|---|---|"]
    for r in top_leakage:
        leakage_lines.append(f"| {r['column']} | {r['single_feature_auc']} |")

    suspicious_note = (
        f"**{len(suspicious)} column(s) exceeded the 0.90 single-feature-AUC flag threshold**: "
        f"{', '.join(r['column'] for r in suspicious)}. These should be scrutinized before trusting "
        f"them as authorization-time-safe (see docs/data_assumptions.md)."
        if suspicious else
        "No V-column exceeded the 0.90 single-feature-AUC flag threshold on the train split. "
        "This doesn't prove they're leak-free, but it's the check the feature-time contract "
        "committed to running, and it found nothing dominant enough to warrant exclusion."
    )

    report = f"""# Detector Evaluation Report

Model version: `{MODEL_VERSION}` &middot; Calibration version: `{CALIBRATION_VERSION}` &middot; Feature schema: `{FEATURE_SCHEMA_VERSION}`

Generated by `api/_app/ml/train.py`. Split is time-ordered on `TransactionDT`
(70% train / 15% calibration / 15% held-out test), not random - see
`docs/data_assumptions.md` for why.

## Dataset

- Train: {train_n:,} transactions, fraud rate {train_fraud_rate:.4%}
- Calibration: {calib_n:,} transactions
- Held-out test: {test_n:,} transactions, fraud rate {test_fraud_rate:.4%}

## V1-V339 leakage check

Per the feature-time contract, each `V` column's single-feature AUC against
`isFraud` was computed on the **train split only** (never test, to avoid the
check itself leaking). Top 15 by AUC:

{chr(10).join(leakage_lines)}

{suspicious_note}

## Held-out test metrics

| Model | Precision | Recall | F1 | PR-AUC | ROC-AUC | Brier score |
|---|---|---|---|---|---|---|
{metrics_row("LightGBM (raw, uncalibrated)", metrics_raw)}
{metrics_row("LightGBM (isotonic-calibrated)", metrics_calibrated)}
{metrics_row("Logistic Regression (baseline)", metrics_logreg)}

The Logistic Regression baseline uses ordinal-encoded (not one-hot) categorical
features - one-hot across ~57 categorical columns (several with thousands of
unique values, e.g. `card1`) produced a multi-GB dense design matrix that
wasn't tractable at this scale. LightGBM, the primary model, still gets full
native categorical splits either way; this only affects the comparison
baseline's encoding sophistication, not the production model.

{confusion_block("LightGBM (calibrated)", metrics_calibrated)}

{confusion_block("Logistic Regression (baseline)", metrics_logreg)}

Precision/recall/F1/confusion-matrix are reported at a fixed 0.5 threshold
**for evaluation purposes only** - RiskPilot's actual decision engine (ticket
05) doesn't use a fixed cutoff, it picks the expected-cost-minimizing action
per transaction. PR-AUC and Brier score are threshold-independent and are the
metrics that matter for judging the detector itself.

## Calibration

Isotonic regression fit on the calibration split, evaluated on the held-out
test split. Brier score improved from {metrics_raw['brier_score']} (raw) to
{metrics_calibrated['brier_score']} (calibrated).

**Raw LightGBM output** - reliability by predicted-probability bin:

{curve_table(calib_curve_raw)}

**After isotonic calibration**:

{curve_table(calib_curve_calibrated)}

A well-calibrated model has "mean predicted" close to "empirical fraud rate"
in every bin - that's what the cost-aware decision engine (ticket 05) depends
on, since it treats the output as a real probability in its expected-cost
arithmetic, not just a ranking score.

## What this does not claim

- These are offline metrics on a public, dated (2019) competition dataset,
  not live Razorpay traffic.
- The V-column leakage check is a heuristic (single-feature AUC), not a proof
  of leakage-freedom - Vesta's exact feature computation is undisclosed.
- The fixed-0.5-threshold metrics above are for model evaluation only; the
  deployed system never uses a fixed cutoff for real decisions.
"""
    (DOCS_DIR / "evaluation_report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
