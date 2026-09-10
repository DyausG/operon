-- Step 13C: dependency-scoped source freshness. Additive only; no backfill.
--
-- Freshness now lives in JSON artifact fields (Evidence.source_dependencies and
-- SupervisorRunSnapshot.source_dependency_manifest). Historical artifacts keep their
-- legacy whole-store source_state_hash as metadata and are never rewritten; the
-- promotion_source_clock table and triggers from migration 004 are retained
-- untouched but are no longer consulted by any freshness check.
--
-- These indexes back the exact dependency reads that are replayed on every
-- reuse, run-completion and promotion revalidation (see core/reliability/freshness.py).
CREATE INDEX IF NOT EXISTS ix_health_score_equipment_scored
    ON health_score(equipment_id, scored_at, score_id);
CREATE INDEX IF NOT EXISTS ix_work_order_equipment_created
    ON work_order(equipment_id, created_at, wo_id);
CREATE INDEX IF NOT EXISTS ix_maintenance_event_wo_created
    ON maintenance_event(wo_id, created_at, event_id);
CREATE INDEX IF NOT EXISTS ix_part_reservation_wo_status
    ON part_reservation(wo_id, status);
