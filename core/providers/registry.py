"""Provider selection and construction: the single place vendors are chosen.

Configuration is process-level: it is loaded from the environment once and may
be changed for the running process through ``ProviderRegistry.select`` /
``update`` (the Settings page calls these through ``/api/providers``). Secrets
are held only in ``SecretStr`` fields in memory; nothing here writes a file,
logs a value or returns a raw credential.

Selection vocabulary (``OPERON_AI_PROVIDER``; legacy ``SENTINEL_LLM_PROVIDER``):
``auto`` (default: first *configured* cloud provider, else none), ``none``,
``gemini``, ``ollama``, ``bedrock``. ``POC_FORCE_DETERMINISTIC=1`` forces ``none``.

``build(kind, role=...)`` is the reusable factory later PRISM work can call to
give the Fast and Slow paths different providers; ``roles`` is reserved for that
and empty today.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from .base import DISPLAY_NAMES, PROVIDER_KINDS, ModelProvider, ProviderStatus
from .bedrock import DEFAULT_AWS_REGION, DEFAULT_BEDROCK_MODEL, BedrockProvider, BedrockSettings
from .errors import ProviderError
from .gemini import DEFAULT_GEMINI_MODEL, GeminiProvider, GeminiSettings
from .none import NoProvider
from .ollama import DEFAULT_OLLAMA_BASE_URL, OllamaProvider, OllamaSettings

SELECTIONS: tuple[str, ...] = ("auto", *PROVIDER_KINDS)
_LEGACY_SELECTION = {"deterministic": "none", "local": "ollama"}
_TRUE = ("1", "true", "yes", "on")

# Non-secret fields the configuration API may change per provider.
UPDATABLE_FIELDS: dict[str, frozenset[str]] = {
    "gemini": frozenset({"model", "api_key"}),
    "ollama": frozenset({"model", "base_url"}),
    "bedrock": frozenset({"model_id", "region"}),
    "none": frozenset(),
}
SECRET_FIELDS = frozenset({"api_key"})


def _env(env: Mapping[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = env.get(name, "")
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUE


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(env.get(name, "") or default)
    except ValueError:
        return default


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(env.get(name, "") or default)
    except ValueError:
        return default


class RoleOverride(BaseModel):
    """Reserved for role-based (fast/slow path) provider assignment. Not consulted yet."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: str
    model: str | None = None


class ProviderConfig(BaseModel):
    """Mutable process configuration. Serialization never includes secrets."""
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    selection: str = "auto"
    force_none: bool = False
    gemini: GeminiSettings = GeminiSettings()
    ollama: OllamaSettings = OllamaSettings()
    bedrock: BedrockSettings = BedrockSettings()
    specialist_model: str | None = None
    roles: dict[str, RoleOverride] = Field(default_factory=dict)


def normalize_selection(value: str | None) -> str:
    raw = (value or "auto").strip().lower()
    raw = _LEGACY_SELECTION.get(raw, raw)
    if raw not in SELECTIONS:
        raise ValueError(f"unknown provider selection {raw!r}; expected one of {', '.join(SELECTIONS)}")
    return raw


def config_from_environment(env: Mapping[str, str] | None = None) -> ProviderConfig:
    env = os.environ if env is None else env
    try:
        selection = normalize_selection(_env(env, "OPERON_AI_PROVIDER", "SENTINEL_LLM_PROVIDER", default="auto"))
    except ValueError:
        selection = "auto"
    gemini_key = _env(env, "GEMINI_API_KEY", "GOOGLE_API_KEY")
    gemini = GeminiSettings(
        api_key=SecretStr(gemini_key) if gemini_key else None,
        key_source="environment" if gemini_key else "none",
        model=_env(env, "OPERON_GEMINI_MODEL", "GEMINI_MODEL_ID", default=DEFAULT_GEMINI_MODEL),
        timeout_seconds=_float(env, "OPERON_GEMINI_TIMEOUT_SECONDS", 30.0),
        max_output_tokens=_int(env, "GEMINI_MAX_TOKENS", 1024),
    )
    ollama = OllamaSettings(
        base_url=_env(env, "OPERON_OLLAMA_BASE_URL", "OLLAMA_HOST", default=DEFAULT_OLLAMA_BASE_URL),
        model=_env(env, "OPERON_OLLAMA_MODEL"),
        timeout_seconds=_float(env, "OPERON_OLLAMA_TIMEOUT_SECONDS", 120.0),
    )
    bedrock = BedrockSettings(
        region=_env(env, "AWS_REGION", "AWS_DEFAULT_REGION", default=DEFAULT_AWS_REGION),
        model_id=_env(env, "OPERON_BEDROCK_SUPERVISOR_MODEL_ID", "OPERON_BEDROCK_MODEL_ID", "BEDROCK_MODEL_ID",
                      default=DEFAULT_BEDROCK_MODEL),
        max_tokens=min(max(_int(env, "BEDROCK_MAX_TOKENS", 2500), 1), 8000),
    )
    return ProviderConfig(
        selection=selection, force_none=_flag(env, "POC_FORCE_DETERMINISTIC"),
        gemini=gemini, ollama=ollama, bedrock=bedrock,
        specialist_model=_env(env, "OPERON_SPECIALIST_MODEL_ID", "OPERON_BEDROCK_SPECIALIST_MODEL_ID") or None,
    )


Factory = Callable[[Any], ModelProvider]


