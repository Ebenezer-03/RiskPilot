"use client";

import { useEffect, useState } from "react";
import { NavHeader } from "@/app/components/nav-header";
import { Field, Panel, STATUS_COLORS, Sparkline, formatCurrency, inputClass, primaryButtonClass } from "@/app/components/ui";
import {
  ApiError,
  getAuditTrace,
  getAuditTrends,
  type Action,
  type AuditTraceResponse,
  type AuditTrendsResponse,
} from "@/lib/api";

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

  async function handleLookup() {
    if (!transactionId.trim()) return;
    setTraceLoading(true);
    setTraceError(null);
    setTrace(null);
    try {
      setTrace(await getAuditTrace(transactionId.trim()));
    } catch (err) {
      setTraceError(err instanceof ApiError ? err.message : "Failed to look up that transaction.");
    } finally {
      setTraceLoading(false);
    }
  }

  const points = trends?.points ?? [];
  const approvalRates = points.map((p) => p.approval_rate);
  const fraudLosses = points.map((p) => p.fraud_loss);
  const fpPoints = points.filter((p) => p.false_positive_rate !== null);
  const falsePositiveRates = fpPoints.map((p) => p.false_positive_rate as number);
  const totalDecisions = points.reduce((sum, p) => sum + p.total_decisions, 0);

  return (
    <div className="min-h-screen bg-obsidian font-sans text-zinc-100">
      <NavHeader endpoints="/audit/{id} · /audit/trends/daily" />

      <main className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
        <Panel title={`Trends · last ${trends?.window_days ?? 30} day(s) · GET /audit/trends/daily`}>
          {trendsError && <p className="text-xs text-rose-400">{trendsError}</p>}
          {!trends && !trendsError && <p className="text-xs text-zinc-500">Loading…</p>}
          {trends && points.length === 0 && (
            <p className="text-xs text-zinc-500">
              No decisions recorded in this window yet - run a few from the Live Decision Console first.
            </p>
          )}
          {points.length > 0 && (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
              <div className="flex flex-col gap-2">
                <span className="text-[11px] tracking-wide text-zinc-500 uppercase">
                  Approval rate · {(approvalRates[approvalRates.length - 1] * 100).toFixed(1)}%
                </span>
                <Sparkline values={approvalRates} colorClassName="text-neon" />
              </div>
              <div className="flex flex-col gap-2">
                <span className="text-[11px] tracking-wide text-zinc-500 uppercase">
                  False-decline rate (labeled txns only)
                  {falsePositiveRates.length > 0 && ` · ${(falsePositiveRates[falsePositiveRates.length - 1] * 100).toFixed(1)}%`}
                </span>
                <Sparkline values={falsePositiveRates} colorClassName="text-amber-400" />
              </div>
              <div className="flex flex-col gap-2">
                <span className="text-[11px] tracking-wide text-zinc-500 uppercase">
                  Realized fraud loss (allowed + confirmed fraud)
                </span>
                <Sparkline values={fraudLosses} colorClassName="text-rose-400" />
              </div>
            </div>
          )}
          {points.length > 0 && (
            <p className="text-[11px] text-zinc-600">
              {totalDecisions} decision(s) across {points.length} day(s) with activity. False-decline rate and
              fraud loss are only meaningful over labeled transactions (synthetic/IEEE-CIS) - live events with no
              ground truth are excluded rather than counted as legitimate.
            </p>
          )}
        </Panel>

        <Panel title="Decision trace lookup · GET /audit/{transaction_id}">
          <Field label="Transaction ID" hint="Paste one from the Live Decision Console's synthetic-transaction output.">
            <div className="flex gap-2">
              <input
                value={transactionId}
                onChange={(e) => setTransactionId(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleLookup()}
                placeholder="txn_..."
                className={`${inputClass} flex-1`}
              />
              <button onClick={handleLookup} disabled={traceLoading || !transactionId.trim()} className={primaryButtonClass}>
                {traceLoading ? "Looking up…" : "Look up"}
              </button>
            </div>
          </Field>
          {traceError && <p className="text-xs text-rose-400">{traceError}</p>}

          {trace && (
            <div className="flex flex-col gap-4 border-t border-zinc-800 pt-3">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 font-mono text-xs sm:grid-cols-4">
                <dt className="text-zinc-500">data_source</dt>
                <dd className="text-zinc-200">{trace.transaction.data_source}</dd>
                <dt className="text-zinc-500">amount</dt>
                <dd className="text-zinc-200">{formatCurrency(trace.transaction.amount)}</dd>
                <dt className="text-zinc-500">merchant_category</dt>
                <dd className="text-zinc-200">{trace.transaction.merchant_category}</dd>
                <dt className="text-zinc-500">ground truth</dt>
                <dd className={trace.transaction.is_fraud ? "text-rose-400" : "text-emerald-400"}>
                  {trace.transaction.is_fraud === null ? "unlabeled" : trace.transaction.is_fraud ? "fraud" : "legitimate"}
                </dd>
              </dl>

              <div className="flex flex-col gap-3">
                <span className="text-[11px] tracking-wide text-zinc-500 uppercase">
                  {trace.decisions.length} decision{trace.decisions.length === 1 ? "" : "s"} (chronological)
                </span>
                {trace.decisions.map((d) => (
                  <div key={d.id} className="flex flex-col gap-2 border border-zinc-800 p-3">
                    <div className="flex flex-wrap items-center gap-3">
                      <span className={`border px-2 py-0.5 font-mono text-xs font-semibold tracking-wide ${STATUS_COLORS[d.action]}`}>
                        {d.action}
                      </span>
                      <span className="font-mono text-[11px] text-zinc-500">
                        {new Date(d.decided_at).toLocaleString()} · p={d.probability_used}
                      </span>
                    </div>
                    <table className="w-full font-mono text-xs">
                      <tbody>
                        {(Object.keys(d.expected_costs) as Action[]).map((action) => (
                          <tr key={action} className="border-t border-zinc-900">
                            <td className={`py-1 pr-2 ${action === d.action ? "text-zinc-100" : "text-zinc-500"}`}>
                              {action}
                              {action === d.action && " ←"}
                            </td>
                            <td className="py-1 text-right text-zinc-200 tabular-nums">
                              {formatCurrency(d.expected_costs[action])}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11px] text-zinc-500 sm:grid-cols-3">
                      <span>model: {d.model_version ?? "—"}</span>
                      <span>calibration: {d.calibration_version ?? "—"}</span>
                      <span>segment_def: {d.segment_definition_version}</span>
                      <span>policy: {d.policy_version}</span>
                      <span>cost_matrix: {d.cost_matrix_version}</span>
                      <span>cost_profile: {d.cost_profile_source}</span>
                    </div>
                    <ul className="flex flex-col gap-1 font-mono text-[11px] text-zinc-400">
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
      </main>
    </div>
  );
}
