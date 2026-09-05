"use client";

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
 * style choice:
 *   spacing (px): 4 8 12 16 24 32 48 64 96 -> tailwind steps 1 2 3 4 6 8 12 16 24
 *   type (px):    11 (uppercase micro-label, the ONE label size app-wide)
 *                 14 (body copy, form values, button text)
 *                 18 (lead paragraph - landing only)
 *   radius:       0 on every dashboard surface (deliberate, flat ops
 *                 console); landing-only tiers: 10 (small elements),
 *                 20 (cards), 60 (large/hero cards), full (pill buttons)
 *
 * ACCESSIBILITY - text-zinc-500/600 measure 2.1-3.4:1 against this dark
 * palette, both below WCAG AA's 4.5:1 floor for normal text. Every text
 * color below is text-zinc-400 (6.3:1) or lighter for exactly this reason -
 * do not reach for 500/600 on real (non-decorative) text.
 *
 * COMPONENTS - Radix UI primitives (@radix-ui/react-*) back Select, Switch,
 * Tabs, Accordion, and the InfoTooltip below: real ARIA semantics and
 * keyboard nav that the earlier hand-rolled buttons/native <select>/
 * <details> didn't have, styled to match this file's flat aesthetic rather
 * than any default theme.
 */

import Link from "next/link";
import * as AccordionPrimitive from "@radix-ui/react-accordion";
import * as SelectPrimitive from "@radix-ui/react-select";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Check, ChevronDown, ChevronRight, Info } from "lucide-react";
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
      className={`flex flex-col gap-4 border border-zinc-800 border-t-zinc-700 bg-panel p-6 transition-opacity ${
        active ? "" : "pointer-events-none opacity-40"
      } ${className}`}
    >
      <h2 className="flex items-center gap-2 text-[11px] font-medium tracking-[0.14em] text-zinc-400 uppercase">
        {step !== undefined && (
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-zinc-600 text-[11px] leading-none font-normal normal-case text-zinc-300">
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
  return <p className="text-sm text-zinc-400">{children}</p>;
}

/** A small "i" glyph that reveals a plain-language explanation of a
 * technical term on hover/focus - for jargon (amount band, guardrail,
 * cost-matrix version) that's real and necessary but not self-explanatory
 * to someone who isn't a risk engineer. */
export function InfoTooltip({ children }: { children: React.ReactNode }) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>
        <button
          type="button"
          // 24x24 CSS px is WCAG 2.5.8 AA's touch-target floor - the 13px
          // glyph stays visually small, the hit area doesn't.
          className="inline-flex h-6 w-6 items-center justify-center text-zinc-400 hover:text-neon"
          aria-label="More information"
        >
          <Info size={13} />
        </button>
      </TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side="top"
          sideOffset={6}
          className="z-50 max-w-xs border border-zinc-700 bg-panel px-3 py-2 text-sm text-zinc-200 normal-case shadow-lg"
        >
          {children}
          <TooltipPrimitive.Arrow className="fill-zinc-700" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export function Field({
  label,
  children,
  hint,
  info,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
  info?: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-2 text-xs">
      <span className="flex items-center gap-1.5 tracking-wide text-zinc-400 uppercase">
        {label}
        {info && <InfoTooltip>{info}</InfoTooltip>}
      </span>
      {children}
      {hint && <span className="text-sm font-normal normal-case text-zinc-400">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "border border-zinc-800 bg-obsidian px-4 py-3 font-mono text-sm text-zinc-100 outline-none focus:border-neon";

/** A raw rupee-amount <input> with a ₹ prefix, so an editable amount field
 * (Console's manual "Amount (INR)", the Advanced detector's read-only
 * TransactionAmt) matches every *displayed* money value elsewhere in the
 * app - all of which go through formatCurrency - instead of reading as a
 * bare, unitless number next to them. */
export function CurrencyInput({
  value,
  onChange,
  readOnly = false,
  className = "",
}: {
  value: string | number;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  className?: string;
}) {
  return (
    <div className="relative">
      <span className="pointer-events-none absolute inset-y-0 left-4 flex items-center font-mono text-sm text-zinc-500">
        ₹
      </span>
      <input
        type="number"
        value={value}
        readOnly={readOnly}
        onChange={onChange ? (e) => onChange(e.target.value) : undefined}
        className={`border border-zinc-800 bg-obsidian py-3 pr-4 pl-8 font-mono text-sm text-zinc-100 outline-none focus:border-neon ${className}`}
      />
    </div>
  );
}

// Secondary/ghost action - most buttons on the dashboard (pick, cancel,
// toggle). Flat corners throughout: the dashboard stays a dense ops
// console, unlike the landing page's pill-shaped marketing buttons.
export const buttonClass =
  "border border-zinc-700 bg-zinc-900 px-4 py-3 text-sm font-medium tracking-wide text-zinc-200 uppercase transition-colors hover:border-neon hover:text-neon disabled:cursor-not-allowed disabled:opacity-40";

// Primary action - the one thing on a given screen you actually want the
// user to press (Score, Decide, Save, Simulate, Promote). Neon fill,
// rationed to exactly this role per the reference doc's "ration the
// accent" rule.
//
// Disabled state is a distinct muted color pair, not `opacity-40` on the
// neon fill - fading a light-bg/dark-text pair uniformly toward this dark
// page background makes both converge to the same near-black value, so the
// label reads as almost invisible instead of "temporarily unavailable".
export const primaryButtonClass =
  "border border-neon bg-neon px-4 py-3 text-sm font-semibold tracking-wide text-obsidian uppercase transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:border-zinc-700 disabled:bg-zinc-800 disabled:text-zinc-500 disabled:hover:opacity-100";

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

// --- Select (Radix) --------------------------------------------------------

export interface SelectOption {
  value: string;
  label: string;
}

/** Styled replacement for every native <select> on the dashboard - a
 * native select can't be restyled beyond trivial tweaks, which was a real
 * part of why form fields read as bland/unfinished. */
export function Select({
  value,
  onValueChange,
  options,
  className = "",
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  className?: string;
}) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger className={`${inputClass} flex items-center justify-between gap-2 ${className}`}>
        <SelectPrimitive.Value />
        <SelectPrimitive.Icon>
          <ChevronDown size={14} className="text-zinc-400" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className="z-50 overflow-hidden border border-zinc-700 bg-panel"
        >
          <SelectPrimitive.Viewport className="p-1">
            {options.map((opt) => (
              <SelectPrimitive.Item
                key={opt.value}
                value={opt.value}
                className="flex cursor-pointer items-center justify-between gap-3 px-3 py-2 font-mono text-sm text-zinc-200 outline-none data-[highlighted]:bg-zinc-800 data-[highlighted]:text-neon"
              >
                <SelectPrimitive.ItemText>{opt.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator>
                  <Check size={14} />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}

// --- Switch (Radix) ---------------------------------------------------------

export function Switch({
  checked,
  onCheckedChange,
  label,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <label className="flex items-center gap-3 text-sm text-zinc-200">
      <SwitchPrimitive.Root
        checked={checked}
        onCheckedChange={onCheckedChange}
        className="relative h-5 w-9 shrink-0 border border-zinc-700 bg-zinc-900 transition-colors data-[state=checked]:border-neon data-[state=checked]:bg-neon"
      >
        <SwitchPrimitive.Thumb className="block h-3.5 w-3.5 translate-x-0.5 bg-zinc-400 transition-transform data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-obsidian" />
      </SwitchPrimitive.Root>
      {label}
    </label>
  );
}

// --- Tabs (Radix) ------------------------------------------------------------

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({ children }: { children: React.ReactNode }) {
  return <TabsPrimitive.List className="flex gap-1 self-start border border-zinc-800">{children}</TabsPrimitive.List>;
}

export function TabsTrigger({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <TabsPrimitive.Trigger
      value={value}
      className="px-4 py-2 text-xs tracking-wide text-zinc-400 uppercase transition-colors hover:text-zinc-200 data-[state=active]:bg-zinc-800 data-[state=active]:text-zinc-100"
    >
      {children}
    </TabsPrimitive.Trigger>
  );
}

// --- Accordion (Radix) -------------------------------------------------------

export function Accordion({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <AccordionPrimitive.Root type="single" collapsible className={className}>
      {children}
    </AccordionPrimitive.Root>
  );
}

export function AccordionItem({
  value,
  title,
  children,
}: {
  value: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <AccordionPrimitive.Item value={value} className="border-t border-zinc-800 first:border-t-0">
      <AccordionPrimitive.Header>
        <AccordionPrimitive.Trigger className="group flex w-full items-center gap-2 px-6 py-4 text-left text-[11px] font-medium tracking-[0.14em] text-zinc-400 uppercase hover:text-zinc-100">
          <ChevronRight size={12} className="shrink-0 transition-transform group-data-[state=open]:rotate-90" />
          {title}
        </AccordionPrimitive.Trigger>
      </AccordionPrimitive.Header>
      <AccordionPrimitive.Content className="overflow-hidden data-[state=closed]:animate-[accordion-up_200ms_ease-out] data-[state=open]:animate-[accordion-down_200ms_ease-out]">
        <div className="flex flex-col gap-4 px-6 pb-6">{children}</div>
      </AccordionPrimitive.Content>
    </AccordionPrimitive.Item>
  );
}

// --- Preset picker (Policy Lab's Simple mode) --------------------------------

export function PresetCards<T extends string>({
  presets,
  value,
  onChange,
}: {
  presets: { key: T; label: string; description: string }[];
  value: T | null;
  onChange: (key: T) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {presets.map((preset) => (
        <button
          key={preset.key}
          onClick={() => onChange(preset.key)}
          className={`flex flex-col gap-1.5 border p-4 text-left transition-colors ${
            value === preset.key
              ? "border-neon bg-neon/10"
              : "border-zinc-800 bg-obsidian hover:border-zinc-600"
          }`}
        >
          <span className={`text-sm font-semibold ${value === preset.key ? "text-neon" : "text-zinc-100"}`}>
            {preset.label}
          </span>
          <span className="text-sm text-zinc-400">{preset.description}</span>
        </button>
      ))}
    </div>
  );
}

const ACTION_ORDER: Action[] = ["ALLOW", "STEP_UP", "REVIEW", "BLOCK"];

const STATUS_BAR_BG: Record<Action, string> = {
  ALLOW: "bg-emerald-500",
  STEP_UP: "bg-amber-500",
  REVIEW: "bg-sky-500",
  BLOCK: "bg-rose-500",
};

/** A merchant reads a bar faster than a 4-row number table - length does
 * the work a column of digits otherwise has to be read one at a time.
 * Used identically on the Live Decision Console and in Audit's decision
 * trace (dark surfaces) and the landing page's guided demo (a light
 * mint-frost card) - `dark` switches the label/value/track colors so it
 * reads correctly on either, since Tailwind's zinc-on-dark defaults are
 * invisible on a light background. */
export function CostBars({
  costs,
  chosen,
  dark = true,
}: {
  costs: Record<Action, number>;
  chosen: Action;
  dark?: boolean;
}) {
  const max = Math.max(...Object.values(costs)) || 1;
  const labelColor = dark ? "text-zinc-400" : "text-slate-text";
  const chosenLabelColor = dark ? "text-zinc-100" : "text-obsidian";
  const trackColor = dark ? "bg-zinc-900" : "bg-black/10";
  const valueColor = dark ? "text-zinc-300" : "text-obsidian";

  return (
    <div className="flex flex-col gap-2">
      {ACTION_ORDER.map((action) => (
        <div key={action} className="flex items-center gap-3">
          <span
            className={`w-16 shrink-0 font-mono text-xs ${
              action === chosen ? `font-semibold ${chosenLabelColor}` : labelColor
            }`}
          >
            {action}
            {action === chosen && " ←"}
          </span>
          <div className={`h-2 flex-1 ${trackColor}`}>
            <div
              className={`h-2 ${STATUS_BAR_BG[action]} ${action === chosen ? "" : "opacity-50"}`}
              style={{ width: `${(costs[action] / max) * 100}%` }}
            />
          </div>
          <span className={`w-20 shrink-0 text-right font-mono text-xs tabular-nums ${valueColor}`}>
            {formatCurrency(costs[action])}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Baseline-vs-candidate as paired bars instead of a table row - the
 * headline metrics on Policy Lab's replay result (fraud loss, GMV
 * blocked, fraud caught, net expected loss) are exactly the kind of
 * "did this get better or worse" comparison a bar communicates in one
 * glance; the full per-metric table stays available underneath for
 * whoever wants to verify the exact numbers. */
export function MetricComparison({
  label,
  baseline,
  candidate,
  currency = false,
  higherIsBetter = false,
}: {
  label: string;
  baseline: number;
  candidate: number;
  currency?: boolean;
  higherIsBetter?: boolean;
}) {
  const max = Math.max(baseline, candidate) || 1;
  const delta = candidate - baseline;
  const improved = higherIsBetter ? delta > 0 : delta < 0;
  const deltaColor = delta === 0 ? "text-zinc-400" : improved ? POSITIVE_TEXT : NEGATIVE_TEXT;
  const fmt = (value: number) => (currency ? formatCurrency(value) : value.toLocaleString("en-IN"));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-zinc-300">{label}</span>
        <span className={`font-mono text-xs tabular-nums ${deltaColor}`}>
          {delta === 0 ? "no change" : `${delta > 0 ? "+" : ""}${fmt(delta)}`}
        </span>
      </div>
      {([
        ["baseline", baseline, "bg-zinc-600", "text-zinc-400"],
        ["candidate", candidate, "bg-neon", "text-zinc-200"],
      ] as const).map(([rowLabel, value, barColor, valueColor]) => (
        <div key={rowLabel} className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-[11px] text-zinc-400">{rowLabel}</span>
          <div className="h-2 flex-1 bg-zinc-900">
            <div className={`h-2 ${barColor}`} style={{ width: `${(value / max) * 100}%` }} />
          </div>
          <span className={`w-20 shrink-0 text-right font-mono text-[11px] tabular-nums ${valueColor}`}>
            {fmt(value)}
          </span>
        </div>
      ))}
    </div>
  );
}

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
    return <span className="text-sm text-zinc-400">no data</span>;
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
        <div className="mt-2 flex justify-between font-mono text-sm text-zinc-400">
          <span>{dates[0]}</span>
          <span>{dates[dates.length - 1]}</span>
        </div>
      )}
    </div>
  );
}

// --- Journey (shared across Console/Policy Lab/Audit) ------------------------

export const JOURNEY = [
  { href: "/console", step: 1, label: "Decide", screen: "Live Decision Console" },
  { href: "/policy-lab", step: 2, label: "Govern", screen: "Policy Lab" },
  { href: "/audit", step: 3, label: "Review", screen: "Audit & Monitoring" },
] as const;

/** Sits at the bottom of a screen's task, carrying the visitor into the
 * next stage of the journey instead of leaving them to notice the nav bar
 * on their own - this is the "Next step" handoff the 3 screens were
 * missing between them. */
export function NextStepCTA({ afterHref, label }: { afterHref: string; label: string }) {
  return (
    <div className="flex flex-col items-start gap-3 border border-zinc-800 border-t-zinc-700 bg-panel px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-sm text-zinc-400">Next in the journey</span>
      <Link href={afterHref} className={`${primaryButtonClass} normal-case`}>
        {label} →
      </Link>
    </div>
  );
}
