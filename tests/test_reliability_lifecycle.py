"""Step 13B lifecycle integration: real repository transactions and real promotion lineage.

Nothing here mocks authority checks. Every incident reaches INTERVENTION_VALIDATED
through PromotionService, and every approval/execution command runs the actual
atomic lifecycle transactions against an isolated SQLite store.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading

import pytest

from core import db, services
from core.reliability import lifecycle as lc
from core.reliability import models as m
from core.reliability.execution import (
    _AUTHORITY_SEAL, TRUSTED_EXECUTOR, ExecutionAmbiguous, ExecutionAuthorization, ExecutionBusy, ExecutionFailed,
    GovernedExecutor,
)
from core.reliability.governance import WorkPackageParameters
from core.reliability.governance import ApprovalLedger, artifact_hash
from core.reliability.legacy import prepare_legacy_intervention
from core.reliability.lifecycle import (
    ApprovalRefused, AuthorityRefused, ExecutionRefused, GovernanceBlocked, LifecycleService, ReconciliationRequired,
)
from core.reliability.repository import IncidentRepository, StaleRevision, new_id, utcnow
from core.reliability.state import InvalidTransition
from tests.conftest import sample_proposal
from tests.test_promotion import ASSET, Environment, result_payload, revision, state

APPROVER = dict(actor_id="approver-1", actor_role="maintenance_approver", rationale="reviewed exact promoted work package")


class Flow(Environment):
    """Promotion environment plus lifecycle commands."""

    def __init__(self):
        super().__init__()
        self.lifecycle = LifecycleService(self.repo)

    def incident(self):
        return self.repo.fetch_incident(self.incident_id)

    def validated(self):
        draft = self.draft()
        report = self.complete(self.start(draft), draft=draft)
        promotion = self.promote_intervention(report, draft)
        return self.repo.get_artifact(self.incident_id, promotion.target_id), promotion

    def awaiting(self):
        intervention, promotion = self.validated()
        requirement = self.lifecycle.request_approval(self.incident_id, expected_revision=revision(self))
        return intervention, promotion, requirement

    def command(self, requirement, intervention=None, **changes):
        intervention = intervention or self.repo.get_artifact(self.incident_id, requirement.intervention_id)
        fields = dict(requirement_id=requirement.id, intervention_id=intervention.id,
                      intervention_hash=artifact_hash(intervention), context_revision=revision(self),
                      decision="APPROVE", **APPROVER)
        return fields | changes

    def ready(self):
        intervention, promotion, requirement = self.awaiting()
        decision = self.lifecycle.decide_approval(self.incident_id, **self.command(requirement, intervention))
        return intervention, promotion, requirement, decision

    def kinds(self, cls):
        return [a for a in self.repo.list_artifacts(self.incident_id) if isinstance(a, cls)]


@pytest.fixture
def flow(seeded_db):
    return Flow()


class RecordingCmms:
    failure_is_definitive = True

    def __init__(self, outcome="confirm", hook=None):
        self.outcome, self.hook, self.calls = outcome, hook, 0
        self.delegate = services.cmms()

    def create_work_package(self, proposal, *, authorization):
        self.calls += 1
        if self.hook:
            self.hook()
        if self.outcome == "fail":
            raise RuntimeError("CMMS rejected the package")
        if self.outcome == "unknown":
            self.failure_is_definitive = False
            raise TimeoutError("response lost after CMMS commit")
        return self.delegate.create_work_package(proposal, authorization=authorization)


def use_cmms(monkeypatch, adapter):
    monkeypatch.setattr(services, "cmms", lambda: adapter)
    return adapter


def counts(repo):
    with db.get_conn(repo.path) as conn:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("work_order", "work_package", "part_reservation", "labor_booking", "execution_claim",
                              "execution_receipt", "approval_decision")}


# ------------------------------------------------------------------ happy path

def test_full_lifecycle_reaches_observing_never_closed(flow):
    intervention, promotion, requirement, decision = flow.ready()
    incident = flow.incident()
    assert incident.phase == m.IncidentPhase.READY
    before = counts(flow.repo)
    report = flow.lifecycle.execute(flow.incident_id, intervention.id, intervention_hash=artifact_hash(intervention))
    incident = flow.incident()
    assert report.phase == incident.phase == m.IncidentPhase.OBSERVING
    assert incident.current_intervention_id == intervention.id
    receipt = flow.repo.get_execution_receipt(flow.incident_id, report.receipt_ids[0])
    assert receipt.status == "CONFIRMED" and receipt.intervention_hash == artifact_hash(intervention)
    assert receipt.external_ids["wo_number"] and receipt.external_ids["package_number"]
    after = counts(flow.repo)
    assert after["work_order"] == before["work_order"] + 1 and after["work_package"] == before["work_package"] + 1
    assert after["execution_receipt"] == 1 and after["execution_claim"] == 1
    # Execution SUCCESS is a confirmed commanded action, not a verified recovery.
    assert not flow.kinds(m.Outcome)
    assert incident.phase != m.IncidentPhase.CLOSED
    events = [e.event_type for e in flow.repo.list_events(flow.incident_id)]
    assert events.count("APPROVAL_REQUESTED") == 1 and events.count("APPROVAL_RECORDED") == 1
    assert events.count("EXECUTION_CLAIMED") == 1 and events.count("EXECUTION_RECORDED") == 1
    phases = [e.payload["to"] for e in flow.repo.list_events(flow.incident_id) if e.event_type == "PHASE_CHANGED"]
    assert phases[-4:] == ["AWAITING_APPROVAL", "READY", "EXECUTING", "OBSERVING"]
    assert flow.lifecycle.status(flow.incident_id).claim_state == "CONFIRMED"
    # Approval never validated anything: the only verdicts are the application promotion verdicts.
    assert all(v.validator_identity == "operon.application.promotion" for v in flow.kinds(m.ValidationVerdict))
    assert decision.promotion_id == promotion.id == requirement.promotion_id


def test_requirement_and_decision_transitions_are_single_atomic_revisions(flow):
    intervention, promotion = flow.validated()
    checkpoint = revision(flow)
    requirement = flow.lifecycle.request_approval(flow.incident_id, expected_revision=checkpoint)
    incident = flow.incident()
    assert incident.revision == checkpoint + 1 and incident.phase == m.IncidentPhase.AWAITING_APPROVAL
    assert requirement.intervention_hash == artifact_hash(intervention) and requirement.promotion_id == promotion.id
    assert requirement.policy_version == lc.POLICY_VERSION and requirement.mode == "HUMAN"
    assert requirement.expires_at <= intervention.window_start
    flow.lifecycle.decide_approval(flow.incident_id, **flow.command(requirement, intervention))
    incident = flow.incident()
    assert incident.revision == checkpoint + 2 and incident.phase == m.IncidentPhase.READY


@pytest.mark.parametrize("command,write_index", [("request", n) for n in range(1, 5)] + [("decide", n) for n in range(1, 4)]
                         + [("claim", n) for n in range(1, 4)] + [("receipt", n) for n in range(1, 4)])
def test_every_lifecycle_write_rolls_back_atomically(flow, monkeypatch, command, write_index):
    if command == "request":
        intervention, _ = flow.validated()
        run = lambda: flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow))
    elif command == "decide":
        intervention, _, requirement = flow.awaiting()
        run = lambda: flow.lifecycle.decide_approval(flow.incident_id, **flow.command(requirement, intervention))
    elif command == "claim":
        intervention, *_ = flow.ready()
        run = lambda: flow.lifecycle._claim(flow.incident_id, intervention.id, None, services.cmms())
    else:
        intervention, *_ = flow.ready()
        claimed = flow.lifecycle._claim(flow.incident_id, intervention.id, None, services.cmms())
        receipt = flow.lifecycle._receipt(claimed, status="CONFIRMED", external_ids={"wo_number": "WO-TEST"})
        run = lambda: flow.lifecycle.record_receipt(receipt)
    before = state(flow), counts(flow.repo)
    count = 0

    def failing(method):
        def wrapped(*args, **kwargs):
            nonlocal count
            result = method(*args, **kwargs)
            count += 1
            if count == write_index:
                raise RuntimeError("injected after durable internal write")
            return result
        return wrapped
    for name in ("_store_artifact", "_update", "_event"):
        monkeypatch.setattr(flow.repo, name, failing(getattr(flow.repo, name)))
    with pytest.raises(RuntimeError, match="injected"):
        run()
    assert count == write_index and (state(flow), counts(flow.repo)) == before


# ---------------------------------------------------------- authority boundary

def test_generic_legacy_artifacts_cannot_satisfy_lifecycle_authority(flow):
    flow.resources()
    with pytest.warns(DeprecationWarning):
        legacy = prepare_legacy_intervention(flow.repo, flow.incident_id, sample_proposal())
    incident = flow.incident()
    assert incident.phase == m.IncidentPhase.AWAITING_APPROVAL and incident.current_intervention_id is None
    with pytest.raises(AuthorityRefused):
        flow.lifecycle.request_approval(flow.incident_id, expected_revision=incident.revision)
    with pytest.raises(ExecutionRefused):
        flow.lifecycle.execute(flow.incident_id, legacy.intervention.id)
    with pytest.raises(ApprovalRefused):
        flow.lifecycle.decide_approval(flow.incident_id, requirement_id=legacy.requirement.id,
                                       intervention_id=legacy.intervention.id,
                                       intervention_hash=artifact_hash(legacy.intervention),
                                       context_revision=incident.revision, decision="APPROVE", **APPROVER)
    assert not flow.repo.list_execution_receipts(flow.incident_id)


def test_phase_alone_grants_no_authority(flow):
    """Legal graph transitions without promotion cannot reach approval or execution."""
    incident = flow.incident()
    for phase in ("DIAGNOSIS_VALIDATED", "PLANNING", "INTERVENTION_VALIDATED"):
        incident = flow.repo.transition(incident.id, m.IncidentPhase(phase), expected_revision=incident.revision,
                                        reason="test graph-only transition")
    with pytest.raises(AuthorityRefused, match="no current promoted intervention"):
        flow.lifecycle.request_approval(flow.incident_id, expected_revision=incident.revision)
    incident = flow.repo.transition(incident.id, m.IncidentPhase.AWAITING_APPROVAL, expected_revision=incident.revision, reason="t")
    incident = flow.repo.transition(incident.id, m.IncidentPhase.READY, expected_revision=incident.revision, reason="t")
    with pytest.raises(AuthorityRefused):
        flow.lifecycle.execute(flow.incident_id, "missing")
    assert flow.incident().phase == m.IncidentPhase.READY and not flow.repo.list_execution_receipts(flow.incident_id)


def test_legacy_ledger_and_executor_refuse_promoted_interventions(flow):
    intervention, promotion, requirement, decision = flow.ready()
    with pytest.raises(PermissionError, match="LifecycleService"):
        ApprovalLedger(flow.repo).request(flow.incident_id, intervention.id)
    with pytest.raises(PermissionError):
        ApprovalLedger(flow.repo).decide(flow.incident_id, requirement.id, actor_id="x", actor_role="maintenance_approver",
                                         decision="APPROVE", rationale="legacy path")
    # The legacy executor delegates promoted targets to the lifecycle boundary.
    report = GovernedExecutor(flow.repo).execute(flow.incident_id, intervention.id)
    assert report.phase == m.IncidentPhase.OBSERVING and len(report.receipt_ids) == 1


def test_old_promotion_retry_cannot_restore_authority(flow):
    draft = flow.draft()
    first_report = flow.complete(flow.start(draft), draft=draft)
    first = flow.promote_intervention(first_report, draft)
    old = flow.repo.get_artifact(flow.incident_id, first.target_id)
    incident = flow.repo.transition(flow.incident_id, m.IncidentPhase.PLANNING, expected_revision=revision(flow),
                                    reason="replan")
    diagnosis_promotion = flow.service.promotion_lineage(flow.incident_id, old.diagnosis_id, "diagnosis")
    second_draft = flow.service.create_draft(flow.incident_id, expected_revision=incident.revision,
                                             **flow.binding_fields(diagnosis_promotion, flow.repo.get_artifact(flow.incident_id, diagnosis_promotion.source_report_id)))
    second = flow.promote_intervention(flow.complete(flow.start(second_draft), draft=second_draft), second_draft)
    assert flow.incident().current_intervention_id == second.target_id != old.id
    before = state(flow)
    assert flow.promote_intervention(first_report, draft, expected_revision=first_report.input_revision) == first
    assert state(flow) == before and flow.incident().current_intervention_id == second.target_id
    requirement = flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow))
    assert requirement.intervention_id == second.target_id
    flow.lifecycle.decide_approval(flow.incident_id, **flow.command(requirement))
    with pytest.raises(ExecutionRefused, match="current VALIDATED"):
        flow.lifecycle.execute(flow.incident_id, old.id)
    assert not flow.repo.list_execution_receipts(flow.incident_id)


# ----------------------------------------------------------------- governance

@pytest.mark.parametrize("stage", ["request", "decide", "execute", "retry"])
@pytest.mark.parametrize("sql", ["UPDATE technician SET available=0", "UPDATE part SET on_hand_qty=0"])
def test_governance_failure_cannot_become_ready_or_execute(flow, monkeypatch, stage, sql):
    if stage == "request":
        intervention, _ = flow.validated()
    elif stage == "decide":
        intervention, _, requirement = flow.awaiting()
    elif stage == "execute":
        intervention, *_ = flow.ready()
    else:
        use_cmms(monkeypatch, RecordingCmms("fail"))
        intervention, *_ = flow.ready()
        with pytest.raises(ExecutionFailed):
            flow.lifecycle.execute(flow.incident_id, intervention.id)
    with db.get_conn(flow.repo.path) as conn:
        conn.execute(sql)
    before = state(flow), counts(flow.repo)
    with pytest.raises(GovernanceBlocked) as blocked:
        if stage == "request":
            flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow))
        elif stage == "decide":
            flow.lifecycle.decide_approval(flow.incident_id, **flow.command(requirement, intervention))
        elif stage == "execute":
            flow.lifecycle.execute(flow.incident_id, intervention.id)
        else:
            flow.lifecycle.retry_execution(flow.incident_id, expected_revision=revision(flow))
    assert blocked.value.assessment.disposition == "BLOCKED" and not blocked.value.assessment.checks["resources_consistent"]
    # Nothing moved: no requirement, decision, claim, receipt or phase change was written.
    assert (state(flow), counts(flow.repo)) == before
    assert flow.incident().phase not in {m.IncidentPhase.EXECUTING, m.IncidentPhase.OBSERVING}


def test_governance_is_deterministic_and_never_auto_approves(flow):
    intervention, promotion = flow.validated()
    assessment = flow.lifecycle.assess_governance(flow.incident_id)
    assert assessment == flow.lifecycle.assess_governance(flow.incident_id)
    assert assessment.disposition == "REQUIRES_HUMAN_APPROVAL" and all(assessment.checks.values())
    assert assessment.intervention_hash == artifact_hash(intervention) and assessment.promotion_id == promotion.id
    with pytest.raises(ExecutionRefused, match="requires READY"):
        flow.lifecycle.execute(flow.incident_id, intervention.id)


# ------------------------------------------------------------------- approval

def test_two_concurrent_approval_requests_create_exactly_one_requirement(flow):
    intervention, _ = flow.validated()
    checkpoint = revision(flow)

    def request(_):
        try:
            return LifecycleService(IncidentRepository(flow.repo.path)).request_approval(
                flow.incident_id, expected_revision=checkpoint)
        except StaleRevision:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, range(2)))
    created = [item for item in results if item is not None]
    assert len(created) == 1 and len(flow.kinds(m.ApprovalRequirement)) == 1
    assert flow.incident().phase == m.IncidentPhase.AWAITING_APPROVAL
    # A retry with the current revision is idempotent: same requirement, no new artifact.
    assert flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow)) == created[0]
    assert len(flow.kinds(m.ApprovalRequirement)) == 1


def test_duplicate_approval_is_idempotent_and_conflicts_are_rejected(flow):
    intervention, promotion, requirement, decision = flow.ready()
    before = state(flow), counts(flow.repo)
    again = flow.lifecycle.decide_approval(flow.incident_id, **(flow.command(requirement, intervention) | {"context_revision": decision.context_revision}))
    assert again == decision and (state(flow), counts(flow.repo)) == before
    with pytest.raises(ApprovalRefused, match="conflicting duplicate"):
        flow.lifecycle.decide_approval(flow.incident_id, **(flow.command(requirement, intervention) | {"decision": "REJECT"}))
    with pytest.raises(ApprovalRefused, match="requires AWAITING_APPROVAL"):
        flow.lifecycle.decide_approval(flow.incident_id, **(flow.command(requirement, intervention) | {"actor_id": "approver-2"}))
    assert (state(flow), counts(flow.repo)) == before
    with db.get_conn(flow.repo.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM approval_decision").fetchone()[0] == 1


@pytest.mark.parametrize("change", [{"context_revision": 1}, {"intervention_hash": "wrong"}, {"intervention_id": "other"},
                                    {"actor_role": "observer"}, {"rationale": " "}])
def test_stale_or_malformed_approvals_are_rejected(flow, change):
    intervention, _, requirement = flow.awaiting()
    before = state(flow), counts(flow.repo)
    with pytest.raises(ApprovalRefused):
        flow.lifecycle.decide_approval(flow.incident_id, **(flow.command(requirement, intervention) | change))
    assert (state(flow), counts(flow.repo)) == before and flow.incident().phase == m.IncidentPhase.AWAITING_APPROVAL


def test_expired_requirement_is_rejected_and_replaced_by_a_new_requirement(flow, monkeypatch):
    intervention, _, requirement = flow.awaiting()
    clock = {"now": None}
    monkeypatch.setattr(lc, "utcnow", lambda: clock["now"] or utcnow())
    clock["now"] = utcnow() + timedelta(hours=25)
    with pytest.raises(ApprovalRefused, match="EXPIRED"):
        flow.lifecycle.decide_approval(flow.incident_id, **flow.command(requirement, intervention))
    # Requirement expiry is bounded by the confirmed window, so a fresh requirement also needs a current window.
    with pytest.raises(GovernanceBlocked, match="window"):
        flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow))
    clock["now"] = None
    fresh = requirement.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1), "id": new_id(), "supersedes_id": requirement.id})
    with flow.repo._write() as conn:
        incident = flow.repo._fetch(conn, flow.incident_id)
        flow.lifecycle._checkpoint(conn, incident, [fresh])
    with pytest.raises(ApprovalRefused, match="EXPIRED"):
        flow.lifecycle.decide_approval(flow.incident_id, **flow.command(fresh, intervention))
    replacement = flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow))
    assert replacement.supersedes_id == fresh.id and flow.incident().phase == m.IncidentPhase.AWAITING_APPROVAL
    flow.lifecycle.decide_approval(flow.incident_id, **flow.command(replacement, intervention))
    assert flow.incident().phase == m.IncidentPhase.READY


def test_stale_approval_after_intervention_supersession_is_rejected(flow):
    old, _, old_requirement = flow.awaiting()
    incident = flow.repo.transition(flow.incident_id, m.IncidentPhase.PLANNING, expected_revision=revision(flow), reason="replan")
    diagnosis_promotion = flow.service.promotion_lineage(flow.incident_id, old.diagnosis_id, "diagnosis")
    draft = flow.service.create_draft(flow.incident_id, expected_revision=incident.revision, **flow.binding_fields(
        diagnosis_promotion, flow.repo.get_artifact(flow.incident_id, diagnosis_promotion.source_report_id)))
    promotion = flow.promote_intervention(flow.complete(flow.start(draft), draft=draft), draft)
    new = flow.repo.get_artifact(flow.incident_id, promotion.target_id)
    requirement = flow.lifecycle.request_approval(flow.incident_id, expected_revision=revision(flow))
    assert requirement.intervention_id == new.id and requirement.id != old_requirement.id
    with pytest.raises(ApprovalRefused, match="exact current"):
        flow.lifecycle.decide_approval(flow.incident_id, **flow.command(old_requirement, old))
    # An old requirement cannot be reused for the new intervention either.
    with pytest.raises(ApprovalRefused):
        flow.lifecycle.decide_approval(flow.incident_id, **(flow.command(old_requirement, new)))
    flow.lifecycle.decide_approval(flow.incident_id, **flow.command(requirement, new))
    assert flow.incident().phase == m.IncidentPhase.READY


def test_rejection_escalates_and_blocks_execution(flow):
    intervention, _, requirement = flow.awaiting()
    decision = flow.lifecycle.decide_approval(flow.incident_id, **(flow.command(requirement, intervention) | {"decision": "REJECT"}))
    assert decision.decision == "REJECT" and flow.incident().phase == m.IncidentPhase.ESCALATED
    incident = flow.repo.transition(flow.incident_id, m.IncidentPhase.INVESTIGATING, expected_revision=revision(flow), reason="human resume")
    for target in ("DIAGNOSIS_VALIDATED", "PLANNING", "INTERVENTION_VALIDATED", "AWAITING_APPROVAL", "READY"):
        incident = flow.repo.transition(incident.id, m.IncidentPhase(target), expected_revision=incident.revision, reason="graph only")
    with pytest.raises((ExecutionRefused, AuthorityRefused)):
        flow.lifecycle.execute(flow.incident_id, intervention.id)


def test_approval_after_new_technical_evidence_requires_revalidation(flow):
    intervention, _, requirement = flow.awaiting()
    flow.confirm()  # new trusted inspection evidence after diagnosis promotion
    with pytest.raises(AuthorityRefused, match="new technical evidence") as refused:
        flow.lifecycle.decide_approval(flow.incident_id, **flow.command(requirement, intervention))
    assert refused.value.disposition == "NEEDS_EVIDENCE" and flow.incident().phase == m.IncidentPhase.AWAITING_APPROVAL


# ------------------------------------------------------------------ execution

def test_two_concurrent_execution_attempts_dispatch_once(flow, monkeypatch):
    intervention, *_ = flow.ready()
    entered, release = threading.Event(), threading.Event()

    def hold():
        entered.set()
        assert release.wait(5)
    adapter = use_cmms(monkeypatch, RecordingCmms(hook=hold))
    outcomes = {}

    def run(name):
        try:
            outcomes[name] = LifecycleService(IncidentRepository(flow.repo.path)).execute(flow.incident_id, intervention.id)
        except Exception as exc:  # noqa: BLE001 - recorded for assertions
            outcomes[name] = exc
    first = threading.Thread(target=run, args=("first",))
    first.start()
    assert entered.wait(5)
    run("second")  # arrives while the first claim is in flight
    assert isinstance(outcomes["second"], ExecutionBusy)
    release.set()
    first.join(5)
    assert outcomes["first"].phase == m.IncidentPhase.OBSERVING
    assert adapter.calls == 1 and counts(flow.repo)["work_package"] == 1
    with pytest.raises(ExecutionRefused, match="requires READY"):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert adapter.calls == 1


def test_execution_target_must_match_exact_current_hash(flow, monkeypatch):
    adapter = use_cmms(monkeypatch, RecordingCmms())
    intervention, *_ = flow.ready()
    with pytest.raises(ExecutionRefused, match="hash"):
        flow.lifecycle.execute(flow.incident_id, intervention.id, intervention_hash="wrong")
    assert adapter.calls == 0 and flow.incident().phase == m.IncidentPhase.READY


@pytest.mark.parametrize("outcome,status,phase,error", [
    ("confirm", "CONFIRMED", "OBSERVING", None), ("fail", "FAILED", "EXECUTION_FAILED", ExecutionFailed),
    ("unknown", "UNKNOWN", "EXECUTION_FAILED", ExecutionAmbiguous)])
def test_evidence_arriving_during_external_execution_never_loses_the_receipt(flow, monkeypatch, outcome, status, phase, error):
    intervention, *_ = flow.ready()
    revisions = {}

    def new_evidence_during_call():
        revisions["at_call"] = revision(flow)
        flow.confirm()  # trusted inspection evidence lands while the external action is in flight
        flow.evidence_service.request_and_collect(flow.incident_id, requested_by="diagnostic", equipment_ids=(ASSET,),
                                                  question="Fresh asset context", capability="get_asset_context",
                                                  required_for="diagnosis")
        revisions["after_evidence"] = revision(flow)
    adapter = use_cmms(monkeypatch, RecordingCmms(outcome, hook=new_evidence_during_call))
    if error is None:
        report = flow.lifecycle.execute(flow.incident_id, intervention.id)
    else:
        with pytest.raises(error) as failure:
            flow.lifecycle.execute(flow.incident_id, intervention.id)
        report = failure.value.report
    assert revisions["after_evidence"] > revisions["at_call"]
    receipt = flow.repo.get_execution_receipt(flow.incident_id, report.receipt_ids[0])
    assert receipt.status == status and receipt.intervention_id == intervention.id
    assert flow.repo.get_execution_claim(receipt.idempotency_key).state == status
    assert flow.incident().phase == m.IncidentPhase(phase) == report.phase
    assert adapter.calls == 1
    # Authority is now flagged for re-evaluation, but recorded reality is untouched.
    status_view = flow.lifecycle.status(flow.incident_id)
    assert not status_view.authority_valid and "new technical evidence" in status_view.authority_reason
    assert status_view.receipt_ids == (receipt.id,)
    if outcome == "confirm":
        assert counts(flow.repo)["work_package"] == 1
    # The receipt recorded through evidence churn is the settled truth: an exact
    # re-delivery is idempotent and a divergent one is refused, never re-recorded.
    before = state(flow), counts(flow.repo)
    flow.lifecycle.record_receipt(receipt)
    with pytest.raises(ReconciliationRequired):
        flow.lifecycle.record_receipt(receipt.model_copy(update={"id": new_id(), "external_ids": {"wo_number": "WO-X"}}))
    assert (state(flow), counts(flow.repo)) == before


def test_unknown_result_is_never_replayed(flow, monkeypatch):
    adapter = use_cmms(monkeypatch, RecordingCmms("unknown"))
    intervention, *_ = flow.ready()
    with pytest.raises(ExecutionAmbiguous):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    incident = flow.incident()
    assert incident.phase == m.IncidentPhase.EXECUTION_FAILED
    receipt = flow.repo.list_execution_receipts(flow.incident_id)[0]
    assert receipt.status == "UNKNOWN" and receipt.error_code == "TimeoutError"
    with pytest.raises(ReconciliationRequired):
        flow.lifecycle.retry_execution(flow.incident_id, expected_revision=incident.revision)
    with pytest.raises(ExecutionRefused):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    forced = flow.repo.transition(flow.incident_id, m.IncidentPhase.READY, expected_revision=revision(flow), reason="graph only")
    with pytest.raises(ReconciliationRequired, match="UNKNOWN"):
        LifecycleService(IncidentRepository(flow.repo.path)).execute(flow.incident_id, intervention.id)
    assert adapter.calls == 1 and flow.incident().phase == forced.phase == m.IncidentPhase.READY
    assert flow.lifecycle.status(flow.incident_id).reconciliation_required


def test_definitive_failure_allows_only_explicit_retry(flow, monkeypatch):
    adapter = use_cmms(monkeypatch, RecordingCmms("fail"))
    intervention, *_ = flow.ready()
    with pytest.raises(ExecutionFailed) as failed:
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert failed.value.report.phase == m.IncidentPhase.EXECUTION_FAILED
    with pytest.raises(ExecutionRefused, match="requires READY"):
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert adapter.calls == 1
    incident = flow.lifecycle.retry_execution(flow.incident_id, expected_revision=revision(flow))
    assert incident.phase == m.IncidentPhase.READY
    adapter.outcome = "confirm"
    report = flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert report.phase == m.IncidentPhase.OBSERVING and adapter.calls == 2
    receipts = flow.repo.list_execution_receipts(flow.incident_id, intervention_id=intervention.id)
    assert [(r.status, r.attempt) for r in receipts] == [("FAILED", 1), ("CONFIRMED", 2)]


def test_restart_after_execution_claim_does_not_replay(flow, monkeypatch):
    adapter = use_cmms(monkeypatch, RecordingCmms())
    intervention, *_ = flow.ready()
    claimed = flow.lifecycle._claim(flow.incident_id, intervention.id, None, adapter)  # process dies here
    assert flow.incident().phase == m.IncidentPhase.EXECUTING
    restarted = LifecycleService(IncidentRepository(flow.repo.path))
    with pytest.raises(ExecutionBusy):
        restarted.execute(flow.incident_id, intervention.id)
    status = restarted.reconcile(flow.incident_id)
    assert status.phase == m.IncidentPhase.EXECUTING and status.claim_state == "IN_FLIGHT" and status.reconciliation_required
    later = utcnow() + lc.AMBIGUOUS_CLAIM_AFTER + timedelta(seconds=1)
    monkeypatch.setattr(lc, "utcnow", lambda: later)
    status = restarted.reconcile(flow.incident_id)
    assert status.phase == m.IncidentPhase.EXECUTION_FAILED and status.claim_state == "UNKNOWN"
    receipt = flow.repo.list_execution_receipts(flow.incident_id)[0]
    assert receipt.status == "UNKNOWN" and receipt.error_code == "AMBIGUOUS_COMMIT" and receipt.attempt == claimed.claim.attempt
    with pytest.raises(ReconciliationRequired):
        restarted.retry_execution(flow.incident_id, expected_revision=revision(flow))
    assert adapter.calls == 0 and counts(flow.repo)["work_package"] == 0


def test_duplicate_completion_callback_is_idempotent_and_conflicts_are_refused(flow):
    intervention, *_ = flow.ready()
    claimed = flow.lifecycle._claim(flow.incident_id, intervention.id, None, services.cmms())
    receipt = flow.lifecycle._receipt(claimed, status="CONFIRMED", external_ids={"wo_number": "WO-1"})
    first = flow.lifecycle.record_receipt(receipt)
    assert first.phase == m.IncidentPhase.OBSERVING
    before = state(flow), counts(flow.repo)
    again = flow.lifecycle.record_receipt(receipt)
    assert again == first and (state(flow), counts(flow.repo)) == before
    # A re-delivered callback legitimately regenerates only artifact identity and timestamps.
    redelivered = receipt.model_copy(update={"id": new_id(), "created_at": utcnow(), "completed_at": utcnow()})
    assert flow.lifecycle.record_receipt(redelivered) == first and (state(flow), counts(flow.repo)) == before
    # Same claim, attempt and status but different consequential content is not the same completion.
    for change in ({"external_ids": {"wo_number": "WO-OTHER"}}, {"external_ids": {}}, {"adapter": "other.Cmms"},
                   {"error_message": "late note"}, {"attempted_at": utcnow()}):
        with pytest.raises(ReconciliationRequired, match="different consequential content"):
            flow.lifecycle.record_receipt(receipt.model_copy(update={"id": new_id(), **change}))
        assert (state(flow), counts(flow.repo)) == before
    conflicting = flow.lifecycle._receipt(claimed, status="FAILED", error_code="Late", error_message="late failure callback")
    with pytest.raises(ReconciliationRequired, match="settled"):
        flow.lifecycle.record_receipt(conflicting)
    assert (state(flow), counts(flow.repo)) == before
    assert flow.repo.get_execution_claim(receipt.idempotency_key).state == "CONFIRMED"
    assert [r.id for r in flow.repo.list_execution_receipts(flow.incident_id)] == [receipt.id]


def test_supersession_while_executing_is_impossible_and_history_stays_immutable(flow):
    intervention, promotion, requirement, decision = flow.ready()
    claimed = flow.lifecycle._claim(flow.incident_id, intervention.id, None, services.cmms())
    incident = flow.incident()
    with pytest.raises(InvalidTransition):
        flow.repo.transition(incident.id, m.IncidentPhase.PLANNING, expected_revision=incident.revision, reason="replace")
    diagnosis_promotion = flow.service.promotion_lineage(flow.incident_id, intervention.diagnosis_id, "diagnosis")
    with pytest.raises(Exception, match="requires current accepted diagnosis and planning"):
        flow.service.create_draft(flow.incident_id, expected_revision=incident.revision, **flow.binding_fields(
            diagnosis_promotion, flow.repo.get_artifact(flow.incident_id, diagnosis_promotion.source_report_id)))
    with pytest.raises(ApprovalRefused):
        flow.lifecycle.decide_approval(flow.incident_id, **(flow.command(requirement, intervention) | {"actor_id": "approver-2"}))
    receipt = flow.lifecycle._receipt(claimed, status="CONFIRMED", external_ids={"wo_number": "WO-2"})
    flow.lifecycle.record_receipt(receipt)
    stored = flow.repo.get_execution_receipt(flow.incident_id, receipt.id)
    assert (stored.intervention_id, stored.intervention_hash) == (intervention.id, artifact_hash(intervention))
    claim = flow.repo.get_execution_claim(receipt.idempotency_key)
    assert (claim.intervention_id, claim.intervention_hash, claim.state) == (intervention.id, artifact_hash(intervention), "CONFIRMED")


# ------------------------------------------- dispatch-time resource revalidation

CRITICAL_PART = "PRT-BRG"  # AC-COMP-01's only critical spare (seed BOM)


def sql(repo, statement, *params):
    with db.get_conn(repo.path) as conn:
        conn.execute(statement, params)


def rows(repo, table, where="1=1", *params):
    with db.get_conn(repo.path) as conn:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} WHERE {where}", params)]


def dispatch_parameters(flow, intervention):
    return WorkPackageParameters.model_validate(intervention.steps[0].parameters)


def authorization_for(incident_id, intervention_id="competitor-intervention"):
    return ExecutionAuthorization(incident_id=incident_id, intervention_id=intervention_id, intervention_hash="h",
                                  step_id="step-1", idempotency_key=f"key:{incident_id}", executor=TRUSTED_EXECUTOR,
                                  _seal=_AUTHORITY_SEAL)


class NonDefinitiveCmms(RecordingCmms):
    """An adapter that does not blanket-declare its failures definitive."""
    failure_is_definitive = False


def assert_atomic_definitive_failure(flow, intervention, before, adapter, error_code="ResourceUnavailable"):
    with pytest.raises(ExecutionFailed) as failure:
        flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert not isinstance(failure.value, ExecutionAmbiguous)
    assert adapter.calls == 1 and failure.value.report.phase == m.IncidentPhase.EXECUTION_FAILED
    after = counts(flow.repo)
    for table in ("work_order", "work_package", "part_reservation", "labor_booking"):
        assert after[table] == before[table], f"{table} must be rolled back"
    receipt = flow.repo.get_execution_receipt(flow.incident_id, failure.value.report.receipt_ids[0])
    assert receipt.status == "FAILED" and receipt.error_code == error_code
    assert flow.repo.get_execution_claim(receipt.idempotency_key).state == "FAILED"
    assert flow.incident().phase == m.IncidentPhase.EXECUTION_FAILED
    assert not flow.lifecycle.status(flow.incident_id).reconciliation_required
    return receipt


@pytest.mark.parametrize("adapter_class", [RecordingCmms, NonDefinitiveCmms])
def test_stale_stock_at_dispatch_fails_atomically_and_definitively(flow, monkeypatch, adapter_class):
    intervention, *_ = flow.ready()
    before = counts(flow.repo)
    # Stock disappears after governance and the claim but before the CMMS transaction.
    adapter = use_cmms(monkeypatch, adapter_class(hook=lambda: sql(flow.repo, "UPDATE part SET on_hand_qty=0 WHERE part_id=?",
                                                                    CRITICAL_PART)))
    receipt = assert_atomic_definitive_failure(flow, intervention, before, adapter)
    assert "insufficient uncommitted stock" in receipt.error_message
    # Definitive FAILED (not UNKNOWN): explicit retry is allowed once stock is back.
    sql(flow.repo, "UPDATE part SET on_hand_qty=3 WHERE part_id=?", CRITICAL_PART)
    adapter.hook = None
    flow.lifecycle.retry_execution(flow.incident_id, expected_revision=revision(flow))
    report = flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert report.phase == m.IncidentPhase.OBSERVING and counts(flow.repo)["part_reservation"] == before["part_reservation"] + 1


def test_competing_incident_cannot_share_the_last_unit_of_stock(flow, monkeypatch):
    intervention, *_ = flow.ready()
    parameters = dispatch_parameters(flow, intervention)
    sql(flow.repo, "UPDATE part SET on_hand_qty=1 WHERE part_id=?", CRITICAL_PART)  # governance still passes on 1
    competitor = GovernedExecutor._legacy_work_package(parameters.model_copy(update={"technician_id": "TECH-203"}))
    real_cmms = services.cmms()
    winner = {}

    def other_incident_dispatches_first():
        # A different incident's governed dispatch reserves the last unit while this claim is in flight.
        winner.update(real_cmms.create_work_package(competitor, authorization=authorization_for("other-incident")))
    adapter = use_cmms(monkeypatch, RecordingCmms(hook=other_incident_dispatches_first))
    before = counts(flow.repo)
    before["work_order"] += 1; before["work_package"] += 1; before["part_reservation"] += 1; before["labor_booking"] += 1
    assert_atomic_definitive_failure(flow, intervention, before, adapter)
    reservations = rows(flow.repo, "part_reservation", "part_id=? AND status='RESERVED'", CRITICAL_PART)
    assert [r["wo_id"] for r in reservations] == [winner["wo_id"]]


def test_concurrent_dispatches_for_the_final_unit_reserve_exactly_once(seeded_db):
    from core.services.adapters.local import LocalCmmsAdapter
    sql(IncidentRepository(), "UPDATE part SET on_hand_qty=1 WHERE part_id=?", CRITICAL_PART)
    proposal = sample_proposal()
    proposal["actions"]["schedule"]["window"] = "2030-01-01T08:00:00+00:00/2030-01-01T09:00:00+00:00"
    proposals = {"incident-a": proposal, "incident-b": {**proposal, "actions": {**proposal["actions"], "technician": {"technician_id": "TECH-203"}}}}
    barrier = threading.Barrier(2)
    outcomes = {}

    def dispatch(incident_id):
        barrier.wait(5)
        try:
            outcomes[incident_id] = LocalCmmsAdapter().create_work_package(proposals[incident_id],
                                                                          authorization=authorization_for(incident_id))
        except Exception as exc:  # noqa: BLE001 - recorded for assertions
            outcomes[incident_id] = exc
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(dispatch, proposals))
    succeeded = [k for k, v in outcomes.items() if isinstance(v, dict)]
    failed = [v for v in outcomes.values() if isinstance(v, Exception)]
    assert len(succeeded) == 1 and len(failed) == 1
    assert type(failed[0]).__name__ == "ResourceUnavailable" and failed[0].failure_is_definitive is True
    repo = IncidentRepository()
    assert len(rows(repo, "part_reservation", "part_id=? AND status='RESERVED'", CRITICAL_PART)) == 1
    assert len(rows(repo, "work_package")) == 1 and len(rows(repo, "labor_booking")) == 1
    # The loser left no work order behind either (seed history holds exactly one WO).
    assert len(rows(repo, "work_order")) == len(rows(repo, "work_order", "wo_id=?", outcomes[succeeded[0]]["wo_id"])) + 1


@pytest.mark.parametrize("change", ["available", "qualification", "plant", "overlapping_booking"])
def test_stale_technician_state_at_dispatch_fails_atomically(flow, monkeypatch, change):
    intervention, *_ = flow.ready()
    parameters = dispatch_parameters(flow, intervention)
    tech = parameters.technician_id
    before = counts(flow.repo)

    def stale_technician():
        if change == "available":
            sql(flow.repo, "UPDATE technician SET available=0 WHERE technician_id=?", tech)
        elif change == "qualification":
            sql(flow.repo, "UPDATE technician SET skills='PUMP,ROTATING' WHERE technician_id=?", tech)
        elif change == "plant":
            sql(flow.repo, "INSERT INTO plant VALUES ('US02','Other Plant','UTC')")
            sql(flow.repo, "UPDATE technician SET plant_id='US02' WHERE technician_id=?", tech)
        else:  # another dated booking for the same technician overlapping this exact window
            start, end = parameters.window.split("/")
            sql(flow.repo, "INSERT INTO labor_booking (wo_id, technician_id, window_label, window_min, status, booked_at) "
                           "VALUES (NULL, ?, ?, 60, 'BOOKED', 'now')", tech, f"{start}/{end}")
            before["labor_booking"] += 1
    adapter = use_cmms(monkeypatch, RecordingCmms(hook=stale_technician))
    receipt = assert_atomic_definitive_failure(flow, intervention, before, adapter)
    expected = {"available": "unavailable technician", "qualification": "exact recorded qualification",
                "plant": "unavailable technician", "overlapping_booking": "overlapping the window"}[change]
    assert expected in receipt.error_message


def test_undated_booking_labels_cannot_prove_a_conflict(flow, monkeypatch):
    """Documented limitation: legacy 'HH:MM–HH:MM' labels carry no date, so overlap is unknowable and not enforced."""
    intervention, *_ = flow.ready()
    tech = dispatch_parameters(flow, intervention).technician_id
    sql(flow.repo, "INSERT INTO labor_booking (wo_id, technician_id, window_label, window_min, status, booked_at) "
                   "VALUES (NULL, ?, '08:00–09:00', 60, 'BOOKED', 'now')", tech)
    adapter = use_cmms(monkeypatch, RecordingCmms())
    report = flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert report.phase == m.IncidentPhase.OBSERVING and adapter.calls == 1


def test_successful_dispatch_is_unchanged_and_writes_every_row_once(flow, monkeypatch):
    intervention, *_ = flow.ready()
    parameters = dispatch_parameters(flow, intervention)
    before = counts(flow.repo)
    adapter = use_cmms(monkeypatch, RecordingCmms())
    report = flow.lifecycle.execute(flow.incident_id, intervention.id)
    assert report.phase == m.IncidentPhase.OBSERVING and adapter.calls == 1
    after = counts(flow.repo)
    assert {t: after[t] - before[t] for t in ("work_order", "work_package", "part_reservation", "labor_booking")} == {
        "work_order": 1, "work_package": 1, "part_reservation": 1, "labor_booking": 1}
    wo_id = int(report.external_objects["wo_id"])
    reservation, = rows(flow.repo, "part_reservation", "wo_id=?", wo_id)
    booking, = rows(flow.repo, "labor_booking", "wo_id=?", wo_id)
    assert (reservation["part_id"], reservation["qty"], reservation["status"]) == (CRITICAL_PART, 1, "RESERVED")
    assert (booking["technician_id"], booking["window_label"], booking["status"]) == (parameters.technician_id, parameters.window, "BOOKED")
    assert set(report.external_objects) >= {"wo_id", "wo_number", "package_number"}


# --------------------------------------------------------------- recovery

def test_crash_after_atomic_approval_reconstructs_ready_without_dispatch(flow, monkeypatch):
    adapter = use_cmms(monkeypatch, RecordingCmms())
    intervention, promotion, requirement, decision = flow.ready()
    restarted = LifecycleService(IncidentRepository(flow.repo.path))
    statuses = restarted.recover()
    status = next(item for item in statuses if item.incident_id == flow.incident_id)
    assert status.phase == m.IncidentPhase.READY and status.authority_valid and status.promotion_id == promotion.id
    assert status.approval.state == "APPROVED" and status.approval.decision_ids == (decision.id,)
    assert status.claim_state is None and adapter.calls == 0 and counts(flow.repo)["execution_claim"] == 0
    report = restarted.execute(flow.incident_id, intervention.id, intervention_hash=status.intervention_hash)
    assert report.phase == m.IncidentPhase.OBSERVING and adapter.calls == 1
    again = LifecycleService(IncidentRepository(flow.repo.path)).recover()
    assert next(item for item in again if item.incident_id == flow.incident_id).phase == m.IncidentPhase.OBSERVING
    assert adapter.calls == 1


def test_projection_exposes_exact_approval_identifiers_only(flow):
    intervention, promotion, requirement = flow.awaiting()
    view = flow.lifecycle.projection(flow.incident_id)
    assert view["phase"] == "AWAITING_APPROVAL" and view["authority_valid"] is True
    assert view["requirement"]["requirement_id"] == requirement.id
    assert view["requirement"]["intervention_hash"] == artifact_hash(intervention)
    assert view["requirement"]["context_revision"] == revision(flow)
    assert "result_payload" not in view and "ValidationVerdict" not in str(view)


# ------------------------------------------------- application reasoning stages

def scripted_supervisor(monkeypatch, env, transform=None):
    async def invoke(runtime, service, context, **kwargs):
        from core.agents.contracts import SupervisorResult
        snapshot = next(a for a in env.repo.list_artifacts(env.incident_id)
                        if isinstance(a, m.SupervisorRunSnapshot) and a.run_id == context.run_id)
        draft = None
        if context.review_target_id:
            draft = env.repo.get_artifact(env.incident_id, context.review_target_id)
        payload = result_payload(env, snapshot, draft=draft)
        if transform:
            payload = transform(payload)
        return SupervisorResult.model_validate(payload)
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", invoke)


async def test_diagnose_parks_missing_confirmation_and_resumes_after_trusted_evidence(flow, monkeypatch):
    scripted_supervisor(monkeypatch, flow)
    outcome = await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=flow.runtime,
                                            evidence_service=flow.evidence_service)
    assert outcome.disposition == "NEEDS_EVIDENCE" and outcome.phase == m.IncidentPhase.AWAITING_EVIDENCE
    assert flow.incident().current_diagnosis_id is None
    fields = dict(incident_id=flow.incident_id, asset_id=ASSET, confirmed_mechanism="Confirmed compressor mechanical overload",
                  failure_mode_code="OSF", supporting_evidence_ids=(flow.history_id,),
                  performed_checks=(m.PerformedCheck(check="Shaft inspection", result="Overload confirmed", passed=True),),
                  observed_at=utcnow(), source="offline-inspection", actor_id="trusted-inspector", provenance="SIMULATED")
    evidence, incident = flow.lifecycle.submit_technical_confirmation(
        m.TrustedTechnicalConfirmation(**fields), expected_revision=revision(flow))
    flow.confirmation = evidence
    assert incident.phase == m.IncidentPhase.INVESTIGATING
    outcome = await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=flow.runtime,
                                            evidence_service=flow.evidence_service)
    assert outcome.disposition == "PROMOTED" and outcome.phase == m.IncidentPhase.DIAGNOSIS_VALIDATED
    assert flow.service.promotion_lineage(flow.incident_id, flow.incident().current_diagnosis_id, "diagnosis").id == outcome.promotion_id


@pytest.mark.parametrize("change,disposition,phase", [
    ({"disposition": "ESCALATED", "decision": None, "blockers": ["Unsafe"]}, "ESCALATED", "ESCALATED"),
    ({"termination_reason": "TIMEOUT"}, "ESCALATED", "ESCALATED"),
    ({"disposition": "UNRESOLVED"}, "NEEDS_EVIDENCE", "AWAITING_EVIDENCE")])
async def test_diagnose_routes_unsuccessful_runs_without_creating_authority(flow, monkeypatch, change, disposition, phase):
    flow.confirm()
    scripted_supervisor(monkeypatch, flow, lambda payload: payload | change)
    outcome = await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=flow.runtime,
                                            evidence_service=flow.evidence_service)
    assert outcome.disposition == disposition and outcome.phase == m.IncidentPhase(phase)
    assert flow.incident().current_diagnosis_id is None and not flow.kinds(m.Diagnosis)


async def test_plan_reviews_exact_draft_and_requests_approval_atomically(flow, monkeypatch):
    scripted_supervisor(monkeypatch, flow)
    promotion, report = flow.diagnosis()
    outcome = await flow.lifecycle.plan(flow.incident_id, runtime=flow.runtime, evidence_service=flow.evidence_service,
                                        expected_revision=revision(flow), **flow.binding_fields(promotion, report))
    assert outcome.disposition == "APPROVAL_REQUESTED" and outcome.phase == m.IncidentPhase.AWAITING_APPROVAL
    incident = flow.incident()
    requirement = flow.repo.get_artifact(flow.incident_id, outcome.requirement_id)
    assert requirement.intervention_id == incident.current_intervention_id and requirement.promotion_id == outcome.promotion_id
    assert flow.service.promotion_lineage(flow.incident_id, incident.current_intervention_id, "intervention").reviewed_draft_id == outcome.draft_id
    phases = [e.payload["to"] for e in flow.repo.list_events(flow.incident_id) if e.event_type == "PHASE_CHANGED"]
    assert phases[-3:] == ["PLANNING", "INTERVENTION_VALIDATED", "AWAITING_APPROVAL"]


async def test_plan_evidence_need_stays_in_planning_and_unsafe_review_escalates(flow, monkeypatch):
    promotion, report = flow.diagnosis()
    scripted_supervisor(monkeypatch, flow, lambda payload: payload | {"disposition": "NEEDS_EVIDENCE",
                                                                       "unresolved_evidence_needs": [{"capability": "inspection", "question": "Check"}]})
    outcome = await flow.lifecycle.plan(flow.incident_id, runtime=flow.runtime, evidence_service=flow.evidence_service,
                                        expected_revision=revision(flow), **flow.binding_fields(promotion, report))
    assert outcome.disposition == "NEEDS_EVIDENCE" and outcome.phase == m.IncidentPhase.PLANNING
    assert flow.incident().current_intervention_id is None
    scripted_supervisor(monkeypatch, flow, lambda payload: payload | {"disposition": "BLOCKED", "decision": None, "blockers": ["Unsafe isolation"]})
    outcome = await flow.lifecycle.review_draft(flow.incident_id, draft_id=outcome.draft_id, runtime=flow.runtime,
                                                evidence_service=flow.evidence_service)
    assert outcome.disposition == "ESCALATED" and outcome.phase == m.IncidentPhase.ESCALATED
    assert flow.incident().current_intervention_id is None and not flow.kinds(m.ApprovalRequirement)


async def test_no_model_invocation_holds_a_write_lock(flow, monkeypatch):
    flow.confirm()
    observed = []

    async def invoke(runtime, service, context, **kwargs):
        from core.agents.contracts import SupervisorResult
        with db.get_conn(flow.repo.path) as conn:
            conn.execute("BEGIN IMMEDIATE")  # would block if the lifecycle held a writer
            observed.append(True)
        snapshot = next(a for a in flow.repo.list_artifacts(flow.incident_id) if isinstance(a, m.SupervisorRunSnapshot))
        return SupervisorResult.model_validate(result_payload(flow, snapshot))
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", invoke)
    outcome = await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=flow.runtime,
                                            evidence_service=flow.evidence_service)
    assert observed and outcome.disposition == "PROMOTED"
