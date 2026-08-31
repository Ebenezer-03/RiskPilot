"""API-seam round-trip test for /transactions (ticket 04's explicit
acceptance criterion: 'Test confirms round-trip persistence and
retrieval'). Requires a real database - apps/web/conftest.py loads
.env.local automatically if present; skipped otherwise, same pattern as
test_health.py's DB-dependent test.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _app import db
from _app.main import app
from _app.segments import MERCHANT_CATEGORIES
from _app.transactions import insert_transaction, record_from_ieee_cis_row

client = TestClient(app)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

pytestmark = pytest.mark.integration


def _skip_without_db():
    if not db.get_database_url():
        pytest.skip("no database URL in environment")


def test_synthetic_transaction_round_trips_through_the_api():
    _skip_without_db()

    create_response = client.post("/transactions/synthetic", json={"count": 1})
    assert create_response.status_code == 200
    [created] = create_response.json()
    assert created["data_source"] == "synthetic"
    assert created["merchant_category"] in MERCHANT_CATEGORIES

    read_response = client.get(f"/transactions/{created['transaction_id']}")
    assert read_response.status_code == 200
    fetched = read_response.json()

    assert fetched["transaction_id"] == created["transaction_id"]
    assert fetched["amount"] == created["amount"]
    assert fetched["merchant_category"] == created["merchant_category"]
    assert fetched["amount_band"] == created["amount_band"]
    assert fetched["is_fraud"] == created["is_fraud"]


def test_generate_synthetic_respects_count():
    _skip_without_db()

    response = client.post("/transactions/synthetic", json={"count": 3})
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_ieee_cis_derived_transaction_round_trips_through_the_api():
    """The other half of 'IEEE-CIS-derived and synthetic transactions both
    persist under the same schema' (ticket 04) - exercised for real against
    Postgres, not just asserted at the mapping-function level (see
    test_record_from_ieee_cis_row_maps_known_fields in test_transactions.py).
    Uses the committed real-data fixture (see tests/fixtures/) rather than
    requiring the full IEEE-CIS dataset, so this runs in a fresh clone/CI
    the same as any other integration test, not just after a manual
    `python -m _app.ml.load_ieee_cis_sample` run."""
    _skip_without_db()

    fixture = json.loads((FIXTURES_DIR / "fraud_example.json").read_text())
    # TransactionID/isFraud are top-level fixture metadata, not inside
    # "features" (see tests/fixtures/generate_fixtures.py) - record_from_ieee_cis_row
    # needs the full raw row shape, so reassemble it the same way the real
    # data pipeline does.
    raw_row = {**fixture["features"], "TransactionID": fixture["transaction_id"], "isFraud": fixture["true_label"]}
    record = record_from_ieee_cis_row(raw_row)

    with db.get_connection() as conn:
        db.ensure_schema(conn)
        insert_transaction(conn, record)

    response = client.get(f"/transactions/{record['transaction_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["data_source"] == "ieee_cis"
    assert body["amount"] == record["amount"]
    assert body["merchant_category"] == record["merchant_category"]
    assert body["is_fraud"] is True  # this fixture's true_label is 1


def test_read_unknown_transaction_returns_404():
    _skip_without_db()

    response = client.get("/transactions/txn_does_not_exist")
    assert response.status_code == 404
