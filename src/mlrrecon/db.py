"""SQLite connection and a minimal, ordered, transactional migration runner."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

DEFAULT_DB = Path("data/mlr.db")


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def migration_files() -> list[tuple[str, str]]:
    folder = resources.files("mlrrecon") / "migrations"
    files = sorted(f for f in folder.iterdir() if f.name.endswith(".sql"))
    return [(f.name.removesuffix(".sql"), f.read_text()) for f in files]


def migrate(con: sqlite3.Connection) -> list[str]:
    """Apply pending migrations in filename order; each runs in its own transaction. Returns versions applied."""
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    con.commit()
    applied = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
    done = []
    for version, sql in migration_files():
        if version in applied:
            continue
        try:
            con.executescript(f"BEGIN;\n{sql}\nINSERT INTO schema_migrations (version) VALUES ('{version}');\nCOMMIT;")
        except sqlite3.Error:
            con.rollback()
            raise
        done.append(version)
    return done
