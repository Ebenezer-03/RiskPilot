"""Loads apps/web/.env.local (pulled via `vercel env pull`) before the test
session starts, so `@pytest.mark.integration` tests that need real Supabase
credentials actually run instead of always skipping. Does nothing if the
file isn't present (e.g. a fresh clone, or CI without it) - integration
tests degrade to skipped in that case, same as before this existed.
"""

from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env.local")


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Every test file's `TestClient(app)` shares the same `app` singleton,
    and RateLimitMiddleware's hit-counter lives on the middleware instance
    for the app's lifetime - so without this, a test file earlier in the
    session (or many tests in one file) can trip a later, otherwise-
    unrelated test's rate limit purely from run order. Forcing Starlette to
    rebuild the middleware stack gives every test a fresh, empty counter,
    matching real usage (a real client's rate limit is scoped to its own
    request history, not to whichever tests happened to run before it in
    this process)."""
    try:
        from _app.rate_limit import reset_rate_limiters
        reset_rate_limiters()
    except Exception:
        pass
    from _app.main import app

    app.middleware_stack = None
    yield
    try:
        from _app.rate_limit import reset_rate_limiters
        reset_rate_limiters()
    except Exception:
        pass
