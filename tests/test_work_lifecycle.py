"""F1.2 durable work lifecycle: acknowledge, decline, report, reassign (M1).

Work facts are about people, never about the plant. Every command is validated against
the current assignment of the executed dispatch, the case revision and the actor; a
keyed retry is answered from the durable record; reassignment keeps history; and the
eligibility policy (operon-work-eligibility-1) decides which reports may later open
outcome verification. Real repository transactions and real promotion lineage.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import threading

import pytest

from core import db
from core.reliability import lifecycle as lc
from core.reliability import models as m
from core.reliability.actors import ActorRefused
from core.reliability.lifecycle import LifecycleRefused, LifecycleService, work_eligibility
from core.reliability.repository import DuplicateRecord, InactiveIncident, StaleRevision, new_id, utcnow
from tests.test_outcome import dispatched
from tests.test_promotion import ASSET, revision
from tests.test_reliability_lifecycle import Flow

TECHNICIAN = m.ActorRef(kind="DECLARED", id="tech-7", role="technician")
DISPATCHER = m.ActorRef(kind="DECLARED", id="dispatcher-1", role="dispatcher")


@pytest.fixture
def flow(seeded_db):
    return Flow()


def events(flow, kind):
    return [e for e in flow.repo.list_events(flow.incident_id) if e.event_type == kind]


def current(flow):
    return next(item for item in flow.lifecycle.work_status(flow.incident_id) if item["current"])


def ack(flow, assignment_id=None, **kw):
    return flow.lifecycle.acknowledge_work(flow.incident_id, assignment_id=assignment_id or current(flow)["assignment_id"],
                                           expected_revision=kw.pop("expected_revision", revision(flow)),
                                           actor=kw.pop("actor", TECHNICIAN), **kw)


def report(flow, assignment_id=None, **kw):
    values = dict(result="COMPLETED", summary="Overhaul performed", performed_at=utcnow(), asset_intervened=True)
    values.update(kw)
    return flow.lifecycle.report_work(flow.incident_id, assignment_id=assignment_id or current(flow)["assignment_id"],
                                      expected_revision=values.pop("expected_revision", revision(flow)),
                                      actor=values.pop("actor", TECHNICIAN), **values)


def decline(flow, assignment_id=None, **kw):
    return flow.lifecycle.decline_work(flow.incident_id, assignment_id=assignment_id or current(flow)["assignment_id"],
                                       expected_revision=kw.pop("expected_revision", revision(flow)),
                                       actor=kw.pop("actor", TECHNICIAN), reason=kw.pop("reason", "Asset inaccessible"),
                                       **kw)


def reassign(flow, assignment_id=None, **kw):
    return flow.lifecycle.reassign_work(flow.incident_id, assignment_id=assignment_id or current(flow)["assignment_id"],
                                        expected_revision=kw.pop("expected_revision", revision(flow)),
                                        actor=kw.pop("actor", DISPATCHER),
                                        rationale=kw.pop("rationale", "second crew available"), **kw)


# ---------------------------------------------------------------- transitions
def test_dispatch_assigns_work_that_is_current_and_carries_instructions(flow):
    _, receipt = dispatched(flow)
    state = current(flow)
    assert state["state"] == "ASSIGNED" and state["receipt_id"] == receipt.id and state["superseded_by"] is None
    assert state["instructions"] and state["eligible"] is None and state["assignee"]["kind"] == "WORKER"


def test_decline_records_a_reason_and_is_only_possible_before_acknowledgement(flow):
    dispatched(flow)
    with pytest.raises(LifecycleRefused, match="reason"):
        decline(flow, reason="  ")
    decline(flow)
    state = current(flow)
    assert (state["state"], state["decline_reason"], state["declined_by"]["id"]) == ("DECLINED", "Asset inaccessible", "tech-7")
    assert events(flow, "WORK_DECLINED")[-1].payload["reason"] == "Asset inaccessible"
    with pytest.raises(LifecycleRefused, match="already DECLINED"):
        ack(flow)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING  # a declined request is not a phase change


def test_an_acknowledged_assignment_cannot_be_declined(flow):
    dispatched(flow)
    ack(flow)
    with pytest.raises(LifecycleRefused, match="report NOT_PERFORMED"):
        decline(flow)


@pytest.mark.parametrize("fields, message", [
    (dict(asset_intervened=None), "must state asset_intervened"),
    (dict(performed_at=None), "requires performed_at"),
    (dict(performed_at=utcnow() - timedelta(days=2)), "precedes the work assignment"),
    (dict(performed_at=utcnow() + timedelta(hours=1)), "in the future"),
    (dict(completed_instructions=(0,)), "must cover every assignment instruction"),
    (dict(completed_instructions=(0, 0, 1)), "distinct indices"),
    (dict(completed_instructions=(99,)), "distinct indices"),
    (dict(result="PARTIAL", completed_instructions=(0,)), "remaining work in findings"),
    (dict(result="PARTIAL", findings=("seal not replaced",)), "name the completed instructions"),
    (dict(result="NOT_PERFORMED", performed_at=None, asset_intervened=True), "contradicts asset_intervened"),
    (dict(result="NOT_PERFORMED", asset_intervened=None), "cannot carry a performed_at"),
    (dict(result="NOT_PERFORMED", performed_at=None, asset_intervened=None, completed_instructions=(0,)),
     "cannot list completed instructions"),
])
def test_malformed_or_contradictory_reports_are_refused_and_write_nothing(flow, fields, message):
    dispatched(flow)
    ack(flow)
    before = revision(flow)
    with pytest.raises(LifecycleRefused, match=message):
        report(flow, **fields)
    assert revision(flow) == before and not flow.kinds(m.WorkReport)
    assert current(flow)["state"] == "ACKNOWLEDGED"


def test_eligibility_is_recorded_with_the_report_and_survives_restart(flow):
    dispatched(flow)
    ack(flow)
    work = report(flow)
    payload = events(flow, "WORK_REPORTED")[-1].payload
    assert payload["eligible"] is True and payload["eligibility_policy"] == lc.WORK_ELIGIBILITY_POLICY
    assert work.completed_instructions == tuple(range(len(current(flow)["instructions"])))
    state = next(iter(LifecycleService(flow.repo).work_status(flow.incident_id)))
    assert (state["state"], state["eligible"], state["reported_at"]) == ("REPORTED", True, work.created_at.isoformat())
    assert state["performed_at_claimed"] == work.performed_at.isoformat()


@pytest.mark.parametrize("fields, eligible, reasons", [
    (dict(result="PARTIAL", completed_instructions=(0,), findings=("realignment pending",)), True, []),
    (dict(asset_intervened=False), False, ["NO_PHYSICAL_INTERVENTION"]),
    (dict(result="NOT_PERFORMED", performed_at=None, asset_intervened=None, findings=("no access",)), False,
     ["NOT_PERFORMED"]),
])
def test_well_formed_reports_are_recorded_truthfully_with_their_eligibility(flow, fields, eligible, reasons):
    dispatched(flow)
    ack(flow)
    report(flow, **fields)
    state = current(flow)
    assert (state["state"], state["eligible"], state["eligibility_reasons"]) == ("REPORTED", eligible, reasons)


def test_only_one_terminal_report_per_assignment(flow):
    dispatched(flow)
    ack(flow)
    first = report(flow, asset_intervened=False)
    with pytest.raises(LifecycleRefused, match="already REPORTED"):
        report(flow)
    # Defence in depth: the unique index refuses a second report written around the command.
    second = first.model_copy(update={"id": new_id(), "asset_intervened": True})
    with pytest.raises(DuplicateRecord):
        with flow.repo._write() as conn:
            flow.repo._store_artifact(conn, flow.repo._fetch(conn, flow.incident_id), second, historical_input=True)
    assert len(flow.kinds(m.WorkReport)) == 1


def test_pre_f1_2_reports_never_qualify():
    created = utcnow()
    assignment = m.WorkAssignment(
        id="a", incident_id="i", created_at=created, equipment_ids=(ASSET,), intervention_id="iv", intervention_hash="h",
        step_id="s", execution_claim_key="k", receipt_id="r", instructions=("Isolate", "Overhaul"),
        assignee=m.WorkAssignee(kind="WORKER", reference="TECH-201", reference_system="roster"))
    legacy = m.WorkReport(id="w", incident_id="i", created_at=created + timedelta(minutes=5), equipment_ids=(ASSET,),
                          assignment_id="a", result="COMPLETED", summary="done", performed_at=created + timedelta(minutes=4),
                          actor=TECHNICIAN, provenance="OBSERVED")
    assert work_eligibility(assignment, legacy) == (False, ("ATTESTATION_MISSING", "INCOMPLETE_COVERAGE"))
    attested = legacy.model_copy(update={"asset_intervened": True, "completed_instructions": (0, 1)})
    assert work_eligibility(assignment, attested) == (True, ())


# ---------------------------------------------------------------- reassignment
def test_reassignment_after_decline_keeps_history_and_issues_a_current_assignment(flow):
    _, receipt = dispatched(flow)
    first = current(flow)["assignment_id"]
    decline(flow)
    second = reassign(flow, assignee_reference="TECH-201")
    states = {item["assignment_id"]: item for item in flow.lifecycle.work_status(flow.incident_id)}
    assert states[first]["state"] == "DECLINED" and states[first]["superseded_by"] == second.id and not states[first]["current"]
    assert states[second.id]["current"] and states[second.id]["supersedes_assignment_id"] == first
    assert second.receipt_id == receipt.id and second.assignee.reference == "TECH-201"
    reassigned = events(flow, "WORK_REASSIGNED")[-1].payload
    assert (reassigned["from_assignment_id"], reassigned["assignment_id"], reassigned["previous_state"]) == (
        first, second.id, "DECLINED")
    assert events(flow, "LIFECYCLE_COMMAND")[-1].payload["command"] == "reassign_work"
    assert events(flow, "WORK_ASSIGNED")[-1].payload["supersedes_assignment_id"] == first
    # The superseded assignment can no longer be acted on; the new one can.
    with pytest.raises(LifecycleRefused, match="superseded by"):
        ack(flow, assignment_id=first)
    ack(flow, assignment_id=second.id)


def test_reassignment_after_an_ineligible_report(flow):
    dispatched(flow)
    ack(flow)
    report(flow, result="NOT_PERFORMED", performed_at=None, asset_intervened=None, findings=("lockout not granted",))
    reassign(flow)
    assert current(flow)["state"] == "ASSIGNED"


@pytest.mark.parametrize("step", ["pending", "acknowledged", "eligible"])
def test_reassignment_is_refused_while_work_is_pending_or_qualified(flow, step):
    dispatched(flow)
    if step != "pending":
        ack(flow)
    if step == "eligible":
        report(flow)
    with pytest.raises(LifecycleRefused, match="only a declined assignment"):
        reassign(flow)


def test_reassignment_requires_a_rationale_and_a_qualified_assignee(flow):
    dispatched(flow)
    decline(flow)
    with pytest.raises(LifecycleRefused, match="rationale"):
        reassign(flow, rationale=" ")
    with pytest.raises(LifecycleRefused, match="cannot take this work"):
        reassign(flow, assignee_reference="NO-SUCH-TECH")
    assert len(flow.kinds(m.WorkAssignment)) == 1


# ----------------------------------------------------------------- idempotency
def test_a_keyed_retry_is_answered_from_the_durable_record(flow):
    dispatched(flow)
    stale = revision(flow)
    ack(flow, request_key="ack-1")
    after = revision(flow)
    assert ack(flow, request_key="ack-1", expected_revision=stale).revision == after  # retry with the old revision
    assert len(events(flow, "WORK_ACKNOWLEDGED")) == 1 and revision(flow) == after
    performed = utcnow()
    first = report(flow, request_key="report-1", performed_at=performed)
    again = report(flow, request_key="report-1", performed_at=performed, expected_revision=after)
    assert again == first and len(flow.kinds(m.WorkReport)) == 1
    assert flow.lifecycle.request_recorded(flow.incident_id, "report-1")


def test_a_reused_key_with_different_content_is_refused(flow):
    dispatched(flow)
    ack(flow, request_key="k-1")
    with pytest.raises(LifecycleRefused, match="different work request") as refused:
        ack(flow, request_key="k-1", note="different")
    assert refused.value.disposition == "CONFLICT"
    with pytest.raises(LifecycleRefused, match="different work request"):
        report(flow, request_key="k-1")  # keys are scoped to the case, across work commands


def test_stale_revision_without_a_key_is_refused(flow):
    dispatched(flow)
    stale = revision(flow)
    ack(flow)
    with pytest.raises(StaleRevision):
        report(flow, expected_revision=stale)


def test_concurrent_reports_record_exactly_one(flow):
    dispatched(flow)
    ack(flow)
    assignment_id, expected = current(flow)["assignment_id"], revision(flow)
    barrier, errors = threading.Barrier(2), []

    def submit(asset_intervened):
        barrier.wait()
        try:
            LifecycleService(flow.repo).report_work(
                flow.incident_id, assignment_id=assignment_id, expected_revision=expected, actor=TECHNICIAN,
                result="COMPLETED", summary="done", performed_at=utcnow(), asset_intervened=asset_intervened)
        except (StaleRevision, LifecycleRefused, DuplicateRecord) as exc:
            errors.append(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(submit, (True, False)))
    assert len(flow.kinds(m.WorkReport)) == 1 and len(errors) == 1


# --------------------------------------------------------- guards and commands
def test_work_commands_require_an_observing_case_and_an_admissible_actor(flow):
    dispatched(flow)
    with pytest.raises(ActorRefused):
        ack(flow, actor=m.ActorRef(kind="SANDBOX", id="s"))  # sandbox identity on an unspecified-environment case
    decline(flow)
    flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=DISPATCHER, rationale="re-plan")
    with pytest.raises(LifecycleRefused, match="require OBSERVING"):
        reassign(flow)


def test_resume_from_observing_is_narrow_and_records_the_abandoned_work(flow):
    _, receipt = dispatched(flow)
    with pytest.raises(LifecycleRefused, match="resume from OBSERVING is allowed only"):
        flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=DISPATCHER, rationale="x")
    ack(flow)
    with pytest.raises(LifecycleRefused, match="resume from OBSERVING is allowed only"):
        flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=DISPATCHER, rationale="x")
    report(flow, result="NOT_PERFORMED", performed_at=None, asset_intervened=None, findings=("wrong part delivered",))
    incident = flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=DISPATCHER,
                                     rationale="re-plan with the correct part")
    assert incident.phase == m.IncidentPhase.INVESTIGATING and incident.current_intervention_id is None
    work = events(flow, "LIFECYCLE_COMMAND")[-1].payload["work"]
    assert work["receipt_id"] == receipt.id and work["external_refs"] == receipt.external_ids
    assert "not recalled" in work["note"] and work["assignments"][0]["state"] == "REPORTED"


def test_resume_is_refused_once_eligible_work_was_reported(flow):
    dispatched(flow)
    ack(flow)
    report(flow)
    with pytest.raises(LifecycleRefused, match="resume from OBSERVING is allowed only"):
        flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=DISPATCHER, rationale="x")


def test_cancel_while_work_is_open_records_the_work_orders_that_are_not_recalled(flow):
    _, receipt = dispatched(flow)
    ack(flow)
    flow.lifecycle.cancel(flow.incident_id, expected_revision=revision(flow), actor=DISPATCHER, rationale="asset retired")
    payload = events(flow, "INCIDENT_CANCELLED")[-1].payload
    assert payload["work"]["assignments"][0]["state"] == "ACKNOWLEDGED"
    assert payload["work"]["external_refs"] == receipt.external_ids and "not recalled" in payload["work"]["note"]
    with pytest.raises(InactiveIncident):
        report(flow)


def test_escalation_records_the_open_work(flow):
    dispatched(flow)
    flow.lifecycle.escalate(flow.incident_id, expected_revision=revision(flow), actor=DISPATCHER, rationale="safety hold")
    assert events(flow, "LIFECYCLE_COMMAND")[-1].payload["work"]["assignments"][0]["state"] == "ASSIGNED"


def test_overdue_flags_are_derived_and_never_transition(flow):
    dispatched(flow)
    state = current(flow)
    assigned = state["assigned_at"]
    view = flow.lifecycle.projection(flow.incident_id, now=utcnow() + lc.WORK_ACK_GRACE + timedelta(minutes=1))
    work = view["work"][0]
    assert work["ack_overdue"] is True and work["report_overdue"] is False and work["assigned_at"] == assigned
    ack(flow)
    window_end = flow.lifecycle.work_status(flow.incident_id)[0]["window_end"]
    late = flow.lifecycle.projection(flow.incident_id, now=utcnow() + timedelta(days=3))["work"][0]
    assert window_end and late["report_overdue"] is True and late["ack_overdue"] is False
    assert flow.incident().phase == m.IncidentPhase.OBSERVING


def test_stalled_verification_is_a_derived_flag_without_transition(flow):
    dispatched(flow)
    ack(flow)
    work = report(flow)
    assert flow.lifecycle.verify_outcome(flow.incident_id).disposition == "OBSERVING"  # plan frozen, no scores yet
    fresh = flow.lifecycle.projection(flow.incident_id, now=work.created_at + timedelta(seconds=30))["verification"]
    assert fresh["state"] == "COLLECTING" and fresh["stalled"] is False
    late = flow.lifecycle.projection(flow.incident_id, now=work.created_at + timedelta(minutes=10))["verification"]
    assert late["stalled"] is True and late["state"] == "COLLECTING"
    assert flow.incident().phase == m.IncidentPhase.OBSERVING


def test_a_report_racing_the_verifier_freezes_exactly_one_work_bound_plan(flow):
    dispatched(flow)
    ack(flow)
    work = report(flow)
    barrier, results = threading.Barrier(3), []

    def verify(_):
        barrier.wait()
        results.append(LifecycleService(flow.repo).verify_outcome(flow.incident_id))
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(verify, range(3)))
    plans = flow.kinds(m.ObservationPlan)
    assert len(plans) == 1 and plans[0].work_report_id == work.id
    assert all(item.disposition in ("OBSERVING", "RETRY") for item in results)
