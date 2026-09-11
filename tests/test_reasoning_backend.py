"""Step 15A: the ReasoningBackend seam, local compatibility and packet-mode parity."""
import json
from unittest.mock import Mock

import pytest

from core import config, engine as engine_module
from core.agents.contracts import SpecialistContext
from core.agents.runtime import RuntimeConfigurationError, StrandsRuntime
from core.reliability import models as m
from core.reliability.promotion import PromotionRefused
from core.reasoning.backend import (
    InProcessPacketBackend, LocalStrandsBackend, ReasoningBackend, ReasoningBackendUnavailable, as_backend,
    backend_from_environment,
)
from core.reasoning.identity import code_identity
from tests.test_engine_lifecycle import make_engine
from tests.test_promotion import ASSET, MECHANISM, revision
from tests.test_reliability_lifecycle import Flow
from tests.test_strands_agents import ScriptedModel, protected_state, settings
from tests.test_supervisor import SpecialistsModel, delegation, evidence_followup, supported_need


@pytest.fixture
def flow(seeded_db):
    return Flow()


def lazy_decision(disposition):
    """Build the SupervisorDecision from the run context the supervisor was given."""
    def turn(messages):
        from tests.test_supervisor import decision
        context = SpecialistContext.model_validate(json.loads(messages[0]["content"][0]["text"])["context"])
        return decision(context, disposition)(messages)
    return turn


def promotable(history_id, confirmation_id):
    """Specialist advice that satisfies the unchanged application diagnosis gates."""
    def transform(role, packet, messages, response):
        if role == "diagnostic":
            reviewed = [item.id for item in packet.evidence]
            response[0][1].update(
                evidence_reviewed=reviewed, recommended_hypothesis="overload", confidence=0.7,
                missing_evidence_requests=[], uncertainties=[],
                competing_hypotheses=[dict(key="overload", mechanism=MECHANISM, supporting_evidence_ids=[history_id, confirmation_id],
                                           confidence=0.7, falsification_tests=["Independent repeat load test"])])
        return response
    return transform


def packet_backend(turns, specialists=None):
    return InProcessPacketBackend(StrandsRuntime(settings(), model=ScriptedModel(turns)),
                                  StrandsRuntime(settings(), model=specialists or SpecialistsModel()))


def test_as_backend_wraps_runtimes_and_passes_backends_through():
    runtime, specialists = StrandsRuntime(settings(), model=ScriptedModel()), StrandsRuntime(settings(), model=ScriptedModel())
    backend = as_backend(runtime, specialists)
    assert isinstance(backend, LocalStrandsBackend) and backend.runtime is runtime and backend.specialist_runtime is specialists
    assert backend.identity()["backend"] == "local" and set(backend.identity()) == {"backend", "supervisor", "specialists"}
    packet = InProcessPacketBackend(runtime)
    assert as_backend(packet) is packet and isinstance(packet, ReasoningBackend)
    assert packet.identity()["backend"] == "packet" and packet.identity()["session_id_scheme"] == "operon-run-{run_id}"
    assert packet.identity()["expected_identity"]["prompts"] == code_identity()["prompts"]
    with pytest.raises(TypeError):
        as_backend(packet, specialists)
    with pytest.raises(TypeError):
        as_backend("runtime")
    with pytest.raises(TypeError):
        LocalStrandsBackend(runtime, "specialists")


async def test_local_backend_is_the_unchanged_supervisor_seam(flow, monkeypatch):
    runtime, specialists = StrandsRuntime(settings(), model=ScriptedModel()), StrandsRuntime(settings(), model=ScriptedModel())
    seen = {}
    async def invoke(runtime_arg, service, context, **kwargs):
        seen.update(runtime=runtime_arg, service=service, kwargs=kwargs)
        from tests.test_promotion import result_payload
        from core.agents.contracts import SupervisorResult
        snapshot = next(a for a in flow.repo.list_artifacts(flow.incident_id) if isinstance(a, m.SupervisorRunSnapshot))
        return SupervisorResult.model_validate(result_payload(flow, snapshot))
    monkeypatch.setattr("core.agents.supervisor.supervise_reliability", invoke)
    flow.confirm()
    outcome = await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=runtime,
                                            evidence_service=flow.evidence_service, specialist_runtime=specialists)
    assert outcome.disposition == "PROMOTED"
    assert seen["runtime"] is runtime and seen["service"] is flow.evidence_service
    assert seen["kwargs"]["specialist_runtime"] is specialists and callable(seen["kwargs"]["cancellation_result_handler"])
    snapshot = next(a for a in flow.repo.list_artifacts(flow.incident_id) if isinstance(a, m.SupervisorRunSnapshot))
    assert snapshot.runtime_identity["backend"] == "local"
    assert snapshot.version_identity == code_identity()


