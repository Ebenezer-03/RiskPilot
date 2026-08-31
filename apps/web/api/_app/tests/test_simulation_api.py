"""API-seam test for POST /simulation/replay (ticket 08's explicit
acceptance criterion: 'API-level test with two known policies confirms
expected delta direction'). Requires a real database - see
test_transactions_api.py's module docstring for why this is
@pytest.mark.integration.
"""

import pytest
from fastapi.testclient import TestClient

from _app import db
from _app.main import app

client = TestClient(app)

pytestmark = pytest.mark.integration


def _skip_without_db():
    if not db.get_database_url():
        pytest.skip("no database URL in environment")


def _seed_synthetic_transactions(count: int) -> None:
    response = client.post("/transactions/synthetic", json={"count": count})
    assert response.status_code == 200, response.text


def test_replay_confirms_expected_delta_direction_for_a_conservative_candidate():
    """A candidate policy with a far higher fraud-loss rate assumption
    treats fraud as more expensive to miss, so it must choose BLOCK/REVIEW
    more often than the baseline over the same window - never allowing more
    of the caught fraud through than baseline did. That must show up as:
      - fraud_loss delta <= 0 (candidate prevents at least as much realized
        fraud loss as baseline)
      - transactions_caught delta >= 0 (candidate catches at least as many
        truly-fraud transactions)
    Uses count=50 synthetic transactions (each already carries its own
    generation-time fraud probability - see transactions.py) so there is
    always a real, non-trivial fraud rate to replay against.
    """
    _skip_without_db()
    _seed_synthetic_transactions(50)

    baseline_policy = {"policy_id": "baseline-default"}
    candidate_policy = {
        "policy_id": "candidate-conservative",
        "cost_assumptions": {"fraud_loss_rate_base": 50.0},
    }

    response = client.post(
        "/simulation/replay",
        json={
            "baseline_policy": baseline_policy,
            "candidate_policy": candidate_policy,
            "window": {"data_source": "synthetic", "limit": 500},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["baseline_policy_id"] == "baseline-default"
    assert body["candidate_policy_id"] == "candidate-conservative"
    assert body["transactions_replayed"] > 0

    aggregate = body["aggregate"]
    assert aggregate["delta"]["fraud_loss"] <= 0
    assert aggregate["delta"]["transactions_caught"] >= 0
    # A far more conservative policy blocks/reviews more overall, which
    # cannot make its own bottom-line expected loss lower than a policy
    # that (by construction, being the day-1 default) is already
    # cost-minimizing under its own assumptions - not asserted here since
    # the two policies use *different* cost assumptions and so aren't
    # comparable on the same expected-loss scale; net_expected_loss is
    # still present and finite for both.
    assert isinstance(aggregate["baseline"]["net_expected_loss"], float)
    assert isinstance(aggregate["candidate"]["net_expected_loss"], float)

    assert "offline estimate" in body["disclaimer"].lower()
    assert isinstance(body["by_segment"], dict)
    assert len(body["by_segment"]) > 0


def test_replay_with_partial_cost_assumption_override_does_not_crash():
    """A caller overriding just one amount band's false-decline bonus
    (e.g. {"low": 0.5}) must not 500 the first time the window contains a
    transaction in a different band - see CostAssumptionsRequest's merge
    validator."""
    _skip_without_db()
    _seed_synthetic_transactions(20)

    response = client.post(
        "/simulation/replay",
        json={
            "baseline_policy": {"policy_id": "baseline"},
            "candidate_policy": {
                "policy_id": "candidate-partial-override",
                "cost_assumptions": {"false_decline_amount_band_bonus": {"low": 0.5}},
            },
            "window": {"data_source": "synthetic", "limit": 500},
        },
    )
    assert response.status_code == 200, response.text


def test_replay_with_no_labeled_transactions_in_window_returns_422():
    _skip_without_db()

    response = client.post(
        "/simulation/replay",
        json={
            "baseline_policy": {"policy_id": "baseline"},
            "candidate_policy": {"policy_id": "candidate"},
            # live_razorpay transactions don't exist yet in this system (no
            # Razorpay integration ticket has been built) - guaranteed empty.
            "window": {"data_source": "live_razorpay", "limit": 10},
        },
    )
    assert response.status_code == 422
