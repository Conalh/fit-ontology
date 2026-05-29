"""Server-side Ask chat sessions (Phase 7b).

The Ask FitOntology conversation history lives in the ``ask_sessions``
table, not in the request body. The browser round-trips only an opaque
session_id, so a tampered client can't inject fake tool_result /
assistant context into the model's view of the conversation.

Contracts pinned:
  1. A first turn with no session_id mints one and persists the stream
     server-side; the response carries the id but NOT the messages.
  2. Continuing with that id loads the prior history and feeds it to the
     model — the stored stream grows across turns.
  3. A session_id that isn't the calling trainer's (unknown or another
     trainer's) is a 404, resolved before the LLM is called.
  4. An over-long conversation is refused with 409.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fit_ontology.api as api_mod
from fit_ontology.db import (
    connect,
    create_ask_session,
    insert_trainer,
    load_ask_session,
    set_trainer_password,
)
from fit_ontology.rate_limit import reset as rate_limit_reset
from fit_ontology.routes import ask as ask_routes
from fit_ontology.routes import auth as auth_routes


class _Recorder:
    """Captures the ``messages`` list passed to each Anthropic create()
    call so a test can assert the model saw the server-side history."""

    def __init__(self) -> None:
        self.calls: list = []


def _fake_anthropic_module(recorder: _Recorder, reply: str = "Here you go."):
    class _Block:
        def __init__(self, **kw):
            self.__dict__.update(kw)

        def model_dump(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _Messages:
        def create(self, **kwargs):
            # Snapshot the outer list — ask() keeps appending to the same
            # list object after create() returns, so storing the reference
            # would capture later mutations too.
            recorder.calls.append(list(kwargs.get("messages") or []))
            return _Resp([_Block(type="text", text=reply)])

    class _Client:
        def __init__(self, **kw):
            self.messages = _Messages()

    return types.SimpleNamespace(Anthropic=lambda **kw: _Client())


@pytest.fixture()
def ask_app(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FIT_ONTOLOGY_SESSION_SECRET", "test-secret")
    monkeypatch.delenv("FIT_ONTOLOGY_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("FIT_ONTOLOGY_DEMO_MODE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    rate_limit_reset()

    db_path = tmp_path / "ask.duckdb"
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, "t_alice", "alice@example.com", "Alice")
        set_trainer_password(con, "t_alice", "letmein")
        insert_trainer(con, "t_bob", "bob@example.com", "Bob")
        set_trainer_password(con, "t_bob", "letmein")

    for mod in (ask_routes, auth_routes):
        monkeypatch.setattr(mod, "DEFAULT_DB_PATH", db_path)
    import fit_ontology.assistant as assistant_mod
    monkeypatch.setattr(assistant_mod, "DEFAULT_DB_PATH", db_path)

    recorder = _Recorder()
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module(recorder))

    client = TestClient(api_mod.app)
    yield client, db_path, recorder
    rate_limit_reset()


def _login(client: TestClient, email: str) -> None:
    r = client.post("/api/auth/login", json={"email": email, "password": "letmein"})
    assert r.status_code == 200, r.text


def test_first_turn_mints_session_and_hides_stream(ask_app):
    client, db_path, _ = ask_app
    _login(client, "alice@example.com")

    r = client.post("/api/ask", json={"question": "who needs a deload?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "Here you go."
    assert body["session_id"].startswith("ask_")
    # The message stream must NOT be returned to the client.
    assert "messages" not in body

    # Persisted server-side: user turn + assistant reply.
    with connect(db_path, read_only=True) as con:
        stored = load_ask_session(con, "t_alice", body["session_id"])
    assert stored is not None
    assert len(stored) == 2
    assert stored[0] == {"role": "user", "content": "who needs a deload?"}


def test_continuing_session_loads_prior_history(ask_app):
    client, db_path, recorder = ask_app
    _login(client, "alice@example.com")

    first = client.post("/api/ask", json={"question": "q1"})
    sid = first.json()["session_id"]

    second = client.post("/api/ask", json={"question": "q2", "session_id": sid})
    assert second.status_code == 200, second.text
    assert second.json()["session_id"] == sid

    # The second LLM call must have been handed the prior turn's history,
    # loaded from the server — not an empty or client-supplied list.
    second_call_messages = recorder.calls[-1]
    assert {"role": "user", "content": "q1"} in second_call_messages
    assert second_call_messages[-1] == {"role": "user", "content": "q2"}

    # And the stored stream grew to four messages (q1, a1, q2, a2).
    with connect(db_path, read_only=True) as con:
        stored = load_ask_session(con, "t_alice", sid)
    assert len(stored) == 4


def test_cross_trainer_session_is_404(ask_app):
    client, _db, _ = ask_app
    _login(client, "alice@example.com")
    sid = client.post("/api/ask", json={"question": "mine"}).json()["session_id"]

    # Bob logs in and tries to continue Alice's conversation.
    _login(client, "bob@example.com")
    r = client.post("/api/ask", json={"question": "give me hers", "session_id": sid})
    assert r.status_code == 404


def test_unknown_session_is_404(ask_app):
    client, _db, _ = ask_app
    _login(client, "alice@example.com")
    r = client.post("/api/ask", json={"question": "hi", "session_id": "ask_nope"})
    assert r.status_code == 404


def test_overlong_conversation_is_409(ask_app):
    client, db_path, _ = ask_app
    _login(client, "alice@example.com")

    # Seed a session already at the message cap.
    long_stream = [{"role": "user", "content": f"m{i}"} for i in range(40)]
    with connect(db_path, read_only=False) as con:
        sid = create_ask_session(con, "t_alice", long_stream)

    r = client.post("/api/ask", json={"question": "one more", "session_id": sid})
    assert r.status_code == 409
