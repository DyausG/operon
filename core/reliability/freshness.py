"""Dependency-scoped source freshness (Step 13C).

An evidence artifact is stale only when a mutable local source that could change
the result of the exact query it represents has changed. Every evidence capability
performs its reads through ``SourceReads``; each read records the ``SourceDependency``
(domain, scope, bound query parameters, result fingerprint) that reproduces it.
Revalidation re-runs the identical read through the same class, so the dependency a
manifest declares and the query it is checked against cannot drift apart.

Fingerprints hash the rows a read returns, in the order the capability consumes
them. A transient change that is fully reverted therefore leaves the dependency
valid: the artifact still reproduces from current sources. Nothing here performs
network or adapter calls; every read is local SQLite and safe under a write lock.

The whole-store ``source_state_hash`` of Step 13A is not consulted anywhere. Legacy
records that carry only that hash cannot prove scoped freshness and are treated as
such by the callers in ``evidence``, ``promotion`` and ``lifecycle``.
"""
from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from . import models as m
from .repository import ARTIFACT_TYPES, content_hash


class InconsistentSourceRead(ValueError):
    """The same read produced different rows inside one collection."""


class SourceDependencyChange(BaseModel):
    """One frozen dependency whose recomputed fingerprint differs from the frozen one."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    dependency: m.SourceDependency
    actual_fingerprint: str

    @property
    def reason(self) -> str:
        return f"SOURCE_DEPENDENCY_CHANGED:{self.dependency.describe()}"


def _fingerprint(rows: Iterable) -> str:
    return content_hash({"rows": [dict(row) if not isinstance(row, dict) else row for row in rows]})


class SourceReads:
    """Exact local reads used by the evidence capabilities, each recorded as a dependency.

    Method names are the ``SourceDomain`` values and their keyword arguments are
    exactly the dependency ``scope`` plus ``parameters`` keys, so ``recompute`` can
    replay any dependency by name without a second query catalogue.
    """

    def __init__(self, conn):
        self.conn = conn
        self._dependencies: dict[str, m.SourceDependency] = {}

    def _record(self, domain: str, scope: dict, parameters: dict, rows) -> m.SourceDependency:
        dependency = m.SourceDependency(domain=domain, scope=scope, parameters=parameters, fingerprint=_fingerprint(rows))
        existing = self._dependencies.get(dependency.identity)
        if existing is not None and existing.fingerprint != dependency.fingerprint:
            raise InconsistentSourceRead(dependency.describe())
        self._dependencies[dependency.identity] = dependency
        return dependency

    @property
    def dependencies(self) -> tuple[m.SourceDependency, ...]:
        return tuple(self._dependencies.values())

    def manifest(self) -> m.SourceDependencyManifest:
        return m.SourceDependencyManifest(basis="SOURCE_QUERY", dependencies=self.dependencies)

    # ------------------------------------------------------------ registry
    def asset_registry(self, *, asset_id: str):
        """Equipment row joined to its line and plant, as read by get_asset_context."""
        row = self.conn.execute(
            "SELECT e.*,l.line_name,l.line_type,p.plant_id,p.plant_name,p.timezone "
            "FROM equipment e JOIN assembly_line l ON l.line_id=e.line_id "
            "JOIN plant p ON p.plant_id=l.plant_id WHERE e.equipment_id=?", (asset_id,),
        ).fetchone()
        self._record("asset_registry", {"asset_id": asset_id}, {}, [row] if row is not None else [])
        return row

    def health_score_latest(self, *, asset_id: str, as_of: str | None = None):
        """Newest health score, optionally bounded to scores at or before ``as_of``."""
        sql, args = "SELECT * FROM health_score WHERE equipment_id=?", [asset_id]
        if as_of is not None:
            sql += " AND scored_at<=?"
            args.append(as_of)
        row = self.conn.execute(sql + " ORDER BY scored_at DESC,score_id DESC LIMIT 1", tuple(args)).fetchone()
        self._record("health_score_latest", {"asset_id": asset_id}, {"as_of": as_of}, [row] if row is not None else [])
        return row

    def sensor_inventory(self, *, asset_id: str, sensor_type: str | None = None):
        """Registered sensors of an asset (optionally one upper-cased type), ordered."""
        sql, args = "SELECT * FROM sensor WHERE equipment_id=?", [asset_id]
        if sensor_type is not None:
            sql += " AND upper(sensor_type)=?"
            args.append(sensor_type)
        rows = self.conn.execute(sql + " ORDER BY sensor_type,sensor_id", tuple(args)).fetchall()
        self._record("sensor_inventory", {"asset_id": asset_id}, {"sensor_type": sensor_type}, rows)
        return rows

    # ------------------------------------------------------------ telemetry
    def telemetry_latest(self, *, sensor_id: str, as_of: str | None = None):
        """Newest reading of one sensor, optionally bounded to ``ts <= as_of``."""
        sql, args = "SELECT ts,value_eu,quality_flag FROM sensor_reading WHERE sensor_id=?", [sensor_id]
        if as_of is not None:
            sql += " AND ts<=?"
            args.append(as_of)
        row = self.conn.execute(sql + " ORDER BY ts DESC,rowid DESC LIMIT 1", tuple(args)).fetchone()
        self._record("telemetry_latest", {"sensor_id": sensor_id}, {"as_of": as_of}, [row] if row is not None else [])
        return row

    def telemetry_window(self, *, sensor_id: str, start_at: str | None = None, end_at: str | None = None,
                         sample_limit: int = 60):
        """The exact bounded (or open-ended) window get_telemetry_window returns, ascending.

        ``start_at``/``end_at`` are the ISO strings bound in SQL. With ``end_at`` set,
        samples strictly after it never enter the result and never stale it; a row
        inserted, deleted or modified inside the returned window does.
        """
        sql, args = "SELECT ts,value_eu,quality_flag FROM sensor_reading WHERE sensor_id=?", [sensor_id]
        if start_at is not None:
            sql += " AND ts>=?"
            args.append(start_at)
        if end_at is not None:
            sql += " AND ts<=?"
            args.append(end_at)
        sql += " ORDER BY ts DESC,rowid DESC LIMIT ?"
        args.append(sample_limit)
        rows = list(reversed(self.conn.execute(sql, tuple(args)).fetchall()))
        self._record("telemetry_window", {"sensor_id": sensor_id},
                     {"start_at": start_at, "end_at": end_at, "sample_limit": sample_limit}, rows)
        return rows

    def health_score_window(self, *, asset_id: str, start_at: str | None = None, end_at: str | None = None,
                            sample_limit: int = 60):
        """Bounded (or open-ended) persisted health-score window of one asset, ascending.

        Same semantics as ``telemetry_window``: with ``end_at`` set, scores stamped
        strictly after it never enter the result and never stale it; a row inserted,
        deleted or modified inside the returned window does. Step 14 outcome
        verification reads only bounded windows through this method.
        """
        sql = "SELECT score_id,scored_at,health_score,failure_prob,predicted_mode FROM health_score WHERE equipment_id=?"
        args: list[object] = [asset_id]
        if start_at is not None:
            sql += " AND scored_at>=?"
            args.append(start_at)
        if end_at is not None:
            sql += " AND scored_at<=?"
            args.append(end_at)
        sql += " ORDER BY scored_at DESC,score_id DESC LIMIT ?"
        args.append(sample_limit)
        rows = list(reversed(self.conn.execute(sql, tuple(args)).fetchall()))
        self._record("health_score_window", {"asset_id": asset_id},
                     {"start_at": start_at, "end_at": end_at, "sample_limit": sample_limit}, rows)
        return rows

    # ---------------------------------------------------------- maintenance
    def maintenance_history(self, *, asset_id: str, before: str | None = None, limit: int = 20):
        """Work orders with joined failure-mode/technician columns plus their events and parts.

        One dependency covers the three reads because the events and parts are
        selected per returned work order; the fingerprint changes when any of them do.
        """
        sql = ("SELECT wo.*,fm.mode_code,fm.failure_mode_name,t.full_name technician_name "
               "FROM work_order wo LEFT JOIN failure_mode fm ON fm.failure_mode_id=wo.failure_mode_id "
               "LEFT JOIN technician t ON t.technician_id=wo.technician_id WHERE wo.equipment_id=?")
        args: list[object] = [asset_id]
        if before is not None:
            sql += " AND wo.created_at<=?"
            args.append(before)
        sql += " ORDER BY wo.created_at DESC,wo.wo_id DESC LIMIT ?"
        args.append(limit)
        orders = self.conn.execute(sql, tuple(args)).fetchall()
        events, parts, fingerprinted = {}, {}, []
        for order in orders:
            events[order["wo_id"]] = self.conn.execute(
                "SELECT event_type,note FROM maintenance_event WHERE wo_id=? ORDER BY created_at,event_id",
                (order["wo_id"],)).fetchall()
            parts[order["wo_id"]] = self.conn.execute(
                "SELECT p.part_number FROM part_reservation pr JOIN part p ON p.part_id=pr.part_id "
                "WHERE pr.wo_id=? AND pr.status IN ('ISSUED','RESERVED') ORDER BY p.part_number",
                (order["wo_id"],)).fetchall()
            fingerprinted.append({"order": dict(order), "events": [dict(row) for row in events[order["wo_id"]]],
                                  "parts": [dict(row) for row in parts[order["wo_id"]]]})
        self._record("maintenance_history", {"asset_id": asset_id}, {"before": before, "limit": limit}, fingerprinted)
        return orders, events, parts

    # ------------------------------------------------------------ incidents
    def related_incidents(self, *, asset_id: str, exclude_incident_id: str | None = None, limit: int = 20):
        """Other incidents of the same asset with their artifacts.

        Every state or artifact change of an incident advances its revision, so the
        ordered (incident_id, revision) list is the exact fingerprint of this read.
        """
        sql = ("SELECT state_json,revision FROM incident i "
               "WHERE EXISTS (SELECT 1 FROM json_each(i.state_json, '$.equipment_ids') WHERE value=?)")
        args: list[object] = [asset_id]
        if exclude_incident_id is not None:
            sql += " AND incident_id<>?"
            args.append(exclude_incident_id)
        sql += " ORDER BY updated_at DESC, incident_id DESC LIMIT ?"
        args.append(limit)
        incidents, fingerprinted = [], []
        for row in self.conn.execute(sql, tuple(args)).fetchall():
            incident = m.Incident.model_validate_json(row["state_json"])
            artifacts = [ARTIFACT_TYPES[kind].model_validate_json(body) for kind, body in self.conn.execute(
                "SELECT kind,body_json FROM incident_artifact WHERE incident_id=? ORDER BY rowid", (incident.id,))]
            incidents.append((incident, artifacts))
            fingerprinted.append({"incident_id": incident.id, "revision": row["revision"]})
        self._record("related_incidents", {"asset_id": asset_id, "exclude_incident_id": exclude_incident_id},
                     {"limit": limit}, fingerprinted)
        return incidents


def recompute(conn, dependency: m.SourceDependency) -> str:
    """Replay one dependency's exact read against current local data; return its fingerprint."""
    reads = SourceReads(conn)
    getattr(reads, dependency.domain)(**dependency.scope, **dependency.parameters)
    return reads._dependencies[dependency.identity].fingerprint


