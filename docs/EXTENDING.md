# Extending Sentinel — the services layer

Sentinel is built so you can go past the on-screen demo and wire the agent to
**your own systems**. The Maintenance Agent never talks to a database or an API
directly. It calls **service interfaces**, and each interface is fulfilled by a
swappable **adapter**. Swap the adapter, keep the agent — the classic
ports-and-adapters (hexagonal) pattern.

```
        agent.py / tools.py                core/services/base.py
        (never changes)          depends on    (interfaces / "ports")
                │                                     ▲
                ▼                                     │  implements
        core/services/registry.py  ── selects ──►  adapters
        (SENTINEL_<DOMAIN>_ADAPTER)                 ├─ local  (SQLite, shipped)
                                                    └─ yours  (Maximo, SAP, …)
```

## The five services

| Domain (env)     | Interface (`core/services/base.py`) | The agent uses it to… |
|------------------|-------------------------------------|-----------------------|
| `inventory`      | `InventoryService`     | check spare-parts availability |
| `workforce`      | `WorkforceService`     | assign a certified, available technician |
| `scheduling`     | `SchedulingService`    | reserve a planned maintenance window |
| `cmms`           | `CmmsService`          | draft a work order, and on approval assemble a full **repair work package** |
| `notifications`  | `NotificationService`  | raise operational alerts and page technicians |

Every method takes and returns plain JSON-serializable `dict`s, so the same
interface works in-process today or over HTTP / MCP later without the agent
changing. Return-shape contracts are documented on each method in `base.py`.

## Selecting an adapter

Each domain reads `SENTINEL_<DOMAIN>_ADAPTER`, defaulting to `local`:

```bash
# .env or environment
SENTINEL_CMMS_ADAPTER=maximo
SENTINEL_NOTIFICATIONS_ADAPTER=pagerduty
# unset domains keep the bundled SQLite 'local' adapter
```

## Writing your own adapter

1. **Implement the interface.** Subclass the port and implement its methods.

   ```python
   # myplant/adapters.py
   from core.services.base import CmmsService

   class MaximoCmmsAdapter(CmmsService):
       def __init__(self):
           self.client = MaximoClient(base_url=os.environ["MAXIMO_URL"], ...)

       def propose_work_order(self, equipment_id, failure_mode_id, technician_id, detail, priority="HIGH"):
           # return a DRAFT dict — nothing is written yet (human approval gates it)
           return {"equipment_id": equipment_id, "failure_mode_id": failure_mode_id,
                   "technician_id": technician_id, "priority": priority, "detail": detail,
                   "status": "DRAFT", "wo_number": "DRAFT"}

       def commit_work_order(self, proposal):
           wo = self.client.create_workorder(...)          # real POST to Maximo
           return {"wo_id": wo.id, "wo_number": wo.wonum, "status": "OPEN"}

       def create_work_package(self, proposal):
           # orchestrate: work order + parts reservation + labor + schedule + notify
           ...
           return {"wo_id": ..., "wo_number": ..., "package_number": ...,
                   "status": "READY", "reserved_parts": [...],
                   "labor_booking": {...}, "notification": {...}}
   ```

2. **Register it under a name.**

   ```python
   from core.services.registry import register
   register("cmms", "maximo", MaximoCmmsAdapter)
   ```

3. **Make sure the registration runs**, then select it. Import your module once at
   startup (e.g. from `server/main.py`), then set `SENTINEL_CMMS_ADAPTER=maximo`.
   The bundled `local` adapters register themselves via
   `core/services/adapters/__init__.py` — use that as the template.

The reference implementation lives in `core/services/adapters/local.py`; it is
deliberately small so it doubles as a worked example.

## Human-in-the-loop is a contract, not an accident

Anything that *writes to the outside world* must happen only after approval:

- `propose_work_order` and `notify(..., send=False)` are **drafts** — surfaced in
  the agent's reasoning trace but never persisted/sent.
- The write-back (`create_work_package`, which sends the dispatch page) runs from
  `engine.approve()` — i.e. after a human clicks **Approve & dispatch**.

Keep this split when you implement an adapter: do reads and drafts during
planning; do writes and sends only in the commit path.

## MCP — the services as tools

The same capabilities are exposed over **MCP** (Model Context Protocol) by a
FastMCP server, `mcp_app/server.py`. This is how an external host — Claude
Desktop, another agent, a future A2A peer — reaches the governed data model
without touching the database. The server's tools are thin wrappers over the
very same service interfaces, so nothing is duplicated.

**Run the server**

```bash
uv run python -m mcp_app.server            # stdio (for a spawning client)
uv run python -m mcp_app.server --http      # streamable-http on :8100
```

