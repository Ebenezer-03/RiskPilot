"""Segment vocabulary shared across the transaction schema (ticket 04) and
the cost-aware decision engine (ticket 05, once built) - defined once here
so the two can't drift apart. See docs/agents/domain.md and issue #1's
Implementation Decisions for the day-1 default segments this encodes.

All thresholds are the spec's own stated illustrative defaults (INR), not
real Razorpay economics.
"""

from __future__ import annotations

from typing import Literal, get_args

# The Literal is the single source of truth (catches a typo as a type error,
# not just a runtime DB constraint violation); MERCHANT_CATEGORIES/
# AMOUNT_BANDS are derived from it for the places that need an iterable
# (validation, tests, random.choice(...)).
MerchantCategory = Literal["electronics", "food_delivery", "digital_goods", "travel"]
MERCHANT_CATEGORIES: list[str] = list(get_args(MerchantCategory))

AmountBand = Literal["low", "medium", "high"]
AMOUNT_BANDS: list[str] = list(get_args(AmountBand))

_LOW_MAX = 1_000
_MEDIUM_MAX = 15_000


def resolve_amount_band(amount: float) -> AmountBand:
    if amount < _LOW_MAX:
        return "low"
    if amount <= _MEDIUM_MAX:
        return "medium"
    return "high"
