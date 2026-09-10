-- Step 13B: additive lifecycle indexes over existing immutable stores. No backfill.
-- One decision per approval requirement per actor: idempotent retries reproduce the
-- same decision; conflicting duplicates are refused in the application transaction
-- and cannot be inserted around it.
CREATE UNIQUE INDEX IF NOT EXISTS ix_approval_decision_requirement_actor
    ON approval_decision(incident_id, json_extract(body_json, '$.requirement_id'), actor_id);
CREATE INDEX IF NOT EXISTS ix_approval_requirement_intervention
    ON incident_artifact(incident_id, json_extract(body_json, '$.intervention_id'))
    WHERE kind='ApprovalRequirement';
CREATE INDEX IF NOT EXISTS ix_promotion_record_target
    ON incident_artifact(incident_id, json_extract(body_json, '$.target_id'), json_extract(body_json, '$.stage'))
    WHERE kind='PromotionRecord';
