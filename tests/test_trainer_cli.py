"""scripts/trainer.py admin CLI tests.

Imports the CLI's main() directly (rather than subprocess'ing) so the
coverage actually counts and exceptions surface with full tracebacks.
Each test points the CLI at a fresh temp DB by monkey-patching
``scripts.trainer.DEFAULT_DB_PATH`` — same pattern test_api.py uses
for the route modules.

Six contracts:
  1. create writes a trainer row + sets a usable password (i.e. the
     resulting hash actually authenticates).
  2. create rejects duplicate emails with a clear error pointing at
     set-password.
  3. create rejects malformed email / empty name.
  4. list dumps every trainer in created_at order.
  5. set-password rotates an existing trainer's password (new pw
     verifies; old pw stops verifying).
  6. set-password rejects unknown emails.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import scripts.trainer as trainer_cli
from fit_ontology.db import connect, get_trainer_by_email, verify_trainer_login


@pytest.fixture()
def cli_db(tmp_path: Path, monkeypatch):
    """Point the CLI at a fresh temp DuckDB. The migration in
    connect() seeds the default trainer, so every test starts with a
    one-trainer baseline rather than an empty table — matches the
    real-world state."""
    db_path = tmp_path / "cli.duckdb"
    # Initialize the DB once so the schema + default trainer are in place
    # before the CLI's own opens.
    with connect(db_path, read_only=False):
        pass
    monkeypatch.setattr(trainer_cli, "DEFAULT_DB_PATH", db_path)
    return db_path


def test_create_writes_a_usable_trainer(cli_db: Path, capsys):
    rc = trainer_cli.main([
        "create",
        "--email", "Friend@example.com",
        "--name", "Friend Trainer",
        "--password", "let-me-in-please",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Created trainer t_" in out

    # Row exists, email normalized to lowercase, password verifies.
    with connect(cli_db, read_only=True) as con:
        row = get_trainer_by_email(con, "friend@example.com")
        assert row is not None
        trainer_id, email, name, _created_at = row
        assert email == "friend@example.com"
        assert name == "Friend Trainer"
        assert verify_trainer_login(con, "friend@example.com", "let-me-in-please") == trainer_id
        # Wrong password still rejected — pins that the hash is real,
        # not a default-empty.
        assert verify_trainer_login(con, "friend@example.com", "wrong") is None


def test_create_rejects_duplicate_email(cli_db: Path, capsys):
    trainer_cli.main([
        "create", "--email", "dup@example.com", "--name", "First",
        "--password", "first-pw",
    ])
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        trainer_cli.main([
            "create", "--email", "dup@example.com", "--name", "Second",
            "--password", "second-pw",
        ])
    # SystemExit's message carries the human-readable error.
    msg = str(exc.value)
    assert "already exists" in msg
    assert "set-password" in msg, "error should point the operator at the rotation command"

    # The original trainer's password must still work — duplicate
    # create must NOT silently overwrite.
    with connect(cli_db, read_only=True) as con:
        assert verify_trainer_login(con, "dup@example.com", "first-pw") is not None
        assert verify_trainer_login(con, "dup@example.com", "second-pw") is None


def test_create_rejects_malformed_input(cli_db: Path):
    with pytest.raises(SystemExit) as exc1:
        trainer_cli.main(["create", "--email", "not-an-email", "--name", "X", "--password", "p"])
    assert "Invalid email" in str(exc1.value)

    with pytest.raises(SystemExit) as exc2:
        trainer_cli.main(["create", "--email", "ok@example.com", "--name", "  ", "--password", "p"])
    assert "Name can't be empty" in str(exc2.value)


def test_list_shows_every_trainer(cli_db: Path, capsys):
    trainer_cli.main([
        "create", "--email", "a@example.com", "--name", "A", "--password", "pwA",
    ])
    trainer_cli.main([
        "create", "--email", "b@example.com", "--name", "B", "--password", "pwB",
    ])
    capsys.readouterr()  # drain create output

    rc = trainer_cli.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    # Header + the two new trainers + the migration-seeded default.
    assert "email" in out
    assert "a@example.com" in out
    assert "b@example.com" in out
    # Default trainer seeded by the migration is there too — confirms
    # list isn't filtering anyone out.
    assert "conal.hg@gmail.com" in out


def test_set_password_rotates_the_hash(cli_db: Path, capsys):
    trainer_cli.main([
        "create", "--email", "rotate@example.com", "--name", "R",
        "--password", "original-pw",
    ])
    capsys.readouterr()

    rc = trainer_cli.main([
        "set-password", "--email", "rotate@example.com", "--password", "new-pw",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Password updated" in out

    with connect(cli_db, read_only=True) as con:
        # New password works.
        assert verify_trainer_login(con, "rotate@example.com", "new-pw") is not None
        # Old password no longer works.
        assert verify_trainer_login(con, "rotate@example.com", "original-pw") is None


def test_set_password_rejects_unknown_email(cli_db: Path):
    with pytest.raises(SystemExit) as exc:
        trainer_cli.main([
            "set-password", "--email", "ghost@example.com", "--password", "x",
        ])
    msg = str(exc.value)
    assert "No trainer" in msg
    assert "create" in msg, "error should point operator at the create command"


def test_create_rejects_both_password_flags(cli_db: Path):
    with pytest.raises(SystemExit) as exc:
        trainer_cli.main([
            "create", "--email", "x@example.com", "--name", "X",
            "--password", "p", "--prompt-password",
        ])
    assert "either" in str(exc.value)
