"""
A2A-client adapters — fulfil the Governance and Monitoring interfaces by
consulting the peer agents over the A2A protocol (`a2a_app/server.py`) instead
of running the deterministic engine in-process.

Select with ``SENTINEL_GOVERNANCE_ADAPTER=a2a`` / ``SENTINEL_MONITORING_ADAPTER=a2a``.
The agent code does not change — it still calls the same interfaces; only the
peer moves onto A2A.

Unlike the MCP tool adapter (which self-spawns a stdio server), A2A peers are
HTTP services run separately — start them with ``uv run python -m a2a_app.server``
and point the adapter at them with ``SENTINEL_A2A_BASE`` (default
http://127.0.0.1:8200). The service interfaces are synchronous while the A2A
client is async, so one background event-loop thread holds a persistent
``httpx`` client and every call is marshalled onto it.
"""
from __future__ import annotations
import asyncio
import atexit
import json
import os
import threading
import uuid

import httpx
from a2a.client import A2AClient, A2ACardResolver
from a2a.types import (Message, Part, TextPart, Role, SendMessageRequest,
                       MessageSendParams)

from ..base import GovernanceService, MonitoringService
from ..registry import register

_TIMEOUT = float(os.getenv("SENTINEL_A2A_TIMEOUT", "30"))


def _extract(resp) -> dict:
    """Pull the JSON reply out of a SendMessageResponse (Message or Task)."""
    root = getattr(resp, "root", resp)
    result = getattr(root, "result", None)
    if result is None:
        raise RuntimeError(f"A2A error response: {getattr(root, 'error', root)}")
    parts = getattr(result, "parts", None)
    if parts is None and hasattr(result, "status"):        # a Task
        msg = getattr(result.status, "message", None)
        parts = getattr(msg, "parts", []) if msg else []
    text = "".join(getattr(getattr(p, "root", p), "text", "") for p in (parts or []))
    try:
        return json.loads(text)
    except Exception:
        return {"text": text}


class _A2ABridge:
    _instance: "_A2ABridge | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "_A2ABridge":
        with cls._lock:
            if cls._instance is None:
                cls._instance = _A2ABridge()
            return cls._instance

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._http: httpx.AsyncClient | None = None
        self._clients: dict[str, A2AClient] = {}
        self._ready = threading.Event()
        self._err: Exception | None = None
        threading.Thread(target=self._run, name="a2a-bridge", daemon=True).start()
        if not self._ready.wait(timeout=_TIMEOUT) or self._err:
            raise self._err or TimeoutError("A2A bridge did not start")
        atexit.register(self.close)

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect())
        self._loop.run_forever()

    async def _connect(self):
        try:
            self._http = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True)
        except Exception as e:
            self._err = e
        finally:
            self._ready.set()

    async def _client_for(self, agent: str) -> A2AClient:
        if agent not in self._clients:
            from core import config
            base = f"{config.A2A_BASE_URL.rstrip('/')}/{agent}"
            card = await A2ACardResolver(self._http, base_url=base).get_agent_card()
            self._clients[agent] = A2AClient(self._http, agent_card=card)
        return self._clients[agent]

    def call(self, agent: str, payload: dict) -> dict:
        fut = asyncio.run_coroutine_threadsafe(self._call(agent, payload), self._loop)
        return fut.result(timeout=_TIMEOUT)

    async def _call(self, agent: str, payload: dict) -> dict:
        client = await self._client_for(agent)
        msg = Message(role=Role.user, message_id=uuid.uuid4().hex, kind="message",
                      parts=[Part(root=TextPart(text=json.dumps(payload, default=str)))])
        req = SendMessageRequest(id=uuid.uuid4().hex, params=MessageSendParams(message=msg))
        return _extract(await client.send_message(req))

    def close(self):
        try:
            if self._http is not None:
                asyncio.run_coroutine_threadsafe(self._http.aclose(), self._loop).result(timeout=5)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)


class A2AGovernanceAdapter(GovernanceService):
    def review_plan(self, proposal: dict) -> dict:
        return _A2ABridge.get().call("governance", proposal)


class A2AMonitoringAdapter(MonitoringService):
    def assess(self, snapshot: dict) -> dict:
        return _A2ABridge.get().call("monitoring", snapshot)


register("governance", "a2a", A2AGovernanceAdapter)
register("monitoring", "a2a", A2AMonitoringAdapter)
