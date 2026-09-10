-- Step 14: outcome verification and autonomous closure. Additive only; no backfill.
--
-- ObservationPlan and Outcome live in the existing immutable artifact store. These
-- unique partial indexes make the application's idempotency durable: exactly one
-- observation plan per CONFIRMED execution receipt, and at most one authoritative
-- outcome per plan. A second worker that races the verifier cannot insert a
-- conflicting record around the application transaction. The health-score window
-- read replayed by outcome freshness checks is already covered by
-- ix_health_score_equipment_scored (migration 006).
CREATE UNIQUE INDEX IF NOT EXISTS ix_observation_plan_receipt
    ON incident_artifact(json_extract(body_json, '$.receipt_id'))
    WHERE kind='ObservationPlan';
CREATE UNIQUE INDEX IF NOT EXISTS ix_outcome_plan
    ON incident_artifact(json_extract(body_json, '$.plan_id'))
    WHERE kind='Outcome';
CREATE INDEX IF NOT EXISTS ix_outcome_incident
    ON incident_artifact(incident_id, kind)
    WHERE kind IN ('Outcome','ObservationPlan');
