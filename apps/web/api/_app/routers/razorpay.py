"""Razorpay Test Mode auto-responder (ticket 14): a checkout trigger page
creates a real test-mode order, a verified webhook scores the resulting
payment through the same /decide engine every other data source goes
through, and a BLOCK decision issues a real Refunds API call against the
captured test payment.

Explicitly **post-capture enforcement, not pre-authorization interception**:
Razorpay's own Test Mode checkout flow authorizes and captures the payment
before this webhook ever fires (see Razorpay's Payments + Webhooks docs) -
there is no hook point before capture available to a webhook-based
integration, so a BLOCK here can only refund an already-captured payment,
not prevent the charge. A pre-auth interception model would need Razorpay's
Route/Payment Links-level hold-and-release primitives, out of scope here.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from . import get_connection_or_503
from .. import db
from ..razorpay_client import (
    RazorpayError,
    create_order,
    create_refund,
    is_configured,
    verify_webhook_signature,
    webhook_is_configured,
)
from ..schemas import DecideRequest, RazorpayCheckoutRequest, RazorpayCheckoutResponse, RazorpayWebhookResult
from ..segments import resolve_amount_band
from ..transactions import estimate_fraud_probability, get_transaction, insert_transaction
from .decisions import decide

router = APIRouter(prefix="/razorpay", tags=["razorpay"])


@router.post("/checkout", response_model=RazorpayCheckoutResponse)
async def create_checkout(payload: RazorpayCheckoutRequest) -> RazorpayCheckoutResponse:
    """Creates a real Razorpay Test Mode order (Orders API) and persists a
    matching `data_source=live_razorpay` transaction row up front, so the
    webhook has something to attach the eventual decision to - and so an
    order that's created but never paid still shows up as a real,
    inspectable row rather than silently not existing."""
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail="Razorpay not configured (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET env vars missing).",
        )

    amount_paise = round(payload.amount * 100)
    receipt = f"riskpilot_{uuid.uuid4().hex[:12]}"
    try:
        order = create_order(amount_paise=amount_paise, currency="INR", receipt=receipt)
    except RazorpayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    transaction_id = f"txn_razorpay_{order['id']}"
    conn = get_connection_or_503()
    with conn:
        db.ensure_schema(conn)
        insert_transaction(
            conn,
            {
                "transaction_id": transaction_id,
                "data_source": "live_razorpay",
                "event_time": datetime.now(timezone.utc),
                "amount": payload.amount,
                "currency": "INR",
                "merchant_id": None,
                "merchant_category": payload.merchant_category,
                "amount_band": resolve_amount_band(payload.amount),
                "is_returning_customer": payload.is_returning_customer,
                "is_known_device": payload.is_known_device,
                # Unlabeled, same as any other live event with no ground
                # truth (see audit/page.tsx's three-way ground-truth
                # rendering) - a real payment has no fraud label to attach.
                "is_fraud": None,
                "raw_features": {"razorpay_order_id": order["id"], "razorpay_receipt": receipt},
            },
        )

    return RazorpayCheckoutResponse(
        transaction_id=transaction_id,
        razorpay_order_id=order["id"],
        razorpay_key_id=os.environ["RAZORPAY_KEY_ID"],
        amount_paise=amount_paise,
        currency="INR",
    )


@router.post("/webhook", response_model=RazorpayWebhookResult)
async def razorpay_webhook(request: Request) -> RazorpayWebhookResult:
    """Verifies the Razorpay signature before touching the payload at all -
    an unsigned or invalid payload is rejected outright (ticket 14's
    acceptance criterion), not merely logged and continued."""
    if not webhook_is_configured():
        raise HTTPException(status_code=503, detail="Razorpay webhook not configured (RAZORPAY_WEBHOOK_SECRET missing).")

    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    if not verify_webhook_signature(raw_body, signature):
        raise HTTPException(status_code=400, detail="Invalid or missing Razorpay webhook signature.")

    payload = json.loads(raw_body)
    event = payload.get("event", "")

    if event not in ("payment.authorized", "payment.captured"):
        # Razorpay sends many event types to the same webhook URL; anything
        # not scored here (refund.processed, order.paid, ...) is
        # acknowledged with 200 so Razorpay doesn't retry it forever, but
        # isn't otherwise acted on.
        return RazorpayWebhookResult(event=event, detail="Event not scored by this integration - acknowledged only.")

    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    order_id = payment_entity.get("order_id")
    if not payment_id or not order_id:
        raise HTTPException(status_code=422, detail="Webhook payload missing payment.entity.id/order_id.")

    transaction_id = f"txn_razorpay_{order_id}"
    conn = get_connection_or_503()
    with conn:
        db.ensure_schema(conn)
        record = get_transaction(conn, transaction_id)
    if record is None:
        # The order was created outside /razorpay/checkout (e.g. directly in
        # the Razorpay Dashboard) - nothing to score against, acknowledge
        # rather than 404 so Razorpay doesn't retry indefinitely.
        return RazorpayWebhookResult(
            event=event, detail=f"No transaction row for order {order_id!r} - not created via /razorpay/checkout."
        )

    probability = estimate_fraud_probability(
        record["amount_band"], record["is_returning_customer"], record["is_known_device"]
    )
    result = await decide(DecideRequest(transaction_id=transaction_id, probability=probability))

    refund_issued = False
    if result.decision == "BLOCK":
        try:
            create_refund(payment_id, notes={"reason": "riskpilot_block_decision", "transaction_id": transaction_id})
            refund_issued = True
        except RazorpayError as exc:
            # The decision is already recorded either way - a refund-API
            # failure (payment already refunded, network error) shouldn't
            # make the webhook itself fail and get retried into a duplicate
            # decision; surface it in the response instead.
            return RazorpayWebhookResult(
                event=event,
                transaction_id=transaction_id,
                decision=result.decision,
                refund_issued=False,
                detail=f"BLOCK decided but refund failed: {exc}",
            )

    return RazorpayWebhookResult(
        event=event, transaction_id=transaction_id, decision=result.decision, refund_issued=refund_issued
    )
