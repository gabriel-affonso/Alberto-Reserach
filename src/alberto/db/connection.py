from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def default_db_path() -> Path:
    configured = os.environ.get("ALBERTO_DB")
    if configured:
        return Path(configured).expanduser()
    return Path(os.environ.get("ALBERTO_HOME", "~/.alberto")).expanduser() / "alberto.sqlite3"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path).expanduser() if path else default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
