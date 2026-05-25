"""Admin CLI for managing trainer accounts.

Phase 1 of the roadmap is "Friend test: one real human (not Conal)
uses the dashboard end-to-end." Now that the app has its own auth
(Phase 2b), inviting that friend means adding a row to the trainers
table — and there's no UI for it yet (sign-up flow is Phase 6). This
CLI fills the gap.

Workflow:

    # Create a new trainer
    python scripts/trainer.py create \\
        --email friend@example.com --name "Their Name" --prompt-password
    # → share that password with them through Signal / iMessage / etc.
    # → they sign in at /login.

    # List who exists
    python scripts/trainer.py list

    # Rotate a password if they forget it
    python scripts/trainer.py set-password \\
        --email friend@example.com --prompt-password

No --password on the command line by default (getpass keeps it out of
shell history); --password is accepted for non-interactive automation.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from getpass import getpass

from fit_ontology.db import (
    DEFAULT_DB_PATH,
    connect,
    get_trainer_by_email,
    insert_trainer,
    set_trainer_password,
)


def _resolve_password(args: argparse.Namespace) -> str:
    """Get the password from --password, --prompt-password (getpass),
    or fail loudly. Trims whitespace because a clipboard-pasted
    password sometimes picks up a trailing newline that bcrypt would
    silently fold into the hash."""
    if args.password and args.prompt_password:
        raise SystemExit("Pass either --password or --prompt-password, not both.")
    if args.password:
        return args.password.strip()
    if args.prompt_password:
        pw = getpass("Password: ").strip()
        confirm = getpass("Confirm: ").strip()
        if pw != confirm:
            raise SystemExit("Passwords don't match.")
        if not pw:
            raise SystemExit("Password can't be empty.")
        return pw
    raise SystemExit("Pass --password or --prompt-password.")


def cmd_create(args: argparse.Namespace) -> int:
    """Create a new trainer row + set their password atomically.

    Email is normalized to lowercase so the verify_trainer_login query
    (which also lowercases) matches what the admin typed regardless of
    case. Duplicate email is a hard error pointing the operator at
    set-password — silently overwriting an existing trainer would let
    a typo lock out a real account."""
    email = args.email.strip().lower()
    name = args.name.strip()
    if not email or "@" not in email:
        raise SystemExit(f"Invalid email: {args.email!r}")
    if not name:
        raise SystemExit("Name can't be empty.")

    password = _resolve_password(args)

    with connect(DEFAULT_DB_PATH, read_only=False) as con:
        existing = get_trainer_by_email(con, email)
        if existing:
            raise SystemExit(
                f"A trainer with email {email!r} already exists (id={existing[0]}).\n"
                "Use 'scripts/trainer.py set-password' to rotate their password."
            )
        trainer_id = f"t_{uuid.uuid4().hex[:12]}"
        insert_trainer(con, trainer_id, email, name)
        set_trainer_password(con, trainer_id, password)

    print(f"Created trainer {trainer_id} ({email}, {name!r}).")
    print("They can sign in at /login with the password you set.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Plain-text table of every trainer. Width tuned for an 80-col
    terminal — the email field is the only one that realistically
    overflows, and a longer email pushes the columns rather than
    truncating because losing characters from an email is worse than
    losing alignment."""
    with connect(DEFAULT_DB_PATH, read_only=True) as con:
        rows = con.execute(
            """
            SELECT id, email, name, created_at,
                   CASE WHEN hashed_password IS NULL THEN 'no' ELSE 'yes' END
            FROM trainers
            ORDER BY created_at
            """
        ).fetchall()

    if not rows:
        print("(no trainers — run 'scripts/trainer.py create ...' to add one)")
        return 0

    headers = ["id", "email", "name", "created_at", "password"]
    fmt_rows = [
        [r[0], r[1], r[2], r[3].strftime("%Y-%m-%d") if r[3] else "—", r[4]]
        for r in rows
    ]
    widths = [
        max(len(headers[i]), max(len(str(row[i])) for row in fmt_rows))
        for i in range(len(headers))
    ]

    def _line(cells):
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))

    print(_line(headers))
    print(_line(["-" * w for w in widths]))
    for row in fmt_rows:
        print(_line(row))
    return 0


def cmd_set_password(args: argparse.Namespace) -> int:
    """Rotate an existing trainer's password. Identified by email
    because a human admin types emails, not synthetic IDs."""
    email = args.email.strip().lower()
    password = _resolve_password(args)

    with connect(DEFAULT_DB_PATH, read_only=False) as con:
        existing = get_trainer_by_email(con, email)
        if not existing:
            raise SystemExit(
                f"No trainer with email {email!r}. "
                "Use 'scripts/trainer.py create' first."
            )
        trainer_id = existing[0]
        set_trainer_password(con, trainer_id, password)

    print(f"Password updated for {email} (trainer {trainer_id}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage trainer accounts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Workflow:", 1)[1] if "Workflow:" in __doc__ else "",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    p_create = subs.add_parser("create", help="Create a new trainer.")
    p_create.add_argument("--email", required=True)
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--password", help="(insecure — stays in shell history)")
    p_create.add_argument(
        "--prompt-password",
        action="store_true",
        help="Prompt for the password via getpass (recommended).",
    )
    p_create.set_defaults(func=cmd_create)

    p_list = subs.add_parser("list", help="List all trainers.")
    p_list.set_defaults(func=cmd_list)

    p_set = subs.add_parser("set-password", help="Rotate a trainer's password.")
    p_set.add_argument("--email", required=True)
    p_set.add_argument("--password")
    p_set.add_argument("--prompt-password", action="store_true")
    p_set.set_defaults(func=cmd_set_password)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
