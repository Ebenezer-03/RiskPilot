"use client";

import { useState } from "react";
import {
  ApiError,
  decide,
  generateSyntheticTransactions,
  scoreTransaction,
  type Action,
  type DecideResponse,
  type MerchantCategory,
  type ScoreResponse,
  type TransactionRecord,
} from "@/lib/api";

const MERCHANT_CATEGORIES: MerchantCategory[] = [
  "electronics",
  "food_delivery",
  "digital_goods",
  "travel",
];

// The IEEE-CIS dataset's actual categorical domains for these columns (see
// apps/web/api/_app/ml/features.py) - a representative subset exposed here,
// not the full ~440-column schema, so /score stays a real model call
// without demanding a spreadsheet-sized form.
const PRODUCT_CODES = ["W", "C", "R", "H", "S"];
const CARD_NETWORKS = ["visa", "mastercard", "american express", "discover"];
const CARD_TYPES = ["debit", "credit"];
const DEVICE_TYPES = ["mobile", "desktop"];

const ACTION_STYLES: Record<Action, string> = {
  ALLOW: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
  STEP_UP: "border-amber-500/40 bg-amber-500/10 text-amber-400",
  REVIEW: "border-sky-500/40 bg-sky-500/10 text-sky-400",
  BLOCK: "border-rose-500/40 bg-rose-500/10 text-rose-400",
};