async def test_packet_backend_diagnosis_promotes_only_through_application_gates(flow, monkeypatch):
    confirmation = flow.confirm()
    backend = packet_backend([delegation("diagnostic"), delegation("critic", ("diagnostic",)), lazy_decision("ADVISORY_CONCLUSION")],
                             SpecialistsModel(supported=True, transform=promotable(flow.history_id, confirmation.id)))
    before = protected_state(flow.repo, flow.incident_id)
    observed = {}
    original = flow.lifecycle.promotion.promote_diagnosis
    def guarded_promote(*args, **kwargs):
        # Everything the packet run produced is still inert when the application gate runs.
        observed["phase"] = flow.incident().phase
        observed["protected"] = protected_state(flow.repo, flow.incident_id)
        observed["authority"] = flow.kinds(m.Diagnosis) + flow.kinds(m.PromotionRecord) + flow.kinds(m.ValidationVerdict)
        return original(*args, **kwargs)
    monkeypatch.setattr(flow.lifecycle.promotion, "promote_diagnosis", guarded_promote)
    outcome = await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=backend,
                                            evidence_service=flow.evidence_service)
    assert outcome.disposition == "PROMOTED" and outcome.phase == m.IncidentPhase.DIAGNOSIS_VALIDATED
    assert observed["phase"] == m.IncidentPhase.INVESTIGATING and observed["authority"] == []
    assert observed["protected"][0] == before[0]
    snapshot = next(a for a in flow.repo.list_artifacts(flow.incident_id) if isinstance(a, m.SupervisorRunSnapshot))
    report = flow.repo.get_artifact(flow.incident_id, outcome.report_id)
    assert snapshot.runtime_identity["backend"] == "packet" and report.completion == "MODEL_COMPLETED"
    assert report.result_payload["disposition"] == "ADVISORY_CONCLUSION" and report.result_payload["evidence_requests"] == []
    assert flow.service.promotion_lineage(flow.incident_id, flow.incident().current_diagnosis_id, "diagnosis").id == outcome.promotion_id
    # The runtime never held the store: its supervisor and specialists saw only the packet.
    assert protected_state(flow.repo, flow.incident_id)[0] == before[0]


async def test_packet_backend_deferred_need_parks_in_awaiting_evidence_without_collecting(flow):
    flow.confirm()
    backend = packet_backend([delegation("diagnostic"), evidence_followup("diagnostic", 0, {"sample_limit": 120}),
                              lazy_decision("UNRESOLVED")], SpecialistsModel(transform=supported_need))
    before = protected_state(flow.repo, flow.incident_id)
    outcome = await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=backend,
                                            evidence_service=flow.evidence_service)
    assert outcome.disposition == "NEEDS_EVIDENCE" and outcome.phase == m.IncidentPhase.AWAITING_EVIDENCE
    report = flow.repo.get_artifact(flow.incident_id, outcome.report_id)
    record = report.result_payload["evidence_requests"][0]
    assert record["status"] == "DEFERRED" and record["parameters"]["sample_limit"] == 120 and record["evidence_id"] is None
    assert report.result_payload["disposition"] == "NEEDS_EVIDENCE"
    requests = [a for a in flow.repo.list_artifacts(flow.incident_id) if isinstance(a, m.EvidenceRequest)]
    assert not any(a.question == "Collect vibration readings" for a in requests)
    assert not flow.kinds(m.Diagnosis) and flow.incident().current_diagnosis_id is None
    assert protected_state(flow.repo, flow.incident_id)[0] == before[0]
    with pytest.raises(PromotionRefused):
        flow.promote_diagnosis(report)


