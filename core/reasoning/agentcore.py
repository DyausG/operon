"""Application-side Amazon Bedrock AgentCore Runtime adapter.

The adapter sends only the Step 15A ``ReasoningRequest`` packet and treats the
entire response as untrusted. Client construction and invocation happen only in
``supervise``; importing Operon or selecting this backend never resolves AWS
credentials or opens a network connection.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import json
import os
from typing import Any
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError, ClientError, ConnectionClosedError, ConnectTimeoutError,
    EndpointConnectionError, ReadTimeoutError,
)
from pydantic import BaseModel, ConfigDict, Field

from core import config
from core.providers.base import CLOUD_TIMEOUTS
from core.agents.contracts import SpecialistContext, SupervisorBounds, SupervisorResult
from .backend import ReasoningBackend
from .errors import ReasoningBackendUnavailable
from .identity import runtime_identity
from .packet import build_request
from .protocol import RuntimeIdentity, SESSION_PREFIX
from .trust import validate_response

__all__ = ["AgentCoreBackend", "AgentCoreSettings", "MAX_RESPONSE_BYTES"]

# A valid bounded SupervisorResult is far smaller than AgentCore's 100 MB service
# limit. Keep the untrusted response boundary aligned with the request boundary.
MAX_RESPONSE_BYTES = 1_000_000
_RESPONSE_READ_CHUNK_BYTES = 64 * 1024


DEFAULT_RUN_SECONDS = CLOUD_TIMEOUTS.run_seconds


class AgentCoreSettings(BaseModel):
    """Explicit application-side runtime invocation and identity settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    runtime_arn: str = Field(min_length=1, max_length=2048, pattern=r"\S")
    qualifier: str = Field(default="DEFAULT", min_length=1, max_length=100, pattern=r"\S")
    region: str = Field(min_length=1, max_length=100, pattern=r"\S")
    supervisor_model_id: str = Field(min_length=1, max_length=300, pattern=r"\S")
    specialist_model_id: str = Field(min_length=1, max_length=300, pattern=r"\S")
    build_id: str | None = Field(default=None, min_length=1, max_length=300, pattern=r"\S")
    connect_timeout_seconds: float = Field(default=5, gt=0, le=30)
    extra_read_timeout_seconds: float = Field(default=60, ge=1, le=300)
    stop_session: bool = True

    @classmethod
    def from_environment(cls) -> "AgentCoreSettings":
        """Read AgentCore configuration without constructing a client.

        AgentCore model IDs are deliberately required. The legacy Bedrock model
        default remains available to local/packet modes, but is not silently
        assumed to be valid for a deployed runtime.
        """
        values = {
            "runtime_arn": os.getenv("OPERON_AGENTCORE_RUNTIME_ARN", "").strip(),
            "qualifier": os.getenv("OPERON_AGENTCORE_QUALIFIER", "DEFAULT").strip(),
            "region": (os.getenv("OPERON_AGENTCORE_REGION", "").strip()
                       or os.getenv("AWS_REGION", "").strip()
                       or os.getenv("AWS_DEFAULT_REGION", "").strip()
                       or config.AWS_REGION),
            "supervisor_model_id": os.getenv("OPERON_BEDROCK_SUPERVISOR_MODEL_ID", "").strip(),
            "specialist_model_id": os.getenv("OPERON_BEDROCK_SPECIALIST_MODEL_ID", "").strip(),
            "build_id": os.getenv("OPERON_RUNTIME_BUILD_ID", "").strip() or None,
        }
        missing = [key for key in ("runtime_arn", "supervisor_model_id", "specialist_model_id") if not values[key]]
        if missing:
            names = {
                "runtime_arn": "OPERON_AGENTCORE_RUNTIME_ARN",
                "supervisor_model_id": "OPERON_BEDROCK_SUPERVISOR_MODEL_ID",
                "specialist_model_id": "OPERON_BEDROCK_SPECIALIST_MODEL_ID",
            }
            raise ValueError("AgentCore requires explicit " + ", ".join(names[key] for key in missing))
        return cls(**values)


def _boto_client_factory(*, region_name: str, config: Config):
    """Smallest SDK-specific seam; called only by ``supervise``."""
    return boto3.Session(region_name=region_name).client("bedrock-agentcore", config=config)


_NON_RETRYABLE_CLIENT_ERRORS = {
    "AccessDeniedException", "ResourceNotFoundException", "ValidationException",
}
_RETRYABLE_CLIENT_ERRORS = {
    "InternalServerException", "RetryableConflictException", "RuntimeClientError",
    "ServiceQuotaExceededException", "ThrottlingException",
}


