"""Small native Strands factory over the provider boundary. No implicit live fallback."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from strands import Agent
from strands.models import Model
from strands.tools.executors import SequentialToolExecutor
from strands.types.agent import Limits
from strands.types.tools import AgentTool

from core.providers.base import ModelOptions, ModelProvider, TimeoutPolicy
from core.providers.errors import ProviderError

RuntimeProvider = Literal["gemini", "ollama", "bedrock"]


class RuntimeConfigurationError(ValueError):
    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


class RuntimeSettings(BaseModel):
    """Explicit provider/model settings; live creation requires a separate opt-in.

    ``provider`` names the model vendor. ``aws_region`` is required for Bedrock and
    ignored otherwise; ``endpoint`` is the Ollama base URL. Existing callers that
    pass only ``model_id`` and ``aws_region`` keep the Bedrock behaviour unchanged.

    Timeouts default to ``None``: the provider's own ``TimeoutPolicy`` applies
    (cloud-oriented for Gemini/Bedrock, much larger for local Ollama inference).
    A value given here is an explicit per-runtime override and always wins.
    """
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    provider: RuntimeProvider = "bedrock"
    model_id: Annotated[str, Field(min_length=1, max_length=300, pattern=r"\S")]
    aws_region: Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")] | None = None
    endpoint: Annotated[str, Field(min_length=1, max_length=300, pattern=r"\S")] | None = None
    live_enabled: bool = False
    max_tokens: int = Field(default=2500, ge=1, le=8000)
    temperature: float = Field(default=0.1, ge=0, le=1)
    connect_timeout_seconds: float | None = Field(default=None, gt=0, le=120)
    read_timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    invocation_timeout_seconds: float | None = Field(default=None, gt=0, le=7200)
    run_timeout_seconds: float | None = Field(default=None, gt=0, le=14400)
    request_attempts: int = Field(default=2, ge=1, le=3)
    max_turns: int = Field(default=6, ge=1, le=12)
    max_output_tokens: int = Field(default=8000, ge=1, le=32000)
    max_total_tokens: int = Field(default=32000, ge=1, le=100000)

    @model_validator(mode="after")
    def _provider_requirements(self):
        if self.provider == "bedrock" and not self.aws_region:
            raise ValueError("Bedrock runtime settings require aws_region")
        return self

    def invocation_limits(self) -> Limits:
        return {"turns": self.max_turns, "output_tokens": self.max_output_tokens,
                "total_tokens": self.max_total_tokens}

    def model_options(self) -> ModelOptions:
        """Only explicitly supplied timeouts travel; ``None`` leaves the provider policy in force."""
        return ModelOptions(temperature=self.temperature, max_tokens=self.max_tokens,
                            connect_timeout_seconds=self.connect_timeout_seconds,
                            read_timeout_seconds=self.read_timeout_seconds,
                            invocation_timeout_seconds=self.invocation_timeout_seconds,
                            run_timeout_seconds=self.run_timeout_seconds, request_attempts=self.request_attempts)

    def identity_locator(self) -> str:
        """Non-secret locator frozen into run identity: region (Bedrock), host (Ollama) or API host (Gemini)."""
        if self.provider == "bedrock":
            return self.aws_region or ""
        if self.provider == "ollama":
            from core.providers.ollama import DEFAULT_OLLAMA_BASE_URL
            return (self.endpoint or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        from core.providers.gemini import GEMINI_ENDPOINT
        return GEMINI_ENDPOINT


def provider_for_settings(settings: RuntimeSettings) -> ModelProvider:
    """Build the provider a runtime describes; pure construction, no credential or client."""
    from core.providers import get_registry
    from core.providers.bedrock import BedrockProvider, BedrockSettings
    from core.providers.gemini import GeminiProvider
    from core.providers.ollama import OllamaProvider
    config = get_registry().config
    if settings.provider == "bedrock":
        overrides = {"connect_timeout_seconds": settings.connect_timeout_seconds,
                     "read_timeout_seconds": settings.read_timeout_seconds}
        return BedrockProvider(BedrockSettings(
            region=settings.aws_region, model_id=settings.model_id,
            request_attempts=settings.request_attempts, max_tokens=settings.max_tokens, temperature=settings.temperature,
            **{key: value for key, value in overrides.items() if value is not None}))
    if settings.provider == "gemini":
        return GeminiProvider(config.gemini.model_copy(update={"model": settings.model_id}))
    update = {"model": settings.model_id}
    if settings.endpoint:
        update["base_url"] = settings.endpoint
    return OllamaProvider(config.ollama.model_copy(update=update))


class StrandsRuntime:
    """Factory only: each call creates a fresh Agent with ephemeral conversation state."""

    def __init__(self, settings: RuntimeSettings, *, model: Model | None = None,
                 provider: ModelProvider | None = None):
        if model is not None and not isinstance(model, Model):
            raise TypeError("injected model must implement the Strands Model boundary")
        if provider is not None and not isinstance(provider, ModelProvider):
            raise TypeError("injected provider must implement the ModelProvider boundary")
        self.settings = settings
        self._model = model
        self._provider = provider

    @property
    def provider(self) -> ModelProvider:
        if self._provider is None:
            self._provider = provider_for_settings(self.settings)
        return self._provider

    def model_implementation(self) -> str:
        if self._model is not None:
            return f"{type(self._model).__module__}.{type(self._model).__qualname__}"
        return f"strands.models.{self.settings.provider}"

    def timeouts(self) -> TimeoutPolicy:
        """The effective time bounds: the provider's policy with this runtime's explicit overrides."""
        return self.provider.timeout_policy().merged(self.settings.model_options())

    def invocation_timeout(self) -> float:
        return self.timeouts().invocation_seconds

    def run_timeout(self) -> float:
        return self.timeouts().run_seconds

    def preflight(self) -> None:
        """Provider capability check before a run starts; raises ``RuntimeConfigurationError``."""
        if self._model is not None:
            return  # an injected Model is the caller's responsibility
        try:
            self.provider.preflight(tool_calling=True)
        except ProviderError as exc:
            raise RuntimeConfigurationError(f"{self.settings.provider} cannot serve this run: {exc}",
                                            code=exc.code) from exc

    def _live_model(self) -> Model:
        if not self.settings.live_enabled:
            raise RuntimeConfigurationError(
                f"{self.settings.provider} model is disabled; explicitly enable live mode or inject a test Model")
        try:
            return self.provider.strands_model(self.settings.model_options())
        except ProviderError as exc:
            raise RuntimeConfigurationError(f"Cannot configure {self.settings.provider}: {exc}", code=exc.code) from exc

    def create_agent(self, *, name: str, system_prompt: str,
                     output_model: type[BaseModel], tools: list[AgentTool],
                     trace_attributes: Mapping[str, str] | None = None) -> Agent:
        # trace_attributes only annotate the agent's telemetry span; they carry no authority.
        return Agent(
            name=name, model=self._model if self._model is not None else self._live_model(),
            system_prompt=system_prompt, structured_output_model=output_model,
            tools=list(tools), callback_handler=None, load_tools_from_directory=False,
            tool_executor=SequentialToolExecutor(), retry_strategy=None,
            trace_attributes=dict(trace_attributes) if trace_attributes else None,
        )
