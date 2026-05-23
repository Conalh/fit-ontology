"""Per-request DuckDB connection dependency.

Every read endpoint takes a fresh read-only connection via this
dependency and closes it on response. We don't pool — DuckDB is
single-writer and the cached-singleton dance the Streamlit dashboard
uses doesn't translate to multi-process ASGI. The overhead is
~milliseconds, which is fine for this scale.
"""
from __future__ import annotations

from collections.abc import Iterator

import duckdb

from ..db import DEFAULT_DB_PATH, connect


def read_only_conn() -> Iterator[duckdb.DuckDBPyConnection]:
    """Per-request read-only connection. Closed in the dependency's
    teardown so we don't leak handles across requests."""
    con = connect(DEFAULT_DB_PATH, read_only=True)
    try:
        yield con
    finally:
        con.close()
