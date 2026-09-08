"""Small native Strands factory. No provider selection or implicit live fallback."""
from __future__ import annotations

from typing import Annotated

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError
from pydantic import BaseModel, ConfigDict, Field
from strands import Agent
from strands.models import BedrockModel, Model
from strands.tools.executors import SequentialToolExecutor
from strands.types.agent import Limits
from strands.types.tools import AgentTool


class RuntimeConfigurationError(ValueError):
    pass


class RuntimeSettings(BaseModel):
    """Explicit Bedrock settings; live creation requires a separate opt-in."""
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    model_id: Annotated[str, Field(min_length=1, max_length=300, pattern=r"\S")]
    aws_region: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
    live_enabled: bool = False
    max_tokens: int = Field(default=2500, ge=1, le=8000)
    temperature: float = Field(default=0.1, ge=0, le=1)
    connect_timeout_seconds: float = Field(default=3, gt=0, le=30)
    read_timeout_seconds: float = Field(default=30, gt=0, le=120)
    invocation_timeout_seconds: float = Field(default=90, gt=0, le=300)
    request_attempts: int = Field(default=2, ge=1, le=3)
    max_turns: int = Field(default=6, ge=1, le=12)
    max_output_tokens: int = Field(default=8000, ge=1, le=32000)
    max_total_tokens: int = Field(default=32000, ge=1, le=100000)

    def invocation_limits(self) -> Limits:
        return {"turns": self.max_turns, "output_tokens": self.max_output_tokens,
                "total_tokens": self.max_total_tokens}


class StrandsRuntime:
    """Factory only: each call creates a fresh Agent with ephemeral conversation state."""

    def __init__(self, settings: RuntimeSettings, *, model: Model | None = None):
        if model is not None and not isinstance(model, Model):
            raise TypeError("injected model must implement the Strands Model boundary")
        self.settings = settings
        self._model = model

    def _bedrock_model(self) -> BedrockModel:
        if not self.settings.live_enabled:
            raise RuntimeConfigurationError("Bedrock is disabled; explicitly enable live mode or inject a test Model")
        try:
            session = boto3.Session(region_name=self.settings.aws_region)
            credentials = session.get_credentials()
            if credentials is None:
                raise RuntimeConfigurationError("Bedrock credentials unavailable; configure an AWS profile or role")
            frozen = credentials.get_frozen_credentials()
            if not frozen.access_key or not frozen.secret_key:
                raise RuntimeConfigurationError("Bedrock credentials are incomplete")
            return BedrockModel(
                boto_session=session,
                boto_client_config=Config(
                    connect_timeout=self.settings.connect_timeout_seconds,
                    read_timeout=self.settings.read_timeout_seconds,
                    retries={"mode": "standard", "total_max_attempts": self.settings.request_attempts},
                ),
                model_id=self.settings.model_id, temperature=self.settings.temperature,
                max_tokens=self.settings.max_tokens, use_native_token_count=False,
            )
        except BotoCoreError as exc:
            raise RuntimeConfigurationError(
                "Cannot configure Bedrock; check AWS credentials, profile, and region"
            ) from exc

    def create_agent(self, *, name: str, system_prompt: str,
                     output_model: type[BaseModel], tools: list[AgentTool]) -> Agent:
        return Agent(
            name=name, model=self._model if self._model is not None else self._bedrock_model(),
            system_prompt=system_prompt, structured_output_model=output_model,
            tools=list(tools), callback_handler=None, load_tools_from_directory=False,
            tool_executor=SequentialToolExecutor(), retry_strategy=None,
        )
