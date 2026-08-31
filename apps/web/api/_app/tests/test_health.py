"""API-seam tests for the liveness/health surface.

Per the spec's testing decisions, behaviour is tested black-box against the
FastAPI app (TestClient), not by reaching into internals.
"""

import psycopg
import pytest
from fastapi.testclient import TestClient

from _app.main import app

client = TestClient(app)


def test_root_reports_service_name():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"service": "riskpilot-api"}


def test_health_without_db_configured(monkeypatch):
    monkeypatch.delenv("POSTGRES_URL_NON_POOLING", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "db": "not_configured"}


def test_health_reports_degraded_when_db_unreachable(monkeypatch):
    monkeypatch.setenv("POSTGRES_URL_NON_POOLING", "postgresql://bad:bad@127.0.0.1:1/nonexistent")

    def raise_connect_error(*args, **kwargs):
        raise psycopg.OperationalError("simulated connection failure")

    monkeypatch.setattr(psycopg, "connect", raise_connect_error)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"
    assert "detail" in body


@pytest.mark.integration
def test_health_connects_to_real_db_when_configured():
    """Only meaningful with real Supabase credentials in the environment
    (e.g. after `vercel env pull`). Skipped by default in CI."""
    import os

    if not (os.environ.get("POSTGRES_URL_NON_POOLING") or os.environ.get("POSTGRES_URL")):
        pytest.skip("no database URL in environment")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["db"] == "connected"
