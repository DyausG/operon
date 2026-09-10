"""Governed, idempotent execution of persisted Intervention artifacts.

Since Step 13B this executor serves only non-promoted (legacy/compatibility)
interventions. Anything with PromotionService lineage is delegated to
core.reliability.lifecycle.LifecycleService, which owns the atomic READY ->
EXECUTING claim, exact approval checks and claim-identity receipts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from hashlib import sha256
import json

from pydantic import BaseModel, ConfigDict, Field

from . import models as m
from .governance import (CAPABILITY_POLICY, ExecutionPolicy, NotificationParameters, PolicyDisposition,
                         WorkPackageParameters, artifact_hash, validate_step_parameters)
from .repository import IncidentRepository, InvalidReference, content_hash, new_id, utcnow


TRUSTED_EXECUTOR = "operon.application.executor"
AMBIGUOUS_CLAIM_AFTER = timedelta(seconds=30)
_AUTHORITY_SEAL = object()


@dataclass(frozen=True)
class ExecutionAuthorization:
    """Opaque capability passed only from this executor to mutation adapters."""
    incident_id: str
    intervention_id: str
    intervention_hash: str
    step_id: str
    idempotency_key: str
    executor: str
    _seal: object = field(repr=False)


def failure_status(adapter, exc: BaseException) -> str:
    """Terminal receipt status for an adapter exception: FAILED only when definitive.

    An exception that declares ``failure_is_definitive`` (raised by the adapter
    inside its own write transaction before any consequential commit, e.g. a
    dispatch-time resource rejection) is definitive regardless of the adapter's
    blanket flag. Otherwise the adapter's flag decides, defaulting to UNKNOWN.
    """
    if getattr(exc, "failure_is_definitive", False) is True:
        return "FAILED"
    return "FAILED" if getattr(adapter, "failure_is_definitive", False) else "UNKNOWN"


def require_execution_authorization(value: object, *, capability: str) -> ExecutionAuthorization:
    if (not isinstance(value, ExecutionAuthorization) or value._seal is not _AUTHORITY_SEAL
            or value.executor != TRUSTED_EXECUTOR):
        raise PermissionError(f"{capability} requires governed execution authorization")
    return value


class ExecutionDenied(PermissionError):
    pass


class ExecutionBusy(RuntimeError):
    pass


class ExecutionFailed(RuntimeError):
    def __init__(self, message: str, report: "ExecutionReport"):
        super().__init__(message)
        self.report = report


class ExecutionAmbiguous(ExecutionFailed):
    pass


class ExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    incident_id: str
    intervention_id: str
    phase: m.IncidentPhase
    receipt_ids: tuple[str, ...] = ()
    skipped_step_ids: tuple[str, ...] = ()
    deferred_step_ids: tuple[str, ...] = ()
    external_objects: dict[str, str] = Field(default_factory=dict)


class GovernedExecutor:
    def __init__(self, repository: IncidentRepository, policy: ExecutionPolicy | None = None,
                 *, executor_id: str = TRUSTED_EXECUTOR):
        self.repository = repository
        self.policy = policy or ExecutionPolicy()
        self.executor_id = executor_id

    def _load(self, incident_id: str, intervention_id: str):
        incident = self.repository.fetch_incident(incident_id)
        intervention = self.repository.get_artifact(incident_id, intervention_id)
        if not isinstance(intervention, m.Intervention):
            raise InvalidReference("execution target is not an Intervention")
        artifacts = self.repository.list_artifacts(incident_id)
        decisions = self.repository.list_approval_decisions(incident_id,
                                                            intervention_id=intervention_id)
        return incident, intervention, artifacts, decisions

    @staticmethod
    def _idempotency_key(incident: m.Incident, intervention: m.Intervention,
                         step: m.InterventionStep, request_hash: str) -> str:
        raw = ":".join((incident.id, intervention.id, artifact_hash(intervention),
                        step.id, step.capability, request_hash))
        return "operon-step:" + sha256(raw.encode()).hexdigest()

    def _receipt(self, incident: m.Incident, intervention: m.Intervention,
                 step: m.InterventionStep, claim: m.ExecutionClaim, *, status: str,
                 adapter: str | None = None, external_ids: dict[str, str] | None = None,
                 error_code: str | None = None, error_message: str | None = None) -> m.ExecutionReceipt:
        now = utcnow()
        return m.ExecutionReceipt(
            id=new_id(), incident_id=incident.id, created_at=now,
            intervention_id=intervention.id, intervention_hash=artifact_hash(intervention),
            step_id=step.id, capability=step.capability,
            idempotency_key=claim.idempotency_key,
            operation_key=f"{claim.idempotency_key}:attempt:{claim.attempt}:{status.lower()}",
            adapter=adapter or claim.adapter, executor=self.executor_id, request_hash=claim.request_hash,
            status=status, external_ids=external_ids or {}, attempted_at=claim.started_at,
            completed_at=now, attempt=claim.attempt, error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _legacy_work_package(parameters: WorkPackageParameters) -> dict:
        return {
            "equipment_id": parameters.equipment_id,
            "failure_mode": {"failure_mode_id": parameters.failure_mode_id},
            "prediction": {"failure_prob": parameters.prediction_failure_prob},
            "actions": {
                "work_order": {"priority": parameters.priority, "detail": parameters.detail},
                "technician": {"technician_id": parameters.technician_id},
                "parts": {"parts": [
                    {"part_id": part.part_id, "part_number": part.part_number,
                     "qty_per_service": part.qty, "is_critical_spare": part.is_critical_spare}
                    for part in parameters.parts
                ]},
                "schedule": {"window": parameters.window, "window_min": parameters.window_min},
            },
        }

    @staticmethod
    def _adapter_for(step: m.InterventionStep):
        from core import services

        if step.capability == "create_work_package":
            return services.cmms()
        if step.capability == "notify":
            return services.notifications()
        raise RuntimeError(f"no trusted executor for {step.capability}")

    def _execute_step(self, adapter, incident: m.Incident, intervention: m.Intervention,
                      step: m.InterventionStep, claim: m.ExecutionClaim) -> dict:

        authorization = ExecutionAuthorization(
            incident_id=incident.id, intervention_id=intervention.id,
            intervention_hash=artifact_hash(intervention), step_id=step.id,
            idempotency_key=claim.idempotency_key, executor=self.executor_id,
            _seal=_AUTHORITY_SEAL,
        )
        parameters = validate_step_parameters(step)
        if step.capability == "create_work_package":
            assert isinstance(parameters, WorkPackageParameters)
            result = adapter.create_work_package(self._legacy_work_package(parameters),
                                                 authorization=authorization)
        elif step.capability == "notify":
            assert isinstance(parameters, NotificationParameters)
            result = adapter.notify(recipient_id=parameters.recipient_id,
                                    subject=parameters.subject, body=parameters.body,
                                    channel=parameters.channel, send=True,
                                    authorization=authorization)
        else:
            raise RuntimeError(f"no trusted executor for {step.capability}")
        return result

    @staticmethod
    def _external_ids(result: dict) -> dict[str, str]:
        return {str(key): str(value) for key, value in result.items()
                if value is not None and (key.endswith("_id") or key.endswith("_number"))}

    def _fail_phase(self, incident_id: str, reason: str) -> m.Incident:
        current = self.repository.fetch_incident(incident_id)
        if current.phase == m.IncidentPhase.EXECUTING:
            return self.repository.transition(current.id, m.IncidentPhase.EXECUTION_FAILED,
                                              expected_revision=current.revision, reason=reason)
        return current

    def _report(self, incident_id: str, intervention_id: str, receipt_ids, skipped,
                deferred, external) -> ExecutionReport:
        return ExecutionReport(
            incident_id=incident_id, intervention_id=intervention_id,
            phase=self.repository.fetch_incident(incident_id).phase,
            receipt_ids=tuple(receipt_ids), skipped_step_ids=tuple(skipped),
            deferred_step_ids=tuple(deferred), external_objects=external,
        )

    def _promoted(self, incident_id: str, intervention_id: str) -> bool:
        return any(isinstance(item, m.PromotionRecord) and item.target_id == intervention_id
                   for item in self.repository.list_artifacts(incident_id))

    def execute(self, incident_id: str, intervention_id: str) -> ExecutionReport:
        if self._promoted(incident_id, intervention_id):
            # Application-promoted interventions execute only through the Step 13B
            # lifecycle boundary: atomic eligibility/claim, exact human approval, and
            # claim-identity receipts. This legacy executor never evaluates them.
            from .lifecycle import LifecycleService
            return LifecycleService(self.repository).execute(incident_id, intervention_id)
        incident, intervention, artifacts, decisions = self._load(incident_id, intervention_id)
        executable_steps = [step for step in intervention.steps
                            if CAPABILITY_POLICY[step.capability].executable_now]
        if incident.phase == m.IncidentPhase.OBSERVING:
            receipts = self.repository.list_execution_receipts(
                incident.id, intervention_id=intervention.id)
            confirmed = {receipt.step_id: receipt for receipt in receipts
                         if receipt.status == "CONFIRMED"}
            if all(step.id in confirmed for step in executable_steps):
                external: dict[str, str] = {}
                for receipt in confirmed.values():
                    external.update(receipt.external_ids)
                deferred = [step.id for step in intervention.steps if step not in executable_steps]
                return self._report(incident.id, intervention.id,
                                    [confirmed[step.id].id for step in executable_steps],
                                    [step.id for step in executable_steps], deferred, external)
        evaluation = self.policy.evaluate(incident, intervention, artifacts, decisions)
        if evaluation.disposition != PolicyDisposition.READY:
            detail = evaluation.blockers or evaluation.reasons
            raise ExecutionDenied(f"{evaluation.disposition.value}: {'; '.join(detail)}")

        if incident.phase in (m.IncidentPhase.INTERVENTION_VALIDATED,
                              m.IncidentPhase.AWAITING_APPROVAL,
                              m.IncidentPhase.EXECUTION_FAILED):
            incident = self.repository.transition(incident.id, m.IncidentPhase.READY,
                                                  expected_revision=incident.revision,
                                                  reason="execution policy satisfied")
        if incident.phase == m.IncidentPhase.READY:
            incident = self.repository.transition(incident.id, m.IncidentPhase.EXECUTING,
                                                  expected_revision=incident.revision,
                                                  reason="governed execution started")
        elif incident.phase != m.IncidentPhase.EXECUTING:
            raise ExecutionDenied(f"incident phase {incident.phase.value} cannot execute")

        receipt_ids: list[str] = []
        skipped: list[str] = []
        deferred: list[str] = []
        external: dict[str, str] = {}

        for step in intervention.steps:
            if not CAPABILITY_POLICY[step.capability].executable_now:
                deferred.append(step.id)
                continue
            request_hash = content_hash({"capability": step.capability,
                                         "parameters": step.parameters})
            key = self._idempotency_key(incident, intervention, step, request_hash)
            existing = self.repository.get_execution_claim(key)
            if existing and existing.state == "CONFIRMED":
                skipped.append(step.id)
                for receipt in self.repository.list_execution_receipts(
                        incident.id, intervention_id=intervention.id):
                    if receipt.idempotency_key == key and receipt.status == "CONFIRMED":
                        receipt_ids.append(receipt.id)
                        external.update(receipt.external_ids)
                continue
            if existing and existing.state == "UNKNOWN":
                self._fail_phase(incident.id, "prior execution outcome remains ambiguous")
                report = self._report(incident.id, intervention.id, receipt_ids, skipped,
                                      deferred, external)
                raise ExecutionAmbiguous("prior action outcome is unknown; manual reconciliation required", report)
            if existing and existing.state == "IN_FLIGHT":
                if utcnow() - existing.started_at < AMBIGUOUS_CLAIM_AFTER:
                    raise ExecutionBusy("execution step already in progress")
                unknown = self._receipt(incident, intervention, step, existing, status="UNKNOWN",
                                        error_code="AMBIGUOUS_COMMIT",
                                        error_message="in-flight claim outlived reconciliation window")
                incident = self.repository.finish_execution_claim(unknown,
                                                                  expected_revision=incident.revision)
                receipt_ids.append(unknown.id)
                self._fail_phase(incident.id, "execution outcome is ambiguous")
                report = self._report(incident.id, intervention.id, receipt_ids, skipped,
                                      deferred, external)
                raise ExecutionAmbiguous("action may have committed; refusing blind retry", report)

            now = utcnow()
            adapter = self._adapter_for(step)
            adapter_name = f"{type(adapter).__module__}.{type(adapter).__qualname__}"
            proposed = m.ExecutionClaim(
                idempotency_key=key, incident_id=incident.id, intervention_id=intervention.id,
                intervention_hash=artifact_hash(intervention), step_id=step.id,
                capability=step.capability, request_hash=request_hash,
                adapter=adapter_name, executor=self.executor_id, state="IN_FLIGHT", attempt=1,
                started_at=now, updated_at=now,
            )
            incident, claim, acquired = self.repository.begin_execution_claim(
                proposed, expected_revision=incident.revision)
            if not acquired:
                raise ExecutionBusy("execution claim changed concurrently")
            try:
                result = self._execute_step(adapter, incident, intervention, step, claim)
            except Exception as exc:
                terminal_status = failure_status(adapter, exc)
                failed = self._receipt(
                    incident, intervention, step, claim, status=terminal_status,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                )
                # Claim-identity CAS: evidence arriving during the external call must
                # not lose the receipt of an action that already happened.
                incident = self.repository.finish_execution_claim(failed)
                receipt_ids.append(failed.id)
                self._fail_phase(incident.id, f"step {step.id} failed")
                report = self._report(incident.id, intervention.id, receipt_ids, skipped,
                                      deferred, external)
                error_type = ExecutionFailed if terminal_status == "FAILED" else ExecutionAmbiguous
                raise error_type(f"step {step.id} failed: {exc}", report) from exc
            confirmed = self._receipt(
                incident, intervention, step, claim, status="CONFIRMED",
                external_ids=self._external_ids(result),
            )
            incident = self.repository.finish_execution_claim(confirmed)
            receipt_ids.append(confirmed.id)
            external.update(confirmed.external_ids)

        incident = self.repository.fetch_incident(incident.id)
        if incident.phase != m.IncidentPhase.EXECUTING:
            raise ExecutionDenied("incident left EXECUTING before completion")
        self.repository.transition(incident.id, m.IncidentPhase.OBSERVING,
                                   expected_revision=incident.revision,
                                   reason="actions dispatched; outcome observation required")
        return self._report(incident.id, intervention.id, receipt_ids, skipped, deferred, external)
