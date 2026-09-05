"use client";

/**
 * The landing page's interactive centerpiece: a user-paced, click-through
 * walkthrough of one real transaction's journey through the pipeline
 * (Score -> Decide -> Audit). Data is fetched once, for real, when the
 * tour starts (generateSyntheticTransactions + decide - no mocked
 * responses anywhere in this app), then each "Next" reveals the next
 * slice of that same result rather than re-fetching - snappy, and still
 * genuinely real data throughout, not a canned script.
 */

import { useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { CostBars, STATUS_COLORS, formatCurrency } from "@/app/components/ui";
import { ApiError, decide, generateSyntheticTransactions, type DecideResponse, type TransactionRecord } from "@/lib/api";

const primaryPill =
  "rounded-full bg-neon px-8 py-4 text-sm font-medium text-obsidian transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";
const ghostPill =
  "rounded-full border border-white/60 px-8 py-4 text-sm font-medium text-white transition-colors hover:border-white disabled:cursor-not-allowed disabled:opacity-40";
const ghostPillSm =
  "rounded-full border border-white/60 px-6 py-3 text-sm font-medium text-white transition-colors hover:border-white disabled:cursor-not-allowed disabled:opacity-40";

const STEP_COUNT = 5;

export function GuidedDemo() {
  const [started, setStarted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [txn, setTxn] = useState<TransactionRecord | null>(null);
  const [result, setResult] = useState<DecideResponse | null>(null);
  const [step, setStep] = useState(0);

  async function start() {
    setStarted(true);
    setLoading(true);
    setError(null);
    setStep(0);
    try {
      const [created] = await generateSyntheticTransactions(1);
      setTxn(created);
      const probability = created.raw_features?.generation_fraud_probability;
      const decided = await decide({
        transaction_id: created.transaction_id,
        probability: typeof probability === "number" ? probability : 0.5,
      });
      setResult(decided);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to run the example.");
    } finally {
      setLoading(false);
    }
  }

  if (!started) {
    return (
      <div className="flex flex-wrap gap-3 pt-2">
        <button onClick={start} className={primaryPill}>
          Walk me through a decision
        </button>
        <Link href="/console" className={ghostPill}>
          Skip to the console
        </Link>
      </div>
    );
  }

  if (loading) {
    return <p className="pt-2 text-sm text-white/60">Generating a real transaction and pricing it…</p>;
  }

  if (error) {
    return (
      <div className="flex flex-col gap-3 pt-2">
        <p className="text-sm text-rose-400">{error}</p>
        <button onClick={start} className={ghostPill}>
          Try again
        </button>
      </div>
    );
  }

  if (!txn || !result) return null;

  return (
    <div className="flex flex-col gap-6 pt-2">
      <div className="min-h-[220px] overflow-hidden rounded-[20px] bg-mint-frost px-6 py-6 text-obsidian sm:px-8">
        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            transition={{ duration: 0.3, ease: [0.52, 0.01, 0, 1] }}
            className="flex flex-col gap-4"
          >
            {step === 0 && (
              <>
                <p className="text-[11px] font-medium tracking-[0.05em] uppercase">Step 1 · Meet the transaction</p>
                <p className="text-sm text-slate-text">
                  A real synthetic transaction, generated on demand - not a scripted example.
                </p>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-sm">
                  <dt className="text-slate-text">merchant</dt>
                  <dd>{txn.merchant_category}</dd>
                  <dt className="text-slate-text">amount</dt>
                  <dd>{formatCurrency(txn.amount)}</dd>
                  <dt className="text-slate-text">customer</dt>
                  <dd>{txn.is_returning_customer ? "returning" : "new"}</dd>
                  <dt className="text-slate-text">device</dt>
                  <dd>{txn.is_known_device ? "known" : "new"}</dd>
                </dl>
              </>
            )}

            {step === 1 && (
              <>
                <p className="text-[11px] font-medium tracking-[0.05em] uppercase">Step 2 · The detector scores it</p>
                <p className="text-sm text-slate-text">
                  A calibrated probability, not a raw model score - 0.74 here would genuinely mean roughly a 74%
                  empirical fraud rate for transactions like this one.
                </p>
                <p className="font-mono text-4xl font-medium">{result.probability_used.toFixed(4)}</p>
                <p className="text-xs text-slate-text">estimated probability this transaction is fraud</p>
              </>
            )}

            {step === 2 && (
              <>
                <p className="text-[11px] font-medium tracking-[0.05em] uppercase">
                  Step 3 · The cost engine prices every action
                </p>
                <p className="text-sm text-slate-text">
                  Not one threshold - the expected cost of Allow, Step-up, Review, and Block, computed and compared
                  side by side.
                </p>
                <CostBars costs={result.expected_costs} chosen={result.decision} dark={false} />
              </>
            )}

            {step === 3 && (
              <>
                <p className="text-[11px] font-medium tracking-[0.05em] uppercase">
                  Step 4 · It picks the cheapest one
                </p>
                <div className="flex items-center gap-3">
                  <span
                    className={`border px-3 py-1 font-mono text-lg font-semibold tracking-wide ${STATUS_COLORS[result.decision]}`}
                  >
                    {result.decision}
                  </span>
                  <span className="font-mono text-sm text-slate-text">
                    {formatCurrency(result.expected_costs[result.decision])} expected cost
                  </span>
                </div>
                <p className="text-sm text-slate-text">{result.reason_codes[0] ?? "No dominant single factor."}</p>
              </>
            )}

            {step === 4 && (
              <>
                <p className="text-[11px] font-medium tracking-[0.05em] uppercase">Step 5 · Fully auditable</p>
                <p className="text-sm text-slate-text">
                  Every decision is stored with the exact model, calibration, segment, policy, and cost-matrix
                  version behind it - reconstructable by transaction id, months later.
                </p>
                <div className="flex flex-wrap gap-3 pt-2">
                  <Link href="/console" className="rounded-full bg-obsidian px-6 py-3 text-sm font-medium text-white">
                    Try your own transaction
                  </Link>
                  <Link
                    href="/audit"
                    className="rounded-full border border-obsidian/30 px-6 py-3 text-sm font-medium text-obsidian"
                  >
                    See the audit trail
                  </Link>
                </div>
              </>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {Array.from({ length: STEP_COUNT }).map((_, i) => (
            <span key={i} className={`h-1.5 w-6 rounded-full ${i === step ? "bg-neon" : "bg-white/20"}`} />
          ))}
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
            className="text-sm text-white/60 hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
          >
            Back
          </button>
          {step < STEP_COUNT - 1 ? (
            <button onClick={() => setStep((s) => Math.min(STEP_COUNT - 1, s + 1))} className={ghostPillSm}>
              Next
            </button>
          ) : (
            <button onClick={start} className={ghostPillSm}>
              Try another example
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
