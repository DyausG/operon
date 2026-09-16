"""One vocabulary for *who reasoned*. Pure functions; nothing here reads a secret.

Five concepts are kept apart on purpose:

* **scenario** - the deterministic telemetry/failure script the Guided Demo replays
  (``core.demo_scenario.SCENARIO``). It is never a reasoning runtime.
* **backend** - the ``ReasoningBackend`` seam that ran (``local``, ``packet``,
  ``agentcore``, ``deterministic``) and the runtime label that describes it.
* **provider** / **model** - the configured ``ModelProvider`` kind and model id the
  backend used (``none`` when no model was involved).
* **provenance** - ``LIVE`` when a real model provider produced the advisory,
  ``INJECTED`` when a test double stood in for the model, ``SIMULATED`` when the
  deterministic advisory ran without any model, ``None`` when nothing ran.
* **live_model** - the single boolean the portal uses to say "model-backed" or not.

``describe_backend`` describes a configured backend object (engine level);
``describe_run_identity`` describes the identity frozen into one persisted run.
Both return the same keys so every run renders the same way.
"""
from __future__ import annotations

from core.providers.base import DISPLAY_NAMES

FIELDS = ("backend", "runtime", "framework", "provider", "model_provider", "model", "locality",
          "provenance", "live_model", "implementation")
LOCALITY = {"ollama": "local", "gemini": "cloud", "bedrock": "cloud", "none": "none"}
RUNTIME_LABELS = {"local": "Local application runtime", "packet": "In-process packet runtime",
                  "agentcore": "AgentCore Runtime", "deterministic": "Deterministic advisory (no model)"}
DETERMINISTIC_BACKEND = "deterministic"


def _describe(*, backend: str | None, provider: str | None, model: str | None, live_model: bool,
              provenance: str | None, implementation: str | None = None, runtime: str | None = None,
              framework: str | None = None) -> dict:
    provider = provider or "none"
    return {
        "backend": backend or "none",
        "runtime": runtime or RUNTIME_LABELS.get(backend or "", "No reasoning runtime"),
        "framework": framework,
        "provider": provider,
        "model_provider": DISPLAY_NAMES.get(provider) if provider != "none" else None,
        "model": model if provider != "none" else None,
        "locality": LOCALITY.get(provider, "cloud"),
        "provenance": provenance,
        "live_model": bool(live_model),
        "implementation": implementation,
    }


def none_description(reason: str | None = None) -> dict:
    out = _describe(backend=None, provider=None, model=None, live_model=False, provenance=None)
    out["unavailable_reason"] = reason
    return out


def _strands_runtime_description(backend_name: str, runtime) -> dict:
    """A ``StrandsRuntime``: live provider model, or an injected model double."""
    settings = runtime.settings
    implementation = runtime.model_implementation()
    injected = getattr(runtime, "_model", None) is not None
    live = bool(settings.live_enabled) and not injected
    return _describe(backend=backend_name, provider=settings.provider, model=settings.model_id, live_model=live,
                     provenance="LIVE" if live else "INJECTED", implementation=implementation,
                     framework="Strands Agents")


def describe_backend(backend) -> dict:
    """Describe a ``ReasoningBackend`` instance (or ``None``) without touching the network."""
    if backend is None:
        return none_description()
    name = getattr(backend, "name", None)
    if name == "agentcore":
        settings = getattr(backend, "settings", None)
        return _describe(backend=name, provider="bedrock", model=getattr(settings, "supervisor_model_id", None),
                         live_model=True, provenance="LIVE", framework="Strands Agents",
                         implementation="bedrock-agentcore runtime")
    if name == DETERMINISTIC_BACKEND:
        identity = backend.identity()
        return _describe(backend=name, provider="none", model=None, live_model=False, provenance="SIMULATED",
                         implementation=identity.get("implementation"), framework="Operon typed advisory contracts")
    runtime = getattr(backend, "runtime", None)
    if runtime is not None and hasattr(runtime, "settings"):
        return _strands_runtime_description(name or "local", runtime)
    return _describe(backend=name, provider=None, model=None, live_model=False, provenance=None,
                     implementation=f"{type(backend).__module__}.{type(backend).__qualname__}")


def describe_run_identity(identity: dict | None) -> dict:
    """Describe the ``runtime_identity`` frozen into a ``SupervisorRunSnapshot``."""
    identity = identity or {}
    backend = identity.get("backend")
    if backend == "agentcore":
        return _describe(backend=backend, provider="bedrock", model=identity.get("supervisor_model_id"),
                         live_model=True, provenance="LIVE", framework="Strands Agents",
                         implementation="bedrock-agentcore runtime")
    if backend == DETERMINISTIC_BACKEND:
        return _describe(backend=backend, provider="none", model=None, live_model=False, provenance="SIMULATED",
                         implementation=identity.get("implementation"), framework="Operon typed advisory contracts")
    supervisor = identity.get("supervisor") or {}
    settings = supervisor.get("settings") or {}
    if settings:
        implementation = str(supervisor.get("implementation") or "")
        live = bool(settings.get("live_enabled")) and implementation.startswith("strands.models.")
        return _describe(backend=backend or "local", provider=settings.get("provider"), model=settings.get("model_id"),
                         live_model=live, provenance="LIVE" if live else "INJECTED", implementation=implementation,
                         framework="Strands Agents")
    return _describe(backend=backend, provider=identity.get("provider"), model=identity.get("model"),
                     live_model=bool(identity.get("live_model")), provenance=identity.get("provenance"),
                     implementation=identity.get("implementation"))


def reasoning_label(description: dict) -> str:
    """Short human label: ``ollama · gemma3:latest`` or ``deterministic advisory · no model``."""
    if description.get("live_model"):
        return f"{description.get('provider')} · {description.get('model')}"
    if description.get("backend") == DETERMINISTIC_BACKEND:
        return "deterministic advisory · no model"
    if description.get("provenance") == "INJECTED":
        return f"{description.get('backend')} · injected model double"
    return "no model provider"
