"""Deterministic, bounded evidence capabilities for reliability investigation.

These functions read the semantic store and return typed results.  They do not
diagnose, call a model, expose SQL, or mutate plant/CMMS state.  ``EvidenceService``
is the trusted application boundary that turns an ``EvidenceRequest`` into an
immutable, provenance-bearing ``Evidence`` artifact.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import math
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from core import config, db
from core.seed_data import EQUIPMENT
from . import models as m
from .repository import IncidentRepository, content_hash, new_id, source_state_hash, utcnow


class UnsupportedEvidenceCapability(ValueError):
    pass


class InvalidEvidenceRequest(ValueError):
    pass


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class TrendDirection(str, Enum):
    RISING = "RISING"
    FALLING = "FALLING"
    STABLE = "STABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DataOrigin(str, Enum):
    MEASURED = "MEASURED"
    DERIVED = "DERIVED"
    SEEDED_DEMO = "SEEDED_DEMO"
    MODEL_PRODUCED = "MODEL_PRODUCED"
    RECORDED = "RECORDED"
    SIMULATED = "SIMULATED"


class ReadContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_version: Literal[1] = 1


class CapabilityProvenance(ReadContract):
    capability: str
    source_system: str
    source_tables: tuple[str, ...]
    data_origins: tuple[DataOrigin, ...]
    collected_at: AwareDatetime
    observation_start: AwareDatetime | None = None
    observation_end: AwareDatetime | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    locator: str


class SensorReading(ReadContract):
    asset_id: str
    sensor_id: str
    sensor_type: str
    timestamp: AwareDatetime
    value: float
    unit: str
    quality: str


class SensorContext(ReadContract):
    sensor_id: str
    sensor_type: str
    unit: str
    latest_reading: SensorReading | None = None


class AssetContext(ReadContract):
    asset_id: str
    availability: Availability
    asset_name: str | None = None
    asset_type: str | None = None
    criticality: str | None = None
    product_tier: str | None = None
    plant_id: str | None = None
    plant_name: str | None = None
    plant_timezone: str | None = None
    line_id: str | None = None
    line_name: str | None = None
    line_type: str | None = None
    operating_state: str | None = None
    risk_state: str | None = None
    current_health: float | None = None
    current_risk: float | None = None
    latest_score_at: AwareDatetime | None = None
    sensors: tuple[SensorContext, ...] = ()
    oem_specifications_available: Literal[False] = False
    operating_limits_available: Literal[False] = False
    missing_fields: tuple[str, ...] = ()
    missing_reason: str | None = None
    provenance: CapabilityProvenance


class TelemetryStatistics(ReadContract):
    sample_count: int = Field(ge=0)
    first_value: float | None = None
    latest_value: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    absolute_delta: float | None = None
    percentage_delta: float | None = None
    trend: TrendDirection


class TelemetrySeries(ReadContract):
    sensor_id: str
    sensor_type: str
    unit: str
    availability: Availability
    readings: tuple[SensorReading, ...]
    statistics: TelemetryStatistics
    missing_reason: str | None = None


class TelemetryWindow(ReadContract):
    asset_id: str
    sensor_type: str | None = None
    requested_start: AwareDatetime | None = None
    requested_end: AwareDatetime | None = None
    requested_sample_limit: int
    availability: Availability
    series: tuple[TelemetrySeries, ...]
    missing_reason: str | None = None
    provenance: CapabilityProvenance


class MaintenanceRecord(ReadContract):
    work_order_id: int
    work_order_number: str | None
    asset_id: str
    maintenance_action: str | None
    created_at: AwareDatetime | None
    status: str
    priority: str | None
    failure_mode_id: str | None
    failure_mode_code: str | None
    failure_mode_name: str | None
    technician_id: str | None
    technician_name: str | None
    event_types: tuple[str, ...] = ()
    event_notes: tuple[str, ...] = ()
    parts: tuple[str, ...] = ()
    outcome: str | None = None
    data_origin: DataOrigin


class MaintenanceHistory(ReadContract):
    asset_id: str
    requested_limit: int
    requested_before: AwareDatetime | None = None
    availability: Availability
    records: tuple[MaintenanceRecord, ...]
    missing_reason: str | None = None
    provenance: CapabilityProvenance


class RelatedIncident(ReadContract):
    incident_id: str
    asset_ids: tuple[str, ...]
    phase: m.IncidentPhase
    severity: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    risk_score: float | None = None
    candidate_failure_mode: str | None = None
    signal_evidence_ids: tuple[str, ...] = ()
    validated_diagnosis_id: str | None = None
    validated_diagnosis: str | None = None
    intervention_ids: tuple[str, ...] = ()
    outcome_ids: tuple[str, ...] = ()
    outcome_results: tuple[str, ...] = ()


class RelatedIncidents(ReadContract):
    asset_id: str
    excluded_incident_id: str | None = None
    requested_limit: int
    availability: Availability
    incidents: tuple[RelatedIncident, ...]
    missing_reason: str | None = None
    provenance: CapabilityProvenance


class OperatingContext(ReadContract):
    asset_id: str
    availability: Availability
    plant_id: str | None = None
    plant_name: str | None = None
    plant_timezone: str | None = None
    line_id: str | None = None
    line_name: str | None = None
    line_type: str | None = None
    criticality: str | None = None
    operating_state: str | None = None
    risk_state: str | None = None
    latest_score_at: AwareDatetime | None = None
    production_calendar: None = None
    line_dependencies: None = None
    unavailable_fields: tuple[str, ...] = ("operating_state", "production_calendar", "line_dependencies")
    missing_reason: str | None = None
    provenance: CapabilityProvenance


CapabilityResult = AssetContext | TelemetryWindow | MaintenanceHistory | RelatedIncidents | OperatingContext


class EvidenceCollection(ReadContract):
    request: m.EvidenceRequest
    evidence: m.Evidence
    result: CapabilityResult
    reused: bool = False


class _EmptyQuery(ReadContract):
    pass


class _TelemetryQuery(ReadContract):
    sensor_type: str | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    sample_limit: int = Field(default=60, ge=1, le=500)

    @model_validator(mode="after")
    def valid_window(self):
        if self.start_at and self.end_at and self.end_at < self.start_at:
            raise ValueError("end_at must not precede start_at")
        return self


class _MaintenanceQuery(ReadContract):
    limit: int = Field(default=20, ge=1, le=100)
    before: AwareDatetime | None = None


class _RelatedQuery(ReadContract):
    limit: int = Field(default=20, ge=1, le=100)


SUPPORTED_CAPABILITIES = frozenset({
    "get_asset_context", "get_telemetry_window", "get_maintenance_history",
    "get_related_incidents", "get_operating_context",
})
_DEMO_ASSET_IDS = frozenset(row[0] for row in EQUIPMENT)


def _aware(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _risk_state(risk: float | None) -> str | None:
    if risk is None:
        return None
    if risk >= config.TRIGGER_THRESHOLD:
        return "CRITICAL"
    if risk >= config.WARN_THRESHOLD:
        return "WARNING"
    return "HEALTHY"


def _stats(readings: tuple[SensorReading, ...]) -> TelemetryStatistics:
    if not readings:
        return TelemetryStatistics(sample_count=0, trend=TrendDirection.INSUFFICIENT_DATA)
    values = [point.value for point in readings]
    first, latest = values[0], values[-1]
    if len(values) < 2:
        trend = TrendDirection.INSUFFICIENT_DATA
        absolute_delta = percentage_delta = None
    else:
        delta = latest - first
        absolute_delta = abs(delta)
        percentage_delta = (delta / abs(first) * 100.0) if not math.isclose(first, 0.0, abs_tol=1e-12) else None
        tolerance = max(abs(first) * 0.01, 1e-9)
        trend = (TrendDirection.STABLE if abs(delta) <= tolerance else
                 TrendDirection.RISING if delta > 0 else TrendDirection.FALLING)
    return TelemetryStatistics(
        sample_count=len(values), first_value=first, latest_value=latest,
        minimum=min(values), maximum=max(values), mean=math.fsum(values) / len(values),
        absolute_delta=absolute_delta, percentage_delta=percentage_delta, trend=trend,
    )


class EvidenceCapabilities:
    """Read-only capabilities. A path can be injected for isolated stores/tests."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path if path is not None else db.DB_PATH)

    def _provenance(self, capability: str, tables: tuple[str, ...], origins: tuple[DataOrigin, ...],
                    parameters: dict[str, JsonValue], locator: str,
                    observed: tuple[datetime | None, datetime | None] = (None, None)) -> CapabilityProvenance:
        return CapabilityProvenance(
            capability=capability, source_system="operon.sqlite", source_tables=tables,
            data_origins=origins, collected_at=utcnow(), observation_start=observed[0],
            observation_end=observed[1], parameters=parameters, locator=locator,
        )

    def get_asset_context(self, asset_id: str) -> AssetContext:
        with db.get_conn(self.path) as conn:
            asset = conn.execute(
                "SELECT e.*,l.line_name,l.line_type,p.plant_id,p.plant_name,p.timezone "
                "FROM equipment e JOIN assembly_line l ON l.line_id=e.line_id "
                "JOIN plant p ON p.plant_id=l.plant_id WHERE e.equipment_id=?", (asset_id,),
            ).fetchone()
            params = {"asset_id": asset_id}
            if asset is None:
                return AssetContext(
                    asset_id=asset_id, availability=Availability.UNAVAILABLE,
                    missing_reason="asset is not present in the equipment registry",
                    missing_fields=("asset_metadata", "sensor_inventory", "health_score"),
                    provenance=self._provenance("get_asset_context", ("equipment", "sensor", "health_score"),
                                                (DataOrigin.RECORDED,), params, f"equipment:{asset_id}"),
                )
            score = conn.execute(
                "SELECT * FROM health_score WHERE equipment_id=? "
                "ORDER BY scored_at DESC,score_id DESC LIMIT 1", (asset_id,),
            ).fetchone()
            sensors = []
            for sensor in conn.execute(
                    "SELECT * FROM sensor WHERE equipment_id=? ORDER BY sensor_type,sensor_id", (asset_id,)):
                latest = conn.execute(
                    "SELECT ts,value_eu,quality_flag FROM sensor_reading WHERE sensor_id=? "
                    "ORDER BY ts DESC,rowid DESC LIMIT 1", (sensor["sensor_id"],),
                ).fetchone()
                reading = None if latest is None else SensorReading(
                    asset_id=asset_id, sensor_id=sensor["sensor_id"], sensor_type=sensor["sensor_type"],
                    timestamp=_aware(latest["ts"]), value=latest["value_eu"], unit=sensor["unit_eu"],
                    quality=latest["quality_flag"],
                )
                sensors.append(SensorContext(sensor_id=sensor["sensor_id"], sensor_type=sensor["sensor_type"],
                                             unit=sensor["unit_eu"], latest_reading=reading))
        score_at = _aware(score["scored_at"]) if score else None
        origins = [DataOrigin.SEEDED_DEMO if asset_id in _DEMO_ASSET_IDS else DataOrigin.RECORDED]
        if score:
            origins.append(DataOrigin.MODEL_PRODUCED)
        observations = [s.latest_reading.timestamp for s in sensors if s.latest_reading]
        if score_at:
            observations.append(score_at)
        missing = ["operating_state", "oem_specifications", "operating_limits"]
        if not sensors:
            missing.append("sensor_inventory")
        if score is None:
            missing.append("health_score")
        risk = float(score["failure_prob"]) if score else None
        return AssetContext(
            asset_id=asset_id, availability=Availability.AVAILABLE,
            asset_name=asset["equipment_name"], asset_type=asset["equipment_class"],
            criticality=asset["criticality"], product_tier=asset["product_tier"],
            plant_id=asset["plant_id"], plant_name=asset["plant_name"],
            plant_timezone=asset["timezone"], line_id=asset["line_id"],
            line_name=asset["line_name"], line_type=asset["line_type"],
            risk_state=_risk_state(risk), current_health=float(score["health_score"]) if score else None,
            current_risk=risk, latest_score_at=score_at, sensors=tuple(sensors),
            missing_fields=tuple(missing),
            provenance=self._provenance(
                "get_asset_context", ("plant", "assembly_line", "equipment", "sensor", "sensor_reading", "health_score"),
                tuple(origins), params, f"equipment:{asset_id}",
                (min(observations) if observations else None, max(observations) if observations else None),
            ),
        )

    def get_telemetry_window(self, asset_id: str, *, sensor_type: str | None = None,
                             start_at: datetime | None = None, end_at: datetime | None = None,
                             sample_limit: int = 60) -> TelemetryWindow:
        query = _TelemetryQuery(sensor_type=sensor_type, start_at=start_at,
                                end_at=end_at, sample_limit=sample_limit)
        normalized_type = query.sensor_type.upper() if query.sensor_type else None
        with db.get_conn(self.path) as conn:
            sql = "SELECT * FROM sensor WHERE equipment_id=?"
            args: list[object] = [asset_id]
            if normalized_type:
                sql += " AND upper(sensor_type)=?"
                args.append(normalized_type)
            sql += " ORDER BY sensor_type,sensor_id"
            sensor_rows = conn.execute(sql, tuple(args)).fetchall()
            series: list[TelemetrySeries] = []
            for sensor in sensor_rows:
                point_sql = (
                    "SELECT ts,value_eu,quality_flag,rowid FROM sensor_reading "
                    "WHERE sensor_id=?"
                )
                point_args: list[object] = [sensor["sensor_id"]]
                if query.start_at:
                    point_sql += " AND ts>=?"
                    point_args.append(_iso(query.start_at))
                if query.end_at:
                    point_sql += " AND ts<=?"
                    point_args.append(_iso(query.end_at))
                point_sql += " ORDER BY ts DESC,rowid DESC LIMIT ?"
                point_args.append(query.sample_limit)
                rows = list(reversed(conn.execute(point_sql, tuple(point_args)).fetchall()))
                readings = tuple(SensorReading(
                    asset_id=asset_id, sensor_id=sensor["sensor_id"], sensor_type=sensor["sensor_type"],
                    timestamp=_aware(row["ts"]), value=row["value_eu"], unit=sensor["unit_eu"],
                    quality=row["quality_flag"],
                ) for row in rows)
                statistics = _stats(readings)
                availability = (Availability.AVAILABLE if statistics.sample_count >= 2 else
                                Availability.PARTIAL if statistics.sample_count == 1 else Availability.UNAVAILABLE)
                reason = None
                if statistics.sample_count == 0:
                    reason = "no persisted readings match the requested window"
                elif statistics.sample_count == 1:
                    reason = "one sample is available; delta and trend require at least two"
                series.append(TelemetrySeries(
                    sensor_id=sensor["sensor_id"], sensor_type=sensor["sensor_type"], unit=sensor["unit_eu"],
                    availability=availability, readings=readings, statistics=statistics, missing_reason=reason,
                ))
        all_readings = [reading for item in series for reading in item.readings]
        if not sensor_rows:
            availability, reason = Availability.UNAVAILABLE, (
                f"sensor {sensor_type!r} is not registered for asset" if sensor_type
                else "asset has no registered sensors"
            )
        elif all(item.availability == Availability.AVAILABLE for item in series):
            availability, reason = Availability.AVAILABLE, None
        else:
            availability = Availability.PARTIAL if all_readings else Availability.UNAVAILABLE
            reason = "one or more requested sensor series has insufficient persisted telemetry"
        timestamps = [point.timestamp for point in all_readings]
        params = query.model_dump(mode="json", exclude={"schema_version"}) | {"asset_id": asset_id}
        locator = (f"sensor_reading:asset={asset_id};sensor={normalized_type or '*'};"
                   f"start={params.get('start_at')};end={params.get('end_at')};limit={query.sample_limit}")
        return TelemetryWindow(
            asset_id=asset_id, sensor_type=normalized_type, requested_start=query.start_at,
            requested_end=query.end_at, requested_sample_limit=query.sample_limit,
            availability=availability, series=tuple(series), missing_reason=reason,
            provenance=self._provenance(
                "get_telemetry_window", ("sensor", "sensor_reading"), (DataOrigin.SIMULATED,),
                params, locator,
                (min(timestamps) if timestamps else None, max(timestamps) if timestamps else None),
            ),
        )

    def get_maintenance_history(self, asset_id: str, *, limit: int = 20,
                                before: datetime | None = None) -> MaintenanceHistory:
        query = _MaintenanceQuery(limit=limit, before=before)
        with db.get_conn(self.path) as conn:
            sql = (
                "SELECT wo.*,fm.mode_code,fm.failure_mode_name,t.full_name technician_name "
                "FROM work_order wo LEFT JOIN failure_mode fm ON fm.failure_mode_id=wo.failure_mode_id "
                "LEFT JOIN technician t ON t.technician_id=wo.technician_id WHERE wo.equipment_id=?"
            )
            args: list[object] = [asset_id]
            if query.before:
                sql += " AND wo.created_at<=?"
                args.append(_iso(query.before))
            sql += " ORDER BY wo.created_at DESC,wo.wo_id DESC LIMIT ?"
            args.append(query.limit)
            rows = conn.execute(sql, tuple(args)).fetchall()
            records = []
            for row in rows:
                events = conn.execute(
                    "SELECT event_type,note FROM maintenance_event WHERE wo_id=? ORDER BY created_at,event_id",
                    (row["wo_id"],),
                ).fetchall()
                parts = conn.execute(
                    "SELECT p.part_number FROM part_reservation pr JOIN part p ON p.part_id=pr.part_id "
                    "WHERE pr.wo_id=? AND pr.status IN ('ISSUED','RESERVED') ORDER BY p.part_number",
                    (row["wo_id"],),
                ).fetchall()
                origin = (DataOrigin.SEEDED_DEMO if (row["wo_number"] or "").startswith("DEMO-HIST-")
                          else DataOrigin.RECORDED)
                records.append(MaintenanceRecord(
                    work_order_id=row["wo_id"], work_order_number=row["wo_number"], asset_id=asset_id,
                    maintenance_action=row["detail"], created_at=_aware(row["created_at"]),
                    status=row["status"], priority=row["priority"], failure_mode_id=row["failure_mode_id"],
                    failure_mode_code=row["mode_code"], failure_mode_name=row["failure_mode_name"],
                    technician_id=row["technician_id"], technician_name=row["technician_name"],
                    event_types=tuple(event["event_type"] for event in events if event["event_type"]),
                    event_notes=tuple(event["note"] for event in events if event["note"]),
                    parts=tuple(part["part_number"] for part in parts),
                    # The current schema has no validated outcome/result field.
                    outcome=None, data_origin=origin,
                ))
        timestamps = [record.created_at for record in records if record.created_at]
        params = query.model_dump(mode="json", exclude={"schema_version"}) | {"asset_id": asset_id}
        origins = tuple(dict.fromkeys(record.data_origin for record in records)) or (DataOrigin.RECORDED,)
        return MaintenanceHistory(
            asset_id=asset_id, requested_limit=query.limit, requested_before=query.before,
            availability=Availability.AVAILABLE if records else Availability.UNAVAILABLE,
            records=tuple(records), missing_reason=None if records else "no persisted maintenance history for asset",
            provenance=self._provenance(
                "get_maintenance_history",
                ("work_order", "maintenance_event", "technician", "failure_mode", "part_reservation", "part"),
                origins, params, f"work_order:equipment_id={asset_id};limit={query.limit}",
                (min(timestamps) if timestamps else None, max(timestamps) if timestamps else None),
            ),
        )

    def get_related_incidents(self, asset_id: str, *, exclude_incident_id: str | None = None,
                              limit: int = 20) -> RelatedIncidents:
        query = _RelatedQuery(limit=limit)
        repository = IncidentRepository(self.path)
        incidents = []
        for incident in repository.list_incidents_for_equipment(
                asset_id, exclude_incident_id=exclude_incident_id, limit=query.limit):
            artifacts = repository.list_artifacts(incident.id)
            signals = [a for a in artifacts if isinstance(a, m.Evidence) and a.kind == "model_signal"]
            accepted = [a for a in artifacts if isinstance(a, m.Diagnosis) and a.status == "ACCEPTED"]
            interventions = [a for a in artifacts if isinstance(a, m.Intervention)]
            outcomes = [a for a in artifacts if isinstance(a, m.Outcome)]
            signal = m.ModelSignal.model_validate(signals[-1].payload) if signals else None
            diagnosis = accepted[-1] if accepted else None
            incidents.append(RelatedIncident(
                incident_id=incident.id, asset_ids=incident.equipment_ids, phase=incident.phase,
                severity=incident.severity, created_at=incident.created_at, updated_at=incident.updated_at,
                risk_score=signal.risk_score if signal else None,
                candidate_failure_mode=signal.candidate_failure_mode if signal else None,
                signal_evidence_ids=tuple(item.id for item in signals),
                validated_diagnosis_id=diagnosis.id if diagnosis else None,
                validated_diagnosis=diagnosis.conclusion if diagnosis else None,
                intervention_ids=tuple(item.id for item in interventions),
                outcome_ids=tuple(item.id for item in outcomes),
                outcome_results=tuple(item.result for item in outcomes),
            ))
        params: dict[str, JsonValue] = {
            "asset_id": asset_id, "exclude_incident_id": exclude_incident_id, "limit": query.limit,
        }
        observations = [item.updated_at for item in incidents]
        return RelatedIncidents(
            asset_id=asset_id, excluded_incident_id=exclude_incident_id,
            requested_limit=query.limit,
            availability=Availability.AVAILABLE if incidents else Availability.UNAVAILABLE,
            incidents=tuple(incidents), missing_reason=None if incidents else "no other persisted incidents for asset",
            provenance=self._provenance(
                "get_related_incidents", ("incident", "incident_artifact"), (DataOrigin.DERIVED,),
                params, f"incident:equipment_id={asset_id};exclude={exclude_incident_id};limit={query.limit}",
                (min(observations) if observations else None, max(observations) if observations else None),
            ),
        )

    def get_operating_context(self, asset_id: str) -> OperatingContext:
        asset = self.get_asset_context(asset_id)
        params = {"asset_id": asset_id}
        if asset.availability == Availability.UNAVAILABLE:
            return OperatingContext(
                asset_id=asset_id, availability=Availability.UNAVAILABLE,
                missing_reason="asset context is unavailable",
                provenance=self._provenance(
                    "get_operating_context", ("plant", "assembly_line", "equipment", "health_score"),
                    (DataOrigin.RECORDED,), params, f"equipment:{asset_id}"),
            )
        origins = ((DataOrigin.SEEDED_DEMO if asset_id in _DEMO_ASSET_IDS else DataOrigin.RECORDED),)
        if asset.current_risk is not None:
            origins += (DataOrigin.MODEL_PRODUCED,)
        return OperatingContext(
            asset_id=asset_id, availability=Availability.PARTIAL,
            plant_id=asset.plant_id, plant_name=asset.plant_name, plant_timezone=asset.plant_timezone,
            line_id=asset.line_id, line_name=asset.line_name, line_type=asset.line_type,
            criticality=asset.criticality, risk_state=asset.risk_state,
            latest_score_at=asset.latest_score_at,
            missing_reason="operating state, production calendar, and line dependencies are not persisted",
            provenance=self._provenance(
                "get_operating_context", ("plant", "assembly_line", "equipment", "health_score"),
                origins, params, f"equipment:{asset_id};line={asset.line_id}",
                (asset.latest_score_at, asset.latest_score_at),
            ),
        )

    def validate_parameters(self, capability: str, parameters: dict) -> dict[str, JsonValue]:
        if capability not in SUPPORTED_CAPABILITIES:
            supported = ", ".join(sorted(SUPPORTED_CAPABILITIES))
            raise UnsupportedEvidenceCapability(
                f"unsupported evidence capability {capability!r}; supported: {supported}"
            )
        model = {
            "get_asset_context": _EmptyQuery,
            "get_operating_context": _EmptyQuery,
            "get_telemetry_window": _TelemetryQuery,
            "get_maintenance_history": _MaintenanceQuery,
            "get_related_incidents": _RelatedQuery,
        }[capability].model_validate(parameters)
        return model.model_dump(mode="json", exclude={"schema_version"})

    def collect(self, capability: str, asset_id: str, parameters: dict,
                *, incident_id: str | None = None) -> CapabilityResult:
        normalized = self.validate_parameters(capability, parameters)
        if capability == "get_asset_context":
            return self.get_asset_context(asset_id)
        if capability == "get_operating_context":
            return self.get_operating_context(asset_id)
        if capability == "get_telemetry_window":
            return self.get_telemetry_window(asset_id, **normalized)
        if capability == "get_maintenance_history":
            return self.get_maintenance_history(asset_id, **normalized)
        if capability == "get_related_incidents":
            return self.get_related_incidents(asset_id, exclude_incident_id=incident_id, **normalized)
        raise AssertionError("capability validation and dispatch are out of sync")

    @staticmethod
    def parse_result(capability: str, payload: dict) -> CapabilityResult:
        cls = {
            "get_asset_context": AssetContext,
            "get_telemetry_window": TelemetryWindow,
            "get_maintenance_history": MaintenanceHistory,
            "get_related_incidents": RelatedIncidents,
            "get_operating_context": OperatingContext,
        }.get(capability)
        if cls is None:
            raise UnsupportedEvidenceCapability(capability)
        return cls.model_validate(payload)


