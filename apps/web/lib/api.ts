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

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(
      `API request failed (${status}): ${
        typeof detail === "string" ? detail : JSON.stringify(detail)
      }`,
    );
    this.status = status;
    this.detail = detail;
  }
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
