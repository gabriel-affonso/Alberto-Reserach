from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from alberto.db.connection import connect
from alberto.db.migrations import apply_migrations
from alberto.db.repositories import AlbertoRepository


@pytest.fixture()
def migrated_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "alberto.sqlite3")
    apply_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def repo(migrated_conn: sqlite3.Connection) -> AlbertoRepository:
    return AlbertoRepository(migrated_conn)
