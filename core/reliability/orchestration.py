"""Application-owned advisory run guards and validation; no authoritative promotion.

Only evidence acquisition writes, through the existing EvidenceService.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import json

from strands import ToolContext
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent

from core.agents.contracts import (
    AdvisoryInput, CriticAssessment, DiagnosticAssessment, EngineeringAssessment,
    DelegationQuery, DelegationRecord, EvidenceFollowup, EvidenceNeed, EvidenceRequestRecord,
    MaintenancePlanAssessment, OperationsAssessment, SpecialistContext, SupervisorDecision,
    SupervisorBounds, SupervisorResult,
)
from core.agents.critic import review_assessment
from core.agents.diagnostic import assess_diagnosis
from core.agents.engineering import assess_engineering
from core.agents.invocation import SpecialistInvocationError
from core.agents.operations import assess_operations
from core.agents.planner import plan_maintenance
from core.agents.runtime import StrandsRuntime
from core.agents.tools import EvidenceQuery, SPECIALIST_TOOL_NAMES, bounded_result
from .assessments import prepare_specialist_context
from .evidence import (
    DeferredEvidenceLedger, EvidenceCollection, EvidenceDeferred, EvidenceDeferredToApplication, EvidenceService,
)
from .repository import IncidentRepository, InvalidReference, new_id


ROLE_CONTRACTS = {
    "diagnostic": DiagnosticAssessment, "engineering": EngineeringAssessment,
    "operations": OperationsAssessment, "critic": CriticAssessment,
    "planner": MaintenancePlanAssessment,
}


def assessment_dependencies(keys: tuple[str, ...], advice: dict[str, AdvisoryInput]) -> tuple[str, ...]:
    """Select the complete provenance closure, never strip prior report references."""
    selected: set[str] = set()
    visiting: set[str] = set()

    def visit(key):
        if key not in advice:
            raise InvalidReference("unsupplied advisory key")
        if key in visiting:
            raise InvalidReference("cyclic advisory references")
        if key in selected:
            return
        visiting.add(key)
        for dependency in advice[key].assessment.input_assessment_keys:
            visit(dependency)
        visiting.remove(key)
        selected.add(key)

    for key in keys:
        visit(key)
    return tuple(key for key in advice if key in selected)


def delegation_context(repository: IncidentRepository, initial: SpecialistContext, *,
                       evidence_ids: tuple[str, ...], advice: dict[str, AdvisoryInput],
                       keys: tuple[str, ...], question: str) -> SpecialistContext:
    selected = assessment_dependencies(keys, advice)
    if len(selected) > 5:
        raise ValueError("advisory dependency closure exceeds five-report packet bound")
    return prepare_specialist_context(
        repository, initial.incident_id, asset_id=initial.asset_id, run_id=initial.run_id,
        evidence_ids=evidence_ids, artifact_ids=tuple(item.id for item in initial.artifacts),
        advisory_inputs=tuple(advice[key] for key in selected),
        evidence_purpose=initial.evidence_purpose, run_purpose=initial.run_purpose, question=question,
        review_target_id=initial.review_target_id, review_target_hash=initial.review_target_hash,
    )


def validate_supervisor_decision(decision: SupervisorDecision, scope: SpecialistContext,
                                 advice: dict[str, AdvisoryInput], evidence_ids: set[str]) -> SupervisorDecision:
    decision = SupervisorDecision.model_validate(decision.model_dump())
    if (decision.incident_id, decision.run_id) != (scope.incident_id, scope.run_id):
        raise InvalidReference("supervisor output belongs to another incident/run")
    if not set(decision.evidence_used) <= evidence_ids:
        raise InvalidReference("supervisor cites evidence not supplied or collected")
    selections = {
        "diagnostic": (decision.candidate_diagnosis_key,),
        "engineering": (decision.engineering_key,), "operations": (decision.operations_key,),
        "critic": decision.critic_keys, "planner": (decision.maintenance_plan_key,),
    }
    for role, keys in selections.items():
        for key in keys:
            if key is not None and (key not in advice or not isinstance(advice[key].assessment, ROLE_CONTRACTS[role])):
                raise InvalidReference("supervisor assessment reference is absent or has the wrong role")
    return decision


def latest_assessments(advice: dict[str, AdvisoryInput]) -> dict[str, str]:
    return {role: key for key, item in advice.items() for role, cls in ROLE_CONTRACTS.items()
            if isinstance(item.assessment, cls)}


def conclusion_gaps(advice: dict[str, AdvisoryInput], purpose="INVESTIGATION") -> tuple[str, ...]:
    """Conservative completeness checks, explicitly not technical or policy approval."""
    latest = latest_assessments(advice)
    if purpose == "DIAGNOSIS":
        diagnostic = latest.get("diagnostic")
        reviewed = any(isinstance(item.assessment, CriticAssessment)
                       and item.assessment.subject_id == diagnostic
                       and item.assessment.recommendation == "ACCEPT" for item in advice.values())
        return () if diagnostic and reviewed else ("Selected diagnosis requires explicit critic review.",)
    if purpose == "INTERVENTION_REVIEW":
        return () if {"engineering", "operations", "critic"} <= latest.keys() else (
            "Exact draft requires engineering, operations, and critic review.",)
    if set(latest) != set(ROLE_CONTRACTS):
        return ("All five specialist roles are required for a supported maintenance conclusion.",)
    diagnostic = advice[latest["diagnostic"]].assessment
    engineering = advice[latest["engineering"]].assessment
    operations = advice[latest["operations"]].assessment
    plan = advice[latest["planner"]].assessment
    gaps = []
    if diagnostic.recommended_hypothesis is None:
        gaps.append("No diagnostic hypothesis is recommended.")
    if engineering.intervention_feasibility != "FEASIBLE" or engineering.safety_concerns:
        gaps.append("Engineering feasibility or safety remains unresolved.")
    if operations.resource_feasibility != "FEASIBLE":
        gaps.append("Operational feasibility remains unresolved.")
    if latest["diagnostic"] not in assessment_dependencies(engineering.input_assessment_keys, advice):
        gaps.append("Engineering advice does not include the current diagnostic assessment.")
    if latest["engineering"] not in assessment_dependencies(operations.input_assessment_keys, advice):
        gaps.append("Operations advice does not include the current engineering assessment.")
    if plan.unresolved_blockers or any(value is None for value in (
            plan.estimated_exposure, plan.reversible, plan.safety_relevant, plan.external_commitment)):
        gaps.append("Maintenance proposal has unresolved blockers or unknown exposure/risk metadata.")
    required = {latest[role] for role in ("diagnostic", "engineering", "operations")}
    plan_inputs = set(assessment_dependencies(plan.input_assessment_keys, advice))
    if not required <= plan_inputs:
        gaps.append("Maintenance proposal does not include the current specialist inputs.")
    # Each current technical input must be in a critic's explicit review packet;
    # reviewing an old diagnostic report cannot validate a new engineering proposal.
    reviewed = set()
    for key in plan_inputs:
        item = advice[key].assessment
        if isinstance(item, CriticAssessment) and item.recommendation == "ACCEPT":
            reviewed.update(item.input_assessment_keys)
    if not required <= reviewed:
        gaps.append("Current diagnostic, engineering, and operations advice needs critic review.")
    return tuple(gaps)


class OrchestrationLimitError(ValueError):
    pass


def _needs(assessment) -> tuple[EvidenceNeed, ...]:
    if isinstance(assessment, DiagnosticAssessment):
        return assessment.missing_evidence_requests
    if isinstance(assessment, CriticAssessment):
        return assessment.requested_additional_evidence
    return ()


def _error(code: str) -> dict:
    return {"status": "error", "content": [{"json": {"error_code": code, "advisory_only": True}}]}


class _DeferredNeed:
    """Evidence-cache entry: the need was deferred to the application, not collected."""
    __slots__ = ("deferral_id",)

    def __init__(self, deferral_id: str):
        self.deferral_id = deferral_id


class EvidenceGuard:
    """The run's evidence requester handed to nested Diagnostic/Critic agents.

    Callable exactly like the plain requester; it also recognizes the structured
    deferral results this run issued, so the specialist hook can tell an
    application-deferred need from a failed tool call without reading any text.
    """

    def __init__(self, run: "SupervisorRun"):
        self._run = run

    async def __call__(self, role, scope, query: EvidenceQuery) -> EvidenceCollection:
        return await self._run.collect_evidence(role, scope, query)

    def recognizes_deferral(self, result) -> bool:
        return self._run.deferred.recognizes(result)


def assemble_result(scope: SpecialistContext, advice: dict[str, AdvisoryInput], *,
                    decision: SupervisorDecision | None, reason: str,
                    delegations: tuple[DelegationRecord, ...], requests: tuple[EvidenceRequestRecord, ...],
                    exhausted: set[str], errors: set[str], tool_calls: int, bounds: SupervisorBounds,
                    invalid_output: bool) -> SupervisorResult:
    """Application-owned assembly of the advisory audit from validated components.

    Shared by the local run (``SupervisorRun.finish``) and the Step 15 trust layer,
    so a remotely produced result is recomputed with exactly the local disposition
    rules; the returned disposition is never taken from the model or the wire.
    """
    latest = latest_assessments(advice)
    critics = tuple(key for key, item in advice.items() if isinstance(item.assessment, CriticAssessment))
    # Keep objections on current subjects. Old reports remain in the audit;
    # replacing one requires a new critic review before a supported conclusion.
    active = [advice[key].assessment for role, key in latest.items() if role != "critic"]
    for key in critics:
        critic = advice[key].assessment
        if critic.subject_kind != "assessment" or critic.subject_id in latest.values():
            # A later agreeable review cannot erase objections on an unchanged report.
            active.append(critic)
    needs = list(decision.unresolved_evidence_needs if decision else ())
    blockers = list(decision.blockers if decision else ())
    for item in active:
        needs.extend(_needs(item))
        blockers.extend(item.uncertainties)
        if isinstance(item, EngineeringAssessment):
            blockers.extend((*item.missing_constraints, *item.blockers, *item.safety_concerns))
        elif isinstance(item, OperationsAssessment):
            blockers.extend(item.blockers)
        elif isinstance(item, MaintenancePlanAssessment):
            blockers.extend(item.unresolved_blockers)
        elif isinstance(item, CriticAssessment):
            blockers.extend((*item.evidence_gaps, *item.contradictions, *item.unsupported_claims))
            if item.recommendation != "ACCEPT":
                blockers.append("Current critic objections require evidence or revision and another review.")
    for request in requests:
        if request.status != "COLLECTED":
            needs.append(EvidenceNeed(capability=request.capability, question=request.question))
    gaps = conclusion_gaps(advice, scope.run_purpose)
    blockers.extend((*sorted(errors), *gaps))
    disposition = decision.disposition if decision else "ESCALATED"
    if exhausted:
        reason = "TIMEOUT" if reason == "TIMEOUT" else "LIMIT_EXHAUSTED"
        disposition = "ESCALATED"
    elif reason != "MODEL_COMPLETED":
        disposition = "ESCALATED"
    elif errors:
        disposition = "BLOCKED"
    elif needs and disposition not in {"BLOCKED", "ESCALATED"}:
        disposition = "NEEDS_EVIDENCE"
    elif (blockers or gaps) and disposition == "ADVISORY_CONCLUSION":
        disposition = "UNRESOLVED"
    used = set(decision.evidence_used if decision else ())
    for item in advice.values():
        used.update(item.assessment.evidence_reviewed)
    # An immutable snapshot: cancelled threads cannot add later results to this run.
    return SupervisorResult(
        incident_id=scope.incident_id, run_id=scope.run_id,
        input_revision=scope.input_revision, disposition=disposition, decision=decision,
        assessments=tuple(advice.values()), delegations=tuple(delegations),
        evidence_requests=tuple(requests), evidence_used=tuple(sorted(used)),
        candidate_diagnosis_key=latest.get("diagnostic"), engineering_key=latest.get("engineering"),
        operations_key=latest.get("operations"), critic_keys=critics,
        maintenance_plan_key=latest.get("planner"),
        unresolved_evidence_needs=tuple(dict.fromkeys(needs)), blockers=tuple(dict.fromkeys(blockers)),
        termination_reason=reason, exhausted_limits=tuple(sorted(exhausted)),
        tool_calls=tool_calls, bounds=bounds,
        invalid_output=invalid_output,
    )


class SupervisorRun:
    """One event-loop-owned run. Never shared between incidents or reused."""

    def __init__(self, runtime: StrandsRuntime, specialist_runtime: StrandsRuntime,
                 service: EvidenceService, scope: SpecialistContext, bounds: SupervisorBounds,
                 *, progress=None, cancelled=None):
        self.runtime, self.specialist_runtime = runtime, specialist_runtime
        self.service, self.scope, self.bounds = service, scope, bounds
        # Stage 2: safe status callback and cooperative cancellation poll (no authority).
        self._progress, self._cancelled = progress, cancelled
        self.advice = {item.key: item for item in scope.advisory_inputs}
        assessment_dependencies(tuple(self.advice), self.advice)
        self.evidence_ids = dict.fromkeys(item.id for item in scope.evidence)
        self.delegations: list[DelegationRecord] = []
        self.requests: list[EvidenceRequestRecord] = []
        # Deferral results are issued and recognized only against this run's records.
        self.deferred = DeferredEvidenceLedger(self.requests)
        self.role_calls: Counter = Counter()
        self.delegation_cache: dict[tuple, dict] = {}
        self.evidence_cache: dict[str, EvidenceCollection | None | _DeferredNeed] = {}
        self.exhausted: set[str] = set()
        self.errors: set[str] = set()
        self.tool_calls = 0
        self.invalid_output = False
        self.closed = False

    def check_scope(self, context: ToolContext):
        expected = self.invocation_state()
        if self.closed or any(context.invocation_state.get(key) != value for key, value in expected.items()):
            raise InvalidReference("tool invocation does not match active incident/run scope")

    def invocation_state(self):
        return {"incident_id": self.scope.incident_id, "run_id": self.scope.run_id,
                "input_revision": self.scope.input_revision}

    def limit(self, name: str):
        self.exhausted.add(name)
        raise OrchestrationLimitError(f"orchestration limit exhausted: {name}")

    def notify(self, **payload) -> None:
        """Structured, secret-free status for the caller; a failing observer never affects the run."""
        if self._progress is None:
            return
        try:
            self._progress({"incident_id": self.scope.incident_id, "run_id": self.scope.run_id, **payload})
        except Exception:  # noqa: BLE001 - observability only
            pass

    def cancellation_requested(self) -> bool:
        if self._cancelled is None:
            return False
        try:
            return bool(self._cancelled())
        except Exception:  # noqa: BLE001 - a broken poll never stops a run on its own
            return False

    def before_tool(self, event: BeforeToolCallEvent):
        if self.cancellation_requested():
            # Cooperative checkpoint at the tool boundary: no further delegation, evidence
            # acquisition or model turn for a superseded run. Whatever came back so far is
            # still fenced by the caller; this only stops wasting provider time.
            self.notify(stage="cancellation_observed", boundary="tool", tool=event.tool_use["name"])
            event.cancel_tool = "Run cancelled: the operator instruction was superseded"
            event.agent.cancel()
            return
        if self.tool_calls >= self.bounds.max_tool_calls:
            self.exhausted.add("supervisor_tool_calls")
            event.cancel_tool = "Supervisor tool call budget exhausted"
            event.agent.cancel()
        else:
            self.tool_calls += 1

    def after_tool(self, event: AfterToolCallEvent):
        if event.result["status"] == "error":
            if event.tool_use["name"] == "SupervisorDecision":
                self.invalid_output = True
            elif not self.deferred.recognizes(event.result):
                # Only a deferral this run issued is an unresolved need rather than a
                # failed call; marker text in any other error never counts.
                self.errors.add("A supervisor tool call was rejected or failed.")

    async def collect_evidence(self, role, scope, query: EvidenceQuery) -> EvidenceCollection:
        """Shared by supervisor and nested Diagnostic/Critic tools, including failures."""
        if self.closed or (scope.incident_id, scope.run_id, scope.asset_id) != (
                self.scope.incident_id, self.scope.run_id, self.scope.asset_id):
            raise InvalidReference("evidence request outside active incident/run scope")
        query = EvidenceQuery.model_validate(query)
        allowed_role = "diagnostic" if role == "supervisor" else role
        if allowed_role not in {"diagnostic", "critic"}:
            raise InvalidReference("role cannot request evidence")
        purpose = scope.evidence_purpose if role in {"critic", "supervisor"} else "diagnosis"
        # Normalize before deduplication, while retaining invalid attempts in the audit.
        validation_error = None
        try:
            if query.capability not in SPECIALIST_TOOL_NAMES[allowed_role] - {"request_evidence"}:
                raise ValueError("unsupported evidence capability for this role")
            parameters = self.service.capabilities.validate_parameters(query.capability, query.parameters)
            fingerprint = json.dumps([query.capability, parameters, purpose], sort_keys=True)
        except ValueError as exc:
            validation_error = exc
            fingerprint = json.dumps([query.capability, query.parameters, purpose], sort_keys=True)
        if fingerprint in self.evidence_cache:
            cached = self.evidence_cache[fingerprint]
            if cached is None:
                raise ValueError("duplicate failed evidence request")
            if isinstance(cached, _DeferredNeed):
                raise EvidenceDeferredToApplication(self.deferred.tool_result(cached.deferral_id))
            return cached
        # Invalid/unsupported attempts consume budget too. Successful normalized
        # duplicates reuse provenance even if question text or requesting role differs.
        if len(self.requests) >= self.bounds.max_evidence_requests:
            self.limit("evidence_requests")
        if len(self.evidence_ids) >= 20:
            self.limit("evidence_packet")
        index = len(self.requests)
        record = dict(requested_by=role, capability=query.capability, question=query.question, required_for=purpose)
        if validation_error is None:
            record["parameters"] = parameters
        self.requests.append(EvidenceRequestRecord(**record, status="CANCELLED", error_code="IncompleteCollection"))
        self.evidence_cache[fingerprint] = None
        self.notify(stage="evidence_considered", role=role, capability=query.capability, status="requested")
        try:
            if validation_error is not None:
                raise validation_error
            collection = await asyncio.to_thread(
                self.service.request_and_collect, scope.incident_id, requested_by=role,
                equipment_ids=(scope.asset_id,), question=query.question,
                capability=query.capability, required_for=purpose, parameters=parameters,
            )
            # Service return values are still checked against the durable incident.
            if (collection.request.incident_id != scope.incident_id or
                    collection.request.resolved_by_evidence_ids != (collection.evidence.id,) or
                    self.service.repository.get_artifact(scope.incident_id, collection.request.id) != collection.request or
                    self.service.repository.get_artifact(scope.incident_id, collection.evidence.id) != collection.evidence or
                    collection.result.model_dump(mode="json") != collection.evidence.payload):
                raise InvalidReference("evidence collection request outside trusted scope")
            record.update(evidence_id=collection.evidence.id, request_id=collection.request.id)
            bounded_result(collection)
            evidence_ids = tuple(dict.fromkeys((*self.evidence_ids, collection.evidence.id)))
            delegation_context(self.service.repository, self.scope, evidence_ids=evidence_ids,
                               advice=self.advice, keys=(), question=self.scope.question)
            self.evidence_ids[collection.evidence.id] = None
            self.evidence_cache[fingerprint] = collection
            self.requests[index] = EvidenceRequestRecord(
                **record, status="UNAVAILABLE" if collection.evidence.quality == "MISSING" else "COLLECTED")
            self.notify(stage="evidence_considered", role=role, capability=query.capability,
                        status=self.requests[index].status, evidence_id=collection.evidence.id)
            return collection
        except asyncio.CancelledError:
            raise
        except EvidenceDeferred:
            # Packet mode (Step 15): this run cannot write. The need is recorded with
            # its normalized parameters for the application to collect later; it is
            # not a model error, so it counts as an unresolved need, never a blocker.
            # The tool returns a structured result bound to this record; no exception
            # and no marker text reaches the SDK.
            self.requests[index] = EvidenceRequestRecord(**record, status="DEFERRED")
            deferral_id = self.deferred.issue(index, capability=query.capability, question=query.question)
            self.evidence_cache[fingerprint] = _DeferredNeed(deferral_id)
            raise EvidenceDeferredToApplication(self.deferred.tool_result(deferral_id))
        except Exception as exc:
            self.requests[index] = EvidenceRequestRecord(**record, status="FAILED", error_code=type(exc).__name__)
            self.errors.add("Evidence acquisition failed; the evidence need remains unresolved.")
            raise ValueError("evidence acquisition failed; preserve uncertainty") from exc

    async def delegate(self, role: str, query: DelegationQuery, context: ToolContext) -> dict:
        self.check_scope(context)
        query = DelegationQuery.model_validate(query)
        try:
            packet = delegation_context(
                self.service.repository, self.scope, evidence_ids=tuple(self.evidence_ids),
                advice=self.advice, keys=query.input_assessment_keys, question=query.question)
            fingerprint = (role, tuple(sorted(item.key for item in packet.advisory_inputs)),
                           tuple(sorted(self.evidence_ids)))
            if fingerprint in self.delegation_cache:
                return self.delegation_cache[fingerprint]
            if len(self.delegations) >= self.bounds.max_delegations:
                self.limit("specialist_delegations")
            if self.role_calls[role] >= self.bounds.max_role_invocations:
                self.limit(f"{role}_invocations")
        except Exception as exc:
            self.errors.add("A delegation was blocked by scope, packet, or orchestration limits.")
            return _error(type(exc).__name__)
        key = f"assessment:{new_id()}"
        self.role_calls[role] += 1
        index = len(self.delegations)
        record = dict(key=key, role=role, question=query.question, input_revision=packet.input_revision,
                      input_assessment_keys=tuple(item.key for item in packet.advisory_inputs),
                      evidence_ids=tuple(item.id for item in packet.evidence))
        self.delegations.append(DelegationRecord(**record, status="CANCELLED", error_code="IncompleteInvocation"))
        # Reserve fingerprint before awaiting: failed identical calls cannot start another agent.
        self.delegation_cache[fingerprint] = _error("PreviousDelegationFailed")
        self.notify(stage="specialist_started", role=role, key=key, evidence_count=len(record["evidence_ids"]),
                    provider=self.specialist_runtime.settings.provider, model=self.specialist_runtime.settings.model_id)
        try:
            invoke = {"diagnostic": assess_diagnosis, "engineering": assess_engineering,
                      "operations": assess_operations, "critic": review_assessment,
                      "planner": plan_maintenance}[role]
            kwargs = {"evidence_requester": EvidenceGuard(self)} if role in {"diagnostic", "critic"} else {}
            assessment = await invoke(self.specialist_runtime, self.service, packet, **kwargs)
            item = AdvisoryInput(key=key, assessment=assessment)
            result = bounded_result(item)
            self.advice[key] = item
            self.delegations[index] = DelegationRecord(**record, status="SUCCEEDED")
            self.delegation_cache[fingerprint] = result
            self.notify(stage="specialist_completed", role=role, key=key, status="SUCCEEDED")
            return result
        except asyncio.CancelledError:
            self.notify(stage="specialist_completed", role=role, key=key, status="CANCELLED")
            raise
        except Exception as exc:
            self.delegations[index] = DelegationRecord(**record, status="FAILED", error_code=type(exc).__name__)
            self.notify(stage="specialist_completed", role=role, key=key, status="FAILED", error_code=type(exc).__name__)
            if isinstance(exc, SpecialistInvocationError) and (exc.stop_reason or "").startswith("limit_"):
                self.exhausted.add(f"{role}_{exc.stop_reason}")
            elif isinstance(exc, asyncio.TimeoutError):
                self.exhausted.add(f"{role}_timeout")
            self.errors.add(f"{role} specialist failed; no assessment from that invocation was accepted.")
            return _error(type(exc).__name__)

    async def acquire(self, request: EvidenceFollowup, tool_context: ToolContext) -> dict:
        self.check_scope(tool_context)
        request = EvidenceFollowup.model_validate(request)
        if request.assessment_key not in self.advice:
            raise InvalidReference("evidence need requires a supplied assessment")
        needs = _needs(self.advice[request.assessment_key].assessment)
        if request.need_index >= len(needs):
            raise InvalidReference("evidence need index outside supplied assessment")
        need = needs[request.need_index]
        query = EvidenceQuery(capability=need.capability, question=need.question,
                              parameters=request.query_parameters)
        try:
            collection = await self.collect_evidence("supervisor", self.scope, query)
        except EvidenceDeferredToApplication as deferred:
            return deferred.tool_result
        return bounded_result(collection)

    def finish(self, decision: SupervisorDecision | None, reason: str) -> SupervisorResult:
        return assemble_result(
            self.scope, self.advice, decision=decision, reason=reason,
            delegations=tuple(self.delegations), requests=tuple(self.requests),
            exhausted=self.exhausted, errors=self.errors, tool_calls=self.tool_calls,
            bounds=self.bounds, invalid_output=self.invalid_output)
