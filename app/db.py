"""SQLite access. The app database is migrated; the supplied file never is."""

import logging
import re
import sqlite3
from pathlib import Path

log = logging.getLogger("meridian.db")

_MIGRATION_NAME = re.compile(r"^(\d{4})_.*\.sql$")


def connect_app_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        path, timeout=5, check_same_thread=False, isolation_level=None
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    if str(mode).lower() != "wal":
        log.warning("write-ahead logging unavailable, using %s", mode)
        conn.execute("PRAGMA journal_mode=DELETE")
    return conn


def connect_scheduling_db(path: Path) -> sqlite3.Connection:
    """The supplied file: a plain connection, no PRAGMA writes, never migrated."""
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _migrations(migrations_dir: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for file in migrations_dir.iterdir():
        match = _MIGRATION_NAME.match(file.name)
        if match:
            found.append((int(match.group(1)), file))
    return sorted(found)


def latest_migration_version(migrations_dir: Path) -> int:
    return max((number for number, _ in _migrations(migrations_dir)), default=0)


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> int:
    """Apply every NNNN_*.sql above PRAGMA user_version, each in its own transaction."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, file in _migrations(migrations_dir):
        if number <= current:
            continue
        conn.execute("BEGIN")
        try:
            for statement in _split(file.read_text()):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version={number}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = number
    return current


def _split(script: str) -> list[str]:
    """Split a script into statements; sqlite3.complete_statement handles semicolons in text."""
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return statements
