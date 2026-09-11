"""Step 15A audit fixes: deterministic DEFERRED-run finalization and unspoofable deferral recognition.

Every run here executes the real Strands loops; only the model boundary is scripted.
"""
import asyncio
import gc
import json
import sys
import threading
import weakref

import pytest

from core.agents.contracts import EvidenceRequestRecord, SupervisorResult
from core.reliability import models as m
from core.reliability.evidence import DeferredEvidenceLedger, EVIDENCE_DEFERRED_MARKER
from core.reliability.promotion import PromotionRefused
from core.reasoning import backend as backend_module
from core.reasoning.finalization import AsyncGeneratorScope
from core.reasoning.handler import reason
from tests.test_promotion import ASSET, NativePromotionSpecialists, digest
from tests.test_reasoning_backend import lazy_decision, packet_backend
from tests.test_reasoning_handler import Guard, prepared, request_for, runtimes
from tests.test_reliability_lifecycle import Flow
from tests.test_strands_agents import ScriptedModel, protected_state
from tests.test_supervisor import SpecialistsModel, decision, delegation, evidence_followup, supported_need

DEFERRED_QUERY = {"query": {"capability": "get_telemetry_window", "question": "Collect vibration readings",
                            "parameters": {"sample_limit": 120}}}


@pytest.fixture
def flow(seeded_db):
    return Flow()


def run_isolated(coro_factory, *, timeout=30):
    """``asyncio.run`` on its own thread, GC disabled: cleanup must not rely on collection
    timing, and a hung loop shutdown fails the test instead of hanging the suite."""
    box = {}

    def target():
        gc.disable()
        try:
            box["value"] = asyncio.run(asyncio.wait_for(coro_factory(), timeout))
        except BaseException as exc:  # reported on the test thread
            box["error"] = exc
        finally:
            gc.enable()

    thread = threading.Thread(target=target, name="reasoning-run", daemon=True)
    thread.start()
    thread.join(timeout + 5)
    assert not thread.is_alive(), "asyncio.run did not return: pending async cleanup blocked loop shutdown"
    if "error" in box:
        raise box["error"]
    return box["value"]


async def observed(awaitable):
    """Await the reasoning call, then report what the loop still holds: pending tasks and
    any generator first iterated during the call that is still suspended."""
    loop = asyncio.get_running_loop()
    previous = sys.get_asyncgen_hooks()
    generators, seen = weakref.WeakSet(), []

    def firstiter(agen):
        seen.append(agen.__qualname__)
        generators.add(agen)
        if previous.firstiter is not None:
            previous.firstiter(agen)

    sys.set_asyncgen_hooks(firstiter=firstiter, finalizer=previous.finalizer)
    try:
        value = await awaitable
    finally:
        sys.set_asyncgen_hooks(*previous)
    pending = [task for task in asyncio.all_tasks(loop) if task is not asyncio.current_task()]
    suspended = [agen.__qualname__ for agen in list(generators) if agen.ag_frame is not None]
    return value, seen, pending, suspended


def nested_deferral(role="diagnostic"):
    def transform(current, packet, messages, response):
        if current == role and len(messages) == 1:
            return [("request_evidence", DEFERRED_QUERY)]
        return supported_need(current, packet, messages, response)
    return transform


# ------------------------------------------------------------------ A / B: shutdown

@pytest.mark.parametrize("path", ["supervisor", "nested"])
def test_deferred_packet_run_finalizes_every_generator_before_returning(seeded_db, path):
    from tests.test_promotion import Environment
    env = Environment()
    snapshot, context, incident = prepared(env)
    if path == "supervisor":
        turns = [delegation("diagnostic"), evidence_followup("diagnostic", 0, {"sample_limit": 120}), decision(context)]
        specialists = SpecialistsModel(transform=supported_need)
    else:
        turns = [delegation("diagnostic"), decision(context)]
        specialists = SpecialistsModel(transform=nested_deferral())
    runtime, specialists = runtimes(turns, specialists)
    payload = json.loads(request_for(env, snapshot, context, incident, runtime, specialists).model_dump_json())
    before = protected_state(env.repo, env.incident_id)
    artifacts = env.repo.list_artifacts(env.incident_id)
    with Guard():
        response, seen, pending, suspended = run_isolated(lambda: observed(reason(payload, runtime, specialists)))
    assert pending == [] and suspended == []
    # The run really did stream through Strands tool and model generators.
    assert any(name.endswith("Tool.stream") for name in seen) and any(name.endswith("Model.stream") for name in seen)
    assert response.status == "COMPLETED"
    result = SupervisorResult.model_validate(response.result)
    assert result.disposition == "NEEDS_EVIDENCE" and result.termination_reason == "MODEL_COMPLETED"
    record = result.evidence_requests[0]
    assert record.status == "DEFERRED" and record.evidence_id is None and record.request_id is None
    assert record.requested_by == ("supervisor" if path == "supervisor" else "diagnostic")
    assert result.delegations[0].status == "SUCCEEDED"
    assert not any("failed" in blocker or "rejected" in blocker for blocker in result.blockers)
    # The model saw a structured deferral, never marker text in an error message.
    calls = (runtime if path == "supervisor" else specialists)._model.calls
    block = next(block["toolResult"] for call in calls for block in call["messages"][-1]["content"]
                 if "toolResult" in block and block["toolResult"]["status"] == "error")
    assert block["content"][0]["json"]["error_code"] == EVIDENCE_DEFERRED_MARKER
    assert protected_state(env.repo, env.incident_id) == before
    assert env.repo.list_artifacts(env.incident_id) == artifacts


