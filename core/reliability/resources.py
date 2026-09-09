"""Bounded local resource reads over the existing service tables.

Explicitly local: no registry selection, assignment, schedule proposal, or CMMS
write method is called. These observations neither reserve nor guarantee resources.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from core import db
from .evidence import CapabilityProvenance, DataOrigin, EvidenceCapabilities, ReadContract


class ResourceQuery(ReadContract):
    limit: int = Field(default=20, strict=True, ge=1, le=50)


class ResourceRead(ReadContract):
    asset_id: str
    availability: Literal["AVAILABLE", "UNAVAILABLE", "UNKNOWN"]
    limitations: tuple[str, ...]
    provenance: CapabilityProvenance


class PartAvailability(ReadContract):
    part_id: str
    part_number: str | None
    description: str | None
    on_hand_qty: int | None
    reserved_qty: int
    uncommitted_qty: int | None
    qty_per_service: int | None
    sufficient_for_service: bool | None
    lead_time_days: int | None


class InventoryAvailability(ResourceRead):
    parts: tuple[PartAvailability, ...] = Field(max_length=50)


class TechnicianAvailability(ReadContract):
    technician_id: str
    full_name: str
    recorded_skills: str | None
    shift: str | None
    active_booking_count: int


class WorkforceAvailability(ResourceRead):
    technicians: tuple[TechnicianAvailability, ...] = Field(max_length=50)


class MaintenanceBooking(ReadContract):
    booking_id: int
    work_order_id: int
    asset_id: str
    technician_id: str | None
    window_label: str | None
    window_min: int | None
    status: str


class MaintenanceWindows(ResourceRead):
    # Existing labels have no dated start/end or production-calendar confirmation.
    confirmed_windows: tuple[()] = ()
    existing_bookings: tuple[MaintenanceBooking, ...] = Field(max_length=50)


class ResourceCapabilities:
    def __init__(self, evidence: EvidenceCapabilities):
        self.evidence = evidence

    def _provenance(self, name: str, asset_id: str, tables: tuple[str, ...], limit: int):
        return self.evidence._provenance(
            name, tables, (DataOrigin.RECORDED, DataOrigin.DERIVED),
            {"asset_id": asset_id, "limit": limit}, f"equipment:{asset_id};limit={limit}",
        )

    @staticmethod
    def _bounded(rows, limit):
        if len(rows) > limit:
            raise ValueError("resource result exceeds requested limit; increase limit up to 50")
        return rows

    def check_part_availability(self, asset_id: str, *, limit: int = 20) -> InventoryAvailability:
        limit = ResourceQuery(limit=limit).limit
        # Reuses InventoryService's BOM relationship; also reports outstanding
        # reservations so on-hand stock is not misrepresented as uncommitted.
        with db.get_conn(self.evidence.path) as conn:
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute(
                "SELECT p.*, ep.qty_per_service, "
                "(SELECT COALESCE(SUM(pr.qty),0) FROM part_reservation pr "
                "WHERE pr.part_id=p.part_id AND pr.status='RESERVED') reserved_qty "
                "FROM equipment_part ep JOIN part p ON p.part_id=ep.part_id "
                "WHERE ep.equipment_id=? ORDER BY p.part_id LIMIT ?", (asset_id, limit + 1),
            ).fetchall()
        parts = []
        for row in self._bounded(rows, limit):
            available = (None if row['on_hand_qty'] is None else
                         max(0, row['on_hand_qty'] - row['reserved_qty']))
            required = row['qty_per_service']
            parts.append(PartAvailability(
                part_id=row['part_id'], part_number=row['part_number'], description=row['description'],
                on_hand_qty=row['on_hand_qty'], reserved_qty=row['reserved_qty'], uncommitted_qty=available,
                qty_per_service=required, lead_time_days=row['lead_time_days'],
                sufficient_for_service=None if available is None or required is None else available >= required,
            ))
        sufficient = [part.sufficient_for_service for part in parts]
        status = ("UNAVAILABLE" if False in sufficient else
                  "UNKNOWN" if not parts or None in sufficient else "AVAILABLE")
        return InventoryAvailability(
            asset_id=asset_id, availability=status, parts=tuple(parts),
            limitations=("Local recorded BOM stock only; no BOM means unknown, not available.",
                         "Reservation-adjusted snapshot; quantities require recheck at execution. Master data may be seeded demo data."),
            provenance=self._provenance("check_part_availability", asset_id,
                                        ("equipment_part", "part", "part_reservation"), limit),
        )

    def inspect_available_technicians(self, asset_id: str, *, limit: int = 20) -> WorkforceAvailability:
        limit = ResourceQuery(limit=limit).limit
        asset = self.evidence.get_asset_context(asset_id)
        with db.get_conn(self.evidence.path) as conn:
            conn.execute("PRAGMA query_only=ON")
            # Exact recorded class skill only. The legacy assignment method's
            # on-shift fallback is not proof of technical qualification.
            rows = conn.execute(
                "SELECT t.*, (SELECT COUNT(*) FROM labor_booking b WHERE b.technician_id=t.technician_id "
                "AND b.status IN ('BOOKED','STARTED')) booking_count FROM technician t "
                "WHERE t.available=1 AND t.plant_id=? AND "
                "instr(',' || replace(upper(t.skills),' ','') || ',', ',' || ? || ',') > 0 "
                "ORDER BY t.technician_id LIMIT ?",
                (asset.plant_id, asset.asset_type, limit + 1),
            ).fetchall()
        technicians = tuple(TechnicianAvailability(
            technician_id=row['technician_id'], full_name=row['full_name'], recorded_skills=row['skills'],
            shift=row['shift'], active_booking_count=row['booking_count'],
        ) for row in self._bounded(rows, limit))
        return WorkforceAvailability(
            asset_id=asset_id,
            availability="UNKNOWN" if technicians or asset.asset_type is None else "UNAVAILABLE",
            technicians=technicians,
            limitations=("Only same-plant available roster entries with the exact recorded class skill are listed.",
                         "Shift dates, qualification expiry, and dated booking overlaps are unknown. Roster may be seeded demo data; no assignment made."),
            provenance=self._provenance("inspect_available_technicians", asset_id,
                                        ("equipment", "technician", "labor_booking"), limit),
        )

    def inspect_maintenance_windows(self, asset_id: str, *, limit: int = 20) -> MaintenanceWindows:
        limit = ResourceQuery(limit=limit).limit
        asset = self.evidence.get_asset_context(asset_id)
        with db.get_conn(self.evidence.path) as conn:
            conn.execute("PRAGMA query_only=ON")
            rows = conn.execute(
                "SELECT b.*, wo.equipment_id FROM labor_booking b "
                "JOIN work_order wo ON wo.wo_id=b.wo_id JOIN equipment e ON e.equipment_id=wo.equipment_id "
                "WHERE e.line_id=? AND b.status IN ('BOOKED','STARTED') ORDER BY b.booking_id LIMIT ?",
                (asset.line_id, limit + 1),
            ).fetchall()
        bookings = tuple(MaintenanceBooking(
            booking_id=row['booking_id'], work_order_id=row['wo_id'], asset_id=row['equipment_id'],
            technician_id=row['technician_id'], window_label=row['window_label'],
            window_min=row['window_min'], status=row['status'],
        ) for row in self._bounded(rows, limit))
        return MaintenanceWindows(
            asset_id=asset_id, availability="UNKNOWN", existing_bookings=bookings,
            limitations=("Production calendar and dated maintenance windows are not persisted.",
                         "Same-line booking labels are conflict clues, not confirmed windows or proof of availability."),
            provenance=self._provenance("inspect_maintenance_windows", asset_id,
                                        ("equipment", "work_order", "labor_booking"), limit),
        )
