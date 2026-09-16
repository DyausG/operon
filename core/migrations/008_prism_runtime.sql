-- Stage 1 (Samsung PRISM Theme 5): interruptible runtime foundation. Additive only; no backfill.
--
-- One session has exactly one canonical current revision (prism_session.current_revision).
-- Turns are accepted operator input (one per revision; replayed frames dedupe on the
-- idempotency key). Runs belong permanently to one revision; a run's status may only
-- advance along the legal graph and never leaves a terminal state (trigger below), so no
-- caller can rewrite history. Effects are durable per (session, revision, idempotency key).
-- Events are the immutable audit/timeline stream. No column ever holds a provider secret.
CREATE TABLE IF NOT EXISTS prism_session (
    session_id         TEXT PRIMARY KEY,
    incident_id        TEXT REFERENCES incident(incident_id),
    status             TEXT NOT NULL CHECK (status IN ('ACTIVE','CLOSED')),
    current_revision   INTEGER NOT NULL CHECK (current_revision >= 0),
    current_turn_id    TEXT,
    canonical_revision INTEGER,
    canonical_run_id   TEXT,
    canonical_json     TEXT,
    recovery_json      TEXT,
    metadata_json      TEXT NOT NULL DEFAULT '{}',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_prism_session_incident ON prism_session(incident_id);

CREATE TABLE IF NOT EXISTS prism_turn (
    turn_id          TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES prism_session(session_id),
    revision         INTEGER NOT NULL CHECK (revision >= 1),
    request_id       TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL,
    content_type     TEXT NOT NULL,
    content          TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    metadata_json    TEXT NOT NULL DEFAULT '{}',
    fast_path_json   TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE (session_id, revision),
    UNIQUE (session_id, idempotency_key)
);
CREATE TRIGGER IF NOT EXISTS immutable_prism_turn
BEFORE UPDATE ON prism_turn BEGIN
    SELECT RAISE(ABORT, 'prism turns are immutable');
END;

CREATE TABLE IF NOT EXISTS prism_run (
    run_id                TEXT PRIMARY KEY,
    session_id            TEXT NOT NULL REFERENCES prism_session(session_id),
    turn_id               TEXT NOT NULL REFERENCES prism_turn(turn_id),
    revision              INTEGER NOT NULL CHECK (revision >= 1),
    attempt               INTEGER NOT NULL CHECK (attempt >= 1),
    role                  TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN
                              ('QUEUED','RUNNING','CANCELLING','CANCELLED','COMPLETED','FAILED','SUPERSEDED','STALE')),
    stale                 INTEGER NOT NULL DEFAULT 0 CHECK (stale IN (0,1)),
    runtime_json          TEXT,
    result_json           TEXT,
    error_json            TEXT,
    cancellation_reason   TEXT,
    recovered_from_run_id TEXT,
    deadline_at           TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    started_at            TEXT,
    superseded_at         TEXT,
    cancelled_at          TEXT,
    completed_at          TEXT,
    UNIQUE (session_id, revision, attempt)
);
CREATE INDEX IF NOT EXISTS ix_prism_run_session_status ON prism_run(session_id, status);
-- Terminal states are final: no status rewrite, no result rewrite, no resurrection.
CREATE TRIGGER IF NOT EXISTS terminal_prism_run
BEFORE UPDATE ON prism_run
WHEN OLD.status IN ('CANCELLED','COMPLETED','FAILED','SUPERSEDED','STALE') BEGIN
    SELECT RAISE(ABORT, 'terminal prism runs are immutable');
END;

CREATE TABLE IF NOT EXISTS prism_effect (
    effect_id        TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES prism_session(session_id),
    revision         INTEGER NOT NULL CHECK (revision >= 1),
    run_id           TEXT NOT NULL REFERENCES prism_run(run_id),
    tool_call_id     TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL,
    kind             TEXT NOT NULL,
    request_hash     TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('PENDING','COMPLETED','FAILED','UNKNOWN')),
    result_json      TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    completed_at     TEXT,
    UNIQUE (session_id, revision, idempotency_key)
);
CREATE TRIGGER IF NOT EXISTS terminal_prism_effect
BEFORE UPDATE ON prism_effect
WHEN OLD.status IN ('COMPLETED','FAILED') BEGIN
    SELECT RAISE(ABORT, 'completed prism effects are immutable');
END;

CREATE TABLE IF NOT EXISTS prism_event (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL REFERENCES prism_session(session_id),
    revision     INTEGER,
    turn_id      TEXT,
    run_id       TEXT,
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_prism_event_session ON prism_event(session_id, event_id);
CREATE TRIGGER IF NOT EXISTS immutable_prism_event
BEFORE UPDATE ON prism_event BEGIN
    SELECT RAISE(ABORT, 'prism events are immutable');
END;
