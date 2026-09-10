"""Application authority, deliberately not an agent tool or engine integration.

Only run_supervisor invokes models, after start_run commits. All promotion gates
are local deterministic reads inside BEGIN IMMEDIATE. Private completion is an
application invocation seam, never a public endpoint accepting model/caller JSON.
"""
from __future__ import annotations

import asyncio
from importlib.metadata import version

from core import db
from core.agents.contracts import (
    CriticAssessment, DiagnosticAssessment, EngineeringAssessment, MaintenancePlanAssessment,
    OperationsAssessment, SpecialistContext, SupervisorBounds, SupervisorResult,
)
from . import models as m
from .freshness import closure, observation_manifest, revalidate
from .governance import WorkPackageParameters
from .repository import (
    IncidentRepository, InvalidReference, StaleRevision, content_hash, manifest_authority, new_id, utcnow,
)
from .resources import ResourceUnavailable, require_part_stock, require_qualified_technician
from .state import validate_transition

POLICY_VERSION = "operon-promotion-1"
VALIDATOR = "operon.application.promotion"
CONFIRM_MECHANISM = "operon.confirm_mechanism"
CONFIRM_RESOURCES = "operon.confirm_resources"


class PromotionRefused(ValueError):
    def __init__(self, reason: str, *, disposition="BLOCKED"):
        super().__init__(reason)
        self.disposition = disposition


class PromotionConflict(ValueError):
    pass


def _require(condition, reason, *, evidence=False):
    if not condition:
        raise PromotionRefused(reason, disposition="NEEDS_EVIDENCE" if evidence else "BLOCKED")


def _hash(value):
    return content_hash(value.model_dump(mode="json"))


def _identity(incident_id):
    return dict(id=new_id(), incident_id=incident_id, created_at=utcnow())


def executable_content_hash(intervention: m.Intervention) -> str:
    """Everything except explicitly application-controlled envelope fields."""
    return content_hash(intervention.model_dump(mode="json", exclude={
        "id", "created_at", "status", "revision", "supersedes_id",
    }))


