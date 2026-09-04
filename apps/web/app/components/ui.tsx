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
 *
 * DISCIPLINE - every value below is drawn from exactly one of these fixed
 * scales; a component reaching for a value outside them is a bug, not a
 * style choice (this is what "not AI slop" cashes out to in code):
 *   spacing (px): 4 8 12 16 24 32 48 64  -> tailwind steps 1 2 3 4 6 8 12 16
 *   type (px):    11 (uppercase micro-label, the ONE label size app-wide)
 *                 12 (secondary/help text, button text)
 *                 14 (body copy, form values)
 *                 18 (lead paragraph - landing only)
 *   radius:       0 on every dashboard surface (deliberate, flat ops
 *                 console); landing-only tiers: 10 (small elements),
 *                 20 (cards), 60 (large/hero cards), full (pill buttons)
 */

import type { Action } from "@/lib/api";

export function formatCurrency(value: number): string {
  return `₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function Panel({
  title,
  step,
  active = true,
  children,
  className = "",
}: {
  title: string;
  /** When set, renders a numbered badge before the title and this panel
   * becomes one step in a sequential flow (see StepHint below). */
  step?: number;
  /** false dims the panel and blocks interaction - used to gate a later
   * step until its prerequisite is done, so a flow reads as a sequence
   * instead of N independent tools competing for attention at once. */
  active?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`flex flex-col gap-4 border border-zinc-800 border-t-zinc-700 bg-panel p-4 transition-opacity ${
        active ? "" : "pointer-events-none opacity-40"
      } ${className}`}
    >
      <h2 className="flex items-center gap-2 text-[11px] font-medium tracking-[0.14em] text-zinc-500 uppercase">
        {step !== undefined && (
          <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-zinc-700 text-[11px] leading-none font-normal normal-case text-zinc-400">
            {step}
          </span>
        )}
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Sits under a gated Panel's title to say what unlocks it - the visual
 * dimming alone doesn't explain itself. */
export function StepHint({ children }: { children: React.ReactNode }) {
  return <p className="text-xs text-zinc-600">{children}</p>;
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-2 text-xs">
      <span className="tracking-wide text-zinc-500 uppercase">{label}</span>
      {children}
      {hint && <span className="text-[11px] font-normal normal-case text-zinc-600">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "border border-zinc-800 bg-obsidian px-3 py-2 font-mono text-sm text-zinc-100 outline-none focus:border-neon";

// Secondary/ghost action - most buttons on the dashboard (pick, cancel,
// toggle). Flat corners throughout: the dashboard stays a dense ops
// console, unlike the landing page's pill-shaped marketing buttons.
export const buttonClass =
  "border border-zinc-700 bg-zinc-900 px-3 py-2 text-xs font-medium tracking-wide text-zinc-200 uppercase transition-colors hover:border-neon hover:text-neon disabled:cursor-not-allowed disabled:opacity-40";

// Primary action - the one thing on a given screen you actually want the
// user to press (Score, Decide, Save, Simulate, Promote). Neon fill,
// rationed to exactly this role per the reference doc's "ration the
// accent" rule.
export const primaryButtonClass =
  "border border-neon bg-neon px-3 py-2 text-xs font-semibold tracking-wide text-obsidian uppercase transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";

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
// data-dense doesn't need hover tooltips or a legend for a single-series
// daily trend, but a bare unlabeled line reads as an unfinished
// placeholder rather than real data - a baseline, a highlighted current
// value, and the date range it covers are the minimum to read as finished.
export function Sparkline({
  values,
  dates,
  colorClassName = "text-neon",
  width = 240,
  height = 40,
}: {
  values: number[];
  dates?: string[];
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
  const coords = values.map((v, i) => [i * step, height - ((v - min) / range) * height]);
  const points = coords.map(([x, y]) => `${x},${y}`).join(" ");
  const [lastX, lastY] = coords[coords.length - 1];

  return (
    <div className={colorClassName}>
      <svg width={width} height={height + 4} viewBox={`0 0 ${width} ${height + 4}`}>
        <line x1={0} y1={height} x2={width} y2={height} stroke="currentColor" strokeOpacity={0.15} strokeWidth={1} />
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.5} />
        <circle cx={lastX} cy={lastY} r={2.5} fill="currentColor" />
      </svg>
      {dates && dates.length > 1 && (
        <div className="mt-2 flex justify-between font-mono text-[11px] text-zinc-600">
          <span>{dates[0]}</span>
          <span>{dates[dates.length - 1]}</span>
        </div>
      )}
    </div>
  );
}