class AgentCoreBackend(ReasoningBackend):
    """Invoke one AgentCore runtime session for one frozen supervisor run."""

    name = "agentcore"

    def __init__(self, settings: AgentCoreSettings, *, client: Any | None = None,
                 client_factory: Callable[..., Any] | None = None):
        self.settings = AgentCoreSettings.model_validate(settings)
        if client is not None and client_factory is not None:
            raise TypeError("provide either an AgentCore client or a client factory, not both")
        self._injected_client = client
        self._client_factory = client_factory or _boto_client_factory
        self._clients: dict[float, Any] = {}

    def expected_identity(self) -> RuntimeIdentity:
        return runtime_identity(
            supervisor_model_id=self.settings.supervisor_model_id,
            specialist_model_id=self.settings.specialist_model_id,
            region=self.settings.region,
            build_id=self.settings.build_id,
        )

    def identity(self) -> dict:
        return {
            "backend": self.name,
            "runtime_arn": self.settings.runtime_arn,
            "qualifier": self.settings.qualifier,
            "region": self.settings.region,
            "supervisor_model_id": self.settings.supervisor_model_id,
            "specialist_model_id": self.settings.specialist_model_id,
            "expected_identity": self.expected_identity().model_dump(mode="json"),
            "session_id_scheme": SESSION_PREFIX + "{run_id}",
        }

    def _client(self, bounds: SupervisorBounds):
        if self._injected_client is not None:
            return self._injected_client
        run_seconds = bounds.timeout_seconds if bounds.timeout_seconds is not None else DEFAULT_RUN_SECONDS
        read_timeout = float(run_seconds + self.settings.extra_read_timeout_seconds)
        if read_timeout not in self._clients:
            client_config = Config(
                connect_timeout=self.settings.connect_timeout_seconds,
                read_timeout=read_timeout,
                retries={"mode": "standard", "total_max_attempts": 1},
            )
            self._clients[read_timeout] = self._client_factory(
                region_name=self.settings.region, config=client_config)
        return self._clients[read_timeout]

    @staticmethod
    def _baggage(request) -> str:
        pairs = (
            ("operon.incident_id", request.incident_id),
            ("operon.run_id", request.run_id),
            ("operon.stage", request.stage),
        )
        return ",".join(f"{key}={quote(value, safe='-._~')}" for key, value in pairs)

    @staticmethod
    def _response_bytes(result: Mapping[str, Any]) -> bytes:
        stream = result.get("response")
        if stream is None:
            raise ReasoningBackendUnavailable(
                "AgentCore response omitted its response stream", code="PROTOCOL", retryable=False)
        chunks: list[bytes] = []
        total = 0

        def append(chunk: Any) -> bool:
            nonlocal total
            if not isinstance(chunk, bytes):
                raise ReasoningBackendUnavailable(
                    "AgentCore response stream contained non-byte chunks",
                    code="PROTOCOL", retryable=False)
            if not chunk:
                return False
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ReasoningBackendUnavailable(
                    f"AgentCore response exceeds {MAX_RESPONSE_BYTES} bytes",
                    code="PROTOCOL", retryable=False)
            chunks.append(chunk)
            return True

        if hasattr(stream, "read"):
            while append(stream.read(_RESPONSE_READ_CHUNK_BYTES)):
                pass
            return b"".join(chunks)
        try:
            iterator = iter(stream)
        except TypeError as exc:
            raise ReasoningBackendUnavailable(
                "AgentCore response stream is not readable", code="PROTOCOL", retryable=False) from exc
        for chunk in iterator:
            append(chunk)
        return b"".join(chunks)

    def _invoke(self, client, request, payload: bytes) -> bytes:
        invoked = False
        try:
            invoked = True
            result = client.invoke_agent_runtime(
                agentRuntimeArn=self.settings.runtime_arn,
                runtimeSessionId=request.runtime_session_id,
                qualifier=self.settings.qualifier,
                payload=payload,
                baggage=self._baggage(request),
                contentType="application/json",
                accept="application/json",
            )
            if not isinstance(result, Mapping):
                raise ReasoningBackendUnavailable(
                    "AgentCore invocation returned no response object", code="PROTOCOL", retryable=False)
            status = result.get("statusCode")
            if status is not None and (not isinstance(status, int) or not 200 <= status < 300):
                retryable = isinstance(status, int) and (status in {402, 409, 424, 429} or status >= 500)
                raise ReasoningBackendUnavailable(
                    f"AgentCore invocation returned HTTP status {status!r}",
                    code="AGENTCORE_HTTP", retryable=retryable)
            echoed_session = result.get("runtimeSessionId")
            if echoed_session is not None and echoed_session != request.runtime_session_id:
                raise ReasoningBackendUnavailable(
                    "AgentCore service echoed a different runtime session id",
                    code="CORRELATION", retryable=False)
            content_type = result.get("contentType")
            if not isinstance(content_type, str) or not content_type.lower().startswith("application/json"):
                raise ReasoningBackendUnavailable(
                    f"AgentCore returned unsupported content type {content_type!r}",
                    code="PROTOCOL", retryable=False)
            return self._response_bytes(result)
        except ReasoningBackendUnavailable:
            raise
        except ReadTimeoutError as exc:
            raise ReasoningBackendUnavailable(
                "AgentCore invocation timed out", code="TIMEOUT", retryable=True) from exc
        except (ConnectionClosedError, ConnectTimeoutError, EndpointConnectionError) as exc:
            raise ReasoningBackendUnavailable(
                "AgentCore network connection failed", code="NETWORK", retryable=True) from exc
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code") or "AGENTCORE_CLIENT")
            retryable = code in _RETRYABLE_CLIENT_ERRORS
            if code not in _RETRYABLE_CLIENT_ERRORS | _NON_RETRYABLE_CLIENT_ERRORS:
                retryable = False
            raise ReasoningBackendUnavailable(
                f"AgentCore invocation failed: {code}", code=code, retryable=retryable) from exc
        except BotoCoreError as exc:
            raise ReasoningBackendUnavailable(
                "AgentCore SDK rejected the invocation", code="SDK_ERROR", retryable=False) from exc
        finally:
            if isinstance(locals().get("result"), Mapping):
                stream = result.get("response")
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        # Transport cleanup cannot make untrusted bytes valid or
                        # invalidate an otherwise valid advisory response.
                        pass
            if invoked and self.settings.stop_session:
                try:
                    client.stop_runtime_session(
                        agentRuntimeArn=self.settings.runtime_arn,
                        runtimeSessionId=request.runtime_session_id,
                        qualifier=self.settings.qualifier,
                    )
                except Exception:
                    # Session cleanup is operational hygiene only. It can neither
                    # validate nor invalidate advisory bytes already received.
                    pass

    async def supervise(self, service, context: SpecialistContext, *, bounds: SupervisorBounds,
                        snapshot=None, cancellation_result_handler=None) -> SupervisorResult:
        if snapshot is None:
            raise ValueError("AgentCore reasoning requires the durable run snapshot")
        bounds = SupervisorBounds.model_validate(bounds)
        expected = self.expected_identity()
        incident = service.repository.fetch_incident(context.incident_id)
        try:
            request = build_request(
                service, incident, context, bounds, snapshot_id=snapshot.id,
                expected_identity=expected)
        except ValueError as exc:
            raise ReasoningBackendUnavailable(
                str(exc), code="PACKET_INVALID", retryable=False) from exc
        # Pydantic's Step 15A wire model is the sole serializer. No service,
        # repository, path, credentials or application capability can enter it.
        payload = request.model_dump_json().encode("utf-8")
        try:
            client = self._client(bounds)
        except (ConnectionClosedError, ConnectTimeoutError, EndpointConnectionError) as exc:
            raise ReasoningBackendUnavailable(
                "AgentCore network connection failed", code="NETWORK", retryable=True) from exc
        except BotoCoreError as exc:
            raise ReasoningBackendUnavailable(
                "AgentCore client configuration failed", code="SDK_ERROR", retryable=False) from exc
        # Injected clients are an offline/test seam and run synchronously. The
        # real boto3 client is isolated on a worker thread so a long synchronous
        # Runtime invocation cannot block the application's event loop. Cancelling
        # this coroutine cannot forcibly interrupt boto; the bounded SDK call keeps
        # running and its finally block still closes the body and stops the session.
        if self._injected_client is not None:
            raw = self._invoke(client, request, payload)
        else:
            raw = await asyncio.to_thread(self._invoke, client, request, payload)
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReasoningBackendUnavailable(
                "AgentCore returned malformed JSON", code="PROTOCOL", retryable=False) from exc
        # Mandatory application trust boundary. This is the only return path.
        return validate_response(
            snapshot=snapshot, context=context, response=response,
            repository=service.repository, expected_identity=expected)
