"""Application-side trust boundary for advisory results produced elsewhere.

``validate_response`` is the only way a remote (or in-process packet) result
enters the application. It re-checks envelope, correlation, runtime identity and
every reference against the durable snapshot, replays the local per-delegation
validation, then recomputes the audit with the local disposition rules and keeps
the more conservative reading. It never persists or promotes anything.
"""
from __future__ import annotations

from collections import Counter

from pydantic import ValidationError

from core.agents.contracts import SpecialistContext, SupervisorBounds, SupervisorResult
from core.reliability import models as m
from core.reliability.assessments import validate_specialist_assessment
from core.reliability.orchestration import (
    ROLE_CONTRACTS, assemble_result, delegation_context, validate_supervisor_decision,
)
from core.reliability.repository import InvalidReference
from .errors import ReasoningBackendUnavailable
from .protocol import PROTOCOL_VERSION, ReasoningResponse, RuntimeIdentity

DISPOSITION_ORDER = ("ADVISORY_CONCLUSION", "UNRESOLVED", "NEEDS_EVIDENCE", "BLOCKED", "ESCALATED")
SELECTION_FIELDS = ("candidate_diagnosis_key", "engineering_key", "operations_key", "maintenance_plan_key", "critic_keys")


def _reject(code: str, message: str, *, retryable: bool = False):
    raise ReasoningBackendUnavailable(message, code=code, retryable=retryable)


def validate_response(*, snapshot: m.SupervisorRunSnapshot, context: SpecialistContext, response,
                      repository, expected_identity: RuntimeIdentity) -> SupervisorResult:
    """Return the application-validated advisory result or raise ``ReasoningBackendUnavailable``."""
    if isinstance(response, ReasoningResponse):
        envelope = response
    else:
        if not isinstance(response, dict):
            _reject("PROTOCOL", "reasoning response is not a JSON object")
        if response.get("protocol_version") != PROTOCOL_VERSION:
            _reject("PROTOCOL_MISMATCH", f"expected protocol {PROTOCOL_VERSION}")
        try:
            envelope = ReasoningResponse.model_validate(response)
        except ValidationError as exc:
            _reject("PROTOCOL", f"reasoning response rejected: {exc.error_count()} error(s)")
    if envelope.status == "FAILED":
        _reject(envelope.failure.code, envelope.failure.message, retryable=envelope.failure.retryable)
    if (envelope.incident_id, envelope.run_id, envelope.snapshot_id, envelope.input_revision) != (
            snapshot.incident_id, snapshot.run_id, snapshot.id, snapshot.input_revision):
        _reject("CORRELATION", "response correlation differs from the durable run snapshot")
    if (context.incident_id, context.run_id, context.input_revision, context.asset_id) != (
            snapshot.incident_id, snapshot.run_id, snapshot.input_revision, snapshot.asset_id):
        _reject("CORRELATION", "context differs from the durable run snapshot")
    drift = envelope.runtime_identity.drift(expected_identity)
    if drift:
        _reject("VERSION_MISMATCH", "runtime identity differs from expected: " + ", ".join(drift))
    try:
        result = SupervisorResult.model_validate(envelope.result)
    except ValidationError as exc:
        _reject("PROTOCOL", f"advisory result rejected: {exc.error_count()} error(s)")
    try:
        return _revalidate(snapshot, context, result, repository)
    except (InvalidReference, ValueError) as exc:
        _reject("RESULT_INVALID", f"{type(exc).__name__}: {exc}")


def _errors(result: SupervisorResult) -> set[str]:
    """Local-run error semantics recomputed from the audit records, never from the wire."""
    errors = set()
    if any(item.status != "SUCCEEDED" for item in result.delegations):
        errors.add("A specialist delegation failed; no assessment from that invocation was accepted.")
    if any(item.status in {"FAILED", "CANCELLED"} for item in result.evidence_requests):
        errors.add("Evidence acquisition failed; the evidence need remains unresolved.")
    if result.invalid_output:
        errors.add("A supervisor tool call was rejected or failed.")
    return errors


