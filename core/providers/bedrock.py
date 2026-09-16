"""Amazon Bedrock provider (boto3; Strands ``BedrockModel`` for agents).

This is the Step 15 Bedrock construction moved behind the provider boundary.
Credentials come only from the standard AWS chain (environment, profile, role);
Operon never stores them. Constructing the provider performs no I/O and resolves
no credential; ``describe`` inspects the environment only.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .base import (
    CLOUD_TIMEOUTS, Capabilities, CredentialStatus, DISPLAY_NAMES, ModelOptions, ModelProvider, ProviderStatus,
    TimeoutPolicy, now_iso,
)
from .errors import ProviderError, normalize_exception

DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
DEFAULT_AWS_REGION = "us-east-1"


class BedrockSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    region: str = Field(default=DEFAULT_AWS_REGION, min_length=1, max_length=100, pattern=r"\S")
    model_id: str = Field(default=DEFAULT_BEDROCK_MODEL, min_length=1, max_length=300, pattern=r"\S")
    profile: str | None = Field(default=None, max_length=200)
    connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    read_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    request_attempts: int = Field(default=2, ge=1, le=3)
    max_tokens: int = Field(default=2500, ge=1, le=8000)
    temperature: float = Field(default=0.1, ge=0, le=1)


def _default_session_factory(*, region_name: str, profile_name: str | None):
    import boto3
    return boto3.Session(region_name=region_name, profile_name=profile_name or None)


def _shared_credentials_present() -> bool:
    path = os.getenv("AWS_SHARED_CREDENTIALS_FILE", "").strip() or str(Path.home() / ".aws" / "credentials")
    try:
        return Path(path).expanduser().is_file()
    except OSError:
        return False


class BedrockProvider(ModelProvider):
    kind = "bedrock"
    display_name = DISPLAY_NAMES["bedrock"]

    def __init__(self, settings: BedrockSettings, *, session_factory: Callable[..., Any] | None = None):
        self.settings = BedrockSettings.model_validate(settings)
        self._session_factory = session_factory

    # ---- metadata ---------------------------------------------------------
    @property
    def model_id(self) -> str:
        return self.settings.model_id

    def credential_status(self) -> CredentialStatus:
        """Environment inspection only; no credential chain resolution, no network."""
        if os.getenv("AWS_ACCESS_KEY_ID", "").strip() and os.getenv("AWS_SECRET_ACCESS_KEY", "").strip():
            return CredentialStatus(configured=True, source="environment", detail="AWS access key present (server-side)")
        if os.getenv("AWS_BEARER_TOKEN_BEDROCK", "").strip():
            return CredentialStatus(configured=True, source="environment", detail="Bedrock API key present (server-side)")
        profile = self.settings.profile or os.getenv("AWS_PROFILE", "").strip()
        if profile:
            return CredentialStatus(configured=True, source="environment", detail=f"AWS profile {profile!r}")
        role_hints = ("AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
        if any(os.getenv(name, "").strip() for name in role_hints):
            return CredentialStatus(configured=True, source="aws_chain", detail="AWS role credentials via the SDK chain")
        if _shared_credentials_present():
            return CredentialStatus(configured=True, source="aws_chain", detail="shared AWS credentials file present")
        return CredentialStatus(configured=False, source="none",
                                detail="no AWS credentials found (AWS_PROFILE, access keys or a role)")

    def configured(self) -> bool:
        return self.credential_status().configured

    def capabilities(self) -> Capabilities:
        return Capabilities(text_generation=True, structured_output=True, tool_calling=True, streaming=True,
                            image_input=None, locality="cloud")

    def identity_locator(self) -> str:
        return self.settings.region

    def timeout_policy(self) -> TimeoutPolicy:
        """Cloud bounds with this provider's configured connect/read timeouts."""
        return CLOUD_TIMEOUTS.model_copy(update={
            "connect_seconds": self.settings.connect_timeout_seconds,
            "first_token_seconds": self.settings.read_timeout_seconds,
            "auxiliary_seconds": min(CLOUD_TIMEOUTS.auxiliary_seconds, self.settings.read_timeout_seconds)})

    def public_settings(self) -> dict[str, Any]:
        return {"region": self.settings.region, "model_id": self.settings.model_id,
                "connect_timeout_seconds": self.settings.connect_timeout_seconds,
                "read_timeout_seconds": self.settings.read_timeout_seconds,
                "request_attempts": self.settings.request_attempts, "max_tokens": self.settings.max_tokens}

    def not_configured_reason(self) -> str:
        return "Bedrock needs AWS credentials (AWS_PROFILE, access keys or a role) and Bedrock model access"

    def describe(self) -> ProviderStatus:
        return self._status(region=self.settings.region, endpoint=f"bedrock-runtime.{self.settings.region}.amazonaws.com",
                            detail="configured (credentials unverified)" if self.configured() else self.not_configured_reason())

    # ---- sessions ---------------------------------------------------------
    def _normalize(self, exc: BaseException) -> ProviderError:
        return normalize_exception(exc, provider=self.kind) or ProviderError(
            "provider_error", f"{type(exc).__name__}: {exc}", provider=self.kind)

    def session(self):
        try:
            factory = self._session_factory or _default_session_factory
            return factory(region_name=self.settings.region, profile_name=self.settings.profile)
        except Exception as exc:  # noqa: BLE001
            raise self._normalize(exc) from exc

    def _resolved_credentials(self, session):
        try:
            credentials = session.get_credentials()
        except Exception as exc:  # noqa: BLE001
            raise self._normalize(exc) from exc
        if credentials is None:
            raise ProviderError("provider_not_configured",
                                "AWS credentials unavailable; configure an AWS profile, access keys or a role",
                                provider=self.kind)
        frozen = credentials.get_frozen_credentials()
        if not frozen.access_key or not frozen.secret_key:
            raise ProviderError("provider_not_configured", "AWS credentials are incomplete", provider=self.kind)
        return credentials

    def client_config(self, options: ModelOptions | None = None):
        from botocore.config import Config
        options = options or ModelOptions()
        policy = self.timeout_policy().merged(options)
        return Config(
            connect_timeout=policy.connect_seconds,
            read_timeout=policy.first_token_seconds,
            retries={"mode": "standard", "total_max_attempts": options.request_attempts or self.settings.request_attempts},
        )

    # ---- operations -------------------------------------------------------
    def test_connection(self, *, timeout: float | None = None) -> ProviderStatus:
        region = self.settings.region
        try:
            session = self.session()
            self._resolved_credentials(session)
            options = ModelOptions(read_timeout_seconds=timeout) if timeout else None
            config = self.client_config(options)
            sts = session.client("sts", config=config)
            sts.get_caller_identity()
            control = session.client("bedrock", config=config)
            detail = self._model_check(control)
        except ProviderError as err:
            return self._failed(err, region=region)
        except Exception as exc:  # noqa: BLE001
            return self._failed(self._normalize(exc), region=region)
        return self._status(reachable=True, probe="connection", region=region, checked_at=now_iso(),
                            endpoint=f"bedrock-runtime.{region}.amazonaws.com",
                            detail=f"credentials valid; {detail}")

    def _model_check(self, control) -> str:
        model_id = self.settings.model_id
        try:
            control.get_foundation_model(modelIdentifier=model_id)
            return f"foundation model {model_id} visible in {self.settings.region}"
        except Exception as first:  # noqa: BLE001
            err = self._normalize(first)
            if err.code != "model_not_found":
                raise err from first
            # Cross-region inference profiles are not foundation models; try that lookup.
            try:
                control.get_inference_profile(inferenceProfileIdentifier=model_id)
                return f"inference profile {model_id} visible in {self.settings.region}"
            except Exception as second:  # noqa: BLE001
                raise self._normalize(second) from second

    def generate_json(self, system: str, user: str, *, timeout: float | None = None) -> dict:
        session = self.session()
        self._resolved_credentials(session)
        options = ModelOptions(read_timeout_seconds=timeout) if timeout else None
        try:
            runtime = session.client("bedrock-runtime", config=self.client_config(options))
            response = runtime.converse(
                modelId=self.settings.model_id,
                system=[{"text": system + "\nRespond with exactly one JSON object and nothing else."}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": self.settings.max_tokens, "temperature": self.settings.temperature})
            blocks = response["output"]["message"]["content"]
            text = "".join(block.get("text", "") for block in blocks).strip()
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._normalize(exc) from exc
        if text.startswith("```"):
            text = text.strip("`")
            text = text[4:] if text.lower().startswith("json") else text
        try:
            parsed = json.loads(text.strip())
        except json.JSONDecodeError as exc:
            raise ProviderError("provider_error", "Bedrock returned a non-JSON response", provider=self.kind) from exc
        if not isinstance(parsed, dict):
            raise ProviderError("provider_error", "Bedrock returned a non-object JSON response", provider=self.kind)
        return parsed

    def strands_model(self, options: ModelOptions | None = None):
        options = options or ModelOptions()
        session = self.session()
        self._resolved_credentials(session)
        try:
            from strands.models import BedrockModel
            return BedrockModel(
                boto_session=session, boto_client_config=self.client_config(options),
                model_id=self.settings.model_id,
                temperature=options.temperature if options.temperature is not None else self.settings.temperature,
                max_tokens=options.max_tokens or self.settings.max_tokens, use_native_token_count=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise self._normalize(exc) from exc
