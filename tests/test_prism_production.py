"""Stage 2: the production PRISM Slow Path over Operon's real reasoning path (no model, no network).

Every test drives the real ``OperonSlowPathAdapter`` (claim -> compute -> fence -> apply) over a real
incident in the engine's database. The only injected piece is the ``ReasoningBackend`` at the exact
seam ``PromotionService.run_supervisor`` uses, so the fence/apply path exercised here is the one a
live provider goes through.

Invariant under test: once revision N is superseded by N+1, nothing produced for N (real supervisor
output, late/non-cooperative provider results, failures, restarts) may mutate canonical PRISM state
or incident state.
"""
from __future__ import annotations

import asyncio
import json
import random
import threading
import time

from fastapi.testclient import TestClient

from core import db
from core.prism import RunStatus
from core.prism.fencing import StaleRevisionError
from core.prism.models import SlowPathResult
from core.prism.operon import OperonSlowPathAdapter, compose_question
from core.prism.slow_path import DeterministicSlowPathAdapter, adapter_from_environment
from core.prism.testing import ControlledAdapter, FakeReasoningBackend
from core.reliability import models as m
from tests.test_engine_lifecycle import make_engine
from tests.test_prism_engine import wait_for

INVESTIGATE = "Investigate the compressor temperature anomaly."
CORRECTION = "Correction: prioritize the vibration spike and ignore the temperature hypothesis for now."


async def production_engine(monkeypatch, backend, adapter_class=OperonSlowPathAdapter, **options):
    engine = make_engine(monkeypatch)
    adapter = adapter_class(**{**engine._prism_services(), "backend_factory": lambda: backend}, **options)
    engine.prism.coordinator.adapter = engine.prism.adapter = adapter
    await engine._advance()
    assert await wait_for(lambda: bool(engine.incidents))
    incident = engine.coordinator.repository.fetch_incident(next(iter(engine.incidents.values())).id)
    assert incident.phase == m.IncidentPhase.INVESTIGATING
    return engine, adapter, incident


def reports_for(engine, incident_id):
    return [a for a in engine.coordinator.repository.list_artifacts(incident_id) if isinstance(a, m.SupervisorReport)]


def effects(engine, session_id, kind=None):
    return [e for e in engine.prism.repository.list_effects(session_id) if kind is None or e.kind == kind]


def runs_by_revision(engine, session_id):
    return {(r.revision, r.attempt): r for r in engine.prism.repository.list_runs(session_id)}


