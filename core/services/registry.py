"""
Service registry — the wiring that lets the agent depend on interfaces while the
concrete backend is chosen at runtime.

Each domain (``inventory``, ``workforce``, ``scheduling``, ``cmms``,
``notifications``) can have several registered adapters. Which one is used is
chosen per-domain by an environment variable, defaulting to ``local``::

    SENTINEL_INVENTORY_ADAPTER=local          # default: SQLite reference impl
    SENTINEL_CMMS_ADAPTER=maximo              # your registered CMMS adapter
    SENTINEL_NOTIFICATIONS_ADAPTER=pagerduty

Registering your own adapter (see docs/EXTENDING.md)::

    from core.services.registry import register
    from core.services.base import CmmsService

    class MaximoCmmsAdapter(CmmsService):
        ...
    register("cmms", "maximo", MaximoCmmsAdapter)

Resolved adapters are cached as singletons. Call ``reset_cache()`` in tests when
you change the environment mid-process.
"""
from __future__ import annotations
import os
from typing import Callable

from .base import DOMAINS

# domain -> { adapter_name -> factory() -> instance }
_FACTORIES: dict[str, dict[str, Callable[[], object]]] = {d: {} for d in DOMAINS}
# domain -> resolved singleton
_CACHE: dict[str, object] = {}


def register(domain: str, name: str, factory: Callable[[], object]) -> None:
    """Register an adapter ``factory`` (usually the adapter class itself) under a
    ``name`` for a ``domain``. Re-registering the same name overrides it."""
    if domain not in _FACTORIES:
        raise ValueError(f"unknown service domain {domain!r}; expected one of {DOMAINS}")
    _FACTORIES[domain][name] = factory


# Per-domain default adapter when SENTINEL_<DOMAIN>_ADAPTER is unset. The peers
# default to the LLM-backed adapter, which self-degrades to deterministic without
# a key — so this is always safe, offline included.
_DEFAULT_ADAPTER = {"governance": "llm", "monitoring": "llm"}


def _selected_name(domain: str) -> str:
    default = _DEFAULT_ADAPTER.get(domain, "local")
    return os.getenv(f"SENTINEL_{domain.upper()}_ADAPTER", default).strip() or default


def resolve(domain: str):
    """Return the (cached) adapter instance selected for ``domain``."""
    if domain in _CACHE:
        return _CACHE[domain]
    _ensure_defaults_loaded()
    name = _selected_name(domain)
    factories = _FACTORIES.get(domain, {})
    if name not in factories:
        available = ", ".join(sorted(factories)) or "none"
        raise LookupError(
            f"no '{name}' adapter registered for service '{domain}' "
            f"(SENTINEL_{domain.upper()}_ADAPTER); registered: {available}")
    inst = factories[name]()
    _CACHE[domain] = inst
    return inst


def reset_cache() -> None:
    """Drop resolved singletons (e.g. after changing env vars in a test)."""
    _CACHE.clear()


_defaults_loaded = False


def _ensure_defaults_loaded() -> None:
    """Import the bundled reference adapters so their ``register(...)`` calls run.
    Imported lazily to avoid a circular import at package load time."""
    global _defaults_loaded
    if _defaults_loaded:
        return
    _defaults_loaded = True
    from . import adapters  # noqa: F401  (import side-effect: registers 'local')