class EvidenceService:
    """Application-owned request, collection, persistence, and resolution flow."""

    def __init__(self, repository: IncidentRepository,
                 capabilities: EvidenceCapabilities | None = None):
        self.repository = repository
        self.capabilities = capabilities or EvidenceCapabilities(repository.path)

    @staticmethod
    def _request_key(incident_id: str, requested_by: str, equipment_ids: tuple[str, ...],
                     question: str, capability: str, required_for: str,
                     parameters: dict[str, JsonValue]) -> str:
        value = {
            "incident_id": incident_id, "requested_by": requested_by,
            "equipment_ids": equipment_ids, "question": question.strip(),
            "capability": capability, "required_for": required_for, "parameters": parameters,
        }
        return "sha256:" + content_hash(value)

    def request_and_collect(self, incident_id: str, *, requested_by: m.Role,
                            equipment_ids: tuple[str, ...], question: str,
                            capability: str, required_for: Literal["diagnosis", "intervention", "outcome"],
                            parameters: dict | None = None) -> EvidenceCollection:
        if len(equipment_ids) != 1:
            raise InvalidEvidenceRequest("current evidence capabilities require exactly one asset")
        if not question.strip():
            raise InvalidEvidenceRequest("evidence question must not be blank")
        normalized = self.capabilities.validate_parameters(capability, parameters or {})
        request_key = self._request_key(
            incident_id, requested_by, equipment_ids, question, capability, required_for, normalized,
        )
        artifacts = self.repository.list_artifacts(incident_id)
        matching = [item for item in artifacts
                    if isinstance(item, m.EvidenceRequest) and item.request_key == request_key]
        previous_request = previous_evidence = None
        if matching and matching[-1].status != "OPEN":
            request = matching[-1]
            evidence = self.repository.get_artifact(incident_id, request.resolved_by_evidence_ids[0])
            assert isinstance(evidence, m.Evidence)
            with db.get_conn(self.repository.path) as conn:
                current_source = source_state_hash(conn, incident_id)
            if evidence.source_state_hash == current_source:
                return EvidenceCollection(
                    request=request, evidence=evidence,
                    result=self.capabilities.parse_result(capability, evidence.payload), reused=True,
                )
            # A stale cached read cannot satisfy a fresh promotion run. Preserve
            # both old records and append a new request/evidence generation.
            previous_request, previous_evidence = request, evidence
            matching = []

        incident = self.repository.fetch_incident(incident_id)
        if matching:
            request = matching[-1]
        else:
            request = m.EvidenceRequest(
                id=new_id(), incident_id=incident_id, created_at=utcnow(), requested_by=requested_by,
                equipment_ids=equipment_ids, question=question.strip(), capability=capability,
                parameters=normalized, request_key=request_key, required_for=required_for,
                supersedes_id=previous_request.id if previous_request else None,
            )
            incident = self.repository.add_artifact(request, expected_revision=incident.revision)

        existing = [item for item in self.repository.list_artifacts(incident_id)
                    if isinstance(item, m.Evidence) and item.request_id == request.id]
        if existing:
            evidence = existing[-1]
            result = self.capabilities.parse_result(capability, evidence.payload)
        else:
            with db.get_conn(self.repository.path) as conn:
                source_checkpoint = source_state_hash(conn, incident_id)
            result = self.capabilities.collect(
                capability, equipment_ids[0], normalized, incident_id=incident_id,
            )
            payload = result.model_dump(mode="json")
            quality = {
                Availability.AVAILABLE: "GOOD",
                Availability.PARTIAL: "SUSPECT",
                Availability.UNAVAILABLE: "MISSING",
            }[result.availability]
            origins = set(result.provenance.data_origins)
            provenance = ("DERIVED" if DataOrigin.DERIVED in origins else
                          "SIMULATED" if origins <= {DataOrigin.SIMULATED, DataOrigin.SEEDED_DEMO,
                                                     DataOrigin.MODEL_PRODUCED} else "OBSERVED")
            evidence = m.Evidence(
                id=new_id(), incident_id=incident_id, created_at=utcnow(),
                equipment_ids=equipment_ids,
                kind={
                    "get_asset_context": "operational_context",
                    "get_telemetry_window": "telemetry",
                    "get_maintenance_history": "maintenance_history",
                    "get_related_incidents": "asset_relation",
                    "get_operating_context": "operational_context",
                }[capability],
                source_uri=f"operon://evidence/{capability}",
                source_locator=result.provenance.locator,
                source_version="operon-evidence-v1", content_hash=content_hash(payload),
                observed_at=result.provenance.observation_end,
                retrieved_at=result.provenance.collected_at, quality=quality,
                provenance=provenance, source_capability=capability,
                source_system=result.provenance.source_system,
                request_id=request.id, collection_key=request_key,
                summary=self._summary(result), payload=payload,
                source_state_hash=source_checkpoint,
                supersedes_id=previous_evidence.id if previous_evidence else None,
            )
            incident = self.repository.fetch_incident(incident_id)
            incident = self.repository.add_artifact(evidence, expected_revision=incident.revision)

        resolution = m.EvidenceRequest(
            id=new_id(), incident_id=incident_id, created_at=utcnow(), requested_by=request.requested_by,
            equipment_ids=request.equipment_ids, question=request.question, capability=request.capability,
            parameters=request.parameters, request_key=request.request_key,
            required_for=request.required_for,
            status="UNAVAILABLE" if evidence.quality == "MISSING" else "SATISFIED",
            resolved_by_evidence_ids=(evidence.id,), supersedes_id=request.id,
        )
        incident = self.repository.fetch_incident(incident_id)
        self.repository.add_artifact(resolution, expected_revision=incident.revision)
        return EvidenceCollection(request=resolution, evidence=evidence, result=result)

    @staticmethod
    def _summary(result: CapabilityResult) -> str:
        if isinstance(result, TelemetryWindow):
            count = sum(item.statistics.sample_count for item in result.series)
            return f"Persisted telemetry window: {count} samples across {len(result.series)} sensor series"
        if isinstance(result, MaintenanceHistory):
            return f"Persisted maintenance history: {len(result.records)} records"
        if isinstance(result, RelatedIncidents):
            return f"Same-asset incident history: {len(result.incidents)} incidents"
        if isinstance(result, OperatingContext):
            return f"Persisted operating context for {result.asset_id}; unavailable fields remain explicit"
        return f"Persisted asset and sensor context for {result.asset_id}"


