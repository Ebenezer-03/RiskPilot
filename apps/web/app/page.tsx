"use client";

import Link from "next/link";
import { useState } from "react";
import { motion } from "framer-motion";
import { STATUS_COLORS, formatCurrency } from "@/app/components/ui";
import { ApiError, decide, generateSyntheticTransactions, type Action, type DecideResponse } from "@/lib/api";

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.52, 0.01, 0, 1] as const } },
};

const primaryPill =
  "rounded-full bg-neon px-7 py-3.5 text-sm font-medium text-obsidian transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";
const ghostPill =
  "rounded-full border border-white/60 px-7 py-3.5 text-sm font-medium text-white transition-colors hover:border-white";

const STATUSES: Action[] = ["ALLOW", "STEP_UP", "REVIEW", "BLOCK"];

const MODULES = [
  { label: "Score", detail: "Calibrated LightGBM detector", color: "bg-neon" },
  { label: "Decide", detail: "4-action expected-cost engine", color: "bg-mint-whisper" },
  { label: "Replay", detail: "Guardrailed policy simulation", color: "bg-signal-yellow" },
  { label: "Audit", detail: "Full decision-level versioning", color: "bg-white" },
];

const SCREENS = [
  {
    href: "/console",
    title: "Live Decision Console",
    description: "Score or generate a transaction and watch the cost engine price every action.",
  },
  {
    href: "/policy-lab",
    title: "Policy Lab",
    description: "Edit cost assumptions, replay a candidate against history, promote it under guardrails.",
  },
  {
    href: "/audit",
    title: "Audit & Monitoring",
    description: "Look up any transaction's full decision trace, and watch approval/fraud trends.",
  },
];

