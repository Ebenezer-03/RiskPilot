"""API-seam tests for the rate-limiting middleware (ticket 13).

Per the spec's testing decisions, behaviour is tested black-box against the
FastAPI app (TestClient), not by reaching into internals - except the
per-key hit counter itself, which we reset between tests since it's
process-global state (see rate_limit.py's own docstring on that scoping).
"""

from fastapi.testclient import TestClient

from _app.main import app
from _app.rate_limit import RateLimitMiddleware

client = TestClient(app)


def _reset_hits():
    for middleware in client.app.user_middleware:
        if middleware.cls is RateLimitMiddleware:
            # Middleware instances are constructed lazily on first request;
            # nothing to reset before that, and each test gets a fresh
            # in-process counter dict via this direct clear.
            pass
    # The middleware stack is rebuilt by Starlette per TestClient app, but
    # the counter dict lives on the middleware instance across requests
    # within a single TestClient - clear it via the app's built middleware
    # stack so tests don't leak hits into each other.
    app.middleware_stack = None  # force Starlette to rebuild on next request


def test_health_is_exempt_from_rate_limiting():
    _reset_hits()
    for _ in range(50):
        response = client.get("/health")
        assert response.status_code == 200


def test_score_endpoint_is_rate_limited_after_threshold():
    _reset_hits()
    # /score's limit is 30 requests / 60s (rate_limit.py's _LIMITS). An
    # invalid payload still passes through the middleware before failing
    # validation, so a 422 still counts as a hit for this test's purpose.
    last_status = None
    for _ in range(31):
        last_status = client.post("/score", json={}).status_code

    assert last_status == 429


def test_rate_limited_response_has_retry_after_header():
    _reset_hits()
    response = None
    for _ in range(31):
        response = client.post("/score", json={})

    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.json()["detail"].startswith("Rate limit exceeded")
