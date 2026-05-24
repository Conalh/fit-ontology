"""DuckDB persistence layer."""
from __future__ import annotations

import json
import os
from pathlib import Path

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


def connect(db_path: Path = DEFAULT_DB_PATH, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection. DuckDB allows only one writer per file
    across processes, so the dashboard should pass ``read_only=True`` to
    coexist with a concurrent sync script. The schema DDL is skipped in
    read-only mode (the file must already exist, which is fine for a
    dashboard that only renders existing data)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if read_only and not db_path.exists():
        # Read-only against a missing file would be misleading; let the
        # caller create+seed the DB first via a normal connect.
        raise FileNotFoundError(f"DuckDB file not found for read-only open: {db_path}")
    con = duckdb.connect(str(db_path), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA_DDL)
    return con


def insert_clients(con, df: pd.DataFrame) -> None:
    con.execute("INSERT OR REPLACE INTO clients SELECT * FROM df")


def ensure_client(con, client_id: str, name: str = "Self", sex: str = "other") -> None:
    """
    Idempotently create a stub client row so foreign-key constraints on
    metrics/sessions don't reject a fresh sync against a brand-new client_id.
    The trainer can edit the row later via SQL or a future Streamlit form;
    we just need a valid parent here.
    """
    existing = con.execute("SELECT 1 FROM clients WHERE id = ?", [client_id]).fetchone()
    if existing:
        return
    con.execute(
        """
        INSERT INTO clients (id, name, sex, age, height_cm, weight_kg, goal, injury_history, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        [client_id, name, sex, 30, 170.0, 70.0, "(self)", None],
    )


def insert_sessions(con, df: pd.DataFrame) -> None:
    con.execute("INSERT OR REPLACE INTO sessions SELECT * FROM df")


def insert_metrics(con, df: pd.DataFrame) -> None:
    con.execute("INSERT OR REPLACE INTO metrics SELECT * FROM df")


def insert_recommendation(con, rec) -> None:
    con.execute(
        """
        INSERT OR REPLACE INTO recommendations VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
        ],
    )


def list_clients(con) -> pd.DataFrame:
    return con.execute("SELECT id, name, goal FROM clients ORDER BY name").df()


def metrics_for_client(con, client_id: str, days: int = 14) -> pd.DataFrame:
    return con.execute(
        f"""
        SELECT date, source, kind, value, unit, id
        FROM metrics
        WHERE client_id = ?
          AND date >= CURRENT_DATE - INTERVAL '{days}' DAY
        ORDER BY date
        """,
        [client_id],
    ).df()


def sessions_for_client(con, client_id: str, days: int = 14) -> pd.DataFrame:
    """Include the session ``id`` in the result so reasoning signals that
    derive from sessions (ACWR, RPE drift) can attach source IDs to
    their output — closing the same audit-trail loop the metrics-based
    signals already have."""
    return con.execute(
        f"""
        SELECT id, date, type, duration_min, rpe, notes
        FROM sessions
        WHERE client_id = ?
          AND date >= CURRENT_DATE - INTERVAL '{days}' DAY
        ORDER BY date
        """,
        [client_id],
    ).df()


def latest_recommendation(con, client_id: str) -> pd.DataFrame:
    return con.execute(
        """
        SELECT recommendation, rationale, source_metric_ids, confidence, generated_at, week_of
        FROM recommendations
        WHERE client_id = ?
        ORDER BY generated_at DESC
        LIMIT 1
        """,
        [client_id],
    ).df()


