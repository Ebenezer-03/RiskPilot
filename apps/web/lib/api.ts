/**
 * Typed client for the FastAPI backend (apps/web/api/_app). Every call
 * below hits the real deployed/local API - see next.config.ts's rewrite
 * (dev) and vercel.json (prod) for how /api/* reaches it. No mocked
 * responses anywhere in this module (ticket 10's explicit acceptance
 * criterion).
 */

export type MerchantCategory =
  | "electronics"
  | "food_delivery"
  | "digital_goods"
  | "travel";

export type AmountBand = "low" | "medium" | "high";

export type Action = "ALLOW" | "STEP_UP" | "REVIEW" | "BLOCK";

export type CostProfileSource = "merchant" | "merchant_category" | "global_default";

export type DataSource = "synthetic" | "ieee_cis" | "live_razorpay";

export interface TransactionRecord {
  transaction_id: string;
  data_source: DataSource;
  event_time: string;
  amount: number;
  currency: string;
  merchant_id: string | null;
  merchant_category: MerchantCategory;
  amount_band: AmountBand;
  is_returning_customer: boolean;
  is_known_device: boolean;
  is_fraud: boolean | null;
  raw_features: Record<string, unknown>;
  created_at: string;
}

export interface ScoreResponse {
  transaction_id: string | null;
  fraud_probability_raw: number;
  fraud_probability_calibrated: number;
  model_version: string;
  calibration_version: string;
  feature_schema_version: string;
  reason_codes: string[];
}

export interface DecideResponse {
  transaction_id: string | null;
  decision: Action;
  expected_costs: Record<Action, number>;
  probability_used: number;
  merchant_category: MerchantCategory;
  amount_band: AmountBand;
  is_returning_customer: boolean;
  is_known_device: boolean;
  cost_profile_source: CostProfileSource;
  reason_codes: string[];
}

/** FastAPI/Pydantic's validation-error shape for a 422 response: a list of
 * per-field problems, each naming the offending field's location and a
 * human-written message. */
interface ValidationErrorItem {
  loc?: unknown[];
  msg?: unknown;
}

function isValidationErrorItem(value: unknown): value is ValidationErrorItem {
  return typeof value === "object" && value !== null && "msg" in value;
}

/** Turns a FastAPI error `detail` into one line a user (not a developer)
 * can read - a plain string passes through, a 422 validation-error array
 * becomes "field: message" per problem, and anything else still falls back
 * to raw JSON rather than silently swallowing information. */
function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail.filter(isValidationErrorItem).map((item) => {
      const field = Array.isArray(item.loc)
        ? item.loc.filter((part) => part !== "body").join(".")
        : undefined;
      const msg = String(item.msg);
      return field ? `${field}: ${msg}` : msg;
    });
    if (messages.length > 0) {
      return messages.join("; ");
    }
  }
  return JSON.stringify(detail);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`API request failed (${status}): ${formatErrorDetail(detail)}`);
    this.status = status;
    this.detail = detail;
  }
}

export interface HealthResponse {
  status: string;
  db: "connected" | "not_configured" | "error";
}

/** Liveness + DB-connectivity check (ticket 01d) - the homepage renders
 * this so a visitor (or a judge) sees a real, live signal that the
 * deployed backend can actually reach its database, not just that the
 * static frontend loaded. */
export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = await res.text();
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export function generateSyntheticTransactions(count: number): Promise<TransactionRecord[]> {
  return request("/transactions/synthetic", {
    method: "POST",
    body: JSON.stringify({ count }),
  });
}

export function scoreTransaction(features: Record<string, string | number | null>): Promise<ScoreResponse> {
  return request("/score", {
    method: "POST",
    body: JSON.stringify({ features }),
  });
}

export interface DecideRequest {
  transaction_id?: string | null;
  probability: number;
  merchant_id?: string | null;
  merchant_category?: MerchantCategory;
  amount?: number;
  is_returning_customer?: boolean;
  is_known_device?: boolean;
  model_version?: string | null;
  calibration_version?: string | null;
  feature_schema_version?: string | null;
}

