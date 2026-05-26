"""DuckDB persistence layer."""
from __future__ import annotations

import json
import os
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import bcrypt
import duckdb
import pandas as pd

from .ontology import SCHEMA_DDL

# Anchor the DB path to the repo root rather than the caller's working
# directory. Previously this was a bare ``Path("data/...")``, which meant
# launching ``fit-ontology-serve`` from a different folder silently
# created a fresh empty DB at the wrong location (DuckDB write-mode
# happily creates a missing file). Now the path resolves the same
# regardless of cwd. The env var ``FIT_ONTOLOGY_DB`` overrides for
# Docker / custom deployments that store the DB elsewhere.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = Path(
    os.environ.get("FIT_ONTOLOGY_DB", str(_PACKAGE_ROOT / "data" / "fit_ontology.duckdb"))
)


# ─── Phase 2a default trainer ────────────────────────────────────────
#
# Until real auth lands in Phase 2b, every request resolves to this
# single trainer via the ``current_trainer_id`` FastAPI dependency,
# and the migration assigns every pre-existing row to this id. The
# email matches Conal's, so when SSO arrives in Phase 2b the row can
# be linked to the real Google identity by email lookup rather than
# needing a re-key. Override via the ``FIT_ONTOLOGY_DEFAULT_TRAINER_*``
# env vars if a deployment seeds a different default.
DEFAULT_TRAINER_ID = os.environ.get("FIT_ONTOLOGY_DEFAULT_TRAINER_ID", "t_default")
DEFAULT_TRAINER_EMAIL = os.environ.get(
    "FIT_ONTOLOGY_DEFAULT_TRAINER_EMAIL", "conal.hg@gmail.com"
)
DEFAULT_TRAINER_NAME = os.environ.get("FIT_ONTOLOGY_DEFAULT_TRAINER_NAME", "Conal")


