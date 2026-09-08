"""Short SQLite commits for trusted application callers, never model-facing tools.

State rows are authoritative; events describe commits, not an event-sourced state.
All mutations check revisions inside BEGIN IMMEDIATE. No caller callback or model
invocation runs in a transaction. IDs/commit times are assigned here; externally
constructed artifacts must have trusted identity/provenance before submission.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from core import db
from . import models as m
from .state import TERMINAL_PHASES, validate_transition


class IncidentNotFound(LookupError):
    pass


class StaleRevision(ValueError):
    pass


class InvalidReference(ValueError):
    pass


class DuplicateRecord(ValueError):
    pass


class InactiveIncident(ValueError):
    pass


ARTIFACT_TYPES = {cls.__name__: cls for cls in (
    m.Evidence, m.EvidenceRequest, m.Hypothesis, m.Diagnosis, m.ValidationVerdict,
    m.Intervention, m.AgentAction, m.ApprovalRequirement, m.Outcome, m.LegacyAlert,
)}
REFERENCE_TYPES = {
    "derived_from_ids": m.Evidence, "resolved_by_evidence_ids": m.Evidence,
    "supporting_evidence_ids": m.Evidence, "contradicting_evidence_ids": m.Evidence,
    "evidence_ids": m.Evidence, "verification_evidence_ids": m.Evidence,
    "evidence_request_ids": m.EvidenceRequest, "hypothesis_ids": m.Hypothesis,
    "alternative_hypothesis_ids": m.Hypothesis, "diagnosis_id": m.Diagnosis,
    "intervention_id": m.Intervention, "requirement_id": m.ApprovalRequirement,
    "input_artifact_ids": m.Artifact, "output_artifact_ids": m.Artifact,
    "execution_receipt_ids": m.ExecutionReceipt,
}


def utcnow():
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


def content_hash(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


class IncidentRepository:
    def __init__(self, path: Path | None = None):
        self.path = Path(path if path is not None else db.DB_PATH)

    @contextmanager
    def _write(self):
        with db.get_conn(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except sqlite3.IntegrityError as exc:
                raise DuplicateRecord(str(exc)) from exc

    @staticmethod
    def _fetch(conn, incident_id: str) -> m.Incident:
        row = conn.execute("SELECT state_json FROM incident WHERE incident_id=?", (incident_id,)).fetchone()
        if row is None:
            raise IncidentNotFound(incident_id)
        return m.Incident.model_validate_json(row[0])

    @staticmethod
    def _check(incident: m.Incident, expected_revision: int):
        if incident.revision != expected_revision:
            raise StaleRevision(f"incident {incident.id}: expected {expected_revision}, current {incident.revision}")
        if incident.phase in TERMINAL_PHASES:
            raise InactiveIncident(incident.id)

    @staticmethod
    def _event(conn, incident, event_type, payload):
        # Validate even internal event writes before serializing.
        event = m.IncidentEvent(id=1, incident_id=incident.id, created_at=utcnow(),
                                revision=incident.revision, event_type=event_type, payload=payload)
        cursor = conn.execute("INSERT INTO incident_event "
                              "(incident_id,created_at,revision,event_type,payload_json) VALUES (?,?,?,?,?)",
                              (event.incident_id, event.created_at.isoformat(), event.revision,
                               event.event_type, json.dumps(event.payload, allow_nan=False)))
        return event.model_copy(update={"id": cursor.lastrowid})

    @staticmethod
    def _update(conn, incident, **changes):
        updated = m.Incident.model_validate({**incident.model_dump(), **changes,
                                             "revision": incident.revision + 1, "updated_at": utcnow()})
        cursor = conn.execute("UPDATE incident SET phase=?,revision=?,updated_at=?,state_json=? "
                              "WHERE incident_id=? AND revision=?",
                              (updated.phase.value, updated.revision, updated.updated_at.isoformat(),
                               updated.model_dump_json(), incident.id, incident.revision))
        if cursor.rowcount != 1:
            raise StaleRevision(incident.id)
        return updated

    def _create(self, conn, equipment_ids, admission_key, severity, triage_score):
        for eid in equipment_ids:
            if not conn.execute("SELECT 1 FROM equipment WHERE equipment_id=?", (eid,)).fetchone():
                raise InvalidReference(f"unknown equipment {eid}")
        now = utcnow()
        incident = m.Incident(id=new_id(), created_at=now, updated_at=now,
                              equipment_ids=equipment_ids, admission_key=admission_key,
                              severity=severity, triage_score=triage_score)
        conn.execute("INSERT INTO incident VALUES (?,?,?,?,?,?,?)",
                     (incident.id, incident.admission_key, incident.phase.value, incident.revision,
                      now.isoformat(), now.isoformat(), incident.model_dump_json()))
        self._event(conn, incident, "INCIDENT_OPENED", {"equipment_ids": list(equipment_ids)})
        return incident

    def create_incident(self, equipment_ids: tuple[str, ...], *, admission_key: str,
                        severity: str = "HIGH", triage_score: float = 0) -> m.Incident:
        with self._write() as conn:
            return self._create(conn, equipment_ids, admission_key, severity, triage_score)

    def fetch_incident(self, incident_id: str) -> m.Incident:
        with db.get_conn(self.path) as conn:
            return self._fetch(conn, incident_id)

    def list_active_incidents(self) -> list[m.Incident]:
        with db.get_conn(self.path) as conn:
            return [m.Incident.model_validate_json(row[0]) for row in conn.execute(
                "SELECT state_json FROM incident WHERE phase NOT IN ('CLOSED','CANCELLED') "
                "ORDER BY created_at,incident_id")]

    @staticmethod
    def _artifact(conn, incident_id, artifact_id):
        row = conn.execute("SELECT kind,body_json FROM incident_artifact "
                           "WHERE artifact_id=? AND incident_id=?", (artifact_id, incident_id)).fetchone()
        if row is None:
            raise InvalidReference(f"artifact {artifact_id} not found in incident {incident_id}")
        return ARTIFACT_TYPES[row[0]].model_validate_json(row[1])

    def get_artifact(self, incident_id: str, artifact_id: str) -> m.Artifact:
        with db.get_conn(self.path) as conn:
            return self._artifact(conn, incident_id, artifact_id)

    def list_artifacts(self, incident_id: str) -> list[m.Artifact]:
        with db.get_conn(self.path) as conn:
            self._fetch(conn, incident_id)
            return [ARTIFACT_TYPES[row[0]].model_validate_json(row[1]) for row in conn.execute(
                "SELECT kind,body_json FROM incident_artifact WHERE incident_id=? ORDER BY rowid", (incident_id,))]

    def _validate_references(self, conn, incident, artifact):
        scope = getattr(artifact, "equipment_ids", ())
        if isinstance(artifact, m.LegacyAlert):
            scope = (artifact.equipment_id,)
        if not set(scope) <= set(incident.equipment_ids):
            raise InvalidReference("artifact equipment outside incident scope")
        if isinstance(artifact, m.Intervention):
            for step in artifact.steps:
                if not set(step.equipment_ids) <= set(incident.equipment_ids):
                    raise InvalidReference("step equipment outside incident scope")
        for field, cls in REFERENCE_TYPES.items():
            refs = getattr(artifact, field, ()) or ()
            for ref in (refs,) if isinstance(refs, str) else refs:
                if cls is m.ExecutionReceipt:
                    target = self._receipt(conn, incident.id, ref)
                else:
                    target = self._artifact(conn, incident.id, ref)
                if not isinstance(target, cls):
                    raise InvalidReference(f"{field} requires {cls.__name__}")
        if getattr(artifact, "supersedes_id", None):
            previous = self._artifact(conn, incident.id, artifact.supersedes_id)
            if type(previous) is not type(artifact):
                raise InvalidReference("superseding artifacts must have the same type")
        if isinstance(artifact, m.Evidence):
            if artifact.content_hash != content_hash(artifact.payload):
                raise InvalidReference("evidence content hash does not match payload")
        if isinstance(artifact, (m.ValidationVerdict, m.ApprovalRequirement, m.ApprovalDecision)):
            target_id = artifact.target_id if isinstance(artifact, m.ValidationVerdict) else artifact.intervention_id
            expected_hash = artifact.target_hash if isinstance(artifact, m.ValidationVerdict) else artifact.intervention_hash
            target = self._artifact(conn, incident.id, target_id)
            cls = (m.Diagnosis if artifact.target_kind == "diagnosis" else m.Intervention) if isinstance(artifact, m.ValidationVerdict) else m.Intervention
            if not isinstance(target, cls) or content_hash(target.model_dump(mode="json")) != expected_hash:
                raise InvalidReference("target type or exact artifact hash does not match")
        if isinstance(artifact, m.ApprovalDecision):
            requirement = self._artifact(conn, incident.id, artifact.requirement_id)
            if (requirement.intervention_id, requirement.intervention_hash) != (artifact.intervention_id, artifact.intervention_hash):
                raise InvalidReference("decision does not match approval requirement")
            if artifact.context_revision != incident.revision:
                raise StaleRevision("approval decision context is stale")
        if hasattr(artifact, "input_revision") and artifact.input_revision != incident.revision:
            raise StaleRevision("artifact input revision is stale")

    def _add_artifact(self, conn, incident, artifact):
        cls = ARTIFACT_TYPES.get(type(artifact).__name__)
        if cls is not type(artifact):
            raise ValueError("unsupported artifact type")
        # Revalidate and detach mutable payloads, including model_copy updates.
        artifact = cls.model_validate_json(artifact.model_dump_json())
        if artifact.incident_id != incident.id:
            raise InvalidReference("wrong incident")
        self._validate_references(conn, incident, artifact)
        conn.execute("INSERT INTO incident_artifact VALUES (?,?,?,?,?,?,?)",
                     (artifact.id, incident.id, cls.__name__, artifact.schema_version,
                      artifact.created_at.isoformat(), content_hash(artifact.model_dump(mode="json")),
                      artifact.model_dump_json()))
        changes = {"artifact_ids": (*incident.artifact_ids, artifact.id)}
        if isinstance(artifact, m.Evidence) and artifact.kind == "model_signal":
            changes["signal_evidence_ids"] = (*incident.signal_evidence_ids, artifact.id)
        if isinstance(artifact, m.LegacyAlert):
            changes["legacy_alert_id"] = artifact.id
        incident = self._update(conn, incident, **changes)
        self._event(conn, incident, "ARTIFACT_ADDED", {"artifact_id": artifact.id, "kind": cls.__name__})
        if isinstance(artifact, m.ApprovalRequirement):
            self._event(conn, incident, "APPROVAL_REQUESTED", {
                "requirement_id": artifact.id,
                "intervention_id": artifact.intervention_id,
                "intervention_hash": artifact.intervention_hash,
            })
        if isinstance(artifact, m.Evidence) and artifact.kind == "model_signal":
            self._event(conn, incident, "SIGNAL_RECORDED", {"evidence_id": artifact.id, "signal_id": artifact.payload["id"]})
        return incident

    def add_artifact(self, artifact: m.Artifact, *, expected_revision: int) -> m.Incident:
        with self._write() as conn:
            incident = self._fetch(conn, artifact.incident_id)
            self._check(incident, expected_revision)
            return self._add_artifact(conn, incident, artifact)

    def admit_signal(self, signal: m.ModelSignal, *, severity="HIGH", triage_score=0) -> tuple[m.Incident, bool]:
        from .signals import signal_evidence
        signal = m.ModelSignal.model_validate_json(signal.model_dump_json())
        key = f"model-risk:{signal.equipment_id}"
        with self._write() as conn:
            row = conn.execute("SELECT state_json FROM incident WHERE admission_key=? "
                               "AND phase NOT IN ('CLOSED','CANCELLED')", (key,)).fetchone()
            if row:
                return m.Incident.model_validate_json(row[0]), False
            incident = self._create(conn, (signal.equipment_id,), key, severity, triage_score)
            return self._add_artifact(conn, incident, signal_evidence(signal, incident.id)), True

    def transition(self, incident_id: str, target: m.IncidentPhase, *, expected_revision: int,
                   reason: str) -> m.Incident:
        with self._write() as conn:
            incident = self._fetch(conn, incident_id)
            self._check(incident, expected_revision)
            validate_transition(incident.phase, target)
            updated = self._update(conn, incident, phase=target)
            payload = {"from": incident.phase.value, "to": updated.phase.value, "reason": reason}
            self._event(conn, updated, "PHASE_CHANGED", payload)
            if updated.phase == m.IncidentPhase.ESCALATED:
                self._event(conn, updated, "INCIDENT_ESCALATED", payload)
            elif updated.phase == m.IncidentPhase.CLOSED:
                self._event(conn, updated, "INCIDENT_CLOSED", payload)
            return updated

    def append_event(self, incident_id: str, event_type: str, payload: dict, *, expected_revision: int) -> m.IncidentEvent:
        """Append application activity; lifecycle events are emitted by their commits."""
        if event_type != "INCIDENT_UPDATED":
            raise ValueError("lifecycle/artifact events must accompany the corresponding repository mutation")
        with self._write() as conn:
            incident = self._fetch(conn, incident_id)
            self._check(incident, expected_revision)
            updated = self._update(conn, incident)
            return self._event(conn, updated, event_type, payload)

    def list_events(self, incident_id: str, *, after_id: int = 0) -> list[m.IncidentEvent]:
        with db.get_conn(self.path) as conn:
            self._fetch(conn, incident_id)
            return [m.IncidentEvent(id=r["event_id"], incident_id=incident_id, created_at=r["created_at"],
                                    revision=r["revision"], event_type=r["event_type"],
                                    payload=json.loads(r["payload_json"])) for r in conn.execute(
                "SELECT * FROM incident_event WHERE incident_id=? AND event_id>? ORDER BY event_id",
                (incident_id, after_id))]

    def add_approval_decision(self, decision: m.ApprovalDecision, *, expected_revision: int) -> m.Incident:
        """Append a trusted decision; policy determines whether it is applicable."""
        decision = m.ApprovalDecision.model_validate_json(decision.model_dump_json())
        with self._write() as conn:
            incident = self._fetch(conn, decision.incident_id)
            self._check(incident, expected_revision)
            self._validate_references(conn, incident, decision)
            conn.execute("INSERT INTO approval_decision VALUES (?,?,?,?,?,?,?)",
                         (decision.id, incident.id, decision.intervention_id, decision.intervention_hash,
                          decision.actor_id, decision.created_at.isoformat(), decision.model_dump_json()))
            updated = self._update(conn, incident)
            self._event(conn, updated, "APPROVAL_RECORDED", {
                "decision_id": decision.id, "decision": decision.decision,
                "intervention_id": decision.intervention_id,
            })
            return updated

    def get_approval_decision(self, incident_id: str, decision_id: str) -> m.ApprovalDecision:
        with db.get_conn(self.path) as conn:
            row = conn.execute("SELECT body_json FROM approval_decision WHERE incident_id=? AND decision_id=?",
                               (incident_id, decision_id)).fetchone()
            if row is None:
                raise InvalidReference(decision_id)
            return m.ApprovalDecision.model_validate_json(row[0])

    def list_approval_decisions(self, incident_id: str, *, intervention_id: str | None = None) -> list[m.ApprovalDecision]:
        with db.get_conn(self.path) as conn:
            self._fetch(conn, incident_id)
            sql = "SELECT body_json FROM approval_decision WHERE incident_id=?"
            params: tuple[str, ...] = (incident_id,)
            if intervention_id is not None:
                sql += " AND intervention_id=?"
                params += (intervention_id,)
            sql += " ORDER BY created_at, decision_id"
            return [m.ApprovalDecision.model_validate_json(row[0])
                    for row in conn.execute(sql, params)]

    def add_execution_receipt(self, receipt: m.ExecutionReceipt, *, expected_revision: int) -> m.Incident:
        """Insert-only foundation. Claim/reconcile/execute behavior is a later stage."""
        receipt = m.ExecutionReceipt.model_validate_json(receipt.model_dump_json())
        with self._write() as conn:
            incident = self._fetch(conn, receipt.incident_id)
            self._check(incident, expected_revision)
            self._validate_references(conn, incident, receipt)
            conn.execute("INSERT INTO execution_receipt VALUES (?,?,?,?,?,?,?)",
                         (receipt.id, incident.id, receipt.intervention_id, receipt.operation_key,
                          receipt.status, receipt.created_at.isoformat(), receipt.model_dump_json()))
            updated = self._update(conn, incident)
            self._event(conn, updated, "EXECUTION_RECORDED", {"receipt_id": receipt.id})
            return updated

    @staticmethod
    def _receipt(conn, incident_id, receipt_id):
        row = conn.execute("SELECT body_json FROM execution_receipt WHERE incident_id=? AND receipt_id=?",
                           (incident_id, receipt_id)).fetchone()
        if row is None:
            raise InvalidReference(receipt_id)
        return m.ExecutionReceipt.model_validate_json(row[0])

    def get_execution_receipt(self, incident_id: str, receipt_id: str) -> m.ExecutionReceipt:
        with db.get_conn(self.path) as conn:
            return self._receipt(conn, incident_id, receipt_id)

    def list_execution_receipts(self, incident_id: str, *, intervention_id: str | None = None) -> list[m.ExecutionReceipt]:
        with db.get_conn(self.path) as conn:
            self._fetch(conn, incident_id)
            sql = "SELECT body_json FROM execution_receipt WHERE incident_id=?"
            params: tuple[str, ...] = (incident_id,)
            if intervention_id is not None:
                sql += " AND intervention_id=?"
                params += (intervention_id,)
            sql += " ORDER BY created_at, receipt_id"
            return [m.ExecutionReceipt.model_validate_json(row[0])
                    for row in conn.execute(sql, params)]

    @staticmethod
    def _claim_from_row(row) -> m.ExecutionClaim:
        return m.ExecutionClaim(
            idempotency_key=row["idempotency_key"], incident_id=row["incident_id"],
            intervention_id=row["intervention_id"], intervention_hash=row["intervention_hash"],
            step_id=row["step_id"], capability=row["capability"], request_hash=row["request_hash"],
            adapter=row["adapter"], executor=row["executor"], state=row["state"], attempt=row["attempt"],
            started_at=row["started_at"], updated_at=row["updated_at"],
            error_message=row["error_message"],
        )

    def get_execution_claim(self, idempotency_key: str) -> m.ExecutionClaim | None:
        with db.get_conn(self.path) as conn:
            row = conn.execute("SELECT * FROM execution_claim WHERE idempotency_key=?",
                               (idempotency_key,)).fetchone()
            return self._claim_from_row(row) if row else None

    def begin_execution_claim(self, claim: m.ExecutionClaim, *, expected_revision: int) -> tuple[m.Incident, m.ExecutionClaim, bool]:
        """Claim a step in a short transaction.

        FAILED claims may be retried. IN_FLIGHT/UNKNOWN claims are returned without
        mutation so the executor can fail safe; CONFIRMED claims are idempotent hits.
        """
        claim = m.ExecutionClaim.model_validate_json(claim.model_dump_json())
        with self._write() as conn:
            incident = self._fetch(conn, claim.incident_id)
            self._check(incident, expected_revision)
            target = self._artifact(conn, incident.id, claim.intervention_id)
            if (not isinstance(target, m.Intervention) or
                    content_hash(target.model_dump(mode="json")) != claim.intervention_hash):
                raise InvalidReference("execution claim is not bound to the exact intervention")
            row = conn.execute("SELECT * FROM execution_claim WHERE idempotency_key=?",
                               (claim.idempotency_key,)).fetchone()
            if row:
                existing = self._claim_from_row(row)
                expected = (claim.incident_id, claim.intervention_id, claim.intervention_hash,
                            claim.step_id, claim.capability, claim.request_hash)
                actual = (existing.incident_id, existing.intervention_id, existing.intervention_hash,
                          existing.step_id, existing.capability, existing.request_hash)
                if actual != expected:
                    raise InvalidReference("idempotency key is bound to a different action")
                if existing.state != "FAILED":
                    return incident, existing, False
                now = utcnow()
                attempt = existing.attempt + 1
                conn.execute("UPDATE execution_claim SET state='IN_FLIGHT',attempt=?,started_at=?,updated_at=?,"
                             "adapter=?,executor=?,error_message=NULL WHERE idempotency_key=? AND state='FAILED'",
                             (attempt, now.isoformat(), now.isoformat(), claim.adapter, claim.executor,
                              claim.idempotency_key))
                claimed = claim.model_copy(update={"state": "IN_FLIGHT", "attempt": attempt,
                                                   "started_at": now, "updated_at": now,
                                                   "error_message": None})
            else:
                conn.execute(
                    "INSERT INTO execution_claim "
                    "(idempotency_key,incident_id,intervention_id,intervention_hash,step_id,"
                    "capability,request_hash,executor,state,attempt,started_at,updated_at,error_message,adapter) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    claim.idempotency_key, claim.incident_id, claim.intervention_id,
                    claim.intervention_hash, claim.step_id, claim.capability, claim.request_hash,
                    claim.executor, "IN_FLIGHT", claim.attempt, claim.started_at.isoformat(),
                    claim.updated_at.isoformat(), None, claim.adapter))
                claimed = claim.model_copy(update={"state": "IN_FLIGHT"})
            updated = self._update(conn, incident)
            self._event(conn, updated, "EXECUTION_CLAIMED", {
                "idempotency_key": claimed.idempotency_key, "step_id": claimed.step_id,
                "attempt": claimed.attempt,
            })
            return updated, claimed, True

    def finish_execution_claim(self, receipt: m.ExecutionReceipt, *, expected_revision: int) -> m.Incident:
        """Append a terminal receipt and checkpoint the corresponding claim."""
        receipt = m.ExecutionReceipt.model_validate_json(receipt.model_dump_json())
        if receipt.status not in ("CONFIRMED", "FAILED", "UNKNOWN"):
            raise ValueError("execution completion requires a terminal receipt")
        with self._write() as conn:
            incident = self._fetch(conn, receipt.incident_id)
            self._check(incident, expected_revision)
            row = conn.execute("SELECT * FROM execution_claim WHERE idempotency_key=?",
                               (receipt.idempotency_key,)).fetchone()
            if row is None:
                raise InvalidReference("execution claim does not exist")
            claim = self._claim_from_row(row)
            expected = (receipt.incident_id, receipt.intervention_id, receipt.intervention_hash,
                        receipt.step_id, receipt.capability, receipt.request_hash, receipt.attempt)
            actual = (claim.incident_id, claim.intervention_id, claim.intervention_hash,
                      claim.step_id, claim.capability, claim.request_hash, claim.attempt)
            if actual != expected or claim.state != "IN_FLIGHT":
                raise InvalidReference("receipt does not match the active execution claim")
            conn.execute("INSERT INTO execution_receipt VALUES (?,?,?,?,?,?,?)",
                         (receipt.id, incident.id, receipt.intervention_id, receipt.operation_key,
                          receipt.status, receipt.created_at.isoformat(), receipt.model_dump_json()))
            conn.execute("UPDATE execution_claim SET state=?,updated_at=?,error_message=? "
                         "WHERE idempotency_key=? AND state='IN_FLIGHT'",
                         (receipt.status, receipt.created_at.isoformat(), receipt.error_message,
                          receipt.idempotency_key))
            updated = self._update(conn, incident)
            self._event(conn, updated, "EXECUTION_RECORDED", {
                "receipt_id": receipt.id, "step_id": receipt.step_id,
                "status": receipt.status, "attempt": receipt.attempt,
            })
            return updated
