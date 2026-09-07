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
