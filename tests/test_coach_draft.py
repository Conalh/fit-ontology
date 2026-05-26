"""Phase 7a — coach_draft module + /api/.../coach-message/draft route.

Two surfaces under test:

  1. build_coach_draft_payload — pure function, every field lands in
     the expected key with the expected shape. Belt-and-suspenders so
     a future refactor that rewires field names breaks here rather
     than producing prompts Claude silently misreads.

  2. The HTTP route — mock anthropic.Anthropic the same way
     test_assistant_tools.py does so we don't burn quota on every
     pytest run. Covers happy-path 200, 412-without-API-key,
     429-when-rate-limited, audit-row-on-success, 404-for-non-owned
     client.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import fit_ontology.api as api_mod
from fit_ontology.coach_draft import build_coach_draft_payload
from fit_ontology.db import (
    audit_log_for_trainer,
    connect,
    ensure_client,
    insert_metrics,
    insert_override,
    insert_recommendation,
    insert_sessions,
    insert_trainer,
    set_trainer_password,
)
from fit_ontology.ontology import MetricKind, OverrideAction, Recommendation, RecommendationOverride
from fit_ontology.rate_limit import reset as rate_limit_reset
from fit_ontology.routes import (
    auth as auth_routes,
)
from fit_ontology.routes import (
    clients as clients_routes,
)
from fit_ontology.routes import (
    coach as coach_routes,
)
from fit_ontology.routes import (
    metrics as metrics_routes,
)
from fit_ontology.routes import (
    overrides as overrides_routes,
)
from fit_ontology.routes import (
    planning as planning_routes,
)
from fit_ontology.routes import (
    recommendation as recommendation_routes,
)
from fit_ontology.routes import (
    share as share_routes,
)
from fit_ontology.routes import (
    thresholds as thresholds_routes,
)

# ─── Pure-function tests ──────────────────────────────────────────────


def test_build_payload_normalizes_first_name():
    payload = build_coach_draft_payload(
        client_name="Alex Rivers",
        client_goal="half marathon Q3",
        recommendation="Deload week: reduce 20%.",
        rationale="HRV trending down + ACWR elevated.",
        confidence=0.82,
        recovery_score={"composite": 58, "hrv": 50, "sleep": 65, "rhr": 60, "acwr": 60},
        plan_adherence={"total_slots": 4, "matched_slots": 2, "match_rate": 0.5},
        recent_overrides=[],
    )
    assert payload["first_name"] == "Alex"
    assert payload["goal"] == "half marathon Q3"
    assert payload["verdict"].startswith("Deload")
    assert payload["confidence"] == 0.82
    assert payload["adherence"]["matched_slots"] == 2
    assert payload["recent_overrides"] == []


def test_build_payload_caps_recent_overrides_to_three():
    """Prompt budget is tight — more than ~3 historical overrides
    bloat the user message without changing what Claude would write."""
    overrides = [{"week_of": f"2026-05-{d}", "action": "reject", "note": None} for d in range(1, 10)]
    payload = build_coach_draft_payload(
        client_name="X", client_goal="g",
        recommendation="r", rationale="rat", confidence=0.5,
        recovery_score=None, plan_adherence=None, recent_overrides=overrides,
    )
    assert len(payload["recent_overrides"]) == 3


def test_build_payload_handles_empty_name():
    """A missing or whitespace-only client name shouldn't produce
    "Hi ," — the prompt has to address someone."""
    payload = build_coach_draft_payload(
        client_name="", client_goal="g",
        recommendation="r", rationale="rat", confidence=0.5,
        recovery_score=None, plan_adherence=None, recent_overrides=None,
    )
    assert payload["first_name"] == "there"


# ─── Route tests — anthropic-mocked ───────────────────────────────────


class _FakeBlock:
    def __init__(self, type: str, text: str = ""):
        self.type = type
        self.text = text


class _FakeResponse:
    def __init__(self, text: str):
        self.content = [_FakeBlock("text", text)]


class _FakeMessages:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.create_calls: list[dict] = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return self._response


class _FakeAnthropic:
    def __init__(self, response: _FakeResponse):
        self.messages = _FakeMessages(response)


def _install_fake_anthropic(monkeypatch, text: str) -> _FakeAnthropic:
    """Replace sys.modules['anthropic'] with a stub whose Anthropic()
    constructor returns a client that always responds with ``text``.
    Returns the stub so a test can inspect create_calls."""
    fake_client = _FakeAnthropic(_FakeResponse(text))
    fake_module = type("M", (), {
        "Anthropic": lambda self=None, **kw: fake_client,
    })()
    monkeypatch.setitem(sys.modules, "anthropic", fake_module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    return fake_client


@pytest.fixture()
def coach_app(tmp_path: Path, monkeypatch):
    """Same fixture pattern as test_security.py — one trainer, one
    client, metrics + sessions seeded so the route's data-gather
    step has something to work with. Pin the session secret + reset
    rate-limit buckets between tests."""
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret")
    monkeypatch.delenv("FIT_ONTOLOGY_REQUIRE_AUTH", raising=False)
    rate_limit_reset()

    db_path = tmp_path / "coach.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_test", "conal@example.com", "Conal Test")
        set_trainer_password(con, "t_test", "letmein")
        ensure_client(con, "t_test", "c_owned", name="Alex Rivers")
        today = date.today()
        rows = []
        for off in range(14, 0, -1):
            d = today - timedelta(days=off)
            rows.append({
                "id": f"m-{off}", "client_id": "c_owned", "date": d,
                "source": "garmin", "kind": MetricKind.HRV_RMSSD.value,
                "value": 55.0, "unit": "ms",
            })
        insert_metrics(con, "t_test", pd.DataFrame(rows))
        sess = pd.DataFrame([
            {"id": f"s-{i}", "client_id": "c_owned",
             "date": today - timedelta(days=i*2),
             "type": "strength", "duration_min": 45, "rpe": 6, "notes": ""}
            for i in range(3)
        ])
        insert_sessions(con, "t_test", sess)

    for mod in (
        clients_routes, metrics_routes, overrides_routes,
        recommendation_routes, thresholds_routes,
        auth_routes, share_routes, planning_routes, coach_routes,
    ):
        monkeypatch.setattr(mod, "DEFAULT_DB_PATH", db_path)

    def _ro():
        c = connect(db_path, read_only=True)
        try:
            yield c
        finally:
            c.close()

    api_mod.app.dependency_overrides[api_mod._read_only_conn] = _ro
    try:
        client = TestClient(api_mod.app)
        client.post("/api/auth/login", json={"email": "conal@example.com", "password": "letmein"})
        yield client, db_path
    finally:
        api_mod.app.dependency_overrides.pop(api_mod._read_only_conn, None)
        rate_limit_reset()


def test_draft_happy_path(coach_app, monkeypatch):
    client, _db = coach_app
    fake = _install_fake_anthropic(
        monkeypatch,
        "Hey Alex — strong week overall. Stay consistent with sleep into next week.",
    )

    r = client.post("/api/clients/c_owned/coach-message/draft")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "Alex" in data["draft"]
    assert data["model"]  # whichever Haiku model is configured

    # The structured payload we send Claude includes the first name,
    # the verdict, and the recovery score — verify build_payload
    # really did its job at the route boundary.
    call = fake.messages.create_calls[0]
    user_text = call["messages"][0]["content"]
    assert "Alex" in user_text
    assert "verdict" in user_text
    assert "recovery" in user_text


def test_draft_412_without_api_key(coach_app, monkeypatch):
    client, _db = coach_app
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Even with the SDK stub installed, the helper short-circuits on
    # missing key before construct, so we don't need the stub here.
    r = client.post("/api/clients/c_owned/coach-message/draft")
    assert r.status_code == 412


def test_draft_404_for_non_owned_client(coach_app, monkeypatch):
    client, _db = coach_app
    _install_fake_anthropic(monkeypatch, "shouldn't matter")
    r = client.post("/api/clients/c_does_not_exist/coach-message/draft")
    assert r.status_code == 404


def test_draft_429_past_the_limit(coach_app, monkeypatch):
    """COACH_DRAFT_LIMIT defaults to 20/hour. Patch to 1 so we don't
    have to hammer the route 21 times."""
    from fit_ontology import rate_limit as rl
    monkeypatch.setattr(rl.COACH_DRAFT_LIMIT, "max_attempts", 1)
    client, _db = coach_app
    _install_fake_anthropic(monkeypatch, "ok")

    r1 = client.post("/api/clients/c_owned/coach-message/draft")
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/clients/c_owned/coach-message/draft")
    assert r2.status_code == 429


def test_draft_writes_audit_row(coach_app, monkeypatch):
    client, db_path = coach_app
    _install_fake_anthropic(monkeypatch, "yo")

    r = client.post("/api/clients/c_owned/coach-message/draft")
    assert r.status_code == 200

    with connect(db_path, read_only=True) as con:
        rows = audit_log_for_trainer(con, "t_test")
    drafted = [r for r in rows if r["action"] == "coach.drafted"]
    assert len(drafted) == 1
    assert drafted[0]["target_id"] == "c_owned"
    # Model is captured in details so the audit history can show
    # "drafted on Haiku 4.5" vs "drafted on Sonnet" when the env
    # var override is in play.
    assert drafted[0]["details"]["model"]


def test_draft_uses_recent_overrides_in_payload(coach_app, monkeypatch):
    """If the trainer has a record of rejecting deloads, the payload
    handed to Claude must include that recent_overrides context so
    the prompt instructions about "respect the rejection pattern"
    have something to land on."""
    client, db_path = coach_app
    fake = _install_fake_anthropic(monkeypatch, "ok")

    # Seed an override row directly so we don't have to drive the
    # whole override roundtrip from the HTTP surface.
    with connect(db_path, read_only=False) as con:
        ov = RecommendationOverride(
            id="o_seed_1",
            client_id="c_owned",
            week_of=date.today() - timedelta(days=7),
            system_recommendation="Deload week",
            system_confidence=0.85,
            trainer_action=OverrideAction.REJECT,
            applied_load_change_pct=None,
            trainer_note="felt fine, kept training",
            created_at=datetime.now(),
        )
        insert_override(con, "t_test", ov)

    r = client.post("/api/clients/c_owned/coach-message/draft")
    assert r.status_code == 200, r.text

    user_text = fake.messages.create_calls[0]["messages"][0]["content"]
    assert "recent_overrides" in user_text
    assert "reject" in user_text  # the seeded action


def test_draft_uses_stored_weekly_recommendation_in_payload(coach_app, monkeypatch):
    client, db_path = coach_app
    fake = _install_fake_anthropic(monkeypatch, "ok")
    today = date.today()
    week_of = today - timedelta(days=today.weekday())

    with connect(db_path, read_only=False) as con:
        insert_recommendation(
            con,
            "t_test",
            Recommendation(
                id="rec_coach_sentinel",
                client_id="c_owned",
                generated_at=datetime.now(),
                week_of=week_of,
                recommendation="Sentinel coach draft verdict.",
                rationale="Stored coach rationale.",
                source_metric_ids=[],
                confidence=0.61,
            ),
        )

    r = client.post("/api/clients/c_owned/coach-message/draft")
    assert r.status_code == 200, r.text

    user_text = fake.messages.create_calls[0]["messages"][0]["content"]
    assert "Sentinel coach draft verdict." in user_text
    assert "Stored coach rationale." in user_text