def _revalidate(snapshot, context, result: SupervisorResult, repository) -> SupervisorResult:
    bounds = SupervisorBounds.model_validate(snapshot.bounds)
    if (result.incident_id, result.run_id, result.input_revision) != (
            snapshot.incident_id, snapshot.run_id, snapshot.input_revision):
        raise InvalidReference("result scope differs from the durable run snapshot")
    if result.bounds != bounds:
        raise InvalidReference("result bounds differ from the frozen run bounds")
    manifest = set(snapshot.evidence_manifest)
    if {item.id for item in context.evidence} != manifest:
        raise InvalidReference("snapshot context evidence differs from its manifest")
    cited = set(result.evidence_used)
    if result.decision is not None:
        cited.update(result.decision.evidence_used)
    for item in result.assessments:
        cited.update(item.assessment.evidence_reviewed)
    for record in result.delegations:
        cited.update(record.evidence_ids)
    if cited - manifest:
        raise InvalidReference("result cites evidence outside the frozen packet")
    for key in sorted(manifest):
        stored = repository.get_artifact(snapshot.incident_id, key)
        if not isinstance(stored, m.Evidence) or snapshot.asset_id not in stored.equipment_ids:
            raise InvalidReference("frozen evidence is not a durable record of this incident and asset")
    for record in result.evidence_requests:
        if record.status in {"COLLECTED", "UNAVAILABLE"} or record.evidence_id is not None or record.request_id is not None:
            raise InvalidReference("a remote run cannot collect durable evidence or mint identities")
    if (len(result.delegations) > bounds.max_delegations or result.tool_calls > bounds.max_tool_calls
            or len(result.evidence_requests) > bounds.max_evidence_requests):
        raise ValueError("orchestration bounds violated")
    advice = {item.key: item for item in context.advisory_inputs}
    remote = {item.key: item for item in result.assessments}
    if len(remote) != len(result.assessments) or set(remote) & set(advice):
        raise InvalidReference("duplicate or reserved advisory keys")
    role_calls: Counter = Counter()
    for record in result.delegations:
        if record.input_revision != snapshot.input_revision:
            raise InvalidReference("delegation input revision differs from the run snapshot")
        role_calls[record.role] += 1
        if role_calls[record.role] > bounds.max_role_invocations:
            raise ValueError("role invocation bound violated")
        # Replay the exact application packet the specialist would have received.
        packet = delegation_context(repository, context, evidence_ids=record.evidence_ids, advice=advice,
                                    keys=record.input_assessment_keys, question=record.question)
        if tuple(item.key for item in packet.advisory_inputs) != record.input_assessment_keys:
            raise InvalidReference("delegation inputs are not the application dependency closure")
        if record.status == "SUCCEEDED":
            item = remote.get(record.key)
            if item is None or record.error_code is not None:
                raise InvalidReference("successful delegation lacks its assessment or carries an error")
            if not isinstance(item.assessment, ROLE_CONTRACTS[record.role]):
                raise InvalidReference("assessment role differs from its delegation")
            validate_specialist_assessment(repository, item.assessment, packet, set())
            advice[record.key] = item
        elif record.key in remote:
            raise InvalidReference("failed delegation cannot carry an assessment")
    if set(remote) - set(advice):
        raise InvalidReference("assessment without a delegation record in this run")
    decision = result.decision
    if decision is not None:
        decision = validate_supervisor_decision(decision, context, advice, manifest)
    recomputed = assemble_result(
        context, advice, decision=decision, reason=result.termination_reason,
        delegations=result.delegations, requests=result.evidence_requests,
        exhausted=set(result.exhausted_limits), errors=_errors(result), tool_calls=result.tool_calls,
        bounds=bounds, invalid_output=result.invalid_output)
    for field in SELECTION_FIELDS:
        if getattr(result, field) != getattr(recomputed, field):
            raise InvalidReference("remote selections differ from the canonical application selections")
    # Conservative merge: the application's recomputation is the base; the remote
    # reading may only add caution, never remove it. Disposition is never copied.
    blockers = tuple(dict.fromkeys((*recomputed.blockers, *result.blockers)))
    needs = tuple(dict.fromkeys((*recomputed.unresolved_evidence_needs, *result.unresolved_evidence_needs)))
    disposition = max((result.disposition, recomputed.disposition), key=DISPOSITION_ORDER.index)
    if needs and disposition in {"ADVISORY_CONCLUSION", "UNRESOLVED"}:
        disposition = "NEEDS_EVIDENCE"
    if blockers and disposition == "ADVISORY_CONCLUSION":
        disposition = "UNRESOLVED"
    merged = recomputed.model_dump(mode="json") | {
        "disposition": disposition, "blockers": blockers, "unresolved_evidence_needs": [n.model_dump(mode="json") for n in needs],
        "evidence_used": sorted(set(result.evidence_used) | set(recomputed.evidence_used)),
        "invalid_output": result.invalid_output or recomputed.invalid_output}
    return SupervisorResult.model_validate(merged)