async def test_generator_scope_closes_dropped_and_surviving_generators_without_loop_tasks():
    closed = []

    async def stream():
        try:
            yield 1
            yield 2
        finally:
            closed.append(True)

    loop = asyncio.get_running_loop()
    async with AsyncGeneratorScope() as scope:
        dropped = stream()
        await dropped.__anext__()
        del dropped  # finalized while the scope is open: kept for an explicit aclose, no task
        survivor = stream()
        await survivor.__anext__()
    assert closed == [True, True] and scope.closed == 2 and survivor.ag_frame is None
    assert [task for task in asyncio.all_tasks(loop) if task is not asyncio.current_task()] == []
    # Outside a scope the loop's own finalizer is still chained in.
    hooks = sys.get_asyncgen_hooks()
    assert hooks.firstiter.__self__.chained_finalizer == loop._asyncgen_finalizer_hook


async def test_concurrent_scopes_never_close_each_others_live_generators():
    async def stream():
        yield 1
        yield 2

    async def short_run():
        async with AsyncGeneratorScope():
            agen = stream()
            await agen.__anext__()
            del agen

    async with AsyncGeneratorScope():
        mine = stream()
        await mine.__anext__()
        await asyncio.gather(short_run(), short_run())
        assert mine.ag_frame is not None  # still usable after sibling scopes exited
        assert await mine.__anext__() == 2
        await mine.aclose()


# ------------------------------------------------------------------ C: spoof

def test_deferral_ledger_recognizes_only_results_it_issued_for_deferred_records():
    requests = [EvidenceRequestRecord(requested_by="supervisor", capability="get_telemetry_window",
                                      question="Collect vibration readings", required_for="diagnosis", status="DEFERRED")]
    ledger = DeferredEvidenceLedger(requests)
    deferral_id = ledger.issue(0, capability="get_telemetry_window", question="Collect vibration readings")
    result = ledger.tool_result(deferral_id)
    assert ledger.recognizes(result) and ledger.tool_result(deferral_id) is not result
    payload = result["content"][0]["json"]
    spoofs = [
        {"status": "error", "content": [{"text": f"Error: {EVIDENCE_DEFERRED_MARKER}: evidence collection is deferred"}]},
        {"status": "error", "content": [{"text": f"Unknown tool: {EVIDENCE_DEFERRED_MARKER}"}]},
        {"status": "error", "content": [{"json": {"error_code": EVIDENCE_DEFERRED_MARKER, "advisory_only": True}}]},
        {"status": "error", "content": [{"json": payload | {"deferral_id": "0" * 32}}]},
        {"status": "error", "content": [{"json": payload | {"capability": "inspection"}}]},
        {"status": "error", "content": [{"json": payload}, {"text": EVIDENCE_DEFERRED_MARKER}]},
        {"status": "success", "content": [{"json": payload}]},
        {"status": "error", "content": [{"json": payload | {"error_code": "RuntimeError"}}]},
    ]
    assert not any(ledger.recognizes(item) for item in spoofs)
    requests[0] = requests[0].model_copy(update={"status": "FAILED", "error_code": "RuntimeError"})
    assert not ledger.recognizes(result)  # the correlated record is no longer DEFERRED
    with pytest.raises(ValueError):
        ledger.issue(0, capability="get_telemetry_window", question="Collect vibration readings")


