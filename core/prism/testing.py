"""Deterministic Slow Path adapters for tests and the manual interruption scenario.

No model, no network. ``ControlledAdapter`` blocks until released, can ignore
cancellation, complete after supersession, fail, commit twice, or perform a
simulated effect. Everything it does still passes through the runtime's fence.
"""
from __future__ import annotations

import asyncio

from .cancellation import CancelledByRuntime, uninterruptible
from .models import ROLE_SLOW, SlowPathResult
from .slow_path import SlowPathExecution


class ControlledAdapter:
    name = "controlled"

    def __init__(self, *, ignore_cancellation: bool = False, fail_with: str | None = None,
                 duplicate_completion: bool = False, effect: dict | None = None, effect_key: str | None = None,
                 auto_release: bool = False):
        self.ignore_cancellation = ignore_cancellation
        self.fail_with = fail_with
        self.duplicate_completion = duplicate_completion
        self.effect = effect
        self.effect_key = effect_key
        self.auto_release = auto_release
        self.release = asyncio.Event()
        self.started: list[SlowPathExecution] = []
        self.finished: list[str] = []
        self.cancelled: list[str] = []
        self.performed_effects: list[dict] = []
        self.results: dict[str, SlowPathResult] = {}

    @property
    def cancellable(self) -> bool:
        return not self.ignore_cancellation

    def identity(self) -> dict:
        return {"adapter": self.name, "role": ROLE_SLOW, "provider": "none", "model": None, "live_model": False,
                "provenance": "INJECTED", "implementation": "operon.prism.testing.controlled",
                "cancellable": self.cancellable}

    def result_for(self, execution: SlowPathExecution) -> SlowPathResult:
        return SlowPathResult(summary=f"result of revision {execution.revision} run {execution.run_id}",
                              findings=[execution.turn.content], provenance="INJECTED", runtime=self.identity(),
                              details={"attempt": execution.identity.attempt})

    async def _wait(self, execution: SlowPathExecution) -> None:
        if self.auto_release:
            return
        if self.ignore_cancellation:
            await uninterruptible(self.release.wait())
            return
        waiter = asyncio.ensure_future(self.release.wait())
        canceller = asyncio.ensure_future(execution.cancellation.wait())
        try:
            done, _ = await asyncio.wait({waiter, canceller}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (waiter, canceller):
                if not task.done():
                    task.cancel()
        if canceller in done and not self.release.is_set():
            self.cancelled.append(execution.run_id)
            raise CancelledByRuntime(execution.cancellation.reason or "cancelled")

    async def run(self, execution: SlowPathExecution) -> SlowPathResult:
        self.started.append(execution)
        await self._wait(execution)
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        if self.effect is not None:
            async def perform():
                self.performed_effects.append({"run_id": execution.run_id, "revision": execution.revision})
                return {"ok": True, **self.effect}
            await execution.effect(tool_call_id=self.effect_key or "tool-call-1", kind="simulated_tool",
                                   payload=self.effect, perform=perform, idempotency_key=self.effect_key)
        result = self.result_for(execution)
        self.results[execution.run_id] = result
        if self.duplicate_completion:
            await execution.complete(result)   # first completion (through the runtime's fence)
        self.finished.append(execution.run_id)
        return result                          # second completion, via the runtime: must be a no-op