export function decide(payload: DecideRequest): Promise<DecideResponse> {
  return request("/decide", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --- Policy registry (ticket 09) --------------------------------------------------

export interface CostAssumptions {
  fraud_loss_rate_base: number;
  fraud_loss_new_device_bonus: number;
  false_decline_rate_base: number;
  false_decline_new_customer_bonus: number;
  false_decline_amount_band_bonus: Record<AmountBand, number>;
  review_cost: number;
  review_catch_rate: number;
  review_friction_rate: number;
  step_up_friction_cost: number;
  step_up_prevent_rate: number;
  step_up_abandonment_rate: number;
}

// The day-1 defaults from cost_engine.py / policy.py, mirrored here purely
// as sensible starting values for a new candidate policy's form - the
// backend applies its own defaults independently for any field omitted
// from a request.
export const DEFAULT_COST_ASSUMPTIONS: CostAssumptions = {
  fraud_loss_rate_base: 1.1,
  fraud_loss_new_device_bonus: 0.1,
  false_decline_rate_base: 0.15,
  false_decline_new_customer_bonus: 0.15,
  false_decline_amount_band_bonus: { low: 0.0, medium: 0.05, high: 0.1 },
  review_cost: 80,
  review_catch_rate: 0.85,
  review_friction_rate: 0.012,
  step_up_friction_cost: 150,
  step_up_prevent_rate: 0.7,
  step_up_abandonment_rate: 0.05,
};

export const DEFAULT_REVIEW_CAPACITY = 200;

export type PolicyStatus = "DRAFT" | "SIMULATED" | "APPROVED" | "CANARY" | "ACTIVE" | "ROLLED_BACK";

export interface SegmentReplayMetrics {
  transaction_count: number;
  fraud_count: number;
  allow_count: number;
  fraud_loss: number;
  legitimate_gmv_blocked: number;
  legitimate_blocked_count: number;
  transactions_caught: number;
  review_count: number;
  review_eligible_count: number;
  net_expected_loss: number;
}

export interface ReplayComparison {
  baseline: SegmentReplayMetrics;
  candidate: SegmentReplayMetrics;
  delta: SegmentReplayMetrics;
}

export interface ReplayResult {
  baseline_policy_id: string;
  candidate_policy_id: string;
  transactions_replayed: number;
  transactions_skipped: number;
  aggregate: ReplayComparison;
  by_segment: Record<string, ReplayComparison>;
  calibration_brier_score: number;
  window_days: number;
  disclaimer: string;
}

export interface PolicyRecord {
  policy_id: string;
  name: string;
  status: PolicyStatus;
  cost_assumptions: CostAssumptions;
  review_capacity: number;
  baseline_policy_id: string | null;
  // Untyped at the wire level (stored as JSONB) - shaped like ReplayResult
  // once a policy has been simulated at least once, per
  // routers/policies.py's `_replay_result_to_dict` (dataclasses.asdict).
  replay_result: ReplayResult | null;
  guardrail_violations: { guardrail: string; detail: string }[] | null;
  created_at: string;
  updated_at: string;
  simulated_at: string | null;
  activated_at: string | null;
  // Ticket 16 (stretch): CANARY's own 95/5-subsample replay (separate from
  // replay_result, the full-window replay from /simulate), and whichever
  // policy this one superseded on activation, for /rollback to revert to.
  canary_replay_result: ReplayResult | null;
  superseded_policy_id: string | null;
}

export interface PolicyWritePayload {
  name: string;
  cost_assumptions?: Partial<CostAssumptions>;
  review_capacity: number;
}

export function listPolicies(): Promise<PolicyRecord[]> {
  return request("/policies");
}

export function getPolicy(policyId: string): Promise<PolicyRecord> {
  return request(`/policies/${encodeURIComponent(policyId)}`);
}

export function createPolicy(policyId: string, payload: PolicyWritePayload): Promise<PolicyRecord> {
  return request("/policies", {
    method: "POST",
    body: JSON.stringify({ policy_id: policyId, ...payload }),
  });
}

export function updatePolicy(policyId: string, payload: PolicyWritePayload): Promise<PolicyRecord> {
  return request(`/policies/${encodeURIComponent(policyId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export interface ReplayWindow {
  data_source?: DataSource | null;
  limit?: number;
}

export function simulatePolicy(
  policyId: string,
  options: { baselinePolicyId?: string | null; window?: ReplayWindow } = {},
): Promise<PolicyRecord> {
  return request(`/policies/${encodeURIComponent(policyId)}/simulate`, {
    method: "POST",
    body: JSON.stringify({
      baseline_policy_id: options.baselinePolicyId ?? null,
      window: options.window ?? {},
    }),
  });
}

export interface GuardrailThresholds {
  max_approval_rate_drop?: number | null;
  min_segment_sample_size?: number | null;
  max_false_positive_rate_increase?: number | null;
  max_calibration_brier_score?: number | null;
}

export interface PolicyPromotionResult {
  policy: PolicyRecord;
  approved: boolean;
  violations: { guardrail: string; detail: string }[];
}

export function promotePolicy(
  policyId: string,
  thresholds: GuardrailThresholds = {},
): Promise<PolicyPromotionResult> {
  return request(`/policies/${encodeURIComponent(policyId)}/promote`, {
    method: "POST",
    body: JSON.stringify({ thresholds }),
  });
}

// Ticket 16 (stretch): SIMULATED -> CANARY, an optional staging step before
// /promote's SIMULATED|CANARY -> ACTIVE - a 95/5 historical-traffic
// subsample exposure, evaluated by the exact same guardrails as a direct
// promotion.
export function canaryPolicy(
  policyId: string,
  options: { window?: ReplayWindow; thresholds?: GuardrailThresholds } = {},
): Promise<PolicyPromotionResult> {
  return request(`/policies/${encodeURIComponent(policyId)}/canary`, {
    method: "POST",
    body: JSON.stringify({ window: options.window ?? {}, thresholds: options.thresholds ?? {} }),
  });
}

export interface PolicyRollbackResult {
  policy: PolicyRecord;
  // Whichever policy this one superseded on activation, reactivated as a
  // result - or null if this was the first-ever activated policy.
  reactivated_policy: PolicyRecord | null;
}

// Ticket 16 (stretch): ACTIVE/CANARY -> ROLLED_BACK, reverting the
// active-policy pointer to whichever policy this one superseded.
export function rollbackPolicy(policyId: string): Promise<PolicyRollbackResult> {
  return request(`/policies/${encodeURIComponent(policyId)}/rollback`, { method: "POST" });
}

// --- Audit & Monitoring (ticket 12) -----------------------------------------------

export interface DecisionRecord {
  id: number;
  transaction_id: string;
  decided_at: string;
  data_source: DataSource;
  probability_used: number;
  action: Action;
  expected_costs: Record<Action, number>;
  reason_codes: string[];
  merchant_category: MerchantCategory;
  amount_band: AmountBand;
  is_returning_customer: boolean;
  is_known_device: boolean;
  cost_profile_source: CostProfileSource;
  model_version: string | null;
  calibration_version: string | null;
  feature_schema_version: string | null;
  segment_definition_version: string;
  policy_version: string;
  cost_matrix_version: string;
}

export interface AuditTraceResponse {
  transaction: TransactionRecord;
  decisions: DecisionRecord[];
}

export function getAuditTrace(transactionId: string): Promise<AuditTraceResponse> {
  return request(`/audit/${encodeURIComponent(transactionId)}`);
}

// --- Razorpay Test Mode auto-responder (ticket 14) --------------------------

export interface RazorpayCheckoutRequest {
  merchant_category: MerchantCategory;
  amount: number;
  is_returning_customer: boolean;
  is_known_device: boolean;
}

export interface RazorpayCheckoutResponse {
  transaction_id: string;
  razorpay_order_id: string;
  razorpay_key_id: string;
  amount_paise: number;
  currency: string;
}

export function createRazorpayCheckout(payload: RazorpayCheckoutRequest): Promise<RazorpayCheckoutResponse> {
  return request<RazorpayCheckoutResponse>("/razorpay/checkout", { method: "POST", body: JSON.stringify(payload) });
}

export interface TrendPoint {
  day: string;
  total_decisions: number;
  approval_rate: number;
  false_positive_rate: number | null;
  fraud_loss: number;
}

export interface AuditTrendsResponse {
  window_days: number;
  points: TrendPoint[];
}

export function getAuditTrends(days = 30): Promise<AuditTrendsResponse> {
  return request(`/audit/trends/daily?days=${days}`);
}