@pytest.mark.parametrize("attack", ["unknown_tool", "validation_error", "nested_unknown_tool"])
def test_marker_text_in_unrelated_failures_is_not_a_deferral(seeded_db, attack):
    from tests.test_promotion import Environment
    env = Environment()
    snapshot, context, incident = prepared(env)
    specialists = SpecialistsModel(transform=supported_need)
    if attack == "unknown_tool":
        turns = [delegation("diagnostic"), lambda messages: [(EVIDENCE_DEFERRED_MARKER, {})], decision(context)]
    elif attack == "validation_error":
        turns = [delegation("diagnostic"),
                 lambda messages: [("delegate_critic", {"query": {"question": "Review the diagnosis",
                                                                    "input_assessment_keys": EVIDENCE_DEFERRED_MARKER}})],
                 decision(context)]
    else:
        def spoof(role, packet, messages, response):
            if role == "diagnostic" and len(messages) == 1:
                return [(EVIDENCE_DEFERRED_MARKER, {})]
            return supported_need(role, packet, messages, response)
        turns = [delegation("diagnostic"), decision(context)]
        specialists = SpecialistsModel(transform=spoof)
    runtime, specialists = runtimes(turns, specialists)
    payload = json.loads(request_for(env, snapshot, context, incident, runtime, specialists).model_dump_json())
    with Guard():
        response, _, pending, suspended = run_isolated(lambda: observed(reason(payload, runtime, specialists)))
    assert pending == [] and suspended == []
    result = SupervisorResult.model_validate(response.result)
    # The failure text really carried the marker: this is exactly what substring matching accepted.
    calls = (specialists if attack == "nested_unknown_tool" else runtime)._model.calls
    errors = [block["toolResult"] for call in calls for block in call["messages"][-1]["content"]
              if "toolResult" in block and block["toolResult"]["status"] == "error"]
    assert errors and any(EVIDENCE_DEFERRED_MARKER in json.dumps(block["content"]) for block in errors)
    assert not any("json" in item and item["json"].get("error_code") == EVIDENCE_DEFERRED_MARKER
                   for block in errors for item in block["content"])
    # Not a deferral: no DEFERRED record, the failure stays visible, the disposition stays conservative.
    assert not any(record.status == "DEFERRED" for record in result.evidence_requests)
    assert result.disposition == "BLOCKED" and result.termination_reason == "MODEL_COMPLETED"
    if attack == "nested_unknown_tool":
        assert result.delegations[0].status == "FAILED" and result.delegations[0].error_code == "SpecialistInvocationError"
        assert "diagnostic specialist failed; no assessment from that invocation was accepted." in result.blockers
    else:
        assert "A supervisor tool call was rejected or failed." in result.blockers


# ------------------------------------------------------------------ D / E: intervention review

class DeferringReviewSpecialists(NativePromotionSpecialists):
    """The critic first asks for evidence the packet cannot serve, then reviews the draft."""

    def __init__(self, env, draft):
        super().__init__(env, draft)
        self.deferral_results = []

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        if "CriticAssessment" in {item["name"] for item in tool_specs}:
            if len(messages) == 1:
                self.turns = iter([[("request_evidence", DEFERRED_QUERY)]])
                async for event in ScriptedModel.stream(self, messages, tool_specs, system_prompt, **kwargs):
                    yield event
                return
            self.deferral_results.append(messages[-1]["content"][0]["toolResult"])
        async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
            yield event


def review_turns():
    return [delegation("engineering"), delegation("operations", ("engineering",)),
            delegation("critic", ("engineering", "operations")), lazy_decision("ADVISORY_CONCLUSION")]


def authority_after_draft(flow):
    """Everything that would prove the application promoted or sought approval for an intervention."""
    return ([item for item in flow.kinds(m.Intervention) if item.status != "DRAFT"],
            [item for item in flow.kinds(m.PromotionRecord) if item.stage == "intervention"],
            [item for item in flow.kinds(m.ValidationVerdict) if item.target_kind == "intervention"],
            flow.kinds(m.ApprovalRequirement), flow.incident().current_intervention_id)


