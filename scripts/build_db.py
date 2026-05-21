"""Build the DuckDB from the synthetic CSVs and JSONs."""
from __future__ import annotations

import sys
from pathlib import Path

# Make src importable when running as `python scripts/build_db.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from fit_ontology.db import connect, insert_clients, insert_metrics, insert_sessions
from fit_ontology.ingest import (
    from_intake_csv,
    from_session_log_csv,
    from_strava_export,
    from_whoop_json,
)

SYNTH = Path("data/synthetic")


def main() -> None:
    con = connect()

    clients = from_intake_csv(SYNTH / "clients.csv")
    insert_clients(con, clients)
    print(f"Loaded {len(clients)} clients.")

    sessions = from_session_log_csv(SYNTH / "sessions.csv")
    insert_sessions(con, sessions)
    print(f"Loaded {len(sessions)} sessions.")

    all_metrics = []
    for cid in ("c_alice", "c_ben", "c_carla"):
        whoop = from_whoop_json(SYNTH / f"whoop_{cid}.json", cid)
        strava = from_strava_export(SYNTH / f"strava_{cid}.csv", cid)
        all_metrics.extend([whoop, strava])
    metrics_df = pd.concat(all_metrics, ignore_index=True)
    insert_metrics(con, metrics_df)
    print(f"Loaded {len(metrics_df)} metric rows.")

    con.close()
    print("Database ready: data/fit_ontology.duckdb")


if __name__ == "__main__":
    main()
