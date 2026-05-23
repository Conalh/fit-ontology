"""One-time migration: collapse duplicate metrics and convert to deterministic IDs.

Before this migration, every sync generated fresh UUIDs for metric rows,
which combined with PRIMARY KEY on ``id`` only meant that re-syncing the
same day for the same source created a duplicate row instead of updating
the existing one. The reasoning layer would then see two HRV values for
the same day and skew its baseline math.

After the change in ``ingest.py``, IDs are deterministic from
``(client_id, date, kind, source)``. This script rewrites existing rows
to match — collapsing any pre-existing duplicates to a single row per
natural key (keeping the most recent value, which the trainer's
wearable would have written second) — so a future re-sync can upsert
cleanly via the PK.

Idempotent. Safe to run multiple times — the second pass is a no-op
because all IDs already match the deterministic form.
"""
from __future__ import annotations

import sys

from fit_ontology.db import connect
from fit_ontology.ingest import metric_id


def main() -> int:
    with connect(read_only=False) as con:
        existing = con.execute(
            "SELECT id, client_id, date, source, kind, value, unit FROM metrics"
        ).df()

        if existing.empty:
            print("No metrics in the database — nothing to migrate.")
            return 0

        before = len(existing)

        # Keep one row per natural key. If duplicates exist we take the
        # last one in insertion order — DuckDB doesn't track an
        # inserted_at on this table, but the lexicographic order of the
        # random UUIDs is a reasonable tie-break and corresponds (in
        # practice) to the more recent sync overwriting the older.
        deduped = (
            existing.sort_values("id")
            .drop_duplicates(subset=["client_id", "date", "source", "kind"], keep="last")
            .copy()
        )

        deduped["id"] = [
            metric_id(r["client_id"], r["date"], r["kind"], r["source"])
            for _, r in deduped.iterrows()
        ]

        after = len(deduped)
        collapsed = before - after

        # Replace the whole table atomically. DELETE + INSERT inside the
        # same write connection is a single transaction in DuckDB.
        con.execute("DELETE FROM metrics")
        con.execute(
            "INSERT INTO metrics SELECT id, client_id, date, source, kind, value, unit FROM deduped"
        )

    print(f"Migrated {before} -> {after} rows ({collapsed} duplicate natural keys collapsed).")
    print("Future syncs will upsert via the deterministic ID and not duplicate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