async def test_backend_failure_persists_audit_report_and_leaves_phase_unchanged(flow, monkeypatch):
    backend = packet_backend([lazy_decision("ADVISORY_CONCLUSION")])
    drifted = backend.expected_identity().model_copy(update={"prompts": "sha256:drifted"})
    monkeypatch.setattr(backend, "expected_identity", lambda: drifted)
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        await flow.service.run_supervisor(flow.incident_id, service=flow.evidence_service, runtime=backend, asset_id=ASSET,
                                          stage="DIAGNOSIS", expected_revision=revision(flow), evidence_ids=flow.evidence_ids())
    assert failure.value.code == "VERSION_MISMATCH" and failure.value.retryable is False
    assert not backend.runtime._model.calls
    reports = flow.kinds(m.SupervisorReport)
    assert len(reports) == 1 and reports[0].completion == "MODEL_FAILED"
    assert "VERSION_MISMATCH" in reports[0].result_payload["blockers"][0]
    assert flow.incident().phase == m.IncidentPhase.INVESTIGATING and not flow.kinds(m.Diagnosis)
    with pytest.raises(PromotionRefused):
        flow.promote_diagnosis(reports[0])
    later = flow.start()  # a new claim supersedes the failed run
    assert flow.incident().active_run_id == later.run_id
    with pytest.raises(ReasoningBackendUnavailable):
        await flow.lifecycle.diagnose(flow.incident_id, asset_id=ASSET, runtime=backend, evidence_service=flow.evidence_service)
    assert flow.incident().phase == m.IncidentPhase.INVESTIGATING


async def test_packet_backend_requires_snapshot_and_refuses_mismatched_store(flow, tmp_path):
    from core.reliability.evidence import EvidenceCapabilities, EvidenceService
    backend = packet_backend([lazy_decision("UNRESOLVED")])
    snapshot = flow.start()
    context = SpecialistContext.model_validate(snapshot.context_payload)
    with pytest.raises(ValueError, match="snapshot"):
        await backend.supervise(flow.evidence_service, context, bounds=None)
    mismatched = EvidenceService(flow.repo, EvidenceCapabilities(tmp_path / "other.db"))
    with pytest.raises(ReasoningBackendUnavailable) as failure:
        await backend.supervise(mismatched, context, bounds=context and __import__("core.agents.contracts", fromlist=["SupervisorBounds"]).SupervisorBounds(), snapshot=snapshot)
    assert failure.value.code == "PACKET_INVALID" and not backend.runtime._model.calls


def test_backend_from_environment_modes(monkeypatch):
    forbidden = Mock(side_effect=AssertionError("no AWS session at construction"))
    monkeypatch.setattr("core.agents.runtime.boto3.Session", forbidden)
    monkeypatch.setenv("OPERON_REASONING_BACKEND", "none")
    assert backend_from_environment() is None
    monkeypatch.setenv("OPERON_REASONING_BACKEND", "local")
    local = backend_from_environment()
    assert isinstance(local, LocalStrandsBackend) and local.runtime.settings.live_enabled
    assert local.runtime.settings.model_id == config.BEDROCK_SUPERVISOR_MODEL_ID and local.specialist_runtime is None
    monkeypatch.setattr(config, "BEDROCK_SPECIALIST_MODEL_ID", "specialist-model")
    monkeypatch.setenv("OPERON_REASONING_BACKEND", "packet")
    packet = backend_from_environment()
    assert isinstance(packet, InProcessPacketBackend) and packet.specialist_runtime.settings.model_id == "specialist-model"
    assert packet.expected_identity().specialist_model_id == "specialist-model"
    monkeypatch.setenv("OPERON_REASONING_BACKEND", "agentcore")
    with pytest.raises(RuntimeConfigurationError, match="15B"):
        backend_from_environment()
    monkeypatch.setenv("OPERON_REASONING_BACKEND", "cloud")
    with pytest.raises(RuntimeConfigurationError, match="unknown"):
        backend_from_environment()
    monkeypatch.delenv("OPERON_REASONING_BACKEND")
    assert config.reasoning_backend() == "none" and backend_from_environment() is None
    monkeypatch.setattr(config, "agent_mode", lambda: "bedrock")
    assert config.reasoning_backend() == "local" and isinstance(backend_from_environment(), LocalStrandsBackend)
    forbidden.assert_not_called()


def test_engine_selects_backend_from_environment_without_clients(seeded_db, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("no AWS session at engine construction"))
    monkeypatch.setattr("core.agents.runtime.boto3.Session", forbidden)
    assert make_engine(monkeypatch).runtime is None
    monkeypatch.setenv("OPERON_REASONING_BACKEND", "packet")
    engine = make_engine(monkeypatch)
    assert isinstance(engine.runtime, InProcessPacketBackend) and engine.snapshot()["authority_path"] == "lifecycle"
    monkeypatch.setenv("OPERON_REASONING_BACKEND", "agentcore")
    assert make_engine(monkeypatch).runtime is None
    forbidden.assert_not_called()
