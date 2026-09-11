"""Step 15A: the application-built packet and packet-backed read-only access."""
from pathlib import Path
import sqlite3

import pytest
from pydantic import ValidationError

from core.agents.contracts import SpecialistContext, SupervisorBounds
from core.agents.tools import RESOURCE_TOOL_NAMES
from core.reliability import models as m
from core.reliability.evidence import EvidenceDeferred, UnsupportedEvidenceCapability
from core.reliability.repository import InvalidReference
from core.reasoning import protocol
from core.reasoning.handler import handler_identity
from core.reasoning.packet import (
    DEFAULT_EVIDENCE_READS, PacketCapabilities, PacketEvidenceAccess, PacketTooLarge, SnapshotRepository,
    build_request,
)
from core.reasoning.protocol import MIN_SESSION_ID_LENGTH, ReasoningRequest, runtime_session_id
from tests.test_promotion import ASSET, Environment
from tests.test_strands_agents import ScriptedModel, protected_state, settings
from core.agents.runtime import StrandsRuntime


@pytest.fixture
def env(seeded_db):
    return Environment()


def make_request(env, snapshot=None, runtime=None):
    snapshot = snapshot or env.start()
    runtime = runtime or StrandsRuntime(settings(), model=ScriptedModel())
    context = SpecialistContext.model_validate(snapshot.context_payload)
    incident = env.repo.fetch_incident(env.incident_id)
    request = build_request(env.evidence_service, incident, context, SupervisorBounds.model_validate(snapshot.bounds),
                            snapshot_id=snapshot.id, expected_identity=handler_identity(runtime))
    return request, snapshot, context


