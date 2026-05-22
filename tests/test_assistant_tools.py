"""Smoke tests for the assistant tools.

These don't call the Anthropic API. They verify the tool implementations
themselves do what the assistant expects: read from the DB, return
serialized payloads in the right shape, and route correctly through the
tool dispatcher.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fit_ontology.assistant import _execute_tool, TOOLS
from fit_ontology.db import connect, ensure_client, insert_metrics, insert_sessions
from fit_ontology.ontology import MetricKind


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    """A real DuckDB on disk with one client plus a week of metrics and
    a few sessions. Returned path is what the tools read from."""
    db_path = tmp_path / "fit_ontology.duckdb"
    con = connect(db_path)
    ensure_client(con, "c_test", name="Test Client")

    today = date.today()
    metric_rows = []
    for offset in range(14, 0, -1):
        d = today - timedelta(days=offset)
        metric_rows.append({
            "id": f"m-hrv-{offset}", "client_id": "c_test", "date": d,
            "source": "garmin", "kind": MetricKind.HRV_RMSSD.value,
            "value": 55.0, "unit": "ms",
        })
        metric_rows.append({
            "id": f"m-sleep-{offset}", "client_id": "c_test", "date": d,
            "source": "garmin", "kind": MetricKind.SLEEP_HOURS.value,
            "value": 7.5, "unit": "h",
        })
    insert_metrics(con, pd.DataFrame(metric_rows))

    session_rows = []
    for i, offset in enumerate([2, 4, 6, 9, 11, 13]):
        session_rows.append({
            "id": f"s-{i}", "client_id": "c_test",
            "date": today - timedelta(days=offset),
            "type": "strength", "duration_min": 60, "rpe": 6, "notes": "",
        })
    insert_sessions(con, pd.DataFrame(session_rows))
    con.close()
    return db_path


def test_tool_definitions_have_required_fields():
    """Each tool definition must satisfy Anthropic's tool schema: a name,
    a description, and an input_schema. Missing any of these breaks the
    API call before it leaves our process."""
    for tool in TOOLS:
        assert tool["name"]
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"


def test_list_clients_returns_csv_with_seeded_client(seeded_db: Path):
    out = _execute_tool("list_clients", {}, seeded_db)
    assert "c_test" in out
    assert "Test Client" in out


def test_get_client_summary_returns_intake_row(seeded_db: Path):
    out = _execute_tool("get_client_summary", {"client_id": "c_test"}, seeded_db)
    assert "c_test" in out
    assert "Test Client" in out


def test_get_client_summary_handles_unknown_id(seeded_db: Path):
    out = _execute_tool("get_client_summary", {"client_id": "c_missing"}, seeded_db)
    assert "no client with id" in out.lower()


def test_get_recent_metrics_returns_hrv_and_sleep(seeded_db: Path):
    out = _execute_tool("get_recent_metrics", {"client_id": "c_test", "days": 7}, seeded_db)
    assert MetricKind.HRV_RMSSD.value in out
    assert MetricKind.SLEEP_HOURS.value in out


def test_get_recent_sessions_returns_session_rows(seeded_db: Path):
    out = _execute_tool("get_recent_sessions", {"client_id": "c_test", "days": 14}, seeded_db)
    assert "strength" in out
    assert "duration_min" in out


def test_compute_recommendation_returns_structured_json(seeded_db: Path):
    out = _execute_tool("compute_recommendation", {"client_id": "c_test"}, seeded_db)
    parsed = json.loads(out)
    assert "recommendation" in parsed
    assert "rationale" in parsed
    assert "confidence" in parsed
    assert 0 <= parsed["confidence"] <= 1


def test_unknown_tool_name_returns_friendly_error(seeded_db: Path):
    out = _execute_tool("definitely_not_a_tool", {}, seeded_db)
    assert "unknown tool" in out.lower()
