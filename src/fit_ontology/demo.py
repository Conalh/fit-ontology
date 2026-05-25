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
from datetime import date, datetime, timedelta

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

    # Resolve the synthetic data path. The Path(__file__) fallback
    # works in editable installs (local dev) where __file__ lives
    # at <repo>/src/fit_ontology/demo.py — parents[2] is the repo
    # root, and data/synthetic is right there. In a non-editable
    # install (the Docker image, which does ``pip install .``),
    # __file__ moves into site-packages and parents[2] no longer
    # points anywhere useful. FIT_ONTOLOGY_SYNTHETIC_DATA_ROOT
    # overrides; the Dockerfile sets it to /app/data/synthetic.
    synth = Path(
        os.environ.get(
            "FIT_ONTOLOGY_SYNTHETIC_DATA_ROOT",
            str(Path(__file__).resolve().parents[2] / "data" / "synthetic"),
        )
    )
    if not synth.exists():
        # Demo data isn't bundled — silently skip. A deployment that
        # opted into demo mode but didn't ship the data files would
        # get an empty demo dashboard rather than a startup crash.
        # Log loud so the operator can spot the misconfiguration.
        import sys
        print(
            f"[fit_ontology.demo] WARNING: synthetic data not found at {synth} — "
            f"demo mode will return an empty roster. Set "
            f"FIT_ONTOLOGY_SYNTHETIC_DATA_ROOT or ship data/synthetic/ in the image.",
            file=sys.stderr,
        )
        return

    # Ensure the demo trainer row exists.
    if not get_trainer(con, DEMO_TRAINER_ID):
        insert_trainer(con, DEMO_TRAINER_ID, DEMO_TRAINER_EMAIL, DEMO_TRAINER_NAME)

    # Two-phase idempotence:
    #
    #   (a) clients/sessions/metrics: short-circuit if the demo
    #       trainer already has clients — these are bulk loads and
    #       re-running is expensive even when it's a no-op.
    #   (b) override history: re-check independently because earlier
    #       deploys seeded clients+sessions but not history (the
    #       history seeder landed later than demo mode itself). Those
    #       existing volumes need a backfill, not a full reseed.
    #
    # Combined into one ``seeded_clients`` flag rather than two
    # separate early returns so the operator log line below still
    # fires with accurate counts in both the fresh-seed and the
    # backfill-only paths.
    existing_clients_df = list_clients(con, DEMO_TRAINER_ID)
    seeded_clients = existing_clients_df.empty

    if seeded_clients:
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
        client_ids = clients_df["id"].tolist()
        sessions_count = len(sessions_df)
        metrics_count = sum(len(f) for f in metric_frames)
    else:
        # Backfill path: clients already exist from an earlier deploy.
        # Skip the heavy reloads, just feed the existing ids into the
        # history seeder. _seed_demo_history is itself idempotent
        # (per-client overrides-exist check) so the no-op case stays
        # cheap on every connect.
        client_ids = existing_clients_df["id"].tolist()
        sessions_count = 0
        metrics_count = 0

    # Synthesise ~4 weeks of past recommendations + trainer overrides
    # per client so the calibration page lands on real content (system-
    # vs-trainer agreement matrix, weekly trend, per-client breakdown,
    # tuning suggestions) instead of an empty-state placeholder. Without
    # this the demo's most data-rich screen is the most empty.
    history_n = _seed_demo_history(con, client_ids)

    # Record-keeping for the operator who tail-fs the logs on first
    # deploy: one line, not a stack of inserts. Stays out of audit
    # log because record_audit needs a trainer that performed an
    # action and "the seeder" isn't that. On the warm path (only
    # history backfill happened) sessions_count + metrics_count are
    # zero — the log line still fires so the operator sees the
    # backfill landed.
    if not seeded_clients and history_n == 0:
        # Nothing to do — fully-seeded warm boot. Skip the log noise.
        return

    import sys
    label = "Seeded" if seeded_clients else "Backfilled history for"
    print(
        f"[fit_ontology.demo] {label} {len(client_ids)} demo clients + "
        f"{sessions_count} sessions + "
        f"{metrics_count} metric rows + "
        f"{history_n} historical overrides "
        f"under {DEMO_TRAINER_ID} at {datetime.utcnow().isoformat()}Z",
        file=sys.stderr,
    )


