"""Focused governed approval and crash-safe execution tests."""
from __future__ import annotations

from datetime import timedelta
import sqlite3

import pytest

from core import db, services, tools
from core.reliability import models as m
from core.reliability.execution import (AMBIGUOUS_CLAIM_AFTER, TRUSTED_EXECUTOR,
                                        ExecutionAmbiguous, ExecutionDenied, ExecutionFailed,
                                        GovernedExecutor)
from core.reliability.governance import (ApprovalLedger, ExecutionPolicy,
                                         PolicyDisposition, artifact_hash)
from core.reliability.repository import (IncidentRepository, InvalidReference,
                                         content_hash, new_id, utcnow)


@pytest.fixture
def repo(seeded_db):
    return IncidentRepository()


def work_step(equipment_id="AC-COMP-01"):
    return m.InterventionStep(
        id=new_id(), created_at=utcnow(), capability="create_work_package",
        equipment_ids=(equipment_id,), parameters={
            "equipment_id": equipment_id, "failure_mode_id": "FM-OSF",
            "technician_id": "TECH-201", "priority": "HIGH", "detail": "governed repair",
            "parts": [], "window": "10:00–10:45", "window_min": 45,
            "prediction_failure_prob": 0.91,
        }, verification_criteria=("observe recovery",),
    )


def notify_step(equipment_id="AC-COMP-01", recipient="TECH-201"):
    return m.InterventionStep(
        id=new_id(), created_at=utcnow(), capability="notify",
        equipment_ids=(equipment_id,), parameters={
            "recipient_id": recipient, "subject": f"Dispatch {equipment_id}",
            "body": "Attend governed intervention", "channel": "sms",
        },
    )


def prepared(repo, *, equipment_id="AC-COMP-01", steps=None, risk="HIGH",
             intervention_status="VALIDATED", verdict="ACCEPT", blocker=()):
    incident = repo.create_incident((equipment_id,), admission_key=f"test:{equipment_id}:{new_id()}")
    incident = repo.transition(incident.id, m.IncidentPhase.INVESTIGATING,
                               expected_revision=incident.revision, reason="test investigation")
    hypothesis = m.Hypothesis(
        id=new_id(), incident_id=incident.id, created_at=utcnow(),
        equipment_ids=(equipment_id,), mechanism="test mechanism", confidence=0.8,
        confidence_basis="test", falsification_tests=("test",),
    )
    incident = repo.add_artifact(hypothesis, expected_revision=incident.revision)
    diagnosis = m.Diagnosis(
        id=new_id(), incident_id=incident.id, created_at=utcnow(),
        equipment_ids=(equipment_id,), hypothesis_ids=(hypothesis.id,),
        conclusion="validated test diagnosis", evidence_ids=(), confidence=0.8,
        status="ACCEPTED",
    )
    incident = repo.add_artifact(diagnosis, expected_revision=incident.revision)
    diagnosis_verdict = m.ValidationVerdict(
        id=new_id(), incident_id=incident.id, created_at=utcnow(),
        target_kind="diagnosis", target_id=diagnosis.id,
        target_hash=content_hash(diagnosis.model_dump(mode="json")),
        input_revision=incident.revision, decision="ACCEPT", validator_run_id="test-critic",
    )
    incident = repo.add_artifact(diagnosis_verdict, expected_revision=incident.revision)
    incident = repo.transition(incident.id, m.IncidentPhase.DIAGNOSIS_VALIDATED,
                               expected_revision=incident.revision, reason="test validation")
    incident = repo.transition(incident.id, m.IncidentPhase.PLANNING,
                               expected_revision=incident.revision, reason="test planning")
    intervention = m.Intervention(
        id=new_id(), incident_id=incident.id, created_at=utcnow(), diagnosis_id=diagnosis.id,
        revision=1, steps=tuple(steps or (work_step(equipment_id),)), risk=risk,
        estimated_cost=1000, estimated_downtime_minutes=45, estimated_avoided_loss=10000,
        business_assumption_version="test-1", status=intervention_status,
    )
    incident = repo.add_artifact(intervention, expected_revision=incident.revision)
    if verdict:
        validation = m.ValidationVerdict(
            id=new_id(), incident_id=incident.id, created_at=utcnow(),
            target_kind="intervention", target_id=intervention.id,
            target_hash=artifact_hash(intervention), input_revision=incident.revision,
            decision=verdict, blocking_issues=tuple(blocker), validator_run_id="test-critic",
        )
        incident = repo.add_artifact(validation, expected_revision=incident.revision)
        if verdict == "ACCEPT":
            incident = repo.transition(incident.id, m.IncidentPhase.INTERVENTION_VALIDATED,
                                       expected_revision=incident.revision, reason="test release")
    return incident, intervention


