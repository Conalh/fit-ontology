"""Phase 3b intake-token helpers.

M1 milestone — helper-layer tests only. The HTTP surface (mint route,
public lookup, submit) lands in M2 + M3 with its own test file.

Contracts pinned here:
  1. Helper roundtrip — create_intake_token + intake_lookup return the
     same token + trainer_id + message, with ``expired=False`` and
     ``consumed=False`` for a freshly-minted token.
  2. Unknown tokens return None (so the route can emit 404).
  3. Expired tokens are flagged ``expired=True`` rather than hidden, so
     the route can distinguish 410 (Gone) from 404 (Not Found) — same
     posture as share_lookup.
  4. A consumed token surfaces ``consumed=True`` on lookup, with the
     consumed_at timestamp populated and the same trainer_id intact,
     so the public page can render a "already submitted" message
     rather than a generic 404.
  5. consume_intake_token is atomic: the first caller wins (returns
     True), every subsequent caller for the same token gets False.
     This is the one-shot guarantee — a leaked link can't be replayed.
  6. consume_intake_token refuses an expired token even if it was
     never consumed. Defense in depth: the route already prechecks
     expiry via intake_lookup, but if a future route forgets, the
     helper still won't claim an expired row.
  7. After consume, the row stores ``consumed_client_id`` so the audit
     trail links token → client for "which intake link became which
     client".
  8. create_intake_token refuses a trainer_id with no trainers row —
     a typo here would otherwise produce a dangling token that no
     submission can use (the eventual INSERT would FK-fail anyway,
     but failing here is a clearer error).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fit_ontology.db import (
    connect,
    consume_intake_token,
    create_intake_token,
    hash_token,
    insert_trainer,
    intake_lookup,
)


def _seed_trainer(db_path: Path, trainer_id: str = "t_test") -> str:
    """Standard fixture: one trainer row. Intake tokens don't need a
    client_id at mint time, so unlike test_share.py we don't seed
    metrics or sessions."""
    with connect(db_path, read_only=False) as con:
        insert_trainer(con, trainer_id, f"{trainer_id}@example.com", "Test Trainer")
    return trainer_id


def test_create_then_lookup_roundtrip(tmp_path: Path):
    db_path = tmp_path / "intake.duckdb"
    trainer_id = _seed_trainer(db_path)

    with connect(db_path, read_only=False) as con:
        token, expires_at = create_intake_token(
            con, trainer_id, trainer_message="welcome aboard"
        )
        assert isinstance(token, str) and len(token) >= 32
        assert expires_at > datetime.utcnow()

    with connect(db_path, read_only=True) as con:
        record = intake_lookup(con, token)

    assert record is not None
    assert record["trainer_id"] == trainer_id
    assert record["trainer_message"] == "welcome aboard"
    assert record["expired"] is False
    assert record["consumed"] is False
    assert record["consumed_at"] is None


def test_unknown_token_returns_none(tmp_path: Path):
    db_path = tmp_path / "intake.duckdb"
    _seed_trainer(db_path)
    with connect(db_path, read_only=True) as con:
        assert intake_lookup(con, "not-a-real-token") is None


def test_expired_token_is_flagged_not_hidden(tmp_path: Path):
    """Expired tokens still return a record — the route uses the
    ``expired`` flag to choose 410 over 404."""
    db_path = tmp_path / "intake.duckdb"
    trainer_id = _seed_trainer(db_path)

    with connect(db_path, read_only=False) as con:
        token, _ = create_intake_token(con, trainer_id)
        con.execute(
            "UPDATE client_intake_tokens SET expires_at = ? WHERE token = ?",
            [datetime.utcnow() - timedelta(days=1), hash_token(token)],
        )

    with connect(db_path, read_only=True) as con:
        record = intake_lookup(con, token)

    assert record is not None
    assert record["expired"] is True
    assert record["consumed"] is False


def test_consumed_token_is_flagged_on_lookup(tmp_path: Path):
    db_path = tmp_path / "intake.duckdb"
    trainer_id = _seed_trainer(db_path)

    with connect(db_path, read_only=False) as con:
        token, _ = create_intake_token(con, trainer_id)
        claimed = consume_intake_token(con, token, client_id="c_new_client")
        assert claimed is True

    with connect(db_path, read_only=True) as con:
        record = intake_lookup(con, token)

    assert record is not None
    assert record["consumed"] is True
    assert record["consumed_at"] is not None
    # trainer_id stays intact so the public page can still say
    # "you've already submitted your intake to {trainer name}".
    assert record["trainer_id"] == trainer_id


def test_consume_is_atomic_single_claim(tmp_path: Path):
    """The one-shot guarantee: only the first consume wins. A leaked
    link can't onboard two clients."""
    db_path = tmp_path / "intake.duckdb"
    trainer_id = _seed_trainer(db_path)

    with connect(db_path, read_only=False) as con:
        token, _ = create_intake_token(con, trainer_id)
        first = consume_intake_token(con, token, client_id="c_first")
        second = consume_intake_token(con, token, client_id="c_second")
        third = consume_intake_token(con, token, client_id="c_third")

    assert first is True
    assert second is False
    assert third is False


