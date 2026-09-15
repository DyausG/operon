"""AI provider configuration API (Stage 0).

Read provider status and capabilities, select the active provider/model, change
non-secret fields, run a connection test, and (Gemini only) set a session-scoped
API key. Responses never carry a credential: ``ProviderStatus`` has no secret
field and the registry keeps keys as ``SecretStr`` in process memory only.

Secret submission is accepted only from a loopback client or when the deployment
declares its host boundary trusted (OPERON_TRUSTED_SUBMISSIONS=1), because this
host has no authentication layer. Nothing here logs request bodies.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from core import config
from core.providers import PROVIDER_KINDS, SELECTIONS, ProviderError

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})
TEST_TIMEOUT_SECONDS = 20.0


class SelectCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=20)
    model: str | None = Field(default=None, max_length=300)


class UpdateCommand(BaseModel):
    """Non-secret fields plus the one session-scoped secret (Gemini ``api_key``)."""
    model_config = ConfigDict(extra="forbid")
    model: str | None = Field(default=None, max_length=300)
    model_id: str | None = Field(default=None, max_length=300)
    base_url: str | None = Field(default=None, max_length=300)
    region: str | None = Field(default=None, max_length=100)
    api_key: SecretStr | None = None

    def fields(self) -> dict[str, Any]:
        out = {k: v for k, v in self.model_dump(exclude={"api_key"}).items() if v is not None}
        if self.api_key is not None:
            out["api_key"] = self.api_key.get_secret_value()
        return out


def _is_loopback(request: Request) -> bool:
    client = request.client
    return client is not None and client.host in LOOPBACK_HOSTS


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def register_provider_routes(app: FastAPI, get_engine: Callable[[], Any]) -> None:
    """Attach the provider endpoints as plain routes (keeps ``app.routes`` introspectable)."""

    def overview() -> dict:
        registry = config.provider_registry()
        engine = get_engine()
        return {"ok": True, **registry.overview(), "agent_mode": config.agent_mode(),
                "reasoning_backend": config.reasoning_backend(),
                "supervisor_available": bool(engine and engine.runtime is not None),
                "reasoning_provenance": engine.reasoning_provenance() if engine else None,
                "selections": list(SELECTIONS)}

    async def reconfigure() -> None:
        engine = get_engine()
        if engine is not None:
            await engine.reconfigure_runtime()

    async def read_overview():
        return overview()

    async def select(command: SelectCommand):
        try:
            config.provider_registry().select(command.provider, model=command.model)
        except ValueError as exc:
            return _error(str(exc))
        await reconfigure()
        return overview()

    async def update(kind: str, command: UpdateCommand, request: Request):
        if kind not in PROVIDER_KINDS or kind == "none":
            return _error(f"provider {kind!r} has no configurable fields", 404)
        fields = command.fields()
        if not fields:
            return _error("nothing to update")
        if "api_key" in fields and not (_is_loopback(request) or config.trusted_submissions_enabled()):
            return _error("secret submission is accepted only from a loopback client or a trusted host boundary "
                          "(set the key in the server environment instead)", 403)
        try:
            status = config.provider_registry().update(kind, **fields)
        except ValueError as exc:
            return _error(str(exc))
        await reconfigure()
        return {"ok": True, "status": status.model_dump(mode="json"), **overview()}

    async def test(kind: str):
        if kind not in PROVIDER_KINDS:
            return _error(f"unknown provider {kind!r}", 404)
        registry = config.provider_registry()
        try:
            status = await asyncio.wait_for(
                asyncio.to_thread(registry.test, kind, timeout=TEST_TIMEOUT_SECONDS),
                timeout=TEST_TIMEOUT_SECONDS + 10)
        except asyncio.TimeoutError:
            failed = registry.build(kind)._failed(ProviderError("timeout", "connection test timed out", provider=kind))
            return {"ok": False, "status": failed.model_dump(mode="json")}
        return {"ok": status.error is None, "status": status.model_dump(mode="json")}

    app.add_api_route("/api/providers", read_overview, methods=["GET"], tags=["providers"])
    app.add_api_route("/api/providers/select", select, methods=["POST"], tags=["providers"])
    app.add_api_route("/api/providers/{kind}", update, methods=["PUT"], tags=["providers"])
    app.add_api_route("/api/providers/{kind}/test", test, methods=["POST"], tags=["providers"])