def block_sqlite(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("packet access must never open SQLite")
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr("core.db.get_conn", forbidden)


@pytest.fixture
def no_sqlite():
    """Scoped guard: SQLite is blocked only inside the ``with`` block, never the fixtures."""
    def guard():
        context = pytest.MonkeyPatch.context()
        patcher = context.__enter__()
        block_sqlite(patcher)
        return context
    return guard


def test_build_request_matches_snapshot_and_covers_default_reads(env):
    request, snapshot, context = make_request(env)
    assert request.context.model_dump(mode="json") == snapshot.context_payload
    assert request.bounds.model_dump(mode="json") == snapshot.bounds
    assert (request.incident_id, request.run_id, request.snapshot_id, request.input_revision, request.stage) == (
        env.incident_id, snapshot.run_id, snapshot.id, snapshot.input_revision, "DIAGNOSIS")
    assert request.incident.revision == snapshot.input_revision and request.incident.active_run_id == snapshot.run_id
    names = [item.capability for item in request.reads]
    assert set(names) == {capability for capability, _ in DEFAULT_EVIDENCE_READS} | RESOURCE_TOOL_NAMES
    assert len(names) == len(set(names))
    assert request.runtime_session_id == runtime_session_id(snapshot.run_id) == f"operon-run-{snapshot.run_id}"
    assert len(request.runtime_session_id) >= MIN_SESSION_ID_LENGTH
    assert len(request.model_dump_json().encode()) < protocol.MAX_REQUEST_BYTES
    # Round trip through JSON, as the wire would carry it.
    assert ReasoningRequest.model_validate_json(request.model_dump_json()) == request


def test_oversized_read_and_oversized_request_are_refused_not_truncated(env, monkeypatch):
    snapshot = env.start()
    capabilities = env.evidence_service.capabilities
    original = capabilities.collect
    def oversized(capability, asset_id, parameters, **kwargs):
        result = original(capability, asset_id, parameters, **kwargs)
        if capability == "get_asset_context":
            return result.model_copy(update={"asset_name": "x" * 48_000})
        return result
    monkeypatch.setattr(capabilities, "collect", oversized)
    with pytest.raises(PacketTooLarge, match="48000"):
        make_request(env, snapshot)
    monkeypatch.setattr(capabilities, "collect", original)
    monkeypatch.setattr(protocol, "MAX_REQUEST_BYTES", 2_000)
    with pytest.raises(PacketTooLarge, match="exceeds"):
        make_request(env, snapshot)


@pytest.mark.parametrize("tamper", [
    {"incident_id": "other"}, {"run_id": "another-run-identifier-of-length"}, {"input_revision": 99},
    {"asset_id": "HYD-PUMP-03"}, {"stage": "INTERVENTION_REVIEW"}, {"runtime_session_id": "operon-run-" + "x" * 30},
    {"protocol_version": "operon-reasoning-0"}, {"authority": True},
])
def test_incoherent_or_foreign_request_is_rejected(env, tamper):
    request, _, _ = make_request(env)
    with pytest.raises(ValidationError):
        ReasoningRequest.model_validate(request.model_dump(mode="json") | tamper)


def test_request_refuses_incident_that_is_not_the_frozen_checkpoint(env):
    request, _, _ = make_request(env)
    payload = request.model_dump(mode="json")
    payload["incident"]["revision"] = payload["incident"]["revision"] + 1
    with pytest.raises(ValidationError, match="checkpoint"):
        ReasoningRequest.model_validate(payload)
    payload = request.model_dump(mode="json")
    payload["incident"]["active_run_id"] = None
    with pytest.raises(ValidationError, match="checkpoint"):
        ReasoningRequest.model_validate(payload)


def test_packet_capabilities_serve_normalized_reads_without_sqlite(env, monkeypatch):
    request, _, context = make_request(env)
    block_sqlite(monkeypatch)
    capabilities = PacketCapabilities(request.reads, asset_id=ASSET, incident_id=env.incident_id)
    assert not hasattr(capabilities, "path")
    window = capabilities.collect("get_telemetry_window", ASSET, {"sample_limit": 60}, incident_id=env.incident_id)
    expected = next(item for item in request.reads if item.capability == "get_telemetry_window")
    assert window.model_dump(mode="json") == expected.result
    assert capabilities.get_asset_context(ASSET).model_dump(mode="json") == next(
        item for item in request.reads if item.capability == "get_asset_context").result
    with pytest.raises(ValueError, match="not in the remote packet"):
        capabilities.collect("get_telemetry_window", ASSET, {"sample_limit": 61})
    with pytest.raises(ValueError, match="not in the remote packet"):
        capabilities.collect("get_health_score_window", ASSET, {})
    with pytest.raises(InvalidReference, match="outside"):
        capabilities.collect("get_asset_context", "HYD-PUMP-03", {})
    with pytest.raises(InvalidReference, match="outside"):
        capabilities.collect("get_related_incidents", ASSET, {}, incident_id="foreign")
    with pytest.raises(UnsupportedEvidenceCapability):
        capabilities.collect("arbitrary_sql", ASSET, {})
    with pytest.raises(ValueError, match="manifests"):
        capabilities.collect_with_dependencies("get_asset_context", ASSET, {})
    with pytest.raises(ValueError, match="manifests"):
        capabilities.expected_dependencies(None, "get_asset_context", ASSET, {}, incident_id=None)


def test_packet_resource_reads_are_served_and_bounded(env, monkeypatch):
    request, _, _ = make_request(env)
    block_sqlite(monkeypatch)
    resources = PacketEvidenceAccess(request).resource_reads()
    for name in RESOURCE_TOOL_NAMES:
        expected = next(item for item in request.reads if item.capability == name)
        assert getattr(resources, name)(ASSET, limit=20).model_dump(mode="json") == expected.result
        with pytest.raises(ValueError, match="not in the remote packet"):
            getattr(resources, name)(ASSET, limit=5)
        with pytest.raises(InvalidReference):
            getattr(resources, name)("HYD-PUMP-03", limit=20)
    with pytest.raises(ValidationError):
        resources.check_part_availability(ASSET, limit=51)


def test_snapshot_repository_exposes_only_packet_artifacts(env, monkeypatch):
    request, _, context = make_request(env)
    other = env.repo.create_incident(("HYD-PUMP-03",), admission_key="other-incident")
    foreign = env.evidence_service.request_and_collect(
        other.id, requested_by="diagnostic", equipment_ids=("HYD-PUMP-03",), question="Read other asset",
        capability="get_asset_context", required_for="diagnosis").evidence
    block_sqlite(monkeypatch)
    repository = SnapshotRepository(request.incident, context)
    assert repository.fetch_incident(env.incident_id) == request.incident
    for item in context.evidence:
        assert repository.get_artifact(env.incident_id, item.id) == item
    with pytest.raises(InvalidReference):
        repository.fetch_incident(other.id)
    with pytest.raises(InvalidReference):
        repository.get_artifact(env.incident_id, foreign.id)
    with pytest.raises(InvalidReference):
        repository.get_artifact(other.id, foreign.id)
    with pytest.raises(InvalidReference):
        repository.get_artifact(env.incident_id, "unknown")


def test_packet_access_defers_supported_needs_and_never_writes(env, no_sqlite):
    request, _, _ = make_request(env)
    before = protected_state(env.repo, env.incident_id)
    artifacts = env.repo.list_artifacts(env.incident_id)
    guard = no_sqlite()
    access = PacketEvidenceAccess(request)
    assert access.same_store() is True
    with pytest.raises(EvidenceDeferred) as deferred:
        access.request_and_collect(env.incident_id, requested_by="diagnostic", equipment_ids=(ASSET,),
                                   question=" Collect a longer window ", capability="get_telemetry_window",
                                   required_for="diagnosis", parameters={"sample_limit": 120})
    assert deferred.value.parameters == {"sensor_type": None, "start_at": None, "end_at": None, "sample_limit": 120}
    assert (deferred.value.requested_by, deferred.value.capability, deferred.value.question, deferred.value.required_for) == (
        "diagnostic", "get_telemetry_window", "Collect a longer window", "diagnosis")
    with pytest.raises(UnsupportedEvidenceCapability):
        access.request_and_collect(env.incident_id, requested_by="diagnostic", equipment_ids=(ASSET,),
                                   question="q", capability="inspection", required_for="diagnosis")
    with pytest.raises(ValidationError):
        access.request_and_collect(env.incident_id, requested_by="diagnostic", equipment_ids=(ASSET,),
                                   question="q", capability="get_telemetry_window", required_for="diagnosis",
                                   parameters={"sample_limit": 501})
    with pytest.raises(InvalidReference):
        access.request_and_collect("other", requested_by="diagnostic", equipment_ids=(ASSET,),
                                   question="q", capability="get_asset_context", required_for="diagnosis")
    with pytest.raises(InvalidReference):
        access.request_and_collect(env.incident_id, requested_by="diagnostic", equipment_ids=("HYD-PUMP-03",),
                                   question="q", capability="get_asset_context", required_for="diagnosis")
    with pytest.raises(ValueError, match="outcome|diagnosis or intervention"):
        access.request_and_collect(env.incident_id, requested_by="diagnostic", equipment_ids=(ASSET,),
                                   question="q", capability="get_asset_context", required_for="outcome")
    with pytest.raises(ValueError, match="supersede"):
        access.request_and_collect(env.incident_id, requested_by="diagnostic", equipment_ids=(ASSET,),
                                   question="q", capability="get_asset_context", required_for="diagnosis",
                                   supersedes_evidence_id="x")
    guard.__exit__(None, None, None)
    assert protected_state(env.repo, env.incident_id) == before
    assert env.repo.list_artifacts(env.incident_id) == artifacts


def test_reasoning_modules_never_open_the_store():
    root = Path(__file__).resolve().parents[1] / "core" / "reasoning"
    for path in root.glob("*.py"):
        source = path.read_text()
        assert "import sqlite3" not in source, path
        assert "get_conn" not in source, path
        assert "IncidentRepository(" not in source, path
        assert "_write()" not in source, path
    handler = (root / "handler.py").read_text()
    assert "from core.reliability.repository import InvalidReference" in handler
    assert "add_artifact" not in handler and "request_and_collect" not in handler
