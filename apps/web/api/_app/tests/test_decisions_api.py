"""API-seam tests for POST /decide (ticket 05's explicit acceptance
criterion: 'API-level tests confirm correct action for representative
segment/probability combinations'). Each case's expected action is derived
by hand from the day-1 default cost constants in cost_engine.py - see the
comment on each test for the arithmetic.
"""

import pytest
from fastapi.testclient import TestClient

from _app import db
from _app.main import app

client = TestClient(app)


def _decide(**kwargs) -> dict:
    response = client.post("/decide", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def test_low_probability_low_value_trusted_customer_allows():
    """p=0.02, low band, returning+known: fraud_loss=550, false_decline=75.
    E_allow=11, E_block=73.5, well below review's 80 flat cost alone -> ALLOW."""
    body = _decide(
        probability=0.02,
        merchant_category="food_delivery",
        amount=500,
        is_returning_customer=True,
        is_known_device=True,
    )
    assert body["decision"] == "ALLOW"
    assert set(body["expected_costs"]) == {"ALLOW", "STEP_UP", "REVIEW", "BLOCK"}


def test_high_probability_high_value_new_customer_new_device_blocks():
    """p=0.95, high band, new+new: false_decline_rate=0.40, fraud_loss_rate=1.20.
    On amount=20000: E_block=400 is far below E_review (~3512), E_step_up
    (~7040), and E_allow (~22800) -> BLOCK."""
    body = _decide(
        probability=0.95,
        merchant_category="electronics",
        amount=20000,
        is_returning_customer=False,
        is_known_device=False,
    )
    assert body["decision"] == "BLOCK"
    assert body["expected_costs"]["BLOCK"] < body["expected_costs"]["ALLOW"]
    assert body["expected_costs"]["BLOCK"] < body["expected_costs"]["REVIEW"]


def test_moderate_probability_medium_value_new_customer_reviews():
    """p=0.3, medium band, new customer + known device: false_decline_rate=0.35,
    fraud_loss_rate=1.10. On amount=5000: E_review (~369.5) beats E_block
    (~1225), E_step_up (~820), and E_allow (~1650) -> REVIEW."""
    body = _decide(
        probability=0.3,
        merchant_category="digital_goods",
        amount=5000,
        is_returning_customer=False,
        is_known_device=True,
    )
    assert body["decision"] == "REVIEW"


def test_response_includes_all_required_fields():
    body = _decide(
        probability=0.5,
        merchant_category="travel",
        amount=10000,
        is_returning_customer=True,
        is_known_device=False,
    )
    assert body["cost_profile_source"] == "global_default"
    assert body["amount_band"] == "medium"
    assert len(body["reason_codes"]) > 0
    assert body["probability_used"] == 0.5


def test_missing_segment_fields_without_transaction_id_returns_422():
    response = client.post("/decide", json={"probability": 0.5})
    assert response.status_code == 422


def test_out_of_range_probability_returns_422():
    response = client.post(
        "/decide",
        json={
            "probability": 1.5,
            "merchant_category": "travel",
            "amount": 1000,
            "is_returning_customer": True,
            "is_known_device": True,
        },
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_decide_resolves_segment_fields_from_transaction_id():
    """transaction_id supplies segment fields; probability is still
    supplied explicitly by the caller (not auto-sourced - see DecideRequest's
    docstring on why)."""
    if not db.get_database_url():
        pytest.skip("no database URL in environment")

    create_response = client.post("/transactions/synthetic", json={"count": 1})
    assert create_response.status_code == 200
    [created] = create_response.json()

    body = _decide(transaction_id=created["transaction_id"], probability=0.6)

    assert body["transaction_id"] == created["transaction_id"]
    assert body["merchant_category"] == created["merchant_category"]
    assert body["amount_band"] == created["amount_band"]
    assert body["is_returning_customer"] == created["is_returning_customer"]
    assert body["is_known_device"] == created["is_known_device"]


@pytest.mark.integration
def test_decide_with_unknown_transaction_id_returns_404():
    if not db.get_database_url():
        pytest.skip("no database URL in environment")

    response = client.post("/decide", json={"transaction_id": "txn_does_not_exist", "probability": 0.5})
    assert response.status_code == 404