function formatCurrency(value: number): string {
  return `₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function Panel({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`flex flex-col gap-3 border border-zinc-800 bg-zinc-950 p-4 ${className}`}
    >
      <h2 className="text-[11px] font-medium tracking-[0.14em] text-zinc-500 uppercase">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="tracking-wide text-zinc-500 uppercase">{label}</span>
      {children}
    </label>
  );
}

const inputClass =
  "border border-zinc-800 bg-black px-2 py-1.5 font-mono text-sm text-zinc-100 outline-none focus:border-zinc-500";

const buttonClass =
  "border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium tracking-wide text-zinc-200 uppercase transition-colors hover:border-zinc-500 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40";

export default function LiveDecisionConsole() {
  const [mode, setMode] = useState<"synthetic" | "manual">("synthetic");

  // --- Transaction (synthetic or manual) ---
  const [synthetic, setSynthetic] = useState<TransactionRecord | null>(null);
  const [syntheticLoading, setSyntheticLoading] = useState(false);
  const [syntheticError, setSyntheticError] = useState<string | null>(null);

  const [merchantCategory, setMerchantCategory] = useState<MerchantCategory>("electronics");
  const [amount, setAmount] = useState("15000");
  const [isReturningCustomer, setIsReturningCustomer] = useState(true);
  const [isKnownDevice, setIsKnownDevice] = useState(true);

  // --- /score (real detector, IEEE-CIS-shaped features) ---
  const [productCD, setProductCD] = useState(PRODUCT_CODES[0]);
  const [card4, setCard4] = useState(CARD_NETWORKS[0]);
  const [card6, setCard6] = useState(CARD_TYPES[0]);
  const [deviceType, setDeviceType] = useState(DEVICE_TYPES[0]);
  const [emailDomain, setEmailDomain] = useState("gmail.com");
  const [scoreResult, setScoreResult] = useState<ScoreResponse | null>(null);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [scoreError, setScoreError] = useState<string | null>(null);

  // --- /decide ---
  const [probability, setProbability] = useState("0.5");
  const [decideResult, setDecideResult] = useState<DecideResponse | null>(null);
  const [decideLoading, setDecideLoading] = useState(false);
  const [decideError, setDecideError] = useState<string | null>(null);

  const activeAmount = mode === "synthetic" ? (synthetic?.amount ?? 0) : Number(amount);

  async function handleGenerateSynthetic() {
    setSyntheticLoading(true);
    setSyntheticError(null);
    setScoreResult(null);
    setDecideResult(null);
    setDecideError(null);
    try {
      const [created] = await generateSyntheticTransactions(1);
      setSynthetic(created);
      const generatedProbability = created.raw_features?.generation_fraud_probability;
      if (typeof generatedProbability === "number") {
        setProbability(generatedProbability.toFixed(4));
      }
    } catch (err) {
      setSyntheticError(err instanceof ApiError ? err.message : "Failed to generate transaction.");
    } finally {
      setSyntheticLoading(false);
    }
  }

  async function handleScore() {
    setScoreLoading(true);
    setScoreError(null);
    try {
      const result = await scoreTransaction({
        TransactionAmt: activeAmount,
        ProductCD: productCD,
        card4,
        card6,
        DeviceType: deviceType,
        P_emaildomain: emailDomain,
      });
      setScoreResult(result);
      setProbability(result.fraud_probability_calibrated.toFixed(4));
      // The probability just changed underneath it - a decide error from
      // before this score is no longer about what's in the field now.
      setDecideResult(null);
      setDecideError(null);
    } catch (err) {
      setScoreError(err instanceof ApiError ? err.message : "Failed to score transaction.");
    } finally {
      setScoreLoading(false);
    }
  }

  async function handleDecide() {
    setDecideLoading(true);
    setDecideError(null);
    try {
      const result = await decide({
        transaction_id: mode === "synthetic" ? synthetic?.transaction_id : null,
        probability: Number(probability),
        merchant_category: mode === "manual" ? merchantCategory : undefined,
        amount: mode === "manual" ? Number(amount) : undefined,
        is_returning_customer: mode === "manual" ? isReturningCustomer : undefined,
        is_known_device: mode === "manual" ? isKnownDevice : undefined,
        model_version: scoreResult?.model_version ?? null,
        calibration_version: scoreResult?.calibration_version ?? null,
        feature_schema_version: scoreResult?.feature_schema_version ?? null,
      });
      setDecideResult(result);
    } catch (err) {
      setDecideError(err instanceof ApiError ? err.message : "Failed to reach the decision engine.");
    } finally {
      setDecideLoading(false);
    }
  }

  const canDecide =
    probability !== "" &&
    !Number.isNaN(Number(probability)) &&
    (mode === "synthetic" ? synthetic !== null : amount !== "" && !Number.isNaN(Number(amount)));

  return (
    <div className="min-h-screen bg-black font-sans text-zinc-100">
      <header className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
        <div className="flex items-baseline gap-3">
          <span className="text-sm font-semibold tracking-[0.2em] text-zinc-100 uppercase">
            RiskPilot
          </span>
          <span className="text-xs tracking-wide text-zinc-500">Live Decision Console</span>
        </div>
        <span className="font-mono text-[11px] text-zinc-600">/decide · /score</span>
      </header>

      <main className="mx-auto grid max-w-6xl grid-cols-1 gap-4 p-6 lg:grid-cols-2">
        {/* --- Transaction --- */}
        <Panel title="Transaction">
          <div className="flex gap-1 self-start border border-zinc-800">
            {(["synthetic", "manual"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-3 py-1 text-xs tracking-wide uppercase ${
                  mode === m ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {m}
              </button>
            ))}
          </div>

          {mode === "synthetic" ? (
            <div className="flex flex-col gap-3">
              <button onClick={handleGenerateSynthetic} disabled={syntheticLoading} className={buttonClass}>
                {syntheticLoading ? "Generating…" : "Generate synthetic transaction"}
              </button>
              {syntheticError && <p className="text-xs text-rose-400">{syntheticError}</p>}
              {synthetic && (
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-zinc-800 pt-3 font-mono text-xs">
                  <dt className="text-zinc-500">id</dt>
                  <dd className="truncate text-zinc-200">{synthetic.transaction_id}</dd>
                  <dt className="text-zinc-500">merchant_category</dt>
                  <dd className="text-zinc-200">{synthetic.merchant_category}</dd>
                  <dt className="text-zinc-500">amount</dt>
                  <dd className="text-zinc-200">{formatCurrency(synthetic.amount)}</dd>
                  <dt className="text-zinc-500">amount_band</dt>
                  <dd className="text-zinc-200">{synthetic.amount_band}</dd>
                  <dt className="text-zinc-500">returning_customer</dt>
                  <dd className="text-zinc-200">{String(synthetic.is_returning_customer)}</dd>
                  <dt className="text-zinc-500">known_device</dt>
                  <dd className="text-zinc-200">{String(synthetic.is_known_device)}</dd>
                  <dt className="text-zinc-500">ground truth (demo only)</dt>
                  <dd className={synthetic.is_fraud ? "text-rose-400" : "text-emerald-400"}>
                    {synthetic.is_fraud ? "fraud" : "legitimate"}
                  </dd>
                </dl>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <Field label="Merchant category">
                <select
                  value={merchantCategory}
                  onChange={(e) => setMerchantCategory(e.target.value as MerchantCategory)}
                  className={inputClass}
                >
                  {MERCHANT_CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Amount (INR)">
                <input
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className={inputClass}
                />
              </Field>
              <label className="flex items-center gap-2 text-xs text-zinc-300">
                <input
                  type="checkbox"
                  checked={isReturningCustomer}
                  onChange={(e) => setIsReturningCustomer(e.target.checked)}
                />
                Returning customer
              </label>
              <label className="flex items-center gap-2 text-xs text-zinc-300">
                <input
                  type="checkbox"
                  checked={isKnownDevice}
                  onChange={(e) => setIsKnownDevice(e.target.checked)}
                />
                Known device
              </label>
            </div>
          )}
        </Panel>

        {/* --- Decision --- */}
        <Panel title="Decision · POST /decide">
          <Field label="Fraud probability to decide on">
            <input
              type="number"
              step="0.0001"
              min={0}
              max={1}
              value={probability}
              onChange={(e) => setProbability(e.target.value)}
              className={inputClass}
            />
          </Field>
          <button onClick={handleDecide} disabled={decideLoading || !canDecide} className={buttonClass}>
            {decideLoading ? "Deciding…" : "Run decision engine"}
          </button>
          {decideError && <p className="text-xs text-rose-400">{decideError}</p>}

          {decideResult && (
            <div className="flex flex-col gap-3 border-t border-zinc-800 pt-3">
              <div className="flex items-center gap-3">
                <span
                  className={`border px-3 py-1 font-mono text-sm font-semibold tracking-wide ${ACTION_STYLES[decideResult.decision]}`}
                >
                  {decideResult.decision}
                </span>
                <span className="font-mono text-xs text-zinc-500">
                  {decideResult.merchant_category}/{decideResult.amount_band}/
                  {decideResult.is_returning_customer ? "returning" : "new"}_customer/
                  {decideResult.is_known_device ? "known" : "new"}_device
                </span>
              </div>

              <table className="w-full font-mono text-xs">
                <tbody>
                  {(Object.keys(decideResult.expected_costs) as Action[]).map((action) => (
                    <tr key={action} className="border-t border-zinc-900">
                      <td
                        className={`py-1 pr-2 ${action === decideResult.decision ? "text-zinc-100" : "text-zinc-500"}`}
                      >
                        {action}
                        {action === decideResult.decision && " ←"}
                      </td>
                      <td className="py-1 text-right text-zinc-200 tabular-nums">
                        {formatCurrency(decideResult.expected_costs[action])}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div className="text-xs text-zinc-500">
                cost profile source: <span className="text-zinc-300">{decideResult.cost_profile_source}</span>
              </div>

              <ul className="flex flex-col gap-1 font-mono text-[11px] text-zinc-400">
                {decideResult.reason_codes.map((code, i) => (
                  <li key={i}>· {code}</li>
                ))}
              </ul>
            </div>
          )}
        </Panel>

        {/* --- Score (optional real detector call) --- */}
        <Panel title="Model score (optional) · POST /score" className="lg:col-span-2">
          <p className="text-xs text-zinc-500">
            Scores a representative subset of the IEEE-CIS feature schema through the real
            calibrated LightGBM detector. Not used for a synthetic transaction&apos;s own decision
            (synthetic data has no ML-compatible features) - available for any transaction to
            demonstrate the detector independently, and its output feeds the probability above.
          </p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <Field label="TransactionAmt">
              <input readOnly value={activeAmount} className={`${inputClass} opacity-60`} />
            </Field>
            <Field label="ProductCD">
              <select value={productCD} onChange={(e) => setProductCD(e.target.value)} className={inputClass}>
                {PRODUCT_CODES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="card4">
              <select value={card4} onChange={(e) => setCard4(e.target.value)} className={inputClass}>
                {CARD_NETWORKS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="card6">
              <select value={card6} onChange={(e) => setCard6(e.target.value)} className={inputClass}>
                {CARD_TYPES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="DeviceType">
              <select value={deviceType} onChange={(e) => setDeviceType(e.target.value)} className={inputClass}>
                {DEVICE_TYPES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="P_emaildomain">
            <input
              value={emailDomain}
              onChange={(e) => setEmailDomain(e.target.value)}
              className={`${inputClass} w-48`}
            />
          </Field>
          <button onClick={handleScore} disabled={scoreLoading} className={`${buttonClass} self-start`}>
            {scoreLoading ? "Scoring…" : "Run detector"}
          </button>
          {scoreError && <p className="text-xs text-rose-400">{scoreError}</p>}

          {scoreResult && (
            <div className="grid grid-cols-1 gap-4 border-t border-zinc-800 pt-3 sm:grid-cols-2">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 font-mono text-xs">
                <dt className="text-zinc-500">raw probability</dt>
                <dd className="text-zinc-200">{scoreResult.fraud_probability_raw}</dd>
                <dt className="text-zinc-500">calibrated probability</dt>
                <dd className="text-zinc-100">{scoreResult.fraud_probability_calibrated}</dd>
                <dt className="text-zinc-500">model_version</dt>
                <dd className="text-zinc-200">{scoreResult.model_version}</dd>
                <dt className="text-zinc-500">calibration_version</dt>
                <dd className="text-zinc-200">{scoreResult.calibration_version}</dd>
              </dl>
              <ul className="flex flex-col gap-1 font-mono text-[11px] text-zinc-400">
                {scoreResult.reason_codes.length === 0 ? (
                  <li>· no material contributing features</li>
                ) : (
                  scoreResult.reason_codes.map((code, i) => <li key={i}>· {code}</li>)
                )}
              </ul>
            </div>
          )}
        </Panel>
      </main>
    </div>
  );
}
