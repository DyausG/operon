-- Additive indexes over the existing immutable artifact store. No legacy backfill.
CREATE UNIQUE INDEX IF NOT EXISTS ix_supervisor_snapshot_run
    ON incident_artifact(json_extract(body_json, '$.run_id'))
    WHERE kind='SupervisorRunSnapshot';
CREATE UNIQUE INDEX IF NOT EXISTS ix_supervisor_report_run
    ON incident_artifact(json_extract(body_json, '$.run_id'))
    WHERE kind='SupervisorReport';
CREATE UNIQUE INDEX IF NOT EXISTS ix_promotion_incident_run_stage
    ON incident_artifact(incident_id, json_extract(body_json, '$.run_id'), json_extract(body_json, '$.stage'))
    WHERE kind='PromotionRecord';
CREATE UNIQUE INDEX IF NOT EXISTS ix_promotion_idempotency
    ON incident_artifact(json_extract(body_json, '$.idempotency_key'))
    WHERE kind='PromotionRecord';
CREATE UNIQUE INDEX IF NOT EXISTS ix_promotion_target
    ON incident_artifact(json_extract(body_json, '$.target_id'))
    WHERE kind='PromotionRecord';

-- Durable raw-source generation also detects changes reverted during reasoning.
-- This clock grants no artifact authority and is intentionally never reset.
CREATE TABLE IF NOT EXISTS promotion_source_clock (
    singleton INTEGER PRIMARY KEY CHECK (singleton=1),
    generation INTEGER NOT NULL CHECK (generation>=0)
);
INSERT OR IGNORE INTO promotion_source_clock VALUES (1,0);
CREATE TRIGGER IF NOT EXISTS promotion_source_plant_insert
AFTER INSERT ON plant BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_plant_update
AFTER UPDATE ON plant BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_plant_delete
AFTER DELETE ON plant BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_assembly_line_insert
AFTER INSERT ON assembly_line BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_assembly_line_update
AFTER UPDATE ON assembly_line BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_assembly_line_delete
AFTER DELETE ON assembly_line BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_equipment_insert
AFTER INSERT ON equipment BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_equipment_update
AFTER UPDATE ON equipment BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_equipment_delete
AFTER DELETE ON equipment BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_sensor_insert
AFTER INSERT ON sensor BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_sensor_update
AFTER UPDATE ON sensor BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_sensor_delete
AFTER DELETE ON sensor BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_sensor_reading_insert
AFTER INSERT ON sensor_reading BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_sensor_reading_update
AFTER UPDATE ON sensor_reading BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_sensor_reading_delete
AFTER DELETE ON sensor_reading BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_health_score_insert
AFTER INSERT ON health_score BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_health_score_update
AFTER UPDATE ON health_score BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_health_score_delete
AFTER DELETE ON health_score BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_failure_mode_insert
AFTER INSERT ON failure_mode BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_failure_mode_update
AFTER UPDATE ON failure_mode BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_failure_mode_delete
AFTER DELETE ON failure_mode BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_technician_insert
AFTER INSERT ON technician BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_technician_update
AFTER UPDATE ON technician BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_technician_delete
AFTER DELETE ON technician BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_part_insert
AFTER INSERT ON part BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_part_update
AFTER UPDATE ON part BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_part_delete
AFTER DELETE ON part BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_equipment_part_insert
AFTER INSERT ON equipment_part BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_equipment_part_update
AFTER UPDATE ON equipment_part BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_equipment_part_delete
AFTER DELETE ON equipment_part BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_work_order_insert
AFTER INSERT ON work_order BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_work_order_update
AFTER UPDATE ON work_order BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_work_order_delete
AFTER DELETE ON work_order BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_maintenance_event_insert
AFTER INSERT ON maintenance_event BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_maintenance_event_update
AFTER UPDATE ON maintenance_event BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_maintenance_event_delete
AFTER DELETE ON maintenance_event BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_part_reservation_insert
AFTER INSERT ON part_reservation BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_part_reservation_update
AFTER UPDATE ON part_reservation BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_part_reservation_delete
AFTER DELETE ON part_reservation BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_labor_booking_insert
AFTER INSERT ON labor_booking BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_labor_booking_update
AFTER UPDATE ON labor_booking BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_labor_booking_delete
AFTER DELETE ON labor_booking BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_work_package_insert
AFTER INSERT ON work_package BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_work_package_update
AFTER UPDATE ON work_package BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
CREATE TRIGGER IF NOT EXISTS promotion_source_work_package_delete
AFTER DELETE ON work_package BEGIN
    UPDATE promotion_source_clock SET generation=generation+1 WHERE singleton=1;
END;
