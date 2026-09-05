"""API-seam tests for ticket 16 (stretch)'s CANARY and ROLLED_BACK
transitions. Same setup pattern as test_policies_api.py: relaxed
thresholds for a guaranteed-passing path, an extreme cost-assumption
difference to force a guaranteed-rejected path.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from _app import db
from _app.main import app

client = TestClient(app)

pytestmark = pytest.mark.integration


def _skip_without_db():
    if not db.get_database_url():
        pytest.skip("no database URL in environment")


def _policy_id(label: str) -> str:
    return f"test-{label}-{uuid.uuid4().hex[:8]}"


def _create_policy(*, name: str, cost_assumptions: dict | None = None, review_capacity: int = 100000) -> dict:
    payload = {"policy_id": _policy_id(name), "name": name, "review_capacity": review_capacity}
    if cost_assumptions is not None:
        payload["cost_assumptions"] = cost_assumptions
    response = client.post("/policies", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _seed_synthetic_transactions(count: int = 200) -> None:
    # /transactions/synthetic caps a single request at 100 - chunk larger
    # requests across multiple calls rather than raising the API's own limit
    # just to suit this test.
    remaining = count
    while remaining > 0:
        batch = min(remaining, 100)
        response = client.post("/transactions/synthetic", json={"count": batch})
        assert response.status_code == 200, response.text
        remaining -= batch


# Relaxed enough that a small 95/5 canary subsample of a modest window
# still passes - see canary_policy's own docstring on why a subsample
# realistically trips min_segment_sample_size at its production default.
_RELAXED_THRESHOLDS = {"min_segment_sample_size": 0, "max_calibration_brier_score": 1.0}


def _simulate(policy_id: str, baseline_policy_id: str) -> None:
    response = client.post(
        f"/policies/{policy_id}/simulate",
        json={"baseline_policy_id": baseline_policy_id, "window": {"data_source": "synthetic", "limit": 500}},
    )
    assert response.status_code == 200, response.text


def test_cannot_canary_a_draft_policy():
    _skip_without_db()
    draft = _create_policy(name="canary-needs-simulated")
    response = client.post(f"/policies/{draft['policy_id']}/canary", json={})
    assert response.status_code == 409


def test_canary_then_promote_to_active():
    _skip_without_db()
    _seed_synthetic_transactions(200)

    baseline = _create_policy(name="canary-baseline")
    candidate = _create_policy(name="canary-candidate")
    _simulate(candidate["policy_id"], baseline["policy_id"])

    canary = client.post(
        f"/policies/{candidate['policy_id']}/canary",
        json={"window": {"data_source": "synthetic", "limit": 500}, "thresholds": _RELAXED_THRESHOLDS},
    )
    assert canary.status_code == 200, canary.text
    body = canary.json()
    assert body["approved"] is True
    assert body["policy"]["status"] == "CANARY"
    assert body["policy"]["canary_replay_result"] is not None
    # The 95/5 subsample is strictly smaller than the full-window replay
    # already stored from /simulate.
    assert (
        body["policy"]["canary_replay_result"]["transactions_replayed"]
        < body["policy"]["replay_result"]["transactions_replayed"]
    )

    promote = client.post(f"/policies/{candidate['policy_id']}/promote", json={"thresholds": _RELAXED_THRESHOLDS})
    assert promote.status_code == 200, promote.text
    assert promote.json()["approved"] is True
    assert promote.json()["policy"]["status"] == "ACTIVE"


def test_cannot_promote_from_draft_or_active_via_canary_route():
    _skip_without_db()
    draft = _create_policy(name="not-yet-simulated")
    response = client.post(f"/policies/{draft['policy_id']}/promote", json={"thresholds": _RELAXED_THRESHOLDS})
    assert response.status_code == 409


def test_rollback_reverts_active_policy_pointer():
    """Promote policy A to ACTIVE, then promote policy B to ACTIVE
    (superseding A), then roll B back - A should be reactivated, exactly
    ticket 16's acceptance criterion."""
    _skip_without_db()
    _seed_synthetic_transactions(200)

    baseline = _create_policy(name="rollback-shared-baseline")

    policy_a = _create_policy(name="rollback-policy-a")
    _simulate(policy_a["policy_id"], baseline["policy_id"])
    promote_a = client.post(f"/policies/{policy_a['policy_id']}/promote", json={"thresholds": _RELAXED_THRESHOLDS})
    assert promote_a.status_code == 200, promote_a.text
    assert promote_a.json()["policy"]["status"] == "ACTIVE"

    policy_b = _create_policy(name="rollback-policy-b")
    _simulate(policy_b["policy_id"], baseline["policy_id"])
    promote_b = client.post(f"/policies/{policy_b['policy_id']}/promote", json={"thresholds": _RELAXED_THRESHOLDS})
    assert promote_b.status_code == 200, promote_b.text
    body_b = promote_b.json()
    assert body_b["policy"]["status"] == "ACTIVE"
    assert body_b["policy"]["superseded_policy_id"] == policy_a["policy_id"]

    rollback = client.post(f"/policies/{policy_b['policy_id']}/rollback")
    assert rollback.status_code == 200, rollback.text
    rollback_body = rollback.json()
    assert rollback_body["policy"]["status"] == "ROLLED_BACK"
    assert rollback_body["reactivated_policy"] is not None
    assert rollback_body["reactivated_policy"]["policy_id"] == policy_a["policy_id"]
    assert rollback_body["reactivated_policy"]["status"] == "ACTIVE"

    # get_current_active_policy orders by activated_at DESC - A should be
    # "the" active policy again now that its activated_at was refreshed.
    refetched_a = client.get(f"/policies/{policy_a['policy_id']}")
    assert refetched_a.json()["status"] == "ACTIVE"