# ---------------------------------------------------------------------------------------------------
# 1. production adapter wiring
# ---------------------------------------------------------------------------------------------------
async def test_production_adapter_invokes_real_reasoning_seam_with_instruction_identity_and_role(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(auto_release=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend)
    before = incident.revision
    session = await engine.prism.create_session(incident_id=incident.id)
    sid = session["session_id"]
    ack = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert ack["fast_path"]["status"] == "accepted" and ack["slow_path"]["role"] == "slow"
    assert await engine.prism.wait_idle(10)
    # The real seam received the authoritative incident, the operator instruction and the run identity.
    assert len(backend.contexts) == 1
    context, snapshot = backend.contexts[0], backend.snapshots[0]
    assert context.incident_id == incident.id and context.run_purpose == "DIAGNOSIS"
    assert INVESTIGATE in context.question and "revision 1" in context.question
    assert snapshot.run_id == context.run_id and snapshot.runtime_identity == backend.identity()
    assert json.loads(json.dumps(snapshot.context_payload))["question"] == context.question
    # The PRISM run carries provider role ``slow`` and the backend's truthful (INJECTED) identity.
    run = engine.prism.repository.get_run(ack["slow_path"]["run_id"])
    assert run.status == RunStatus.COMPLETED and run.role == "slow"
    assert run.runtime["adapter"] == "operon" and run.runtime["role"] == "slow"
    assert run.runtime["provider"] == "none" and run.runtime["live_model"] is False and run.runtime["provenance"] == "INJECTED"
    assert run.result["provenance"] == "INJECTED"
    request = run.result["details"]["reasoning_request"]
    assert request["revision"] == 1 and request["incident_id"] == incident.id and request["role"] == "slow"
    assert request["context_policy"] == "current_instruction+last_canonical_summary"
    candidate = run.result["details"]["candidate"]
    assert candidate["operon_run_id"] == snapshot.run_id and candidate["disposition"] == "ADVISORY_CONCLUSION"
    assert [s["role"] for s in candidate["specialists"]] == ["diagnostic", "critic", "planner"]
    assert candidate["recommended_hypothesis"]["mechanism"]
    # Applied exactly once, inside the fence: one SupervisorReport, one apply effect, settlement recorded.
    applied = run.result["details"]["applied"]
    reports = reports_for(engine, incident.id)
    assert [r.run_id for r in reports] == [snapshot.run_id] and applied["report_id"] == reports[0].id
    assert reports[0].stale_reasons == () and reports[0].completion == "MODEL_COMPLETED"
    assert applied["settlement"]["disposition"] == "NEEDS_EVIDENCE"
    after = engine.coordinator.repository.fetch_incident(incident.id)
    assert after.phase == m.IncidentPhase.AWAITING_EVIDENCE and after.revision > before
    assert after.active_run_id == snapshot.run_id and after.current_diagnosis_id is None
    assert [e.kind for e in effects(engine, sid)] == ["operon_run_claim", "canonical_apply"]
    state = engine.prism.repository.get_session(sid)
    assert state.canonical_revision == 1 and state.canonical_run_id == run.run_id
    stages = [e.payload.get("stage") for e in engine.prism.repository.list_events(sid) if e.event_type == "slow_path_progress"]
    assert stages[:2] == ["reasoning_context_prepared", "run_claimed"]
    assert stages[-3:] == ["candidate_ready", "candidate_fenced", "candidate_applied"]
    assert "supervisor_started" in stages and "specialist_completed" in stages
    view = engine.prism.session_view(sid)
    assert view["reasoning"]["instruction"] == INVESTIGATE and view["reasoning"]["candidate"]["disposition"] == "ADVISORY_CONCLUSION"
    assert view["reasoning"]["applied"]["settlement"]["incident_phase"] == "AWAITING_EVIDENCE"
    await engine.prism.shutdown()


# ---------------------------------------------------------------------------------------------------
# 2. instruction correction enters the new revision's reasoning request; context stays bounded
# ---------------------------------------------------------------------------------------------------
def test_reasoning_question_is_bounded_and_never_carries_superseded_instructions():
    question, meta = compose_question("  Investigate   the anomaly " + "x" * 5000, 3,
                                      {"canonical_revision": 2, "canonical_summary": "y" * 5000})
    assert len(question) <= 2000 and question.startswith("Operator instruction (PRISM revision 3, authoritative): Investigate the anomaly")
    assert meta["prior_canonical_revision"] == 2 and meta["instruction_chars"] == 1400
    assert "Prior canonical context (revision 2" in question
    question, meta = compose_question(CORRECTION, 2, {"canonical_revision": None, "canonical_summary": None})
    assert meta["prior_canonical_revision"] is None and "Prior canonical" not in question


async def test_correction_becomes_the_authoritative_instruction_of_revision_two(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(block=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await wait_for(lambda: len(backend.contexts) == 1)
    assert INVESTIGATE in backend.contexts[0].question
    two = await engine.prism.submit_message(sid, content=CORRECTION)
    assert two["revision"] == 2 and two["fast_path"]["status"] == "accepted_superseding"
    assert await wait_for(lambda: len(backend.contexts) == 2)
    request = backend.contexts[1]
    assert CORRECTION in request.question and INVESTIGATE not in request.question
    assert "revision 2" in request.question and request.incident_id == incident.id
    assert backend.snapshots[1].run_id != backend.snapshots[0].run_id
    # Revision 1's real run was cancelled at the seam (cooperative adapter): no late result exists.
    assert backend.cancelled == [backend.contexts[0].run_id]
    backend.release.set()
    assert await engine.prism.wait_idle(10)
    runs = runs_by_revision(engine, sid)
    assert runs[(1, 1)].status == RunStatus.CANCELLED and runs[(1, 1)].stale and runs[(1, 1)].result is None
    assert runs[(2, 1)].status == RunStatus.COMPLETED
    state = engine.prism.repository.get_session(sid)
    assert state.canonical_revision == 2 and CORRECTION[:40] in state.canonical["result"]["summary"]
    assert state.canonical["result"]["details"]["reasoning_request"]["revision"] == 2
    reports = reports_for(engine, incident.id)
    assert [r.run_id for r in reports] == [backend.snapshots[1].run_id]   # revision 1 left no report
    after = engine.coordinator.repository.fetch_incident(incident.id)
    assert after.active_run_id == backend.snapshots[1].run_id
    await engine.prism.shutdown()


async def test_prior_canonical_summary_is_carried_but_the_new_instruction_overrides(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(auto_release=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await engine.prism.wait_idle(10)
    await engine.prism.submit_message(sid, content=CORRECTION)
    assert await engine.prism.wait_idle(10)
    second = backend.contexts[1].question
    assert second.startswith(f"Operator instruction (PRISM revision 2, authoritative): {CORRECTION}")
    assert "Prior canonical context (revision 1" in second
    # Exactly one authoritative instruction; the old one survives only inside the prior canonical summary.
    assert second.index(INVESTIGATE) > second.index("Prior canonical context")
    state = engine.prism.repository.get_session(sid)
    assert state.canonical_revision == 2
    assert state.canonical["result"]["details"]["reasoning_request"]["prior_canonical_revision"] == 1
    await engine.prism.shutdown()


# ---------------------------------------------------------------------------------------------------
# 3 / 4. stale real candidate, cooperative and non-cooperative provider
# ---------------------------------------------------------------------------------------------------
async def _stale_candidate_scenario(monkeypatch, *, cooperative: bool):
    backend = FakeReasoningBackend(block=True, ignore_cancellation=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend, cooperative=cooperative)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await wait_for(lambda: len(backend.contexts) == 1)
    claimed = engine.coordinator.repository.fetch_incident(incident.id)
    assert claimed.active_run_id == backend.snapshots[0].run_id
    two = await engine.prism.submit_message(sid, content=CORRECTION)
    assert two["superseded"] == {"revision": 1, "run_ids": [one["slow_path"]["run_id"]]}
    assert engine.prism.repository.get_run(one["slow_path"]["run_id"]).status == RunStatus.CANCELLING
    assert await wait_for(lambda: len(backend.contexts) == 2)
    assert CORRECTION in backend.contexts[1].question
    backend.release.set()          # both real runs now return: revision 2 (current) and revision 1 (late)
    assert await engine.prism.wait_idle(10)
    runs = runs_by_revision(engine, sid)
    first, second = runs[(1, 1)], runs[(2, 1)]
    assert first.status == RunStatus.STALE and first.stale
    assert first.result["details"]["candidate"]["operon_run_id"] == backend.snapshots[0].run_id
    assert first.result["details"]["candidate"]["disposition"] == "ADVISORY_CONCLUSION"   # a valid diagnosis candidate
    assert "applied" not in first.result["details"]
    assert second.status == RunStatus.COMPLETED and "applied" in second.result["details"]
    state = engine.prism.repository.get_session(sid)
    assert state.canonical_revision == 2 and state.canonical_run_id == second.run_id
    assert CORRECTION[:40] in state.canonical["result"]["summary"]
    # Incident: only revision 2's Operon run produced a report; revision 1's claim is superseded history.
    reports = reports_for(engine, incident.id)
    assert [r.run_id for r in reports] == [backend.snapshots[1].run_id]
    after = engine.coordinator.repository.fetch_incident(incident.id)
    assert after.active_run_id == backend.snapshots[1].run_id and after.phase == m.IncidentPhase.AWAITING_EVIDENCE
    assert after.current_diagnosis_id is None
    kinds = [(e.revision, e.kind, e.status.value) for e in effects(engine, sid)]
    assert (1, "operon_run_claim", "COMPLETED") in kinds and (2, "canonical_apply", "COMPLETED") in kinds
    assert not any(rev == 1 and kind == "canonical_apply" for rev, kind, _ in kinds)
    events = engine.prism.repository.list_events(sid)
    assert any(e.event_type == "stale_result_discarded" and e.run_id == first.run_id for e in events)
    assert any(e.event_type == "slow_path_progress" and e.payload.get("stage") == "candidate_fenced"
               and e.payload.get("disposition") == "stale" and e.run_id == first.run_id for e in events)
    view = engine.prism.session_view(sid)
    assert view["stale_results"] == 1 and view["reasoning"]["stale_candidates"][0]["run_id"] == first.run_id
    assert view["reasoning"]["candidate"]["operon_run_id"] == backend.snapshots[1].run_id
    await engine.prism.shutdown()
    return engine, backend


async def test_stale_real_candidate_cannot_change_incident_or_prism_state(seeded_db, monkeypatch):
    await _stale_candidate_scenario(monkeypatch, cooperative=True)


async def test_non_cooperative_provider_returning_late_is_fenced(seeded_db, monkeypatch):
    engine, backend = await _stale_candidate_scenario(monkeypatch, cooperative=False)
    assert backend.cancelled == []            # the provider never observed a cancellation and still finished
    assert engine.prism.adapter.cancellable is False


# ---------------------------------------------------------------------------------------------------
# 5. apply race: revision-1 apply boundary versus acceptance of revision 2 on durable connections
# ---------------------------------------------------------------------------------------------------
class BarrierAdapter(OperonSlowPathAdapter):
    """Blocks at the candidate -> fence boundary until released (the seam the development hold uses)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.arrived = asyncio.Event()
        self.gate = asyncio.Event()

    async def _before_fence(self, execution, candidate):
        self.arrived.set()
        await self.gate.wait()


async def test_apply_boundary_races_revision_two_acceptance_without_stale_incident_writes(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(auto_release=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend, adapter_class=BarrierAdapter)
    repo, prism_repo = engine.coordinator.repository, engine.prism.repository
    outcomes = {"committed": 0, "stale": 0}
    for round_no in range(8):
        adapter.arrived.clear(); adapter.gate.clear()
        sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
        one = await engine.prism.submit_message(sid, content=f"{INVESTIGATE} round {round_no}")
        assert await wait_for(lambda: adapter.arrived.is_set())
        claimed = repo.fetch_incident(incident.id)
        operon_run = backend.snapshots[-1].run_id
        assert claimed.active_run_id == operon_run
        errors: list[BaseException] = []

        def accept_revision_two():   # a second durable connection, exactly what the API path uses
            try:
                time.sleep(random.random() * 0.004)
                prism_repo.accept_turn(sid, request_id=f"race-{round_no}", idempotency_key=f"race-{round_no}",
                                       content=f"{CORRECTION} round {round_no}", content_type="text", metadata={},
                                       fast_path=engine.prism.fast_path, schedule_slow_path=False)
            except BaseException as exc:  # noqa: BLE001 - surfaced below
                errors.append(exc)
        thread = threading.Thread(target=accept_revision_two)
        thread.start()
        await asyncio.sleep(random.random() * 0.004)
        adapter.gate.set()                                     # revision 1 reaches the fence now
        assert await engine.prism.wait_idle(10)
        await asyncio.to_thread(thread.join)
        assert not errors, errors
        run = prism_repo.get_run(one["slow_path"]["run_id"])
        state = prism_repo.get_session(sid)
        after = repo.fetch_incident(incident.id)
        reports = [r for r in reports_for(engine, incident.id) if r.run_id == operon_run]
        applies = [e for e in effects(engine, sid, "canonical_apply")]
        assert state.current_revision == 2
        if run.status == RunStatus.COMPLETED:      # the fence admitted revision 1 before revision 2 was accepted
            outcomes["committed"] += 1
            assert len(reports) == 1 and len(applies) == 1 and state.canonical_run_id == run.run_id
            assert after.phase == m.IncidentPhase.AWAITING_EVIDENCE
        else:                                      # revision 2 won: nothing of revision 1 reached the incident
            outcomes["stale"] += 1
            assert run.status == RunStatus.STALE and run.stale
            assert reports == [] and applies == [] and state.canonical_run_id is None
            assert after.revision == claimed.revision and after.phase == claimed.phase
        # Never both, never neither: the report exists exactly when PRISM committed.
        assert (len(reports) == 1) == (run.status == RunStatus.COMPLETED) == (len(applies) == 1)
        # Bring the incident back to INVESTIGATING for the next round when revision 1 applied.
        if after.phase == m.IncidentPhase.AWAITING_EVIDENCE:
            repo.transition(incident.id, m.IncidentPhase.INVESTIGATING, expected_revision=after.revision,
                            reason="test reset")
    assert outcomes["committed"] + outcomes["stale"] == 8
    await engine.prism.shutdown()


async def test_apply_failure_rolls_back_the_whole_commit(seeded_db, monkeypatch):
    class Exploding(OperonSlowPathAdapter):
        async def _before_fence(self, execution, candidate):
            original = self.promotion._complete_run

            def broken(*args, **kwargs):
                original(*args, **kwargs)            # the incident write happens ...
                raise RuntimeError("apply exploded after the report write")
            self.promotion._complete_run = broken
    backend = FakeReasoningBackend(auto_release=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend, adapter_class=Exploding)
    before = engine.coordinator.repository.fetch_incident(incident.id)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await engine.prism.wait_idle(10)
    run = engine.prism.repository.get_run(one["slow_path"]["run_id"])
    assert run.status == RunStatus.FAILED and run.error["code"] == "RuntimeError"
    # ... but is rolled back with the failed commit: no report, no apply effect, no canonical state.
    assert reports_for(engine, incident.id) == [] and effects(engine, sid, "canonical_apply") == []
    assert engine.prism.repository.get_session(sid).canonical_revision is None
    after = engine.coordinator.repository.fetch_incident(incident.id)
    assert after.phase == before.phase and after.active_run_id == backend.snapshots[0].run_id
    await engine.prism.shutdown()


# ---------------------------------------------------------------------------------------------------
# 6. a current candidate applies exactly once
# ---------------------------------------------------------------------------------------------------
async def test_current_candidate_applies_exactly_once_under_duplicate_completion_retry_and_restart(seeded_db, monkeypatch):
    seen: dict[str, object] = {}

    class Recording(OperonSlowPathAdapter):
        async def run(self, execution):
            seen["execution"] = execution
            return await super().run(execution)
    backend = FakeReasoningBackend(auto_release=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend, adapter_class=Recording)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE, request_id="once-1", idempotency_key="once-1")
    assert await engine.prism.wait_idle(10)
    execution = seen["execution"]
    operon_run = backend.snapshots[0].run_id
    assert len(reports_for(engine, incident.id)) == 1 and len(effects(engine, sid, "canonical_apply")) == 1
    # (a) duplicate candidate completion (provider callback twice): the fence refuses, apply is never invoked.
    calls = []
    decision = await execution.complete(SlowPathResult(summary="duplicate", provenance="INJECTED"),
                                        apply=lambda conn: calls.append(conn))
    assert not decision.committed and decision.reason == "already_terminal" and calls == []
    # (b) the whole adapter run replayed on the same (terminal) execution: refused at the claim, fail closed.
    try:
        await adapter.run(execution)
        raise AssertionError("a replayed run must be refused by the fence")
    except StaleRevisionError as exc:
        assert exc.decision.reason == "already_terminal"
    assert len(backend.contexts) == 1 and len(reports_for(engine, incident.id)) == 1
    assert [e.kind for e in effects(engine, sid)] == ["operon_run_claim", "canonical_apply"]
    # (c) HTTP/websocket retry of the same operator message: deduplicated, no new revision or run.
    again = await engine.prism.submit_message(sid, content=INVESTIGATE, request_id="once-1", idempotency_key="once-1")
    assert again["duplicate"] and again["revision"] == 1 and engine.prism.repository.list_runs(sid)[-1].run_id == one["slow_path"]["run_id"]
    # (d) restart after the apply: canonical state exists, recovery retries nothing, nothing is applied twice.
    restarted = make_engine(monkeypatch)
    restarted.prism.coordinator.adapter = restarted.prism.adapter = OperonSlowPathAdapter(
        **{**restarted._prism_services(), "backend_factory": lambda: FakeReasoningBackend(auto_release=True)})
    await restarted.start(); await restarted.stop()
    assert restarted.prism.recovered == [] and await restarted.prism.wait_idle(5)
    assert len(reports_for(restarted, incident.id)) == 1 and len(effects(restarted, sid, "canonical_apply")) == 1
    assert restarted.prism.repository.get_session(sid).canonical_run_id == one["slow_path"]["run_id"]
    assert restarted.coordinator.repository.fetch_incident(incident.id).active_run_id == operon_run
    await engine.prism.shutdown(); await restarted.prism.shutdown()


# ---------------------------------------------------------------------------------------------------
# 7. stale failure never becomes the current failure
# ---------------------------------------------------------------------------------------------------
async def test_stale_failure_of_revision_one_does_not_overwrite_revision_two(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(block=True, ignore_cancellation=True, fail_with="provider exploded", fail_calls={1})
    engine, adapter, incident = await production_engine(monkeypatch, backend, cooperative=False)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await wait_for(lambda: len(backend.contexts) == 1)
    two = await engine.prism.submit_message(sid, content=CORRECTION)
    assert await wait_for(lambda: len(backend.contexts) == 2)
    backend.release.set()
    assert await engine.prism.wait_idle(10)
    runs = runs_by_revision(engine, sid)
    assert runs[(1, 1)].status == RunStatus.FAILED and runs[(1, 1)].stale and runs[(1, 1)].error["message"] == "provider exploded"
    assert runs[(2, 1)].status == RunStatus.COMPLETED
    view = engine.prism.session_view(sid)
    assert view["last_failure"] is None and view["runtime_state"] == "completed" and view["reasoning"]["current_failure"] is None
    assert view["canonical_revision"] == 2
    # The stale failure's audit report was refused by the fence: only revision 2 reached the incident.
    assert [r.run_id for r in reports_for(engine, incident.id)] == [backend.snapshots[1].run_id]
    events = engine.prism.repository.list_events(sid)
    assert any(e.event_type == "slow_path_progress" and e.payload.get("stage") == "stale_failure_fenced" for e in events)
    assert any(e.event_type == "run_failed" and e.payload["stale"] is True and e.run_id == runs[(1, 1)].run_id for e in events)
    await engine.prism.shutdown()


async def test_current_revision_failure_is_recorded_truthfully_without_escalating(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(auto_release=True, fail_with="model unavailable")
    engine, adapter, incident = await production_engine(monkeypatch, backend)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await engine.prism.wait_idle(10)
    run = engine.prism.repository.get_run(one["slow_path"]["run_id"])
    assert run.status == RunStatus.FAILED and not run.stale
    view = engine.prism.session_view(sid)
    assert view["last_failure"]["run_id"] == run.run_id and view["reasoning"]["current_failure"]["message"] == "model unavailable"
    reports = reports_for(engine, incident.id)
    assert len(reports) == 1 and reports[0].completion == "MODEL_FAILED" and reports[0].run_id == backend.snapshots[0].run_id
    after = engine.coordinator.repository.fetch_incident(incident.id)
    assert after.phase == m.IncidentPhase.INVESTIGATING       # PRISM never escalates on the operator's behalf
    await engine.prism.shutdown()


# ---------------------------------------------------------------------------------------------------
# 8. recovery
# ---------------------------------------------------------------------------------------------------
async def test_restart_during_production_reasoning_retries_once_and_abandoned_run_cannot_apply(seeded_db, monkeypatch):
    old_backend = FakeReasoningBackend(block=True, ignore_cancellation=True)
    engine, adapter, incident = await production_engine(monkeypatch, old_backend)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await wait_for(lambda: len(old_backend.contexts) == 1)
    first_operon_run = old_backend.snapshots[0].run_id
    # The process "dies" mid-reasoning: the old engine is abandoned with its run still RUNNING.
    new_backend = FakeReasoningBackend(auto_release=True)
    restarted = make_engine(monkeypatch)
    restarted.prism.coordinator.adapter = restarted.prism.adapter = OperonSlowPathAdapter(
        **{**restarted._prism_services(), "backend_factory": lambda: new_backend})
    await restarted.start(); await restarted.stop()
    report = restarted.prism.recovered[0]
    assert report["session_id"] == sid and report["retried"]["attempt"] == 2 and report["failed_runs"] == [one["slow_path"]["run_id"]]
    assert await restarted.prism.wait_idle(10)
    runs = runs_by_revision(restarted, sid)
    assert runs[(1, 1)].status == RunStatus.FAILED and runs[(1, 1)].error["code"] == "process_restart"
    assert runs[(1, 2)].status == RunStatus.COMPLETED and runs[(1, 2)].recovered_from_run_id == runs[(1, 1)].run_id
    # The retry reasoned again with the current instruction over the authoritative incident: a NEW Operon run.
    assert len(new_backend.contexts) == 1 and INVESTIGATE in new_backend.contexts[0].question
    second_operon_run = new_backend.snapshots[0].run_id
    assert second_operon_run != first_operon_run
    reports = reports_for(restarted, incident.id)
    assert [r.run_id for r in reports] == [second_operon_run]
    after = restarted.coordinator.repository.fetch_incident(incident.id)
    assert after.active_run_id == second_operon_run and after.phase == m.IncidentPhase.AWAITING_EVIDENCE
    state = restarted.prism.repository.get_session(sid)
    assert state.canonical_revision == 1 and state.canonical_run_id == runs[(1, 2)].run_id
    assert state.recovery["retried"]["attempt"] == 2
    assert [(e.revision, e.kind, e.status.value) for e in effects(restarted, sid)] == [
        (1, "operon_run_claim", "COMPLETED"), (1, "operon_run_claim", "COMPLETED"), (1, "canonical_apply", "COMPLETED")]
    # The abandoned pre-restart worker now returns (old provider stream): it is never trusted.
    old_backend.release.set()
    assert await engine.prism.wait_idle(10)
    assert len(reports_for(restarted, incident.id)) == 1
    assert restarted.prism.repository.get_run(one["slow_path"]["run_id"]).status == RunStatus.FAILED
    assert restarted.prism.repository.get_session(sid).canonical_run_id == runs[(1, 2)].run_id
    assert restarted.coordinator.repository.fetch_incident(incident.id).active_run_id == second_operon_run
    await engine.prism.shutdown(); await restarted.prism.shutdown()


# ---------------------------------------------------------------------------------------------------
# 9. Fast Path / event loop / HTTP responsiveness while the real seam is blocked
# ---------------------------------------------------------------------------------------------------
async def test_fast_path_and_event_loop_stay_responsive_while_production_reasoning_is_blocked(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(block=True, ignore_cancellation=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend, cooperative=False)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await wait_for(lambda: len(backend.contexts) == 1)
    gaps: list[float] = []

    async def ticker():
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now
    tick = asyncio.create_task(ticker())
    started = time.perf_counter()
    two = await engine.prism.submit_message(sid, content=CORRECTION)
    accepted_ms = (time.perf_counter() - started) * 1000
    assert two["fast_path"]["status"] == "accepted_superseding" and two["revision"] == 2
    assert two["fast_path"]["latency_ms"] < 250 and accepted_ms < 500 and two["acceptance_ms"] < 500
    events = engine.prism.repository.list_events(sid)
    by_type = {e.event_type: e for e in events if e.revision in (1, 2)}
    # supersession/cancellation and the new Slow Path are recorded in the acceptance transaction itself.
    assert {"interruption_received", "revision_superseded", "cancellation_requested", "slow_path_queued"} <= set(by_type)
    assert await wait_for(lambda: len(backend.contexts) == 2, timeout=5)
    await asyncio.sleep(0.05)
    tick.cancel()
    assert max(gaps) < 0.25, max(gaps)
    backend.release.set()
    assert await engine.prism.wait_idle(10)
    await engine.prism.shutdown()


def test_http_acceptance_stays_prompt_while_the_real_seam_is_blocked(seeded_db, monkeypatch):
    from server import main as server_main
    engine = make_engine(monkeypatch)
    backend = FakeReasoningBackend(block=True, ignore_cancellation=True)
    engine.prism.coordinator.adapter = engine.prism.adapter = OperonSlowPathAdapter(
        **{**engine._prism_services(), "backend_factory": lambda: backend}, cooperative=False)
    server_main.app.router.on_startup.clear()
    monkeypatch.setattr(server_main, "engine", engine)
    with TestClient(server_main.app) as client:
        for _ in range(40):
            client.post("/api/start")
            state = client.get("/api/state").json()
            if state.get("alerts") and state["alerts"][0].get("incident_id"):
                incident_id = state["alerts"][0]["incident_id"]
                break
            time.sleep(0.05)
        client.post("/api/stop")
        sid = client.post("/api/prism/sessions", json={"incident_id": incident_id}).json()["session"]["session_id"]
        one = client.post(f"/api/prism/sessions/{sid}/messages", json={"content": INVESTIGATE, "request_id": "http-1"})
        assert one.status_code == 202
        deadline = time.time() + 5
        while time.time() < deadline and len(backend.contexts) < 1:
            time.sleep(0.02)
        assert len(backend.contexts) == 1
        started = time.perf_counter()
        two = client.post(f"/api/prism/sessions/{sid}/messages", json={"content": CORRECTION, "request_id": "http-2"})
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert two.status_code == 202 and two.json()["fast_path"]["status"] == "accepted_superseding"
        assert elapsed_ms < 1000, elapsed_ms
        view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
        assert view["runtime_state"] in ("superseding", "slow_path") and view["reasoning"]["instruction"] == CORRECTION
        assert view["provenance"]["adapter"] == "operon" and view["provenance"]["provenance"] == "INJECTED"
        backend.release.set()
        deadline = time.time() + 10
        while time.time() < deadline:
            view = client.get(f"/api/prism/sessions/{sid}").json()["session"]
            if view["canonical_revision"] == 2 and view["stale_results"] == 1:
                break
            time.sleep(0.05)
        assert view["canonical_revision"] == 2 and view["stale_results"] == 1
        assert view["reasoning"]["applied"]["report_id"]


# ---------------------------------------------------------------------------------------------------
# bounded second pass when the frozen inputs changed during reasoning
# ---------------------------------------------------------------------------------------------------
class EvidenceCollectingBackend(FakeReasoningBackend):
    """On its first call the (real) evidence service writes new evidence during reasoning."""

    async def supervise(self, service, context, *, bounds, snapshot=None, **kwargs):
        if len(self.contexts) == 0:
            service.request_and_collect(context.incident_id, requested_by="diagnostic",
                                        equipment_ids=(context.asset_id,), question="Read recorded service history",
                                        capability="get_maintenance_history", required_for="diagnosis")
        return await super().supervise(service, context, bounds=bounds, snapshot=snapshot, **kwargs)


async def test_inputs_changed_during_reasoning_trigger_one_bounded_fenced_retry_pass(seeded_db, monkeypatch):
    backend = EvidenceCollectingBackend(auto_release=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await engine.prism.wait_idle(10)
    run = engine.prism.repository.get_run(one["slow_path"]["run_id"])
    assert run.status == RunStatus.COMPLETED and run.result["runtime"]["pass"] == 2 and len(backend.contexts) == 2
    reports = reports_for(engine, incident.id)
    assert [r.run_id for r in reports] == [backend.snapshots[0].run_id, backend.snapshots[1].run_id]
    assert reports[0].stale_reasons == ("ACTIVE_RUN_CHANGED", "REVISION_CHANGED_DURING_RUN") or "REVISION_CHANGED_DURING_RUN" in reports[0].stale_reasons
    assert reports[1].stale_reasons == ()
    assert [e.kind for e in effects(engine, sid)] == ["operon_run_claim", "operon_run_report", "operon_run_claim", "canonical_apply"]
    assert run.result["details"]["applied"]["report_id"] == reports[1].id
    await engine.prism.shutdown()


# ---------------------------------------------------------------------------------------------------
# lifecycle boundaries: AWAITING_EVIDENCE resumes under an instruction; autonomous diagnosis yields
# ---------------------------------------------------------------------------------------------------
async def test_operator_instruction_resumes_an_awaiting_evidence_incident_inside_the_fenced_claim(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(auto_release=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend)
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await engine.prism.wait_idle(10)
    assert engine.coordinator.repository.fetch_incident(incident.id).phase == m.IncidentPhase.AWAITING_EVIDENCE
    await engine.prism.submit_message(sid, content=CORRECTION)
    assert await engine.prism.wait_idle(10)
    events = engine.coordinator.repository.list_events(incident.id)
    changes = [(e.payload["from"], e.payload["to"], e.payload["reason"]) for e in events if e.event_type == "PHASE_CHANGED"]
    assert ("AWAITING_EVIDENCE", "INVESTIGATING", "operator instruction (PRISM revision 2)") in changes
    assert changes[-1][1] == "AWAITING_EVIDENCE" and "PRISM revision 2" in changes[-1][2]
    await engine.prism.shutdown()


async def test_autonomous_diagnosis_is_suppressed_while_a_prism_revision_reasons(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(block=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend)
    eid = next(iter(engine.incidents))
    engine._base_runtime = object()          # pretend a runtime is configured
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await wait_for(lambda: len(backend.contexts) == 1)
    engine._schedule_diagnosis(eid)
    assert eid not in engine._lifecycle_tasks
    assert engine._reasoning_diagnostics[-1]["diagnosis_scheduling_decision"] == "suppressed_prism_active"
    engine._base_runtime = None
    backend.release.set()
    assert await engine.prism.wait_idle(10)
    await engine.prism.shutdown()


async def test_production_adapter_waits_while_the_engine_owns_the_incident(seeded_db, monkeypatch):
    backend = FakeReasoningBackend(auto_release=True)
    engine, adapter, incident = await production_engine(monkeypatch, backend)
    eid = next(iter(engine.incidents))
    blocker = asyncio.Event()

    async def engine_run():
        await blocker.wait()
    engine._lifecycle_tasks[eid] = asyncio.create_task(engine_run())
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await wait_for(lambda: any(e.payload.get("stage") == "waiting_for_incident"
                                      for e in engine.prism.repository.list_events(sid)))
    assert backend.contexts == []
    blocker.set()
    assert await engine.prism.wait_idle(10)
    assert len(backend.contexts) == 1
    await engine.prism.shutdown()


# ---------------------------------------------------------------------------------------------------
# selection, truthful provenance, unlinked sessions
# ---------------------------------------------------------------------------------------------------
def test_adapter_selection_defaults_to_production_and_labels_no_provider_runs_simulated(seeded_db):
    adapter = adapter_from_environment(env={})
    assert isinstance(adapter, OperonSlowPathAdapter) and adapter.cancellable
    identity = adapter.identity()
    assert identity["adapter"] == "operon" and identity["role"] == "slow"
    assert identity["backend"] == "deterministic" and identity["provider"] == "none"
    assert identity["live_model"] is False and identity["provenance"] == "SIMULATED"
    assert isinstance(adapter_from_environment(env={"OPERON_PRISM_SLOW_PATH": "deterministic"}), DeterministicSlowPathAdapter)
    tuned = adapter_from_environment(env={"OPERON_PRISM_SLOW_PATH": "operon", "OPERON_PRISM_SLOW_COOPERATIVE": "0",
                                          "OPERON_PRISM_SLOW_HOLD_SECONDS": "2.5", "OPERON_PRISM_SLOW_MAX_PASSES": "3"})
    assert tuned.cancellable is False and tuned.hold_seconds == 2.5 and tuned.max_passes == 3


async def test_engine_default_slow_path_reasons_with_the_deterministic_advisory_labelled_simulated(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)
    assert isinstance(engine.prism.adapter, OperonSlowPathAdapter)
    await engine._advance()
    assert await wait_for(lambda: bool(engine.incidents))
    incident = next(iter(engine.incidents.values()))
    sid = (await engine.prism.create_session(incident_id=incident.id))["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await engine.prism.wait_idle(10)
    run = engine.prism.repository.get_run(one["slow_path"]["run_id"])
    assert run.status == RunStatus.COMPLETED and run.result["provenance"] == "SIMULATED"
    assert run.runtime["backend"] == "deterministic" and run.runtime["live_model"] is False
    assert run.result["details"]["reasoning"]["provenance"] == "SIMULATED"
    snapshot = engine.coordinator.repository.get_artifact(incident.id, run.result["details"]["candidate"]["snapshot_id"])
    assert snapshot.runtime_identity["backend"] == "deterministic" and snapshot.runtime_identity["live_model"] is False
    assert engine.snapshot()["prism"]["slow_path"]["provenance"] == "SIMULATED"
    await engine.prism.shutdown()


async def test_unlinked_session_fails_closed_instead_of_reasoning_without_incident_context(seeded_db, monkeypatch):
    engine = make_engine(monkeypatch)
    sid = (await engine.prism.create_session())["session_id"]
    one = await engine.prism.submit_message(sid, content=INVESTIGATE)
    assert await engine.prism.wait_idle(10)
    run = engine.prism.repository.get_run(one["slow_path"]["run_id"])
    assert run.status == RunStatus.FAILED and run.error["code"] == "incident_required"
    await engine.prism.shutdown()


# ---------------------------------------------------------------------------------------------------
# the fenced transact primitive itself
# ---------------------------------------------------------------------------------------------------
async def test_fenced_transact_is_atomic_idempotent_and_refused_after_supersession(seeded_db):
    from core.prism import PrismRepository, PrismRuntime
    repo = PrismRepository()
    adapter = ControlledAdapter()
    rt = PrismRuntime(repo, adapter=adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content=INVESTIGATE)
    assert await wait_for(lambda: repo.get_run(one["slow_path"]["run_id"]).status == RunStatus.RUNNING)
    identity = adapter.started[0].identity
    with db.get_conn(repo.path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS stage2_probe (k TEXT PRIMARY KEY)")

    def write_then_fail(conn):
        conn.execute("INSERT INTO stage2_probe VALUES ('rolled-back')")
        raise RuntimeError("boom")
    try:
        repo.transact(identity, kind="probe", idempotency_key="probe-1", request_hash="h", perform=write_then_fail)
    except RuntimeError:
        pass
    with db.get_conn(repo.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM stage2_probe").fetchone()[0] == 0
    assert repo.list_effects(sid) == []

    def write(conn):
        conn.execute("INSERT INTO stage2_probe VALUES ('kept')")
        return {"wrote": "kept"}
    effect, performed, events = repo.transact(identity, kind="probe", idempotency_key="probe-1", request_hash="h", perform=write)
    assert performed and effect.status.value == "COMPLETED" and effect.result == {"wrote": "kept"}
    again, performed, _ = repo.transact(identity, kind="probe", idempotency_key="probe-1", request_hash="h",
                                        perform=lambda conn: (_ for _ in ()).throw(AssertionError("must not run")))
    assert not performed and again.effect_id == effect.effect_id
    await rt.submit_message(sid, content=CORRECTION)          # revision 2 supersedes revision 1
    try:
        repo.transact(identity, kind="probe", idempotency_key="probe-2", request_hash="h", perform=write)
        raise AssertionError("stale transact must be refused")
    except StaleRevisionError as exc:
        assert exc.decision.reason == "stale_revision"
    with db.get_conn(repo.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM stage2_probe").fetchone()[0] == 1
    assert [e.event_type for e in repo.list_events(sid)].count("effect_refused") == 1
    adapter.release.set()
    await rt.wait_idle(5)
    await rt.shutdown()
