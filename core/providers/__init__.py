"""Provider-agnostic model layer.

    Operon domain/runtime
            |
       ModelProvider
       /    |     \\
    Gemini Ollama Bedrock   (+ NoProvider: truthful deterministic mode)

``core.providers.registry`` is the only place a vendor is selected or built.
Importing this package creates no client, session, credential lookup or socket.
"""
from .base import (Capabilities, CredentialStatus, DISPLAY_NAMES, ModelOptions, ModelProvider, PROVIDER_KINDS,
                   ProviderStatus)
from .errors import ERROR_CODES, ProviderError, normalize_exception
from .registry import (ProviderConfig, ProviderRegistry, SELECTIONS, active, build, config_from_environment,
                       get_registry, normalize_selection, reset)

__all__ = ["Capabilities", "CredentialStatus", "DISPLAY_NAMES", "ERROR_CODES", "ModelOptions", "ModelProvider",
           "PROVIDER_KINDS", "ProviderConfig", "ProviderError", "ProviderRegistry", "ProviderStatus", "SELECTIONS",
           "active", "build", "config_from_environment", "get_registry", "normalize_exception", "normalize_selection",
           "reset"]
