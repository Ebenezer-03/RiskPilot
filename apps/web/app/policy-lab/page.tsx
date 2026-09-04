"use client";

import { useEffect, useState } from "react";
import { NavHeader } from "@/app/components/nav-header";
import { Field, Panel, StepHint, formatCurrency, inputClass, primaryButtonClass } from "@/app/components/ui";
import {
  ApiError,
  DEFAULT_COST_ASSUMPTIONS,
  DEFAULT_REVIEW_CAPACITY,
  createPolicy,
  listPolicies,
  promotePolicy,
  simulatePolicy,
  updatePolicy,
  type AmountBand,
  type PolicyPromotionResult,
  type PolicyRecord,
  type SegmentReplayMetrics,
} from "@/lib/api";

type AssumptionField =
  | "fraud_loss_rate_base"
  | "fraud_loss_new_device_bonus"
  | "false_decline_rate_base"
  | "false_decline_new_customer_bonus"
  | "review_cost"
  | "review_catch_rate"
  | "review_friction_rate"
  | "step_up_friction_cost"
  | "step_up_prevent_rate"
  | "step_up_abandonment_rate";

const ASSUMPTION_FIELDS: { key: AssumptionField; label: string }[] = [
  { key: "fraud_loss_rate_base", label: "Fraud loss rate (× amount)" },
  { key: "fraud_loss_new_device_bonus", label: "+ new-device bonus" },
  { key: "false_decline_rate_base", label: "False-decline rate (× amount)" },
  { key: "false_decline_new_customer_bonus", label: "+ new-customer bonus" },
  { key: "review_cost", label: "Review cost (flat ₹)" },
  { key: "review_catch_rate", label: "Review catch rate" },
  { key: "review_friction_rate", label: "Review friction rate (× amount)" },
  { key: "step_up_friction_cost", label: "Step-up friction cost (flat ₹)" },
  { key: "step_up_prevent_rate", label: "Step-up prevent rate" },
  { key: "step_up_abandonment_rate", label: "Step-up abandonment rate (× amount)" },
];

const AMOUNT_BANDS: AmountBand[] = ["low", "medium", "high"];

function newPolicyId(): string {
  return `policy-${new Date().toISOString().replace(/[:.]/g, "-")}`;
}

const METRIC_ROWS: { key: keyof SegmentReplayMetrics; label: string; currency?: boolean }[] = [
  { key: "transaction_count", label: "Transactions" },
  { key: "fraud_count", label: "Fraud (ground truth)" },
  { key: "allow_count", label: "Allowed" },
  { key: "fraud_loss", label: "Fraud loss", currency: true },
  { key: "legitimate_gmv_blocked", label: "Legitimate GMV blocked", currency: true },
  { key: "legitimate_blocked_count", label: "Legitimate txns blocked" },
  { key: "transactions_caught", label: "Fraud caught" },
  { key: "review_count", label: "Routed to review (post-cap)" },
  { key: "review_eligible_count", label: "Review-eligible (pre-cap)" },
  { key: "net_expected_loss", label: "Net expected loss", currency: true },
];

function formatMetric(value: number, currency?: boolean): string {
  return currency ? formatCurrency(value) : value.toLocaleString("en-IN");
}

function formatDelta(value: number, currency?: boolean): string {
  const formatted = formatMetric(Math.abs(value), currency);
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `-${formatted}`;
  return formatted;
}

