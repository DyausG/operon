"""
Sentinel MCP server (FastMCP).

Exposes the maintenance agent's governed capabilities as MCP **tools**, backed by
the same services layer (`core/services/`) the in-app agent uses. This is how an
external host — Claude Desktop, another agent, or a future A2A peer — reaches the
governed data model without reaching into the database directly.

The tools are thin wrappers over the service interfaces, so they stay grounded in
real data (the anti-hallucination semantic layer). This process always uses the
**local** SQLite adapters — never the `mcp` client adapter — so a client that
selects `SENTINEL_*_ADAPTER=mcp` and spawns this server can never recurse.

Run it:

    uv run python -m mcp_app.server                 # stdio (for a spawning client)
    uv run python -m mcp_app.server --http           # streamable-http on :8100
    SENTINEL_MCP_TRANSPORT=streamable-http uv run python -m mcp_app.server

Register it with Claude Desktop (stdio) — see docs/EXTENDING.md.
"""
from __future__ import annotations
import os
import sys

# Force local adapters for THIS process before importing the services layer, so
# an MCP-client adapter (SENTINEL_*_ADAPTER=mcp) that spawns us can't cause a loop.
for _domain in ("INVENTORY", "WORKFORCE", "SCHEDULING", "CMMS", "NOTIFICATIONS"):
    os.environ[f"SENTINEL_{_domain}_ADAPTER"] = "local"

# Ensure the project root is importable when launched as a spawned subprocess.
import pathlib
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP

from core import services
from core.db import get_conn, init_schema
from core.seed_data import seed
from core.tools import get_equipment, get_failure_mode_by_code


def _ensure_seeded() -> None:
    """Make standalone use work: create the schema and seed master data if the
    fleet is empty (a client spawned by the running app shares its already-seeded
    DB, so this is a no-op in that path)."""
    init_schema()
    try:
        with get_conn() as c:
            n = c.execute("SELECT COUNT(*) n FROM equipment").fetchone()["n"]
    except Exception:
        n = 0
    if not n:
        seed()


mcp = FastMCP(
    "sentinel-maintenance",
    host=os.getenv("SENTINEL_MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("SENTINEL_MCP_PORT", "8100")),
)


# ---------------------------------------------------------------------------
# Read / plan tools (side-effect free or draft-only)
# ---------------------------------------------------------------------------
@mcp.tool()
def check_parts(equipment_id: str) -> dict:
    """Spare-parts availability for an asset (bill-of-materials + on-hand stock)."""
    return services.inventory().check_parts(equipment_id)


@mcp.tool()
def assign_technician(equipment_class: str, current_shift: str = "A") -> dict:
    """Best available, certified technician for an equipment class."""
    return services.workforce().assign_technician(equipment_class, current_shift)


@mcp.tool()
def block_schedule(equipment_id: str, window_min: int = 45) -> dict:
    """Propose a planned maintenance window so the repair avoids a line-down."""
    return services.scheduling().block_schedule(equipment_id, window_min)


@mcp.tool()
def notify_technician(technician_id: str | None, subject: str,
                      body: str = "", channel: str = "sms") -> dict:
    """Draft a dispatch page to a technician (draft only — not sent until approved)."""
    return services.notifications().notify(recipient_id=technician_id, subject=subject,
                                           body=body, channel=channel, send=False)


@mcp.tool()
def propose_work_order(equipment_id: str, failure_mode_id: str,
                       technician_id: str | None = None, detail: str = "",
                       priority: str = "HIGH") -> dict:
    """Draft a predictive CMMS work order (not written until a human approves)."""
    return services.cmms().propose_work_order(equipment_id, failure_mode_id,
                                              technician_id, detail, priority)


@mcp.tool()
def get_equipment_record(equipment_id: str) -> dict:
    """Look up an equipment master record (class, criticality, product tier)."""
    return get_equipment(equipment_id)


@mcp.tool()
def get_failure_mode(mode_code: str) -> dict:
    """Look up a failure-mode record (TWF | HDF | PWF | OSF)."""
    return get_failure_mode_by_code(mode_code)


# ---------------------------------------------------------------------------
# Governed writes (a human gates these via the app's approval flow)
# ---------------------------------------------------------------------------
@mcp.tool()
def raise_alert(equipment_id: str, severity: str, summary: str,
                source: str = "agent") -> dict:
    """Record a governed operational alert."""
    return services.notifications().raise_alert(equipment_id=equipment_id, severity=severity,
                                                summary=summary, source=source)


@mcp.tool()
def create_work_package(proposal: dict) -> dict:
    """Commit a complete repair work package (work order + reserved parts + labor
    booking + schedule hold + dispatch notification). This is the write-back path;
    in the app it runs only after a human approves."""
    return services.cmms().create_work_package(proposal)


def main() -> None:
    transport = os.getenv("SENTINEL_MCP_TRANSPORT", "stdio")
    if "--http" in sys.argv:
        transport = "streamable-http"
    elif "--sse" in sys.argv:
        transport = "sse"
    _ensure_seeded()
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