class ProviderRegistry:
    """Builds providers from the current configuration; caches until it changes."""

    def __init__(self, config: ProviderConfig | None = None, *, factories: Mapping[str, Factory] | None = None):
        self._config = config if config is not None else config_from_environment()
        self._factories: dict[str, Factory] = {
            "none": lambda _settings: NoProvider(),
            "gemini": GeminiProvider,
            "ollama": OllamaProvider,
            "bedrock": BedrockProvider,
        }
        if factories:
            self._factories.update(factories)
        self._cache: dict[str, ModelProvider] = {}

    # ---- configuration ----------------------------------------------------
    @property
    def config(self) -> ProviderConfig:
        return self._config

    def reload(self, env: Mapping[str, str] | None = None) -> None:
        self._config = config_from_environment(env)
        self._cache.clear()

    def selection(self) -> str:
        return "none" if self._config.force_none else self._config.selection

    def _settings_for(self, kind: str):
        return {"none": None, "gemini": self._config.gemini, "ollama": self._config.ollama,
                "bedrock": self._config.bedrock}[kind]

    # ---- construction -----------------------------------------------------
    def build(self, kind: str | None = None, *, role: str | None = None) -> ModelProvider:
        """Construct (or reuse) the provider for ``kind``; ``role`` is reserved for PRISM paths."""
        if kind is None:
            override = self._config.roles.get(role) if role else None
            kind = override.provider if override else self.resolve_kind()
        if kind not in PROVIDER_KINDS:
            raise ValueError(f"unknown provider kind {kind!r}")
        if kind not in self._cache:
            self._cache[kind] = self._factories[kind](self._settings_for(kind))
        return self._cache[kind]

    def resolve_kind(self) -> str:
        """The effective provider kind: explicit selection, or the first configured one for ``auto``."""
        selection = self.selection()
        if selection != "auto":
            return selection
        for candidate in ("gemini", "bedrock"):
            if self.build(candidate).configured():
                return candidate
        return "none"

    def active(self) -> ModelProvider:
        return self.build(self.resolve_kind())

    # ---- mutation (process-level) -----------------------------------------
    def select(self, selection: str, *, model: str | None = None) -> ProviderStatus:
        kind = normalize_selection(selection)
        if model is not None and kind not in ("auto", "none"):
            self.update(kind, **{"model_id" if kind == "bedrock" else "model": model})
        self._config.selection = kind
        self._config.force_none = False
        self._cache.clear()
        return self.status(self.resolve_kind())

    def update(self, kind: str, **fields: Any) -> ProviderStatus:
        """Change non-secret fields, or (Gemini) set a session-scoped API key. Never returns a secret."""
        if kind not in PROVIDER_KINDS or kind == "none":
            raise ValueError(f"provider {kind!r} has no configurable fields")
        unknown = set(fields) - UPDATABLE_FIELDS[kind]
        if unknown:
            raise ValueError(f"{kind} does not accept field(s): {', '.join(sorted(unknown))}")
        current = self._settings_for(kind)
        changes: dict[str, Any] = {}
        for name, value in fields.items():
            if name in SECRET_FIELDS:
                secret = str(value or "").strip()
                if secret:
                    changes["api_key"], changes["key_source"] = SecretStr(secret), "session"
                else:  # clearing a session key falls back to the environment value, if any
                    env_key = _env(os.environ, "GEMINI_API_KEY", "GOOGLE_API_KEY")
                    changes["api_key"] = SecretStr(env_key) if env_key else None
                    changes["key_source"] = "environment" if env_key else "none"
            else:
                if value is None:
                    continue
                text = str(value).strip()
                if not text and name != "model":
                    raise ValueError(f"{name} must not be empty")
                changes[name] = text
        try:
            updated = current.model_copy(update=changes)
            updated = type(current).model_validate(updated.model_dump())
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            raise ValueError(f"invalid {kind} configuration: {detail}") from exc
        setattr(self._config, kind, updated)
        self._cache.pop(kind, None)
        return self.status(kind)

    # ---- reporting --------------------------------------------------------
    def status(self, kind: str | None = None) -> ProviderStatus:
        return self.build(kind or self.resolve_kind()).describe()

    def test(self, kind: str | None = None, *, timeout: float | None = None) -> ProviderStatus:
        return self.build(kind or self.resolve_kind()).test_connection(timeout=timeout)

    def overview(self) -> dict:
        active = self.resolve_kind()
        return {
            "selection": self.selection(),
            "active": active,
            "active_display_name": DISPLAY_NAMES[active],
            "providers": {kind: self.status(kind).model_dump(mode="json") for kind in PROVIDER_KINDS},
            "specialist_model": self._config.specialist_model,
            "roles": {name: role.model_dump() for name, role in self._config.roles.items()},
        }

    def provenance(self) -> dict:
        provider = self.active()
        return {
            "provider": provider.kind,
            "model_provider": DISPLAY_NAMES[provider.kind] if provider.kind != "none" else None,
            "model": provider.model_id,
            "locality": provider.capabilities().locality,
        }


_REGISTRY: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """The process registry (lazy; constructing it performs no I/O)."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ProviderRegistry()
    return _REGISTRY


def reset(config: ProviderConfig | None = None, *, factories: Mapping[str, Factory] | None = None) -> ProviderRegistry:
    """Replace the process registry (tests, or after the environment changed)."""
    global _REGISTRY
    _REGISTRY = ProviderRegistry(config, factories=factories)
    return _REGISTRY


def active() -> ModelProvider:
    return get_registry().active()


def build(kind: str | None = None, *, role: str | None = None) -> ModelProvider:
    return get_registry().build(kind, role=role)


__all__ = ["ProviderConfig", "ProviderRegistry", "RoleOverride", "SELECTIONS", "UPDATABLE_FIELDS", "active", "build",
           "config_from_environment", "get_registry", "normalize_selection", "reset", "ProviderError"]
