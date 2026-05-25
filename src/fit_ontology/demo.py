"""Public demo mode (Phase 4).

Module exports:
  - DEMO_TRAINER_ID, DEMO_TRAINER_EMAIL, DEMO_TRAINER_NAME
  - is_demo_enabled() — env-var check
  - is_demo_trainer(trainer_id) — id comparison
  - seed_demo_data_if_needed(con) — idempotent first-boot seed


A hosted deployment of FitOntology has a chicken-and-egg problem for
a portfolio audience: the dashboard's interesting only when it has
real clients + wearable data + history to reason over, but a reviewer
who lands on /login with no account has no way to see any of that.

Demo mode is the answer. When ``FIT_ONTOLOGY_DEMO_MODE=1`` is set on
the deployment:

  1. On first connect() with an empty database, the synthetic dataset
     (data/synthetic/*) is loaded under a dedicated ``t_demo``
     trainer. Three clients, ~40 days of HRV / sleep / RHR, a couple
     dozen sessions each, a pre-computed current-week recommendation
     and weekly plan per client.

  2. An unauthenticated visitor's ``current_trainer_id`` resolves to
     ``t_demo`` instead of 401-ing — they get the full dashboard,
     scoped to demo data, with no login required. This explicitly
     overrides ``FIT_ONTOLOGY_REQUIRE_AUTH`` for the demo scope only;
     a logged-in trainer still gets their own data.

  3. Every mutating endpoint refuses writes from the demo trainer
     with HTTP 403 and a "Demo mode — read-only. Run locally to save
     changes." message. Enforcement lives in the
     ``forbid_demo_trainer`` FastAPI dependency in routes/deps.py
     (route-level) AND ``_assert_clients_owned`` keeps working at
     the db layer, so a demo visitor cannot land any write — period.

  4. Lazy-persist GET endpoints (recommendation, plan) skip their
     persistence branch when serving the demo trainer, since the
     demo data already has those rows pre-seeded. This avoids
     hitting the writer lock on every visitor's first page-load and
     keeps the demo trainer's data stable across visits.

What ``DEMO_MODE`` is NOT: a per-user sandbox. Every demo visitor
sees the SAME demo trainer's data; their UI clicks "succeed" only
in the sense that the read-side renders, write-side returns 403.
A future iteration could give each visitor their own ephemeral
session-scoped sandbox, but that's significantly more plumbing
(per-session DB views, periodic cleanup) for the same portfolio-
signal value.
"""
from __future__ import annotations

import os

# The demo trainer's id is deliberately distinct from DEFAULT_TRAINER_ID
# ("t_default") so a deployment can have both: a real trainer the
# operator logs in as, and a demo trainer the public sees when no
# cookie is present.
DEMO_TRAINER_ID = "t_demo"
DEMO_TRAINER_EMAIL = "demo@fitontology.app"
DEMO_TRAINER_NAME = "Demo Trainer"


def is_demo_enabled() -> bool:
    """True iff the deployment opted into public demo mode.

    Read at call time (not module import) so a test can monkey-patch
    the env var and see the flip without reloading.
    """
    return os.environ.get("FIT_ONTOLOGY_DEMO_MODE", "").strip() in {"1", "true", "yes"}


def is_demo_trainer(trainer_id: str | None) -> bool:
    """True iff ``trainer_id`` is the demo trainer. Centralized so
    every write-gate uses the same comparison — a future change to
    use a different id (or multiple demo trainers per region) is one
    edit here."""
    return trainer_id == DEMO_TRAINER_ID


def seed_demo_data_if_needed(con) -> None:
    """Idempotently load the synthetic dataset under the demo trainer.

    Runs on every connect()-with-write but short-circuits cheaply
    when the demo trainer already has clients — so the cost on a
    warm DB is one SELECT COUNT(*).

    The dataset:
      - 3 clients (Alice, Ben, Carla) with intake details that
        exercise the contraindications system (lumbar history,
        knee injury, hypertension medication)
      - 28+ days of HRV / sleep / RHR per client from Whoop + Strava
        synthetic exports
      - A handful of recent strength + cardio sessions per client

    What we deliberately do NOT pre-compute here:
      - Weekly recommendations — generated lazily by /recommendation,
        but the demo-trainer scope skips persistence so each visitor
        gets a fresh compute against the same data without polluting
        the audit log
      - Plans — same shape

    Why not just run scripts/build_db.py: that script writes under
    DEFAULT_TRAINER_ID and dumps to stdout. We need control over
    the trainer scope + no logging when the seed already happened.
    Reuses the ingest helpers it calls.
    """
    from datetime import datetime
    from pathlib import Path

    import pandas as pd

    from .db import (
        ensure_client,
        get_trainer,
        insert_clients,
        insert_metrics,
        insert_sessions,
        insert_trainer,
        list_clients,
    )
    from .ingest import (
        from_intake_csv,
        from_session_log_csv,
        from_strava_export,
        from_whoop_json,
    )

    # Resolve the synthetic data path the same way db.py anchors the
    # default DB path: relative to the repo root, not the cwd. Lets
    # the seed work whether the process starts from /app, /, or
    # somewhere weird inside Docker.
    repo_root = Path(__file__).resolve().parents[2]
    synth = repo_root / "data" / "synthetic"
    if not synth.exists():
        # Demo data isn't bundled — silently skip. A deployment that
        # opted into demo mode but didn't ship the data files would
        # get an empty demo dashboard rather than a startup crash.
        return

    # Ensure the demo trainer row exists.
    if not get_trainer(con, DEMO_TRAINER_ID):
        insert_trainer(con, DEMO_TRAINER_ID, DEMO_TRAINER_EMAIL, DEMO_TRAINER_NAME)

    # Short-circuit: if the demo trainer already has clients, the
    # seed already ran. Idempotent — safe on every connect().
    if not list_clients(con, DEMO_TRAINER_ID).empty:
        return

    # Clients — load the intake CSV, then stamp it onto the demo
    # trainer via insert_clients (which adds the trainer_id column
    # to the df before INSERT OR REPLACE).
    clients_df = from_intake_csv(synth / "clients.csv")
    insert_clients(con, DEMO_TRAINER_ID, clients_df)

    # Sessions — same shape. ensure_client first so the FK passes
    # (insert_clients already created the rows, but the FK check is
    # belt-and-suspenders against a partial seed).
    for client_id in clients_df["id"]:
        ensure_client(con, DEMO_TRAINER_ID, client_id)

    sessions_df = from_session_log_csv(synth / "sessions.csv")
    insert_sessions(con, DEMO_TRAINER_ID, sessions_df)

    # Metrics — one Whoop + one Strava per client. Iterate the
    # client_id column rather than hardcoding so adding a fourth
    # synthetic client doesn't require touching this code.
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
        insert_metrics(con, DEMO_TRAINER_ID, all_metrics)

    # Record-keeping for the operator who tail-fs the logs on first
    # deploy: one line, not a stack of inserts. Stays out of audit
    # log because record_audit needs a trainer that performed an
    # action and "the seeder" isn't that.
    import sys
    print(
        f"[fit_ontology.demo] Seeded {len(clients_df)} demo clients + "
        f"{len(sessions_df)} sessions + "
        f"{sum(len(f) for f in metric_frames)} metric rows "
        f"under {DEMO_TRAINER_ID} at {datetime.utcnow().isoformat()}Z",
        file=sys.stderr,
    )
