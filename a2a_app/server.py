"""
Sentinel A2A peer server.

Hosts two peer agents behind the A2A protocol:

  * **Governance** — rules APPROVE / CONDITIONS / VETO on a proposed work package.
  * **Monitoring** — assesses the active-alert set for systemic patterns.

Each agent's reasoning is the same deterministic engine used by the `local`
adapters (`core/services/adapters/local.py`), so there is no duplicated logic —
this server just wraps that logic in A2A agent executors and publishes an agent
card for each. Both are mounted on one Starlette app (one port), under
``/governance`` and ``/monitoring``.

    uv run python -m a2a_app.server         # serves on :8200 (SENTINEL_A2A_PORT)

An A2A client (see core/services/adapters/a2a_adapter.py, selected with
SENTINEL_GOVERNANCE_ADAPTER=a2a) resolves the agent card at
``<base>/governance/.well-known/agent.json`` and sends it the proposal as a
message; the agent replies with the verdict as JSON.
"""
from __future__ import annotations
import json
import os
import sys
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from a2a.server.apps import A2AStarletteApplication
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.utils import new_agent_text_message
from a2a.types import AgentCard, AgentSkill, AgentCapabilities

from core import config
from core.services.adapters.local import LocalGovernanceAdapter, LocalMonitoringAdapter


# ---------------------------------------------------------------------------
# Executors — wrap the deterministic engines as A2A agents. Input arrives as the
# user message text (a JSON payload); the reply is the result as JSON text.
# ---------------------------------------------------------------------------
class _JsonExecutor(AgentExecutor):
    def _handle(self, payload: dict) -> dict:  # override
        raise NotImplementedError

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        raw = context.get_user_input() or "{}"
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
        result = self._handle(payload)
        await event_queue.enqueue_event(new_agent_text_message(json.dumps(result, default=str)))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("cancel is not supported")


class GovernanceExecutor(_JsonExecutor):
    def _handle(self, payload: dict) -> dict:
        return LocalGovernanceAdapter().review_plan(payload)


class MonitoringExecutor(_JsonExecutor):
    def _handle(self, payload: dict) -> dict:
        return LocalMonitoringAdapter().assess(payload)


# ---------------------------------------------------------------------------
# Agent cards
# ---------------------------------------------------------------------------
def _governance_card(url: str) -> AgentCard:
    return AgentCard(
        name="Sentinel Governance Agent",
        description="Policy authority that rules APPROVE / CONDITIONS / VETO on a proposed "
                    "maintenance work package before a human approves it.",
        url=url, version="1.0.0",
        default_input_modes=["text"], default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[AgentSkill(
            id="review_plan", name="Review maintenance plan",
            description="Rule on a proposed repair work package against maintenance policy "
                        "(technician certification, critical-spare availability, spend authority, "
                        "failure-probability justification).",
            tags=["governance", "policy", "maintenance", "approval"],
            examples=["Review this proposed work package and return a policy decision."])],
    )


def _monitoring_card(url: str) -> AgentCard:
    return AgentCard(
        name="Sentinel Monitoring Agent",
        description="Reliability analyst that assesses the active-alert set for systemic "
                    "patterns and recommends escalation.",
        url=url, version="1.0.0",
        default_input_modes=["text"], default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[AgentSkill(
            id="assess", name="Assess fleet alerts",
            description="Correlate the active alerts (by equipment class and failure mode) to "
                        "detect systemic issues and decide whether to escalate.",
            tags=["monitoring", "reliability", "correlation", "escalation"],
            examples=["Assess these active alerts for common-cause patterns."])],
    )


def _agent_app(card: AgentCard, executor: AgentExecutor):
    handler = DefaultRequestHandler(agent_executor=executor, task_store=InMemoryTaskStore())
    return A2AStarletteApplication(agent_card=card, http_handler=handler).build()


def build_app(base_url: str | None = None) -> Starlette:
    base = (base_url or config.A2A_BASE_URL).rstrip("/")
    # NB: the mounted RPC endpoint is the mount root, which Starlette serves with a
    # trailing slash — advertise that exact URL so clients POST to it directly.
    return Starlette(routes=[
        Mount("/governance", app=_agent_app(_governance_card(f"{base}/governance/"),
                                            GovernanceExecutor())),
        Mount("/monitoring", app=_agent_app(_monitoring_card(f"{base}/monitoring/"),
                                            MonitoringExecutor())),
    ])


def main() -> None:
    host = os.getenv("SENTINEL_A2A_HOST", config.A2A_HOST)
    port = int(os.getenv("SENTINEL_A2A_PORT", str(config.A2A_PORT)))
    print(f"  Sentinel A2A peers -> http://{host}:{port}/governance  &  /monitoring")
    uvicorn.run(build_app(), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
