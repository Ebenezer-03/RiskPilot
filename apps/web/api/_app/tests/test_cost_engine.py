"""Pure-function tests for the cost-aware decision engine (ticket 05) - the
spec's explicit second seam alongside the API layer, since routing every
numeric edge case through HTTP plumbing would add noise without confidence.
"""

import pytest

from _app.cost_engine import (
    CostProfile,
    build_reason_codes,
    choose_action,
    compute_expected_costs,
    default_cost_profile,
    resolve_cost_profile,
)

SIMPLE_PROFILE = CostProfile(
    fraud_loss_rate=1.0,
    false_decline_rate=0.5,
    review_cost=10.0,
    review_catch_rate=0.8,
    review_friction_rate=0.1,
    step_up_friction_cost=20.0,
    step_up_prevent_rate=0.6,
    step_up_abandonment_rate=0.05,
)
AMOUNT = 1000.0


def test_e_allow_and_e_block_at_p_equals_0():
    """p=0: a certainly-legitimate transaction. Allowing it costs nothing
    (no fraud can occur); blocking it costs the full false-decline cost
    (the false-decline definitely happens, since it wasn't fraud)."""
    costs = compute_expected_costs(0.0, AMOUNT, SIMPLE_PROFILE)
    assert costs["ALLOW"] == 0.0
    assert costs["BLOCK"] == pytest.approx(AMOUNT * SIMPLE_PROFILE.false_decline_rate)


def test_e_allow_and_e_block_at_p_equals_1():
    """p=1: a certainly-fraudulent transaction. Allowing it costs the full
    fraud loss; blocking it costs nothing (there's no legitimate customer
    to wrongly decline)."""
    costs = compute_expected_costs(1.0, AMOUNT, SIMPLE_PROFILE)
    assert costs["ALLOW"] == pytest.approx(AMOUNT * SIMPLE_PROFILE.fraud_loss_rate)
    assert costs["BLOCK"] == 0.0


def test_e_review_at_p_equals_0_is_just_operational_plus_friction():
    """p=0: no fraud to catch, so only the flat review cost and the
    friction/delay cost (which lands fully, since (1-p)=1) apply."""
    costs = compute_expected_costs(0.0, AMOUNT, SIMPLE_PROFILE)
    expected = SIMPLE_PROFILE.review_cost + AMOUNT * SIMPLE_PROFILE.review_friction_rate
    assert costs["REVIEW"] == pytest.approx(expected)


def test_e_review_at_p_equals_1_is_operational_plus_residual_fraud():
    """p=1: no legitimate customer to inconvenience, so only the flat
    review cost and the fraud that slips through the review's catch rate
    apply."""
    costs = compute_expected_costs(1.0, AMOUNT, SIMPLE_PROFILE)
    residual_fraud = (1 - SIMPLE_PROFILE.review_catch_rate) * AMOUNT * SIMPLE_PROFILE.fraud_loss_rate
    assert costs["REVIEW"] == pytest.approx(SIMPLE_PROFILE.review_cost + residual_fraud)


def test_e_step_up_at_p_equals_0_is_just_friction():
    costs = compute_expected_costs(0.0, AMOUNT, SIMPLE_PROFILE)
    expected = SIMPLE_PROFILE.step_up_friction_cost + AMOUNT * SIMPLE_PROFILE.step_up_abandonment_rate
    assert costs["STEP_UP"] == pytest.approx(expected)


def test_e_step_up_at_p_equals_1_is_friction_plus_residual_fraud():
    costs = compute_expected_costs(1.0, AMOUNT, SIMPLE_PROFILE)
    residual_prob = 1 - SIMPLE_PROFILE.step_up_prevent_rate
    expected = SIMPLE_PROFILE.step_up_friction_cost + residual_prob * AMOUNT * SIMPLE_PROFILE.fraud_loss_rate
    assert costs["STEP_UP"] == pytest.approx(expected)


def test_choose_action_picks_minimum_cost():
    costs = {"ALLOW": 50, "STEP_UP": 30, "REVIEW": 10, "BLOCK": 100}
    assert choose_action(costs) == "REVIEW"


def test_choose_action_tie_breaks_deterministically_by_action_order():
    # ALLOW comes before STEP_UP in ACTIONS - a tie should always resolve
    # the same way, not depend on dict iteration order.
    costs = {"ALLOW": 10, "STEP_UP": 10, "REVIEW": 10, "BLOCK": 10}
    assert choose_action(costs) == "ALLOW"


def test_default_cost_profile_matches_spec_anchor_points():
    """The spec states false-decline cost ranges ~0.15x amount (low-value/
    high-trust) to ~0.4x amount (high-value/new-customer) - the day-1
    default constants are tuned to land exactly on both stated anchors."""
    low_trusted = default_cost_profile("low", is_returning_customer=True, is_known_device=True)
    assert low_trusted.false_decline_rate == pytest.approx(0.15)

    high_new = default_cost_profile("high", is_returning_customer=False, is_known_device=True)
    assert high_new.false_decline_rate == pytest.approx(0.40)


def test_default_cost_profile_new_device_raises_fraud_loss_rate():
    known = default_cost_profile("medium", is_returning_customer=True, is_known_device=True)
    unknown = default_cost_profile("medium", is_returning_customer=True, is_known_device=False)
    assert unknown.fraud_loss_rate > known.fraud_loss_rate


def test_resolve_cost_profile_prefers_merchant_over_category_over_default():
    merchant_profile = SIMPLE_PROFILE
    category_profile = CostProfile(**{**SIMPLE_PROFILE.__dict__, "review_cost": 999.0})

    profile, source = resolve_cost_profile(
        merchant_id="m_1",
        merchant_category="electronics",
        amount_band="low",
        is_returning_customer=True,
        is_known_device=True,
        merchant_overrides={"m_1": merchant_profile},
        category_overrides={"electronics": category_profile},
    )
    assert source == "merchant"
    assert profile is merchant_profile


def test_resolve_cost_profile_falls_back_to_category_when_no_merchant_override():
    category_profile = SIMPLE_PROFILE

    profile, source = resolve_cost_profile(
        merchant_id="m_unknown",
        merchant_category="electronics",
        amount_band="low",
        is_returning_customer=True,
        is_known_device=True,
        merchant_overrides={},
        category_overrides={"electronics": category_profile},
    )
    assert source == "merchant_category"
    assert profile is category_profile


def test_resolve_cost_profile_falls_back_to_global_default_when_no_overrides():
    profile, source = resolve_cost_profile(
        merchant_id="m_unknown",
        merchant_category="electronics",
        amount_band="low",
        is_returning_customer=True,
        is_known_device=True,
    )
    assert source == "global_default"
    assert profile == default_cost_profile("low", True, True)


def test_build_reason_codes_includes_segment_probability_and_runner_up():
    costs = {"ALLOW": 50, "STEP_UP": 30, "REVIEW": 10, "BLOCK": 100}
    codes = build_reason_codes(
        action="REVIEW",
        expected_costs=costs,
        probability=0.42,
        merchant_category="electronics",
        amount_band="high",
        is_returning_customer=False,
        is_known_device=False,
        cost_profile_source="global_default",
    )
    joined = " | ".join(codes)
    assert "electronics/high/new_customer/new_device" in joined
    assert "global_default" in joined
    assert "0.4200" in joined
    assert "REVIEW" in joined and "STEP_UP" in joined  # chosen + runner-up