def recommendation_for_week(con, client_id: str, week_of):
    """Return the stored Recommendation for this (client, week) or None.
    Hydrates the JSON source_metric_ids back into a list, so callers
    get the same shape ``generate_recommendation`` produces in memory."""
    from .ontology import Recommendation

    row = con.execute(
        """
        SELECT id, client_id, generated_at, week_of, recommendation, rationale,
               source_metric_ids, confidence
        FROM recommendations
        WHERE client_id = ? AND week_of = ?
        LIMIT 1
        """,
        [client_id, week_of],
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


def recommendations_for_client(con, client_id: str, limit: int = 12) -> pd.DataFrame:
    """All stored weekly recommendations for a client, newest first.
    Drives the history view on the detail page."""
    return con.execute(
        """
        SELECT id, client_id, week_of, recommendation, rationale,
               source_metric_ids, confidence, generated_at
        FROM recommendations
        WHERE client_id = ?
        ORDER BY week_of DESC
        LIMIT ?
        """,
        [client_id, limit],
    ).df()


# ─── Trainer overrides ────────────────────────────────────────────────
#
# A read-only DuckDB connection cannot create tables, so a DB that
# predates the override schema will error on the first SELECT. We catch
# the missing-table case and return empty results; the table appears the
# first time an override is written (which opens write mode, where the
# IF NOT EXISTS DDL runs as part of connect()).

def insert_override(con, ov) -> None:
    con.execute(
        """
        INSERT INTO recommendation_overrides
        (id, client_id, week_of, system_recommendation, system_confidence,
         trainer_action, applied_load_change_pct, trainer_note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def overrides_for_client(con, client_id: str, limit: int = 50) -> pd.DataFrame:
    """All overrides for a client, newest first. Empty if the table
    doesn't exist yet (pre-migration DB)."""
    try:
        return con.execute(
            """
            SELECT id, client_id, week_of, system_recommendation, system_confidence,
                   trainer_action, applied_load_change_pct, trainer_note, created_at
            FROM recommendation_overrides
            WHERE client_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [client_id, limit],
        ).df()
    except duckdb.CatalogException:
        return _empty_overrides_df()


def latest_override_for_week(con, client_id: str, week_of) -> pd.DataFrame:
    """The most recent override for (client_id, week_of), or empty."""
    try:
        return con.execute(
            """
            SELECT id, client_id, week_of, system_recommendation, system_confidence,
                   trainer_action, applied_load_change_pct, trainer_note, created_at
            FROM recommendation_overrides
            WHERE client_id = ? AND week_of = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [client_id, week_of],
        ).df()
    except duckdb.CatalogException:
        return _empty_overrides_df()


# ─── Per-client thresholds ────────────────────────────────────────────
#
# Sparse-table model: a stored row means the trainer explicitly
# overrode that threshold for this client; absence means use the
# population default from reasoning.DEFAULT_THRESHOLDS. Reads tolerate
# a missing table for pre-migration DBs.

def thresholds_for_client(con, client_id: str) -> dict[str, float]:
    try:
        rows = con.execute(
            "SELECT name, value FROM client_thresholds WHERE client_id = ?",
            [client_id],
        ).fetchall()
        return {name: float(value) for name, value in rows}
    except duckdb.CatalogException:
        return {}


def upsert_threshold(con, client_id: str, name: str, value: float) -> None:
    con.execute(
        """
        INSERT INTO client_thresholds (client_id, name, value)
        VALUES (?, ?, ?)
        ON CONFLICT (client_id, name) DO UPDATE SET value = EXCLUDED.value
        """,
        [client_id, name, value],
    )


def delete_threshold(con, client_id: str, name: str) -> None:
    con.execute(
        "DELETE FROM client_thresholds WHERE client_id = ? AND name = ?",
        [client_id, name],
    )


def all_overrides(con, limit: int = 1000) -> pd.DataFrame:
    """All overrides across clients — for the calibration page."""
    try:
        return con.execute(
            """
            SELECT id, client_id, week_of, system_recommendation, system_confidence,
                   trainer_action, applied_load_change_pct, trainer_note, created_at
            FROM recommendation_overrides
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [limit],
        ).df()
    except duckdb.CatalogException:
        return _empty_overrides_df()


# ─── Planned sessions (weekly plan) ──────────────────────────────────

def upsert_planned_session(con, ps) -> None:
    """Insert or replace a single planned-session row. Used both during
    initial engine generation and for trainer edits (a PATCH on a slot).
    Source string and contraindications JSON live in the row alongside
    the structured fields so a reload doesn't need to re-derive them."""
    from .planning import serialize_contraindications

    con.execute(
        """
        INSERT OR REPLACE INTO planned_sessions VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ],
    )


def insert_plan(con, planned_sessions) -> None:
    """Persist a freshly-generated plan (list of PlannedSession). Wraps
    individual upserts so a partial failure leaves the DB in a usable
    state — each slot is independent."""
    for ps in planned_sessions:
        upsert_planned_session(con, ps)


def plan_for_week(con, client_id: str, week_of):
    """Return the list of PlannedSession rows for ``(client_id, week_of)``,
    ordered by slot. Empty list if no plan persisted yet."""
    from .ontology import PlannedSession, PlanSource, SessionType
    from .planning import parse_contraindications

    try:
        rows = con.execute(
            """
            SELECT id, client_id, week_of, slot, type, title, description,
                   target_duration_min, target_load_au, target_rpe,
                   contraindications, source, generated_at, executed_session_id
            FROM planned_sessions
            WHERE client_id = ? AND week_of = ?
            ORDER BY slot
            """,
            [client_id, week_of],
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