def connect(db_path: Path = DEFAULT_DB_PATH, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection. DuckDB allows only one writer per file
    across processes, so the dashboard should pass ``read_only=True`` to
    coexist with a concurrent sync script. The schema DDL + migrations
    are skipped in read-only mode (the file must already exist, which
    is fine for a dashboard that only renders existing data)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if read_only and not db_path.exists():
        # Read-only against a missing file would be misleading; let the
        # caller create+seed the DB first via a normal connect.
        raise FileNotFoundError(f"DuckDB file not found for read-only open: {db_path}")
    con = duckdb.connect(str(db_path), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA_DDL)
        _run_migrations(con)
        # Local import keeps demo.py optional: the module's own
        # is_demo_enabled() check is the gate, so a deployment that
        # doesn't opt into demo mode pays one env-var lookup and exits.
        from .demo import is_demo_enabled, seed_demo_data_if_needed
        if is_demo_enabled():
            seed_demo_data_if_needed(con)
    return con


def _run_migrations(con: duckdb.DuckDBPyConnection) -> None:
    """Idempotent data migrations that complement SCHEMA_DDL.

    SCHEMA_DDL handles structure (CREATE TABLE / ALTER ADD COLUMN /
    CREATE INDEX, all guarded by IF NOT EXISTS so a re-run is a
    no-op). This function handles *data* steps that DDL can't express
    — currently just the Phase 2a multi-tenant backfill:

    1. Seed the default trainer row if no trainer exists. We don't
       INSERT-OR-IGNORE on a specific id because a deployment may
       have overridden ``DEFAULT_TRAINER_ID``; the right invariant
       is "there is at least one trainer," not "this exact id exists."
    2. Backfill ``trainer_id`` on every client-data table where it's
       still NULL (i.e. rows that predate Phase 2a). Assign them all
       to the default trainer so the single-trainer dashboard keeps
       rendering exactly the same data after the migration.

    Both steps are safe to re-run: step 1 short-circuits if a trainer
    already exists, step 2's WHERE filters to NULL-only rows.
    """
    # Step 1: ensure at least one trainer exists.
    existing = con.execute("SELECT COUNT(*) FROM trainers").fetchone()
    if existing and existing[0] == 0:
        con.execute(
            """
            INSERT INTO trainers (id, email, name, hashed_password, created_at)
            VALUES (?, ?, ?, NULL, ?)
            """,
            [DEFAULT_TRAINER_ID, DEFAULT_TRAINER_EMAIL, DEFAULT_TRAINER_NAME, datetime.utcnow()],
        )

    # Step 1b (Phase 2b-α): seed the default trainer's password from
    # FIT_ONTOLOGY_DEFAULT_TRAINER_PASSWORD if (and only if) the row
    # currently has no hash. Lets a deployment set the bootstrap
    # password once via env var without re-applying it on every restart
    # (which would let an operator who lost the env var lock themselves
    # out). To rotate, clear the env var, set a new value, restart.
    bootstrap_pw = os.environ.get("FIT_ONTOLOGY_DEFAULT_TRAINER_PASSWORD", "").strip()
    if bootstrap_pw:
        row = con.execute(
            "SELECT id, hashed_password FROM trainers WHERE id = ?",
            [DEFAULT_TRAINER_ID],
        ).fetchone()
        if row and not row[1]:
            con.execute(
                "UPDATE trainers SET hashed_password = ? WHERE id = ?",
                [_hash_password(bootstrap_pw), DEFAULT_TRAINER_ID],
            )

    # Step 2: resolve which trainer to assign legacy rows to. If a
    # deployment-supplied DEFAULT_TRAINER_ID matches an existing row,
    # use it; otherwise fall back to whichever trainer is in the
    # table (one-trainer assumption holds during Phase 2a). This
    # protects against an env-var change that doesn't match the
    # seeded row.
    target = con.execute(
        "SELECT id FROM trainers WHERE id = ? LIMIT 1", [DEFAULT_TRAINER_ID]
    ).fetchone()
    if not target:
        target = con.execute("SELECT id FROM trainers LIMIT 1").fetchone()
    if not target:
        # No trainers at all — nothing to backfill against, and a
        # NULL backfill would defeat the purpose. Bail silently;
        # the next connect() (with the env var aligned) will fix it.
        return
    backfill_id = target[0]

    for table in (
        "clients",
        "sessions",
        "metrics",
        "recommendations",
        "recommendation_overrides",
        "planned_sessions",
        "client_thresholds",
    ):
        con.execute(
            f"UPDATE {table} SET trainer_id = ? WHERE trainer_id IS NULL",
            [backfill_id],
        )


# ─── Password hashing (Phase 2b-α) ───────────────────────────────────
#
# bcrypt directly rather than via passlib — passlib 1.7.4's bcrypt
# loader broke against bcrypt 5.x (missing ``__about__``), and bcrypt's
# bare API is small enough that the abstraction wasn't earning its
# place. Cost factor 12 is the bcrypt default in 4.x+ and the right
# balance for an interactive login (a few hundred ms on a modern CPU).


def _hash_password(plaintext: str) -> str:
    """Return a bcrypt hash suitable for storage in trainers.hashed_password.

    bcrypt operates on bytes and silently truncates at 72; we strip and
    cap here so a paste with a trailing newline or an unusually long
    passphrase produces the same hash on every run rather than
    different ones depending on what fell off the end.
    """
    pw_bytes = plaintext.strip().encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def _verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time comparison of a candidate password against the
    stored hash. Returns False (rather than raising) on a malformed
    hash so the login route can give a uniform 401."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(
            plaintext.strip().encode("utf-8")[:72],
            hashed.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


# ─── Trainer-scoped helpers ───────────────────────────────────────────
#
# Every helper that reads or writes client-data takes ``trainer_id`` as
# the FIRST data argument after ``con``. This is the chokepoint that
# enforces multi-tenant isolation (roadmap Phase 2a): route code can't
# accidentally leak across trainers because there is no helper that
# operates without a trainer_id. Reads add a ``WHERE trainer_id = ?``
# filter on the outermost query; writes persist trainer_id alongside
# the row. Trainer-scoping is composed with client-scoping rather than
# replacing it — a request for client X's metrics still filters on
# client_id; the trainer_id gate just ensures client X actually belongs
# to the calling trainer.


def _assert_clients_owned(con, trainer_id: str, client_ids) -> None:
    """Raise if any client_id does not belong to trainer_id.

    DuckDB foreign keys only know that ``clients.id`` exists; they do not
    know that a child row's ``trainer_id`` matches the owning client row.
    Every client-data write calls this guard before inserting so a leaked
    client_id cannot create rows under the wrong trainer scope.
    """
    ids = sorted({str(cid) for cid in client_ids if cid is not None})
    if not ids:
        return
    placeholders = ", ".join("?" for _ in ids)
    rows = con.execute(
        f"""
        SELECT id FROM clients
        WHERE trainer_id = ? AND id IN ({placeholders})
        """,
        [trainer_id, *ids],
    ).fetchall()
    owned = {row[0] for row in rows}
    missing = [cid for cid in ids if cid not in owned]
    if missing:
        target = missing[0] if len(missing) == 1 else ", ".join(missing)
        raise ValueError(f"No client with id {target}")


def get_trainer_by_email(con, email: str):
    """Return (id, email, name, created_at) for an existing trainer, or None."""
    return con.execute(
        "SELECT id, email, name, created_at FROM trainers WHERE email = ?",
        [email],
    ).fetchone()


def get_trainer(con, trainer_id: str):
    """Return (id, email, name, created_at) for a trainer, or None."""
    return con.execute(
        "SELECT id, email, name, created_at FROM trainers WHERE id = ?",
        [trainer_id],
    ).fetchone()


def insert_trainer(con, trainer_id: str, email: str, name: str,
                   hashed_password: str | None = None) -> None:
    """Create a trainer row. Used by tests and by the eventual sign-up
    flow in Phase 2b. The default trainer is seeded by _run_migrations()
    on first connect; this helper is for additional trainers."""
    con.execute(
        """
        INSERT INTO trainers (id, email, name, hashed_password, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        [trainer_id, email, name, hashed_password, datetime.utcnow()],
    )


def set_trainer_password(con, trainer_id: str, plaintext: str) -> None:
    """Hash and store a new password for ``trainer_id``. Used by the
    sign-up flow and by tests; the migration seeds the default
    trainer's bootstrap password through a different path."""
    con.execute(
        "UPDATE trainers SET hashed_password = ? WHERE id = ?",
        [_hash_password(plaintext), trainer_id],
    )


def verify_trainer_login(con, email: str, plaintext: str) -> str | None:
    """Return the trainer's id on a successful email+password match, or
    None on any failure (unknown email, no password set, wrong
    password). The single bool result keeps timing/error shape uniform
    so the login route can return one 401 for every failure mode
    without leaking which one occurred."""
    row = con.execute(
        "SELECT id, hashed_password FROM trainers WHERE email = ?",
        [email.strip().lower()] if "@" in email else [email.strip()],
    ).fetchone()
    if not row:
        # Run a dummy verify against a fixed hash so an attacker can't
        # time the difference between "no such email" and "wrong
        # password." The hash here is for the string "x" — irrelevant.
        _verify_password(plaintext, "$2b$12$AbcdefghijklmnopqrstuOZJjMz4uHJlBjzy/0Z6E3W5cFvKZqcVe")
        return None
    trainer_id, hashed = row
    if _verify_password(plaintext, hashed):
        return trainer_id
    return None


def insert_clients(con, trainer_id: str, df: pd.DataFrame) -> None:
    """Bulk insert of clients for one trainer. The helper stamps the
    trainer_id column onto the df before write so a caller that forgot
    to set it still produces correctly-scoped rows — the whole point of
    routing every write through this layer."""
    df = df.copy()
    df["trainer_id"] = trainer_id
    con.execute("INSERT OR REPLACE INTO clients SELECT * FROM df")


def ensure_client(con, trainer_id: str, client_id: str,
                  name: str = "Self", sex: str = "other") -> None:
    """
    Idempotently create a stub client row so foreign-key constraints on
    metrics/sessions don't reject a fresh sync against a brand-new client_id.
    The trainer can edit the row later via SQL or a future Streamlit form;
    we just need a valid parent here. Scoped by ``trainer_id`` so two
    trainers can both have a client called "Self" without collision.
    """
    existing = con.execute(
        "SELECT 1 FROM clients WHERE id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    ).fetchone()
    if existing:
        return
    con.execute(
        """
        INSERT INTO clients
          (id, trainer_id, name, sex, age, height_cm, weight_kg, goal, injury_history, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        [client_id, trainer_id, name, sex, 30, 170.0, 70.0, "(self)", None],
    )


def delete_client_cascade(con, trainer_id: str, client_id: str) -> dict | None:
    """Hard-delete a client and every row that FK-references them.

    Returns the deleted client's snapshot (id, name) so the route layer
    can audit-log the name even though the row is gone after this
    call. Returns None if the client doesn't exist OR doesn't belong
    to ``trainer_id`` — same shape as a missing-client lookup, so the
    route can map None → 404.

    DuckDB enforces foreign-key constraints strictly: deleting a
    client while sessions/metrics/etc still reference it raises
    ConstraintException. Deletes have to walk the dependent tables
    first, in roughly reverse-FK-depth order. Caller is expected to
    wrap this in a single ``with connect(..., read_only=False)``
    context — every statement here lands on the same connection so
    DuckDB's per-file writer lock serialises them naturally; an
    explicit BEGIN TRANSACTION around the lot would be ideal but the
    DuckDB Python connector's transaction handling is inconsistent
    across versions, and the per-connection serialisation gets us
    the same partial-write protection in practice.

    The ``client_intake_tokens`` table is special-cased: its
    ``consumed_client_id`` is a stamp that records "this token
    submitted into client X" rather than a structural FK, so we
    NULL it out rather than dropping the historical mint event —
    the trainer still wants to be able to answer "did this intake
    URL get used?" after the resulting client was deleted.
    """
    # Ownership-and-existence check + capture the name for the audit
    # log before we lose the row.
    row = con.execute(
        "SELECT id, name FROM clients WHERE id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    ).fetchone()
    if not row:
        return None
    snapshot = {"id": row[0], "name": row[1]}

    # Order matters — leaf rows first so each DELETE's FK targets are
    # all unreferenced before it runs. Intake tokens' consumed_client_id
    # is NULL'd rather than deleted (see docstring).
    con.execute(
        "UPDATE client_intake_tokens SET consumed_client_id = NULL "
        "WHERE consumed_client_id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    )
    for table in (
        "client_share_tokens",
        "client_thresholds",
        "planned_sessions",
        "recommendation_overrides",
        "recommendations",
        "metrics",
        "sessions",
    ):
        con.execute(
            f"DELETE FROM {table} WHERE client_id = ? AND trainer_id = ?",
            [client_id, trainer_id],
        )
    # Finally the parent row itself.
    con.execute(
        "DELETE FROM clients WHERE id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    )
    return snapshot


def insert_client_from_payload(con, trainer_id: str, payload) -> str:
    """Insert one client row from a ``ClientCreate``-shaped payload and
    return the generated id.

    Extracted from ``routes/clients.py:post_client`` so both the
    authed POST /api/clients route and the public intake-submit route
    (Phase 3b) share one INSERT chokepoint. Audit logging stays at
    the route layer because the action name differs by entry point
    (``client.created`` for the authed UI, ``intake.submitted`` for
    a token-bound public submission).

    ``payload`` is duck-typed on the attribute names the existing
    ClientCreate model exposes (name / sex / age / height_cm /
    weight_kg / goal / injury_history). ``sex`` may be a Sex enum or
    a raw string — we normalize to .value so the column stays
    VARCHAR-shaped regardless of where the call came from.
    """
    client_id = f"c_{uuid.uuid4().hex[:12]}"
    sex_value = payload.sex.value if hasattr(payload.sex, "value") else payload.sex
    con.execute(
        """
        INSERT INTO clients
          (id, trainer_id, name, sex, age, height_cm, weight_kg, goal, injury_history, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        [
            client_id,
            trainer_id,
            payload.name,
            sex_value,
            payload.age,
            payload.height_cm,
            payload.weight_kg,
            payload.goal,
            payload.injury_history,
        ],
    )
    return client_id


def insert_sessions(con, trainer_id: str, df: pd.DataFrame) -> None:
    """Bulk insert of sessions for one trainer. See ``insert_clients``
    for the trainer_id stamping rationale."""
    df = df.copy()
    _assert_clients_owned(con, trainer_id, df["client_id"].unique().tolist())
    df["trainer_id"] = trainer_id
    con.execute("INSERT OR REPLACE INTO sessions SELECT * FROM df")


def insert_metrics(con, trainer_id: str, df: pd.DataFrame) -> None:
    """Bulk insert of metrics for one trainer. See ``insert_clients``
    for the trainer_id stamping rationale."""
    df = df.copy()
    _assert_clients_owned(con, trainer_id, df["client_id"].unique().tolist())
    df["trainer_id"] = trainer_id
    con.execute("INSERT OR REPLACE INTO metrics SELECT * FROM df")


def insert_recommendation(con, trainer_id: str, rec) -> None:
    _assert_clients_owned(con, trainer_id, [rec.client_id])
    con.execute(
        """
        INSERT OR REPLACE INTO recommendations
          (id, client_id, generated_at, week_of, recommendation, rationale,
           source_metric_ids, confidence, trainer_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            rec.id,
            rec.client_id,
            rec.generated_at,
            rec.week_of,
            rec.recommendation,
            rec.rationale,
            json.dumps(rec.source_metric_ids),
            rec.confidence,
            trainer_id,
        ],
    )


def list_clients(con, trainer_id: str) -> pd.DataFrame:
    """Roster view: every client this trainer owns. The trainer_id
    filter is the multi-tenant gate — without it the dashboard would
    list every trainer's clients."""
    return con.execute(
        "SELECT id, name, goal FROM clients WHERE trainer_id = ? ORDER BY name",
        [trainer_id],
    ).df()


def metrics_for_client(con, trainer_id: str, client_id: str, days: int = 14) -> pd.DataFrame:
    """Metrics for one client. Filters on both trainer_id and client_id:
    the trainer_id gate prevents trainer B from reading trainer A's
    metrics even if they happened to know the client_id."""
    return con.execute(
        f"""
        SELECT date, source, kind, value, unit, id
        FROM metrics
        WHERE trainer_id = ?
          AND client_id = ?
          AND date >= CURRENT_DATE - INTERVAL '{days}' DAY
        ORDER BY date
        """,
        [trainer_id, client_id],
    ).df()


def sessions_for_client(con, trainer_id: str, client_id: str, days: int = 14) -> pd.DataFrame:
    """Include the session ``id`` in the result so reasoning signals that
    derive from sessions (ACWR, RPE drift) can attach source IDs to
    their output — closing the same audit-trail loop the metrics-based
    signals already have."""
    return con.execute(
        f"""
        SELECT id, date, type, duration_min, rpe, notes
        FROM sessions
        WHERE trainer_id = ?
          AND client_id = ?
          AND date >= CURRENT_DATE - INTERVAL '{days}' DAY
        ORDER BY date
        """,
        [trainer_id, client_id],
    ).df()


def latest_recommendation(con, trainer_id: str, client_id: str) -> pd.DataFrame:
    return con.execute(
        """
        SELECT recommendation, rationale, source_metric_ids, confidence, generated_at, week_of
        FROM recommendations
        WHERE trainer_id = ? AND client_id = ?
        ORDER BY generated_at DESC
        LIMIT 1
        """,
        [trainer_id, client_id],
    ).df()


def recommendation_for_week(con, trainer_id: str, client_id: str, week_of):
    """Return the stored Recommendation for this (trainer, client, week)
    or None. Hydrates the JSON source_metric_ids back into a list, so
    callers get the same shape ``generate_recommendation`` produces in
    memory."""
    from .ontology import Recommendation

    row = con.execute(
        """
        SELECT id, client_id, generated_at, week_of, recommendation, rationale,
               source_metric_ids, confidence
        FROM recommendations
        WHERE trainer_id = ? AND client_id = ? AND week_of = ?
        LIMIT 1
        """,
        [trainer_id, client_id, week_of],
    ).fetchone()
    if not row:
        return None
    rid, cid, gen_at, woek, rec_text, rat, source_json, conf = row
    return Recommendation(
        id=rid,
        client_id=cid,
        generated_at=gen_at,
        week_of=woek,
        recommendation=rec_text,
        rationale=rat,
        source_metric_ids=json.loads(source_json) if source_json else [],
        confidence=float(conf),
    )


def recommendations_for_client(con, trainer_id: str, client_id: str, limit: int = 12) -> pd.DataFrame:
    """All stored weekly recommendations for a client, newest first.
    Drives the history view on the detail page."""
    return con.execute(
        """
        SELECT id, client_id, week_of, recommendation, rationale,
               source_metric_ids, confidence, generated_at
        FROM recommendations
        WHERE trainer_id = ? AND client_id = ?
        ORDER BY week_of DESC
        LIMIT ?
        """,
        [trainer_id, client_id, limit],
    ).df()


# ─── Trainer overrides ────────────────────────────────────────────────
#
# A read-only DuckDB connection cannot create tables, so a DB that
# predates the override schema will error on the first SELECT. We catch
# the missing-table case and return empty results; the table appears the
# first time an override is written (which opens write mode, where the
# IF NOT EXISTS DDL runs as part of connect()).

def insert_override(con, trainer_id: str, ov) -> None:
    _assert_clients_owned(con, trainer_id, [ov.client_id])
    con.execute(
        """
        INSERT INTO recommendation_overrides
        (id, client_id, week_of, system_recommendation, system_confidence,
         trainer_action, applied_load_change_pct, trainer_note, created_at, trainer_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ov.id,
            ov.client_id,
            ov.week_of,
            ov.system_recommendation,
            ov.system_confidence,
            ov.trainer_action.value,
            ov.applied_load_change_pct,
            ov.trainer_note,
            ov.created_at,
            trainer_id,
        ],
    )


def _empty_overrides_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "id",
            "client_id",
            "week_of",
            "system_recommendation",
            "system_confidence",
            "trainer_action",
            "applied_load_change_pct",
            "trainer_note",
            "created_at",
        ]
    )


def overrides_for_client(con, trainer_id: str, client_id: str, limit: int = 50) -> pd.DataFrame:
    """All overrides for a client, newest first. Empty if the table
    doesn't exist yet (pre-migration DB)."""
    try:
        return con.execute(
            """
            SELECT id, client_id, week_of, system_recommendation, system_confidence,
                   trainer_action, applied_load_change_pct, trainer_note, created_at
            FROM recommendation_overrides
            WHERE trainer_id = ? AND client_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [trainer_id, client_id, limit],
        ).df()
    except duckdb.CatalogException:
        return _empty_overrides_df()


def latest_override_for_week(con, trainer_id: str, client_id: str, week_of) -> pd.DataFrame:
    """The most recent override for (trainer, client, week), or empty."""
    try:
        return con.execute(
            """
            SELECT id, client_id, week_of, system_recommendation, system_confidence,
                   trainer_action, applied_load_change_pct, trainer_note, created_at
            FROM recommendation_overrides
            WHERE trainer_id = ? AND client_id = ? AND week_of = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [trainer_id, client_id, week_of],
        ).df()
    except duckdb.CatalogException:
        return _empty_overrides_df()


# ─── Per-client thresholds ────────────────────────────────────────────
#
# Sparse-table model: a stored row means the trainer explicitly
# overrode that threshold for this client; absence means use the
# population default from reasoning.DEFAULT_THRESHOLDS. Reads tolerate
# a missing table for pre-migration DBs.

def thresholds_for_client(con, trainer_id: str, client_id: str) -> dict[str, float]:
    try:
        rows = con.execute(
            "SELECT name, value FROM client_thresholds WHERE trainer_id = ? AND client_id = ?",
            [trainer_id, client_id],
        ).fetchall()
        return {name: float(value) for name, value in rows}
    except duckdb.CatalogException:
        return {}


def upsert_threshold(con, trainer_id: str, client_id: str, name: str, value: float) -> None:
    _assert_clients_owned(con, trainer_id, [client_id])
    # The PK is (client_id, name) — adding trainer_id to the conflict
    # target would change PK semantics (and DuckDB would reject it).
    # We rely on (trainer_id, client_id) being effectively unique:
    # client_id is a uuid'd column, so two trainers can't collide on
    # it in practice. Trainer_id is set on both INSERT and UPDATE so a
    # mistakenly-passed cross-trainer client_id at least writes the
    # caller's trainer_id, surfacing the bug on the next read.
    con.execute(
        """
        INSERT INTO client_thresholds (client_id, name, value, trainer_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (client_id, name) DO UPDATE
          SET value = EXCLUDED.value,
              trainer_id = EXCLUDED.trainer_id
        """,
        [client_id, name, value, trainer_id],
    )


def delete_threshold(con, trainer_id: str, client_id: str, name: str) -> None:
    _assert_clients_owned(con, trainer_id, [client_id])
    con.execute(
        "DELETE FROM client_thresholds WHERE trainer_id = ? AND client_id = ? AND name = ?",
        [trainer_id, client_id, name],
    )


def all_overrides(con, trainer_id: str, limit: int = 1000) -> pd.DataFrame:
    """All overrides for a trainer across all their clients — for the
    calibration page."""
    try:
        return con.execute(
            """
            SELECT id, client_id, week_of, system_recommendation, system_confidence,
                   trainer_action, applied_load_change_pct, trainer_note, created_at
            FROM recommendation_overrides
            WHERE trainer_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [trainer_id, limit],
        ).df()
    except duckdb.CatalogException:
        return _empty_overrides_df()


# ─── Planned sessions (weekly plan) ──────────────────────────────────

def upsert_planned_session(con, trainer_id: str, ps) -> None:
    """Insert or replace a single planned-session row. Used both during
    initial engine generation and for trainer edits (a PATCH on a slot).
    Source string and contraindications JSON live in the row alongside
    the structured fields so a reload doesn't need to re-derive them.

    Explicit column list (instead of positional VALUES) so adding new
    columns — trainer_id today, more tomorrow — doesn't silently
    misalign with the table definition."""
    from .planning import serialize_contraindications

    _assert_clients_owned(con, trainer_id, [ps.client_id])
    con.execute(
        """
        INSERT OR REPLACE INTO planned_sessions
          (id, client_id, week_of, slot, type, title, description,
           target_duration_min, target_load_au, target_rpe,
           contraindications, source, generated_at, executed_session_id, trainer_id)
        VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ps.id,
            ps.client_id,
            ps.week_of,
            ps.slot,
            ps.type.value if hasattr(ps.type, "value") else str(ps.type),
            ps.title,
            ps.description,
            ps.target_duration_min,
            ps.target_load_au,
            ps.target_rpe,
            serialize_contraindications(ps.contraindications),
            ps.source.value if hasattr(ps.source, "value") else str(ps.source),
            ps.generated_at,
            ps.executed_session_id,
            trainer_id,
        ],
    )


def insert_plan(con, trainer_id: str, planned_sessions) -> None:
    """Persist a freshly-generated plan (list of PlannedSession). Wraps
    individual upserts so a partial failure leaves the DB in a usable
    state — each slot is independent."""
    for ps in planned_sessions:
        upsert_planned_session(con, trainer_id, ps)


def match_planned_sessions(con, trainer_id: str, client_id: str) -> int:
    """Link unmatched sessions to unmatched planned_sessions slots.

    For each session belonging to ``(trainer_id, client_id)`` that
    isn't yet linked to a planned slot, look up the slots for that
    session's week and pick one: prefer same ``type`` first, then
    lowest ``slot`` number. If a match is found, write the session id
    into the slot's ``executed_session_id``. Idempotent — sessions
    already linked are skipped. Returns the number of new links made.

    Closes the plan-vs-execution telemetry loop: once a real session
    lands (via Garmin sync, upload, manual entry), the matcher records
    "this session executed slot X of week Y" so future calibration can
    ask "did the deload week actually get followed?" without re-deriving
    the link.
    """
    from datetime import timedelta

    try:
        # LEFT JOIN tells us which sessions don't yet have any planned
        # slot pointing back at them. ORDER BY date keeps the linking
        # deterministic on a fresh run.
        rows = con.execute(
            """
            SELECT s.id, s.date, s.type
            FROM sessions s
            LEFT JOIN planned_sessions ps ON ps.executed_session_id = s.id
            WHERE s.trainer_id = ? AND s.client_id = ? AND ps.id IS NULL
            ORDER BY s.date
            """,
            [trainer_id, client_id],
        ).fetchall()
    except duckdb.CatalogException:
        # planned_sessions table doesn't exist yet (pre-migration)
        return 0

    linked = 0
    for session_id, session_date, session_type in rows:
        # Normalize the date — DuckDB returns Python ``date`` for DATE
        # columns, but be defensive in case a caller hands in a Timestamp.
        if hasattr(session_date, "weekday"):
            sd = session_date
        else:
            sd = pd.to_datetime(session_date).date()
        week_of = sd - timedelta(days=sd.weekday())

        # Same-type slots come first (CASE ... THEN 0 ELSE 1), then
        # ascending slot number among the remaining candidates.
        match = con.execute(
            """
            SELECT id FROM planned_sessions
            WHERE trainer_id = ?
              AND client_id = ?
              AND week_of = ?
              AND executed_session_id IS NULL
            ORDER BY
                CASE WHEN type = ? THEN 0 ELSE 1 END,
                slot
            LIMIT 1
            """,
            [trainer_id, client_id, week_of, session_type],
        ).fetchone()

        if match:
            con.execute(
                "UPDATE planned_sessions SET executed_session_id = ? WHERE id = ?",
                [session_id, match[0]],
            )
            linked += 1
    return linked


def plan_for_week(con, trainer_id: str, client_id: str, week_of):
    """Return the list of PlannedSession rows for ``(trainer_id,
    client_id, week_of)``, ordered by slot. Empty list if no plan
    persisted yet."""
    from .ontology import PlannedSession, PlanSource, SessionType
    from .planning import parse_contraindications

    try:
        rows = con.execute(
            """
            SELECT id, client_id, week_of, slot, type, title, description,
                   target_duration_min, target_load_au, target_rpe,
                   contraindications, source, generated_at, executed_session_id
            FROM planned_sessions
            WHERE trainer_id = ? AND client_id = ? AND week_of = ?
            ORDER BY slot
            """,
            [trainer_id, client_id, week_of],
        ).fetchall()
    except duckdb.CatalogException:
        # Pre-migration DB
        return []

    out = []
    for r in rows:
        out.append(PlannedSession(
            id=r[0],
            client_id=r[1],
            week_of=r[2],
            slot=r[3],
            type=SessionType(r[4]),
            title=r[5],
            description=r[6],
            target_duration_min=r[7],
            target_load_au=r[8],
            target_rpe=r[9],
            contraindications=parse_contraindications(r[10]),
            source=PlanSource(r[11]),
            generated_at=r[12],
            executed_session_id=r[13],
        ))
    return out


# ─── Audit log (Phase 5a) ────────────────────────────────────────────
#
# Append-only — record_audit is the only writer this codebase has, and
# there's no helper to delete rows from audit_log. The point is that
# even an attacker who compromises a trainer's session can't erase
# evidence of what they did with it (modulo the writer cooperating,
# which it won't).
#
# We tolerate a missing table on read for pre-Phase-5a DBs the same
# way the override / threshold readers do — older DBs without the
# table just see an empty audit log on the eventual /audit endpoint
# rather than an error.


def record_audit(
    con,
    trainer_id: str,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict | None = None,
    ip: str | None = None,
) -> None:
    """Append one row to audit_log. Failures bubble — auditing is not
    optional for the calling action: if we can't record what
    happened, we shouldn't claim it succeeded.

    details is serialized to JSON inline rather than via a separate
    column-per-key schema, because the set of "action-specific
    fields" is naturally heterogeneous (override.saved cares about
    trainer_action, plan.edited cares about slot + field-changed).
    Long JSON in a VARCHAR is fine at this scale; we're not indexing
    into it.
    """
    con.execute(
        """
        INSERT INTO audit_log
          (id, trainer_id, action, target_type, target_id, details, ip, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            f"a_{uuid.uuid4().hex[:12]}",
            trainer_id,
            action,
            target_type,
            target_id,
            json.dumps(details) if details else None,
            ip,
            datetime.utcnow(),
        ],
    )


def audit_log_for_trainer(con, trainer_id: str, limit: int = 100):
    """Return the most recent ``limit`` audit rows for a trainer,
    newest first. Tolerates a missing table (pre-migration DB)."""
    try:
        rows = con.execute(
            """
            SELECT id, trainer_id, action, target_type, target_id, details, ip, created_at
            FROM audit_log
            WHERE trainer_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [trainer_id, limit],
        ).fetchall()
    except duckdb.CatalogException:
        return []
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "trainer_id": r[1],
            "action": r[2],
            "target_type": r[3],
            "target_id": r[4],
            "details": json.loads(r[5]) if r[5] else None,
            "ip": r[6],
            "created_at": r[7],
        })
    return out


# ─── Share tokens (Phase 3a) ─────────────────────────────────────────
#
# Opaque token → read-only client view, no login. Three helpers:
#   create_share_token   trainer-scoped write — mints a fresh token
#                        for one of the trainer's clients
#   share_lookup         public read — resolves a token to the data
#                        needed to render the client view, or None if
#                        the token is unknown/expired/wrong-trainer
#   revoke_share_token   trainer-scoped delete — invalidates a live
#                        token before its natural expiry
#
# Tokens themselves are 32-byte URL-safe random strings (~256 bits).
# We store them in cleartext: the security model is "guessing this
# token is computationally infeasible," not "the DB is the secret."
# If/when the threat model tightens, store SHA-256(token) instead and
# compare hashed — a one-file change here, no schema change required
# (token field stays VARCHAR).


SHARE_TTL_DAYS_DEFAULT = 14


def create_share_token(
    con,
    trainer_id: str,
    client_id: str,
    trainer_message: str | None = None,
    ttl_days: int = SHARE_TTL_DAYS_DEFAULT,
) -> tuple[str, datetime]:
    """Mint a fresh share token for ``(trainer_id, client_id)``.

    Verifies the client actually belongs to the trainer before
    writing — otherwise a trainer could mint a public link to
    another trainer's client just by knowing their client_id.
    Returns (token, expires_at). The caller (route layer) is
    responsible for turning the token into a full URL.
    """
    owns = con.execute(
        "SELECT 1 FROM clients WHERE id = ? AND trainer_id = ?",
        [client_id, trainer_id],
    ).fetchone()
    if not owns:
        # Same error shape as a missing client — don't leak the
        # difference between "doesn't exist" and "exists but isn't yours."
        raise ValueError(f"No client with id {client_id}")

    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires_at = now + timedelta(days=ttl_days)
    con.execute(
        """
        INSERT INTO client_share_tokens
          (id, token, client_id, trainer_id, trainer_message, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            f"st_{uuid.uuid4().hex[:12]}",
            token,
            client_id,
            trainer_id,
            (trainer_message or None),
            now,
            expires_at,
        ],
    )
    return token, expires_at


def share_lookup(con, token: str):
    """Resolve a token to ``(trainer_id, client_id, trainer_message,
    expires_at)`` or None.

    Tolerates a missing table (pre-Phase-3a DB on a read-only
    connection): returns None. The route layer maps None → 404.
    Distinguishes expired tokens from unknown ones in the return
    type so the route can emit 410 (Gone) for expired rather than
    404, giving the client a slightly more useful error.
    """
    try:
        row = con.execute(
            """
            SELECT trainer_id, client_id, trainer_message, expires_at
            FROM client_share_tokens
            WHERE token = ?
            """,
            [token],
        ).fetchone()
    except duckdb.CatalogException:
        return None
    if not row:
        return None
    trainer_id, client_id, msg, expires_at = row
    return {
        "trainer_id": trainer_id,
        "client_id": client_id,
        "trainer_message": msg,
        "expires_at": expires_at,
        "expired": expires_at < datetime.utcnow(),
    }


def revoke_share_token(con, trainer_id: str, token: str) -> bool:
    """Delete a token if it belongs to ``trainer_id``. Returns True if
    a row was removed, False if the token didn't exist or belonged to
    another trainer. The boolean lets the route distinguish "your
    link is now dead" from "no such link" for the audit log.

    SELECT-then-DELETE rather than relying on cursor.rowcount because
    DuckDB's Python connector doesn't update rowcount after DML in a
    way we can depend on across versions.
    """
    exists = con.execute(
        "SELECT 1 FROM client_share_tokens WHERE token = ? AND trainer_id = ?",
        [token, trainer_id],
    ).fetchone()
    if not exists:
        return False
    con.execute(
        "DELETE FROM client_share_tokens WHERE token = ? AND trainer_id = ?",
        [token, trainer_id],
    )
    return True


# ─── Intake tokens (Phase 3b) ────────────────────────────────────────
#
# Inbound counterpart to client_share_tokens. The trainer mints one of
# these per "send intake link" action and shares the resulting URL with
# a prospective client; the client opens it, fills the form, and the
# submission inserts a row into ``clients`` scoped to the token's
# trainer_id. One-shot by design — a submitted token is dead, a fresh
# link is one new client.
#
#   create_intake_token   trainer-scoped write — mints a fresh token
#                         not yet tied to any client
#   intake_lookup         public read — resolves a token to the data
#                         needed to render the form (trainer name +
#                         optional welcome message), distinguishing
#                         unknown / expired / already-consumed
#   consume_intake_token  public write — atomic single-claim; flips
#                         consumed_at NULL → now() exactly once, returns
#                         True only for the caller that won the claim
#
# Same token-shape and storage posture as share tokens (32-byte
# URL-safe random, stored cleartext, 256 bits of entropy is the secret).


INTAKE_TTL_DAYS_DEFAULT = 14


def create_intake_token(
    con,
    trainer_id: str,
    trainer_message: str | None = None,
    ttl_days: int = INTAKE_TTL_DAYS_DEFAULT,
) -> tuple[str, datetime]:
    """Mint a fresh intake token for ``trainer_id``.

    Unlike ``create_share_token`` there's no client_id to check
    ownership against — the client doesn't exist yet. We do verify
    the trainer row exists, so a typo in trainer_id surfaces here
    instead of as a dangling token that no submission can resolve
    against (intake_lookup would still work, but the resulting
    INSERT would fail the FK on whatever trainer_id we passed
    through). Returns (token, expires_at); caller turns the token
    into a full URL.
    """
    owns = con.execute(
        "SELECT 1 FROM trainers WHERE id = ?",
        [trainer_id],
    ).fetchone()
    if not owns:
        raise ValueError(f"No trainer with id {trainer_id}")

    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires_at = now + timedelta(days=ttl_days)
    con.execute(
        """
        INSERT INTO client_intake_tokens
          (id, token, trainer_id, trainer_message, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            f"it_{uuid.uuid4().hex[:12]}",
            token,
            trainer_id,
            (trainer_message or None),
            now,
            expires_at,
        ],
    )
    return token, expires_at


def intake_lookup(con, token: str):
    """Resolve a token to ``(trainer_id, trainer_message, expires_at,
    expired, consumed)`` or None.

    Tolerates a missing table (pre-Phase-3b DB on a read-only
    connection): returns None. The route layer maps None → 404,
    ``expired=True`` → 410, ``consumed=True`` → 410 with a
    different message ("this form has already been submitted").
    """
    try:
        row = con.execute(
            """
            SELECT trainer_id, trainer_message, expires_at, consumed_at
            FROM client_intake_tokens
            WHERE token = ?
            """,
            [token],
        ).fetchone()
    except duckdb.CatalogException:
        return None
    if not row:
        return None
    trainer_id, msg, expires_at, consumed_at = row
    return {
        "trainer_id": trainer_id,
        "trainer_message": msg,
        "expires_at": expires_at,
        "expired": expires_at < datetime.utcnow(),
        "consumed": consumed_at is not None,
        "consumed_at": consumed_at,
    }


def consume_intake_token(con, token: str, client_id: str) -> bool:
    """Atomically claim a token for ``client_id``.

    Flips ``consumed_at`` NULL → now() and stamps
    ``consumed_client_id``, in a single UPDATE guarded by ``WHERE
    consumed_at IS NULL`` so two in-flight submissions for the
    same token can't both succeed. Returns True if this caller
    claimed the token, False if it was already consumed (or
    doesn't exist / is expired — the caller has already done the
    intake_lookup precheck for those, so a False here means the
    race lost).

    RETURNING id rather than rowcount because DuckDB's Python
    connector doesn't surface affected-rows reliably across
    versions (same reason ``revoke_share_token`` uses
    SELECT-then-DELETE).
    """
    now = datetime.utcnow()
    result = con.execute(
        """
        UPDATE client_intake_tokens
        SET consumed_at = ?, consumed_client_id = ?
        WHERE token = ? AND consumed_at IS NULL AND expires_at >= ?
        RETURNING id
        """,
        [now, client_id, token, now],
    ).fetchone()
    return result is not None
