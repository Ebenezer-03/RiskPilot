"""Vercel Python function entrypoint.

Vercel maps requests under /api/* to this file and hands the ASGI app
full control of routing beneath that mount point. The actual FastAPI
app lives in _app/ (kept as a package, not `app`, to avoid shadowing
Next.js's own `app/` directory in this same project).
"""

from _app.main import app  # noqa: F401
