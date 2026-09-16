"""Runtime events: durable rows become versioned websocket envelopes.

The existing ``/ws`` stream keeps its message types unchanged; PRISM adds one
additive message ``{"type": "prism", "prism_version": 1, "event": {...},
"session": {...compact view...}}``. Events carry identity and timestamps only:
no prompts, no results beyond bounded summaries, never a secret.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging

from .models import PrismEvent

PRISM_EVENT_VERSION = 1
EVENT_TYPES: tuple[str, ...] = (
    "session_created", "session_recovered", "turn_accepted", "fast_path_acknowledged", "slow_path_queued",
    "slow_path_started", "slow_path_progress", "interruption_received", "revision_superseded",
    "cancellation_requested", "run_cancelled", "run_completed", "run_failed", "stale_result_discarded",
    "canonical_state_updated", "effect_started", "effect_completed", "effect_refused", "reconnect_state",
)
logger = logging.getLogger(__name__)
Broadcast = Callable[[dict], Awaitable[None]]


def envelope(event: PrismEvent, session_view: dict | None) -> dict:
    return {"type": "prism", "prism_version": PRISM_EVENT_VERSION, "event": event.model_dump(mode="json"),
            "session": session_view}


class EventPublisher:
    """Fans durable events out to the websocket broadcast and in-process subscribers."""

    def __init__(self, broadcast: Broadcast | None = None):
        self._broadcast = broadcast
        self._subscribers: list[Callable[[dict], None]] = []
        self.published: int = 0

    def subscribe(self, callback: Callable[[dict], None]) -> Callable[[], None]:
        self._subscribers.append(callback)
        return lambda: self._subscribers.remove(callback)

    async def publish(self, events: list[PrismEvent], session_view: dict | None) -> None:
        for event in events:
            message = envelope(event, session_view)
            self.published += 1
            for callback in list(self._subscribers):
                try:
                    callback(message)
                except Exception:  # subscribers never break the runtime
                    logger.exception("prism event subscriber failed")
            if self._broadcast is not None:
                try:
                    await self._broadcast(message)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("prism event broadcast failed")
