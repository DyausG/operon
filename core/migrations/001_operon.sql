CREATE TABLE IF NOT EXISTS incident (
    incident_id TEXT PRIMARY KEY,
    admission_key TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN (
        'OPEN','INVESTIGATING','AWAITING_EVIDENCE','DIAGNOSIS_VALIDATED','PLANNING',
        'INTERVENTION_VALIDATED','AWAITING_APPROVAL','READY','EXECUTING','OBSERVING',
        'CLOSED','ESCALATED','EXECUTION_FAILED','CANCELLED')),
    revision INTEGER NOT NULL CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state_json TEXT NOT NULL CHECK (json_valid(state_json))
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_incident_active_admission
    ON incident(admission_key) WHERE phase NOT IN ('CLOSED','CANCELLED');
CREATE INDEX IF NOT EXISTS ix_incident_phase ON incident(phase);
CREATE TABLE IF NOT EXISTS incident_artifact (
    artifact_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incident(incident_id),
    kind TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    body_json TEXT NOT NULL CHECK (json_valid(body_json))
);
CREATE INDEX IF NOT EXISTS ix_artifact_incident ON incident_artifact(incident_id);
CREATE TABLE IF NOT EXISTS incident_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL REFERENCES incident(incident_id),
    created_at TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json))
);
CREATE INDEX IF NOT EXISTS ix_event_incident ON incident_event(incident_id, event_id);
CREATE TABLE IF NOT EXISTS approval_decision (
    decision_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incident(incident_id),
    intervention_id TEXT NOT NULL REFERENCES incident_artifact(artifact_id),
    intervention_hash TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    body_json TEXT NOT NULL CHECK (json_valid(body_json))
);
CREATE TABLE IF NOT EXISTS execution_receipt (
    receipt_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incident(incident_id),
    intervention_id TEXT NOT NULL REFERENCES incident_artifact(artifact_id),
    operation_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('CLAIMED','CONFIRMED','FAILED','UNKNOWN')),
    created_at TEXT NOT NULL,
    body_json TEXT NOT NULL CHECK (json_valid(body_json))
);
CREATE TRIGGER IF NOT EXISTS immutable_incident_artifact
BEFORE UPDATE ON incident_artifact BEGIN
    SELECT RAISE(ABORT, 'incident artifacts are immutable');
END;
CREATE TRIGGER IF NOT EXISTS immutable_incident_event
BEFORE UPDATE ON incident_event BEGIN
    SELECT RAISE(ABORT, 'incident events are append-only');
END;
CREATE TRIGGER IF NOT EXISTS immutable_approval_decision
BEFORE UPDATE ON approval_decision BEGIN
    SELECT RAISE(ABORT, 'approval decisions are immutable');
END;
