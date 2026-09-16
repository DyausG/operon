"""PrismRuntime: the facade Operon's engine and API use.

Sessions, operator messages (Fast Path acknowledgement + Slow Path scheduling),
durable views for reconnect, startup recovery and shutdown. Correctness lives in
the repository transactions and the commit fence; this module only orchestrates.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
import time

from .coordinator import RunCoordinator
from .events import EventPublisher, PRISM_EVENT_VERSION
from .fast_path import DeterministicFastPath
from .fencing import CommitFence
from .idempotency import normalize_request
from .models import ACTIVE_RUN_STATUSES, CONTENT_TYPES, MAX_CONTENT_CHARS, MAX_METADATA_BYTES, MAX_METADATA_KEYS, RunStatus
from .observability import latency_summary, log_transition
from .recovery import DEFAULT_POLICY, POLICIES, describe as describe_recovery
from .repository import IdempotencyConflict, InvalidReference, PrismRepository, SessionNotFound
from .slow_path import adapter_from_environment

logger = logging.getLogger(__name__)
DEFAULT_DEADLINE_SECONDS = 600.0
RESET_TABLES = ("prism_event", "prism_effect", "prism_run", "prism_turn", "prism_session")


class MessageRejected(ValueError):
    pass


def validate_message(content: str, content_type: str, metadata: dict | None) -> dict:
    if not isinstance(content, str) or not content.strip():
        raise MessageRejected("content must be a non-empty string")
    if len(content) > MAX_CONTENT_CHARS:
        raise MessageRejected(f"content exceeds {MAX_CONTENT_CHARS} characters")
    if content_type not in CONTENT_TYPES:
        raise MessageRejected(f"content_type must be one of {', '.join(CONTENT_TYPES)}")
    metadata = dict(metadata or {})
    if len(metadata) > MAX_METADATA_KEYS:
        raise MessageRejected(f"metadata may hold at most {MAX_METADATA_KEYS} keys")
    for key, value in metadata.items():
        if not isinstance(key, str) or not key or len(key) > 40:
            raise MessageRejected("metadata keys must be strings of at most 40 characters")
        if not (value is None or isinstance(value, (str, int, float, bool))):
            raise MessageRejected("metadata values must be scalars")
        if isinstance(value, str) and len(value) > 500:
            raise MessageRejected("metadata string values must be at most 500 characters")
    import json
    if len(json.dumps(metadata, sort_keys=True).encode()) > MAX_METADATA_BYTES:
        raise MessageRejected(f"metadata exceeds {MAX_METADATA_BYTES} bytes")
    return metadata


class PrismRuntime:
    def __init__(self, repository: PrismRepository | None = None, *, adapter=None, fast_path=None,
                 incident_repository=None, broadcast=None, deadline_seconds: float | None = None,
                 recovery_policy: str = DEFAULT_POLICY):
        self.repository = repository or PrismRepository()
        self.adapter = adapter or adapter_from_environment()
        self.fast_path = fast_path or DeterministicFastPath()
        self.fence = CommitFence(self.repository)
        self.publisher = EventPublisher(broadcast)
        self.incident_repository = incident_repository
        self.coordinator = RunCoordinator(self.repository, self.fence, self.adapter, self.publisher,
                                          incident_repository=incident_repository, view=self.compact_view)
        if recovery_policy not in POLICIES:
            raise ValueError(f"unknown recovery policy {recovery_policy!r}")
        self.recovery_policy = recovery_policy
        env_deadline = os.getenv("OPERON_PRISM_SLOW_DEADLINE_SECONDS", "").strip()
        self.deadline_seconds = deadline_seconds if deadline_seconds is not None else (
            float(env_deadline) if env_deadline else DEFAULT_DEADLINE_SECONDS)
        self._locks: dict[str, asyncio.Lock] = {}
        self.recovered: list[dict] | None = None
        self.fast_path_samples: list[float] = []

    # ---- sessions -------------------------------------------------------------------
    async def create_session(self, *, incident_id: str | None = None, metadata: dict | None = None) -> dict:
        metadata = validate_message("x", "text", metadata)  # bounds only
        session, events = self.repository.create_session(incident_id=incident_id, metadata=metadata)
        log_transition("session_created", session_id=session.session_id, incident_id=incident_id)
        await self.publisher.publish(events, self.compact_view(session.session_id))
        return self.session_view(session.session_id)

    def list_sessions(self, *, incident_id: str | None = None) -> list[dict]:
        return [self.compact_view(s.session_id) for s in self.repository.list_sessions(incident_id=incident_id)]

    # ---- operator messages -----------------------------------------------------------
    async def submit_message(self, session_id: str, *, content: str, content_type: str = "text",
                             request_id: str | None = None, idempotency_key: str | None = None,
                             metadata: dict | None = None, schedule_slow_path: bool = True) -> dict:
        """Accept operator input promptly. Never awaits the Slow Path."""
        started = time.monotonic()
        metadata = validate_message(content, content_type, metadata)
        request_id, idempotency_key = normalize_request(request_id, idempotency_key)
        deadline_at = datetime.now(timezone.utc) + timedelta(seconds=self.deadline_seconds)
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:  # in-process ordering only; the BEGIN IMMEDIATE transaction is the authority
            acceptance = self.repository.accept_turn(
                session_id, request_id=request_id, idempotency_key=idempotency_key, content=content,
                content_type=content_type, metadata=metadata, fast_path=self.fast_path,
                schedule_slow_path=schedule_slow_path, deadline_at=deadline_at, started_monotonic=started)
            ack = acceptance.turn.fast_path
            if not acceptance.duplicate and acceptance.superseded_runs:
                # Signal the old revision's workers immediately; N+1 never waits for N to stop.
                self.coordinator.supersede(
                    acceptance.superseded_runs, reason=f"superseded by revision {acceptance.turn.revision}")
            log_transition("turn_accepted" if not acceptance.duplicate else "turn_deduplicated",
                           session_id=session_id, turn_id=acceptance.turn.turn_id, revision=acceptance.turn.revision,
                           request_id=request_id, idempotency_key=idempotency_key,
                           run_id=acceptance.run.run_id if acceptance.run else None,
                           superseded=[r.run_id for r in acceptance.superseded_runs], fast_path=ack.status,
                           latency_ms=ack.latency_ms)
            # Acceptance events go out before the new run is scheduled so clients always see
            # accepted -> acknowledged -> queued -> started in that order.
            await self.publisher.publish(list(acceptance.events), self.compact_view(session_id))
            if not acceptance.duplicate and acceptance.run is not None:
                self.coordinator.schedule(acceptance.run, acceptance.turn, acceptance.session)
        if ack.latency_ms is not None and not acceptance.duplicate:
            self.fast_path_samples.insert(0, ack.latency_ms)
            del self.fast_path_samples[500:]
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 3)
        return {
            "ok": True, "session_id": session_id, "turn_id": acceptance.turn.turn_id,
            "revision": acceptance.turn.revision, "request_id": request_id, "idempotency_key": idempotency_key,
            "duplicate": acceptance.duplicate, "fast_path": ack.model_dump(mode="json"),
            "slow_path": self._run_summary(acceptance.run),
            "superseded": {"revision": ack.superseded_revision,
                           "run_ids": [r.run_id for r in acceptance.superseded_runs]} if ack.superseded_revision else None,
            "current_revision": acceptance.session.current_revision, "acceptance_ms": elapsed_ms,
        }

    # ---- views -----------------------------------------------------------------------------
    @staticmethod
    def _run_summary(run) -> dict | None:
        if run is None:
            return None
        return {"run_id": run.run_id, "revision": run.revision, "attempt": run.attempt, "status": run.status.value,
                "stale": run.stale, "role": run.role, "runtime": run.runtime, "cancellation_reason": run.cancellation_reason,
                "recovered_from_run_id": run.recovered_from_run_id, "error": run.error,
                "created_at": run.created_at.isoformat(), "started_at": run.started_at.isoformat() if run.started_at else None,
                "superseded_at": run.superseded_at.isoformat() if run.superseded_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None}

    def _state_of(self, session, runs, current_run) -> str:
        if session.current_revision == 0:
            return "idle"
        if session.recovery and current_run is not None and current_run.recovered_from_run_id:
            if current_run.status in ACTIVE_RUN_STATUSES:
                return "recovering"
        if any(r.status == RunStatus.CANCELLING for r in runs):
            return "superseding"
        if current_run is None:
            return "fast_path"
        if current_run.status in (RunStatus.QUEUED, RunStatus.RUNNING):
            return "slow_path"
        if current_run.status == RunStatus.COMPLETED:
            return "completed"
        if current_run.status == RunStatus.FAILED:
            return "failed"
        if current_run.status == RunStatus.CANCELLED:
            return "cancelled"
        return "fast_path"

    def compact_view(self, session_id: str) -> dict | None:
        try:
            return self._view(session_id, full=False)
        except SessionNotFound:
            return None

    def session_view(self, session_id: str) -> dict:
        return self._view(session_id, full=True)

    def _view(self, session_id: str, *, full: bool) -> dict:
        session = self.repository.get_session(session_id)
        turns = self.repository.list_turns(session_id)
        runs = self.repository.list_runs(session_id)
        current_turn = next((t for t in turns if t.turn_id == session.current_turn_id), None)
        current_runs = [r for r in runs if r.revision == session.current_revision]
        current_run = current_runs[-1] if current_runs else None
        active_run = next((r for r in reversed(runs) if r.status in ACTIVE_RUN_STATUSES and r.revision == session.current_revision), None)
        superseding = [r for r in runs if r.status == RunStatus.CANCELLING]
        interruption = None
        latest_superseded = [r for r in runs if r.superseded_at is not None]
        if latest_superseded:
            last = max(latest_superseded, key=lambda r: (r.superseded_at, r.revision))
            interruption = {"superseded_revision": last.revision, "superseded_by": session.current_revision,
                            "run_ids": [r.run_id for r in latest_superseded if r.revision == last.revision],
                            "at": last.superseded_at.isoformat(), "still_running": [r.run_id for r in superseding]}
        stale = [r for r in runs if r.status == RunStatus.STALE]
        failure = next((r for r in reversed(runs) if r.status == RunStatus.FAILED and not r.stale
                        and r.revision == session.current_revision), None)
        view = {
            "session_id": session.session_id, "incident_id": session.incident_id, "status": session.status,
            "current_revision": session.current_revision, "current_turn_id": session.current_turn_id,
            "canonical_revision": session.canonical_revision, "canonical_run_id": session.canonical_run_id,
            "canonical": session.canonical, "canonical_current": session.canonical_revision == session.current_revision,
            "fast_path": current_turn.fast_path.model_dump(mode="json") if current_turn else None,
            "slow_path": self._run_summary(current_run), "active_run": self._run_summary(active_run),
            "runtime_state": self._state_of(session, runs, current_run),
            "interruption": interruption,
            "stale_results": len(stale), "stale_run_ids": [r.run_id for r in stale],
            "superseded_runs": sum(1 for r in runs if r.stale), "cancelled_runs": sum(1 for r in runs if r.status == RunStatus.CANCELLED),
            "last_failure": self._run_summary(failure),
            "recovery": {**session.recovery, "description": describe_recovery(session.recovery)} if session.recovery else None,
            "provenance": self.adapter.identity(), "fast_path_identity": getattr(self.fast_path, "identity", {}),
            "in_process_runs": [r for r in self.coordinator.active_run_ids() if any(x.run_id == r for x in runs)],
            "turn_count": len(turns), "run_count": len(runs), "metadata": session.metadata,
            "created_at": session.created_at.isoformat(), "updated_at": session.updated_at.isoformat(),
            "prism_version": PRISM_EVENT_VERSION,
        }
        if full:
            view["turns"] = [{"turn_id": t.turn_id, "revision": t.revision, "request_id": t.request_id,
                              "idempotency_key": t.idempotency_key, "content_type": t.content_type,
                              "content": t.content, "metadata": t.metadata, "fast_path": t.fast_path.model_dump(mode="json"),
                              "created_at": t.created_at.isoformat()} for t in turns]
            view["runs"] = [{**self._run_summary(r), "turn_id": r.turn_id, "result": r.result} for r in runs]
            view["effects"] = [e.model_dump(mode="json") for e in self.repository.list_effects(session_id)]
            view["events"] = [e.model_dump(mode="json") for e in self.repository.list_events(session_id)[-100:]]
            if session.incident_id and self.incident_repository is not None:
                try:
                    incident = self.incident_repository.fetch_incident(session.incident_id)
                    view["incident"] = {"id": incident.id, "phase": incident.phase.value, "revision": incident.revision}
                except LookupError:
                    view["incident"] = None
        return view

    def reconnect_state(self, session_id: str, *, after_event_id: int = 0) -> dict:
        """What a reconnecting client needs: the durable view plus events it missed."""
        view = self.session_view(session_id)
        events = self.repository.list_events(session_id, after_id=after_event_id)
        return {"ok": True, "type": "prism_reconnect", "prism_version": PRISM_EVENT_VERSION, "session": view,
                "events": [e.model_dump(mode="json") for e in events],
                "recovered": self.recovered is not None, "recovery": view.get("recovery")}

    def overview(self) -> dict:
        sessions = [self.compact_view(s.session_id) for s in self.repository.list_sessions()]
        return {"prism_version": PRISM_EVENT_VERSION, "sessions": [s for s in sessions if s],
                "slow_path": self.adapter.identity(), "fast_path": getattr(self.fast_path, "identity", {}),
                "recovered": self.recovered, "metrics": self.metrics()}

    def metrics(self) -> dict:
        samples = self.fast_path_samples or self.repository.fast_path_latencies()
        return {"fast_path_acknowledgement": latency_summary(samples),
                "runs_committed": self.coordinator.completed, "runs_stale": self.coordinator.stale,
                "in_process_runs": len(self.coordinator.active_run_ids())}

    # ---- lifecycle -----------------------------------------------------------------------------
    async def recover(self) -> list[dict]:
        """Startup reconstruction: restore canonical revisions, classify incomplete runs, never revive superseded work."""
        reports, to_schedule, events = self.repository.recover(policy=self.recovery_policy)
        for run in to_schedule:
            turn = self.repository.get_turn(run.turn_id)
            session = self.repository.get_session(run.session_id)
            self.coordinator.schedule(run, turn, session)
        by_session: dict[str, list] = {}
        for event in events:
            by_session.setdefault(event.session_id, []).append(event)
        for session_id, session_events in by_session.items():
            await self.publisher.publish(session_events, self.compact_view(session_id))
        for report in reports:
            log_transition("session_recovered", **{k: v for k, v in report.items() if k != "policy"},
                           recovery_reason=report.get("policy"))
        self.recovered = reports
        return reports

    async def shutdown(self) -> None:
        await self.coordinator.shutdown()

    def reset_memory(self) -> None:
        self._locks.clear()
        self.coordinator.handles.clear()
        self.fast_path_samples.clear()
        self.recovered = None

    async def wait_idle(self, timeout: float = 10.0) -> bool:
        return await self.coordinator.wait_idle(timeout)


__all__ = ["IdempotencyConflict", "InvalidReference", "MessageRejected", "PrismRuntime", "RESET_TABLES",
           "SessionNotFound", "validate_message"]