def revalidate(conn, manifest: m.SourceDependencyManifest | None, *,
               cache: dict[str, str] | None = None) -> tuple[SourceDependencyChange, ...]:
    """Recompute every dependency of a manifest; return those whose result changed.

    ``cache`` maps dependency identity to a fingerprint recomputed earlier in the same
    transaction, so a closure shared by many artifacts is checked once.
    """
    if manifest is None:
        return ()
    changes = []
    for dependency in manifest.dependencies:
        if cache is not None and dependency.identity in cache:
            actual = cache[dependency.identity]
        else:
            actual = recompute(conn, dependency)
            if cache is not None:
                cache[dependency.identity] = actual
        if actual != dependency.fingerprint:
            changes.append(SourceDependencyChange(dependency=dependency, actual_fingerprint=actual))
    return tuple(changes)


def closure(manifests: Iterable[m.SourceDependencyManifest | None]) -> m.SourceDependencyManifest:
    """Union of the dependencies of several artifacts, as frozen by a run snapshot.

    Two artifacts that froze the same read with different fingerprints cannot both
    be current; that is refused rather than silently keeping one of them.
    """
    merged: dict[str, m.SourceDependency] = {}
    for manifest in manifests:
        for dependency in (manifest.dependencies if manifest is not None else ()):
            existing = merged.get(dependency.identity)
            if existing is not None and existing.fingerprint != dependency.fingerprint:
                raise InconsistentSourceRead(f"conflicting frozen fingerprints for {dependency.describe()}")
            merged[dependency.identity] = dependency
    # Canonical order: the closure is compared for equality across visits.
    return m.SourceDependencyManifest(basis="CLOSURE", dependencies=tuple(merged[key] for key in sorted(merged)))


def observation_manifest() -> m.SourceDependencyManifest:
    return m.SourceDependencyManifest(basis="IMMUTABLE_OBSERVATION")


def derived_manifest() -> m.SourceDependencyManifest:
    return m.SourceDependencyManifest(basis="DERIVED")
