"""Bundled service adapters. Importing this package registers the built-in
``local`` (SQLite-backed) adapter for every domain, and the ``mcp`` client
adapter when the ``mcp`` package is available. Drop your own adapter module here
(or anywhere) and call ``core.services.registry.register(...)`` to add it."""
from __future__ import annotations
from . import local  # noqa: F401  (import side-effect: registers the 'local' adapters)

# LLM-backed peers (Governance/Monitoring via Gemini). The DEFAULT for those two
# domains — self-degrades to deterministic without a key, so it's always safe.
try:
    from . import gemini_peers  # noqa: F401  (registers the 'llm' peer adapters)
except Exception:  # pragma: no cover - google-genai not installed / import issue
    pass

# The MCP client adapter is optional: if the `mcp` package isn't installed, the
# default `local` path must still work. Registering it does not spawn anything —
# the server subprocess starts only when an `mcp` adapter is actually used.
try:
    from . import mcp_adapter  # noqa: F401  (registers the 'mcp' adapters)
except Exception:  # pragma: no cover - mcp not installed / import issue
    pass

# The A2A client adapter is optional too (Governance/Monitoring peers over A2A).
# Registering does not connect — the bridge starts only when an `a2a` adapter is used.
try:
    from . import a2a_adapter  # noqa: F401  (registers the 'a2a' adapters)
except Exception:  # pragma: no cover - a2a-sdk not installed / import issue
    pass
