"""DuckDB persistence layer."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from .ontology import SCHEMA_DDL

DEFAULT_DB_PATH = Path("data/fit_ontology.duckdb")


def connect(db_path: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA_DDL)
    return con


def insert_clients(con, df: pd.DataFrame) -> None:
    con.execute("INSERT OR REPLACE INTO clients SELECT * FROM df")


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
    return con.execute(
        f"""
        SELECT date, type, duration_min, rpe, notes
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
