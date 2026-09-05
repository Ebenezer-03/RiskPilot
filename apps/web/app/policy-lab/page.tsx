"use client";

import { useEffect, useState } from "react";
import { NavHeader } from "@/app/components/nav-header";
import {
  Accordion,
  AccordionItem,
  Field,
  MetricComparison,
  NextStepCTA,
  Panel,
  PresetCards,
  Select,
  StepHint,
  Switch,
  formatCurrency,
  inputClass,
  primaryButtonClass,
} from "@/app/components/ui";
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

// Simple mode's 3 presets - each only overrides the two headline knobs
// (fraud loss rate, false-decline rate); everything else stays at the
// day-1 default. "Balanced" *is* the day-1 default, so it needs no
// override at all - a merchant who never opens Advanced still gets a
// real, considered cost profile, not a placeholder.
type PresetKey = "conservative" | "balanced" | "aggressive";

const PRESETS: {
  key: PresetKey;
  label: string;
  description: string;
  fraud_loss_rate_base: number;
  false_decline_rate_base: number;
}[] = [
  {
    key: "conservative",
    label: "Conservative",
    description: "Treats a missed fraud as costlier than a wrongly-blocked sale - blocks/reviews more.",
    fraud_loss_rate_base: 1.5,
    false_decline_rate_base: 0.1,
  },
  {
    key: "balanced",
    label: "Balanced",
    description: "The day-1 default cost profile - a reasonable starting point for most merchants.",
    fraud_loss_rate_base: DEFAULT_COST_ASSUMPTIONS.fraud_loss_rate_base,
    false_decline_rate_base: DEFAULT_COST_ASSUMPTIONS.false_decline_rate_base,
  },
  {
    key: "aggressive",
    label: "Aggressive",
    description: "Treats a wrongly-blocked sale as costlier than a missed fraud - approves more.",
    fraud_loss_rate_base: 0.8,
    false_decline_rate_base: 0.25,
  },
];

function newPolicyId(): string {
  return `policy-${new Date().toISOString().replace(/[:.]/g, "-")}`;
}

// `higherIsBetter` mirrors MetricComparison's flag above - omit it for rows
// where a delta's direction has no inherent good/bad reading (raw counts,
// ground-truth facts, operational volume), so the table doesn't imply a
// verdict it can't back up. Only set it where "up" or "down" is
// unambiguously the win: catching more fraud is good, losing more money or
// blocking more legitimate customers is bad.
const METRIC_ROWS: {
  key: keyof SegmentReplayMetrics;
  label: string;
  currency?: boolean;
  higherIsBetter?: boolean;
}[] = [
  { key: "transaction_count", label: "Transactions" },
  { key: "fraud_count", label: "Fraud (ground truth)" },
  { key: "allow_count", label: "Allowed" },
  { key: "fraud_loss", label: "Fraud loss", currency: true, higherIsBetter: false },
  { key: "legitimate_gmv_blocked", label: "Legitimate GMV blocked", currency: true, higherIsBetter: false },
  { key: "legitimate_blocked_count", label: "Legitimate txns blocked", higherIsBetter: false },
  { key: "transactions_caught", label: "Fraud caught", higherIsBetter: true },
  { key: "review_count", label: "Routed to review (post-cap)" },
  { key: "review_eligible_count", label: "Review-eligible (pre-cap)" },
  { key: "net_expected_loss", label: "Net expected loss", currency: true, higherIsBetter: false },
];

/** Shared by the full comparison table and the by-segment table below - a
 * delta only reads as "good" (emerald) or "bad" (amber) when the metric has
 * a declared direction; otherwise it stays neutral so an up/down move in a
 * fact like "fraud (ground truth)" doesn't read as a verdict. */
