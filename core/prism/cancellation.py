"""Cooperative cancellation for Slow Path work.

A ``CancellationToken`` is signalled when the run's revision is superseded (or on
shutdown). Workers that can stop check it; workers that cannot keep running and
their output is fenced. The token is an optimization: it never decides whether a
result is canonical (see ``fencing``).
"""
from __future__ import annotations

import asyncio
import time


class CancelledByRuntime(Exception):
    """Raised by ``raise_if_cancelled`` inside a cooperative worker."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class CancellationToken:
    def __init__(self):
        self._event = asyncio.Event()
        self.reason: str | None = None
        self.requested_at: float | None = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self, reason: str) -> bool:
        if self._event.is_set():
            return False
        self.reason, self.requested_at = reason, time.monotonic()
        self._event.set()
        return True

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledByRuntime(self.reason or "cancelled")

    async def wait(self, timeout: float | None = None) -> bool:
        """Wait for a cancellation signal; ``True`` when signalled, ``False`` on timeout."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def sleep(self, seconds: float, *, step: float = 0.02) -> None:
        """Cooperative sleep: returns early (raising) when cancelled."""
        deadline = time.monotonic() + seconds
        while True:
            self.raise_if_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if await self.wait(min(step, remaining)):
                self.raise_if_cancelled()


async def uninterruptible(awaitable):
    """Run ``awaitable`` to completion even if this task is cancelled (models a non-cancellable worker).

    The cancellation request is swallowed here on purpose; the runtime fences whatever
    comes back. Only deterministic test adapters and explicitly non-cancellable
    integrations should use this.
    """
    inner = asyncio.ensure_future(awaitable)
    while True:
        try:
            return await asyncio.shield(inner)
        except asyncio.CancelledError:
            if inner.done():
                raise
            continue
