"""API-seam tests for the policy registry (ticket 09): CRUD, the
DRAFT -> SIMULATED -> ACTIVE lifecycle, and the ticket's explicit
acceptance criterion - one passing promotion, one rejected promotion per
guardrail. Requires a real database - see test_transactions_api.py's
module docstring for why this is @pytest.mark.integration.

Runs against a persistent, shared Supabase instance (not a throwaway
per-test DB), so every policy_id is uuid-suffixed to stay collision-free
across repeat runs, and guardrail tests force determinism either through
an extreme cost-assumption difference (approval rate / false-positive
rate) or a deliberately strict/lenient threshold override (sample size,
calibration) rather than relying on the database's total accumulated
transaction volume, which this suite doesn't control.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from _app import db
from _app.main import app
from _app.transactions import insert_transaction

client = TestClient(app)

pytestmark = pytest.mark.integration


def _skip_without_db():
    if not db.get_database_url():
        pytest.skip("no database URL in environment")


def _policy_id(label: str) -> str:
    return f"test-{label}-{uuid.uuid4().hex[:8]}"


def _create_policy(*, name="Test policy", cost_assumptions=None, review_capacity=1000) -> dict:
    payload = {"policy_id": _policy_id(name.lower().replace(" ", "-")), "name": name, "review_capacity": review_capacity}
    if cost_assumptions is not None:
        payload["cost_assumptions"] = cost_assumptions
    response = client.post("/policies", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _seed_synthetic_transactions(count: int = 30) -> None:
    response = client.post("/transactions/synthetic", json={"count": count})
    assert response.status_code == 200, response.text


def _seed_review_eligible_transaction() -> None:
    """p=0.3, digital_goods/medium/new_customer/known_device -> REVIEW under
    the day-1 default cost assumptions (see test_decisions_api.py's
    identical case) - a deterministic REVIEW-eligible row regardless of
    what else is in the database."""
    import random
    from datetime import datetime, timezone

    conn = db.get_connection()
    with conn:
        insert_transaction(
            conn,
            {
                "transaction_id": f"txn_synthetic_review_{uuid.uuid4().hex[:12]}",
                "data_source": "synthetic",
                "event_time": datetime.now(timezone.utc),
                "amount": 5000,
                "currency": "INR",
                "merchant_id": f"m_digital_goods_{random.randint(1, 50):03d}",
                "merchant_category": "digital_goods",
                "amount_band": "medium",
                "is_returning_customer": False,
                "is_known_device": True,
                "is_fraud": False,
                "raw_features": {"generation_fraud_probability": 0.3},
            },
        )


def test_policy_crud_lifecycle():
    _skip_without_db()

    created = _create_policy()
    assert created["status"] == "DRAFT"
    policy_id = created["policy_id"]

    fetched = client.get(f"/policies/{policy_id}")
    assert fetched.status_code == 200
    assert fetched.json()["policy_id"] == policy_id

    listing = client.get("/policies")
    assert listing.status_code == 200
    assert any(p["policy_id"] == policy_id for p in listing.json())

    updated = client.put(
        f"/policies/{policy_id}", json={"name": "Renamed", "review_capacity": 500}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["review_capacity"] == 500

    deleted = client.delete(f"/policies/{policy_id}")
    assert deleted.status_code == 204
    assert client.get(f"/policies/{policy_id}").status_code == 404


def test_cannot_edit_or_delete_a_non_draft_policy():
    _skip_without_db()
    _seed_synthetic_transactions(30)

    created = _create_policy()
    policy_id = created["policy_id"]

    # data_source pinned to synthetic - the default (any source) window
    # would also pull previously-seeded ieee_cis rows, each requiring a
    # real (slow) SHAP-explained model score; synthetic-only keeps this
    # test fast via the cheap generation-time-probability proxy.
    simulate_response = client.post(
        f"/policies/{policy_id}/simulate", json={"window": {"data_source": "synthetic", "limit": 500}}
    )
    assert simulate_response.status_code == 200, simulate_response.text
    assert simulate_response.json()["status"] == "SIMULATED"

    assert client.put(f"/policies/{policy_id}", json={"name": "x", "review_capacity": 1}).status_code == 409
    assert client.delete(f"/policies/{policy_id}").status_code == 409


def test_passing_promotion():
    """An identical-to-baseline candidate (no behavior change at all)
    passes every guardrail. Sample-size and calibration thresholds are
    relaxed here deliberately - this test isolates "an unremarkable
    candidate gets promoted", not the guardrails' own trigger conditions
    (covered individually below)."""
    _skip_without_db()
    _seed_synthetic_transactions(30)

    shared_assumptions = None  # default cost assumptions for both sides
    baseline = _create_policy(name="passing-baseline", cost_assumptions=shared_assumptions, review_capacity=100000)
    candidate = _create_policy(name="passing-candidate", cost_assumptions=shared_assumptions, review_capacity=100000)

    simulate = client.post(
        f"/policies/{candidate['policy_id']}/simulate",
        json={"baseline_policy_id": baseline["policy_id"], "window": {"data_source": "synthetic", "limit": 500}},
    )
    assert simulate.status_code == 200, simulate.text

    promote = client.post(
        f"/policies/{candidate['policy_id']}/promote",
        json={"thresholds": {"min_segment_sample_size": 0, "max_calibration_brier_score": 1.0}},
    )
    assert promote.status_code == 200, promote.text
    body = promote.json()
    assert body["approved"] is True
    assert body["violations"] == []
    assert body["policy"]["status"] == "ACTIVE"


def _simulate_conservative_candidate(*, thresholds: dict) -> dict:
    """Shared setup for the approval-rate-drop and false-positive-rate
    guardrail tests: a candidate with a drastically higher fraud-loss-rate
    assumption blocks nearly everything, cratering approval rate and
    blocking legitimate transactions the (default-assumption) baseline
    would have allowed."""
    _seed_synthetic_transactions(30)

    baseline = _create_policy(name="conservative-baseline", review_capacity=100000)
    candidate = _create_policy(
        name="conservative-candidate",
        cost_assumptions={"fraud_loss_rate_base": 1000.0},
        review_capacity=100000,
    )

    simulate = client.post(
        f"/policies/{candidate['policy_id']}/simulate",
        json={"baseline_policy_id": baseline["policy_id"], "window": {"data_source": "synthetic", "limit": 500}},
    )
    assert simulate.status_code == 200, simulate.text

    promote = client.post(f"/policies/{candidate['policy_id']}/promote", json={"thresholds": thresholds})
    assert promote.status_code == 200, promote.text
    return promote.json()


def test_rejected_promotion_approval_rate_drop():
    _skip_without_db()
    body = _simulate_conservative_candidate(thresholds={})
    assert body["approved"] is False
    assert any(v["guardrail"] == "approval_rate_drop" for v in body["violations"])
    assert body["policy"]["status"] == "SIMULATED"


def test_rejected_promotion_false_positive_rate_increase():
    _skip_without_db()
    body = _simulate_conservative_candidate(thresholds={})
    assert body["approved"] is False
    assert any(v["guardrail"] == "false_positive_rate_increase" for v in body["violations"])


def test_rejected_promotion_review_queue_overflow():
    _skip_without_db()
    _seed_review_eligible_transaction()

    baseline = _create_policy(name="overflow-baseline", review_capacity=100000)
    # review_capacity=0: any REVIEW-eligible transaction overflows it.
    candidate = _create_policy(name="overflow-candidate", review_capacity=0)

    simulate = client.post(
        f"/policies/{candidate['policy_id']}/simulate",
        json={"baseline_policy_id": baseline["policy_id"], "window": {"data_source": "synthetic", "limit": 500}},
    )
    assert simulate.status_code == 200, simulate.text

    promote = client.post(
        f"/policies/{candidate['policy_id']}/promote",
        json={"thresholds": {"min_segment_sample_size": 0, "max_calibration_brier_score": 1.0}},
    )
    assert promote.status_code == 200, promote.text
    body = promote.json()
    assert body["approved"] is False
    assert any(v["guardrail"] == "review_queue_overflow" for v in body["violations"])


def test_rejected_promotion_sample_size_floor():
    _skip_without_db()
    _seed_synthetic_transactions(5)

    baseline = _create_policy(name="samplesize-baseline", review_capacity=100000)
    candidate = _create_policy(name="samplesize-candidate", review_capacity=100000)

    simulate = client.post(
        f"/policies/{candidate['policy_id']}/simulate",
        json={"baseline_policy_id": baseline["policy_id"], "window": {"data_source": "synthetic", "limit": 500}},
    )
    assert simulate.status_code == 200, simulate.text

    # An absurdly high floor guarantees every segment falls short,
    # regardless of how much data has accumulated in this shared database.
    promote = client.post(
        f"/policies/{candidate['policy_id']}/promote",
        json={"thresholds": {"min_segment_sample_size": 10_000_000, "max_calibration_brier_score": 1.0}},
    )
    assert promote.status_code == 200, promote.text
    body = promote.json()
    assert body["approved"] is False
    assert any(v["guardrail"] == "sample_size_floor" for v in body["violations"])


def test_rejected_promotion_calibration_degradation():
    _skip_without_db()
    _seed_synthetic_transactions(30)

    baseline = _create_policy(name="calibration-baseline", review_capacity=100000)
    candidate = _create_policy(name="calibration-candidate", review_capacity=100000)

    simulate = client.post(
        f"/policies/{candidate['policy_id']}/simulate",
        json={"baseline_policy_id": baseline["policy_id"], "window": {"data_source": "synthetic", "limit": 500}},
    )
    assert simulate.status_code == 200, simulate.text

    # A zero threshold is always exceeded by a real (non-zero) Brier score.
    promote = client.post(
        f"/policies/{candidate['policy_id']}/promote",
        json={"thresholds": {"min_segment_sample_size": 0, "max_calibration_brier_score": 0.0}},
    )
    assert promote.status_code == 200, promote.text
    body = promote.json()
    assert body["approved"] is False
    assert any(v["guardrail"] == "calibration_degradation" for v in body["violations"])


def test_cannot_promote_a_draft_policy():
    _skip_without_db()
    created = _create_policy()
    response = client.post(f"/policies/{created['policy_id']}/promote", json={})
    assert response.status_code == 409


def test_cannot_simulate_a_non_draft_policy():
    _skip_without_db()
    _seed_synthetic_transactions(30)
    created = _create_policy()
    window = {"window": {"data_source": "synthetic", "limit": 500}}
    first = client.post(f"/policies/{created['policy_id']}/simulate", json=window)
    assert first.status_code == 200
    second = client.post(f"/policies/{created['policy_id']}/simulate", json=window)
    assert second.status_code == 409


def test_get_unknown_policy_returns_404():
    _skip_without_db()
    response = client.get(f"/policies/{_policy_id('missing')}")
    assert response.status_code == 404