function deltaColor(delta: number, higherIsBetter?: boolean): string {
  if (delta === 0 || higherIsBetter === undefined) return "text-zinc-400";
  const improved = higherIsBetter ? delta > 0 : delta < 0;
  return improved ? "text-emerald-400" : "text-amber-400";
}

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

  // Empty on first render (server and client both render "") - newPolicyId()
  // embeds a timestamp, so calling it during useState's initializer runs it
  // once during SSR and again during client hydration a few ms apart,
  // producing two different ids and a React hydration mismatch. Filling it
  // in from an effect (client-only, post-hydration) avoids that.
  const [policyId, setPolicyId] = useState("");
  useEffect(() => {
    setPolicyId(newPolicyId());
  }, []);
  const [name, setName] = useState("Candidate policy");
  const [reviewCapacity, setReviewCapacity] = useState(String(DEFAULT_REVIEW_CAPACITY));
  const [advancedMode, setAdvancedMode] = useState(false);
  const [selectedPreset, setSelectedPreset] = useState<PresetKey | null>("balanced");
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

  function applyPreset(key: PresetKey) {
    const preset = PRESETS.find((p) => p.key === key);
    if (!preset) return;
    setSelectedPreset(key);
    setAssumptions((prev) => ({
      ...prev,
      fraud_loss_rate_base: String(preset.fraud_loss_rate_base),
      false_decline_rate_base: String(preset.false_decline_rate_base),
    }));
  }

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

  const baselineOptions = [
    { value: "", label: "auto (current ACTIVE policy, else day-1 default)" },
    ...policies
      .filter((p) => p.policy_id !== policy?.policy_id)
      .map((p) => ({ value: p.policy_id, label: `${p.policy_id} (${p.status})` })),
  ];
  const dataSourceOptions = [
    { value: "", label: "any" },
    { value: "synthetic", label: "synthetic" },
    { value: "ieee_cis", label: "ieee_cis" },
  ];

  return (
    <div className="min-h-screen bg-obsidian font-sans text-zinc-100">
      <NavHeader endpoints="/policies · /simulation/replay" />

      <main className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
        <Panel title="Candidate policy" step={1}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Policy ID">
              <input
                value={policyId}
                onChange={(e) => handlePolicyIdChange(e.target.value)}
                disabled={policyIdLocked}
                // The generated default (policy-<ISO timestamp>) is wider than
                // this field on anything narrower than a wide desktop -
                // truncate with an ellipsis instead of a silent hard clip,
                // and expose the full value as a native hover tooltip since
                // it's the one thing here a user might need to copy exactly.
                title={policyId}
                className={`${inputClass} truncate ${policyIdLocked ? "opacity-60" : ""}`}
              />
            </Field>
            <Field label="Name">
              <input value={name} onChange={(e) => setName(e.target.value)} disabled={!canEdit} className={inputClass} />
            </Field>
            <Field label="Daily review capacity" info="The hard cap on how many transactions your review team can look at per day.">
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

          <div className="border-t border-zinc-800 pt-4">
            <Switch checked={advancedMode} onCheckedChange={setAdvancedMode} label="Advanced: edit every cost number directly" />
          </div>

          {!advancedMode ? (
            <div className="flex flex-col gap-3">
              <span className="text-[11px] tracking-wide text-zinc-400 uppercase">
                How cautious should this policy be?
              </span>
              <PresetCards presets={PRESETS} value={selectedPreset} onChange={applyPreset} />
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                {ASSUMPTION_FIELDS.map(({ key, label }) => (
                  <Field key={key} label={label}>
                    <input
                      type="number"
                      step="0.01"
                      value={assumptions[key]}
                      onChange={(e) => {
                        setSelectedPreset(null);
                        setAssumptions((prev) => ({ ...prev, [key]: e.target.value }));
                      }}
                      disabled={!canEdit}
                      className={inputClass}
                    />
                  </Field>
                ))}
              </div>

              <div className="flex flex-col gap-3 border-t border-zinc-800 pt-4">
                <span className="text-[11px] tracking-wide text-zinc-400 uppercase">
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
                <p className="text-sm text-zinc-400">
                  The low/medium/high amount-band cutoffs themselves are a fixed, global day-1 default (not yet
                  policy-editable) - this adjusts each band&apos;s false-decline cost multiplier, which is
                  policy-editable.
                </p>
              </div>
            </>
          )}

          {!canEdit && (
            <p className="text-sm text-amber-400">
              This policy is {policy?.status} - no longer editable. Change the Policy ID above to start a new
              candidate.
            </p>
          )}
          <button onClick={handleSave} disabled={saveLoading || !canEdit} className={`${primaryButtonClass} self-start`}>
            {saveLoading ? "Saving…" : policy ? "Update candidate policy" : "Save as candidate policy"}
          </button>
          {saveError && <p className="text-sm text-rose-400">{saveError}</p>}
          {policy && (
            <p className="font-mono text-xs text-zinc-400">
              {policy.policy_id} · status: <span className="text-zinc-200">{policy.status}</span>
            </p>
          )}
        </Panel>

        <Panel title="Replay · POST /policies/{id}/simulate" step={2} active={!!policy}>
          {!policy && <StepHint>Save a candidate policy first (step 1).</StepHint>}
          {policiesError && <p className="text-sm text-rose-400">{policiesError}</p>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Baseline policy" info="What the candidate is compared against - the currently ACTIVE policy if you don't pick one.">
              <Select value={baselinePolicyId} onValueChange={setBaselinePolicyId} options={baselineOptions} />
            </Field>
            <Field label="Historical window: data source">
              <Select
                value={windowDataSource}
                onValueChange={(v) => setWindowDataSource(v as typeof windowDataSource)}
                options={dataSourceOptions}
              />
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
            <p className="text-sm text-zinc-400">Already {policy.status.toLowerCase()} - replay already ran.</p>
          )}
          {simulateError && <p className="text-sm text-rose-400">{simulateError}</p>}

          {replay && (
            <div className="flex flex-col gap-4 border-t border-zinc-800 pt-4">
              <p className="text-sm text-zinc-400 italic">{replay.disclaimer}</p>
              <p className="font-mono text-xs text-zinc-400">
                {replay.transactions_replayed} transactions replayed over {replay.window_days} day(s)
                {replay.transactions_skipped > 0 && `, ${replay.transactions_skipped} skipped (unscoreable)`} ·
                calibration Brier score: {replay.calibration_brier_score}
              </p>

              {/* Headline comparison - the 4 numbers a merchant actually
                  cares about, as baseline-vs-candidate bars. The full
                  per-metric table (10 rows) and the by-segment breakdown
                  stay available below for anyone verifying the exact
                  numbers, collapsed by default. */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <MetricComparison
                  label="Fraud loss"
                  baseline={replay.aggregate.baseline.fraud_loss}
                  candidate={replay.aggregate.candidate.fraud_loss}
                  currency
                />
                <MetricComparison
                  label="Legitimate GMV blocked"
                  baseline={replay.aggregate.baseline.legitimate_gmv_blocked}
                  candidate={replay.aggregate.candidate.legitimate_gmv_blocked}
                  currency
                />
                <MetricComparison
                  label="Fraud caught"
                  baseline={replay.aggregate.baseline.transactions_caught}
                  candidate={replay.aggregate.candidate.transactions_caught}
                  higherIsBetter
                />
                <MetricComparison
                  label="Net expected loss"
                  baseline={replay.aggregate.baseline.net_expected_loss}
                  candidate={replay.aggregate.candidate.net_expected_loss}
                  currency
                />
              </div>

              <Accordion>
                <AccordionItem value="full-table" title="Full comparison table">
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[520px] font-mono text-xs">
                      <thead>
                        <tr className="text-left text-zinc-400">
                          <th className="pb-2 font-normal">Metric</th>
                          <th className="pb-2 text-right font-normal">Baseline</th>
                          <th className="pb-2 text-right font-normal">Candidate</th>
                          <th className="pb-2 text-right font-normal">Delta</th>
                        </tr>
                      </thead>
                      <tbody>
                        {METRIC_ROWS.map(({ key, label, currency, higherIsBetter }) => {
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
                              <td className={`py-1 text-right tabular-nums ${deltaColor(delta, higherIsBetter)}`}>
                                {formatDelta(delta, currency)}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  <Accordion>
                    <AccordionItem value="by-segment" title={`By segment (${Object.keys(replay.by_segment).length})`}>
                      <div className="overflow-x-auto">
                        <table className="w-full min-w-[640px] font-mono text-xs">
                          <thead>
                            <tr className="text-left text-zinc-400">
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
                                  className={`py-1 text-right tabular-nums ${deltaColor(comparison.delta.net_expected_loss, false)}`}
                                >
                                  {formatDelta(comparison.delta.net_expected_loss, true)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </AccordionItem>
                  </Accordion>
                </AccordionItem>
              </Accordion>
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
          {promoteError && <p className="text-sm text-rose-400">{promoteError}</p>}

          {promotion && promotion.approved && (
            <div className="border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-400">
              Approved - all five guardrails passed. Policy is now ACTIVE.
            </div>
          )}

          {promotion && !promotion.approved && (
            <div className="flex flex-col gap-2 border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
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

        <NextStepCTA afterHref="/audit" label="Review: see this policy's decisions in the audit trail" />
      </main>
    </div>
  );
}
