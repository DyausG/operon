"""MCP round-trip (integration): the `mcp` adapter self-spawns the FastMCP server
as a stdio subprocess and calls the governed tools over MCP.

Deselect with `-m 'not integration'`.
"""
from __future__ import annotations
import pytest

pytestmark = pytest.mark.integration


def test_mcp_adapter_round_trips(seeded_db, monkeypatch):
    monkeypatch.setenv("SENTINEL_INVENTORY_ADAPTER", "mcp")
    monkeypatch.setenv("SENTINEL_WORKFORCE_ADAPTER", "mcp")

    from core import services, tools
    services.reset_cache()

    # these calls execute in the spawned MCP server process (shares the temp DB)
    parts = tools.check_parts("AC-COMP-01")
    assert "on hand" in parts["summary"]
    assert isinstance(parts["parts"], list) and parts["parts"]

    tech = tools.assign_technician("COMPRESSOR")
    assert tech["technician"]["technician_id"] == "TECH-201"

    # confirm the adapter really is the MCP one, not local
    from core.services.adapters.mcp_adapter import MCPInventoryAdapter
    assert isinstance(services.inventory(), MCPInventoryAdapter)

    # The transport no longer exposes raw consequential writes. Its only write
    # entry loads durable incident/intervention state and evaluates policy.
    from core.services.adapters.mcp_adapter import _Bridge
    with pytest.raises(RuntimeError, match="Unknown tool"):
        _Bridge.get().call("create_work_package", {"proposal": {}})
    with pytest.raises(RuntimeError):
        _Bridge.get().call("execute_governed_intervention", {
            "incident_id": "missing", "intervention_id": "missing"})

    from core.reliability.governance import ApprovalLedger
    from core.reliability.legacy import prepare_legacy_intervention
    from core.reliability.repository import IncidentRepository
    from tests.conftest import sample_proposal
    repo = IncidentRepository()
    incident = repo.create_incident(("AC-COMP-01",), admission_key="mcp-governed-test")
    proposal = sample_proposal()
    proposal["criticality"] = "HIGH"
    proposal["governance"] = {"decision": "APPROVE", "reasons": [], "conditions": []}
    prepared = prepare_legacy_intervention(repo, incident.id, proposal)
    ApprovalLedger(repo).decide(
        incident.id, prepared.requirement.id, actor_id="mcp-test-manager",
        actor_role="maintenance_approver", decision="APPROVE", rationale="MCP integration test")
    result = _Bridge.get().call("execute_governed_intervention", {
        "incident_id": incident.id, "intervention_id": prepared.intervention.id})
    assert result["phase"] == "OBSERVING"
    assert repo.list_execution_receipts(incident.id)[0].status == "CONFIRMED"