def approve(repo, incident, intervention):
    ledger = ApprovalLedger(repo)
    requirement = ledger.request(incident.id, intervention.id)
    assert requirement is not None
    ledger.decide(incident.id, requirement.id, actor_id="manager-1",
                  actor_role="maintenance_approver", decision="APPROVE",
                  rationale="reviewed exact intervention")
    return requirement


def test_unvalidated_and_blocked_interventions_cannot_execute(repo):
    incident, intervention = prepared(repo, intervention_status="DRAFT", verdict=None)
    with pytest.raises(ExecutionDenied, match="BLOCKED"):
        GovernedExecutor(repo).execute(incident.id, intervention.id)

    incident, intervention = prepared(repo, risk="PROHIBITED")
    evaluation = ApprovalLedger(repo).evaluate(incident.id, intervention.id)
    assert evaluation.disposition == PolicyDisposition.BLOCKED
    with pytest.raises(ExecutionDenied, match="prohibited"):
        GovernedExecutor(repo).execute(incident.id, intervention.id)


def test_approval_required_rejection_and_exact_revision_binding(repo):
    incident, intervention = prepared(repo)
    requirement = ApprovalLedger(repo).request(incident.id, intervention.id)
    with pytest.raises(ExecutionDenied, match="REQUIRES_APPROVAL"):
        GovernedExecutor(repo).execute(incident.id, intervention.id)

    ledger = ApprovalLedger(repo)
    ledger.decide(incident.id, requirement.id, actor_id="manager-1",
                  actor_role="maintenance_approver", decision="REJECT",
                  rationale="unsafe timing")
    with pytest.raises(ExecutionDenied, match="rejected"):
        GovernedExecutor(repo).execute(incident.id, intervention.id)

    other_incident, other = prepared(repo, equipment_id="HYD-PUMP-03")
    wrong = m.ApprovalDecision(
        id=new_id(), incident_id=other_incident.id, created_at=utcnow(),
        requirement_id=requirement.id, intervention_id=other.id,
        intervention_hash=artifact_hash(other), actor_id="manager-1",
        actor_role="maintenance_approver", decision="APPROVE", rationale="wrong incident",
        context_revision=repo.fetch_incident(other_incident.id).revision,
    )
    with pytest.raises(InvalidReference):
        repo.add_approval_decision(wrong, expected_revision=wrong.context_revision)


def test_stale_approval_cannot_authorize_revised_intervention(repo):
    incident, first = prepared(repo)
    approve(repo, incident, first)
    incident = repo.fetch_incident(incident.id)
    second = first.model_copy(update={
        "id": new_id(), "created_at": utcnow(), "revision": 2,
        "supersedes_id": first.id,
        "steps": (work_step(),),
    })
    incident = repo.add_artifact(second, expected_revision=incident.revision)
    verdict = m.ValidationVerdict(
        id=new_id(), incident_id=incident.id, created_at=utcnow(),
        target_kind="intervention", target_id=second.id,
        target_hash=artifact_hash(second), input_revision=incident.revision,
        decision="ACCEPT", validator_run_id="test-critic",
    )
    repo.add_artifact(verdict, expected_revision=incident.revision)

    assert ApprovalLedger(repo).evaluate(incident.id, first.id).disposition == PolicyDisposition.BLOCKED
    assert ApprovalLedger(repo).evaluate(incident.id, second.id).disposition == PolicyDisposition.REQUIRES_APPROVAL
    with pytest.raises(ExecutionDenied):
        GovernedExecutor(repo).execute(incident.id, second.id)


