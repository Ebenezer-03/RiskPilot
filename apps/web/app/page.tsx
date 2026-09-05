"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { GuidedDemo } from "@/app/components/guided-demo";
import { STATUS_COLORS } from "@/app/components/ui";
import { getHealth, type Action } from "@/lib/api";

const fadeUp = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.52, 0.01, 0, 1] as const } },
};

const ghostPill =
  "rounded-full border border-white/60 px-8 py-4 text-sm font-medium text-white transition-colors hover:border-white";

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
  {
    href: "/razorpay-demo",
    title: "Razorpay Test Mode",
    description: "Pay through a real Razorpay Test Mode order - a verified webhook decides and, on BLOCK, refunds it.",
  },
];

type HealthState = "checking" | "connected" | "unreachable";

export default function Landing() {
  // Ticket 01d: the homepage calls the real /health endpoint and renders
  // the result - a live signal that the deployed backend can actually
  // reach its database, not just that the static frontend loaded.
  const [health, setHealth] = useState<HealthState>("checking");
  useEffect(() => {
    getHealth()
      .then((res) => setHealth(res.db === "connected" ? "connected" : "unreachable"))
      .catch(() => setHealth("unreachable"));
  }, []);

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
      <section className="mx-auto flex max-w-[1200px] flex-col gap-8 px-6 pt-16 pb-24">
        <motion.p
          initial="hidden"
          animate="show"
          variants={fadeUp}
          className="text-[11px] font-medium tracking-[0.05em] text-neon uppercase"
        >
          Cost-aware fraud decisioning · policy simulation
        </motion.p>
        <motion.h1
          initial="hidden"
          animate="show"
          variants={fadeUp}
          className="max-w-3xl text-[48px] leading-[1.1] font-medium sm:text-[64px]"
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
        <motion.div initial="hidden" animate="show" variants={fadeUp}>
          <GuidedDemo />
        </motion.div>

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
        <div className="rounded-[60px] bg-mint-frost px-8 py-12 text-obsidian sm:px-16">
          <p className="text-[11px] font-medium tracking-[0.05em] uppercase">The pipeline</p>
          <h2 className="mt-2 max-w-xl text-[32px] font-medium">One transaction, four accountable stages.</h2>
          <div className="mt-12 flex flex-col gap-3 sm:flex-row sm:items-stretch sm:gap-0">
            {MODULES.map((mod, i) => (
              <div key={mod.label} className="flex flex-1 items-center">
                <div className="flex flex-1 flex-col gap-2 rounded-[10px] bg-white p-6 shadow-[1px_0_9px_2px_rgba(0,0,0,0.04)]">
                  <span className={`h-2 w-8 rounded-full ${mod.color}`} />
                  <span className="text-base font-medium">{mod.label}</span>
                  <span className="text-sm text-slate-text">{mod.detail}</span>
                </div>
                {i < MODULES.length - 1 && <span className="hidden px-3 text-2xl text-fog-border sm:block">→</span>}
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
        <p className="text-[11px] font-medium tracking-[0.05em] text-neon uppercase">Go to</p>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {SCREENS.map((screen) => (
            <Link
              key={screen.href}
              href={screen.href}
              className="flex flex-col gap-2 rounded-[20px] border border-white/10 p-6 transition-colors hover:border-neon"
            >
              <span className="text-lg font-medium">{screen.title}</span>
              <span className="text-sm text-white/60">{screen.description}</span>
            </Link>
          ))}
        </div>
      </motion.section>

      <footer className="flex flex-col items-center gap-3 border-t border-white/10 px-6 py-8 text-center text-xs text-white/70">
        <p>
          Illustrative cost assumptions and synthetic/IEEE-CIS data only - no real Razorpay data, and offline replay
          is an estimate, not proof of causal production impact.
        </p>
        <span className="flex items-center gap-1.5 font-mono text-[11px] tracking-wide uppercase">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              health === "connected" ? "bg-emerald-400" : health === "unreachable" ? "bg-rose-400" : "bg-zinc-500"
            }`}
          />
          {health === "checking" && "Checking API…"}
          {health === "connected" && "API + database: connected"}
          {health === "unreachable" && "API unreachable"}
        </span>
      </footer>
    </div>
  );
}