export default function Landing() {
  const [exampleLoading, setExampleLoading] = useState(false);
  const [exampleError, setExampleError] = useState<string | null>(null);
  const [exampleResult, setExampleResult] = useState<DecideResponse | null>(null);

  async function runExample() {
    setExampleLoading(true);
    setExampleError(null);
    setExampleResult(null);
    try {
      const [txn] = await generateSyntheticTransactions(1);
      const probability = txn.raw_features?.generation_fraud_probability;
      const result = await decide({
        transaction_id: txn.transaction_id,
        probability: typeof probability === "number" ? probability : 0.5,
      });
      setExampleResult(result);
    } catch (err) {
      setExampleError(err instanceof ApiError ? err.message : "Failed to run the example.");
    } finally {
      setExampleLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-obsidian font-sans text-white">
      {/* --- Nav --- */}
      <header className="mx-auto flex max-w-[1200px] items-center justify-between px-6 py-6">
        <span className="text-sm font-medium tracking-[0.05em] uppercase">RiskPilot</span>
        <Link href="/console" className={ghostPill}>
          Open the console
        </Link>
      </header>

      {/* --- Hero --- */}
      <section className="mx-auto flex max-w-[1200px] flex-col gap-8 px-6 pt-16 pb-20">
        <motion.p
          initial="hidden"
          animate="show"
          variants={fadeUp}
          className="text-[9px] font-medium tracking-[0.05em] text-neon uppercase"
        >
          Cost-aware fraud decisioning · policy simulation
        </motion.p>
        <motion.h1
          initial="hidden"
          animate="show"
          variants={fadeUp}
          className="max-w-3xl text-5xl leading-[1.1] font-medium sm:text-6xl"
        >
          Every decision, priced.
        </motion.h1>
        <motion.p
          initial="hidden"
          animate="show"
          variants={fadeUp}
          className="max-w-lg text-lg leading-relaxed text-white/80"
        >
          A fixed threshold treats every transaction&apos;s error as equally costly. RiskPilot prices Allow,
          Step-up, Review, and Block against each other per segment - and lets you replay a policy change against
          history, gated by guardrails, before it ever touches a live transaction.
        </motion.p>
        <motion.div initial="hidden" animate="show" variants={fadeUp} className="flex flex-wrap gap-3 pt-2">
          <button onClick={runExample} disabled={exampleLoading} className={primaryPill}>
            {exampleLoading ? "Running…" : "Run an example transaction"}
          </button>
          <Link href="/console" className={ghostPill}>
            Explore the console
          </Link>
        </motion.div>

        {exampleError && <p className="text-sm text-rose-400">{exampleError}</p>}

        {exampleResult && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex flex-wrap items-center gap-4 rounded-3xl bg-mint-frost px-6 py-5 text-obsidian"
          >
            <span
              className={`border px-3 py-1 font-mono text-sm font-semibold tracking-wide ${STATUS_COLORS[exampleResult.decision]}`}
            >
              {exampleResult.decision}
            </span>
            <span className="text-sm">
              {exampleResult.merchant_category} · {exampleResult.amount_band} amount ·{" "}
              {exampleResult.is_returning_customer ? "returning" : "new"} customer
            </span>
            <span className="font-mono text-sm text-slate-text">
              chosen action cost: {formatCurrency(exampleResult.expected_costs[exampleResult.decision])}
            </span>
          </motion.div>
        )}

        {/* Status-color strip - the one place color is loud, and it's the
            product's actual signal (ALLOW/STEP_UP/REVIEW/BLOCK), not
            decoration. */}
        <motion.div
          initial="hidden"
          whileInView="show"
          viewport={{ once: true }}
          variants={fadeUp}
          className="flex flex-wrap gap-6 border-t border-white/10 pt-8"
        >
          {STATUSES.map((status) => (
            <span key={status} className={`border px-3 py-1 font-mono text-xs tracking-wide ${STATUS_COLORS[status]}`}>
              {status}
            </span>
          ))}
        </motion.div>
      </section>

      {/* --- Pipeline illustration --- */}
      <motion.section
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-80px" }}
        variants={fadeUp}
        className="mx-auto max-w-[1200px] px-6 pb-20"
      >
        <div className="rounded-[60px] bg-mint-frost px-8 py-12 text-obsidian sm:px-14">
          <p className="text-[9px] font-medium tracking-[0.05em] uppercase">The pipeline</p>
          <h2 className="mt-2 max-w-xl text-3xl font-medium">One transaction, four accountable stages.</h2>
          <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:items-stretch sm:gap-0">
            {MODULES.map((mod, i) => (
              <div key={mod.label} className="flex flex-1 items-center">
                <div className="flex flex-1 flex-col gap-2 rounded-2xl bg-white p-5 shadow-[1px_0_9px_2px_rgba(0,0,0,0.04)]">
                  <span className={`h-2 w-8 rounded-full ${mod.color}`} />
                  <span className="text-base font-medium">{mod.label}</span>
                  <span className="text-sm text-slate-text">{mod.detail}</span>
                </div>
                {i < MODULES.length - 1 && <span className="hidden px-3 text-2xl text-stone-border sm:block">→</span>}
              </div>
            ))}
          </div>
        </div>
      </motion.section>

      {/* --- Entry points --- */}
      <motion.section
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-80px" }}
        variants={fadeUp}
        className="mx-auto max-w-[1200px] px-6 pb-24"
      >
        <p className="text-[9px] font-medium tracking-[0.05em] text-neon uppercase">Go to</p>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
          {SCREENS.map((screen) => (
            <Link
              key={screen.href}
              href={screen.href}
              className="flex flex-col gap-2 rounded-2xl border border-white/10 p-6 transition-colors hover:border-neon"
            >
              <span className="text-lg font-medium">{screen.title}</span>
              <span className="text-sm text-white/60">{screen.description}</span>
            </Link>
          ))}
        </div>
      </motion.section>

      <footer className="border-t border-white/10 px-6 py-8 text-center text-xs text-white/40">
        Illustrative cost assumptions and synthetic/IEEE-CIS data only - no real Razorpay data, and offline replay
        is an estimate, not proof of causal production impact.
      </footer>
    </div>
  );
}
