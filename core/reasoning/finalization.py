"""Deterministic finalization of the async generators a reasoning run leaves suspended.

Strands stops iterating a tool or model stream at its result event and returns,
leaving that async generator suspended at its last ``yield``. CPython finalizes a
dropped suspended generator through the asyncio hook captured at its first
iteration, and that hook only *schedules* ``aclose()``: ``call_soon_threadsafe``
creates a task on one loop tick and the task first runs on the next. A generator
dropped inside the run's last two ticks (the supervisor's final structured-output
tool always is) therefore leaves a pending ``async_generator_athrow`` task when
``reason()`` returns; ``asyncio.run`` then cancels it during shutdown instead of
closing it, and any traceback cycle (an error tool result) moves the drop to GC
time, which is why the symptom is intermittent.

``AsyncGeneratorScope`` makes the cleanup explicit and synchronous with the run:

* generators first iterated inside the scope's task tree are tracked (attribution
  by ``contextvars``, so concurrent runs in one loop never close each other's
  still-needed generators) and any survivor is closed on exit;
* while a scope is active on this loop run, generators handed to the finalizer are
  kept and closed by the scope on exit instead of being scheduled fire-and-forget.

Nothing here sleeps, collects garbage or depends on reference-count timing. No
authority is involved: this is loop hygiene for the advisory reasoning path only.
"""
from __future__ import annotations

import contextvars
import sys
import threading
import weakref

__all__ = ["AsyncGeneratorScope"]

_ACTIVE: contextvars.ContextVar["AsyncGeneratorScope | None"] = contextvars.ContextVar(
    "operon_reasoning_generator_scope", default=None)


class _HookRegistry:
    """Per loop-run chain in front of asyncio's asyncgen hooks (hooks are per thread).

    The event loop installs its own hooks in ``run_forever`` and restores the
    previous ones on exit, so a registry lives exactly as long as the loop run that
    installed it and never outlives the loop's finalizer hook it chains to.
    """

    def __init__(self, chained_firstiter, chained_finalizer):
        self.chained_firstiter = chained_firstiter
        self.chained_finalizer = chained_finalizer
        self.lock = threading.Lock()
        self.active = 0          # scopes currently open on this loop run
        self.pending: list = []  # finalized suspended generators awaiting an explicit aclose()

    def firstiter(self, agen):
        scope = _ACTIVE.get()
        if scope is not None:
            scope.track(agen)
        if self.chained_firstiter is not None:
            self.chained_firstiter(agen)

    def finalizer(self, agen):
        # Captured at first iteration, so this runs for our generators whichever
        # thread drops the last reference. CPython only calls it for a suspended,
        # not yet closed generator, and at most once per generator.
        with self.lock:
            if self.active > 0:
                self.pending.append(agen)
                return
        if self.chained_finalizer is not None:
            self.chained_finalizer(agen)

    def open(self):
        with self.lock:
            self.active += 1

    def take_pending(self) -> list:
        """Hand out finalized generators; when none remain, close this scope's registration."""
        with self.lock:
            if self.pending:
                batch, self.pending = self.pending, []
                return batch
            self.active -= 1
            return []


def _registry() -> _HookRegistry:
    hooks = sys.get_asyncgen_hooks()
    owner = getattr(hooks.firstiter, "__self__", None)
    if isinstance(owner, _HookRegistry):
        return owner
    registry = _HookRegistry(hooks.firstiter, hooks.finalizer)
    sys.set_asyncgen_hooks(firstiter=registry.firstiter, finalizer=registry.finalizer)
    return registry


async def _aclose(agen):
    try:
        await agen.aclose()
    except Exception:
        # A generator that mishandles GeneratorExit is closed by that failure; loop
        # hygiene never turns a completed advisory result into an error.
        pass


class AsyncGeneratorScope:
    """``async with`` scope: every generator the run leaves suspended is closed on exit."""

    def __init__(self):
        self._generators: weakref.WeakSet = weakref.WeakSet()
        self._registry: _HookRegistry | None = None
        self._token = None
        self.closed = 0

    def track(self, agen):
        self._generators.add(agen)

    def suspended(self) -> list:
        """Tracked generators still alive, suspended and not running."""
        return [agen for agen in list(self._generators) if agen.ag_frame is not None and not agen.ag_running]

    async def close(self) -> int:
        """Close survivors and finalized generators deterministically; finished ones are no-ops."""
        for agen in self.suspended():
            await _aclose(agen)
            self.closed += 1
        if self._registry is not None:
            # Closing may drop further generators into the registry; drain until empty,
            # and only then release this scope's registration.
            while batch := self._registry.take_pending():
                for agen in batch:
                    await _aclose(agen)
                    self.closed += 1
            self._registry = None
        return self.closed

    async def __aenter__(self):
        self._registry = _registry()
        self._registry.open()
        self._token = _ACTIVE.set(self)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ACTIVE.reset(self._token)
        await self.close()
        return False
