"""Loads a small sample of real IEEE-CIS held-out-test-split rows into the
`transactions` table via record_from_ieee_cis_row(), demonstrating this
ticket's acceptance criterion that IEEE-CIS-derived and synthetic
transactions persist under the same schema. Not run automatically (needs
data/raw/ + requirements-train.txt, same as train.py) - a one-off,
reproducible demo/seed script, not part of the request-time path.

Run from apps/web/api:  python -m _app.ml.load_ieee_cis_sample [N]
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env.local")

from .. import db
from ..transactions import insert_transaction, record_from_ieee_cis_row
from .features import ALL_FEATURE_COLUMNS, ID_COLUMN, TARGET_COLUMN, add_derived_features, row_to_json_safe
from .train import load_data, time_ordered_split

DEFAULT_SAMPLE_SIZE = 25


def main(sample_size: int = DEFAULT_SAMPLE_SIZE) -> None:
    df = load_data()
    df = add_derived_features(df)
    _, _, test_df = time_ordered_split(df)
    sample = test_df.sample(n=sample_size, random_state=42)

    columns_needed = [ID_COLUMN, TARGET_COLUMN, *ALL_FEATURE_COLUMNS]
    with db.get_connection() as conn:
        db.ensure_schema(conn)
        inserted = 0
        for _, row in sample.iterrows():
            raw = row_to_json_safe(row[columns_needed])
            record = record_from_ieee_cis_row(raw)
            if insert_transaction(conn, record):
                inserted += 1

    print(f"Inserted {inserted}/{sample_size} IEEE-CIS-derived transactions (data_source=ieee_cis).")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_SIZE
    main(n)
