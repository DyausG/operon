"""
Master (dimension) data for the demo fleet: one plant, one line, eight assets
across six equipment classes, their sensors, the four AI4I failure modes, a
maintenance crew (labor ontology), and the spare-parts bridge.

Vendor-neutral synthetic values only.
"""
from __future__ import annotations
from .db import get_conn, init_schema, RELIABILITY_RESET_TABLES
from .config import PLANT_NAME

# equipment_id, name, class, criticality, product_tier
EQUIPMENT = [
    ("AC-COMP-01",  "Instrument Air Compressor 01", "COMPRESSOR",  "HIGH",   "H"),
    ("CNC-MILL-07", "CNC Machining Center 07",      "CNC_MACHINE", "HIGH",   "H"),
    ("HYD-PUMP-03", "Hydraulic Power Unit 03",      "PUMP",        "MEDIUM", "M"),
    ("COOL-PMP-09", "Coolant Circulation Pump 09",  "PUMP",        "MEDIUM", "L"),
    ("WELD-ROB-05", "Spot-Weld Robot 05",           "ROBOT",       "MEDIUM", "M"),
    ("CONV-02",     "Main Transfer Conveyor 02",    "CONVEYOR",    "LOW",    "L"),
    ("GRIND-04",    "Surface Grinder 04",           "GRINDER",     "MEDIUM", "M"),
    ("PRESS-08",    "Hydraulic Press 08",           "PRESS",       "HIGH",   "H"),
]

# Canonical mapping from simulator/model feature names to seeded sensor types.
# Persistence imports this mapping so generated readings can only reference IDs
# that the seed data actually creates.
SENSOR_FEATURES = (
    ("air_temp", "AIRTEMP", "K"),
    ("process_temp", "PROCTEMP", "K"),
    ("rot_speed", "SPEED", "rpm"),
    ("torque", "TORQUE", "Nm"),
    ("tool_wear", "TOOLWEAR", "min"),
)
SENSORS = [(sensor_type, unit) for _, sensor_type, unit in SENSOR_FEATURES]

# id, name, title, skills(CSV), shift, available
TECHNICIANS = [
    ("TECH-201", "Demo Technician 201", "Reliability Technician II", "COMPRESSOR,PUMP,ROTATING,VIBRATION", "A", 1),
    ("TECH-202", "Demo Technician 202", "CNC Maintenance Tech I",    "CNC_MACHINE,GRINDER,TOOLING",        "A", 1),
    ("TECH-203", "Demo Technician 203", "Reliability Technician I",  "COMPRESSOR,PUMP,ROTATING",           "B", 1),
    ("TECH-204", "Demo Technician 204", "Controls Engineer",         "ROBOT,PLC,CONVEYOR,PRESS",           "A", 1),
    ("TECH-205", "Demo Technician 205", "Maintenance Tech II",       "PRESS,HYDRAULICS,PUMP",              "A", 0),  # on leave
    ("TECH-206", "Demo Technician 206", "Machinist / Tooling",       "CNC_MACHINE,GRINDER,TOOLING",        "B", 1),
]

PARTS = [
    # part_id, erp_material_no, part_number, description, on_hand, lead_time_days
    ("PRT-BRG",  "MAT-100482", "DEMO-BRG-6316",  "Drive-end deep-groove ball bearing", 3,  5),
    ("PRT-TOOL", "MAT-100640", "DEMO-TOOL-1204", "Carbide turning insert (10-pack)",   14, 2),
    ("PRT-SEAL", "MAT-100521", "DEMO-SEAL-070",  "Hydraulic rod seal kit",             5,  4),
    ("PRT-CPL",  "MAT-100119", "DEMO-CPL-090",   "Flexible jaw coupling insert",       6,  3),
    ("PRT-COOL", "MAT-100777", "DEMO-LUBE-222",  "High-temp bearing grease (400g)",    12, 1),
    ("PRT-FLT",  "MAT-100913", "DEMO-FILTER-055", "Intake air filter",                 9,  2),
    ("PRT-PMPK", "MAT-100388", "DEMO-PUMP-050",  "Coolant pump rebuild kit",           1,  7),  # short stock
]

# equipment_id, part_id, qty_per_service, is_critical_spare
EQUIPMENT_PART = [
    ("AC-COMP-01",  "PRT-BRG",  1, 1), ("AC-COMP-01",  "PRT-CPL", 1, 0), ("AC-COMP-01", "PRT-FLT", 1, 0),
    ("CNC-MILL-07", "PRT-TOOL", 2, 1), ("CNC-MILL-07", "PRT-COOL",1, 0),
    ("HYD-PUMP-03", "PRT-SEAL", 1, 1), ("HYD-PUMP-03", "PRT-BRG", 1, 0),
    ("COOL-PMP-09", "PRT-PMPK", 1, 1), ("COOL-PMP-09", "PRT-SEAL",1, 0),
    ("WELD-ROB-05", "PRT-CPL",  1, 1),
    ("CONV-02",     "PRT-CPL",  1, 0),
    ("GRIND-04",    "PRT-TOOL", 1, 1),
    ("PRESS-08",    "PRT-SEAL", 2, 1),
]

