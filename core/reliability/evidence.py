"""Deterministic, bounded evidence capabilities for reliability investigation.

These functions read the semantic store and return typed results.  They do not
diagnose, call a model, expose SQL, or mutate plant/CMMS state.  ``EvidenceService``
is the trusted application boundary that turns an ``EvidenceRequest`` into an
immutable, provenance-bearing ``Evidence`` artifact.

Step 13C: every capability performs its reads through ``freshness.SourceReads`` in
one read transaction, so the returned result and its ``SourceDependencyManifest``
describe the same rows. Freshness of stored evidence is decided by replaying those
exact reads, never by a whole-store checkpoint.
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
from .freshness import SourceReads, revalidate
from .repository import SOURCE_QUERY_KINDS, IncidentRepository, content_hash, new_id, utcnow


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
    # Application-pinned snapshot boundary; None means "latest at collection time".
    as_of: AwareDatetime | None = None
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
    as_of: AwareDatetime | None = None
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


class HealthScorePoint(ReadContract):
    asset_id: str
    score_id: int
    scored_at: AwareDatetime
    health_score: float
    failure_prob: float
    predicted_mode: str | None = None


class HealthScoreWindow(ReadContract):
    """Bounded persisted classifier scores of one asset (Step 14 outcome evidence).

    These are the engine's persisted model outputs, not physical measurements; a
    window of them can show whether the modelled risk stayed elevated, fell, or rose
    after an intervention. It cannot prove a mechanical repair.
    """
    asset_id: str
    requested_start: AwareDatetime | None = None
    requested_end: AwareDatetime | None = None
    requested_sample_limit: int
    availability: Availability
    scores: tuple[HealthScorePoint, ...]
    risk_statistics: TelemetryStatistics
    health_statistics: TelemetryStatistics
    missing_reason: str | None = None
    provenance: CapabilityProvenance


CapabilityResult = AssetContext | TelemetryWindow | MaintenanceHistory | RelatedIncidents | OperatingContext | HealthScoreWindow


class EvidenceCollection(ReadContract):
    request: m.EvidenceRequest
    evidence: m.Evidence
    result: CapabilityResult
    reused: bool = False


class _AsOfQuery(ReadContract):
    """Optional snapshot boundary for "latest" reads.

    Without it the capability reads the newest rows, which is an open-ended query
    that later same-asset writes legitimately change. The deterministic baseline
    pins the application collection time so its evidence stays reproducible while
    telemetry keeps streaming.
    """
    as_of: AwareDatetime | None = None


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


class _HealthScoreQuery(ReadContract):
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
    "get_related_incidents", "get_operating_context", "get_health_score_window",
})
_QUERY_MODELS = {
    "get_asset_context": _AsOfQuery,
    "get_operating_context": _AsOfQuery,
    "get_telemetry_window": _TelemetryQuery,
    "get_maintenance_history": _MaintenanceQuery,
    "get_related_incidents": _RelatedQuery,
    "get_health_score_window": _HealthScoreQuery,
}
_DEMO_ASSET_IDS = frozenset(row[0] for row in EQUIPMENT)


def _aware(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(timezone.utc).isoformat()


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
    """Read-only capabilities. A path can be injected for isolated stores/tests.

    Public ``get_*`` methods return results only. ``collect_with_dependencies``
    returns the result together with the application-generated dependency manifest
    of the reads that produced it; both come from the same read transaction.
    """

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

    # ------------------------------------------------------------ internals
    def _asset_context(self, reads: SourceReads, asset_id: str, as_of: datetime | None) -> AssetContext:
        bound = _iso(as_of)
        asset = reads.asset_registry(asset_id=asset_id)
        params: dict[str, JsonValue] = {"asset_id": asset_id, "as_of": bound}
        if asset is None:
            return AssetContext(
                asset_id=asset_id, as_of=as_of, availability=Availability.UNAVAILABLE,
                missing_reason="asset is not present in the equipment registry",
                missing_fields=("asset_metadata", "sensor_inventory", "health_score"),
                provenance=self._provenance("get_asset_context", ("equipment", "sensor", "health_score"),
                                            (DataOrigin.RECORDED,), params, f"equipment:{asset_id}"),
            )
        score = reads.health_score_latest(asset_id=asset_id, as_of=bound)
        sensors = []
        for sensor in reads.sensor_inventory(asset_id=asset_id):
            latest = reads.telemetry_latest(sensor_id=sensor["sensor_id"], as_of=bound)
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
            asset_id=asset_id, as_of=as_of, availability=Availability.AVAILABLE,
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
                tuple(origins), params, f"equipment:{asset_id};as_of={bound}",
                (min(observations) if observations else None, max(observations) if observations else None),
            ),
        )

    def _telemetry_window(self, reads: SourceReads, asset_id: str, query: _TelemetryQuery) -> TelemetryWindow:
        normalized_type = query.sensor_type.upper() if query.sensor_type else None
        start, end = _iso(query.start_at), _iso(query.end_at)
        sensor_rows = reads.sensor_inventory(asset_id=asset_id, sensor_type=normalized_type)
        series: list[TelemetrySeries] = []
        for sensor in sensor_rows:
            rows = reads.telemetry_window(sensor_id=sensor["sensor_id"], start_at=start, end_at=end,
                                          sample_limit=query.sample_limit)
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
                f"sensor {query.sensor_type!r} is not registered for asset" if query.sensor_type
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

    def _health_score_window(self, reads: SourceReads, asset_id: str, query: _HealthScoreQuery) -> HealthScoreWindow:
        start, end = _iso(query.start_at), _iso(query.end_at)
        rows = reads.health_score_window(asset_id=asset_id, start_at=start, end_at=end, sample_limit=query.sample_limit)
        scores = tuple(HealthScorePoint(
            asset_id=asset_id, score_id=int(row["score_id"]), scored_at=_aware(row["scored_at"]),
            health_score=float(row["health_score"]), failure_prob=float(row["failure_prob"]),
            predicted_mode=row["predicted_mode"],
        ) for row in rows)
        risk = _stats(tuple(SensorReading(asset_id=asset_id, sensor_id="risk", sensor_type="RISK", timestamp=p.scored_at,
                                          value=p.failure_prob, unit="probability", quality="GOOD") for p in scores))
        health = _stats(tuple(SensorReading(asset_id=asset_id, sensor_id="health", sensor_type="HEALTH", timestamp=p.scored_at,
                                            value=p.health_score, unit="score", quality="GOOD") for p in scores))
        count = len(scores)
        availability = (Availability.AVAILABLE if count >= 2 else
                        Availability.PARTIAL if count == 1 else Availability.UNAVAILABLE)
        reason = (None if count >= 2 else "one persisted score is available; trend requires at least two" if count == 1
                  else "no persisted health scores match the requested window")
        params = query.model_dump(mode="json", exclude={"schema_version"}) | {"asset_id": asset_id}
        timestamps = [point.scored_at for point in scores]
        return HealthScoreWindow(
            asset_id=asset_id, requested_start=query.start_at, requested_end=query.end_at,
            requested_sample_limit=query.sample_limit, availability=availability, scores=scores,
            risk_statistics=risk, health_statistics=health, missing_reason=reason,
            provenance=self._provenance(
                "get_health_score_window", ("health_score",), (DataOrigin.MODEL_PRODUCED, DataOrigin.SIMULATED),
                params, f"health_score:asset={asset_id};start={start};end={end};limit={query.sample_limit}",
                (min(timestamps) if timestamps else None, max(timestamps) if timestamps else None),
            ),
        )

    def _maintenance_history(self, reads: SourceReads, asset_id: str, query: _MaintenanceQuery) -> MaintenanceHistory:
        orders, events, parts = reads.maintenance_history(asset_id=asset_id, before=_iso(query.before), limit=query.limit)
        records = []
        for row in orders:
            origin = (DataOrigin.SEEDED_DEMO if (row["wo_number"] or "").startswith("DEMO-HIST-")
                      else DataOrigin.RECORDED)
            records.append(MaintenanceRecord(
                work_order_id=row["wo_id"], work_order_number=row["wo_number"], asset_id=asset_id,
                maintenance_action=row["detail"], created_at=_aware(row["created_at"]),
                status=row["status"], priority=row["priority"], failure_mode_id=row["failure_mode_id"],
                failure_mode_code=row["mode_code"], failure_mode_name=row["failure_mode_name"],
                technician_id=row["technician_id"], technician_name=row["technician_name"],
                event_types=tuple(event["event_type"] for event in events[row["wo_id"]] if event["event_type"]),
                event_notes=tuple(event["note"] for event in events[row["wo_id"]] if event["note"]),
                parts=tuple(part["part_number"] for part in parts[row["wo_id"]]),
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

    def _related_incidents(self, reads: SourceReads, asset_id: str, exclude_incident_id: str | None,
                           query: _RelatedQuery) -> RelatedIncidents:
        incidents = []
        for incident, artifacts in reads.related_incidents(
                asset_id=asset_id, exclude_incident_id=exclude_incident_id, limit=query.limit):
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

    def _operating_context(self, reads: SourceReads, asset_id: str, as_of: datetime | None) -> OperatingContext:
        # Reads only the registry row and latest score: sensors and readings are
        # not part of this result, so they are deliberately not dependencies.
        bound = _iso(as_of)
        asset = reads.asset_registry(asset_id=asset_id)
        params: dict[str, JsonValue] = {"asset_id": asset_id, "as_of": bound}
        if asset is None:
            return OperatingContext(
                asset_id=asset_id, as_of=as_of, availability=Availability.UNAVAILABLE,
                missing_reason="asset context is unavailable",
                provenance=self._provenance(
                    "get_operating_context", ("plant", "assembly_line", "equipment", "health_score"),
                    (DataOrigin.RECORDED,), params, f"equipment:{asset_id}"),
            )
        score = reads.health_score_latest(asset_id=asset_id, as_of=bound)
        score_at = _aware(score["scored_at"]) if score else None
        risk = float(score["failure_prob"]) if score else None
        origins = ((DataOrigin.SEEDED_DEMO if asset_id in _DEMO_ASSET_IDS else DataOrigin.RECORDED),)
        if risk is not None:
            origins += (DataOrigin.MODEL_PRODUCED,)
        return OperatingContext(
            asset_id=asset_id, as_of=as_of, availability=Availability.PARTIAL,
            plant_id=asset["plant_id"], plant_name=asset["plant_name"], plant_timezone=asset["timezone"],
            line_id=asset["line_id"], line_name=asset["line_name"], line_type=asset["line_type"],
            criticality=asset["criticality"], risk_state=_risk_state(risk),
            latest_score_at=score_at,
            missing_reason="operating state, production calendar, and line dependencies are not persisted",
            provenance=self._provenance(
                "get_operating_context", ("plant", "assembly_line", "equipment", "health_score"),
                origins, params, f"equipment:{asset_id};line={asset['line_id']};as_of={bound}",
                (score_at, score_at),
            ),
        )

    def _dispatch(self, reads: SourceReads, capability: str, asset_id: str, normalized: dict,
                  incident_id: str | None) -> CapabilityResult:
        query = _QUERY_MODELS[capability].model_validate(normalized)
        if capability == "get_asset_context":
            return self._asset_context(reads, asset_id, query.as_of)
        if capability == "get_operating_context":
            return self._operating_context(reads, asset_id, query.as_of)
        if capability == "get_telemetry_window":
            return self._telemetry_window(reads, asset_id, query)
        if capability == "get_maintenance_history":
            return self._maintenance_history(reads, asset_id, query)
        if capability == "get_related_incidents":
            return self._related_incidents(reads, asset_id, incident_id, query)
        if capability == "get_health_score_window":
            return self._health_score_window(reads, asset_id, query)
        raise AssertionError("capability validation and dispatch are out of sync")

    def _read(self, capability: str, asset_id: str, parameters: dict, incident_id: str | None):
        normalized = self.validate_parameters(capability, parameters)
        with db.get_conn(self.path) as conn:
            # One read transaction: the result and its dependency fingerprints see
            # the same committed state, so the manifest describes exactly these rows.
            conn.execute("BEGIN")
            reads = SourceReads(conn)
            result = self._dispatch(reads, capability, asset_id, normalized, incident_id)
            return result, reads.manifest()

    # -------------------------------------------------------------- public
    def get_asset_context(self, asset_id: str, *, as_of: datetime | None = None) -> AssetContext:
        return self._read("get_asset_context", asset_id, {"as_of": as_of}, None)[0]

    def get_telemetry_window(self, asset_id: str, *, sensor_type: str | None = None,
                             start_at: datetime | None = None, end_at: datetime | None = None,
                             sample_limit: int = 60) -> TelemetryWindow:
        return self._read("get_telemetry_window", asset_id, dict(
            sensor_type=sensor_type, start_at=start_at, end_at=end_at, sample_limit=sample_limit), None)[0]

    def get_maintenance_history(self, asset_id: str, *, limit: int = 20,
                                before: datetime | None = None) -> MaintenanceHistory:
        return self._read("get_maintenance_history", asset_id, dict(limit=limit, before=before), None)[0]

    def get_related_incidents(self, asset_id: str, *, exclude_incident_id: str | None = None,
                              limit: int = 20) -> RelatedIncidents:
        return self._read("get_related_incidents", asset_id, dict(limit=limit), exclude_incident_id)[0]

    def get_operating_context(self, asset_id: str, *, as_of: datetime | None = None) -> OperatingContext:
        return self._read("get_operating_context", asset_id, {"as_of": as_of}, None)[0]

    def get_health_score_window(self, asset_id: str, *, start_at: datetime | None = None,
                                end_at: datetime | None = None, sample_limit: int = 60) -> HealthScoreWindow:
        return self._read("get_health_score_window", asset_id,
                          dict(start_at=start_at, end_at=end_at, sample_limit=sample_limit), None)[0]

    def validate_parameters(self, capability: str, parameters: dict) -> dict[str, JsonValue]:
        if capability not in SUPPORTED_CAPABILITIES:
            supported = ", ".join(sorted(SUPPORTED_CAPABILITIES))
            raise UnsupportedEvidenceCapability(
                f"unsupported evidence capability {capability!r}; supported: {supported}"
            )
        model = _QUERY_MODELS[capability].model_validate(parameters)
        return model.model_dump(mode="json", exclude={"schema_version"})

    def collect(self, capability: str, asset_id: str, parameters: dict,
                *, incident_id: str | None = None) -> CapabilityResult:
        return self._read(capability, asset_id, parameters, incident_id)[0]

    def collect_with_dependencies(self, capability: str, asset_id: str, parameters: dict,
                                  *, incident_id: str | None = None
                                  ) -> tuple[CapabilityResult, m.SourceDependencyManifest]:
        """Result plus the application-generated manifest of the reads that produced it."""
        return self._read(capability, asset_id, parameters, incident_id)

    def expected_dependencies(self, conn, capability: str, asset_id: str, parameters: dict,
                              *, incident_id: str | None) -> m.SourceDependencyManifest:
        """Replay a capability's reads on an open connection; returns only the manifest.

        Used by the repository to refuse caller-supplied manifests whose dependency
        set or fingerprints differ from what the capability actually reads now.
        """
        reads = SourceReads(conn)
        self._dispatch(reads, capability, asset_id, self.validate_parameters(capability, parameters), incident_id)
        return reads.manifest()

    @staticmethod
    def parse_result(capability: str, payload: dict) -> CapabilityResult:
        cls = {
            "get_asset_context": AssetContext,
            "get_telemetry_window": TelemetryWindow,
            "get_maintenance_history": MaintenanceHistory,
            "get_related_incidents": RelatedIncidents,
            "get_operating_context": OperatingContext,
            "get_health_score_window": HealthScoreWindow,
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

    def _reusable(self, evidence: m.Evidence, artifacts: list[m.Artifact], capability: str) -> bool:
        """Exact request, current artifact, intact hash/provenance, dependency manifest still valid."""
        if any(getattr(item, "supersedes_id", None) == evidence.id for item in artifacts):
            return False
        if evidence.content_hash != content_hash(evidence.payload):
            return False
        if evidence.source_capability != capability or evidence.source_system == "legacy.unspecified":
            return False
        manifest = evidence.source_dependencies
        if manifest is None or manifest.basis != "SOURCE_QUERY":
            # Legacy whole-store checkpoints prove nothing about scoped freshness.
            return False
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            return not revalidate(conn, manifest)

    def request_and_collect(self, incident_id: str, *, requested_by: m.Role,
                            equipment_ids: tuple[str, ...], question: str,
                            capability: str, required_for: Literal["diagnosis", "intervention", "outcome"],
                            parameters: dict | None = None,
                            supersedes_evidence_id: str | None = None) -> EvidenceCollection:
        """Request, collect (or reuse) and resolve one bounded read as durable evidence.

        ``supersedes_evidence_id`` (Step 14) lets an application boundary that
        advances a bounded window (a later ``end_at`` of the same observation) declare
        the previous generation superseded, so only the newest window stays current
        while every generation remains immutable history. It is ignored when the
        identical request is reusable and refused when the record is not a current
        same-capability, same-scope evidence of this incident.
        """
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
            if self._reusable(evidence, artifacts, capability):
                return EvidenceCollection(
                    request=request, evidence=evidence,
                    result=self.capabilities.parse_result(capability, evidence.payload), reused=True,
                )
            # A stale or unverifiable cached read cannot satisfy a fresh promotion run.
            # Preserve both old records and append a new request/evidence generation.
            previous_request, previous_evidence = request, evidence
            matching = []
        elif not matching and supersedes_evidence_id is not None:
            previous_request, previous_evidence = self._generation_to_supersede(
                artifacts, supersedes_evidence_id, capability, equipment_ids, required_for)

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
            result, manifest = self.capabilities.collect_with_dependencies(
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
                kind=SOURCE_QUERY_KINDS[capability],
                source_uri=f"operon://evidence/{capability}",
                source_locator=result.provenance.locator,
                source_version="operon-evidence-v1", content_hash=content_hash(payload),
                observed_at=result.provenance.observation_end,
                retrieved_at=result.provenance.collected_at, quality=quality,
                provenance=provenance, source_capability=capability,
                source_system=result.provenance.source_system,
                request_id=request.id, collection_key=request_key,
                summary=self._summary(result), payload=payload,
                source_dependencies=manifest,
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
    def _generation_to_supersede(artifacts, evidence_id, capability, equipment_ids, required_for):
        evidence = next((item for item in artifacts if isinstance(item, m.Evidence) and item.id == evidence_id), None)
        if evidence is None or evidence.source_capability != capability or evidence.equipment_ids != equipment_ids:
            raise InvalidEvidenceRequest("superseded evidence must be a same-capability, same-scope record of this incident")
        if any(getattr(item, "supersedes_id", None) == evidence.id for item in artifacts):
            raise InvalidEvidenceRequest("evidence generation is already superseded")
        superseded = {item.supersedes_id for item in artifacts if isinstance(item, m.EvidenceRequest) and item.supersedes_id}
        resolutions = [item for item in artifacts if isinstance(item, m.EvidenceRequest) and item.id not in superseded
                       and evidence.id in item.resolved_by_evidence_ids and item.required_for == required_for]
        if not resolutions:
            raise InvalidEvidenceRequest("superseded evidence has no current resolved request for this purpose")
        return resolutions[-1], evidence

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
        if isinstance(result, HealthScoreWindow):
            return f"Persisted health-score window: {len(result.scores)} classifier scores (not physical measurements)"
        return f"Persisted asset and sensor context for {result.asset_id}"


# Narrow module-level capabilities for application/tool consumers.
def get_asset_context(asset_id: str, *, path: Path | None = None, as_of: datetime | None = None) -> AssetContext:
    return EvidenceCapabilities(path).get_asset_context(asset_id, as_of=as_of)


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


def get_operating_context(asset_id: str, *, path: Path | None = None,
                          as_of: datetime | None = None) -> OperatingContext:
    return EvidenceCapabilities(path).get_operating_context(asset_id, as_of=as_of)


def get_health_score_window(asset_id: str, *, path: Path | None = None,
                            start_at: datetime | None = None, end_at: datetime | None = None,
                            sample_limit: int = 60) -> HealthScoreWindow:
    return EvidenceCapabilities(path).get_health_score_window(
        asset_id, start_at=start_at, end_at=end_at, sample_limit=sample_limit)
