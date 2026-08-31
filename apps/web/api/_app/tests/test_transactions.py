"""Pure-function coverage for segment resolution and the synthetic
generator's feature correlations, plus the IEEE-CIS mapper - the narrow
exception to the API-only seam (see docs, and test_health.py/test_score.py
for the primary HTTP-seam tests). The actual persistence round-trip is
covered at the API seam in test_transactions_api.py.
"""

import random

import pytest

from _app.segments import MERCHANT_CATEGORIES, resolve_amount_band
from _app.transactions import generate_synthetic_transaction, record_from_ieee_cis_row


def test_resolve_amount_band_boundaries():
    assert resolve_amount_band(0) == "low"
    assert resolve_amount_band(999.99) == "low"
    assert resolve_amount_band(1_000) == "medium"
    assert resolve_amount_band(15_000) == "medium"
    assert resolve_amount_band(15_000.01) == "high"
    assert resolve_amount_band(500_000) == "high"


def test_generated_transaction_has_expected_shape():
    record = generate_synthetic_transaction(random.Random(42))
    assert record["data_source"] == "synthetic"
    assert record["transaction_id"].startswith("txn_synthetic_")
    assert record["merchant_category"] in MERCHANT_CATEGORIES
    assert record["amount_band"] in {"low", "medium", "high"}
    assert record["amount"] > 0
    assert isinstance(record["is_fraud"], bool)


def test_generated_labels_are_not_i_i_d_random():
    """The acceptance criterion is 'realistic feature correlations, not
    random fraud labels' - verify the correlation actually holds: a large
    sample of new-customer/new-device/high-amount transactions should have
    a materially higher fraud rate than returning/known-device/low-amount
    ones. A purely random generator (fixed p regardless of features) would
    fail this with overwhelming probability at this sample size."""
    rng = random.Random(7)
    high_risk_fraud_count = 0
    high_risk_total = 0
    low_risk_fraud_count = 0
    low_risk_total = 0

    # Force the feature combination directly rather than filtering random
    # draws, so the test is fast and deterministic about which regime it's
    # measuring - the correlation is in generate_synthetic_transaction's
    # probability formula, exercised the same way either way.
    for _ in range(3000):
        record = generate_synthetic_transaction(rng)
        is_high_risk_shape = (
            not record["is_returning_customer"] and not record["is_known_device"] and record["amount_band"] == "high"
        )
        is_low_risk_shape = (
            record["is_returning_customer"] and record["is_known_device"] and record["amount_band"] == "low"
        )
        if is_high_risk_shape:
            high_risk_total += 1
            high_risk_fraud_count += record["is_fraud"]
        elif is_low_risk_shape:
            low_risk_total += 1
            low_risk_fraud_count += record["is_fraud"]

    assert high_risk_total > 20 and low_risk_total > 20, "need enough samples of each shape to compare rates"
    high_risk_rate = high_risk_fraud_count / high_risk_total
    low_risk_rate = low_risk_fraud_count / low_risk_total
    assert high_risk_rate > low_risk_rate * 3, (
        f"expected new+new+high fraud rate ({high_risk_rate:.3f}) to be well above "
        f"returning+known+low fraud rate ({low_risk_rate:.3f})"
    )


def test_record_from_ieee_cis_row_maps_known_fields():
    row = {
        "TransactionID": 3577004,
        "TransactionAmt": 25000.0,
        "ProductCD": "R",
        "D1": 45.0,
        "DeviceType": "mobile",
        "isFraud": 1,
    }

    record = record_from_ieee_cis_row(row)

    assert record["transaction_id"] == "txn_ieee_3577004"
    assert record["data_source"] == "ieee_cis"
    assert record["amount"] == 25000.0
    assert record["merchant_category"] == "electronics"  # ProductCD "R" per the illustrative mapping
    assert record["amount_band"] == "high"
    assert record["is_returning_customer"] is True  # D1=45 > 30
    assert record["is_known_device"] is True  # DeviceType present
    assert record["is_fraud"] is True
    assert record["raw_features"] == row


def test_record_from_ieee_cis_row_handles_missing_identity_data():
    row = {
        "TransactionID": 1,
        "TransactionAmt": 50.0,
        "ProductCD": "W",
        "D1": None,
        "DeviceType": None,
        "isFraud": 0,
    }

    record = record_from_ieee_cis_row(row)

    assert record["is_returning_customer"] is False
    assert record["is_known_device"] is False
    assert record["amount_band"] == "low"
