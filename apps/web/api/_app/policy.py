"""A Policy (tickets 08/09) pairs the cost-engine's per-segment cost
assumptions with a daily review-capacity cap - the two knobs issue #1's
Policy Lab story (14) says a risk analyst edits ("cost assumptions, segment
thresholds, review capacity"; segment *thresholds* meaning the amount-band
cutoffs in segments.py, which the day-1 MVP treats as fixed rather than
per-policy - see segments.py).

Used directly, inline, by the replay engine (ticket 08 - a policy doesn't
need to be persisted to be replayed against historical traffic). Ticket 09
layers CRUD + a DRAFT->SIMULATED->ACTIVE lifecycle + guardrails on top of
this same shape, persisting policies so they can be referenced by id.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cost_engine import DEFAULT_COST_ASSUMPTIONS, CostAssumptions

# Not spec-specified as a number (issue #1's stories talk about "a daily
# cap" conceptually, e.g. story 12/13, without naming a figure) - a
# documented illustrative default, like the cost constants in cost_engine.py,
# overridable per policy.
DEFAULT_REVIEW_CAPACITY = 200


@dataclass(frozen=True)
class Policy:
    cost_assumptions: CostAssumptions = DEFAULT_COST_ASSUMPTIONS
    review_capacity: int = DEFAULT_REVIEW_CAPACITY


DEFAULT_POLICY = Policy()
