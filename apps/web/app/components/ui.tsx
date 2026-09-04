/**
 * Shared visual primitives for the dashboard's data-dense fintech-console
 * look (dark obsidian canvas, thin borders, no rounded bubbly chrome) -
 * used by the Live Decision Console, Policy Lab, and Audit & Monitoring
 * screens so all three read as one system, not separately-styled demos.
 * Palette adapted from the "Sauce Labs" reference: obsidian/deep-abyss
 * canvas + a single rationed neon accent, reused here as the dashboard's
 * primary-action color even though the dashboard itself stays flat/dense
 * rather than adopting the reference's pill-button marketing chrome -
 * that stays on the landing page only.
 */

import type { Action } from "@/lib/api";

export function formatCurrency(value: number): string {
  return `₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function Panel({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex flex-col gap-3 border border-zinc-800 bg-obsidian-deep p-4 ${className}`}>
      <h2 className="text-[11px] font-medium tracking-[0.14em] text-zinc-500 uppercase">{title}</h2>
      {children}
    </section>
  );
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="tracking-wide text-zinc-500 uppercase">{label}</span>
      {children}
      {hint && <span className="text-[11px] font-normal normal-case text-zinc-600">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "border border-zinc-800 bg-obsidian px-2 py-1.5 font-mono text-sm text-zinc-100 outline-none focus:border-neon";

// Secondary/ghost action - most buttons on the dashboard (pick, cancel,
// toggle). Flat corners throughout: the dashboard stays a dense ops
// console, unlike the landing page's pill-shaped marketing buttons.
export const buttonClass =
  "border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium tracking-wide text-zinc-200 uppercase transition-colors hover:border-neon hover:text-neon disabled:cursor-not-allowed disabled:opacity-40";

// Primary action - the one thing on a given screen you actually want the
// user to press (Score, Decide, Save, Simulate, Promote). Neon fill,
// rationed to exactly this role per the reference doc's "ration the
// accent" rule.
export const primaryButtonClass =
  "border border-neon bg-neon px-3 py-1.5 text-xs font-semibold tracking-wide text-obsidian uppercase transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";

// Semantic status colors, shared across every screen: action badges
// (Live Decision Console), replay deltas and guardrail violations
// (Policy Lab), and trend indicators (Audit & Monitoring). Kept as a
// 4-color quartet deliberately overriding the "single rationed accent"
// reference-doc rule - a risk console can't collapse ALLOW/STEP_UP/
// REVIEW/BLOCK into one color without becoming unreadable at a glance.
export const STATUS_COLORS: Record<Action, string> = {
  ALLOW: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  STEP_UP: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  REVIEW: "border-sky-500/40 bg-sky-500/10 text-sky-400",
  BLOCK: "border-rose-500/40 bg-rose-500/10 text-rose-400",
};

export const POSITIVE_TEXT = "text-emerald-400";
export const NEGATIVE_TEXT = "text-rose-400";
export const WARNING_TEXT = "text-amber-400";

// Minimal hand-rolled trend line - no charting library. A dashboard this
// data-dense doesn't need axes/tooltips/legends for a single-series daily
// trend; a bare shape reads faster here than a full chart component would.
export function Sparkline({
  values,
  colorClassName = "text-neon",
  width = 240,
  height = 40,
}: {
  values: number[];
  colorClassName?: string;
  width?: number;
  height?: number;
}) {
  if (values.length === 0) {
    return <span className="text-[11px] text-zinc-600">no data</span>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const points = values
    .map((v, i) => `${i * step},${height - ((v - min) / range) * height}`)
    .join(" ");

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={colorClassName}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.5} />
    </svg>
  );
}