def test_rollback_with_no_superseded_policy_reactivates_nothing():
    _skip_without_db()
    _seed_synthetic_transactions(200)

    baseline = _create_policy(name="rollback-solo-baseline")
    candidate = _create_policy(name="rollback-solo-candidate")
    _simulate(candidate["policy_id"], baseline["policy_id"])
    promote = client.post(f"/policies/{candidate['policy_id']}/promote", json={"thresholds": _RELAXED_THRESHOLDS})
    assert promote.status_code == 200, promote.text

    # This candidate may or may not have superseded some earlier-ACTIVE
    # policy from another test in this same shared database - only assert
    # the one thing this test actually controls: rollback always succeeds
    # and the policy itself always ends up ROLLED_BACK.
    rollback = client.post(f"/policies/{candidate['policy_id']}/rollback")
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["policy"]["status"] == "ROLLED_BACK"


def test_cannot_rollback_a_draft_or_simulated_policy():
    _skip_without_db()
    draft = _create_policy(name="rollback-needs-active")
    response = client.post(f"/policies/{draft['policy_id']}/rollback")
    assert response.status_code == 409


def test_cannot_rollback_a_stale_superseded_active_policy():
    """transition_to_active never demotes the row it supersedes (more than
    one row can carry status='ACTIVE' over the system's lifetime - see
    policy_registry.py's own docstring), so promoting A then B leaves A's
    DB status literally 'ACTIVE' even though B is the one actually
    governing /decide. Rolling back A directly (not through B) must be
    rejected, not silently succeed with no real effect."""
    _skip_without_db()
    _seed_synthetic_transactions(200)

    baseline = _create_policy(name="stale-rollback-baseline")

    policy_a = _create_policy(name="stale-rollback-a")
    _simulate(policy_a["policy_id"], baseline["policy_id"])
    promote_a = client.post(f"/policies/{policy_a['policy_id']}/promote", json={"thresholds": _RELAXED_THRESHOLDS})
    assert promote_a.status_code == 200, promote_a.text

    policy_b = _create_policy(name="stale-rollback-b")
    _simulate(policy_b["policy_id"], baseline["policy_id"])
    promote_b = client.post(f"/policies/{policy_b['policy_id']}/promote", json={"thresholds": _RELAXED_THRESHOLDS})
    assert promote_b.status_code == 200, promote_b.text
    assert promote_b.json()["policy"]["superseded_policy_id"] == policy_a["policy_id"]

    # A's own status column is still 'ACTIVE' - confirm the naive read would
    # be misleading before asserting the endpoint doesn't fall for it.
    assert client.get(f"/policies/{policy_a['policy_id']}").json()["status"] == "ACTIVE"

    stale_rollback = client.post(f"/policies/{policy_a['policy_id']}/rollback")
    assert stale_rollback.status_code == 409, stale_rollback.text

    # B is untouched and still the real current-active policy.
    assert client.get(f"/policies/{policy_b['policy_id']}").json()["status"] == "ACTIVE"

    # Rolling back B (the real current-active policy) still works and
    # correctly reactivates A.
    rollback_b = client.post(f"/policies/{policy_b['policy_id']}/rollback")
    assert rollback_b.status_code == 200, rollback_b.text
    assert rollback_b.json()["reactivated_policy"]["policy_id"] == policy_a["policy_id"]
