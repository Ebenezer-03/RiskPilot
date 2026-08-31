"""Transaction generation and lookup - ticket 04."""

from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException

from .. import db
from ..schemas import GenerateSyntheticRequest, TransactionRecord
from ..transactions import generate_synthetic_transaction, get_transaction, insert_transaction

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/synthetic", response_model=list[TransactionRecord])
async def generate_synthetic(payload: GenerateSyntheticRequest) -> list[TransactionRecord]:
    try:
        conn = db.get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    with conn:
        db.ensure_schema(conn)
        rng = random.Random()
        created: list[dict] = []
        for _ in range(payload.count):
            record = generate_synthetic_transaction(rng)
            insert_transaction(conn, record)
            created.append(get_transaction(conn, record["transaction_id"]))

    return [TransactionRecord(**row) for row in created]


@router.get("/{transaction_id}", response_model=TransactionRecord)
async def read_transaction(transaction_id: str) -> TransactionRecord:
    try:
        conn = db.get_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    with conn:
        row = get_transaction(conn, transaction_id)

    if row is None:
        raise HTTPException(status_code=404, detail=f"No transaction with id {transaction_id!r}")
    return TransactionRecord(**row)