# The four AI4I failure modes as governed records.
# failure_mode_id, mode_code, name, description, recommended_action, est_planned_minutes
FAILURE_MODES = [
    ("FM-OSF", "OSF", "Overstrain Failure",
     "Combined tool-wear and torque exceed the material overstrain limit for the product tier. "
     "Signature: rising torque with high accumulated tool wear (wear·torque product past threshold).",
     "Schedule planned service: replace worn tool/bearing, re-set feed & torque, verify alignment.", 45),
    ("FM-HDF", "HDF", "Heat-Dissipation Failure",
     "Insufficient heat dissipation: the process-to-air temperature differential collapses while "
     "rotational speed is low, so generated heat is not carried away.",
     "Restore cooling: clear heat-exchanger/airflow path, re-lubricate, verify coolant flow.", 40),
    ("FM-PWF", "PWF", "Power Failure",
     "Mechanical power (torque × angular speed) drifts outside the safe operating band, stressing "
     "the drivetrain toward stall or over-power trip.",
     "Inspect drive & coupling, rebalance load, verify VFD parameters and motor current.", 50),
    ("FM-TWF", "TWF", "Tool Wear Failure",
     "Cutting tool reaches end-of-life wear; surface finish and dimensional tolerance degrade and "
     "the tool is at imminent risk of breakage.",
     "Replace cutting tool/insert at the next micro-stop; re-qualify first-off part.", 30),
]

# Which failure mode each machine class trends toward (for grounding the agent).
CLASS_DEFAULT_MODE = {
    "COMPRESSOR": "FM-OSF", "CNC_MACHINE": "FM-TWF", "PUMP": "FM-HDF",
    "ROBOT": "FM-PWF", "CONVEYOR": "FM-PWF", "GRINDER": "FM-TWF", "PRESS": "FM-OSF",
}

# A deliberately small, clearly identified historical fixture.  It gives the
# investigation layer one credible prior maintenance record without pretending
# to be a CMMS history import or asserting a verified diagnostic outcome.
DEMO_MAINTENANCE_HISTORY = (
    {
        "wo_number": "DEMO-HIST-WO-0001",
        "equipment_id": "AC-COMP-01",
        "failure_mode_id": None,
        "technician_id": "TECH-201",
        "status": "COMPLETE",
        "priority": "ROUTINE",
        "created_at": "2026-08-18T14:00:00+00:00",
        "detail": "Quarterly compressor inspection; replaced the intake filter and checked coupling alignment.",
        "event_type": "PREVENTIVE",
        "note": "Scheduled demo maintenance record; equipment was returned to service. No causal diagnosis was stored.",
    },
)


def _seed_maintenance_history(conn) -> None:
    for record in DEMO_MAINTENANCE_HISTORY:
        row = conn.execute("SELECT wo_id FROM work_order WHERE wo_number=?",
                           (record["wo_number"],)).fetchone()
        if row is not None:
            continue
        cursor = conn.execute(
            "INSERT INTO work_order "
            "(wo_number,equipment_id,failure_mode_id,technician_id,status,priority,created_at,detail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            tuple(record[key] for key in (
                "wo_number", "equipment_id", "failure_mode_id", "technician_id",
                "status", "priority", "created_at", "detail",
            )),
        )
        conn.execute(
            "INSERT INTO maintenance_event "
            "(equipment_id,failure_mode_id,wo_id,event_type,created_at,note) VALUES (?,?,?,?,?,?)",
            (record["equipment_id"], record["failure_mode_id"], cursor.lastrowid,
             record["event_type"], record["created_at"], record["note"]),
        )


def seed_maintenance_history() -> None:
    """Idempotently restore the explicit historical demo fixture."""
    with get_conn() as conn:
        _seed_maintenance_history(conn)


def seed(reset: bool = False) -> None:
    """Create missing demo master data without disturbing existing state.

    ``reset=True`` remains the explicit full-demo reset path. Normal startup uses
    the default and is safe to repeat against an existing database.
    """
    init_schema()
    with get_conn() as conn:
        if reset:
            # child/transactional tables first so foreign keys never block the wipe
            for t in RELIABILITY_RESET_TABLES + ("labor_booking", "part_reservation", "work_package", "notification",
                      "alert", "maintenance_event", "work_order", "health_score", "sensor_reading",
                      "equipment_part", "sensor", "part", "technician", "failure_mode",
                      "equipment", "assembly_line", "plant"):
                conn.execute(f"DELETE FROM {t};")

        conn.execute("INSERT OR IGNORE INTO plant VALUES (?,?,?)",
                     ("US01", PLANT_NAME, "America/Chicago"))
        conn.execute("INSERT OR IGNORE INTO assembly_line VALUES (?,?,?,?)",
                     ("LINE-A", "US01", "Coil Assembly Line A", "ASSEMBLY"))

        for eid, name, cls, crit, tier in EQUIPMENT:
            conn.execute("INSERT OR IGNORE INTO equipment VALUES (?,?,?,?,?,?)",
                         (eid, "LINE-A", name, cls, crit, tier))
            for stype, unit in SENSORS:
                conn.execute("INSERT OR IGNORE INTO sensor VALUES (?,?,?,?)",
                             (f"{eid}-{stype}", eid, stype, unit))
        for row in FAILURE_MODES:
            conn.execute("INSERT OR IGNORE INTO failure_mode VALUES (?,?,?,?,?,?)", row)
        for row in TECHNICIANS:
            conn.execute("INSERT OR IGNORE INTO technician VALUES (?,?,?,?,?,?,?)",
                         (row[0], "US01", row[1], row[2], row[3], row[4], row[5]))
        for row in PARTS:
            conn.execute("INSERT OR IGNORE INTO part VALUES (?,?,?,?,?,?)", row)
        for row in EQUIPMENT_PART:
            conn.execute("INSERT OR IGNORE INTO equipment_part VALUES (?,?,?,?)", row)
        _seed_maintenance_history(conn)


if __name__ == "__main__":
    seed()
    print("Verified master data: 8 assets, 4 failure modes, 6 technicians, 7 parts.")
