"""Cost-aware decision engine (ticket 05). Computes the expected cost of
ALLOW/STEP_UP/REVIEW/BLOCK for a transaction and picks the minimum-cost
action, per issue #1's Implementation Decisions:

    E[C_allow]   = p * fraud_loss
    E[C_block]   = (1 - p) * false_decline_cost
    E[C_review]  = review_cost + p * residual_fraud_after_review + (1 - p) * friction_delay_cost
    E[C_step_up] = friction_cost + p_after_stepup * fraud_loss + (1 - p) * abandonment_cost

All constants below are the spec's own stated illustrative defaults (fraud
loss ~1.1x amount, false-decline 0.15x-0.4x amount, review cost flat 80,
step-up friction flat 150) where the spec gives an exact number; where it
only gestures at a concept ("an abandonment-probability proxy") without a
number, a reasonable documented value is chosen here as the day-1 default -
none of this is real Razorpay economics, and all of it is meant to be
edited later via the Policy Lab (ticket 09), not hardcoded permanently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from .segments import AmountBand, MerchantCategory

Action = Literal["ALLOW", "STEP_UP", "REVIEW", "BLOCK"]
ACTIONS: tuple[Action, ...] = get_args(Action)

# Which fallback-chain tier a cost profile came from - a Literal (not a bare
# str) so a typo becomes a type error, same reasoning as db.DataSource /
# segments.MerchantCategory / segments.AmountBand.
CostProfileSource = Literal["merchant", "merchant_category", "global_default"]


@dataclass(frozen=True)
class CostProfile:
    fraud_loss_rate: float  # fraud_loss = amount * fraud_loss_rate
    false_decline_rate: float  # false_decline_cost = amount * false_decline_rate
    review_cost: float  # flat operational cost of a review
    review_catch_rate: float  # fraction of fraud a review actually catches
    review_friction_rate: float  # friction_delay_cost = amount * review_friction_rate
    step_up_friction_cost: float  # flat friction cost of a step-up challenge
    step_up_prevent_rate: float  # fraction of fraud a step-up challenge prevents
    step_up_abandonment_rate: float  # abandonment_cost = amount * step_up_abandonment_rate


# --- Day-1 default cost constants -------------------------------------------------

FRAUD_LOSS_RATE_BASE = 1.10  # spec: "fraud loss ~= 1.1x transaction amount"
FRAUD_LOSS_NEW_DEVICE_BONUS = 0.10  # not spec-specified; a new/unfingerprinted
# device plausibly means higher investigation/chargeback-dispute cost if fraud
# does occur - documented choice, not a fitted number.

FALSE_DECLINE_RATE_BASE = 0.15  # spec: "~=0.15x amount (low-value/high-trust)"
FALSE_DECLINE_NEW_CUSTOMER_BONUS = 0.15
# Amount-band bonus tuned so the two segments the spec explicitly anchors
# land exactly on its stated range: low+returning -> 0.15, high+new -> 0.40.
FALSE_DECLINE_AMOUNT_BAND_BONUS: dict[AmountBand, float] = {"low": 0.0, "medium": 0.05, "high": 0.10}

REVIEW_COST = 80.0  # spec: "review cost flat Rs.80/case"
REVIEW_CATCH_RATE = 0.85  # from the spec's own worked example in the grilling session
REVIEW_FRICTION_RATE = 0.012  # ~= the worked example's Rs.300-on-Rs.25,000 delay-friction cost

STEP_UP_FRICTION_COST = 150.0  # spec: "step-up friction flat Rs.150"
STEP_UP_PREVENT_RATE = 0.70  # from the spec's own worked example
STEP_UP_ABANDONMENT_RATE = 0.05  # not spec-specified; "an abandonment-probability
# proxy" per the spec's own wording - 5% is a documented illustrative choice.

# Versioning for the audit trail (ticket 07). There is no Policy Lab yet
# (ticket 09) to mint new policy/cost-matrix versions at runtime, so these
# are the fixed day-1 defaults - bumped by hand if this module's constants
# change, until the Policy Lab makes versioning dynamic. Kept as two
# separate constants (not one) because they're conceptually distinct even
# though they change together today: POLICY_VERSION identifies the decision
# policy (which actions exist, the tie-break rule, the fallback chain
# mechanism), COST_MATRIX_VERSION identifies just the cost constants above -
# the Policy Lab will let a candidate cost matrix change under a fixed
# policy, or vice versa.
POLICY_VERSION = "policy-v1.0"
COST_MATRIX_VERSION = "cost-matrix-v1.0"


def default_cost_profile(amount_band: AmountBand, is_returning_customer: bool, is_known_device: bool) -> CostProfile:
    false_decline_rate = (
        FALSE_DECLINE_RATE_BASE
        + (0.0 if is_returning_customer else FALSE_DECLINE_NEW_CUSTOMER_BONUS)
        + FALSE_DECLINE_AMOUNT_BAND_BONUS[amount_band]
    )
    fraud_loss_rate = FRAUD_LOSS_RATE_BASE + (0.0 if is_known_device else FRAUD_LOSS_NEW_DEVICE_BONUS)

    return CostProfile(
        fraud_loss_rate=fraud_loss_rate,
        false_decline_rate=false_decline_rate,
        review_cost=REVIEW_COST,
        review_catch_rate=REVIEW_CATCH_RATE,
        review_friction_rate=REVIEW_FRICTION_RATE,
        step_up_friction_cost=STEP_UP_FRICTION_COST,
        step_up_prevent_rate=STEP_UP_PREVENT_RATE,
        step_up_abandonment_rate=STEP_UP_ABANDONMENT_RATE,
    )


def resolve_cost_profile(
    *,
    merchant_id: str | None,
    merchant_category: MerchantCategory,
    amount_band: AmountBand,
    is_returning_customer: bool,
    is_known_device: bool,
    merchant_overrides: dict[str, CostProfile] | None = None,
    category_overrides: dict[str, CostProfile] | None = None,
) -> tuple[CostProfile, CostProfileSource]:
    """Fallback chain: merchant-specific -> merchant-category -> global
    default. `merchant_overrides`/`category_overrides` are empty by default -
    there is no policy registry yet (that's ticket 09's Policy Lab); this
    function's job today is the *mechanism*, exercised and tested with
    injected overrides, ready for ticket 09 to populate for real. Returns
    (profile, source) so callers/reason-codes can say which tier was used.
    """
    merchant_overrides = merchant_overrides or {}
    category_overrides = category_overrides or {}

    if merchant_id and merchant_id in merchant_overrides:
        return merchant_overrides[merchant_id], "merchant"
    if merchant_category in category_overrides:
        return category_overrides[merchant_category], "merchant_category"
    return default_cost_profile(amount_band, is_returning_customer, is_known_device), "global_default"


def compute_expected_costs(probability: float, amount: float, cost_profile: CostProfile) -> dict[Action, float]:
    """The four E[C_action] formulas. `probability` is the calibrated fraud
    probability, `amount` the transaction amount. Pure function - no I/O,
    no clamping/validation beyond what the caller already guarantees
    (0 <= probability <= 1), so p=0 and p=1 are legitimate, meaningful inputs
    (a certainly-legitimate or certainly-fraudulent transaction), not edge
    cases to special-case away.
    """
    fraud_loss = amount * cost_profile.fraud_loss_rate
    false_decline_cost = amount * cost_profile.false_decline_rate

    e_allow = probability * fraud_loss
    e_block = (1 - probability) * false_decline_cost

    residual_fraud_after_review = (1 - cost_profile.review_catch_rate) * fraud_loss
    friction_delay_cost = amount * cost_profile.review_friction_rate
    e_review = (
        cost_profile.review_cost
        + probability * residual_fraud_after_review
        + (1 - probability) * friction_delay_cost
    )

    probability_after_stepup = probability * (1 - cost_profile.step_up_prevent_rate)
    abandonment_cost = amount * cost_profile.step_up_abandonment_rate
    e_step_up = (
        cost_profile.step_up_friction_cost
        + probability_after_stepup * fraud_loss
        + (1 - probability) * abandonment_cost
    )

    return {"ALLOW": e_allow, "STEP_UP": e_step_up, "REVIEW": e_review, "BLOCK": e_block}


def choose_action(expected_costs: dict[Action, float]) -> Action:
    """The minimum-expected-cost action. Ties broken by ACTIONS order
    (ALLOW < STEP_UP < REVIEW < BLOCK) - deterministic, not arbitrary dict
    iteration order, so the same inputs always produce the same decision."""
    return min(ACTIONS, key=lambda action: expected_costs[action])


def build_reason_codes(
    *,
    action: Action,
    expected_costs: dict[Action, float],
    probability: float,
    merchant_category: MerchantCategory,
    amount_band: AmountBand,
    is_returning_customer: bool,
    is_known_device: bool,
    cost_profile_source: CostProfileSource,
) -> list[str]:
    """Deterministic, template-based text - not an LLM explanation. Per the
    spec's own framing (story 10): explain a decision without overclaiming
    AI explainability."""
    ranked = sorted(ACTIONS, key=lambda a: expected_costs[a])
    runner_up = ranked[1]

    segment = (
        f"{merchant_category}/{amount_band}/"
        f"{'returning' if is_returning_customer else 'new'}_customer/"
        f"{'known' if is_known_device else 'new'}_device"
    )

    return [
        f"segment: {segment}",
        f"cost profile source: {cost_profile_source}",
        f"calibrated fraud probability: {probability:.4f}",
        f"{action} selected at expected cost Rs.{expected_costs[action]:.2f} "
        f"vs next-best {runner_up} at Rs.{expected_costs[runner_up]:.2f}",
    ]
