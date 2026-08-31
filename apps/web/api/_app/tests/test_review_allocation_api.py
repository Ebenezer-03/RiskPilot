"""API-seam test for POST /review/allocate (ticket 06's explicit acceptance
criterion: 'API-level test with an oversubscribed batch confirms cap +
ranking correctness')."""

from fastapi.testclient import TestClient

from _app.main import app

client = TestClient(app)


def _allocate(**kwargs) -> dict:
    response = client.post("/review/allocate", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def test_oversubscribed_batch_caps_and_ranks_correctly():
    """3 REVIEW-eligible candidates, capacity 2. Savings by hand:
    txn_top:   best_non_review=ALLOW(900)... wait BLOCK=900 vs ALLOW=1000/STEP_UP=500
               -> best non-review = STEP_UP(500), savings = 500-10 = 490
    txn_mid:   ALLOW=50/STEP_UP=30/REVIEW=10/BLOCK=100 -> best non-review=STEP_UP(30),
               savings = 30-10 = 20
    txn_bottom: ALLOW=50/STEP_UP=45/REVIEW=44/BLOCK=60 -> best non-review=STEP_UP(45),
               savings = 45-44 = 1
    Ranked: txn_top (490) > txn_mid (20) > txn_bottom (1). With capacity=2, only
    txn_top and txn_mid stay routed to REVIEW; txn_bottom is downgraded to STEP_UP.
    """
    body = _allocate(
        items=[
            {
                "transaction_id": "txn_bottom",
                "expected_costs": {"ALLOW": 50.0, "STEP_UP": 45.0, "REVIEW": 44.0, "BLOCK": 60.0},
            },
            {
                "transaction_id": "txn_top",
                "expected_costs": {"ALLOW": 1000.0, "STEP_UP": 500.0, "REVIEW": 10.0, "BLOCK": 900.0},
            },
            {
                "transaction_id": "txn_mid",
                "expected_costs": {"ALLOW": 50.0, "STEP_UP": 30.0, "REVIEW": 10.0, "BLOCK": 100.0},
            },
        ],
        daily_capacity=2,
    )

    assert body["daily_capacity"] == 2
    assert body["total_candidates"] == 3
    assert body["routed_to_review_count"] == 2

    results_by_id = {r["transaction_id"]: r for r in body["results"]}
    assert [r["transaction_id"] for r in body["results"]] == ["txn_top", "txn_mid", "txn_bottom"]

    assert results_by_id["txn_top"]["routed_to_review"] is True
    assert results_by_id["txn_top"]["final_action"] == "REVIEW"
    assert results_by_id["txn_top"]["expected_savings_from_review"] == 490.0

    assert results_by_id["txn_mid"]["routed_to_review"] is True
    assert results_by_id["txn_mid"]["final_action"] == "REVIEW"

    assert results_by_id["txn_bottom"]["routed_to_review"] is False
    assert results_by_id["txn_bottom"]["final_action"] == "STEP_UP"
    assert results_by_id["txn_bottom"]["expected_savings_from_review"] == 1.0


def test_under_capacity_batch_routes_everyone_to_review():
    body = _allocate(
        items=[
            {"transaction_id": "txn_1", "expected_costs": {"ALLOW": 50.0, "STEP_UP": 30.0, "REVIEW": 10.0, "BLOCK": 100.0}},
        ],
        daily_capacity=10,
    )
    assert body["routed_to_review_count"] == 1
    assert body["results"][0]["routed_to_review"] is True


def test_empty_batch_returns_empty_results():
    body = _allocate(items=[], daily_capacity=5)
    assert body["total_candidates"] == 0
    assert body["routed_to_review_count"] == 0
    assert body["results"] == []


def test_negative_daily_capacity_returns_422():
    response = client.post(
        "/review/allocate",
        json={
            "items": [{"transaction_id": "txn_1", "expected_costs": {"ALLOW": 1, "STEP_UP": 1, "REVIEW": 1, "BLOCK": 1}}],
            "daily_capacity": -1,
        },
    )
    assert response.status_code == 422


def test_missing_action_in_expected_costs_returns_422():
    response = client.post(
        "/review/allocate",
        json={
            "items": [{"transaction_id": "txn_1", "expected_costs": {"ALLOW": 1, "STEP_UP": 1, "BLOCK": 1}}],
            "daily_capacity": 5,
        },
    )
    assert response.status_code == 422
