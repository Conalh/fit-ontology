"""Per-request DuckDB connection + current-trainer dependencies.

Every read endpoint takes a fresh read-only connection via this
dependency and closes it on response. We don't pool — DuckDB is
single-writer and the cached-singleton dance the Streamlit dashboard
uses doesn't translate to multi-process ASGI. The overhead is
~milliseconds, which is fine for this scale.

``current_trainer_id`` is the single seam that resolves the calling
trainer's id. In Phase 2a (no auth yet) it returns the default
trainer that the migration seeded. Phase 2b will swap the body to
parse a signed cookie / JWT / SSO subject — route signatures don't
change, which is the point of having a dependency instead of a bare
constant.
"""
from __future__ import annotations

from collections.abc import Iterator

import duckdb

from ..db import DEFAULT_DB_PATH, DEFAULT_TRAINER_ID, connect


def read_only_conn() -> Iterator[duckdb.DuckDBPyConnection]:
    """Per-request read-only connection. Closed in the dependency's
    teardown so we don't leak handles across requests."""
    con = connect(DEFAULT_DB_PATH, read_only=True)
    try:
        yield con
    finally:
        con.close()


def current_trainer_id() -> str:
    """The trainer the current request acts as. Phase 2a placeholder —
    every request resolves to the default trainer, which the migration
    seeded and to which all legacy data was backfilled. Phase 2b will
    parse a real session token here; routes are already shaped to take
    a trainer_id and won't need to change."""
    return DEFAULT_TRAINER_ID
