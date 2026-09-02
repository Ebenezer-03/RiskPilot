"""Shared glue for router modules. `db.py` itself stays framework-agnostic
(no FastAPI import), so the HTTPException mapping for "no database
configured" lives here instead, one place every router imports rather than
each re-writing the same try/except.
"""

from __future__ import annotations

import psycopg
from fastapi import HTTPException

from .. import db


def get_connection_or_503() -> psycopg.Connection:
    try:
        return db.get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