def _seed_demo_history(con, client_ids: list[str]) -> int:
    """Generate 4 weeks of past recommendations + overrides per demo
    client so the calibration page has real content.

    Procedure: for each (client, week-back-N), filter metrics to
    "what was available at the end of that week," run the reasoning
    engine against that snapshot, persist the result with a stable
    ID, then synthesise a trainer override with believable
    accept/edit/reject probabilities tied to the verdict severity.

    Stability: every ID is deterministic on (client_id, week_of), so
    running the seed twice updates-in-place via INSERT OR REPLACE
    rather than duplicating. Action choice uses a seeded RNG keyed
    on the same tuple so trainer-A's decisions are identical from
    one boot to the next — the demo's calibration page shows the
    SAME agreement matrix every visit, not a fresh randomisation.

    Returns the number of (recommendation, override) pairs written.
    Short-circuits if any demo override already exists.
    """
    import random

    import pandas as pd

    from .db import (
        insert_override,
        insert_recommendation,
        metrics_for_client,
        overrides_for_client,
        sessions_for_client,
    )
    from .ontology import OverrideAction, RecommendationOverride
    from .reasoning import generate_recommendation

    today = date.today()
    pairs_written = 0

    for client_id in client_ids:
        # Skip if this client already has demo overrides — keeps the
        # seed idempotent even though the recommendation IDs would
        # INSERT-OR-REPLACE cleanly. Cheaper to check once than to
        # re-run the engine eight times for no net change.
        existing = overrides_for_client(con, DEMO_TRAINER_ID, client_id, limit=1)
        if not existing.empty:
            continue

        # Pull everything available; we'll filter per-week below.
        all_metrics = metrics_for_client(con, DEMO_TRAINER_ID, client_id, days=70)
        all_sessions = sessions_for_client(con, DEMO_TRAINER_ID, client_id, days=70)
        if all_metrics.empty:
            continue

        for weeks_back in (1, 2, 3, 4):
            # End-of-week-back Sunday is "what the trainer was deciding on
            # that Monday." Filter to data available at that point so the
            # historical recommendation is what the engine would have
            # produced in real time, not a hindsight reconstruction.
            historical_today = today - timedelta(days=weeks_back * 7)
            week_of = historical_today - timedelta(days=historical_today.weekday())

            # The metrics/sessions date columns come back as
            # datetime64[us] (pandas auto-promotes DuckDB DATE on
            # read), but ``historical_today`` is a python date — direct
            # comparison raises InvalidComparison. Normalise both
            # sides to pandas Timestamps to dodge that.
            cutoff = pd.Timestamp(historical_today)
            metrics_at = all_metrics[pd.to_datetime(all_metrics["date"]) <= cutoff]
            sessions_at = (
                all_sessions[pd.to_datetime(all_sessions["date"]) <= cutoff]
                if not all_sessions.empty
                else all_sessions
            )

            # Need at least ~14 days of HRV / sleep for the baseline-
            # window detectors to fire meaningfully. Fewer than that
            # and the recommendation defaults to a flat "Standard" with
            # low confidence — not interesting calibration content.
            if len(metrics_at) < 14:
                continue

            rec = generate_recommendation(client_id, metrics_at, sessions_at)
            # Stable IDs so the seed is genuinely idempotent + the
            # calibration page renders the same rows on every visit.
            rec.id = f"r_demo_{client_id}_{week_of.isoformat()}"
            rec.week_of = week_of
            # Monday-morning of the historical week is when the trainer
            # would have been reading this verdict. Time of day doesn't
            # matter; date does, for the weekly-trend chart.
            rec.generated_at = datetime.combine(week_of, datetime.min.time())
            insert_recommendation(con, DEMO_TRAINER_ID, rec)

            # Seeded RNG → stable trainer behaviour per (client, week).
            # The seed string includes the verdict text so a change to
            # the engine's wording (which would only happen with a real
            # threshold tweak) re-randomises in a controlled way.
            rng = random.Random(f"{client_id}|{week_of.isoformat()}|{rec.recommendation}")
            roll = rng.random()
            verdict_lower = rec.recommendation.lower()

            # Trainers usually agree with the system but disagree more
            # often on the louder calls — a deload week is the kind of
            # decision where the trainer has more reason to push back
            # ("client felt great"). Numbers chosen so the agreement
            # matrix has variety without painting an unrealistically
            # contentious picture.
            if verdict_lower.startswith("deload"):
                action = (
                    OverrideAction.ACCEPT if roll < 0.55
                    else OverrideAction.EDIT if roll < 0.85
                    else OverrideAction.REJECT
                )
            elif verdict_lower.startswith("conservative"):
                action = (
                    OverrideAction.ACCEPT if roll < 0.7
                    else OverrideAction.EDIT if roll < 0.9
                    else OverrideAction.REJECT
                )
            else:  # Standard / fallback
                action = (
                    OverrideAction.ACCEPT if roll < 0.85
                    else OverrideAction.EDIT if roll < 0.97
                    else OverrideAction.REJECT
                )

            note: str | None = None
            applied_pct: float | None = None
            if action == OverrideAction.EDIT:
                # Edits are usually small magnitude shifts: "more
                # conservative than the system said" or "less" by
                # 5-10%. Sign chosen by the next roll so edits split
                # both ways across the dataset.
                applied_pct = rng.choice([-10.0, -5.0, 5.0, 10.0])
            elif action == OverrideAction.REJECT:
                note = rng.choice([
                    "Client felt great this morning, kept training.",
                    "Travel week — skipping the deload, will deload next week.",
                    "Mid-meet block, holding intensity.",
                    "Sleep was off — went lighter than the system suggested.",
                    "Client missed last session anyway, no extra recovery needed.",
                ])

            ov = RecommendationOverride(
                id=f"o_demo_{client_id}_{week_of.isoformat()}",
                client_id=client_id,
                week_of=week_of,
                system_recommendation=rec.recommendation,
                system_confidence=rec.confidence,
                trainer_action=action,
                applied_load_change_pct=applied_pct,
                trainer_note=note,
                created_at=datetime.combine(week_of, datetime.min.time()),
            )
            insert_override(con, DEMO_TRAINER_ID, ov)
            pairs_written += 1

    return pairs_written
