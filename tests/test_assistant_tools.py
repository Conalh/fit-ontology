"""Smoke tests for the assistant tools.

These don't call the Anthropic API. They verify the tool implementations
themselves do what the assistant expects: read from the DB, return
serialized payloads in the right shape, and route correctly through the
tool dispatcher.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from fit_ontology.assistant import TOOLS, AssistantTurn, _execute_tool, ask
from fit_ontology.db import (
    DEFAULT_TRAINER_ID,
    connect,
    ensure_client,
    insert_metrics,
    insert_sessions,
)
from fit_ontology.ontology import MetricKind


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    """A real DuckDB on disk with one client plus a week of metrics and
    a few sessions. Returned path is what the tools read from."""
    db_path = tmp_path / "fit_ontology.duckdb"
    con = connect(db_path)
    ensure_client(con, DEFAULT_TRAINER_ID, "c_test", name="Test Client")

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
    insert_metrics(con, DEFAULT_TRAINER_ID, pd.DataFrame(metric_rows))

    session_rows = []
    for i, offset in enumerate([2, 4, 6, 9, 11, 13]):
        session_rows.append({
            "id": f"s-{i}", "client_id": "c_test",
            "date": today - timedelta(days=offset),
            "type": "strength", "duration_min": 60, "rpe": 6, "notes": "",
        })
    insert_sessions(con, DEFAULT_TRAINER_ID, pd.DataFrame(session_rows))
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
    out = _execute_tool("list_clients", {}, seeded_db, DEFAULT_TRAINER_ID)
    assert "c_test" in out
    assert "Test Client" in out


def test_get_client_summary_returns_intake_row(seeded_db: Path):
    out = _execute_tool("get_client_summary", {"client_id": "c_test"}, seeded_db, DEFAULT_TRAINER_ID)
    assert "c_test" in out
    assert "Test Client" in out


def test_get_client_summary_handles_unknown_id(seeded_db: Path):
    out = _execute_tool("get_client_summary", {"client_id": "c_missing"}, seeded_db, DEFAULT_TRAINER_ID)
    assert "no client with id" in out.lower()


def test_get_recent_metrics_returns_hrv_and_sleep(seeded_db: Path):
    out = _execute_tool("get_recent_metrics", {"client_id": "c_test", "days": 7}, seeded_db, DEFAULT_TRAINER_ID)
    assert MetricKind.HRV_RMSSD.value in out
    assert MetricKind.SLEEP_HOURS.value in out


def test_get_recent_sessions_returns_session_rows(seeded_db: Path):
    out = _execute_tool("get_recent_sessions", {"client_id": "c_test", "days": 14}, seeded_db, DEFAULT_TRAINER_ID)
    assert "strength" in out
    assert "duration_min" in out


def test_compute_recommendation_returns_structured_json(seeded_db: Path):
    out = _execute_tool("compute_recommendation", {"client_id": "c_test"}, seeded_db, DEFAULT_TRAINER_ID)
    parsed = json.loads(out)
    assert "recommendation" in parsed
    assert "rationale" in parsed
    assert "confidence" in parsed
    assert 0 <= parsed["confidence"] <= 1


def test_get_recent_overrides_returns_csv(seeded_db: Path):
    import uuid
    from datetime import date, datetime

    from fit_ontology.db import insert_override
    from fit_ontology.ontology import OverrideAction, RecommendationOverride
    con = connect(seeded_db, read_only=False)
    ov = RecommendationOverride(
        id=f"o_{uuid.uuid4().hex[:12]}",
        client_id="c_test",
        week_of=date(2026, 5, 18),
        system_recommendation="Standard progression",
        system_confidence=0.8,
        trainer_action=OverrideAction.ACCEPT,
        trainer_note="Looks perfect",
        created_at=datetime.now(),
    )
    insert_override(con, DEFAULT_TRAINER_ID, ov)
    con.close()

    out = _execute_tool("get_recent_overrides", {"client_id": "c_test", "limit": 5}, seeded_db, DEFAULT_TRAINER_ID)
    assert "c_test" in out
    assert "accept" in out
    assert "Looks perfect" in out


def test_unknown_tool_name_returns_friendly_error(seeded_db: Path):
    out = _execute_tool("definitely_not_a_tool", {}, seeded_db, DEFAULT_TRAINER_ID)
    assert "unknown tool" in out.lower()


# --- Multi-turn chat: ask() must return the full Anthropic message stream
#     so the Streamlit page can pass it back as `history=` on the next
#     turn. Without that the second turn has no idea what tool_use /
#     tool_result blocks the first turn produced.


class _FakeBlock:
    """Minimal stand-in for an Anthropic content block — enough for the
    parts of ask() that read .type / .text / .name / .input / .id."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        return self._responses.pop(0)


class _FakeAnthropic:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def test_ask_returns_full_message_stream(monkeypatch, seeded_db: Path):
    """A single Q&A with no tool use should return a 2-message stream
    (user + assistant) so the next turn has context."""
    response = _FakeResponse(content=[_FakeBlock(type="text", text="Hello.")])
    fake_module = type("M", (), {"Anthropic": lambda self=None, **kw: _FakeAnthropic([response])})()
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    turn = ask("hi", db_path=seeded_db)

    assert isinstance(turn, AssistantTurn)
    assert turn.answer == "Hello."
    assert len(turn.messages) == 2
    assert turn.messages[0] == {"role": "user", "content": "hi"}
    assert turn.messages[1]["role"] == "assistant"


def test_ask_preserves_tool_use_blocks_for_next_turn(monkeypatch, seeded_db: Path):
    """When the model uses a tool, the returned messages must include the
    assistant's tool_use block AND the user tool_result block — that's
    what makes the second turn's context coherent."""
    tool_use_response = _FakeResponse(content=[
        _FakeBlock(type="tool_use", id="toolu_1", name="list_clients", input={}),
    ])
    final_response = _FakeResponse(content=[_FakeBlock(type="text", text="Just one client.")])
    fake_module = type("M", (), {"Anthropic": lambda self=None, **kw: _FakeAnthropic([tool_use_response, final_response])})()
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    turn = ask("how many clients?", db_path=seeded_db)

    # user → assistant(tool_use) → user(tool_result) → assistant(text)
    assert len(turn.messages) == 4
    assert turn.messages[1]["role"] == "assistant"
    assert any(b.get("type") == "tool_use" for b in turn.messages[1]["content"])
    assert turn.messages[2]["role"] == "user"
    assert any(b.get("type") == "tool_result" for b in turn.messages[2]["content"])
    assert turn.messages[3]["role"] == "assistant"