class PromotionService:
    def __init__(self, repository: IncidentRepository):
        self.repository = repository

    def _all(self, conn, incident_id, cls):
        return [self.repository._artifact(conn, incident_id, row[0]) for row in conn.execute(
            "SELECT artifact_id FROM incident_artifact WHERE incident_id=? AND kind=? ORDER BY rowid",
            (incident_id, cls.__name__))]

    def _get(self, conn, incident_id, artifact_id, cls):
        value = self.repository._artifact(conn, incident_id, artifact_id)
        _require(isinstance(value, cls), f"reference requires {cls.__name__}")
        return value

    def _current(self, conn, incident_id, artifact):
        _require(not any(getattr(item, "supersedes_id", None) == artifact.id
                         for item in self._all(conn, incident_id, type(artifact))),
                 "superseded source artifact")

    @staticmethod
    def _dependency_fresh(conn, evidence, cache):
        """Dependency-scoped freshness of one artifact (its own manifest only).

        The provenance DAG is walked by ``_evidence``; a DERIVED record is fresh
        exactly when every parent is. Legacy records carrying only the pre-13C
        whole-store hash cannot prove scoped freshness and must be collected again;
        a legacy model signal is a dated observation and remains valid.
        """
        reason = manifest_authority(evidence)
        _require(reason is None, reason or "", evidence=True)
        manifest = evidence.source_dependencies
        if manifest is None:
            _require(evidence.kind == "model_signal",
                     "evidence predates dependency-scoped freshness and must be collected again", evidence=True)
            return
        if manifest.basis == "DERIVED":
            _require(evidence.derived_from_ids, "derived evidence lacks provenance parents", evidence=True)
        changes = revalidate(conn, manifest, cache=cache)
        _require(not changes, "evidence source dependency changed: "
                 + ", ".join(item.dependency.describe() for item in changes), evidence=True)

    def _evidence(self, conn, incident, asset_id, ids, *, fresh=True):
        """Complete durable dependency closure, with exact scope and source provenance."""
        found, visiting, cache = {}, set(), {}

        def visit(key):
            _require(key not in visiting, "cyclic evidence provenance")
            if key in found:
                return
            visiting.add(key)
            evidence = self._get(conn, incident.id, key, m.Evidence)
            _require(asset_id in evidence.equipment_ids, "evidence belongs to another asset")
            self._current(conn, incident.id, evidence)
            _require(evidence.content_hash == content_hash(evidence.payload), "evidence payload hash mismatch")
            _require(evidence.quality == "GOOD", "evidence quality is insufficient", evidence=True)
            _require(evidence.source_system != "legacy.unspecified" and evidence.source_capability != "legacy.unspecified",
                     "evidence lacks trusted source provenance", evidence=True)
            if fresh:
                self._dependency_fresh(conn, evidence, cache)
            for parent in evidence.derived_from_ids:
                visit(parent)
            visiting.remove(key)
            found[key] = evidence
        for key in ids:
            visit(key)
        return found

    @staticmethod
    def _closure(evidence):
        """Exact source dependency closure of an evidence packet (all artifacts, all parents)."""
        try:
            return closure(item.source_dependencies for item in evidence.values())
        except ValueError as exc:
            raise PromotionRefused(f"inconsistent evidence dependency closure: {exc}") from exc

    def _manifest(self, values):
        return {key: _hash(value) for key, value in sorted(values.items())}

    def _checkpoint(self, conn, incident, artifacts, *, phase=None, **changes):
        """One revision and event checkpoint for the entire atomic command."""
        for artifact in artifacts:
            self.repository._store_artifact(conn, incident, artifact, historical_input=True)
        if phase is not None and phase != incident.phase:
            validate_transition(incident.phase, phase)
            changes["phase"] = phase
        updated = self.repository._update(
            conn, incident, artifact_ids=(*incident.artifact_ids, *(item.id for item in artifacts)), **changes)
        for artifact in artifacts:
            self.repository._event(conn, updated, "ARTIFACT_ADDED", {
                "artifact_id": artifact.id, "kind": type(artifact).__name__, "boundary": VALIDATOR})
        if phase is not None and phase != incident.phase:
            self.repository._event(conn, updated, "PHASE_CHANGED", {
                "from": incident.phase.value, "to": phase.value, "reason": VALIDATOR})
        return updated

    def submit_technical_confirmation(self, confirmation: m.TrustedTechnicalConfirmation, *, expected_revision: int):
        """Trusted application submission only; never registered as an agent capability.

        Actor authentication/authorization belongs to the calling application. No
        public API or model-facing tool exposes this command in Step 13A.
        """
        confirmation = m.TrustedTechnicalConfirmation.model_validate_json(confirmation.model_dump_json())
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, confirmation.incident_id)
            self.repository._check(incident, expected_revision)
            _require(confirmation.asset_id in incident.equipment_ids, "confirmation asset scope mismatch")
            _require(confirmation.observed_at <= utcnow(), "confirmation observation is in the future")
            support = self._evidence(conn, incident, confirmation.asset_id, confirmation.supporting_evidence_ids)
            _require(any(item.kind in {"telemetry", "maintenance_history", "inspection"}
                         and item.source_capability != CONFIRM_MECHANISM for item in support.values()),
                     "confirmation needs independent technical evidence; model signal alone is insufficient", evidence=True)
            if confirmation.failure_mode_code:
                _require(conn.execute("SELECT 1 FROM failure_mode WHERE mode_code=?", (confirmation.failure_mode_code,)).fetchone(),
                         "unknown trusted failure mode")
            return self._submit_evidence(conn, incident, confirmation, CONFIRM_MECHANISM, "inspection",
                                         tuple(support))

    def _submit_evidence(self, conn, incident, payload, capability, kind, support=()):
        body = payload.model_dump(mode="json")
        evidence = m.Evidence(
            **_identity(incident.id), equipment_ids=(payload.asset_id,), kind=kind,
            source_uri=f"operon://trusted/{payload.source}", source_locator=f"actor:{payload.actor_id}",
            source_version=POLICY_VERSION, content_hash=content_hash(body), observed_at=payload.observed_at,
            retrieved_at=utcnow(), quality="GOOD", provenance=payload.provenance,
            summary=f"Trusted application submission: {capability}", payload=body,
            source_capability=capability, source_system=VALIDATOR, derived_from_ids=support,
            # An immutable dated observation by a trusted actor. Later source changes
            # never make it false; its supporting evidence is validated by its own
            # manifests through the provenance DAG whenever the closure is checked.
            source_dependencies=observation_manifest())
        self._checkpoint(conn, incident, [evidence])
        return evidence

    def _resource_rows(self, conn, asset_id, technician_id, parts):
        # Technician and stock rules are the shared deterministic dispatch rules; the
        # local CMMS adapter re-applies the same functions inside its reservation
        # transaction, so promotion-time success is never trusted at dispatch.
        try:
            asset, _ = require_qualified_technician(conn, asset_id, technician_id)
        except ResourceUnavailable as exc:
            raise PromotionRefused(str(exc), disposition="NEEDS_EVIDENCE") from exc
        rows = {}
        bom = {row["part_id"]: row for row in conn.execute(
            "SELECT ep.*,p.part_number,p.on_hand_qty FROM equipment_part ep JOIN part p USING(part_id) "
            "WHERE equipment_id=?", (asset_id,))}
        _require(bom and set(bom) == {part.part_id for part in parts}, "binding must cover the recorded BOM exactly", evidence=True)
        for part in parts:
            row = bom[part.part_id]
            _require(row["qty_per_service"] is not None and part.quantity >= row["qty_per_service"],
                     "insufficient parts or unknown BOM quantities", evidence=True)
            try:
                stock = require_part_stock(conn, part.part_id, part.quantity)
            except ResourceUnavailable as exc:
                raise PromotionRefused("insufficient parts or unknown BOM quantities", disposition="NEEDS_EVIDENCE") from exc
            rows[part.part_id] = dict(row) | {"reserved_quantity": stock["reserved_qty"]}
        return asset, rows

    @staticmethod
    def _inventory_snapshot(parts, rows):
        return tuple(m.ConfirmedInventory(
            part_id=part.part_id, part_number=rows[part.part_id]["part_number"],
            on_hand_quantity=rows[part.part_id]["on_hand_qty"],
            reserved_quantity=rows[part.part_id]["reserved_quantity"], required_quantity=part.quantity) for part in parts)

    def submit_resource_confirmation(self, confirmation: m.ResourceConfirmation, *, expected_revision: int):
        confirmation = m.ResourceConfirmation.model_validate_json(confirmation.model_dump_json())
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, confirmation.incident_id)
            self.repository._check(incident, expected_revision)
            _require(confirmation.asset_id in incident.equipment_ids, "resource confirmation asset mismatch")
            _require(confirmation.observed_at <= utcnow() < confirmation.window_start, "resource dates are not current")
            asset, rows = self._resource_rows(conn, confirmation.asset_id, confirmation.technician_id, confirmation.parts)
            _require(confirmation.qualification == asset["equipment_class"], "dated qualification mismatch")
            confirmation = confirmation.model_copy(update={"inventory_snapshot": self._inventory_snapshot(confirmation.parts, rows)})
            return self._submit_evidence(conn, incident, confirmation, CONFIRM_RESOURCES, "resource_availability")

    def start_run(self, incident_id: str, *, asset_id: str, stage: str, expected_revision: int,
                  evidence_ids: tuple[str, ...], runtime, specialist_runtime=None,
                  bounds: SupervisorBounds | None = None, draft_id: str | None = None):
        """Atomically claim a new application ID and freeze inputs; never invokes a model.

        A new claim supersedes an older active run, including an unfinished one.
        Its late completion remains auditable and is permanently ineligible.
        """
        from core.agents import supervisor, diagnostic, engineering, operations, critic, planner, invocation
        bounds = SupervisorBounds.model_validate(bounds or SupervisorBounds())
        def runtime_identity(value):
            model = value._model
            return {"settings": value.settings.model_dump(mode="json"),
                    "implementation": f"{type(model).__module__}.{type(model).__qualname__}" if model else "strands.BedrockModel",
                    "injected_configuration_hash": content_hash(model.get_config()) if model else None}
        # Even injected provider configuration is read before acquiring a DB lock.
        runtimes = {"supervisor": runtime_identity(runtime), "specialists": runtime_identity(specialist_runtime or runtime)}
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            self.repository._check(incident, expected_revision)
            _require(asset_id in incident.equipment_ids, "run asset outside incident scope")
            artifacts = []
            if stage == "DIAGNOSIS":
                _require(incident.phase == m.IncidentPhase.INVESTIGATING and draft_id is None,
                         "diagnosis run requires INVESTIGATING")
                question = "Assess competing mechanisms and explicitly review the selected diagnostic assessment."
            elif stage == "INTERVENTION_REVIEW":
                _require(incident.phase == m.IncidentPhase.PLANNING and draft_id, "draft review requires PLANNING and exact draft")
                diagnosis, lineage = self._lineage(conn, incident, incident.current_diagnosis_id, "diagnosis", current=True)
                draft = self._get(conn, incident_id, draft_id, m.Intervention)
                self._current(conn, incident_id, draft)
                _require(draft.status == "DRAFT" and draft.binding_id and draft.diagnosis_id == diagnosis.id,
                         "review requires application-bound draft for current diagnosis")
                self._get(conn, incident_id, draft.binding_id, m.WorkPackageBinding)
                _require(set(evidence_ids) == set(draft.evidence_ids), "review evidence must match exact draft evidence closure")
                artifacts = [diagnosis, self._get(conn, incident_id, lineage.verdict_id, m.ValidationVerdict), draft]
                question = f"Review exact draft {draft.id} with artifact hash {_hash(draft)}. Preserve its executable content."
            else:
                raise PromotionRefused("unsupported run stage")
            evidence = self._evidence(conn, incident, asset_id, evidence_ids)
            # Application-generated before any model reasoning; the model can neither
            # define nor modify what the frozen packet depends on.
            dependencies = self._closure(evidence)
            run_id = new_id()
            context = SpecialistContext(
                incident_id=incident_id, asset_id=asset_id, run_id=run_id, input_revision=incident.revision + 1,
                evidence=tuple(evidence.values()), artifacts=tuple(artifacts), lifecycle_state=incident.phase,
                run_purpose=stage, evidence_purpose="diagnosis" if stage == "DIAGNOSIS" else "intervention", question=question,
                review_target_id=draft.id if stage == "INTERVENTION_REVIEW" else None,
                review_target_hash=_hash(draft) if stage == "INTERVENTION_REVIEW" else None)
            prompts = {"supervisor": supervisor.SUPERVISOR_PROMPT, "diagnostic": diagnostic.DIAGNOSTIC_PROMPT,
                       "engineering": engineering.ENGINEERING_PROMPT, "operations": operations.OPERATIONS_PROMPT,
                       "critic": critic.CRITIC_PROMPT, "planner": planner.PLANNER_PROMPT, "grounding": invocation.GROUNDING_PROMPT}
            snapshot = m.SupervisorRunSnapshot(
                **_identity(incident_id), asset_id=asset_id, run_id=run_id, stage=stage,
                input_revision=context.input_revision, evidence_manifest=self._manifest(evidence),
                input_artifact_manifest={item.id: _hash(item) for item in artifacts},
                source_dependency_manifest=dependencies, context_payload=context.model_dump(mode="json"),
                bounds=bounds.model_dump(mode="json"),
                runtime_identity=runtimes,
                version_identity={"policy": POLICY_VERSION, "strands": version("strands-agents"),
                                  "prompts": content_hash(prompts), "schema": content_hash(SupervisorResult.model_json_schema()),
                                  "context_schema": content_hash(SpecialistContext.model_json_schema())})
            self._checkpoint(conn, incident, [snapshot], active_run_id=run_id)
            return snapshot

    async def run_supervisor(self, incident_id: str, *, service, runtime, specialist_runtime=None, **kwargs):
        """Durable wrapper for the existing native supervisor; engine hookup is 13B."""
        from core.agents.supervisor import supervise_reliability
        _require(service.repository.path.resolve() == self.repository.path.resolve()
                 and service.capabilities.path.resolve() == self.repository.path.resolve(), "run stores must match")
        snapshot = self.start_run(incident_id, runtime=runtime, specialist_runtime=specialist_runtime, **kwargs)
        context = SpecialistContext.model_validate(snapshot.context_payload)
        cancelled_result = None
        def preserve_cancellation(result):
            nonlocal cancelled_result
            cancelled_result = result
        try:
            result = await supervise_reliability(runtime, service, context,
                                                 bounds=SupervisorBounds.model_validate(snapshot.bounds),
                                                 specialist_runtime=specialist_runtime,
                                                 cancellation_result_handler=preserve_cancellation)
        except BaseException as exc:
            if not isinstance(exc, (Exception, asyncio.CancelledError)):
                raise
            reason = "CANCELLED" if isinstance(exc, asyncio.CancelledError) else "MODEL_FAILED"
            result = SupervisorResult(
                incident_id=incident_id, run_id=snapshot.run_id, input_revision=snapshot.input_revision,
                disposition="ESCALATED", decision=None, assessments=(), delegations=(), evidence_requests=(),
                evidence_used=(), candidate_diagnosis_key=None, engineering_key=None, operations_key=None,
                critic_keys=(), maintenance_plan_key=None, unresolved_evidence_needs=(),
                blockers=("Application invocation did not complete.",), termination_reason=reason,
                exhausted_limits=(), tool_calls=0, bounds=SupervisorBounds.model_validate(snapshot.bounds))
            self._complete_run(snapshot, cancelled_result or result)
            raise
        return self._complete_run(snapshot, result)

    def _complete_run(self, snapshot, result):
        """Private application completion, not caller-supplied promotion input."""
        result = SupervisorResult.model_validate_json(result.model_dump_json())
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, snapshot.incident_id)
            stored = self._get(conn, incident.id, snapshot.id, m.SupervisorRunSnapshot)
            _require(stored == snapshot, "snapshot differs from stored run")
            _require((result.incident_id, result.run_id, result.input_revision) == (
                snapshot.incident_id, snapshot.run_id, snapshot.input_revision), "wrong incident/run/input revision")
            for report in self._all(conn, incident.id, m.SupervisorReport):
                if report.run_id == snapshot.run_id:
                    if report.result_hash != _hash(result):
                        raise PromotionConflict("terminal report already exists with different result")
                    return report
            stale = []
            if incident.active_run_id != snapshot.run_id:
                stale.append("ACTIVE_RUN_CHANGED")
            if incident.revision != snapshot.input_revision:
                stale.append("REVISION_CHANGED_DURING_RUN")
            if snapshot.source_dependency_manifest is None:
                # A pre-13C snapshot froze only the whole-store hash, which can no
                # longer prove that the exact inputs are unchanged.
                stale.append("LEGACY_SOURCE_CHECKPOINT_UNVERIFIABLE")
            else:
                # Only reads the frozen packet actually relied upon can stale the run;
                # unrelated telemetry, incidents, technicians or bookings cannot.
                stale.extend(change.reason for change in revalidate(conn, snapshot.source_dependency_manifest))
            ids = set(snapshot.evidence_manifest) | set(result.evidence_used)
            ids.update(record.evidence_id for record in result.evidence_requests if record.evidence_id)
            for item in result.assessments:
                ids.update(item.assessment.evidence_reviewed)
            # Scope checks do not suppress failed/stale audit reports; hash every
            # actually referenced durable record, without pretending new evidence
            # was present at the original input checkpoint.
            evidence = {key: self._get(conn, incident.id, key, m.Evidence) for key in sorted(ids)}
            _require(all(snapshot.asset_id in item.equipment_ids for item in evidence.values()), "report evidence wrong asset")
            report = m.SupervisorReport(
                **_identity(incident.id), snapshot_id=snapshot.id, asset_id=snapshot.asset_id, run_id=snapshot.run_id,
                result_payload=result.model_dump(mode="json"), result_hash=_hash(result),
                input_revision=snapshot.input_revision, completion_revision=incident.revision,
                checkpoint_revision=incident.revision + 1, evidence_manifest=self._manifest(evidence),
                completion=result.termination_reason, stale_reasons=tuple(stale))
            self._checkpoint(conn, incident, [report])
            return report

    def _audit_result(self, snapshot, report):
        """Revalidate application audit, dependency DAG, canonical selections and calls."""
        from .orchestration import ROLE_CONTRACTS, assessment_dependencies, latest_assessments
        result = SupervisorResult.model_validate(report.result_payload)
        _require(result.termination_reason == "MODEL_COMPLETED" and not result.exhausted_limits and not result.invalid_output,
                 "run failed, cancelled, timed out or exhausted limits")
        _require(result.disposition == "ADVISORY_CONCLUSION" and result.decision is not None,
                 "run is not a supported advisory conclusion")
        _require(not result.blockers and not result.unresolved_evidence_needs,
                 "run has unresolved blockers or evidence needs", evidence=True)
        _require(result.bounds.model_dump(mode="json") == snapshot.bounds, "run bounds differ from snapshot")
        _require(len(result.delegations) <= result.bounds.max_delegations
                 and result.tool_calls <= result.bounds.max_tool_calls
                 and len(result.evidence_requests) <= result.bounds.max_evidence_requests, "orchestration bounds violated")
        _require(all(item.status == "SUCCEEDED" and item.error_code is None for item in result.delegations),
                 "unresolved specialist invocation failure")
        _require(all(item.status == "COLLECTED" and item.error_code is None for item in result.evidence_requests),
                 "unresolved evidence invocation failure", evidence=True)
        advice = {item.key: item for item in result.assessments}
        _require(len(advice) == len(result.assessments), "duplicate advisory keys")
        assessment_dependencies(tuple(advice), advice)
        records = {item.key: item for item in result.delegations}
        _require(len(records) == len(result.delegations) and records.keys() == advice.keys(),
                 "every selected assessment must originate in this successful run")
        seen = set()
        for record in result.delegations:
            assessment = advice[record.key].assessment
            _require(isinstance(assessment, ROLE_CONTRACTS[record.role]) and assessment.incident_id == snapshot.incident_id,
                     "assessment role/incident mismatch")
            _require(record.input_revision == snapshot.input_revision, "stale assessment review")
            _require(set(assessment.input_assessment_keys) <= set(record.input_assessment_keys) <= seen,
                     "assessment relies on unsupplied or future inputs")
            _require(set(assessment.evidence_reviewed) <= set(record.evidence_ids) <= snapshot.evidence_manifest.keys(),
                     "assessment cites evidence outside its frozen packet")
            _require(not assessment.uncertainties, "assessment uncertainty remains", evidence=True)
            seen.add(record.key)
        for role in ROLE_CONTRACTS:
            _require(sum(record.role == role for record in result.delegations) <= result.bounds.max_role_invocations,
                     "role invocation bound violated")
        latest = latest_assessments(advice)
        for role, field in (("diagnostic", "candidate_diagnosis_key"), ("engineering", "engineering_key"),
                            ("operations", "operations_key"), ("planner", "maintenance_plan_key")):
            _require(getattr(result, field) == latest.get(role), "selected assessment is not canonical")
            _require(getattr(result.decision, field) == getattr(result, field), "decision differs from canonical result")
            if role == "diagnostic" and latest.get(role):
                _require(not advice[latest[role]].assessment.missing_evidence_requests,
                         "current diagnosis has unresolved evidence need", evidence=True)
        critics = tuple(key for key, item in advice.items() if isinstance(item.assessment, CriticAssessment))
        _require(set(result.critic_keys) == set(critics) and set(result.decision.critic_keys) <= set(critics),
                 "critic selection mismatch")
        decision = result.decision
        _require((decision.incident_id, decision.run_id) == (snapshot.incident_id, snapshot.run_id), "wrong decision run")
        _require(decision.disposition == "ADVISORY_CONCLUSION" and not decision.blockers
                 and not decision.unresolved_evidence_needs, "decision has unresolved evidence or blockers")
        _require(set((*result.evidence_used, *decision.evidence_used)) <= snapshot.evidence_manifest.keys(),
                 "run cites unsupplied evidence")
        return result, advice

    def _fresh(self, conn, incident, report_id, stage):
        report = self._get(conn, incident.id, report_id, m.SupervisorReport)
        snapshot = self._get(conn, incident.id, report.snapshot_id, m.SupervisorRunSnapshot)
        _require(snapshot.stage == stage and report.asset_id == snapshot.asset_id
                 and snapshot.asset_id in incident.equipment_ids and report.run_id == snapshot.run_id,
                 "report does not belong to run/stage/asset")
        _require(incident.active_run_id == snapshot.run_id, "active-run mismatch")
        _require(not report.stale_reasons and report.input_revision == snapshot.input_revision == report.completion_revision
                 and report.checkpoint_revision == report.completion_revision + 1
                 and incident.revision == report.checkpoint_revision, "stale report revision checkpoint")
        _require(snapshot.source_dependency_manifest is not None,
                 "run snapshot predates dependency-scoped freshness; a new run is required")
        changes = revalidate(conn, snapshot.source_dependency_manifest)
        _require(not changes, "frozen source dependency changed: "
                 + ", ".join(item.dependency.describe() for item in changes), evidence=True)
        evidence = self._evidence(conn, incident, snapshot.asset_id, tuple(snapshot.evidence_manifest))
        _require(self._manifest(evidence) == snapshot.evidence_manifest == report.evidence_manifest,
                 "evidence manifest differs from actual run inputs")
        _require(self._closure(evidence) == snapshot.source_dependency_manifest,
                 "frozen dependency closure differs from the evidence packet")
        context = SpecialistContext.model_validate(snapshot.context_payload)
        _require((context.incident_id, context.asset_id, context.run_id, context.input_revision, context.run_purpose) == (
            incident.id, snapshot.asset_id, snapshot.run_id, snapshot.input_revision, snapshot.stage), "snapshot context mismatch")
        _require(self._manifest({item.id: item for item in context.evidence}) == snapshot.evidence_manifest,
                 "snapshot evidence content mismatch")
        _require({item.id: _hash(item) for item in context.artifacts} == snapshot.input_artifact_manifest,
                 "snapshot artifact manifest mismatch")
        for key, digest in snapshot.input_artifact_manifest.items():
            artifact = self.repository._artifact(conn, incident.id, key)
            _require(_hash(artifact) == digest, "source artifact hash mismatch")
            self._current(conn, incident.id, artifact)
        requests = self._all(conn, incident.id, m.EvidenceRequest)
        superseded = {item.supersedes_id for item in requests}
        current_requests = [item for item in requests if item.id not in superseded]
        _require(not any(item.status == "OPEN" for item in current_requests),
                 "unresolved durable evidence request", evidence=True)
        # Step 13B correction: a request resolved only by SUSPECT/MISSING evidence
        # (UNAVAILABLE capability, partial baseline context) can never be part of a
        # packet under the GOOD-quality rule above, so it does not block. Resolved
        # GOOD evidence, including stale GOOD evidence, must still be in the packet.
        def grounded(item):
            resolved = [self._get(conn, incident.id, key, m.Evidence) for key in item.resolved_by_evidence_ids]
            return bool(resolved) and (set(item.resolved_by_evidence_ids) <= evidence.keys()
                                       or all(record.quality != "GOOD" for record in resolved))
        _require(all(grounded(item) for item in current_requests),
                 "resolved evidence request is not grounded in the reviewed evidence packet", evidence=True)
        result, advice = self._audit_result(snapshot, report)
        return snapshot, report, result, advice, evidence

    def _critic_review(self, advice, *, subject_id, subject_kind, inputs=(), draft=None):
        reviews = [item.assessment for item in advice.values() if isinstance(item.assessment, CriticAssessment)
                   and ((item.assessment.subject_id == subject_id and item.assessment.subject_kind == subject_kind)
                        or set(item.assessment.input_assessment_keys) & set(inputs))]
        _require(reviews and any(item.subject_id == subject_id and item.subject_kind == subject_kind
                                and set(inputs) <= set(item.input_assessment_keys) for item in reviews),
                 "explicit critic review of exact current inputs required")
        for review in reviews:
            _require(review.recommendation == "ACCEPT" and not (review.evidence_gaps or review.contradictions
                     or review.unsupported_claims or review.requested_additional_evidence or review.uncertainties),
                     "outstanding critic rejection or evidence need", evidence=True)
        if draft:
            _require(any(item.subject_id == draft.id and set(inputs) <= set(item.input_assessment_keys)
                         and (item.reviewed_intervention_id, item.reviewed_intervention_hash) == (draft.id, _hash(draft))
                         for item in reviews), "critic did not review exact draft")
        return tuple(item.reasoning_summary for item in reviews)

    def _retry(self, conn, incident_id, run_id, stage, request):
        for promotion in self._all(conn, incident_id, m.PromotionRecord):
            if promotion.run_id == run_id and promotion.stage == stage:
                if promotion.request_hash != content_hash(request):
                    raise PromotionConflict("same promotion identity with a different payload/hash")
                # No pointer writes: an old successful retry cannot reactivate authority.
                return promotion
        return None

    def _verdict(self, incident, target, stage, input_revision, run_id, challenges, checks):
        return m.ValidationVerdict(
            **_identity(incident.id), target_kind=stage, target_id=target.id, target_hash=_hash(target),
            input_revision=input_revision, decision="ACCEPT", challenges=challenges,
            evidence_ids=target.evidence_ids, validator_run_id=run_id, validator_identity=VALIDATOR,
            validation_policy_version=POLICY_VERSION, check_results={check: True for check in checks})

    def _record(self, incident, snapshot, report, target, verdict, stage, request, mapping, evidence, **extra):
        return m.PromotionRecord(
            **_identity(incident.id), run_id=snapshot.run_id, stage=stage, source_report_id=report.id,
            source_report_hash=_hash(report), validation_policy_version=POLICY_VERSION,
            input_revision=snapshot.input_revision, output_revision=incident.revision + 1,
            target_id=target.id, target_hash=_hash(target), verdict_id=verdict.id,
            advisory_artifact_mapping=mapping, evidence_manifest=self._manifest(evidence),
            idempotency_key=content_hash({"incident": incident.id, "run": snapshot.run_id, "stage": stage}),
            request_hash=content_hash(request), **extra)

    def promote_diagnosis(self, incident_id: str, *, report_id: str, confirmation_id: str, expected_revision: int):
        with self.repository._write() as conn:
            report = self._get(conn, incident_id, report_id, m.SupervisorReport)
            request = {"report_id": report_id, "report_hash": _hash(report), "confirmation_id": confirmation_id}
            retry = self._retry(conn, incident_id, report.run_id, "diagnosis", request)
            if retry:
                return retry
            incident = self.repository._fetch(conn, incident_id)
            self.repository._check(incident, expected_revision)
            _require(incident.phase == m.IncidentPhase.INVESTIGATING, "diagnosis promotion requires INVESTIGATING")
            snapshot, report, result, advice, evidence = self._fresh(conn, incident, report_id, "DIAGNOSIS")
            _require(result.candidate_diagnosis_key in advice, "selected diagnostic is missing")
            diagnostic = advice[result.candidate_diagnosis_key].assessment
            _require(isinstance(diagnostic, DiagnosticAssessment) and diagnostic.recommended_hypothesis
                     and not diagnostic.missing_evidence_requests, "diagnosis needs evidence", evidence=True)
            selected = next(item for item in diagnostic.competing_hypotheses if item.key == diagnostic.recommended_hypothesis)
            _require(selected.supporting_evidence_ids and not selected.contradicting_evidence_ids,
                     "selected hypothesis lacks uncontradicted grounded support", evidence=True)
            _require(confirmation_id in evidence, "trusted confirmation was not supplied to this run", evidence=True)
            confirmation_evidence = evidence[confirmation_id]
            _require(confirmation_evidence.kind == "inspection" and confirmation_evidence.source_capability == CONFIRM_MECHANISM
                     and confirmation_evidence.source_system == VALIDATOR, "trusted technical confirmation required", evidence=True)
            confirmation = m.TrustedTechnicalConfirmation.model_validate(confirmation_evidence.payload)
            _require((confirmation.incident_id, confirmation.asset_id, confirmation.confirmed_mechanism) == (
                incident.id, snapshot.asset_id, selected.mechanism), "confirmation scope or exact mechanism mismatch", evidence=True)
            _require(confirmation_evidence.derived_from_ids == confirmation.supporting_evidence_ids
                     or set(confirmation.supporting_evidence_ids) <= set(confirmation_evidence.derived_from_ids),
                     "confirmation support differs from durable provenance")
            _require(confirmation.provenance == confirmation_evidence.provenance
                     and confirmation.observed_at == confirmation_evidence.observed_at,
                     "confirmation provenance mismatch")
            _require(set(selected.supporting_evidence_ids) & {confirmation_id, *confirmation.supporting_evidence_ids},
                     "hypothesis support does not include confirmed technical evidence", evidence=True)
            _require(any(evidence[key].kind in {"telemetry", "maintenance_history", "inspection"}
                         for key in selected.supporting_evidence_ids), "model/classifier evidence cannot confirm a mechanism", evidence=True)
            challenges = self._critic_review(advice, subject_id=result.candidate_diagnosis_key,
                                             subject_kind="assessment", inputs=(result.candidate_diagnosis_key,))
            hypotheses, mapping = [], {}
            for suggestion in diagnostic.competing_hypotheses:
                accepted = suggestion.key == selected.key
                hypothesis = m.Hypothesis(
                    **_identity(incident.id), equipment_ids=(snapshot.asset_id,), mechanism=suggestion.mechanism,
                    failure_mode_code=confirmation.failure_mode_code if accepted else None,
                    status="SUPPORTED" if accepted else "UNRESOLVED",
                    supporting_evidence_ids=suggestion.supporting_evidence_ids,
                    contradicting_evidence_ids=suggestion.contradicting_evidence_ids, confidence=None,
                    confidence_basis=("Categorical trusted confirmation; no numerical causal confidence assigned." if accepted else
                                      "Unvalidated competing advisory suggestion; no numerical causal confidence assigned."),
                    falsification_tests=suggestion.falsification_tests)
                hypotheses.append(hypothesis)
                mapping[f"{result.candidate_diagnosis_key}/{suggestion.key}"] = hypothesis.id
            selected_id = mapping[f"{result.candidate_diagnosis_key}/{selected.key}"]
            diagnosis = m.Diagnosis(
                **_identity(incident.id), equipment_ids=(snapshot.asset_id,),
                hypothesis_ids=(selected_id, *(item.id for item in hypotheses if item.id != selected_id)),
                alternative_hypothesis_ids=tuple(item.id for item in hypotheses if item.id != selected_id),
                conclusion=selected.mechanism, failure_mode_code=confirmation.failure_mode_code,
                evidence_ids=tuple(sorted(evidence)), confidence=None, status="ACCEPTED",
                supersedes_id=incident.current_diagnosis_id)
            mapping[result.candidate_diagnosis_key] = diagnosis.id
            verdict = self._verdict(incident, diagnosis, "diagnosis", snapshot.input_revision, snapshot.run_id, challenges,
                                    ("freshness", "evidence_closure", "canonical_diagnostic", "critic_review", "trusted_mechanism_match"))
            promotion = self._record(incident, snapshot, report, diagnosis, verdict, "diagnosis", request, mapping, evidence)
            self._checkpoint(conn, incident, [*hypotheses, diagnosis, verdict, promotion],
                             phase=m.IncidentPhase.DIAGNOSIS_VALIDATED, current_diagnosis_id=diagnosis.id,
                             current_intervention_id=None, active_run_id=None)
            return promotion

    def _lineage(self, conn, incident, target_id, stage, *, current):
        _require(target_id, "promoted authority is absent")
        promotions = [item for item in self._all(conn, incident.id, m.PromotionRecord)
                      if item.target_id == target_id and item.stage == stage]
        _require(len(promotions) == 1, "artifact lacks application promotion lineage")
        record = promotions[0]
        target = self._get(conn, incident.id, target_id, m.Diagnosis if stage == "diagnosis" else m.Intervention)
        verdict = self._get(conn, incident.id, record.verdict_id, m.ValidationVerdict)
        report = self._get(conn, incident.id, record.source_report_id, m.SupervisorReport)
        snapshot = self._get(conn, incident.id, report.snapshot_id, m.SupervisorRunSnapshot)
        _require(record.target_hash == _hash(target) == verdict.target_hash and verdict.target_id == target.id
                 and verdict.target_kind == stage and verdict.decision == "ACCEPT" and not verdict.blocking_issues
                 and verdict.validator_identity == VALIDATOR
                 and record.validation_policy_version == verdict.validation_policy_version == POLICY_VERSION
                 and verdict.validator_run_id == record.run_id == report.run_id == snapshot.run_id
                 and record.source_report_hash == _hash(report) and verdict.input_revision == record.input_revision == snapshot.input_revision,
                 "invalid application promotion lineage")
        _require(target.status == ("ACCEPTED" if stage == "diagnosis" else "VALIDATED")
                 and not report.stale_reasons and report.input_revision == report.completion_revision
                 and record.output_revision == report.checkpoint_revision + 1
                 and set(record.evidence_manifest) == set(target.evidence_ids) == set(verdict.evidence_ids)
                 and verdict.check_results and all(verdict.check_results.values()),
                 "promotion checkpoint or validated target mismatch")
        _require(not any(item.target_id == target.id and item.target_hash == _hash(target)
                         and (item.decision != "ACCEPT" or item.blocking_issues)
                         for item in self._all(conn, incident.id, m.ValidationVerdict)),
                 "authoritative target has an outstanding application rejection")
        if stage == "intervention":
            draft = self._get(conn, incident.id, record.reviewed_draft_id, m.Intervention)
            _require(record.reviewed_content_hash == executable_content_hash(target) == executable_content_hash(draft)
                     and snapshot.input_artifact_manifest.get(draft.id) == _hash(draft),
                     "intervention exact review lineage mismatch")
        if current:
            _require(getattr(incident, f"current_{stage}_id") == target_id, "artifact is not current promoted authority")
            self._current(conn, incident.id, target)
            if stage == "diagnosis":
                newer = conn.execute(
                    "SELECT body_json FROM incident_artifact WHERE incident_id=? AND kind='Evidence' AND rowid > "
                    "(SELECT rowid FROM incident_artifact WHERE artifact_id=?)", (incident.id, record.id)).fetchall()
                _require(not any(m.Evidence.model_validate_json(row[0]).kind in {
                    "telemetry", "model_signal", "maintenance_history", "inspection", "document", "operational_context"}
                    for row in newer), "new technical evidence requires diagnosis revalidation", evidence=True)
            if stage == "intervention":
                diagnosis, lineage = self._lineage(conn, incident, target.diagnosis_id, "diagnosis", current=True)
                _require(record.source_diagnosis_promotion_id == lineage.id, "intervention diagnosis lineage mismatch")
        return target, record

    def promotion_lineage(self, incident_id: str, target_id: str, stage: str, *, require_current=True):
        _require(stage in {"diagnosis", "intervention"}, "invalid lineage stage")
        with db.get_conn(self.repository.path) as conn:
            conn.execute("BEGIN")
            incident = self.repository._fetch(conn, incident_id)
            return self._lineage(conn, incident, target_id, stage, current=require_current)[1]

    def _binding(self, conn, incident, binding):
        diagnosis, lineage = self._lineage(conn, incident, binding.diagnosis_id, "diagnosis", current=True)
        _require(binding.asset_id in diagnosis.equipment_ids, "binding equipment differs from diagnosis")
        _require(binding.safety_relevant and binding.external_commitment and not binding.reversible,
                 "work package risk metadata conflicts with governed capability policy")
        report = self._get(conn, incident.id, binding.source_report_id, m.SupervisorReport)
        snapshot = self._get(conn, incident.id, report.snapshot_id, m.SupervisorRunSnapshot)
        _require(snapshot.asset_id == binding.asset_id, "source plan asset mismatch")
        _require(not report.stale_reasons and report.input_revision == snapshot.input_revision == report.completion_revision,
                 "source plan was produced by a stale run")
        result, advice = self._audit_result(snapshot, report)
        _require(result.maintenance_plan_key == binding.source_plan_key and binding.source_plan_key in advice,
                 "binding requires canonical durable source plan")
        plan = advice[binding.source_plan_key].assessment
        _require(isinstance(plan, MaintenancePlanAssessment), "binding requires planner advice")
        from .orchestration import assessment_dependencies
        dependencies = assessment_dependencies(plan.input_assessment_keys, advice)
        _require(diagnosis.id in plan.validated_input_ids or (
            lineage.source_report_id == report.id and any(lineage.advisory_artifact_mapping.get(key) == diagnosis.id for key in dependencies)),
            "source plan lacks current diagnosis lineage")
        _require(not plan.unresolved_blockers and all(value is not None for value in (
            plan.estimated_exposure, plan.reversible, plan.safety_relevant, plan.external_commitment)),
            "source plan has unknown risk/exposure or blockers")
        _require(all(set(step.equipment_ids) == {binding.asset_id} for step in plan.proposed_steps), "plan equipment mismatch")
        evidence_ids = set(binding.evidence_ids) | set(diagnosis.evidence_ids) | set(plan.evidence_reviewed)
        evidence_ids.update((binding.resource_confirmation_id, binding.signal_evidence_id))
        evidence = self._evidence(conn, incident, binding.asset_id, evidence_ids)
        resource = evidence[binding.resource_confirmation_id]
        _require(resource.kind == "resource_availability" and resource.source_capability == CONFIRM_RESOURCES
                 and resource.source_system == VALIDATOR, "durable dated resource confirmation required", evidence=True)
        confirmation = m.ResourceConfirmation.model_validate(resource.payload)
        _require((confirmation.incident_id, confirmation.asset_id, confirmation.technician_id,
                  confirmation.window_start, confirmation.window_end, confirmation.parts) == (
                      incident.id, binding.asset_id, binding.technician_id, binding.window_start, binding.window_end, binding.parts),
                 "resource confirmation does not match exact binding")
        _require(confirmation.observed_at == resource.observed_at and confirmation.provenance == resource.provenance,
                 "resource provenance mismatch")
        _require(utcnow() < binding.window_start, "confirmed maintenance window has expired", evidence=True)
        asset, parts = self._resource_rows(conn, binding.asset_id, binding.technician_id, binding.parts)
        _require(confirmation.qualification == asset["equipment_class"], "technician qualification mismatch")
        _require(confirmation.inventory_snapshot == self._inventory_snapshot(binding.parts, parts),
                 "durable inventory snapshot differs from actual stock", evidence=True)
        mode = conn.execute("SELECT * FROM failure_mode WHERE failure_mode_id=?", (binding.failure_mode_id,)).fetchone()
        _require(mode and diagnosis.failure_mode_code and mode["mode_code"] == diagnosis.failure_mode_code,
                 "adapter requires validated exact failure-mode identity")
        signal_evidence = evidence[binding.signal_evidence_id]
        _require(signal_evidence.kind == "model_signal", "adapter classifier context requires a durable signal")
        signal = m.ModelSignal.model_validate(signal_evidence.payload)
        _require(signal.equipment_id == binding.asset_id, "signal equipment mismatch")
        parameters = WorkPackageParameters(
            equipment_id=binding.asset_id, failure_mode_id=binding.failure_mode_id,
            technician_id=binding.technician_id, priority="HIGH", detail="\n".join(binding.work_instructions),
            parts=tuple(dict(part_id=part.part_id, part_number=parts[part.part_id]["part_number"], qty=part.quantity,
                             is_critical_spare=bool(parts[part.part_id]["is_critical_spare"])) for part in binding.parts),
            window=f"{binding.window_start.isoformat()}/{binding.window_end.isoformat()}",
            window_min=binding.duration_minutes, prediction_failure_prob=signal.risk_score)
        return diagnosis, lineage, plan, parameters, evidence

    def create_draft(self, incident_id: str, *, expected_revision: int, **binding_fields):
        """Bind trusted structured fields. IDs are assigned here, not by the planner."""
        binding = m.WorkPackageBinding(**_identity(incident_id), **binding_fields)
        with self.repository._write() as conn:
            incident = self.repository._fetch(conn, incident_id)
            self.repository._check(incident, expected_revision)
            _require(incident.phase in {m.IncidentPhase.DIAGNOSIS_VALIDATED, m.IncidentPhase.PLANNING},
                     "draft construction requires current accepted diagnosis and planning")
            diagnosis, _, _, parameters, evidence = self._binding(conn, incident, binding)
            previous = self._all(conn, incident_id, m.Intervention)
            draft = m.Intervention(
                **_identity(incident_id), diagnosis_id=diagnosis.id, revision=max((item.revision for item in previous), default=0) + 1,
                steps=(m.InterventionStep(
                    id=new_id(), created_at=utcnow(), capability="create_work_package", equipment_ids=(binding.asset_id,),
                    parameters=parameters.model_dump(mode="json"), preconditions=binding.technical_preconditions,
                    verification_criteria=binding.verification_criteria),), evidence_ids=tuple(sorted(evidence)),
                risk="HIGH", window_start=binding.window_start, window_end=binding.window_end,
                estimated_cost=binding.estimated_cost, estimated_downtime_minutes=binding.estimated_downtime_minutes,
                estimated_avoided_loss=binding.estimated_avoided_loss, business_assumption_version=binding.business_assumption_version,
                status="DRAFT", binding_id=binding.id,
                risk_metadata=self._risk_metadata(binding),
                supersedes_id=previous[-1].id if previous and previous[-1].status == "DRAFT" else None)
            self._checkpoint(conn, incident, [binding, draft], phase=m.IncidentPhase.PLANNING, active_run_id=None)
            return draft

    @staticmethod
    def _risk_metadata(binding):
        return {"safety_review": binding.safety_review, "safety_relevant": binding.safety_relevant,
                "reversible": binding.reversible, "external_commitment": binding.external_commitment,
                "policy": POLICY_VERSION}

    def promote_intervention(self, incident_id: str, *, report_id: str, draft_id: str, expected_revision: int):
        with self.repository._write() as conn:
            report = self._get(conn, incident_id, report_id, m.SupervisorReport)
            draft = self._get(conn, incident_id, draft_id, m.Intervention)
            request = {"report_id": report_id, "report_hash": _hash(report), "draft_id": draft_id, "draft_hash": _hash(draft)}
            retry = self._retry(conn, incident_id, report.run_id, "intervention", request)
            if retry:
                return retry
            incident = self.repository._fetch(conn, incident_id)
            self.repository._check(incident, expected_revision)
            _require(incident.phase == m.IncidentPhase.PLANNING, "intervention promotion requires PLANNING")
            snapshot, report, result, advice, evidence = self._fresh(conn, incident, report_id, "INTERVENTION_REVIEW")
            _require(draft.status == "DRAFT" and draft.binding_id
                     and snapshot.input_artifact_manifest.get(draft.id) == _hash(draft), "exact bound draft review required")
            binding = self._get(conn, incident_id, draft.binding_id, m.WorkPackageBinding)
            diagnosis, lineage, plan, parameters, closure = self._binding(conn, incident, binding)
            _require(draft.diagnosis_id == diagnosis.id and set(draft.evidence_ids) == set(evidence) == set(closure),
                     "draft diagnosis or evidence closure changed")
            _require(len(draft.steps) == 1 and draft.steps[0].capability == "create_work_package"
                     and draft.steps[0].equipment_ids == (snapshot.asset_id,) and not draft.steps[0].depends_on,
                     "unsupported or deferred executable capability")
            _require(WorkPackageParameters.model_validate(draft.steps[0].parameters) == parameters,
                     "executable parameters differ from reviewed binding")
            _require(draft.steps[0].preconditions == binding.technical_preconditions
                     and draft.risk_metadata == self._risk_metadata(binding)
                     and draft.steps[0].verification_criteria == binding.verification_criteria
                     and (draft.estimated_cost, draft.estimated_downtime_minutes, draft.estimated_avoided_loss,
                          draft.business_assumption_version, draft.window_start, draft.window_end, draft.risk) == (
                              binding.estimated_cost, binding.estimated_downtime_minutes, binding.estimated_avoided_loss,
                              binding.business_assumption_version, binding.window_start, binding.window_end, "HIGH"),
                     "draft substantive content differs from application binding")
            eng = advice.get(result.engineering_key)
            ops = advice.get(result.operations_key)
            _require(eng and isinstance(eng.assessment, EngineeringAssessment)
                     and ops and isinstance(ops.assessment, OperationsAssessment), "current engineering and operations required")
            eng, ops = eng.assessment, ops.assessment
            for assessment in (eng, ops):
                _require((assessment.reviewed_intervention_id, assessment.reviewed_intervention_hash) == (draft.id, _hash(draft)),
                         "assessment did not review exact draft")
            _require(eng.diagnosis_id == diagnosis.id and eng.intervention_feasibility == "FEASIBLE"
                     and eng.constraints_considered and not (eng.missing_constraints or eng.blockers or eng.safety_concerns),
                     "engineering constraints, blockers or safety unresolved", evidence=True)
            _require(ops.intervention_id == draft.id and ops.resource_feasibility == "FEASIBLE" and not ops.blockers
                     and ops.inventory_observations and ops.workforce_observations and ops.scheduling_observations
                     and binding.resource_confirmation_id in ops.evidence_reviewed,
                     "operations lacks feasible durable resource review", evidence=True)
            _require(result.engineering_key in ops.input_assessment_keys, "operations uses stale engineering assessment")
            challenges = self._critic_review(advice, subject_id=draft.id, subject_kind="intervention",
                                             inputs=(result.engineering_key, result.operations_key), draft=draft)
            previous = self._all(conn, incident_id, m.Intervention)
            target = m.Intervention.model_validate(draft.model_dump() | {
                "id": new_id(), "created_at": utcnow(), "status": "VALIDATED",
                "revision": max(item.revision for item in previous) + 1,
                "supersedes_id": incident.current_intervention_id or draft.id})
            _require(executable_content_hash(target) == executable_content_hash(draft), "reviewed content changed")
            verdict = self._verdict(incident, target, "intervention", snapshot.input_revision, snapshot.run_id, challenges,
                                    ("freshness", "diagnosis_lineage", "exact_draft", "engineering", "dated_resources",
                                     "critic_review", "executable_parameters", "explicit_business_assumptions"))
            mapping = {result.engineering_key: target.id, result.operations_key: target.id,
                       f"{binding.source_report_id}/{binding.source_plan_key}": draft.id}
            promotion = self._record(incident, snapshot, report, target, verdict, "intervention", request, mapping, evidence,
                                     source_diagnosis_promotion_id=lineage.id, reviewed_draft_id=draft.id,
                                     reviewed_content_hash=executable_content_hash(draft))
            self._checkpoint(conn, incident, [target, verdict, promotion], phase=m.IncidentPhase.INTERVENTION_VALIDATED,
                             current_intervention_id=target.id, active_run_id=None)
            return promotion
