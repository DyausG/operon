"""Operon-level provider failures. One vocabulary for every vendor SDK.

Vendor exceptions never cross the provider boundary. Each adapter maps what its
SDK raises onto ``ProviderError`` with one of ``ERROR_CODES``; messages are
redacted so a credential can never be echoed into a log, an API response or a UI.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

ProviderErrorCode = Literal[
    "provider_not_configured", "authentication_failed", "provider_unreachable", "model_not_found",
    "rate_limited", "timeout", "unsupported_capability", "provider_error",
]
ERROR_CODES: tuple[str, ...] = (
    "provider_not_configured", "authentication_failed", "provider_unreachable", "model_not_found",
    "rate_limited", "timeout", "unsupported_capability", "provider_error",
)
RETRYABLE_CODES = frozenset({"provider_unreachable", "rate_limited", "timeout"})
MAX_MESSAGE_CHARS = 400


def redact(text: str, secrets: Iterable[str | None] = ()) -> str:
    """Strip any known secret value out of ``text`` and bound its length."""
    out = str(text or "")
    for secret in secrets:
        if secret and len(secret) >= 6 and secret in out:
            out = out.replace(secret, "[redacted]")
    return out[:MAX_MESSAGE_CHARS]


class ProviderError(RuntimeError):
    """A normalized provider failure. ``code`` is one of ``ERROR_CODES``."""

    def __init__(self, code: str, message: str, *, provider: str, retryable: bool | None = None,
                 secrets: Iterable[str | None] = ()):
        if code not in ERROR_CODES:
            raise ValueError(f"unknown provider error code {code!r}")
        super().__init__(redact(message, secrets))
        self.code = code
        self.provider = provider
        self.retryable = (code in RETRYABLE_CODES) if retryable is None else bool(retryable)

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "provider": self.provider, "retryable": self.retryable}


def _module_of(exc: BaseException) -> str:
    return type(exc).__module__ or ""


def normalize_exception(exc: BaseException, *, provider: str, secrets: Iterable[str | None] = ()) -> ProviderError | None:
    """Best-effort mapping of a vendor SDK exception onto a ``ProviderError``.

    Returns ``None`` when the exception is not recognisably a provider/transport
    failure, so callers can keep their own handling for application errors. No SDK
    is imported here; recognition is by module and attributes only.
    """
    if isinstance(exc, ProviderError):
        return exc
    module = _module_of(exc)
    name = type(exc).__name__
    text = str(exc)
    secrets = tuple(secrets)

    def err(code: str, message: str | None = None, **kw) -> ProviderError:
        return ProviderError(code, message or f"{name}: {text}", provider=provider, secrets=secrets, **kw)

    # Transport-level failures (httpx / stdlib) are provider-neutral.
    if module.startswith("httpx"):
        if "Timeout" in name:
            return err("timeout", f"{provider} request timed out")
        if name in {"ConnectError", "RemoteProtocolError", "ReadError", "WriteError", "NetworkError", "ProxyError"}:
            return err("provider_unreachable", f"{provider} endpoint unreachable: {text}")
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if isinstance(status, int):
            return _from_status(status, provider, text, secrets)
    if isinstance(exc, (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return err("provider_unreachable", f"{provider} endpoint refused the connection")
    if isinstance(exc, TimeoutError) or name.endswith("Timeout"):
        return err("timeout", f"{provider} request timed out")
    if isinstance(exc, OSError) and getattr(exc, "errno", None) is not None and not isinstance(exc, PermissionError):
        return err("provider_unreachable", f"{provider} endpoint unreachable: {text}")

    # Google GenAI SDK: APIError carries the HTTP status in ``code``.
    if module.startswith("google.genai"):
        status = getattr(exc, "code", None)
        if isinstance(status, int):
            return _from_status(status, provider, text, secrets)
        return err("provider_error")

    # Ollama client: ResponseError carries ``status_code``; RequestError is transport.
    if module.startswith("ollama"):
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            return _from_status(status, provider, text, secrets)
        return err("provider_unreachable", f"{provider} request failed: {text}")

    # botocore / boto3.
    if module.startswith("botocore"):
        if name in {"ReadTimeoutError", "ConnectTimeoutError"}:
            return err("timeout", f"{provider} request timed out")
        if name in {"EndpointConnectionError", "ConnectionClosedError", "ProxyConnectionError", "SSLError"}:
            return err("provider_unreachable", f"{provider} endpoint unreachable")
        if name in {"NoCredentialsError", "PartialCredentialsError", "ProfileNotFound", "NoRegionError"}:
            return err("provider_not_configured", f"AWS configuration incomplete: {name}")
        if name in {"UnauthorizedSSOTokenError", "TokenRetrievalError", "SSOTokenLoadError"}:
            return err("authentication_failed", f"AWS session credentials are not usable: {name}")
        response = getattr(exc, "response", None)
        code = ""
        if isinstance(response, dict):
            code = str(response.get("Error", {}).get("Code") or "")
        return _from_aws_code(code or name, provider, text, secrets)

    # Strands wraps some provider failures in its own exception types.
    if module.startswith("strands"):
        if name == "ModelThrottledException":
            return err("rate_limited", f"{provider} throttled the request")
        if name == "ContextWindowOverflowException":
            return err("provider_error", f"{provider} rejected the request: context window exceeded", retryable=False)
        return None
    return None


def _from_status(status: int, provider: str, text: str, secrets) -> ProviderError:
    lowered = text.lower()
    if status in (401, 403) or (status == 400 and ("api key" in lowered or "api_key" in lowered)):
        return ProviderError("authentication_failed", f"{provider} rejected the credential (HTTP {status})",
                             provider=provider, secrets=secrets)
    if status == 404:
        return ProviderError("model_not_found", f"{provider}: model or endpoint not found (HTTP 404): {text}",
                             provider=provider, secrets=secrets)
    if status == 429:
        return ProviderError("rate_limited", f"{provider} rate limit reached (HTTP 429)", provider=provider, secrets=secrets)
    if status == 408 or status == 504:
        return ProviderError("timeout", f"{provider} request timed out (HTTP {status})", provider=provider, secrets=secrets)
    if status >= 500:
        return ProviderError("provider_error", f"{provider} server error (HTTP {status})", provider=provider,
                             retryable=True, secrets=secrets)
    return ProviderError("provider_error", f"{provider} request failed (HTTP {status}): {text}", provider=provider,
                         secrets=secrets)


_AWS_AUTH = {"ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId", "UnrecognizedClientException",
             "InvalidSignatureException", "AuthFailure", "SignatureDoesNotMatch", "InvalidIdentityToken"}
_AWS_ACCESS = {"AccessDenied", "AccessDeniedException", "UnauthorizedException", "UnauthorizedOperation"}
_AWS_NOT_FOUND = {"ResourceNotFoundException", "ValidationException", "ModelNotReadyException", "NotFound"}
_AWS_THROTTLE = {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException",
                 "Throttling", "RequestLimitExceeded"}
_AWS_TRANSIENT = {"InternalServerException", "ServiceUnavailableException", "ModelTimeoutException",
                  "InternalFailure", "ServiceUnavailable"}


def _from_aws_code(code: str, provider: str, text: str, secrets) -> ProviderError:
    if code in _AWS_AUTH:
        return ProviderError("authentication_failed", f"AWS rejected the credentials: {code}", provider=provider, secrets=secrets)
    if code in _AWS_ACCESS:
        return ProviderError("authentication_failed", f"AWS denied access: {code} (check IAM and Bedrock model access)",
                             provider=provider, secrets=secrets)
    if code in _AWS_NOT_FOUND:
        return ProviderError("model_not_found", f"Bedrock model not available: {code}: {text}", provider=provider,
                             secrets=secrets)
    if code in _AWS_THROTTLE:
        return ProviderError("rate_limited", f"AWS throttled the request: {code}", provider=provider, secrets=secrets)
    if code == "ModelTimeoutException":
        return ProviderError("timeout", "Bedrock model invocation timed out", provider=provider, secrets=secrets)
    if code in _AWS_TRANSIENT:
        return ProviderError("provider_error", f"AWS service error: {code}", provider=provider, retryable=True, secrets=secrets)
    return ProviderError("provider_error", f"AWS request failed: {code}: {text}", provider=provider, secrets=secrets)
