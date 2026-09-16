"""PRISM interruptible-runtime API (Stage 1).

Session creation/state, operator messages, reconnect events and Fast Path latency
metrics. Message acceptance returns as soon as the turn is durable: it carries the
session, turn, resulting revision, the Fast Path acknowledgement and the scheduled
Slow Path run identity, and never waits for the Slow Path. Bodies are bounded and
validated; metadata is opaque and never interpreted as provider configuration.
"""
from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from core.prism import IdempotencyConflict, InvalidReference, MessageRejected, SessionNotFound
from core.prism.idempotency import IDENTITY_PATTERN, InvalidIdentity
from core.prism.models import CONTENT_TYPES, MAX_CONTENT_CHARS, MAX_METADATA_KEYS

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
Scalar = str | int | float | bool | None


class CreateSessionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: str | None = Field(default=None, min_length=1, max_length=64)
    metadata: dict[str, Scalar] = Field(default_factory=dict, max_length=MAX_METADATA_KEYS)


class MessageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=MAX_CONTENT_CHARS)
    content_type: str = Field(default="text", pattern="^(" + "|".join(CONTENT_TYPES) + ")$")
    request_id: str | None = Field(default=None, pattern=IDENTITY_PATTERN.pattern)
    idempotency_key: str | None = Field(default=None, pattern=IDENTITY_PATTERN.pattern)
    metadata: dict[str, Scalar] = Field(default_factory=dict, max_length=MAX_METADATA_KEYS)
    schedule_slow_path: bool = True


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def register_prism_routes(app: FastAPI, get_runtime: Callable[[], Any]) -> None:
    def runtime():
        value = get_runtime()
        if value is None:
            raise RuntimeError("PRISM runtime is not available")
        return value

    def _session_id(session_id: str) -> str | JSONResponse:
        if not SESSION_ID_RE.match(session_id or ""):
            return _error("malformed session id", 400)
        return session_id

    async def create_session(command: CreateSessionCommand):
        try:
            view = await runtime().create_session(incident_id=command.incident_id, metadata=command.metadata)
        except InvalidReference as exc:
            return _error(str(exc), 404)
        except MessageRejected as exc:
            return _error(str(exc), 400)
        return JSONResponse({"ok": True, "session": view}, status_code=201)

    async def list_sessions(incident_id: str | None = None):
        return {"ok": True, "sessions": runtime().list_sessions(incident_id=incident_id)}

    async def get_session(session_id: str):
        checked = _session_id(session_id)
        if isinstance(checked, JSONResponse):
            return checked
        try:
            return {"ok": True, "session": runtime().session_view(session_id)}
        except SessionNotFound:
            return _error("unknown session", 404)

    async def post_message(session_id: str, command: MessageCommand):
        checked = _session_id(session_id)
        if isinstance(checked, JSONResponse):
            return checked
        try:
            result = await runtime().submit_message(
                session_id, content=command.content, content_type=command.content_type,
                request_id=command.request_id, idempotency_key=command.idempotency_key,
                metadata=command.metadata, schedule_slow_path=command.schedule_slow_path)
        except SessionNotFound:
            return _error("unknown session", 404)
        except IdempotencyConflict as exc:
            return _error(str(exc), 409)
        except (MessageRejected, InvalidIdentity, InvalidReference) as exc:
            return _error(str(exc), 400)
        return JSONResponse(result, status_code=202)

    async def events(session_id: str, after: int = 0):
        checked = _session_id(session_id)
        if isinstance(checked, JSONResponse):
            return checked
        if after < 0:
            return _error("after must be >= 0", 400)
        try:
            return runtime().reconnect_state(session_id, after_event_id=after)
        except SessionNotFound:
            return _error("unknown session", 404)

    async def metrics():
        return {"ok": True, **runtime().metrics()}

    async def overview():
        return {"ok": True, **runtime().overview()}

    app.add_api_route("/api/prism", overview, methods=["GET"], tags=["prism"])
    app.add_api_route("/api/prism/metrics", metrics, methods=["GET"], tags=["prism"])
    app.add_api_route("/api/prism/sessions", create_session, methods=["POST"], tags=["prism"])
    app.add_api_route("/api/prism/sessions", list_sessions, methods=["GET"], tags=["prism"])
    app.add_api_route("/api/prism/sessions/{session_id}", get_session, methods=["GET"], tags=["prism"])
    app.add_api_route("/api/prism/sessions/{session_id}/messages", post_message, methods=["POST"], tags=["prism"])
    app.add_api_route("/api/prism/sessions/{session_id}/events", events, methods=["GET"], tags=["prism"])