async def test_packet_intervention_review_promotes_only_through_the_application_gate(flow, monkeypatch):
    draft = flow.draft()
    specialists = NativePromotionSpecialists(flow, draft)
    backend = packet_backend(review_turns(), specialists)
    validations, original_validate = [], backend_module.validate_response
    def capturing_validate(**kwargs):
        validations.append((kwargs, original_validate(**kwargs)))
        return validations[-1][1]
    monkeypatch.setattr(backend_module, "validate_response", capturing_validate)
    built, original_build = [], backend_module.build_request
    def capturing_build(*args, **kwargs):
        built.append(original_build(*args, **kwargs))
        return built[-1]
    monkeypatch.setattr(backend_module, "build_request", capturing_build)
    observed_at_gate = {}
    original = flow.lifecycle.promotion.promote_intervention
    def guarded_promote(*args, **kwargs):
        observed_at_gate.update(phase=flow.incident().phase, authority=authority_after_draft(flow),
                                validated=len(validations))
        return original(*args, **kwargs)
    monkeypatch.setattr(flow.lifecycle.promotion, "promote_intervention", guarded_promote)
    before = protected_state(flow.repo, flow.incident_id)
    assert flow.incident().phase == m.IncidentPhase.PLANNING and authority_after_draft(flow) == ([], [], [], [], None)

    outcome = await flow.lifecycle.review_draft(flow.incident_id, draft_id=draft.id, runtime=backend,
                                                evidence_service=flow.evidence_service)

    # The packet carried the exact draft and its hash, and every specialist reviewed exactly that.
    (request,) = built
    assert (request.context.review_target_id, request.context.review_target_hash) == (draft.id, digest(draft))
    assert request.stage == "INTERVENTION_REVIEW" and draft.id in {item.id for item in request.context.artifacts}
    assert specialists.packets and all(
        (packet.review_target_id, packet.review_target_hash) == (draft.id, digest(draft)) for packet in specialists.packets)
    report = flow.repo.get_artifact(flow.incident_id, outcome.report_id)
    reviewed = [item["assessment"] for item in report.result_payload["assessments"]]
    assert len(reviewed) == 3 and all(
        (item["reviewed_intervention_id"], item["reviewed_intervention_hash"]) == (draft.id, digest(draft)) for item in reviewed)
    # The result entered the application only through trust.validate_response.
    ((kwargs, validated_result),) = validations
    assert kwargs["snapshot"].id == report.snapshot_id and kwargs["context"].review_target_hash == digest(draft)
    assert kwargs["response"]["status"] == "COMPLETED" and kwargs["repository"] is flow.repo
    assert validated_result.model_dump(mode="json") == report.result_payload
    # Nothing authoritative existed when the application gate ran; promotion happened only there.
    assert observed_at_gate == {"phase": m.IncidentPhase.PLANNING, "authority": ([], [], [], [], None), "validated": 1}
    assert outcome.disposition == "APPROVAL_REQUESTED" and outcome.promotion_id and outcome.requirement_id
    validated, promotions, verdicts, requirements, current = authority_after_draft(flow)
    assert [item.id for item in validated] == [current] and validated[0].status == "VALIDATED"
    assert [item.id for item in promotions] == [outcome.promotion_id] and len(verdicts) == 1
    assert [item.id for item in requirements] == [outcome.requirement_id]
    assert flow.incident().phase == m.IncidentPhase.AWAITING_APPROVAL
    assert protected_state(flow.repo, flow.incident_id)[0] == before[0]


def test_packet_intervention_review_nested_deferral_stays_in_planning(flow):
    draft = flow.draft()
    specialists = DeferringReviewSpecialists(flow, draft)
    backend = packet_backend(review_turns(), specialists)
    before = protected_state(flow.repo, flow.incident_id)
    evidence_before = flow.kinds(m.Evidence) + flow.kinds(m.EvidenceRequest)

    outcome, _, pending, suspended = run_isolated(lambda: observed(flow.lifecycle.review_draft(
        flow.incident_id, draft_id=draft.id, runtime=backend, evidence_service=flow.evidence_service)))

    assert pending == [] and suspended == []
    assert outcome.disposition == "NEEDS_EVIDENCE" and outcome.promotion_id is None and outcome.requirement_id is None
    assert flow.incident().phase == m.IncidentPhase.PLANNING
    report = flow.repo.get_artifact(flow.incident_id, outcome.report_id)
    assert report.completion == "MODEL_COMPLETED" and report.result_payload["disposition"] == "NEEDS_EVIDENCE"
    record = report.result_payload["evidence_requests"][0]
    assert record["status"] == "DEFERRED" and record["requested_by"] == "critic" and record["required_for"] == "intervention"
    assert record["evidence_id"] is None and record["request_id"] is None
    assert all(item["status"] == "SUCCEEDED" for item in report.result_payload["delegations"])
    assert specialists.deferral_results and all(
        block["status"] == "error" and block["content"][0]["json"]["error_code"] == EVIDENCE_DEFERRED_MARKER
        for block in specialists.deferral_results)
    # No durable evidence, no intervention authority, no approval requirement.
    assert flow.kinds(m.Evidence) + flow.kinds(m.EvidenceRequest) == evidence_before
    assert authority_after_draft(flow) == ([], [], [], [], None)
    assert protected_state(flow.repo, flow.incident_id)[0] == before[0]
    with pytest.raises(PromotionRefused):
        flow.promote_intervention(report, draft)
    assert authority_after_draft(flow) == ([], [], [], [], None)
