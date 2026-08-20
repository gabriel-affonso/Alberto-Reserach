from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from alberto.db.connection import connect
from alberto.db.migrations import apply_migrations
from alberto.db.repositories import AlbertoRepository


@pytest.fixture(autouse=True)
def isolate_delivery_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ALBERTO_EMAIL_PROVIDER",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "SMTP_TO",
    ):
        monkeypatch.delenv(name, raising=False)


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
