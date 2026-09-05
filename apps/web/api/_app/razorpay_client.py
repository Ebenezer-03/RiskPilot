"""Thin Razorpay Test Mode API client (ticket 14 - the auto-responder
integration). Hand-rolled against Razorpay's plain REST API (stdlib
`urllib` + basic auth), not the `razorpay` SDK - one fewer dependency for
three small calls (create order, verify a webhook signature, create a
refund).

Configuration: RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET (API auth, from the
Razorpay Dashboard's Test Mode API Keys screen) and RAZORPAY_WEBHOOK_SECRET
(a separate shared secret you set when registering the webhook URL in the
Dashboard - not the API secret). All three are test-mode credentials by
design; this module never touches live-mode keys, and nothing here should
ever run against a live Razorpay account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request

_API_BASE = "https://api.razorpay.com/v1"


def is_configured() -> bool:
    return bool(os.environ.get("RAZORPAY_KEY_ID") and os.environ.get("RAZORPAY_KEY_SECRET"))


def webhook_is_configured() -> bool:
    return bool(os.environ.get("RAZORPAY_WEBHOOK_SECRET"))


class RazorpayError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"Razorpay API error ({status}): {detail}")
        self.status = status
        self.detail = detail


def _request(method: str, path: str, body: dict | None = None) -> dict:
    key_id = os.environ.get("RAZORPAY_KEY_ID")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay not configured (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET).")

    auth = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{_API_BASE}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RazorpayError(exc.code, detail) from exc


def create_order(*, amount_paise: int, currency: str, receipt: str) -> dict:
    """Orders API - a real Razorpay Test Mode order, not a simulated one.
    Amount is in the smallest currency unit (paise for INR), per Razorpay's
    own convention."""
    return _request(
        "POST",
        "/orders",
        {"amount": amount_paise, "currency": currency, "receipt": receipt, "payment_capture": 1},
    )


def create_refund(payment_id: str, *, notes: dict | None = None) -> dict:
    """Refunds API - the BLOCK-decision enforcement action (ticket 14's
    acceptance criterion). Full refund of a captured test payment; no
    partial-amount support needed for this demo's scope."""
    return _request("POST", f"/payments/{payment_id}/refund", {"notes": notes or {}})


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    """HMAC-SHA256 of the raw request body against RAZORPAY_WEBHOOK_SECRET,
    compared with `hmac.compare_digest` (constant-time) rather than `==` -
    ticket 14's acceptance criterion is explicit that an unsigned/invalid
    payload must be rejected, not silently trusted."""
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
