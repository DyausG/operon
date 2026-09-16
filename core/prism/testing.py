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

from core.reasoning.backend import ReasoningBackend


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


class FakeReasoningBackend(ReasoningBackend):
    """Injectable stand-in at the *production* reasoning seam (``ReasoningBackend.supervise``).

    It is driven through exactly the interface ``PromotionService.run_supervisor`` and the
    production PRISM adapter use, so tests exercise the real claim -> compute -> fence -> apply
    path. It can block until released, ignore cancellation (finish late), fail, or answer at
    once; it records every context it was asked to reason over (the reasoning request).
    Provenance is INJECTED; it never presents itself as a live model.
    """
    name = "fake"
    supports_progress = True

    def __init__(self, *, block: bool = True, ignore_cancellation: bool = False, fail_with: str | None = None,
                 auto_release: bool = False, result_factory=None, fail_calls: set[int] | None = None):
        self.block, self.ignore_cancellation, self.fail_with = block, ignore_cancellation, fail_with
        self.auto_release = auto_release
        self.fail_calls = fail_calls   # 1-based supervise() call numbers that fail (None: every call when fail_with)
        self.result_factory = result_factory
        self.release = asyncio.Event()
        self.contexts: list = []          # every SpecialistContext handed to the supervisor (in order)
        self.snapshots: list = []
        self.progress: list[dict] = []
        self.cancelled: list[str] = []
        self.completed: list[str] = []

    def identity(self) -> dict:
        return {"backend": self.name, "provider": "none", "model": None, "provenance": "INJECTED", "live_model": False,
                "implementation": "operon.prism.testing.fake-reasoning-backend"}

    def run_timeout(self) -> float:
        return 60.0

    async def supervise(self, service, context, *, bounds, snapshot=None, cancellation_result_handler=None,
                        progress=None, cancelled=None):
        self.contexts.append(context)
        self.snapshots.append(snapshot)
        call_no = len(self.contexts)
        if progress is not None:   # the real supervisor announces itself before any model turn; so does the fake
            progress({"stage": "supervisor_started", "provider": "none", "model": None, "run_purpose": context.run_purpose,
                      "evidence_count": len(context.evidence), "injected": True})
        if self.block and not self.auto_release:
            try:
                if self.ignore_cancellation:
                    await uninterruptible(self.release.wait())
                else:
                    await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.append(context.run_id)
                raise
        if self.fail_with and (self.fail_calls is None or call_no in self.fail_calls):
            raise RuntimeError(self.fail_with)
        if self.result_factory is not None:
            result = self.result_factory(context, snapshot, bounds)
        else:
            from core.demo_scenario import DeterministicAdvisoryBackend
            forward = None if progress is None else (
                lambda payload: None if payload.get("stage") == "supervisor_started" else progress(payload))
            result = await DeterministicAdvisoryBackend().supervise(service, context, bounds=bounds, snapshot=snapshot,
                                                                    progress=forward)
            decision = result.decision.model_copy(update={
                "reasoning_summary": f"Injected reasoning over: {context.question[:600]}"})
            result = result.model_copy(update={"decision": decision})
        self.completed.append(context.run_id)
        return result
