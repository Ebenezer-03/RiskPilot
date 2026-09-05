"use client";

import { useState } from "react";
import { NavHeader } from "@/app/components/nav-header";
import {
  Accordion,
  AccordionItem,
  CostBars,
  CurrencyInput,
  Field,
  NextStepCTA,
  Panel,
  STATUS_COLORS,
  Select,
  StepHint,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  buttonClass,
  formatCurrency,
  inputClass,
  primaryButtonClass,
} from "@/app/components/ui";
import {
  ApiError,
  decide,
  generateSyntheticTransactions,
  scoreTransaction,
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
// without demanding a spreadsheet-sized form. Kept behind the "Advanced"
// disclosure below: these are raw ML dataset field names, not anything a
// merchant using this console would recognize.
const PRODUCT_CODES = ["W", "C", "R", "H", "S"];
const CARD_NETWORKS = ["visa", "mastercard", "american express", "discover"];
const CARD_TYPES = ["debit", "credit"];
const DEVICE_TYPES = ["mobile", "desktop"];

const asOptions = (values: string[]) => values.map((v) => ({ value: v, label: v }));

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

  // Step 2 unlocks once there's a transaction to decide on - independent
  // of whether the probability field is currently a *valid* number
  // (canDecide, below), so the panel dims/undims on the same condition a
  // first-time user would describe as "I have a transaction now."
  const hasTransaction =
    mode === "synthetic" ? synthetic !== null : amount !== "" && !Number.isNaN(Number(amount));
  const canDecide = hasTransaction && probability !== "" && !Number.isNaN(Number(probability));

  return (
    <div className="min-h-screen bg-obsidian font-sans text-zinc-100">
      <NavHeader endpoints="/decide · /score" />

      <main className="mx-auto flex max-w-6xl flex-col gap-4 p-6">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* --- Step 1: Transaction --- */}
          <Panel title="Transaction" step={1}>
            <Tabs value={mode} onValueChange={(v) => setMode(v as "synthetic" | "manual")}>
              <TabsList>
                <TabsTrigger value="synthetic">Synthetic</TabsTrigger>
                <TabsTrigger value="manual">Manual</TabsTrigger>
              </TabsList>

              <TabsContent value="synthetic" className="flex flex-col gap-4 pt-4">
                <button
                  onClick={handleGenerateSynthetic}
                  disabled={syntheticLoading}
                  className={`${primaryButtonClass} self-start`}
                >
                  {syntheticLoading ? "Generating…" : "Generate synthetic transaction"}
                </button>
                {syntheticError && <p className="text-sm text-rose-400">{syntheticError}</p>}
                {synthetic && (
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-zinc-800 pt-4 font-mono text-xs">
                    <dt className="text-zinc-400">id</dt>
                    <dd className="truncate text-zinc-200">{synthetic.transaction_id}</dd>
                    <dt className="text-zinc-400">merchant_category</dt>
                    <dd className="text-zinc-200">{synthetic.merchant_category}</dd>
                    <dt className="text-zinc-400">amount</dt>
                    <dd className="text-zinc-200">{formatCurrency(synthetic.amount)}</dd>
                    <dt className="text-zinc-400">amount_band</dt>
                    <dd className="text-zinc-200">{synthetic.amount_band}</dd>
                    <dt className="text-zinc-400">returning_customer</dt>
                    <dd className="text-zinc-200">{String(synthetic.is_returning_customer)}</dd>
                    <dt className="text-zinc-400">known_device</dt>
                    <dd className="text-zinc-200">{String(synthetic.is_known_device)}</dd>
                    <dt className="text-zinc-400">ground truth (demo only)</dt>
                    <dd
                      className={
                        synthetic.is_fraud === null
                          ? "text-zinc-400"
                          : synthetic.is_fraud
                            ? "text-rose-400"
                            : "text-emerald-400"
                      }
                    >
                      {synthetic.is_fraud === null ? "unlabeled" : synthetic.is_fraud ? "fraud" : "legitimate"}
                    </dd>
                  </dl>
                )}
              </TabsContent>

              <TabsContent value="manual" className="pt-4">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Merchant category">
                    <Select
                      value={merchantCategory}
                      onValueChange={(v) => setMerchantCategory(v as MerchantCategory)}
                      options={asOptions(MERCHANT_CATEGORIES)}
                    />
                  </Field>
                  <Field label="Amount (INR)">
                    <CurrencyInput value={amount} onChange={setAmount} />
                  </Field>
                  <Switch checked={isReturningCustomer} onCheckedChange={setIsReturningCustomer} label="Returning customer" />
                  <Switch checked={isKnownDevice} onCheckedChange={setIsKnownDevice} label="Known device" />
                </div>
              </TabsContent>
            </Tabs>
          </Panel>

          {/* --- Step 2: Decision --- */}
          <Panel title="Decision · POST /decide" step={2} active={hasTransaction}>
            {!hasTransaction && <StepHint>Generate or fill in a transaction first (step 1).</StepHint>}
            <Field
              label="Fraud probability to decide on"
              hint="Fill it from the detector under Advanced below, or type your own."
              info="How likely this transaction is fraud, on a scale from 0 (certainly legitimate) to 1 (certainly fraud)."
            >
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
            <button
              onClick={handleDecide}
              disabled={decideLoading || !canDecide}
              className={`${primaryButtonClass} self-start`}
            >
              {decideLoading ? "Deciding…" : "Run decision engine"}
            </button>
            {decideError && <p className="text-sm text-rose-400">{decideError}</p>}

            {decideResult && (
              <div className="flex flex-col gap-3 border-t border-zinc-800 pt-4">
                <div className="flex items-center gap-3">
                  <span
                    className={`border px-3 py-1 font-mono text-sm font-semibold tracking-wide ${STATUS_COLORS[decideResult.decision]}`}
                  >
                    {decideResult.decision}
                  </span>
                  <span className="font-mono text-xs text-zinc-400">
                    {decideResult.merchant_category}/{decideResult.amount_band}/
                    {decideResult.is_returning_customer ? "returning" : "new"}_customer/
                    {decideResult.is_known_device ? "known" : "new"}_device
                  </span>
                </div>

                <CostBars costs={decideResult.expected_costs} chosen={decideResult.decision} />

                <div className="text-sm text-zinc-400">
                  cost profile source: <span className="text-zinc-200">{decideResult.cost_profile_source}</span>
                </div>

                <ul className="flex flex-col gap-1 font-mono text-xs text-zinc-400">
                  {decideResult.reason_codes.map((code, i) => (
                    <li key={i}>· {code}</li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>
        </div>

        {/* --- Advanced: real detector, hidden by default (raw ML dataset
             fields aren't merchant-facing - this exists to prove the
             detector works, not for daily use) --- */}
        <Accordion className="border border-zinc-800 border-t-zinc-700 bg-panel">
          <AccordionItem value="advanced" title="Advanced: score against the real detector · POST /score">
            <p className="text-sm text-zinc-400">
              Scores a representative subset of the IEEE-CIS feature schema through the real
              calibrated LightGBM detector. Not used for a synthetic transaction&apos;s own decision
              (synthetic data has no ML-compatible features) - available for any transaction to
              demonstrate the detector independently, and its output feeds step 2&apos;s probability.
            </p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              <Field label="TransactionAmt">
                <CurrencyInput value={activeAmount} readOnly className="opacity-60" />
              </Field>
              <Field label="ProductCD">
                <Select value={productCD} onValueChange={setProductCD} options={asOptions(PRODUCT_CODES)} />
              </Field>
              <Field label="card4">
                <Select value={card4} onValueChange={setCard4} options={asOptions(CARD_NETWORKS)} />
              </Field>
              <Field label="card6">
                <Select value={card6} onValueChange={setCard6} options={asOptions(CARD_TYPES)} />
              </Field>
              <Field label="DeviceType">
                <Select value={deviceType} onValueChange={setDeviceType} options={asOptions(DEVICE_TYPES)} />
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
            {scoreError && <p className="text-sm text-rose-400">{scoreError}</p>}

            {scoreResult && (
              <div className="grid grid-cols-1 gap-4 border-t border-zinc-800 pt-4 sm:grid-cols-2">
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-xs">
                  <dt className="text-zinc-400">raw probability</dt>
                  <dd className="text-zinc-200">{scoreResult.fraud_probability_raw}</dd>
                  <dt className="text-zinc-400">calibrated probability</dt>
                  <dd className="text-zinc-100">{scoreResult.fraud_probability_calibrated}</dd>
                  <dt className="text-zinc-400">model_version</dt>
                  <dd className="text-zinc-200">{scoreResult.model_version}</dd>
                  <dt className="text-zinc-400">calibration_version</dt>
                  <dd className="text-zinc-200">{scoreResult.calibration_version}</dd>
                </dl>
                <ul className="flex flex-col gap-1 font-mono text-xs text-zinc-400">
                  {scoreResult.reason_codes.length === 0 ? (
                    <li>· no material contributing features</li>
                  ) : (
                    scoreResult.reason_codes.map((code, i) => <li key={i}>· {code}</li>)
                  )}
                </ul>
              </div>
            )}
          </AccordionItem>
        </Accordion>

        <NextStepCTA afterHref="/policy-lab" label="Govern: shape the policy behind this decision" />
      </main>
    </div>
  );
}