# Narrow module-level capabilities for application/tool consumers.
def get_asset_context(asset_id: str, *, path: Path | None = None) -> AssetContext:
    return EvidenceCapabilities(path).get_asset_context(asset_id)


def get_telemetry_window(asset_id: str, *, path: Path | None = None,
                         sensor_type: str | None = None,
                         start_at: datetime | None = None,
                         end_at: datetime | None = None,
                         sample_limit: int = 60) -> TelemetryWindow:
    return EvidenceCapabilities(path).get_telemetry_window(
        asset_id, sensor_type=sensor_type, start_at=start_at,
        end_at=end_at, sample_limit=sample_limit,
    )


def get_maintenance_history(asset_id: str, *, path: Path | None = None,
                            limit: int = 20,
                            before: datetime | None = None) -> MaintenanceHistory:
    return EvidenceCapabilities(path).get_maintenance_history(asset_id, limit=limit, before=before)


def get_related_incidents(asset_id: str, *, path: Path | None = None,
                          exclude_incident_id: str | None = None,
                          limit: int = 20) -> RelatedIncidents:
    return EvidenceCapabilities(path).get_related_incidents(
        asset_id, exclude_incident_id=exclude_incident_id, limit=limit,
    )


def get_operating_context(asset_id: str, *, path: Path | None = None) -> OperatingContext:
    return EvidenceCapabilities(path).get_operating_context(asset_id)