def test_success_receipts_observing_and_idempotency_survive_reconstruction(repo):
    incident, intervention = prepared(repo)
    requirement = approve(repo, incident, intervention)
    first = GovernedExecutor(repo).execute(incident.id, intervention.id)

    assert first.phase == m.IncidentPhase.OBSERVING
    assert len(first.receipt_ids) == 1
    assert repo.get_execution_receipt(incident.id, first.receipt_ids[0]).status == "CONFIRMED"
    with db.get_conn(repo.path) as conn:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("work_order", "work_package", "notification")}
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE execution_receipt SET status='FAILED'")

    rebuilt_repo = IncidentRepository(repo.path)
    second = GovernedExecutor(rebuilt_repo).execute(incident.id, intervention.id)
    assert second.skipped_step_ids == (intervention.steps[0].id,)
    assert rebuilt_repo.list_approval_decisions(incident.id)[0].id
    assert rebuilt_repo.list_execution_receipts(incident.id)[0].id == first.receipt_ids[0]
    with db.get_conn(repo.path) as conn:
        assert {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in counts} == counts


def test_partial_failure_retry_preserves_and_skips_successful_steps(repo, monkeypatch):
    steps = (notify_step(recipient="TECH-201"), notify_step(recipient="TECH-202"))
    incident, intervention = prepared(repo, steps=steps)
    approve(repo, incident, intervention)

    class FlakyNotifications:
        failure_is_definitive = True

        def __init__(self):
            self.calls = []
            self.fail_second = True

        def notify(self, **kwargs):
            self.calls.append(kwargs["recipient_id"])
            if kwargs["recipient_id"] == "TECH-202" and self.fail_second:
                raise RuntimeError("CMMS downstream unavailable")
            return {"notification_id": len(self.calls), "status": "SENT"}

    adapter = FlakyNotifications()
    monkeypatch.setattr(services, "notifications", lambda: adapter)
    with pytest.raises(ExecutionFailed) as failed:
        GovernedExecutor(repo).execute(incident.id, intervention.id)
    assert failed.value.report.phase == m.IncidentPhase.EXECUTION_FAILED
    receipts = repo.list_execution_receipts(incident.id, intervention_id=intervention.id)
    assert [r.status for r in receipts] == ["CONFIRMED", "FAILED"]
    assert receipts[-1].adapter.endswith("FlakyNotifications")
    assert receipts[-1].executor == TRUSTED_EXECUTOR
    assert receipts[-1].capability == "notify"
    assert receipts[-1].error_code == "RuntimeError"

    adapter.fail_second = False
    report = GovernedExecutor(IncidentRepository(repo.path)).execute(incident.id, intervention.id)
    assert report.phase == m.IncidentPhase.OBSERVING
    assert adapter.calls == ["TECH-201", "TECH-202", "TECH-202"]
    assert steps[0].id in report.skipped_step_ids
    assert [r.status for r in repo.list_execution_receipts(
        incident.id, intervention_id=intervention.id)] == ["CONFIRMED", "FAILED", "CONFIRMED"]


def test_ambiguous_external_failure_is_not_retried(repo, monkeypatch):
    incident, intervention = prepared(repo, steps=(notify_step(),))
    approve(repo, incident, intervention)

    class AmbiguousNotifications:
        calls = 0

        def notify(self, **kwargs):
            self.calls += 1
            raise TimeoutError("response lost after dispatch")

    adapter = AmbiguousNotifications()
    monkeypatch.setattr(services, "notifications", lambda: adapter)
    with pytest.raises(ExecutionAmbiguous):
        GovernedExecutor(repo).execute(incident.id, intervention.id)
    receipt = repo.list_execution_receipts(incident.id)[0]
    assert receipt.status == "UNKNOWN"
    assert receipt.adapter.endswith("AmbiguousNotifications")
    assert receipt.executor == TRUSTED_EXECUTOR
    assert receipt.capability == "notify"
    assert receipt.error_code == "TimeoutError"
    with pytest.raises(ExecutionAmbiguous, match="manual reconciliation"):
        GovernedExecutor(IncidentRepository(repo.path)).execute(incident.id, intervention.id)
    assert adapter.calls == 1
    assert repo.fetch_incident(incident.id).phase == m.IncidentPhase.EXECUTION_FAILED


