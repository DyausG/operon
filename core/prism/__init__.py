"""PRISM interruptible runtime (Samsung PRISM Theme 5, Stage 1 foundation).

Invariant: once revision N is superseded by N+1, no result produced for N may
mutate canonical state. ``fencing`` enforces it inside the repository transaction;
everything else (cancellation, scheduling, events, UI) is built around that.
Importing this package creates no client, session, socket or provider.
"""
from .models import (Acceptance, CommitDecision, FastPathState, PrismEffect, PrismEvent, PrismRun, PrismSession,
                     PrismTurn, RunIdentity, RunStatus, SlowPathResult)
from .repository import IdempotencyConflict, InvalidReference, PrismRepository, SessionNotFound
from .runtime import MessageRejected, PrismRuntime, RESET_TABLES

__all__ = ["Acceptance", "CommitDecision", "FastPathState", "IdempotencyConflict", "InvalidReference", "MessageRejected",
           "PrismEffect", "PrismEvent", "PrismRepository", "PrismRun", "PrismRuntime", "PrismSession", "PrismTurn",
           "RESET_TABLES", "RunIdentity", "RunStatus", "SessionNotFound", "SlowPathResult"]
