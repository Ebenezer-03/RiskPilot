"""API-seam tests for the Razorpay Test Mode auto-responder (ticket 14).

We don't have real Razorpay test-mode credentials in this environment, so
the actual Orders/Refunds HTTP calls (razorpay_client.create_order /
create_refund) are monkeypatched - everything else (signature verification,
transaction persistence, the real /decide call, the audit trail, the
BLOCK -> refund wiring) runs for real against the real DB, same pattern as
test_transactions_api.py.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from _app import db
from _app.main import app
from _app.routers import razorpay as razorpay_router

client = TestClient(app)

pytestmark = pytest.mark.integration


def _skip_without_db():
    if not db.get_database_url():
        pytest.skip("no database URL in environment")


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_checkout_returns_503_when_not_configured(monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    response = client.post(
        "/razorpay/checkout",
        json={"merchant_category": "electronics", "amount": 15000, "is_returning_customer": True, "is_known_device": True},
    )

    assert response.status_code == 503


def test_checkout_creates_order_and_transaction_row(monkeypatch):
    _skip_without_db()
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
    monkeypatch.setattr(
        razorpay_router, "create_order", lambda *, amount_paise, currency, receipt: {"id": "order_fake123"}
    )

    response = client.post(
        "/razorpay/checkout",
        json={"merchant_category": "electronics", "amount": 15000, "is_returning_customer": True, "is_known_device": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["razorpay_order_id"] == "order_fake123"
    assert body["transaction_id"] == "txn_razorpay_order_fake123"
    assert body["razorpay_key_id"] == "rzp_test_fake"

    read_response = client.get(f"/transactions/{body['transaction_id']}")
    assert read_response.status_code == 200
    txn = read_response.json()
    assert txn["data_source"] == "live_razorpay"
    assert txn["is_fraud"] is None


def test_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_fake")

    response = client.post(
        "/razorpay/webhook",
        content=json.dumps({"event": "payment.captured", "payload": {}}),
        headers={"X-Razorpay-Signature": "not-the-real-signature"},
    )

    assert response.status_code == 400


def test_webhook_rejects_missing_signature(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_fake")

    response = client.post("/razorpay/webhook", content=json.dumps({"event": "payment.captured", "payload": {}}))

    assert response.status_code == 400


def test_webhook_scores_captured_payment_and_records_decision(monkeypatch):
    _skip_without_db()
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_fake")
    monkeypatch.setattr(
        razorpay_router, "create_order", lambda *, amount_paise, currency, receipt: {"id": "order_fake456"}
    )

    checkout = client.post(
        "/razorpay/checkout",
        # Returning customer + known device + low amount -> the cheapest
        # segment the heuristic can produce, so this should decide ALLOW
        # and never reach the refund path.
        json={"merchant_category": "digital_goods", "amount": 500, "is_returning_customer": True, "is_known_device": True},
    )
    assert checkout.status_code == 200

    event_body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_fake456", "order_id": "order_fake456"}}},
        }
    ).encode()
    signature = _sign(event_body, "whsec_fake")

    response = client.post("/razorpay/webhook", content=event_body, headers={"X-Razorpay-Signature": signature})

    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == "txn_razorpay_order_fake456"
    assert body["decision"] == "ALLOW"
    assert body["refund_issued"] is False

    trace = client.get(f"/audit/{body['transaction_id']}")
    assert trace.status_code == 200
    assert trace.json()["decisions"][0]["action"] == "ALLOW"


def test_webhook_block_decision_triggers_refund(monkeypatch):
    _skip_without_db()
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "fake_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_fake")
    monkeypatch.setattr(
        razorpay_router, "create_order", lambda *, amount_paise, currency, receipt: {"id": "order_fake789"}
    )
    refund_calls = []
    monkeypatch.setattr(
        razorpay_router,
        "create_refund",
        lambda payment_id, **kwargs: refund_calls.append(payment_id) or {"id": "rfnd_fake"},
    )
    # estimate_fraud_probability's realistic ceiling (new customer + new
    # device + high amount = 0.25) lands in REVIEW, not BLOCK, under the
    # default cost assumptions - forcing a high probability here isolates
    # the BLOCK -> refund wiring itself from that heuristic's range.
    monkeypatch.setattr(razorpay_router, "estimate_fraud_probability", lambda *args, **kwargs: 0.9)

    checkout = client.post(
        "/razorpay/checkout",
        json={
            "merchant_category": "electronics",
            "amount": 200000,
            "is_returning_customer": False,
            "is_known_device": False,
        },
    )
    assert checkout.status_code == 200

    event_body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_fake789", "order_id": "order_fake789"}}},
        }
    ).encode()
    signature = _sign(event_body, "whsec_fake")

    response = client.post("/razorpay/webhook", content=event_body, headers={"X-Razorpay-Signature": signature})

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "BLOCK"
    assert body["refund_issued"] is True
    assert refund_calls == ["pay_fake789"]


def test_webhook_ignores_unscored_event_types(monkeypatch):
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_fake")
    event_body = json.dumps({"event": "order.paid", "payload": {}}).encode()
    signature = _sign(event_body, "whsec_fake")

    response = client.post("/razorpay/webhook", content=event_body, headers={"X-Razorpay-Signature": signature})

    assert response.status_code == 200
    assert response.json()["decision"] is None
