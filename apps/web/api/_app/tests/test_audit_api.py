"""API-seam tests for GET /audit/{transaction_id} (ticket 07's explicit
acceptance criterion: 'API-level test confirms a decision's trace
round-trips exactly'). Requires a real database - see test_transactions_api.py's
module docstring for why these are marked @pytest.mark.integration.
"""

import pytest
from fastapi.testclient import TestClient

from _app import db
from _app.cost_engine import POLICY_VERSION
from _app.main import app
from _app.segments import SEGMENT_DEFINITION_VERSION

client = TestClient(app)

pytestmark = pytest.mark.integration


def _skip_without_db():
    if not db.get_database_url():
        pytest.skip("no database URL in environment")


def _create_synthetic_transaction() -> dict:
    response = client.post("/transactions/synthetic", json={"count": 1})
    assert response.status_code == 200, response.text
    [created] = response.json()
    return created


def test_decision_trace_round_trips_exactly():
    _skip_without_db()

    txn = _create_synthetic_transaction()
    decide_response = client.post(
        "/decide",
        json={
            "transaction_id": txn["transaction_id"],
            "probability": 0.42,
            "model_version": "fraud-model-v1.0",
            "calibration_version": "isotonic-v1.0",
            "feature_schema_version": "features-v1.0",
        },
    )
    assert decide_response.status_code == 200, decide_response.text
    decided = decide_response.json()

    audit_response = client.get(f"/audit/{txn['transaction_id']}")
    assert audit_response.status_code == 200, audit_response.text
    trace = audit_response.json()

    assert trace["transaction"]["transaction_id"] == txn["transaction_id"]
    assert trace["transaction"]["data_source"] == "synthetic"

    assert len(trace["decisions"]) == 1
    [entry] = trace["decisions"]

    # Every field returned by /decide is exactly reconstructable from the
    # audit trace.
    assert entry["transaction_id"] == txn["transaction_id"]
    assert entry["action"] == decided["decision"]
    assert entry["expected_costs"] == decided["expected_costs"]
    assert entry["reason_codes"] == decided["reason_codes"]
    assert entry["probability_used"] == decided["probability_used"] == 0.42
    assert entry["merchant_category"] == decided["merchant_category"]
    assert entry["amount_band"] == decided["amount_band"]
    assert entry["is_returning_customer"] == decided["is_returning_customer"]
    assert entry["is_known_device"] == decided["is_known_device"]
    assert entry["cost_profile_source"] == decided["cost_profile_source"]

    # Full version metadata (issue #1's audit trail spec) is stored, not
    # just the decision's own numbers.
    assert entry["data_source"] == "synthetic"
    assert entry["model_version"] == "fraud-model-v1.0"
    assert entry["calibration_version"] == "isotonic-v1.0"
    assert entry["feature_schema_version"] == "features-v1.0"
    assert entry["segment_definition_version"] == SEGMENT_DEFINITION_VERSION
    # policy_version identifies the decision mechanism, which the registry
    # never varies, so it's always the constant. cost_matrix_version isn't
    # asserted against the hardcoded day-1 constant here: this suite runs
    # against a persistent, shared database (see test_policies_api.py's
    # module docstring), where another test may have already promoted a
    # policy to ACTIVE - ticket 09's whole point is that /decide then
    # stamps *that* policy's id here instead (see decisions.py). Populated
    # either way is what this test can actually guarantee.
    assert entry["policy_version"] == POLICY_VERSION
    assert entry["cost_matrix_version"]


def test_decision_without_explicit_model_versions_stores_null():
    """A synthetic transaction's probability doesn't come from the real
    detector - model_version/calibration_version/feature_schema_version are
    honestly null rather than fabricated, when the caller doesn't supply
    them."""
    _skip_without_db()

    txn = _create_synthetic_transaction()
    client.post("/decide", json={"transaction_id": txn["transaction_id"], "probability": 0.1})

    trace = client.get(f"/audit/{txn['transaction_id']}").json()
    [entry] = trace["decisions"]

    assert entry["model_version"] is None
    assert entry["calibration_version"] is None
    assert entry["feature_schema_version"] is None
    # Policy-level versions are always populated, even with no real model
    # behind the probability (see the equivalent assertion's comment in
    # test_decision_trace_round_trips_exactly above).
    assert entry["segment_definition_version"] == SEGMENT_DEFINITION_VERSION
    assert entry["policy_version"] == POLICY_VERSION
    assert entry["cost_matrix_version"]


def test_repeated_decisions_on_the_same_transaction_are_all_recorded():
    """Re-deciding a transaction (e.g. after a policy change) is a
    legitimate, separately-auditable event - not overwritten or
    deduplicated."""
    _skip_without_db()

    txn = _create_synthetic_transaction()
    client.post("/decide", json={"transaction_id": txn["transaction_id"], "probability": 0.1})
    client.post("/decide", json={"transaction_id": txn["transaction_id"], "probability": 0.9})

    trace = client.get(f"/audit/{txn['transaction_id']}").json()

    assert len(trace["decisions"]) == 2
    # Oldest first (chronological trail).
    assert trace["decisions"][0]["probability_used"] == 0.1
    assert trace["decisions"][1]["probability_used"] == 0.9


def test_audit_for_unknown_transaction_returns_404():
    _skip_without_db()

    response = client.get("/audit/txn_does_not_exist")
    assert response.status_code == 404


def test_decide_without_transaction_id_is_not_persisted():
    """An ad-hoc /decide call with no transaction_id has nothing to audit
    by ID - it isn't stored, and this isn't a failure mode (see
    audit.py's module docstring)."""
    _skip_without_db()

    response = client.post(
        "/decide",
        json={
            "probability": 0.5,
            "merchant_category": "travel",
            "amount": 1000,
            "is_returning_customer": True,
            "is_known_device": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["transaction_id"] is None
    # No transaction_id to audit by; nothing else to assert here beyond
    # "this didn't error" - the persistence-skip is exercised for real by
    # every other test above returning exactly one row per decide call.