def test_consume_refuses_expired_token(tmp_path: Path):
    """Defense in depth — even if the route forgets to precheck
    expiry, the helper itself refuses to claim an expired row."""
    db_path = tmp_path / "intake.duckdb"
    trainer_id = _seed_trainer(db_path)

    with connect(db_path, read_only=False) as con:
        token, _ = create_intake_token(con, trainer_id)
        con.execute(
            "UPDATE client_intake_tokens SET expires_at = ? WHERE token = ?",
            [datetime.utcnow() - timedelta(days=1), hash_token(token)],
        )
        claimed = consume_intake_token(con, token, client_id="c_late")

    assert claimed is False


def test_consume_records_client_id_for_audit(tmp_path: Path):
    """After consume, ``consumed_client_id`` is populated so we can
    answer "which intake link became which client" later."""
    db_path = tmp_path / "intake.duckdb"
    trainer_id = _seed_trainer(db_path)

    with connect(db_path, read_only=False) as con:
        token, _ = create_intake_token(con, trainer_id)
        consume_intake_token(con, token, client_id="c_audit_target")
        row = con.execute(
            "SELECT consumed_client_id FROM client_intake_tokens WHERE token = ?",
            [hash_token(token)],
        ).fetchone()

    assert row is not None
    assert row[0] == "c_audit_target"


def test_token_is_stored_hashed_not_cleartext(tmp_path: Path):
    """The DB must never hold the live token — only its SHA-256 digest.
    A read of the table (leaked backup, errant log) can't be turned into
    a usable intake link."""
    db_path = tmp_path / "intake.duckdb"
    trainer_id = _seed_trainer(db_path)

    with connect(db_path, read_only=False) as con:
        token, _ = create_intake_token(con, trainer_id)

    with connect(db_path, read_only=True) as con:
        stored = con.execute(
            "SELECT token FROM client_intake_tokens WHERE trainer_id = ?",
            [trainer_id],
        ).fetchone()[0]

    assert stored != token                 # not cleartext
    assert stored == hash_token(token)     # the digest
    assert len(stored) == 64               # sha256 hex


def test_create_refuses_unknown_trainer(tmp_path: Path):
    """Mint should fail loudly if the trainer_id doesn't exist —
    otherwise a typo produces a dangling token whose submission
    will FK-fail later, far from the cause."""
    db_path = tmp_path / "intake.duckdb"
    _seed_trainer(db_path)  # seeds t_test, NOT t_typo

    with connect(db_path, read_only=False) as con, pytest.raises(ValueError):
        create_intake_token(con, "t_typo")
