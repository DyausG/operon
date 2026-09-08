CREATE TABLE IF NOT EXISTS execution_claim (
    idempotency_key TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incident(incident_id),
    intervention_id TEXT NOT NULL REFERENCES incident_artifact(artifact_id),
    intervention_hash TEXT NOT NULL,
    step_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    executor TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('IN_FLIGHT','CONFIRMED','FAILED','UNKNOWN')),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS ix_execution_claim_incident
    ON execution_claim(incident_id, intervention_id);
CREATE INDEX IF NOT EXISTS ix_approval_intervention
    ON approval_decision(incident_id, intervention_id, created_at);
CREATE INDEX IF NOT EXISTS ix_receipt_intervention
    ON execution_receipt(incident_id, intervention_id, created_at);
CREATE TRIGGER IF NOT EXISTS immutable_execution_receipt
BEFORE UPDATE ON execution_receipt BEGIN
    SELECT RAISE(ABORT, 'execution receipts are immutable');
END;
