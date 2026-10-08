"""Who may act on which incident before real identity exists (F1).

There is no authenticated identity until F3. Until then every human action is one
of: a declared SANDBOX identity (only in a sandbox process, only on sandbox
incidents), a historical caller-DECLARED local actor (only on UNSPECIFIED, pre-F1
style incidents), a SCENARIO driver (never in production) or the SYSTEM itself.
Production incidents therefore refuse every human action: nothing may masquerade as
authenticated production identity.
"""
from __future__ import annotations

from core import config
from . import models as m


class ActorRefused(PermissionError):
    """The actor kind is not admissible for this incident or process environment."""


def process_environment() -> str:
    return config.environment().upper()


def request_actor_kind() -> str:
    """Kind assigned by the server to an HTTP caller. Callers never choose their own kind."""
    environment = process_environment()
    if environment == "PRODUCTION":
        raise ActorRefused("authenticated identity is required in production and is not available before F3")
    return "SANDBOX" if environment == "SANDBOX" else "DECLARED"


def authorize(kind: str | None, incident: m.Incident) -> str:
    """Return the admissible actor kind for ``incident`` or raise ``ActorRefused``.

    ``None`` (a pre-F1 caller that names no kind) is read as DECLARED.
    """
    kind = kind or "DECLARED"
    if kind == "SYSTEM":
        return kind
    if incident.environment == "PRODUCTION":
        raise ActorRefused("production incidents accept only authenticated identity, which is not available before F3")
    if kind == "SANDBOX":
        if incident.environment != "SANDBOX" or process_environment() != "SANDBOX":
            raise ActorRefused("a sandbox identity is accepted only on sandbox incidents in a sandbox environment")
        return kind
    if kind == "DECLARED":
        if incident.environment != "UNSPECIFIED":
            raise ActorRefused(f"a caller-declared identity is not accepted on {incident.environment.lower()} incidents")
        return kind
    if kind == "SCENARIO":
        return kind
    raise ActorRefused(f"unknown actor kind {kind!r}")


def refuse_simulated_in_production(incident: m.Incident, provenance: str) -> None:
    if incident.environment == "PRODUCTION" and provenance == "SIMULATED":
        raise ActorRefused("simulated human input is not admissible on a production incident")
