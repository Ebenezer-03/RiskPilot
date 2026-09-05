"use client";

/**
 * Ticket 14's "checkout trigger page" - creates a real Razorpay Test Mode
 * order (Orders API) and opens Razorpay's own Checkout overlay against it.
 * Paying (in Test Mode, with Razorpay's documented test card/UPI details)
 * fires a real payment.authorized/payment.captured webhook at
 * /api/razorpay/webhook, which scores the payment through the same
 * /decide engine every other data source goes through and - on BLOCK -
 * issues a real Refunds API call. That scoring happens server-side,
 * asynchronously; this page's job ends at "payment captured", so it points
 * you at the Audit trail to see what the webhook decided.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import Script from "next/script";
import { NavHeader } from "@/app/components/nav-header";
import { CurrencyInput, Field, Panel, Select, Switch, primaryButtonClass } from "@/app/components/ui";
import { ApiError, createRazorpayCheckout, type MerchantCategory } from "@/lib/api";

const MERCHANT_CATEGORIES: MerchantCategory[] = ["electronics", "food_delivery", "digital_goods", "travel"];

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void };
  }
}

export default function RazorpayDemo() {
  const [scriptReady, setScriptReady] = useState(false);
  const [merchantCategory, setMerchantCategory] = useState<MerchantCategory>("electronics");
  const [amount, setAmount] = useState("15000");
  const [isReturningCustomer, setIsReturningCustomer] = useState(true);
  const [isKnownDevice, setIsKnownDevice] = useState(true);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paidTxnId, setPaidTxnId] = useState<string | null>(null);

  // Razorpay's Checkout overlay posts back to this page via its own JS
  // handlers, not a redirect - nothing to read from the URL on mount.
  useEffect(() => {}, []);

  async function startCheckout() {
    setLoading(true);
    setError(null);
    setPaidTxnId(null);
    try {
      const order = await createRazorpayCheckout({
        merchant_category: merchantCategory,
        amount: Number(amount),
        is_returning_customer: isReturningCustomer,
        is_known_device: isKnownDevice,
      });

      if (!scriptReady || !window.Razorpay) {
        throw new Error("Razorpay Checkout script hasn't loaded yet - wait a moment and try again.");
      }

      const razorpay = new window.Razorpay({
        key: order.razorpay_key_id,
        amount: order.amount_paise,
        currency: order.currency,
        order_id: order.razorpay_order_id,
        name: "RiskPilot (Test Mode)",
        description: `${merchantCategory} - demo checkout`,
        handler: () => setPaidTxnId(order.transaction_id),
        modal: { ondismiss: () => setLoading(false) },
      });
      razorpay.open();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Failed to start checkout.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-obsidian font-sans text-zinc-100">
      <Script src="https://checkout.razorpay.com/v1/checkout.js" onLoad={() => setScriptReady(true)} />
      <NavHeader endpoints="/razorpay/checkout · /razorpay/webhook" />

      <main className="mx-auto flex max-w-3xl flex-col gap-4 p-6">
        <Panel title="Razorpay Test Mode checkout · POST /razorpay/checkout">
          <p className="text-sm text-zinc-400">
            Creates a real Razorpay Test Mode order and opens Razorpay&apos;s own Checkout overlay. Pay with{" "}
            <a
              href="https://razorpay.com/docs/payments/payments/test-card-upi-details/"
              target="_blank"
              rel="noreferrer"
              className="text-neon hover:underline"
            >
              Razorpay&apos;s documented test card/UPI details
            </a>{" "}
            - no real money moves. The resulting webhook scores the payment through the real decision engine and, on a
            BLOCK decision, issues a real Refunds API call against the captured test payment.
          </p>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Merchant category">
              <Select
                value={merchantCategory}
                onValueChange={(v) => setMerchantCategory(v as MerchantCategory)}
                options={MERCHANT_CATEGORIES.map((c) => ({ value: c, label: c }))}
              />
            </Field>
            <Field label="Amount (INR)">
              <CurrencyInput value={amount} onChange={setAmount} />
            </Field>
          </div>
          <div className="flex flex-wrap gap-4 border-t border-zinc-800 pt-4">
            <Switch checked={isReturningCustomer} onCheckedChange={setIsReturningCustomer} label="Returning customer" />
            <Switch checked={isKnownDevice} onCheckedChange={setIsKnownDevice} label="Known device" />
          </div>
          <p className="text-xs text-zinc-400">
            A real Razorpay payment carries none of the IEEE-CIS-shaped ML features /score needs, so these two flags -
            not a model score - drive the same illustrative fraud-probability heuristic the synthetic generator uses.
          </p>

          <button onClick={startCheckout} disabled={loading} className={`${primaryButtonClass} self-start`}>
            {loading ? "Opening checkout…" : "Pay with Razorpay (Test Mode)"}
          </button>
          {error && <p className="text-sm text-rose-400">{error}</p>}

          {paidTxnId && (
            <div className="flex flex-col gap-2 border-t border-zinc-800 pt-4">
              <p className="text-sm text-emerald-400">
                Payment captured. The webhook scores it asynchronously - usually within a few seconds.
              </p>
              <p className="font-mono text-xs text-zinc-400">{paidTxnId}</p>
              <Link href="/audit" className="text-sm text-neon hover:underline">
                Look it up in the Audit trail →
              </Link>
            </div>
          )}
        </Panel>
      </main>
    </div>
  );
}
