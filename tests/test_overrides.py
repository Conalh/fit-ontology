"""Trainer override roundtrip.

Verifies that:
  - The DDL applied by a write-mode connect() creates the overrides table.
  - insert_override → overrides_for_client → latest_override_for_week
    returns the same row.
  - The override survives a close/reopen cycle (persistence works).
  - Read-only access against a DB that pre-dates the override table
    returns an empty DataFrame instead of erroring.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path

import duckdb

from fit_ontology.db import (
    connect,
    insert_override,
    latest_override_for_week,
    overrides_for_client,
)
from fit_ontology.ontology import OverrideAction, RecommendationOverride


def _seed_client(con, client_id: str = "c_test") -> str:
    con.execute(
        """
        INSERT OR REPLACE INTO clients
            (id, name, sex, age, height_cm, weight_kg, goal, injury_history, created_at)
        VALUES (?, 'Test Client', 'other', 30, 170.0, 70.0, 'test', NULL, CURRENT_TIMESTAMP)
        """,
        [client_id],
    )
    return client_id


def _make_override(client_id: str, week_of: date, action: OverrideAction, **kw) -> RecommendationOverride:
    return RecommendationOverride(
        id=f"o_{uuid.uuid4().hex[:12]}",
        client_id=client_id,
        week_of=week_of,
        system_recommendation=kw.get("system_recommendation", "Deload week: reduce training load by 20%."),
        system_confidence=kw.get("system_confidence", 0.9),
        trainer_action=action,
        applied_load_change_pct=kw.get("applied_load_change_pct"),
        trainer_note=kw.get("trainer_note"),
        created_at=kw.get("created_at", datetime.now()),
    )


def test_override_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "test.duckdb"
    week_of = date(2026, 5, 18)

    with connect(db_path, read_only=False) as con:
        client_id = _seed_client(con)
        ov = _make_override(
            client_id,
            week_of,
            OverrideAction.EDIT,
            applied_load_change_pct=-10.0,
            trainer_note="travel week",
        )
        insert_override(con, ov)

    # Reopen read-only — the override should survive.
    with connect(db_path, read_only=True) as con:
        latest = latest_override_for_week(con, client_id, week_of)
        assert len(latest) == 1
        row = latest.iloc[0]
        assert row["trainer_action"] == "edit"
        assert row["applied_load_change_pct"] == -10.0
        assert row["trainer_note"] == "travel week"

        history = overrides_for_client(con, client_id)
        assert len(history) == 1


def test_latest_override_returns_most_recent(tmp_path: Path) -> None:
    """The trainer's view changes; we keep the audit trail but only the
    most recent decision is operative."""
    db_path = tmp_path / "test.duckdb"
    week_of = date(2026, 5, 18)

    with connect(db_path, read_only=False) as con:
        client_id = _seed_client(con)
        insert_override(con, _make_override(
            client_id, week_of, OverrideAction.ACCEPT,
            created_at=datetime(2026, 5, 19, 9, 0, 0),
        ))
        insert_override(con, _make_override(
            client_id, week_of, OverrideAction.REJECT,
            trainer_note="client called sick",
            created_at=datetime(2026, 5, 20, 14, 30, 0),
        ))

    with connect(db_path, read_only=True) as con:
        latest = latest_override_for_week(con, client_id, week_of)
        assert latest.iloc[0]["trainer_action"] == "reject"

        history = overrides_for_client(con, client_id)
        assert len(history) == 2  # both preserved


def test_reader_tolerates_missing_table(tmp_path: Path) -> None:
    """A DB built before the override schema existed should not break the
    dashboard reader — it should just see zero overrides."""
    db_path = tmp_path / "old.duckdb"

    # Build a DB with the legacy schema (no overrides table).
    legacy_ddl = """
    CREATE TABLE clients (
        id VARCHAR PRIMARY KEY, name VARCHAR, sex VARCHAR, age INTEGER,
        height_cm DOUBLE, weight_kg DOUBLE, goal VARCHAR,
        injury_history VARCHAR, created_at TIMESTAMP
    );
    """
    raw = duckdb.connect(str(db_path))
    raw.execute(legacy_ddl)
    raw.execute(
        "INSERT INTO clients VALUES ('c_legacy', 'Legacy', 'other', 30, 170.0, 70.0, 'test', NULL, CURRENT_TIMESTAMP)"
    )
    raw.close()

    # Reopen read-only — should NOT auto-create the overrides table.
    raw_ro = duckdb.connect(str(db_path), read_only=True)
    try:
        history = overrides_for_client(raw_ro, "c_legacy")
        latest = latest_override_for_week(raw_ro, "c_legacy", date(2026, 5, 18))
    finally:
        raw_ro.close()

    assert history.empty
    assert latest.empty
