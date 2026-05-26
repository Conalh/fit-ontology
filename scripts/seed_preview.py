"""Seed the preview DB (``data/preview_test.duckdb``) with synthetic
clients under the default trainer.

Sister to ``scripts/build_db.py`` (which writes the production-shaped
``data/fit_ontology.duckdb``) and to ``fit_ontology.demo:_seed_demo_history``
(which seeds the demo-mode dataset under ``t_demo``). This script
exists because the local preview loop runs WITHOUT demo mode — so
the user's logged-in ``t_default`` session sees an empty roster
until something seeds it.

Idempotent. Safe to re-run; short-circuits when ``t_default``
already has clients. To force a fresh seed, delete
``data/preview_test.duckdb`` first.

Usage:
    python scripts/seed_preview.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Anchor the DB path the same way preview_serve.py does so this script
# can be run before the API server has booted.
REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault(
    "FIT_ONTOLOGY_DB", str(REPO_ROOT / "data" / "preview_test.duckdb")
)


def main() -> int:
    import pandas as pd

    from fit_ontology.db import (
        DEFAULT_DB_PATH,
        DEFAULT_TRAINER_ID,
        connect,
        ensure_client,
        insert_clients,
        insert_metrics,
        insert_sessions,
        list_clients,
    )
    from fit_ontology.ingest import (
        from_intake_csv,
        from_session_log_csv,
        from_strava_export,
        from_whoop_json,
    )

    synth = REPO_ROOT / "data" / "synthetic"
    if not synth.exists():
        print(f"synthetic data not found at {synth} — run scripts/generate_synthetic.py first")
        return 1

    with connect(DEFAULT_DB_PATH, read_only=False) as con:
        existing = list_clients(con, DEFAULT_TRAINER_ID)
        if not existing.empty:
            print(
                f"t_default already has {len(existing)} clients — short-circuiting. "
                f"Delete {DEFAULT_DB_PATH} to force a fresh seed."
            )
            return 0

        # Clients
        clients_df = from_intake_csv(synth / "clients.csv")
        insert_clients(con, DEFAULT_TRAINER_ID, clients_df)
        for client_id in clients_df["id"]:
            ensure_client(con, DEFAULT_TRAINER_ID, client_id)

        # Sessions
        sessions_df = from_session_log_csv(synth / "sessions.csv")
        insert_sessions(con, DEFAULT_TRAINER_ID, sessions_df)

        # Metrics
        metric_frames = []
        for client_id in clients_df["id"]:
            whoop_path = synth / f"whoop_{client_id}.json"
            strava_path = synth / f"strava_{client_id}.csv"
            if whoop_path.exists():
                metric_frames.append(from_whoop_json(whoop_path, client_id))
            if strava_path.exists():
                metric_frames.append(from_strava_export(strava_path, client_id))
        if metric_frames:
            all_metrics = pd.concat(metric_frames, ignore_index=True)
            insert_metrics(con, DEFAULT_TRAINER_ID, all_metrics)

        # History — 4 weeks of past recommendations + overrides so the
        # calibration page lands on real content. Reuses the demo
        # seeder's logic by calling it with t_default in place of
        # t_demo. The function references DEMO_TRAINER_ID internally
        # but only as a write target — we can monkeypatch for the
        # duration of the call to avoid duplicating ~150 lines of
        # backfill logic.
        from fit_ontology import demo as demo_mod

        client_ids = clients_df["id"].tolist()
        original_demo_id = demo_mod.DEMO_TRAINER_ID
        demo_mod.DEMO_TRAINER_ID = DEFAULT_TRAINER_ID
        try:
            n_history = demo_mod._seed_demo_history(con, client_ids)
        finally:
            demo_mod.DEMO_TRAINER_ID = original_demo_id

        print(
            f"Seeded {len(client_ids)} clients + "
            f"{len(sessions_df)} sessions + "
            f"{sum(len(f) for f in metric_frames)} metric rows + "
            f"{n_history} historical override pairs under {DEFAULT_TRAINER_ID}."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
