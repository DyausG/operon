"""Migration 008 on fresh, existing (pre-PRISM) and repeatedly migrated databases, plus restart."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from core import db
from core.migrations import apply_migrations

PRISM_TABLES = {"prism_session", "prism_turn", "prism_run", "prism_effect", "prism_event"}


def tables(path: Path) -> set[str]:
    with db.get_conn(path) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def versions(path: Path) -> list[str]:
    with db.get_conn(path) as conn:
        return [r[0] for r in conn.execute("SELECT version FROM schema_migration ORDER BY version")]


def test_fresh_database_gets_the_prism_schema(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_schema(path)
    assert PRISM_TABLES <= tables(path) and versions(path)[-1] == "008_prism_runtime"
    with db.get_conn(path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert {"terminal_prism_run", "immutable_prism_turn", "immutable_prism_event", "terminal_prism_effect"} <= triggers


def test_existing_pre_prism_database_is_migrated_in_place(tmp_path):
    path = tmp_path / "existing.db"
    with db.get_conn(path) as conn:
        conn.executescript(db.SCHEMA)
        conn.execute("INSERT INTO plant VALUES ('p1','Existing plant','UTC')")
    # Apply every migration except 008, exactly as a Stage 0 deployment would have.
    with db.get_conn(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migration (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    with db.get_conn(path) as conn:
        apply_migrations(conn)
    with db.get_conn(path) as conn:
        conn.execute("DELETE FROM schema_migration WHERE version='008_prism_runtime'")
        for table in PRISM_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    assert "008_prism_runtime" not in versions(path) and not (PRISM_TABLES & tables(path))
    db.init_schema(path)
    assert PRISM_TABLES <= tables(path) and versions(path)[-1] == "008_prism_runtime"
    with db.get_conn(path) as conn:
        assert conn.execute("SELECT plant_name FROM plant").fetchone()[0] == "Existing plant"


def test_repeated_migration_and_restart_are_idempotent(tmp_path):
    path = tmp_path / "repeat.db"
    for _ in range(3):
        db.init_schema(path)
    assert versions(path).count("008_prism_runtime") == 1
    with db.get_conn(path) as conn:
        conn.execute("INSERT INTO prism_session (session_id,incident_id,status,current_revision,metadata_json,created_at,"
                     "updated_at) VALUES ('s1',NULL,'ACTIVE',3,'{}','t','t')")
    db.init_schema(path)   # "restart"
    with db.get_conn(path) as conn:
        assert conn.execute("SELECT current_revision FROM prism_session WHERE session_id='s1'").fetchone()[0] == 3
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_schema_refuses_illegal_states_and_rewrites(tmp_path):
    path = tmp_path / "guard.db"
    db.init_schema(path)
    with db.get_conn(path) as conn:
        conn.execute("INSERT INTO prism_session (session_id,incident_id,status,current_revision,metadata_json,created_at,"
                     "updated_at) VALUES ('s1',NULL,'ACTIVE',1,'{}','t','t')")
        conn.execute("INSERT INTO prism_turn (turn_id,session_id,revision,request_id,idempotency_key,content_type,content,"
                     "content_hash,metadata_json,fast_path_json,created_at) VALUES ('t1','s1',1,'r','k','text','c','h','{}','{}','t')")
        try:
            conn.execute("INSERT INTO prism_run (run_id,session_id,turn_id,revision,attempt,role,status,created_at,updated_at)"
                         " VALUES ('r1','s1','t1',1,1,'slow','BOGUS','t','t')")
            raise AssertionError("illegal status accepted")
        except sqlite3.IntegrityError:
            pass
        conn.execute("INSERT INTO prism_run (run_id,session_id,turn_id,revision,attempt,role,status,created_at,updated_at)"
                     " VALUES ('r1','s1','t1',1,1,'slow','COMPLETED','t','t')")
        try:
            conn.execute("UPDATE prism_run SET status='RUNNING' WHERE run_id='r1'")
            raise AssertionError("terminal run rewritten")
        except sqlite3.IntegrityError:
            pass
        try:
            conn.execute("INSERT INTO prism_run (run_id,session_id,turn_id,revision,attempt,role,status,created_at,updated_at)"
                         " VALUES ('r2','s1','t1',1,1,'slow','QUEUED','t','t')")
            raise AssertionError("duplicate (session, revision, attempt) accepted")
        except sqlite3.IntegrityError:
            pass
