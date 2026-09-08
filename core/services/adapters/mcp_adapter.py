"""
MCP-client adapters — fulfil the service interfaces by calling the Operon MCP
server (`mcp_app/server.py`) over MCP, instead of touching SQLite directly.

Select per-domain with ``SENTINEL_<DOMAIN>_ADAPTER=mcp``. The agent code does not
change: it still calls the same interfaces; only the backend moves onto MCP.

Transport: the client **self-spawns** the server as a stdio subprocess, so there
is nothing to start by hand and no network port — the repo still "just runs".
The service interfaces are synchronous while the MCP client is async, so a single
background event-loop thread holds one long-lived session and every call is
marshalled onto it. The spawned server is forced to `local` adapters, so a
`mcp` selection can never recurse into itself.
"""
from __future__ import annotations
import asyncio
import atexit
import json
import os
import sys
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from ..base import (InventoryService, WorkforceService, SchedulingService,
                    CmmsService, NotificationService)
from ..registry import register

_CALL_TIMEOUT = float(os.getenv("SENTINEL_MCP_TIMEOUT", "30"))


def _parse(res) -> dict:
    """Turn a CallToolResult into the plain dict the interface promises."""
    if getattr(res, "isError", False):
        txt = "; ".join(getattr(b, "text", "") for b in (res.content or []))
        raise RuntimeError(f"MCP tool error: {txt}")
    sc = getattr(res, "structuredContent", None)
    if isinstance(sc, dict):
        # FastMCP wraps non-object returns as {"result": ...}; unwrap that case.
        return sc["result"] if set(sc.keys()) == {"result"} else sc
    for b in (res.content or []):
        t = getattr(b, "text", None)
        if t:
            try:
                return json.loads(t)
            except Exception:
                return {"text": t}
    return {}


class _Bridge:
    """One long-lived MCP session on a dedicated background event loop."""
    _instance: "_Bridge | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "_Bridge":
        with cls._lock:
            if cls._instance is None:
                cls._instance = _Bridge()
            return cls._instance

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None
        self._ready = threading.Event()
        self._err: Exception | None = None
        threading.Thread(target=self._run, name="mcp-bridge", daemon=True).start()
        if not self._ready.wait(timeout=_CALL_TIMEOUT) or self._err:
            raise self._err or TimeoutError("MCP server did not become ready")
        atexit.register(self.close)

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect())
        self._loop.run_forever()

    async def _connect(self):
        try:
            from core import config
            root = str(config.PROJECT_DIR)
            env = {**os.environ, "PYTHONPATH": root + os.pathsep + os.environ.get("PYTHONPATH", "")}
            for d in ("INVENTORY", "WORKFORCE", "SCHEDULING", "CMMS", "NOTIFICATIONS"):
                env[f"SENTINEL_{d}_ADAPTER"] = "local"      # the server must not recurse
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "mcp_app.server"], env=env, cwd=root)
            self._stack = AsyncExitStack()
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
        except Exception as e:  # surfaced to the constructor via _ready
            self._err = e
        finally:
            self._ready.set()

    def call(self, name: str, args: dict) -> dict:
        fut = asyncio.run_coroutine_threadsafe(self._call(name, args), self._loop)
        return fut.result(timeout=_CALL_TIMEOUT)

    async def _call(self, name: str, args: dict) -> dict:
        return _parse(await self._session.call_tool(name, args))

    def close(self):
        try:
            if self._stack is not None:
                asyncio.run_coroutine_threadsafe(self._stack.aclose(), self._loop).result(timeout=5)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)


# ---------------------------------------------------------------------------
# Adapters — each just marshals its interface call onto an MCP tool call.
# ---------------------------------------------------------------------------
class MCPInventoryAdapter(InventoryService):
    def check_parts(self, equipment_id: str) -> dict:
        return _Bridge.get().call("check_parts", {"equipment_id": equipment_id})


class MCPWorkforceAdapter(WorkforceService):
    def assign_technician(self, equipment_class: str, current_shift: str = "A") -> dict:
        return _Bridge.get().call("assign_technician",
                                  {"equipment_class": equipment_class, "current_shift": current_shift})


class MCPSchedulingAdapter(SchedulingService):
    def block_schedule(self, equipment_id: str, window_min: int = 45) -> dict:
        return _Bridge.get().call("block_schedule",
                                  {"equipment_id": equipment_id, "window_min": window_min})


class MCPNotificationAdapter(NotificationService):
    def raise_alert(self, *, equipment_id: str, severity: str,
                    summary: str, source: str = "agent") -> dict:
        return _Bridge.get().call("raise_alert", {"equipment_id": equipment_id,
                                  "severity": severity, "summary": summary, "source": source})

    def notify(self, *, recipient_id, subject: str, body: str,
               channel: str = "sms", send: bool = True, wo_id=None,
               authorization=None) -> dict:
        # Over MCP this drafts the page; the actual send happens server-side inside
        # create_work_package, so the client only ever needs the draft path.
        if send:
            raise PermissionError("MCP dispatch must use execute_governed_intervention")
        return _Bridge.get().call("notify_technician", {"technician_id": recipient_id,
                                  "subject": subject, "body": body, "channel": channel})


class MCPCmmsAdapter(CmmsService):
    def propose_work_order(self, equipment_id, failure_mode_id, technician_id,
                           detail, priority="HIGH") -> dict:
        return _Bridge.get().call("propose_work_order", {"equipment_id": equipment_id,
                                  "failure_mode_id": failure_mode_id, "technician_id": technician_id,
                                  "detail": detail, "priority": priority})

    def create_work_package(self, proposal: dict, *, authorization=None) -> dict:
        raise PermissionError("MCP work-package commits must use execute_governed_intervention")

    def commit_work_order(self, proposal: dict, *, authorization=None) -> dict:
        raise PermissionError("MCP work-order commits must use execute_governed_intervention")


# ---------------------------------------------------------------------------
# Register under the name "mcp" (selected via SENTINEL_<DOMAIN>_ADAPTER=mcp).
# ---------------------------------------------------------------------------
register("inventory", "mcp", MCPInventoryAdapter)
register("workforce", "mcp", MCPWorkforceAdapter)
register("scheduling", "mcp", MCPSchedulingAdapter)
register("cmms", "mcp", MCPCmmsAdapter)
register("notifications", "mcp", MCPNotificationAdapter)
