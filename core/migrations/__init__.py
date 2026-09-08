"""Small, atomic, versioned SQLite migrations; no dependency on a framework."""
from pathlib import Path
import sqlite3


def apply_migrations(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise RuntimeError("migrations require a connection without an active transaction")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migration "
                     "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        for path in sorted(Path(__file__).parent.glob("[0-9]*_*.sql")):
            if conn.execute("SELECT 1 FROM schema_migration WHERE version=?", (path.stem,)).fetchone():
                continue
            # executescript implicitly commits; complete_statement lets triggers and
            # multiline SQL execute inside the same transaction as the ledger row.
            statement = ""
            for line in path.read_text().splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    conn.execute(statement)
                    statement = ""
            if statement.strip():
                raise ValueError(f"incomplete SQL in {path.name}")
            conn.execute("INSERT INTO schema_migration VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                         (path.stem,))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
