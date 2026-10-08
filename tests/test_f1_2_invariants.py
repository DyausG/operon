"""F1.2 invariants: dispatch != work performed != plant response != recovery != verified recovery.

These tests fix the target behaviour of F1.2 (design/v2/12-f1.2-plant-work-verification-plan.md):

* dispatch never changes the (simulated) plant;
* verification waits for an eligible work report and observes only after it;
* a restart preserves plant condition, so it can never create an artificial recovery;
* business value is attributed only to a verified outcome;
* pre-version-2 cases are never closed from their dispatch receipt.

Real repository transactions, real promotion lineage and the real verifier throughout.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from core import db
from core.agents.runtime import StrandsRuntime
from core.reliability import lifecycle as lc
from core.reliability import models as m
from core.reliability import outcome as oc
from core.reliability.lifecycle import LifecycleRefused, LifecycleService
from core.reliability.repository import utcnow
from tests.test_engine_lifecycle import ASSET, Bridge, make_engine, recorded_broadcasts, scripted_supervisor, tick
from tests.test_outcome import HEALTHY, observing, outcomes, plans, post, verify, write_scores
from tests.test_promotion import revision
from tests.test_reliability_lifecycle import Flow
from tests.test_strands_agents import ScriptedModel, settings

# M0: target behaviour, expected to fail until the milestones land (strict: an unexpected pass fails the run).
pytestmark = pytest.mark.xfail(strict=True, reason="F1.2 target behaviour, not implemented yet (M0)")

TECHNICIAN = m.ActorRef(kind="DECLARED", id="tech-7", role="technician")
ENGINEER = m.ActorRef(kind="DECLARED", id="engineer-1", role="reliability_engineer")


@pytest.fixture
def flow(seeded_db):
    return Flow()


def assignment_of(flow):
    [assignment] = [item for item in flow.kinds(m.WorkAssignment)]
    return assignment


def complete_work(flow, *, result="COMPLETED", later=timedelta(0), monkeypatch=None, **fields):
    """Acknowledge and report the current assignment through the lifecycle commands."""
    assignment = assignment_of(flow)
    flow.lifecycle.acknowledge_work(flow.incident_id, assignment_id=assignment.id, expected_revision=revision(flow),
                                    actor=TECHNICIAN)
    if monkeypatch is not None and later:
        shifted = utcnow() + later
        monkeypatch.setattr(lc, "utcnow", lambda: shifted)
    values = dict(result=result, summary="Bearing replaced and shaft realigned", performed_at=lc.utcnow(),
                  asset_intervened=True)
    values.update(fields)
    return flow.lifecycle.report_work(flow.incident_id, assignment_id=assignment.id, expected_revision=revision(flow),
                                      actor=TECHNICIAN, **values)


def legacy_v1_plan(flow, receipt):
    """Persist an observation plan exactly as the pre-F1.2 verifier did (receipt-bound, operon-outcome-1)."""
    verifier = oc.OutcomeVerifier(flow.lifecycle)
    with flow.repo._write() as conn:
        incident = flow.repo._fetch(conn, flow.incident_id)
        lineage = verifier._executed(conn, incident)
        confirmed_at = receipt.completed_at
        baseline = verifier._baseline(conn, incident, lineage, confirmed_at)
        plan = m.ObservationPlan(
            id="legacy-plan-v1", incident_id=incident.id, created_at=utcnow(), equipment_ids=(baseline["asset_id"],),
            asset_id=baseline["asset_id"], diagnosis_id=lineage.diagnosis.id,
            diagnosis_promotion_id=lineage.diagnosis_record.id, intervention_id=lineage.intervention.id,
            intervention_hash=lineage.intervention_hash, promotion_id=lineage.record.id,
            approval_requirement_id=lineage.requirement.id, approval_decision_ids=lineage.decision_ids,
            execution_claim_key=lineage.claim.idempotency_key, receipt_id=receipt.id,
            receipt_operation_key=receipt.operation_key, receipt_attempt=receipt.attempt, confirmed_at=confirmed_at,
            observation_start=oc.observation_start(confirmed_at), baseline_signal_evidence_id=baseline["signal_evidence"].id,
            baseline_evidence_ids=baseline["evidence_ids"], baseline_metrics=baseline["metrics"],
            diagnosed_failure_mode_code=lineage.diagnosis.failure_mode_code, policy_version="operon-outcome-1",
            policy_parameters=oc.policy_parameters())
        flow.lifecycle._checkpoint(conn, incident, [plan], events=[("OBSERVATION_PLANNED", {
            "plan_id": plan.id, "receipt_id": receipt.id, "policy_version": "operon-outcome-1"})])
    return plan


# ------------------------------------------------------------ lifecycle level
def test_verification_waits_for_an_eligible_work_report(flow):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)  # the plant looks healthy, but nobody reported any work
    result = verify(flow)
    assert result.disposition == "AWAITING_WORK" and result.outcome_id is None
    assert not plans(flow) and not outcomes(flow)
    assert flow.incident().phase == m.IncidentPhase.OBSERVING


def test_observation_starts_only_after_the_server_recorded_report(flow, monkeypatch):
    _, receipt = observing(flow)
    post(flow, receipt, HEALTHY)  # healthy scores stamped before the report can never count
    report = complete_work(flow, later=timedelta(minutes=10), monkeypatch=monkeypatch)
    monkeypatch.undo()
    first = verify(flow)
    assert first.disposition == "OBSERVING" and first.post_score_count == 0
    [plan] = plans(flow)
    assert plan.policy_version == "operon-outcome-2" and plan.work_report_id == report.id
    assert plan.observation_start == oc.observation_start(report.created_at) > report.created_at >= receipt.completed_at
    write_scores(flow.repo.path, ASSET, HEALTHY, start=plan.observation_start + timedelta(seconds=1))
    result = verify(flow)
    assert result.disposition == "CLOSED"
    [outcome] = outcomes(flow)
    assert outcome.work_report_id == report.id and outcome.observation_start == plan.observation_start


def test_a_completed_report_with_unhealthy_telemetry_is_not_recovery(flow):
    _, receipt = observing(flow)
    report = complete_work(flow)
    assert verify(flow).disposition == "OBSERVING"
    [plan] = plans(flow)
    write_scores(flow.repo.path, ASSET, (0.91,) * 12, start=plan.observation_start + timedelta(seconds=1))
    result = verify(flow)
    assert result.result == "NOT_RECOVERED" and flow.incident().phase == m.IncidentPhase.INVESTIGATING
    assert outcomes(flow)[0].work_report_id == report.id


def test_pre_version_two_receipt_bound_plan_is_blocked_never_closed(flow):
    _, receipt = observing(flow)
    legacy = legacy_v1_plan(flow, receipt)
    post(flow, receipt, HEALTHY)
    for service in (flow.lifecycle, LifecycleService(flow.repo)):  # identical after a restart
        result = service.verify_outcome(flow.incident_id)
        assert result.disposition == "BLOCKED" and result.outcome_id is None
        view = service.projection(flow.incident_id)
        assert view["verification"]["state"] == "BLOCKED"
        assert view["verification"]["code"] == "LEGACY_RECEIPT_BOUND_PLAN"
        assert view["verification"]["plan_id"] == legacy.id and view["reconciliation_required"] is True
    assert not outcomes(flow) and flow.incident().phase == m.IncidentPhase.OBSERVING
    with pytest.raises(LifecycleRefused, match="operon-outcome-1"):
        complete_work(flow)
    flow.lifecycle.resume(flow.incident_id, expected_revision=revision(flow), actor=ENGINEER,
                          rationale="re-plan under work-evidence verification")
    incident = flow.incident()
    assert incident.phase == m.IncidentPhase.INVESTIGATING and incident.current_intervention_id is None


# --------------------------------------------------------------- engine level
async def to_approval(monkeypatch, clock, *, response="RECOVERS"):
    holder = {}
    scripted_supervisor(monkeypatch, holder)
    engine = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    engine._clock = lambda: clock["now"]
    engine.sim.assets[ASSET].prog = 0.9
    engine.sim.assets[ASSET].profile.intervention_response = response
    await engine._advance()
    bridge = holder["bridge"] = Bridge(engine, ASSET)
    await engine.drain()
    bridge.confirm()
    await engine.stop()
    engine._progress_lifecycle()
    await engine.drain()
    bridge.resources()
    assert (await engine.plan(bridge.incident_id, expected_revision=bridge.revision(), **bridge.binding_fields()))["ok"]
    intent = {key: engine.alerts[ASSET]["lifecycle"][key]
              for key in ("requirement_id", "intervention_id", "intervention_hash", "context_revision")}
    return engine, bridge, intent


async def report_via_engine(engine, bridge, *, result="COMPLETED"):
    [work] = engine.lifecycle.work_status(bridge.incident_id)
    ack = await engine.lifecycle_command(bridge.incident_id, "acknowledge_work", assignment_id=work["assignment_id"],
                                         expected_revision=bridge.revision(), actor=TECHNICIAN)
    assert ack["ok"], ack
    response = await engine.lifecycle_command(
        bridge.incident_id, "report_work", assignment_id=work["assignment_id"], expected_revision=bridge.revision(),
        actor=TECHNICIAN, result=result, summary="Overhaul performed", performed_at=utcnow(), asset_intervened=True)
    assert response["ok"], response
    return response


async def test_dispatch_never_changes_the_simulated_plant(seeded_db, monkeypatch):
    clock = {"now": utcnow()}
    engine, bridge, intent = await to_approval(monkeypatch, clock)
    before = (engine.sim.assets[ASSET].mode, engine.sim.assets[ASSET].prog)
    messages = recorded_broadcasts(engine)
    result = await engine.approve(ASSET, intent)
    assert result["ok"] and result["phase"] == "OBSERVING"
    assert (engine.sim.assets[ASSET].mode, engine.sim.assets[ASSET].prog) == before == ("arrested", before[1])
    # One compatible `resolved` (legacy consumers) and one canonical lifecycle `alert` for the dispatch.
    assert [msg["type"] for msg in messages].count("resolved") == 1
    assert any(msg["type"] == "alert" and msg.get("phase") == "dispatched" for msg in messages)
    # Dispatch is not value: nothing is prevented or recovered until an outcome is verified.
    business = engine._business_summary()
    assert business["events_prevented"] == 0 and business["recovered_value"] == 0
    assert business["events_dispatched"] == 1 and business["events_awaiting_verification"] == 1


async def test_restart_never_creates_an_artificial_recovery(seeded_db, monkeypatch):
    clock = {"now": utcnow()}
    engine, bridge, intent = await to_approval(monkeypatch, clock, response="PERSISTS")
    assert (await engine.approve(ASSET, intent))["ok"]
    await report_via_engine(engine, bridge)
    held = engine.sim.assets[ASSET]
    assert held.mode == "unresponsive" and held.prog > 0.9
    restarted = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    state = restarted.sim.assets[ASSET]
    assert (state.mode, state.prog, state.profile.intervention_response) == (held.mode, held.prog, "PERSISTS")


async def test_restart_preserves_ordinary_assets_and_open_cases(seeded_db, monkeypatch):
    clock = {"now": utcnow()}
    engine = make_engine(monkeypatch, failure_prob=0.05)  # below admission: ordinary fleet only
    engine._clock = lambda: clock["now"]
    await engine.stop()
    await tick(engine, clock, 6)
    trajectory = {eid: (state.mode, state.prog, state.tick) for eid, state in engine.sim.assets.items()}
    assert any(prog > 0 for _, prog, _ in trajectory.values())
    restarted = make_engine(monkeypatch, failure_prob=0.05)
    assert {eid: (state.mode, state.prog, state.tick) for eid, state in restarted.sim.assets.items()} == trajectory


async def test_awaiting_work_case_is_held_across_restart(seeded_db, monkeypatch):
    clock = {"now": utcnow()}
    engine, bridge, intent = await to_approval(monkeypatch, clock)
    assert (await engine.approve(ASSET, intent))["ok"]
    held = (engine.sim.assets[ASSET].mode, engine.sim.assets[ASSET].prog)
    restarted = make_engine(monkeypatch, runtime=StrandsRuntime(settings(), model=ScriptedModel()))
    assert (restarted.sim.assets[ASSET].mode, restarted.sim.assets[ASSET].prog) == held
    assert restarted.alerts[ASSET]["lifecycle"]["verification"]["state"] == "AWAITING_WORK"
