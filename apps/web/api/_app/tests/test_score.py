"""API-seam tests for /score (ticket 03c).

Fixtures are real held-out-test-split rows from the IEEE-CIS dataset (see
tests/fixtures/generate_fixtures.py), not synthetic/hand-crafted - a
"clearly fraudulent" and a "clearly legitimate" example picked by the
trained model's own most-extreme calibrated probabilities on data it never
trained on.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _app.main import app

client = TestClient(app)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


def _artifacts_available() -> bool:
    from _app.ml.features import CALIBRATOR_ARTIFACT_FILENAME, MODEL_ARTIFACT_FILENAME

    artifacts_dir = Path(__file__).resolve().parents[1] / "artifacts"
    return (artifacts_dir / MODEL_ARTIFACT_FILENAME).exists() and (
        artifacts_dir / CALIBRATOR_ARTIFACT_FILENAME
    ).exists()


pytestmark = pytest.mark.skipif(
    not _artifacts_available(),
    reason="model/calibrator artifacts not present - run `python -m _app.ml.train` first",
)


def test_fraud_shaped_input_scores_high():
    fixture = _load_fixture("fraud_example")

    response = client.post("/score", json={
        "transaction_id": str(fixture["transaction_id"]),
        "features": fixture["features"],
    })

    assert response.status_code == 200
    body = response.json()
    assert body["fraud_probability_calibrated"] > 0.5
    assert body["model_version"]
    assert body["calibration_version"]


def test_legitimate_shaped_input_scores_low():
    fixture = _load_fixture("legitimate_example")

    response = client.post("/score", json={
        "transaction_id": str(fixture["transaction_id"]),
        "features": fixture["features"],
    })

    assert response.status_code == 200
    body = response.json()
    assert body["fraud_probability_calibrated"] < 0.1


def test_response_includes_nonempty_reason_codes():
    fixture = _load_fixture("fraud_example")

    response = client.post("/score", json={
        "transaction_id": str(fixture["transaction_id"]),
        "features": fixture["features"],
    })

    assert response.status_code == 200
    reason_codes = response.json()["reason_codes"]
    assert isinstance(reason_codes, list)
    assert len(reason_codes) > 0
    assert all(isinstance(code, str) and code for code in reason_codes)


def test_score_with_no_features_does_not_crash():
    """An empty/sparse payload (nothing known about the transaction yet)
    should still return a valid response - every feature is NaN/missing,
    which LightGBM and the categorical coercion both handle natively."""
    response = client.post("/score", json={"transaction_id": "txn_empty", "features": {}})

    assert response.status_code == 200
    body = response.json()
    assert 0.0 <= body["fraud_probability_calibrated"] <= 1.0
