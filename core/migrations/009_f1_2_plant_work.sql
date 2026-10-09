-- F1.2: durable simulated-plant state and work-boundary idempotency. Additive only, no backfill.
--
-- simulator_asset_state is the memory of the sandbox plant itself. A real plant does not reset
-- when OPERON restarts, so the simulator restores each asset (mode, degradation progress,
-- tick and scenario profile) from here instead of starting healthy. It is plant-side
-- state, never read by outcome verification, and it is wiped by the demo reset.
CREATE TABLE IF NOT EXISTS simulator_asset_state (
    equipment_id          TEXT PRIMARY KEY,
    mode                  TEXT NOT NULL,
    prog                  REAL NOT NULL CHECK (prog >= 0),
    tick                  INTEGER NOT NULL CHECK (tick >= 0),
    scenario              TEXT NOT NULL,
    start_tick            INTEGER NOT NULL,
    ramp_ticks            INTEGER NOT NULL CHECK (ramp_ticks >= 1),
    intervention_response TEXT NOT NULL,
    partial_response      TEXT NOT NULL,
    field_response        TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

-- Exactly one work report per assignment: a second, possibly contradictory terminal
-- report cannot be inserted around the application transaction.
CREATE UNIQUE INDEX IF NOT EXISTS ix_work_report_assignment
    ON incident_artifact(json_extract(body_json, '$.assignment_id'))
    WHERE kind='WorkReport';

-- At most one recorded plant actuation per work report (replay after restart is idempotent).
CREATE UNIQUE INDEX IF NOT EXISTS ix_plant_actuation_report
    ON incident_artifact(json_extract(body_json, '$.report_id'))
    WHERE kind='PlantActuation';

-- Work state and idempotent replays are derived from typed events per incident.
CREATE INDEX IF NOT EXISTS ix_incident_event_type
    ON incident_event(incident_id, event_type);