export default function PolicyLab() {
  const [policies, setPolicies] = useState<PolicyRecord[]>([]);
  const [policiesError, setPoliciesError] = useState<string | null>(null);
  const [baselinePolicyId, setBaselinePolicyId] = useState<string>("");

  const [policyId, setPolicyId] = useState(newPolicyId());
  const [name, setName] = useState("Candidate policy");
  const [reviewCapacity, setReviewCapacity] = useState(String(DEFAULT_REVIEW_CAPACITY));
  const [assumptions, setAssumptions] = useState<Record<AssumptionField, string>>({
    fraud_loss_rate_base: String(DEFAULT_COST_ASSUMPTIONS.fraud_loss_rate_base),
    fraud_loss_new_device_bonus: String(DEFAULT_COST_ASSUMPTIONS.fraud_loss_new_device_bonus),
    false_decline_rate_base: String(DEFAULT_COST_ASSUMPTIONS.false_decline_rate_base),
    false_decline_new_customer_bonus: String(DEFAULT_COST_ASSUMPTIONS.false_decline_new_customer_bonus),
    review_cost: String(DEFAULT_COST_ASSUMPTIONS.review_cost),
    review_catch_rate: String(DEFAULT_COST_ASSUMPTIONS.review_catch_rate),
    review_friction_rate: String(DEFAULT_COST_ASSUMPTIONS.review_friction_rate),
    step_up_friction_cost: String(DEFAULT_COST_ASSUMPTIONS.step_up_friction_cost),
    step_up_prevent_rate: String(DEFAULT_COST_ASSUMPTIONS.step_up_prevent_rate),
    step_up_abandonment_rate: String(DEFAULT_COST_ASSUMPTIONS.step_up_abandonment_rate),
  });
  const [amountBandBonus, setAmountBandBonus] = useState<Record<AmountBand, string>>({
    low: String(DEFAULT_COST_ASSUMPTIONS.false_decline_amount_band_bonus.low),
    medium: String(DEFAULT_COST_ASSUMPTIONS.false_decline_amount_band_bonus.medium),
    high: String(DEFAULT_COST_ASSUMPTIONS.false_decline_amount_band_bonus.high),
  });

  const [policy, setPolicy] = useState<PolicyRecord | null>(null);
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [windowDataSource, setWindowDataSource] = useState<"" | "synthetic" | "ieee_cis">("synthetic");
  const [windowLimit, setWindowLimit] = useState("500");
  const [simulateLoading, setSimulateLoading] = useState(false);
  const [simulateError, setSimulateError] = useState<string | null>(null);

  const [promotion, setPromotion] = useState<PolicyPromotionResult | null>(null);
  const [promoteLoading, setPromoteLoading] = useState(false);
  const [promoteError, setPromoteError] = useState<string | null>(null);

  useEffect(() => {
    listPolicies()
      .then(setPolicies)
      .catch((err) => setPoliciesError(err instanceof ApiError ? err.message : "Failed to load policies."));
  }, [policy?.status]); // refresh the baseline list whenever this candidate's status changes

  function assumptionsPayload() {
    return {
      ...Object.fromEntries(ASSUMPTION_FIELDS.map(({ key }) => [key, Number(assumptions[key])])),
      false_decline_amount_band_bonus: {
        low: Number(amountBandBonus.low),
        medium: Number(amountBandBonus.medium),
        high: Number(amountBandBonus.high),
      },
    };
  }

  async function handleSave() {
    setSaveLoading(true);
    setSaveError(null);
    try {
      const payload = { name, cost_assumptions: assumptionsPayload(), review_capacity: Number(reviewCapacity) };
      const saved = policy ? await updatePolicy(policyId, payload) : await createPolicy(policyId, payload);
      setPolicy(saved);
      setPromotion(null);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Failed to save candidate policy.");
    } finally {
      setSaveLoading(false);
    }
  }

  async function handleSimulate() {
    if (!policy) return;
    setSimulateLoading(true);
    setSimulateError(null);
    try {
      const updated = await simulatePolicy(policy.policy_id, {
        baselinePolicyId: baselinePolicyId || null,
        window: { data_source: windowDataSource || null, limit: Number(windowLimit) },
      });
      setPolicy(updated);
    } catch (err) {
      setSimulateError(err instanceof ApiError ? err.message : "Failed to run replay.");
    } finally {
      setSimulateLoading(false);
    }
  }

  async function handlePromote() {
    if (!policy) return;
    setPromoteLoading(true);
    setPromoteError(null);
    try {
      const result = await promotePolicy(policy.policy_id);
      setPromotion(result);
      setPolicy(result.policy);
    } catch (err) {
      setPromoteError(err instanceof ApiError ? err.message : "Failed to run the promotion check.");
    } finally {
      setPromoteLoading(false);
    }
  }

  function handlePolicyIdChange(newId: string) {
    setPolicyId(newId);
    if (policy && policy.status !== "DRAFT") {
      // policy_id is immutable server-side once saved, and this policy is
      // past DRAFT so it can't be edited further either - typing a new id
      // here starts a fresh candidate rather than trying to rename the
      // saved one. Clear everything tied to the old candidate so the rest
      // of the form (still showing its values, left as a starting point)
      // becomes editable again.
      setPolicy(null);
      setPromotion(null);
      setSaveError(null);
      setSimulateError(null);
      setPromoteError(null);
    }
  }

  const replay = policy?.replay_result ?? null;
  const canEdit = !policy || policy.status === "DRAFT";
  const canSimulate = policy?.status === "DRAFT";
  const canPromote = policy?.status === "SIMULATED";
  // Once saved, a DRAFT's id truly can't be renamed (the API has no such
  // operation) - but a SIMULATED/ACTIVE policy is terminal for this form,
  // so the id field re-enables specifically as the "start a new candidate"
  // affordance the warning below promises.
  const policyIdLocked = !!policy && policy.status === "DRAFT";

  return (
    <div className="min-h-screen bg-obsidian font-sans text-zinc-100">
      <NavHeader endpoints="/policies · /simulation/replay" />

      <main className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
        <Panel title="Candidate policy · cost profile, amount-band adjustments & review capacity" step={1}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Policy ID">
              <input
                value={policyId}
                onChange={(e) => handlePolicyIdChange(e.target.value)}
                disabled={policyIdLocked}
                className={`${inputClass} ${policyIdLocked ? "opacity-60" : ""}`}
              />
            </Field>
            <Field label="Name">
              <input value={name} onChange={(e) => setName(e.target.value)} disabled={!canEdit} className={inputClass} />
            </Field>
            <Field label="Daily review capacity">
              <input
                type="number"
                min={0}
                value={reviewCapacity}
                onChange={(e) => setReviewCapacity(e.target.value)}
                disabled={!canEdit}
                className={inputClass}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3 border-t border-zinc-800 pt-3 sm:grid-cols-5">
            {ASSUMPTION_FIELDS.map(({ key, label }) => (
              <Field key={key} label={label}>
                <input
                  type="number"
                  step="0.01"
                  value={assumptions[key]}
                  onChange={(e) => setAssumptions((prev) => ({ ...prev, [key]: e.target.value }))}
                  disabled={!canEdit}
                  className={inputClass}
                />
              </Field>
            ))}
          </div>

          <div className="flex flex-col gap-2 border-t border-zinc-800 pt-3">
            <span className="text-[11px] tracking-wide text-zinc-500 uppercase">
              False-decline amount-band adjustment (added to the base rate above)
            </span>
            <div className="grid grid-cols-3 gap-3 sm:w-1/2">
              {AMOUNT_BANDS.map((band) => (
                <Field key={band} label={band}>
                  <input
                    type="number"
                    step="0.01"
                    value={amountBandBonus[band]}
                    onChange={(e) => setAmountBandBonus((prev) => ({ ...prev, [band]: e.target.value }))}
                    disabled={!canEdit}
                    className={inputClass}
                  />
                </Field>
              ))}
            </div>
            <p className="text-[11px] text-zinc-600">
              The low/medium/high amount-band cutoffs themselves are a fixed, global day-1 default (not yet
              policy-editable) - this adjusts each band&apos;s false-decline cost multiplier, which is policy-editable.
            </p>
          </div>

          {!canEdit && (
            <p className="text-[11px] text-amber-400">
              This policy is {policy?.status} - no longer editable. Change the Policy ID above to start a new
              candidate.
            </p>
          )}
          <button onClick={handleSave} disabled={saveLoading || !canEdit} className={`${primaryButtonClass} self-start`}>
            {saveLoading ? "Saving…" : policy ? "Update candidate policy" : "Save as candidate policy"}
          </button>
          {saveError && <p className="text-xs text-rose-400">{saveError}</p>}
          {policy && (
            <p className="font-mono text-[11px] text-zinc-500">
              {policy.policy_id} · status: <span className="text-zinc-300">{policy.status}</span>
            </p>
          )}
        </Panel>

        <Panel title="Replay · POST /policies/{id}/simulate" step={2} active={!!policy}>
          {!policy && <StepHint>Save a candidate policy first (step 1).</StepHint>}
          {policiesError && <p className="text-xs text-rose-400">{policiesError}</p>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Baseline policy">
              <select
                value={baselinePolicyId}
                onChange={(e) => setBaselinePolicyId(e.target.value)}
                className={inputClass}
              >
                <option value="">auto (current ACTIVE policy, else day-1 default)</option>
                {policies
                  .filter((p) => p.policy_id !== policy?.policy_id)
                  .map((p) => (
                    <option key={p.policy_id} value={p.policy_id}>
                      {p.policy_id} ({p.status})
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Historical window: data source">
              <select
                value={windowDataSource}
                onChange={(e) => setWindowDataSource(e.target.value as typeof windowDataSource)}
                className={inputClass}
              >
                <option value="">any</option>
                <option value="synthetic">synthetic</option>
                <option value="ieee_cis">ieee_cis</option>
              </select>
            </Field>
            <Field label="Historical window: limit">
              <input
                type="number"
                min={1}
                max={5000}
                value={windowLimit}
                onChange={(e) => setWindowLimit(e.target.value)}
                className={inputClass}
              />
            </Field>
          </div>
          <button onClick={handleSimulate} disabled={simulateLoading || !canSimulate} className={`${primaryButtonClass} self-start`}>
            {simulateLoading ? "Replaying…" : "Run replay"}
          </button>
          {!canSimulate && policy && policy.status !== "DRAFT" && (
            <p className="text-[11px] text-zinc-600">Already {policy.status.toLowerCase()} - replay already ran.</p>
          )}
          {simulateError && <p className="text-xs text-rose-400">{simulateError}</p>}

          {replay && (
            <div className="flex flex-col gap-4 border-t border-zinc-800 pt-3">
              <p className="text-[11px] text-zinc-500 italic">{replay.disclaimer}</p>
              <p className="font-mono text-[11px] text-zinc-500">
                {replay.transactions_replayed} transactions replayed over {replay.window_days} day(s)
                {replay.transactions_skipped > 0 && `, ${replay.transactions_skipped} skipped (unscoreable)`} ·
                calibration Brier score: {replay.calibration_brier_score}
              </p>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] font-mono text-xs">
                  <thead>
                    <tr className="text-left text-zinc-500">
                      <th className="pb-2 font-normal">Metric</th>
                      <th className="pb-2 text-right font-normal">Baseline</th>
                      <th className="pb-2 text-right font-normal">Candidate</th>
                      <th className="pb-2 text-right font-normal">Delta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {METRIC_ROWS.map(({ key, label, currency }) => {
                      const delta = replay.aggregate.delta[key];
                      return (
                        <tr key={key} className="border-t border-zinc-900">
                          <td className="py-1 pr-2 text-zinc-400">{label}</td>
                          <td className="py-1 text-right text-zinc-200 tabular-nums">
                            {formatMetric(replay.aggregate.baseline[key], currency)}
                          </td>
                          <td className="py-1 text-right text-zinc-200 tabular-nums">
                            {formatMetric(replay.aggregate.candidate[key], currency)}
                          </td>
                          <td
                            className={`py-1 text-right tabular-nums ${
                              delta === 0 ? "text-zinc-600" : delta > 0 ? "text-amber-400" : "text-emerald-400"
                            }`}
                          >
                            {formatDelta(delta, currency)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <details className="text-xs">
                <summary className="cursor-pointer text-zinc-500 hover:text-zinc-300">
                  By segment ({Object.keys(replay.by_segment).length})
                </summary>
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full min-w-[640px] font-mono text-[11px]">
                    <thead>
                      <tr className="text-left text-zinc-500">
                        <th className="pb-2 font-normal">Segment</th>
                        <th className="pb-2 text-right font-normal">Txns (baseline)</th>
                        <th className="pb-2 text-right font-normal">Txns (candidate)</th>
                        <th className="pb-2 text-right font-normal">Net loss delta</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(replay.by_segment).map(([segment, comparison]) => (
                        <tr key={segment} className="border-t border-zinc-900">
                          <td className="py-1 pr-2 text-zinc-400">{segment}</td>
                          <td className="py-1 text-right text-zinc-200 tabular-nums">
                            {comparison.baseline.transaction_count}
                          </td>
                          <td className="py-1 text-right text-zinc-200 tabular-nums">
                            {comparison.candidate.transaction_count}
                          </td>
                          <td
                            className={`py-1 text-right tabular-nums ${
                              comparison.delta.net_expected_loss === 0
                                ? "text-zinc-600"
                                : comparison.delta.net_expected_loss > 0
                                  ? "text-amber-400"
                                  : "text-emerald-400"
                            }`}
                          >
                            {formatDelta(comparison.delta.net_expected_loss, true)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </div>
          )}
        </Panel>

        <Panel title="Promotion · POST /policies/{id}/promote" step={3} active={canPromote || promotion !== null}>
          {!canPromote && !promotion && (
            <StepHint>
              {policy?.status === "ACTIVE" ? "Already active." : "Run a replay first (step 2)."}
            </StepHint>
          )}
          <button onClick={handlePromote} disabled={promoteLoading || !canPromote} className={`${primaryButtonClass} self-start`}>
            {promoteLoading ? "Checking guardrails…" : "Promote to ACTIVE"}
          </button>
          {promoteError && <p className="text-xs text-rose-400">{promoteError}</p>}

          {promotion && promotion.approved && (
            <div className="border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-400">
              Approved - all five guardrails passed. Policy is now ACTIVE.
            </div>
          )}

          {promotion && !promotion.approved && (
            <div className="flex flex-col gap-2 border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              <p className="font-semibold text-rose-400">
                Rejected - {promotion.violations.length} guardrail{promotion.violations.length === 1 ? "" : "s"}{" "}
                violated. Policy stays SIMULATED.
              </p>
              <ul className="flex flex-col gap-1">
                {promotion.violations.map((v) => (
                  <li key={v.guardrail}>
                    <span className="font-mono font-semibold uppercase">{v.guardrail.replace(/_/g, " ")}</span>:{" "}
                    {v.detail}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Panel>
      </main>
    </div>
  );
}
