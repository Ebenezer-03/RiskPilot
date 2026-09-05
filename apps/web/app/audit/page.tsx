"use client";

import { useEffect, useState } from "react";
import { History, SearchX } from "lucide-react";
import { NavHeader } from "@/app/components/nav-header";
import {
  CostBars,
  Field,
  NextStepCTA,
  Panel,
  STATUS_COLORS,
  Sparkline,
  formatCurrency,
  inputClass,
  primaryButtonClass,
} from "@/app/components/ui";
import { ApiError, getAuditTrace, getAuditTrends, type AuditTraceResponse, type AuditTrendsResponse } from "@/lib/api";

const RECENT_LOOKUPS_KEY = "riskpilot.audit.recent_lookups";
const MAX_RECENT_LOOKUPS = 8;

function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function loadRecentLookups(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENT_LOOKUPS_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    // Private browsing, cleared site data, etc. - a missing history list
    // isn't worth surfacing as an error, it just means the list is empty.
    return [];
  }
}

export default function AuditMonitoring() {
  // --- Trends ---
  const [trends, setTrends] = useState<AuditTrendsResponse | null>(null);
  const [trendsError, setTrendsError] = useState<string | null>(null);

  useEffect(() => {
    getAuditTrends(30)
      .then(setTrends)
      .catch((err) => setTrendsError(err instanceof ApiError ? err.message : "Failed to load trends."));
  }, []);

  // --- Trace lookup ---
  const [transactionId, setTransactionId] = useState("");
  const [trace, setTrace] = useState<AuditTraceResponse | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);
  // Lazy initializer, not an effect: this is per-viewer browser state, not
  // a value synchronized from React into an external system, so reading it
  // once at mount time is the right shape here. Guarded for SSR, where
  // `window` doesn't exist yet - the client render then reads it for real.
  const [recentLookups, setRecentLookups] = useState<string[]>(() =>
    typeof window === "undefined" ? [] : loadRecentLookups(),
  );

  async function handleLookup(id?: string) {
    const targetId = (id ?? transactionId).trim();
    if (!targetId) return;
    setTransactionId(targetId);
    setTraceLoading(true);
    setTraceError(null);
    setTrace(null);
    try {
      setTrace(await getAuditTrace(targetId));
      const updated = [targetId, ...recentLookups.filter((existing) => existing !== targetId)].slice(
        0,
        MAX_RECENT_LOOKUPS,
      );
      setRecentLookups(updated);
      try {
        window.localStorage.setItem(RECENT_LOOKUPS_KEY, JSON.stringify(updated));
      } catch {
        // Per-viewer convenience only - a failed write just means this
        // lookup won't be remembered next visit.
      }
    } catch (err) {
      setTraceError(err instanceof ApiError ? err.message : "Failed to look up that transaction.");
    } finally {
      setTraceLoading(false);
    }
  }

  const points = trends?.points ?? [];
  const dayLabels = points.map((p) => formatDay(p.day));
  const approvalRates = points.map((p) => p.approval_rate);
  const fraudLosses = points.map((p) => p.fraud_loss);
  const fpPoints = points.filter((p) => p.false_positive_rate !== null);
  const falsePositiveRates = fpPoints.map((p) => p.false_positive_rate as number);
  const falsePositiveDays = fpPoints.map((p) => formatDay(p.day));
  const totalDecisions = points.reduce((sum, p) => sum + p.total_decisions, 0);

  return (
    <div className="min-h-screen bg-obsidian font-sans text-zinc-100">
      <NavHeader endpoints="/audit/{id} · /audit/trends/daily" />

      <main className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
        <Panel title={`Trends · last ${trends?.window_days ?? 30} day(s) · GET /audit/trends/daily`}>
          {trendsError && <p className="text-sm text-rose-400">{trendsError}</p>}
          {!trends && !trendsError && <p className="text-sm text-zinc-400">Loading…</p>}
          {trends && points.length === 0 && (
            <p className="text-sm text-zinc-400">
              No decisions recorded in this window yet - run a few from the Live Decision Console first.
            </p>
          )}
          {points.length > 0 && (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
              <div className="flex flex-col gap-2">
                <span className="text-[11px] tracking-wide text-zinc-400 uppercase">
                  Approval rate · {(approvalRates[approvalRates.length - 1] * 100).toFixed(1)}%
                </span>
                <Sparkline values={approvalRates} dates={dayLabels} colorClassName="text-neon" />
              </div>
              <div className="flex flex-col gap-2">
                <span className="text-[11px] tracking-wide text-zinc-400 uppercase">
                  False-decline rate (labeled txns only)
                  {falsePositiveRates.length > 0 && ` · ${(falsePositiveRates[falsePositiveRates.length - 1] * 100).toFixed(1)}%`}
                </span>
                <Sparkline values={falsePositiveRates} dates={falsePositiveDays} colorClassName="text-amber-400" />
              </div>
              <div className="flex flex-col gap-2">
                <span className="text-[11px] tracking-wide text-zinc-400 uppercase">
                  Realized fraud loss (allowed + confirmed fraud)
                </span>
                <Sparkline values={fraudLosses} dates={dayLabels} colorClassName="text-rose-400" />
              </div>
            </div>
          )}
          {points.length > 0 && (
            <p className="text-sm text-zinc-400">
              {totalDecisions} decision(s) across {points.length} day(s) with activity. False-decline rate and
              fraud loss are only meaningful over labeled transactions (synthetic/IEEE-CIS) - live events with no
              ground truth are excluded rather than counted as legitimate.
            </p>
          )}
        </Panel>

        <Panel title="Decision trace lookup · GET /audit/{transaction_id}">
          <Field label="Transaction ID" hint="Paste one from the Live Decision Console's synthetic-transaction output.">
            {/* Stacks below ~400px so the button never has to squeeze -
                a primary CTA wrapping its own label mid-word looks broken. */}
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={transactionId}
                onChange={(e) => setTransactionId(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleLookup()}
                placeholder="txn_..."
                className={`${inputClass} flex-1`}
              />
              <button
                onClick={() => handleLookup()}
                disabled={traceLoading || !transactionId.trim()}
                className={primaryButtonClass}
              >
                {traceLoading ? "Looking up…" : "Look up"}
              </button>
            </div>
          </Field>
          {traceError && <p className="text-sm text-rose-400">{traceError}</p>}

          {recentLookups.length > 0 && !trace && (
            <div className="flex flex-col gap-2 border-t border-zinc-800 pt-4">
              <span className="flex items-center gap-1.5 text-[11px] tracking-wide text-zinc-400 uppercase">
                <History size={12} /> Recent lookups
              </span>
              <div className="flex flex-wrap gap-2">
                {recentLookups.map((id) => (
                  <button
                    key={id}
                    onClick={() => handleLookup(id)}
                    className="border border-zinc-800 px-3 py-1.5 font-mono text-xs text-zinc-300 hover:border-neon hover:text-neon"
                  >
                    {id}
                  </button>
                ))}
              </div>
            </div>
          )}

          {!trace && !traceLoading && !traceError && recentLookups.length === 0 && (
            <div className="flex flex-col items-center gap-2 border-t border-zinc-800 py-8 text-zinc-400">
              <SearchX size={20} />
              <p className="text-sm">No transaction looked up yet - paste an id above.</p>
            </div>
          )}

          {trace && (
            <div className="flex flex-col gap-4 border-t border-zinc-800 pt-4">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-xs sm:grid-cols-4">
                <dt className="text-zinc-400">data_source</dt>
                <dd className="text-zinc-200">{trace.transaction.data_source}</dd>
                <dt className="text-zinc-400">amount</dt>
                <dd className="text-zinc-200">{formatCurrency(trace.transaction.amount)}</dd>
                <dt className="text-zinc-400">merchant_category</dt>
                <dd className="text-zinc-200">{trace.transaction.merchant_category}</dd>
                <dt className="text-zinc-400">ground truth</dt>
                <dd
                  className={
                    trace.transaction.is_fraud === null
                      ? "text-zinc-400"
                      : trace.transaction.is_fraud
                        ? "text-rose-400"
                        : "text-emerald-400"
                  }
                >
                  {trace.transaction.is_fraud === null ? "unlabeled" : trace.transaction.is_fraud ? "fraud" : "legitimate"}
                </dd>
              </dl>

              <div className="flex flex-col gap-3">
                <span className="text-[11px] tracking-wide text-zinc-400 uppercase">
                  {trace.decisions.length} decision{trace.decisions.length === 1 ? "" : "s"} (chronological)
                </span>
                {trace.decisions.map((d) => (
                  <div key={d.id} className="flex flex-col gap-3 border border-zinc-800 p-4">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className={`border px-2 py-0.5 font-mono text-xs font-semibold tracking-wide ${STATUS_COLORS[d.action]}`}>
                        {d.action}
                      </span>
                      <span className="font-mono text-xs text-zinc-400">
                        {new Date(d.decided_at).toLocaleString()} · p={d.probability_used}
                      </span>
                    </div>
                    <CostBars costs={d.expected_costs} chosen={d.action} />
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-xs text-zinc-400 sm:grid-cols-3">
                      <span>model: {d.model_version ?? "—"}</span>
                      <span>calibration: {d.calibration_version ?? "—"}</span>
                      <span>segment_def: {d.segment_definition_version}</span>
                      <span>policy: {d.policy_version}</span>
                      <span>cost_matrix: {d.cost_matrix_version}</span>
                      <span>cost_profile: {d.cost_profile_source}</span>
                    </div>
                    <ul className="flex flex-col gap-1 font-mono text-xs text-zinc-400">
                      {d.reason_codes.map((code, i) => (
                        <li key={i}>· {code}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Panel>

        <NextStepCTA afterHref="/console" label="Decide: try another transaction" />
      </main>
    </div>
  );
}