**Register it with Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "sentinel-maintenance": {
      "command": "uv",
      "args": ["run", "python", "-m", "mcp_app.server"],
      "cwd": "/absolute/path/to/agentic-predictive-maintenance"
    }
  }
}
```

**Point the agent's own tools at MCP.** There is an `mcp` adapter behind every
service interface (`core/services/adapters/mcp_adapter.py`). Select it and the
agent reaches its capabilities *over MCP* instead of in-process — no agent-code
change:

```bash
SENTINEL_INVENTORY_ADAPTER=mcp
SENTINEL_WORKFORCE_ADAPTER=mcp
SENTINEL_CMMS_ADAPTER=mcp
# …etc
```

The `mcp` adapter self-spawns the server as a stdio subprocess (nothing to start
by hand, no port), holds one long-lived session on a background event loop, and
forces the spawned server to `local` adapters so a `mcp` selection can never
recurse. It proves the transport is swappable end to end; the default remains
`local` so the repo still runs fully offline.

> MCP is the transport for **tools**. It slots in as just another adapter behind
> these same interfaces — the interfaces are the contract, MCP is one way to
> satisfy them.

## A2A — the peer agents

Two capabilities are *agents*, not tools: they reason. So they're reached over
**A2A** (Agent-to-Agent), not MCP.

| Peer | Interface | What it decides |
|------|-----------|-----------------|
| **Governance** | `GovernanceService.review_plan(proposal)` | APPROVE / CONDITIONS / VETO on a proposed work package (certification, critical-spare availability, spend authority, failure-probability justification) |
| **Monitoring** | `MonitoringService.assess(snapshot)` | whether the active alerts show a systemic pattern (same class / same failure mode) worth escalating |

Both follow the same ports-and-adapters rule as everything else, with three
adapters:

- **`llm`** (the **default**) — reasons with Google Gemini, grounded in the plan /
  the alert set, and **self-degrades to the deterministic engine** whenever a
  Gemini key is absent (offline, CI) or a call is rate-limited past its retries.
  So it's always safe to select — it just uses the best available brain. Governance
  keeps a hard safety rule regardless of the model: no assigned technician → VETO.
- **`local`** — the deterministic policy / correlation engine. Pin it with
  `SENTINEL_GOVERNANCE_ADAPTER=local` / `SENTINEL_MONITORING_ADAPTER=local` (e.g.
  to conserve free-tier quota).
- **`a2a`** — reaches the peers as real agents over the A2A protocol (below).

The LLM peers share the agent's Gemini client + rate limiter (`core/gemini.py`),
so the whole app respects one free-tier budget; Monitoring also caches by
active-alert set so an unchanged set never re-spends a call.

- **Governance** runs when the agent assembles a plan — its verdict is added to
  the reasoning trace *before* the human approves, so the operator sees the policy
  ruling. It advises and can flag a VETO; the human still decides.
- **Monitoring** runs on the live alert set — when it finds a correlation it folds
  an escalation note into the triage rationale.

Both are best-effort: an unavailable peer never breaks the loop.

**Run the peer server** (hosts both agents on one port, under `/governance` and
`/monitoring`):

```bash
uv run python -m a2a_app.server           # serves on :8200 (SENTINEL_A2A_PORT)
```

Each publishes an A2A **agent card** at
`http://127.0.0.1:8200/<agent>/.well-known/agent.json`, so any A2A client (not
just Sentinel) can discover and call it.

**Point the Maintenance Agent's peers at A2A** — start the server above, then:

```bash
SENTINEL_GOVERNANCE_ADAPTER=a2a
SENTINEL_MONITORING_ADAPTER=a2a
SENTINEL_A2A_BASE=http://127.0.0.1:8200     # if not the default
```

The `a2a` adapter holds one persistent session on a background event loop and
marshals the sync interface calls onto it. The peers' logic is the *same*
deterministic engine the `local` adapters use (`core/services/adapters/local.py`)
— the A2A server just wraps it as agent executors, so nothing is duplicated. The
default stays `local`, so the repo still runs fully offline.

> **A2A is for agents; MCP is for tools.** Both are transports behind these same
> service interfaces — the interfaces are the contract. Governance and Monitoring
> are peers because they reason over a plan / the fleet; the CMMS and inventory
> capabilities are tools because they execute a lookup or a write.

## Bringing your own peer agent

Because the interface is the contract, you can replace either peer with your own
agent — a smarter LLM-backed governance reviewer, an ML anomaly-correlation
monitor — by implementing `GovernanceService` / `MonitoringService` and either
registering it directly (an in-process adapter) or standing it up as an A2A
service the bundled `a2a` adapter can already reach.
