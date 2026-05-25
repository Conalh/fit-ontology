"""Pull an Apple Health Export into the ontology.

Usage:
    python scripts/import_apple_health.py path/to/export.zip [--client-id c_apple]

How to get the file:
    On the iPhone, open Health → tap your profile photo (top right) →
    scroll to "Export All Health Data" → tap. iOS produces an
    ``export.zip``; AirDrop or email it to the machine running
    FitOntology and point this script at it.

We surface HRV (SDNN), resting HR, and body composition. Sleep aggregates
require stage-level parsing across multiple <Record> rows per night and
are left for a future iteration; Garmin / Whoop already give us totals.

The script is idempotent — re-importing the same export is safe because
metrics carry stable per-row IDs and `INSERT OR REPLACE` is used at the
DB layer.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fit_ontology.db import DEFAULT_TRAINER_ID, connect, ensure_client, insert_metrics
from fit_ontology.ingest import from_apple_health_export


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", type=Path, help="Path to export.zip or export.xml from the iOS Health app.")
    parser.add_argument(
        "--client-id",
        default="c_apple",
        help="Client ID to attribute the metrics to (default: c_apple). "
        "Use an existing ID to merge with that client's data.",
    )
    parser.add_argument(
        "--client-name",
        default="Apple Health Self",
        help="Display name if the client row needs to be created.",
    )
    args = parser.parse_args()

    if not args.export.exists():
        print(f"File not found: {args.export}", file=sys.stderr)
        return 1

    print(f"Parsing {args.export} ...")
    metrics = from_apple_health_export(args.export, args.client_id)
    print(f"Extracted {len(metrics)} daily metric rows across {metrics['kind'].nunique()} signal kinds.")
    if metrics.empty:
        print("Nothing to insert — the export had no records of types we map.")
        return 0

    with connect(read_only=False) as con:
        ensure_client(con, DEFAULT_TRAINER_ID, args.client_id, name=args.client_name)
        insert_metrics(con, DEFAULT_TRAINER_ID, metrics)

    print("Done. Open the Streamlit dashboard to see the data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
