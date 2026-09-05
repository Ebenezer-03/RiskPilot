"""Fraud-scoring service: loads the trained artifacts once at process start
and scores individual transactions, producing a calibrated probability plus
SHAP-derived reason codes.

Deliberately does not import api._app.ml.train (training-only, pulls in
pandas-heavy offline tooling and is not meant to run inside the deployed
function - training is offline-only per the spec). This module only reads
the artifacts train.py already produced.

Reason codes are computed via LightGBM's own native `pred_contrib=True`
(booster.predict), not the external `shap` package - it runs the same
TreeSHAP algorithm shap.TreeExplainer would (LightGBM implements it
in-tree), with zero extra dependencies. This matters concretely on Vercel:
shap's own declared dependencies always pull in numba+llvmlite (~150MB)
for accelerating explainer types this app doesn't even use, and that was
enough on its own to push the deployed function bundle over Vercel's 500MB
per-function limit.
"""

from __future__ import annotations

import ctypes
import glob
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

import joblib

_logger = logging.getLogger(__name__)

_REAL_LIBGOMP_SONAME = b"libgomp.so.1\x00"


def _preload_bundled_libgomp() -> None:
    """Vercel's Python Functions run on a minimal Linux base image with no
    system libgomp (GNU OpenMP) installed, but the official `lightgbm`
    manylinux wheel dynamically links against it without bundling it (a
    known upstream packaging gap - microsoft/LightGBM#4484) - importing
    lightgbm there fails with `OSError: libgomp.so.1: cannot open shared
    object file`.

    numpy/scipy/scikit-learn's own manylinux wheels vendor a private copy
    of libgomp too (under a `<pkg>.libs/` sibling directory), but two
    approaches that both sound like they should reuse it were tried and
    empirically failed against a real deployment:

    1. ctypes.CDLL-loading the vendored file directly (RTLD_GLOBAL) - it
       loads fine, but doesn't help. auditwheel renames vendored copies
       with a hash suffix (e.g. `libgomp-a34b3233.so.1.0.0`) *and patches
       their ELF DT_SONAME to match that new name*, specifically so two
       packages' own bundled copies never collide. The loaded object
       therefore registers under its hashed soname, not "libgomp.so.1" -
       it can't satisfy lightgbm's dependency on that literal name.
    2. Copying the vendored file to a writable dir renamed to
       `libgomp.so.1` and adding that dir to LD_LIBRARY_PATH (mutating
       os.environ, which does update the process's real environment) -
       still didn't help. The renamed *file* doesn't carry a renamed
       *soname*; the underlying dynamic linker in this runtime evidently
       isn't re-resolving lightgbm's dlopen against a directory search
       here either.

    What actually works: patch the copy's own DT_SONAME string in place to
    the literal bytes "libgomp.so.1\\0", then ctypes.CDLL it directly by
    path with RTLD_GLOBAL. auditwheel's hashed soname is stored as a plain
    null-terminated string in the .dynstr section - overwriting those exact
    bytes with a *same-length-or-shorter*, null-padded replacement doesn't
    move any other byte offset in the file, so nothing else in the ELF
    needs re-parsing or re-linking. Once genuinely loaded under the soname
    "libgomp.so.1", lightgbm's own dlopen finds it via the already-loaded-
    object check before ever touching the filesystem.

    A genuine no-op on Windows/macOS (the glob simply won't match anything
    there)."""
    candidates: list[str] = []
    for root in sys.path:
        if not root:
            continue
        candidates.extend(glob.glob(f"{root}/**/libgomp*.so*", recursive=True))

    if not candidates:
        _logger.warning("libgomp preload: no bundled libgomp*.so* found under any sys.path entry.")
        return

    source = candidates[0]
    data = bytearray(Path(source).read_bytes())
    own_soname = (Path(source).name + "\x00").encode()
    offset = data.find(own_soname)
    if offset == -1 or len(_REAL_LIBGOMP_SONAME) > len(own_soname):
        _logger.warning("libgomp preload: could not locate a patchable soname string in %s.", source)
        return

    patched = _REAL_LIBGOMP_SONAME.ljust(len(own_soname), b"\x00")
    data[offset : offset + len(own_soname)] = patched

    patched_path = Path(tempfile.gettempdir()) / "riskpilot_libgomp_compat" / "libgomp.so.1"
    patched_path.parent.mkdir(exist_ok=True)
    patched_path.write_bytes(bytes(data))

    try:
        ctypes.CDLL(str(patched_path), mode=ctypes.RTLD_GLOBAL)
        _logger.info("libgomp preload: patched soname in %s and loaded %s", source, patched_path)
    except OSError as exc:
        _logger.warning("libgomp preload: patched copy at %s still failed to load (%s)", patched_path, exc)


_preload_bundled_libgomp()

import lightgbm as lgb  # noqa: E402 - must follow the libgomp preload above
import pandas as pd

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
        # LightGBM's own pred_contrib=True runs the exact TreeSHAP algorithm
        # in-tree - one row of per-feature contributions to the model's raw
        # margin output (the fraud-class direction), plus one trailing bias
        # (expected-value) term that isn't a feature contribution at all and
        # must be dropped before zipping against ALL_FEATURE_COLUMNS.
        contribs = self.booster.predict(row, pred_contrib=True)[0]
        values = contribs[:-1]
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
