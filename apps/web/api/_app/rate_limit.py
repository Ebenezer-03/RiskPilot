"""Basic per-client API rate limiting (ticket 13's reliability story).

A hand-rolled fixed-window counter, not a new dependency (slowapi/redis) -
this is deliberately the simplest thing that actually rejects abusive
traffic, not a distributed-systems rate limiter. It lives in this single
process's memory, so it's scoped per warm server instance:

- Local `uvicorn` / a single long-lived server: works exactly as written,
  one shared counter for the process's lifetime.
- Vercel Fluid Compute: instances are reused across concurrent requests
  (see the platform's own docs), so a warm instance still enforces its
  own limit correctly across requests it actually serves - it just isn't
  a *global* limit shared across every instance/region. A determined
  attacker distributing requests across many cold instances could evade
  it. Upgrading to a shared store (Upstash Redis via the Marketplace) is
  the natural next step if this ever needs to be attack-resistant rather
  than abuse-resistant; out of scope for this ticket.
"""

import time
from collections import defaultdict, deque

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# (max requests, window in seconds) per route prefix. /health is exempt -
# uptime monitors and the homepage's own live status indicator poll it
# and shouldn't be able to lock themselves out.
_DEFAULT_LIMIT = (120, 60)
_LIMITS: dict[str, tuple[int, int]] = {
    "/score": (30, 60),
    "/decide": (30, 60),
    "/simulation/replay": (10, 60),
    # Creates a real Razorpay order per call - rationed tighter than /score
    # or /decide, which only touch this app's own DB.
    "/razorpay/checkout": (10, 60),
}
_EXEMPT_PREFIXES = ("/health",)


def _client_ip(request: Request) -> str:
    """The real end-client IP, not the proxy's - this app is always reached
    through a single trusted hop (the Next.js /api/* rewrite in dev/Compose,
    Vercel's own edge in production), which sets X-Forwarded-For to the
    actual visitor's IP. Without this, every request arriving through that
    proxy would show request.client.host as the proxy's own IP, collapsing
    every distinct user behind it into one shared rate-limit bucket per
    route - trusting the *first* XFF entry (the client-added one, not
    anything a downstream hop could have appended) is standard practice for
    exactly one trusted hop like this."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _bucket_for(path: str) -> tuple[str, int, int]:
    """The matched prefix doubles as the counter's bucket key - two distinct
    routes under the same first path segment (/razorpay/checkout vs
    /razorpay/webhook) must not share one counter just because a naive
    `path.split("/")[1]` key would collapse them together."""
    for prefix, limit in _LIMITS.items():
        if path.startswith(prefix):
            return (prefix, *limit)
    return ("*", *_DEFAULT_LIMIT)


_active_instances: "list[RateLimitMiddleware]" = []


def reset_rate_limiters() -> None:
    for instance in _active_instances:
        instance.reset()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        # client_key -> deque of request timestamps within the current window.
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        _active_instances.append(self)

    def reset(self) -> None:
        self._hits.clear()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        bucket, max_requests, window_seconds = _bucket_for(path)
        client_ip = _client_ip(request)
        key = f"{client_ip}:{bucket}"

        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()

        if len(hits) >= max_requests:
            retry_after = max(1, int(window_seconds - (now - hits[0])))
            return Response(
                content=(
                    '{"detail":"Rate limit exceeded - '
                    f'max {max_requests} requests per {window_seconds}s on this endpoint. '
                    'Retry after the window resets."}'
                ),
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )

        hits.append(now)
        return await call_next(request)