def test_partial_success_then_unknown_preserves_receipts_and_refuses_replay(repo, monkeypatch):
    steps = (notify_step(recipient="TECH-201"), notify_step(recipient="TECH-202"), work_step())
    incident, intervention = prepared(repo, steps=steps)
    approve(repo, incident, intervention)

    class RecordingNotifications:
        failure_is_definitive = True

        def __init__(self):
            self.calls = []

        def notify(self, **kwargs):
            self.calls.append(kwargs["recipient_id"])
            return {"notification_id": len(self.calls), "status": "SENT"}

    class AmbiguousCmms:
        def __init__(self):
            self.calls = 0

        def create_work_package(self, _proposal, *, authorization):
            self.calls += 1
            raise TimeoutError("response lost after remote CMMS commit")

    notifications = RecordingNotifications()
    cmms = AmbiguousCmms()
    monkeypatch.setattr(services, "notifications", lambda: notifications)
    monkeypatch.setattr(services, "cmms", lambda: cmms)

    with pytest.raises(ExecutionAmbiguous) as first_failure:
        GovernedExecutor(repo).execute(incident.id, intervention.id)
    first_receipts = repo.list_execution_receipts(incident.id, intervention_id=intervention.id)
    assert [receipt.status for receipt in first_receipts] == ["CONFIRMED", "CONFIRMED", "UNKNOWN"]
    assert first_receipts[-1].adapter.endswith("AmbiguousCmms")
    assert first_receipts[-1].executor == TRUSTED_EXECUTOR
    assert first_receipts[-1].capability == "create_work_package"
    assert first_receipts[-1].error_code == "TimeoutError"
    assert first_failure.value.report.receipt_ids == tuple(receipt.id for receipt in first_receipts)
    assert notifications.calls == ["TECH-201", "TECH-202"]
    assert cmms.calls == 1

    rebuilt_repo = IncidentRepository(repo.path)
    with pytest.raises(ExecutionAmbiguous, match="manual reconciliation") as retry:
        GovernedExecutor(rebuilt_repo).execute(incident.id, intervention.id)
    assert retry.value.report.skipped_step_ids == (steps[0].id, steps[1].id)
    assert notifications.calls == ["TECH-201", "TECH-202"]
    assert cmms.calls == 1
    assert rebuilt_repo.list_execution_receipts(
        incident.id, intervention_id=intervention.id) == first_receipts


def test_stale_in_flight_claim_preserves_adapter_on_unknown_receipt(repo):
    incident, intervention = prepared(repo, steps=(notify_step(),))
    approve(repo, incident, intervention)
    incident = repo.fetch_incident(incident.id)
    incident = repo.transition(incident.id, m.IncidentPhase.READY,
                               expected_revision=incident.revision, reason="test execution ready")
    incident = repo.transition(incident.id, m.IncidentPhase.EXECUTING,
                               expected_revision=incident.revision, reason="test execution started")
    step = intervention.steps[0]
    request_hash = content_hash({"capability": step.capability,
                                 "parameters": step.parameters})
    started_at = utcnow() - AMBIGUOUS_CLAIM_AFTER - timedelta(seconds=1)
    claim = m.ExecutionClaim(
        idempotency_key=GovernedExecutor._idempotency_key(
            incident, intervention, step, request_hash),
        incident_id=incident.id, intervention_id=intervention.id,
        intervention_hash=artifact_hash(intervention), step_id=step.id,
        capability=step.capability, request_hash=request_hash,
        adapter="vendor.cmms.RemoteNotificationAdapter", executor=TRUSTED_EXECUTOR,
        state="IN_FLIGHT", attempt=1, started_at=started_at, updated_at=started_at,
    )
    incident, _, acquired = repo.begin_execution_claim(claim, expected_revision=incident.revision)
    assert acquired

    with pytest.raises(ExecutionAmbiguous, match="refusing blind retry"):
        GovernedExecutor(IncidentRepository(repo.path)).execute(incident.id, intervention.id)
    receipt = repo.list_execution_receipts(incident.id)[0]
    assert receipt.status == "UNKNOWN"
    assert receipt.adapter == "vendor.cmms.RemoteNotificationAdapter"
    assert receipt.executor == TRUSTED_EXECUTOR
    assert receipt.error_code == "AMBIGUOUS_COMMIT"


def test_public_mutation_surfaces_cannot_bypass_governance(repo):
    from mcp_app import server
    from tests.conftest import sample_proposal

    with pytest.raises(TypeError):
        tools.commit_actions(sample_proposal(), None)
    with pytest.raises(PermissionError, match="governed execution"):
        services.cmms().create_work_package(sample_proposal())
    with pytest.raises(PermissionError, match="persisted Intervention"):
        tools.notify_technician("TECH-201", "dispatch", "go", send=True)
    exposed = set(server.mcp._tool_manager._tools)
    assert "create_work_package" not in exposed
    assert "raise_alert" not in exposed
    assert "execute_governed_intervention" in exposed
    assert tools.check_parts("AC-COMP-01")["parts"]
