"""
SQLite persistence — a compact but faithful predictive-maintenance semantic model.
Column names mirror a production asset-health schema so the POC maps cleanly onto
a real deployment. The agent may only read/write through these governed tables.
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS plant (
    plant_id   TEXT PRIMARY KEY,
    plant_name TEXT NOT NULL,
    timezone   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assembly_line (
    line_id       TEXT PRIMARY KEY,
    plant_id      TEXT NOT NULL REFERENCES plant(plant_id),
    line_name     TEXT NOT NULL,
    line_type     TEXT
);
CREATE TABLE IF NOT EXISTS equipment (
    equipment_id    TEXT PRIMARY KEY,
    line_id         TEXT NOT NULL REFERENCES assembly_line(line_id),
    equipment_name  TEXT NOT NULL,
    equipment_class TEXT NOT NULL,
    criticality     TEXT DEFAULT 'MEDIUM',
    product_tier    TEXT DEFAULT 'L'          -- AI4I product quality tier L|M|H
);
CREATE TABLE IF NOT EXISTS sensor (
    sensor_id    TEXT PRIMARY KEY,
    equipment_id TEXT NOT NULL REFERENCES equipment(equipment_id),
    sensor_type  TEXT NOT NULL,
    unit_eu      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sensor_reading (
    sensor_id    TEXT NOT NULL REFERENCES sensor(sensor_id),
    ts           TEXT NOT NULL,
    value_eu     REAL NOT NULL,
    quality_flag TEXT DEFAULT 'GOOD'
);
CREATE INDEX IF NOT EXISTS ix_reading ON sensor_reading(sensor_id, ts);

CREATE TABLE IF NOT EXISTS health_score (
    score_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id  TEXT NOT NULL REFERENCES equipment(equipment_id),
    scored_at     TEXT NOT NULL,
    health_score  REAL NOT NULL,
    failure_prob  REAL NOT NULL,
    predicted_mode TEXT
);
CREATE TABLE IF NOT EXISTS failure_mode (
    failure_mode_id    TEXT PRIMARY KEY,
    mode_code          TEXT NOT NULL,      -- TWF | HDF | PWF | OSF
    failure_mode_name  TEXT NOT NULL,
    description        TEXT,
    recommended_action TEXT,
    est_planned_minutes INTEGER DEFAULT 45
);
CREATE TABLE IF NOT EXISTS technician (
    technician_id TEXT PRIMARY KEY,
    plant_id      TEXT NOT NULL REFERENCES plant(plant_id),
    full_name     TEXT NOT NULL,
    job_title     TEXT,
    skills        TEXT,                    -- CSV of certified equipment_class / skill codes
    shift         TEXT,
    available     INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS part (
    part_id        TEXT PRIMARY KEY,
    erp_material_no TEXT,
    part_number    TEXT,
    description    TEXT,
    on_hand_qty    INTEGER DEFAULT 0,
    lead_time_days INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS equipment_part (
    equipment_id      TEXT NOT NULL REFERENCES equipment(equipment_id),
    part_id           TEXT NOT NULL REFERENCES part(part_id),
    qty_per_service   INTEGER DEFAULT 1,
    is_critical_spare INTEGER DEFAULT 0,
    PRIMARY KEY (equipment_id, part_id)
);
CREATE TABLE IF NOT EXISTS work_order (
    wo_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    wo_number     TEXT,
    equipment_id  TEXT NOT NULL REFERENCES equipment(equipment_id),
    failure_mode_id TEXT REFERENCES failure_mode(failure_mode_id),
    technician_id TEXT REFERENCES technician(technician_id),
    status        TEXT DEFAULT 'OPEN',
    priority      TEXT DEFAULT 'HIGH',
    created_at    TEXT,
    detail        TEXT
);
CREATE TABLE IF NOT EXISTS maintenance_event (
    event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id  TEXT NOT NULL REFERENCES equipment(equipment_id),
    failure_mode_id TEXT REFERENCES failure_mode(failure_mode_id),
    wo_id         INTEGER REFERENCES work_order(wo_id),
    event_type    TEXT,
    created_at    TEXT,
    note          TEXT
);

-- --------------------------------------------------------------------------
-- Governed action tables — the write side of the agent's services layer.
-- Populated by the service adapters in core/services/. A real deployment can
-- back the same interfaces with an external CMMS / WMS / notification system;
-- these tables are the reference (local) implementation's store.
-- --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert (
    alert_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id  TEXT NOT NULL REFERENCES equipment(equipment_id),
    severity      TEXT DEFAULT 'HIGH',        -- LOW | MEDIUM | HIGH | CRITICAL
    summary       TEXT,
    source        TEXT DEFAULT 'agent',       -- who raised it (agent | monitor | operator)
    status        TEXT DEFAULT 'OPEN',        -- OPEN | ACKNOWLEDGED | CLOSED
    raised_at     TEXT
);
CREATE TABLE IF NOT EXISTS notification (
    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_id  TEXT,                       -- technician_id / role / address
    channel       TEXT DEFAULT 'sms',         -- sms | email | slack | dashboard
    subject       TEXT,
    body          TEXT,
    status        TEXT DEFAULT 'SENT',        -- DRAFT | SENT | FAILED
    wo_id         INTEGER REFERENCES work_order(wo_id),
    sent_at       TEXT
);
CREATE TABLE IF NOT EXISTS work_package (
    package_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    package_number TEXT,
    wo_id          INTEGER REFERENCES work_order(wo_id),
    equipment_id   TEXT NOT NULL REFERENCES equipment(equipment_id),
    status         TEXT DEFAULT 'READY',      -- READY | IN_PROGRESS | COMPLETE
    created_at     TEXT
);
CREATE TABLE IF NOT EXISTS part_reservation (
    reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    wo_id          INTEGER REFERENCES work_order(wo_id),
    part_id        TEXT NOT NULL REFERENCES part(part_id),
    qty            INTEGER DEFAULT 1,
    status         TEXT DEFAULT 'RESERVED',   -- RESERVED | ISSUED | RELEASED
    reserved_at    TEXT
);
CREATE TABLE IF NOT EXISTS labor_booking (
    booking_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    wo_id          INTEGER REFERENCES work_order(wo_id),
    technician_id  TEXT REFERENCES technician(technician_id),
    window_label   TEXT,
    window_min     INTEGER,
    status         TEXT DEFAULT 'BOOKED',     -- BOOKED | STARTED | DONE
    booked_at      TEXT
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_schema() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def reset_transactional() -> None:
    """Wipe the loop's write-back + telemetry (keep master data)."""
    with get_conn() as conn:
        for t in ("labor_booking", "part_reservation", "work_package", "notification",
                  "alert", "maintenance_event", "work_order", "health_score", "sensor_reading"):
            conn.execute(f"DELETE FROM {t};")
