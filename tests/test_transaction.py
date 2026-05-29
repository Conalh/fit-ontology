"""The ``db.transaction`` context manager.

Contracts pinned:
  1. A clean exit COMMITs — writes inside the block survive.
  2. An exception ROLLBACKs — writes inside the block are undone.
  3. The original exception propagates unmasked (a failing rollback
     doesn't swallow it).
  4. The CM yields the same connection for ``with transaction(con) as c``.
  5. Documentation guard: the client delete cascade canNOT run inside a
     transaction because of DuckDB's over-eager FK checking — this pins
     that limitation so a future DuckDB that fixes it trips the test and
     prompts us to revisit delete_client_cascade.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from fit_ontology.db import (
    connect,
    delete_client_cascade,
    ensure_client,
    insert_metrics,
    insert_sessions,
    insert_trainer,
    transaction,
)
from fit_ontology.ontology import MetricKind


def test_transaction_commits_on_clean_exit(tmp_path: Path):
    db_path = tmp_path / "tx.duckdb"
    with connect(db_path, read_only=False) as con, transaction(con):
        insert_trainer(con, "t_keep", "keep@example.com", "Keeper")
    with connect(db_path, read_only=True) as con:
        row = con.execute("SELECT id FROM trainers WHERE id = 't_keep'").fetchone()
    assert row is not None


def test_transaction_rolls_back_on_exception(tmp_path: Path):
    db_path = tmp_path / "tx.duckdb"
    with (
        connect(db_path, read_only=False) as con,
        pytest.raises(RuntimeError),
        transaction(con),
    ):
        insert_trainer(con, "t_gone", "gone@example.com", "Goner")
        raise RuntimeError("boom mid-write")
    # Fresh connection: the rolled-back row must not exist.
    with connect(db_path, read_only=True) as con:
        row = con.execute("SELECT id FROM trainers WHERE id = 't_gone'").fetchone()
    assert row is None


def test_transaction_propagates_original_exception(tmp_path: Path):
    """The caller needs to see the real failure, not a rollback artifact."""
    db_path = tmp_path / "tx.duckdb"

    class Sentinel(Exception):
        pass

    with (
        connect(db_path, read_only=False) as con,
        pytest.raises(Sentinel),
        transaction(con),
    ):
        insert_trainer(con, "t_x", "x@example.com", "X")
        raise Sentinel("this exact error")


def test_transaction_yields_the_connection(tmp_path: Path):
    """Sugar: the context manager hands back the same connection so a
    caller can ``with transaction(con) as c``."""
    db_path = tmp_path / "tx.duckdb"
    with connect(db_path, read_only=False) as con, transaction(con) as c:
        assert isinstance(c, duckdb.DuckDBPyConnection)
        assert c is con


def test_cascade_inside_transaction_hits_duckdb_fk_limit(tmp_path: Path):
    """Guard on a DuckDB limitation, not on our code.

    delete_client_cascade is intentionally run WITHOUT transaction()
    because DuckDB's foreign-key checker is over-eager inside an explicit
    transaction: the parent ``DELETE FROM clients`` still sees the child
    rows we deleted earlier in the same uncommitted transaction and
    raises ConstraintException. This test pins that behavior so that if a
    future DuckDB release fixes it (the cascade would then succeed and
    this test would fail), we're prompted to revisit the decision and
    wrap the cascade for true atomicity.
    """
    db_path = tmp_path / "tx.duckdb"
    today = date.today()
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t1", "t1@example.com", "T1")
        ensure_client(con, "t1", "c_victim", name="Victim")
        insert_metrics(con, "t1", pd.DataFrame([
            {"id": f"m-{i}", "client_id": "c_victim", "date": today - timedelta(days=i),
             "source": "garmin", "kind": MetricKind.HRV_RMSSD.value, "value": 55.0, "unit": "ms"}
            for i in range(5)
        ]))
        insert_sessions(con, "t1", pd.DataFrame([
            {"id": f"s-{i}", "client_id": "c_victim", "date": today - timedelta(days=i),
             "type": "strength", "duration_min": 45, "rpe": 6, "notes": ""}
            for i in range(3)
        ]))

    with (
        connect(db_path, read_only=False) as con,
        pytest.raises(duckdb.ConstraintException),
        transaction(con),
    ):
        delete_client_cascade(con, "t1", "c_victim")

    # The failed transaction rolled back — the client survives intact.
    with connect(db_path, read_only=True) as con:
        assert con.execute(
            "SELECT 1 FROM clients WHERE id = 'c_victim'"
        ).fetchone() is not None
