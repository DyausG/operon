"""Focused detail lookup and lineage tests for the disposable Guided Demo."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json

import pytest

from core.demo import DemoScenarioRunner
from core.demo.artifacts import DemoArtifactGraphError, validate_demo_artifact_graph
from core.engine import DemoEngine


FLEET = [{"equipment_id": "AC-COMP-01", "name": "Air Compressor 01",
          "equipment_class": "COMPRESSOR", "criticality": "HIGH"}]


async def wait_status(runner: DemoScenarioRunner, status: str) -> dict:
    deadline = asyncio.get_running_loop().time() + 2
    while asyncio.get_running_loop().time() < deadline:
        state = runner.snapshot()
        if state and state["demo_scenario"]["status"] == status:
            return state
        await asyncio.sleep(.002)
    raise AssertionError(f"demo did not reach {status}")


def approval_intent(state: dict) -> dict:
    lifecycle = state["alerts"][0]["lifecycle"]
    return {key: lifecycle[key] for key in
            ("requirement_id", "intervention_id", "intervention_hash", "context_revision")}


async def completed_runner() -> DemoScenarioRunner:
    runner = DemoScenarioRunner(FLEET, time_scale=.001)
    await runner.start("AC-COMP-01")
    awaiting = await wait_status(runner, "awaiting_human_approval")
    assert (await runner.approve("AC-COMP-01", approval_intent(awaiting)))["ok"]
    await wait_status(runner, "complete")
    return runner


@pytest.mark.asyncio
async def test_major_demo_artifacts_are_detailed_indexed_and_simulated():
    runner = await completed_runner()
    artifacts = runner.artifacts()
    types = {item["artifact_type"] for item in artifacts}
    assert {
        "predictive_signal", "evidence", "technician_inspection", "specialist_activity",
        "specialist_advisory", "diagnosis", "diagnosis_validation", "intervention",
        "engineering_review", "operations_review", "critic_intervention_review",
        "intervention_validation", "inventory_reservation", "technician_assignment",
        "scheduling_record", "work_package", "approval_request", "approval_binding",
        "execution_receipt", "work_order", "recovery_observation",
        "outcome_verification", "incident_closure", "lifecycle_event",
    } <= types

    evidence = runner.artifact("DEMO-EVIDENCE-TREND")
    assert evidence["provenance"] == "SIMULATED" and evidence["live_model"] is False
    assert evidence["runtime"] == "operon.demo.guided-v1"
    assert evidence["payload"]["payload"]["vibration_mm_s"][-1] == 9.2
    assert evidence["incident_id"] == "DEMO-INCIDENT-01"
    assert evidence["equipment_id"] == "AC-COMP-01"

    advisory = runner.artifact("DEMO-ADV-DIAGNOSTIC-01")
    assert advisory["payload"]["structured_findings"]
    assert advisory["payload"]["evidence_references"]
    assert "chain_of_thought" not in json.dumps(advisory).lower()
    assert all(item["provenance"] == "SIMULATED" and item["live_model"] is False for item in artifacts)
    await runner.reset()


@pytest.mark.asyncio
async def test_snapshot_ids_activity_links_and_exact_plan_lineage_are_resolvable():
    runner = await completed_runner()
    state = runner.snapshot()
    view = state["alerts"][0]["lifecycle"]["read_model"]
    assert view["diagnosis"]["artifact_id"] == "DEMO-DIAGNOSIS-01"
    assert view["intervention"]["artifact_id"] == "DEMO-INTERVENTION-01"
    assert view["binding"]["work_package_id"] == "DEMO-WP-1042"
    assert view["execution_receipts"][0]["artifact_id"] == "DEMO-RECEIPT-01"
    assert view["outcomes"][0]["artifact_id"] == "DEMO-OUTCOME-01"
    assert all(item["artifact_id"] for run in view["agent_runs"] for item in run["delegations"])

    linked_events = {item["event_type"]: item["artifact_id"] for item in view["events"]
                     if item.get("represented_artifact_id") or item.get("artifact_id") != item["id"]}
    assert linked_events["EVIDENCE_ACQUIRED"] in {item["id"] for item in view["evidence"]}
    assert linked_events["DIAGNOSIS_CREATED"] == "DEMO-DIAGNOSIS-01"
    assert linked_events["DIAGNOSIS_VALIDATED"] == "DEMO-VERDICT-DIAGNOSIS"
    assert linked_events["INTERVENTION_CREATED"] == "DEMO-INTERVENTION-01"
    assert linked_events["APPROVAL_RECORDED"] == "DEMO-APPROVAL-01"
    assert linked_events["EXECUTION_CONFIRMED"] == "DEMO-RECEIPT-01"
    assert linked_events["RECOVERY_VERIFIED"] == "DEMO-OUTCOME-01"
    assert all(runner.artifact(item["artifact_id"]) is not None for item in view["events"])

    diagnosis = runner.artifact("DEMO-DIAGNOSIS-01")
    verdict = runner.artifact("DEMO-VERDICT-DIAGNOSIS")
    intervention = runner.artifact("DEMO-INTERVENTION-01")
    approval = runner.artifact("DEMO-APPROVAL-01")
    receipt = runner.artifact("DEMO-RECEIPT-01")
    outcome = runner.artifact("DEMO-OUTCOME-01")
    assert all(runner.artifact(item) for item in diagnosis["payload"]["evidence_ids"])
    assert verdict["payload"]["subject_artifact_id"] == diagnosis["id"]
    assert intervention["payload"]["diagnosis_id"] == diagnosis["id"]
    assert approval["payload"]["intervention_id"] == intervention["id"]
    assert approval["payload"]["work_package_id"] == "DEMO-WP-1042"
    assert receipt["payload"]["approval_binding_id"] == approval["id"]
    assert receipt["payload"]["work_package_id"] == approval["payload"]["work_package_id"]
    assert outcome["payload"]["execution_receipt_id"] == receipt["id"]
    assert all(runner.artifact(item)["artifact_type"] == "recovery_observation"
               for item in outcome["payload"]["observation_ids"])
    runner.validate_artifact_graph()
    await runner.reset()


@pytest.mark.asyncio
async def test_demo_artifact_http_lookup_and_reset_invalidation(seeded_db):
    from server import main as server_main

    previous = server_main.engine
    engine = DemoEngine(runtime=None)
    engine.demo_runner.time_scale = .001
    server_main.engine = engine
    try:
        await engine.start_guided_demo("AC-COMP-01")
        await wait_status(engine.demo_runner, "awaiting_human_approval")
        response = await server_main.demo_artifact("DEMO-DIAGNOSIS-01")
        assert response.status_code == 200
        assert json.loads(response.body)["artifact_type"] == "diagnosis"

        missing = await server_main.demo_artifact("DEMO-NOT-FOUND")
        assert missing.status_code == 404
        await engine.demo_runner.reset(publish=False)
        stale = await server_main.demo_artifact("DEMO-DIAGNOSIS-01")
        assert stale.status_code == 404
        assert engine.demo_runner.artifacts() == []

        await engine.demo_runner.start("AC-COMP-01")
        rebuilt = await wait_status(engine.demo_runner, "awaiting_human_approval")
        rebuilt_events = rebuilt["alerts"][0]["lifecycle"]["read_model"]["events"]
        rebuilt_ids = [item["id"] for item in engine.demo_runner.artifacts()]
        assert rebuilt_events[0]["id"] == "DEMO-EVENT-01"
        assert len(rebuilt_ids) == len(set(rebuilt_ids))
        assert engine.demo_runner.artifact("DEMO-DIAGNOSIS-01")["created_at"] == \
            json.loads(response.body)["created_at"]
        engine.demo_runner.validate_artifact_graph()
    finally:
        await engine.demo_runner.reset(publish=False)
        await engine.stop()
        server_main.engine = previous


@pytest.mark.asyncio
async def test_graph_validation_rejects_duplicates_and_broken_references():
    runner = await completed_runner()
    artifacts = runner.artifacts()
    validate_demo_artifact_graph(artifacts)

    with pytest.raises(DemoArtifactGraphError, match="duplicate demo artifact id"):
        validate_demo_artifact_graph(artifacts + [deepcopy(artifacts[0])])

    broken = deepcopy(artifacts)
    diagnosis = next(item for item in broken if item["artifact_type"] == "diagnosis")
    diagnosis["supporting_ids"].append("DEMO-MISSING-EVIDENCE")
    with pytest.raises(DemoArtifactGraphError, match="broken supporting_ids reference"):
        validate_demo_artifact_graph(broken)
    await runner.reset()
