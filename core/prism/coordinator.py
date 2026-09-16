"""In-process run coordination: task registry, scheduling, cancellation signalling.

The coordinator is coordination, not authority. It starts Slow Path tasks, signals
their tokens when a revision is superseded, cancels the asyncio task when the
adapter says it can be cancelled, and hands every outcome to the commit fence.
A worker that survives cancellation (non-cancellable adapter, provider thread,
late result) simply reaches the fence later and is recorded stale.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import time

from .cancellation import CancellationToken, CancelledByRuntime
from .events import EventPublisher
from .fencing import CommitFence, StaleRevisionError
from .models import PrismRun, PrismSession, PrismTurn, RunIdentity
from .observability import log_transition
from .repository import PrismRepository
from .slow_path import SlowPathAdapter, SlowPathExecution, SlowPathUnavailable, incident_context

logger = logging.getLogger(__name__)


@dataclass
class RunHandle:
    identity: RunIdentity
    token: CancellationToken
    task: asyncio.Task | None = None
    started_monotonic: float = field(default_factory=time.monotonic)
    deadline_task: asyncio.Task | None = None
    incident_id: str | None = None

    @property
    def done(self) -> bool:
        return self.task is not None and self.task.done()


class RunCoordinator:
    def __init__(self, repository: PrismRepository, fence: CommitFence, adapter: SlowPathAdapter,
                 publisher: EventPublisher, *, incident_repository=None, view=None):
        self.repository, self.fence, self.adapter, self.publisher = repository, fence, adapter, publisher
        self.incident_repository = incident_repository
        self._view = view or (lambda session_id: None)
        self.handles: dict[str, RunHandle] = {}
        self.completed: int = 0
        self.stale: int = 0

    # ---- scheduling --------------------------------------------------------------
    def identity_for(self, run: PrismRun, turn: PrismTurn) -> RunIdentity:
        return RunIdentity(session_id=run.session_id, turn_id=run.turn_id, revision=run.revision, run_id=run.run_id,
                           attempt=run.attempt, request_id=turn.request_id, role=run.role)

    def schedule(self, run: PrismRun, turn: PrismTurn, session: PrismSession) -> RunHandle:
        if run.run_id in self.handles and not self.handles[run.run_id].done:
            return self.handles[run.run_id]
        identity = self.identity_for(run, turn)
        handle = RunHandle(identity=identity, token=CancellationToken(), incident_id=session.incident_id)
        self.handles[run.run_id] = handle
        handle.task = asyncio.create_task(self._execute(handle, turn, session, run.deadline_at),
                                          name=f"prism-slow:{run.session_id[:8]}:r{run.revision}:a{run.attempt}")
        return handle

    def supersede(self, runs, *, reason: str) -> list[str]:
        """Signal cooperative cancellation for superseded runs; hard-cancel when the adapter allows it."""
        signalled = []
        for run in runs:
            handle = self.handles.get(run.run_id)
            if handle is None or handle.done:
                continue
            handle.token.cancel(reason)
            if getattr(self.adapter, "cancellable", True) and handle.task is not None:
                handle.task.cancel()
            signalled.append(run.run_id)
            log_transition("cancellation_signalled", session_id=run.session_id, run_id=run.run_id,
                           revision=run.revision, reason=reason, hard_cancel=getattr(self.adapter, "cancellable", True))
        return signalled

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        tasks = []
        for handle in list(self.handles.values()):
            if handle.done or handle.task is None:
                continue
            handle.token.cancel("runtime_shutdown")
            handle.task.cancel()
            tasks.append(handle.task)
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
        self.handles.clear()

    async def wait_idle(self, timeout: float = 10.0) -> bool:
        tasks = [h.task for h in self.handles.values() if h.task is not None and not h.done]
        if not tasks:
            return True
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        return not pending

    def active_run_ids(self) -> list[str]:
        return [run_id for run_id, handle in self.handles.items() if not handle.done]

    def active_incident_ids(self) -> set[str]:
        """Incidents with an in-process Slow Path run (the engine suppresses its own diagnosis for them)."""
        return {handle.incident_id for handle in self.handles.values() if not handle.done and handle.incident_id}

    # ---- execution -------------------------------------------------------------------
    async def _publish(self, events, session_id: str) -> None:
        if events:
            await self.publisher.publish(list(events), self._view(session_id))

    async def _progress(self, identity: RunIdentity, payload: dict) -> None:
        try:
            events = self.repository.progress(identity, payload)
        except Exception:  # progress is audit only
            logger.debug("prism progress not recorded", exc_info=True)
            return
        await self._publish(events, identity.session_id)

    async def _deadline(self, handle: RunHandle, seconds: float) -> None:
        await asyncio.sleep(seconds)
        if not handle.done:
            handle.token.cancel("deadline_exceeded")
            if getattr(self.adapter, "cancellable", True) and handle.task is not None:
                handle.task.cancel()

    async def _execute(self, handle: RunHandle, turn: PrismTurn, session: PrismSession, deadline_at) -> None:
        identity = handle.identity
        runtime = self.adapter.identity()
        started, events = self.repository.start_run(identity, runtime=runtime)
        await self._publish(events, identity.session_id)
        if started is None:
            log_transition("slow_path_not_started", session_id=identity.session_id, run_id=identity.run_id,
                           revision=identity.revision, reason="superseded before start")
            return
        log_transition("slow_path_started", session_id=identity.session_id, turn_id=identity.turn_id,
                       run_id=identity.run_id, revision=identity.revision, attempt=identity.attempt,
                       previous_status="QUEUED", new_status="RUNNING", runtime=runtime)
        deadline_monotonic = None
        if deadline_at is not None:
            deadline = deadline_at if isinstance(deadline_at, datetime) else datetime.fromisoformat(str(deadline_at))
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            deadline_monotonic = time.monotonic() + max(0.0, remaining)
            handle.deadline_task = asyncio.create_task(self._deadline(handle, max(0.0, remaining)))
        context = incident_context(self.incident_repository, session.incident_id)
        canonical = session.canonical or {}
        context["session"] = {"session_id": session.session_id, "canonical_revision": session.canonical_revision,
                              "canonical_run_id": session.canonical_run_id,
                              "canonical_summary": (canonical.get("result") or {}).get("summary")}
        execution = SlowPathExecution(
            identity=identity, turn=turn, context=context,
            cancellation=handle.token, fence=self.fence.for_run(identity), runtime=runtime,
            deadline_monotonic=deadline_monotonic, role=identity.role,
            progress=lambda payload: self._progress(identity, payload),
            commit=lambda result, apply=None: self._commit(handle, result, runtime, apply=apply),
            publish=lambda events: self._publish(events, identity.session_id))
        try:
            try:
                result = await self.adapter.run(execution)
            finally:
                if handle.deadline_task is not None:
                    handle.deadline_task.cancel()
            if execution.decision is None:
                # Every result passes the fence exactly here unless the adapter already
                # completed explicitly (with an atomic apply); a second pass is a no-op.
                await self._commit(handle, result, runtime)
        except (asyncio.CancelledError, CancelledByRuntime) as exc:
            reason = handle.token.reason or ("runtime_cancelled" if isinstance(exc, asyncio.CancelledError) else str(exc))
            if reason == "deadline_exceeded":
                run, events = self.repository.fail_run(identity, {"code": "deadline_exceeded",
                                                                  "message": "slow path exceeded its deadline"})
            else:
                run, events = self.repository.cancel_run(identity, reason)
            await self._publish(events, identity.session_id)
            log_transition("slow_path_cancelled", session_id=identity.session_id, run_id=identity.run_id,
                           revision=identity.revision, reason=reason, new_status=run.status.value if run else None,
                           latency_ms=round((time.monotonic() - handle.started_monotonic) * 1000, 1))
            if isinstance(exc, asyncio.CancelledError) and not handle.token.cancelled:
                raise
            return
        except StaleRevisionError as exc:
            run, events = self.repository.cancel_run(identity, f"effect refused: {exc.decision.reason}")
            await self._publish(events, identity.session_id)
            log_transition("slow_path_effect_refused", session_id=identity.session_id, run_id=identity.run_id,
                           revision=identity.revision, current_revision=exc.decision.current_revision,
                           reason=exc.decision.reason, stale=True)
            return
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, never re-raised into the loop
            code = getattr(exc, "code", type(exc).__name__)
            run, events = self.repository.fail_run(identity, {"code": str(code), "message": str(exc)[:1000]})
            await self._publish(events, identity.session_id)
            log_transition("slow_path_failed", level=logging.WARNING, session_id=identity.session_id,
                           run_id=identity.run_id, revision=identity.revision, error_code=str(code),
                           stale=run.stale if run else None, new_status=run.status.value if run else None)
            return

    async def _commit(self, handle: RunHandle, result, runtime: dict, apply=None):
        """Every result, early or final, passes through the fence exactly here; duplicates are no-ops."""
        identity = handle.identity
        decision, events = self.fence.commit(identity, result, runtime=runtime, apply=apply)
        await self._publish(events, identity.session_id)
        if decision.committed:
            self.completed += 1
        elif decision.reason != "already_terminal":
            self.stale += 1
        log_transition("slow_path_result", session_id=identity.session_id, turn_id=identity.turn_id,
                       run_id=identity.run_id, revision=identity.revision, current_revision=decision.current_revision,
                       canonical=decision.committed, stale=not decision.committed, fence_reason=decision.reason,
                       previous_status="RUNNING", new_status="COMPLETED" if decision.committed else "STALE",
                       latency_ms=round((time.monotonic() - handle.started_monotonic) * 1000, 1))
        return decision


__all__ = ["RunCoordinator", "RunHandle", "SlowPathUnavailable"]
