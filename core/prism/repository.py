"""Durable PRISM state: short SQLite transactions with compare-and-swap predicates.

Follows the Operon repository conventions (``core.reliability.repository``): every
mutation runs inside ``BEGIN IMMEDIATE``; every UPDATE carries the state it expects
(``WHERE current_revision=?``, ``WHERE status IN (...)``) and a ``rowcount != 1``
fails closed. The database triggers (migration 008) refuse rewrites of terminal
runs, completed effects, turns and events, so even a logic slip cannot rewrite
history. Provider secrets never reach this module.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from core import db
from core.reliability.repository import content_hash

from . import fencing
from .models import (
    Acceptance, CommitDecision, EffectStatus, FastPathState, PrismEffect, PrismEvent, PrismRun,
    PrismSession, PrismTurn, RunIdentity, RunStatus, SlowPathResult, TERMINAL_RUN_STATUSES, validate_run_transition,
)


class SessionNotFound(LookupError):
    pass


class RunNotFound(LookupError):
    pass


class EffectNotFound(LookupError):
    pass


class IdempotencyConflict(ValueError):
    """The same idempotency key was reused for a different request."""


class InvalidReference(ValueError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid4())


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _loads(value):
    return json.loads(value) if value else None


def _row_session(row) -> PrismSession:
    return PrismSession(
        session_id=row["session_id"], incident_id=row["incident_id"], status=row["status"],
        current_revision=row["current_revision"], current_turn_id=row["current_turn_id"],
        canonical_revision=row["canonical_revision"], canonical_run_id=row["canonical_run_id"],
        canonical=_loads(row["canonical_json"]), recovery=_loads(row["recovery_json"]),
        metadata=_loads(row["metadata_json"]) or {}, created_at=row["created_at"], updated_at=row["updated_at"])


def _row_turn(row) -> PrismTurn:
    return PrismTurn(
        turn_id=row["turn_id"], session_id=row["session_id"], revision=row["revision"], request_id=row["request_id"],
        idempotency_key=row["idempotency_key"], content_type=row["content_type"], content=row["content"],
        content_hash=row["content_hash"], metadata=_loads(row["metadata_json"]) or {},
        fast_path=FastPathState.model_validate(json.loads(row["fast_path_json"])), created_at=row["created_at"])


def _row_run(row) -> PrismRun:
    return PrismRun(
        run_id=row["run_id"], session_id=row["session_id"], turn_id=row["turn_id"], revision=row["revision"],
        attempt=row["attempt"], role=row["role"], status=RunStatus(row["status"]), stale=bool(row["stale"]),
        runtime=_loads(row["runtime_json"]), result=_loads(row["result_json"]), error=_loads(row["error_json"]),
        cancellation_reason=row["cancellation_reason"], recovered_from_run_id=row["recovered_from_run_id"],
        deadline_at=row["deadline_at"], created_at=row["created_at"], updated_at=row["updated_at"],
        started_at=row["started_at"], superseded_at=row["superseded_at"], cancelled_at=row["cancelled_at"],
        completed_at=row["completed_at"])


def _row_effect(row) -> PrismEffect:
    return PrismEffect(
        effect_id=row["effect_id"], session_id=row["session_id"], revision=row["revision"], run_id=row["run_id"],
        tool_call_id=row["tool_call_id"], idempotency_key=row["idempotency_key"], kind=row["kind"],
        request_hash=row["request_hash"], status=EffectStatus(row["status"]), result=_loads(row["result_json"]),
        created_at=row["created_at"], updated_at=row["updated_at"], completed_at=row["completed_at"])


def _row_event(row) -> PrismEvent:
    return PrismEvent(event_id=row["event_id"], session_id=row["session_id"], revision=row["revision"],
                      turn_id=row["turn_id"], run_id=row["run_id"], event_type=row["event_type"],
                      payload=json.loads(row["payload_json"]), created_at=row["created_at"])


class PrismRepository:
    def __init__(self, path: Path | None = None):
        self.path = Path(path if path is not None else db.DB_PATH)

    # ---- transaction helpers ----------------------------------------------
    @contextmanager
    def _write(self):
        with db.get_conn(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    @contextmanager
    def _read(self):
        with db.get_conn(self.path) as conn:
            yield conn

    @staticmethod
    def _session(conn, session_id: str) -> PrismSession:
        row = conn.execute("SELECT * FROM prism_session WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        return _row_session(row)

    @staticmethod
    def _run(conn, run_id: str) -> PrismRun:
        row = conn.execute("SELECT * FROM prism_run WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return _row_run(row)

    @staticmethod
    def _turn(conn, turn_id: str) -> PrismTurn:
        row = conn.execute("SELECT * FROM prism_turn WHERE turn_id=?", (turn_id,)).fetchone()
        if row is None:
            raise InvalidReference(turn_id)
        return _row_turn(row)

    @staticmethod
    def _event(conn, session_id: str, event_type: str, payload: dict, *, revision=None, turn_id=None,
               run_id=None, at: datetime | None = None) -> PrismEvent:
        at = at or utcnow()
        cursor = conn.execute(
            "INSERT INTO prism_event (session_id,revision,turn_id,run_id,event_type,payload_json,created_at) "
            "VALUES (?,?,?,?,?,?,?)", (session_id, revision, turn_id, run_id, event_type, _json(payload), at.isoformat()))
        return PrismEvent(event_id=cursor.lastrowid, session_id=session_id, revision=revision, turn_id=turn_id,
                          run_id=run_id, event_type=event_type, payload=payload, created_at=at)

    @staticmethod
    def _touch_session(conn, session: PrismSession, at: datetime, **changes) -> PrismSession:
        """CAS on the session's current revision; a concurrent revision change fails closed."""
        updated = session.model_copy(update={**changes, "updated_at": at})
        cursor = conn.execute(
            "UPDATE prism_session SET status=?,current_revision=?,current_turn_id=?,canonical_revision=?,"
            "canonical_run_id=?,canonical_json=?,recovery_json=?,updated_at=? "
            "WHERE session_id=? AND current_revision=?",
            (updated.status, updated.current_revision, updated.current_turn_id, updated.canonical_revision,
             updated.canonical_run_id, _json(updated.canonical) if updated.canonical is not None else None,
             _json(updated.recovery) if updated.recovery is not None else None, at.isoformat(),
             session.session_id, session.current_revision))
        if cursor.rowcount != 1:
            raise RuntimeError(f"session {session.session_id} changed concurrently; refusing to commit")
        return updated

    @staticmethod
    def _set_run_status(conn, run: PrismRun, target: RunStatus, at: datetime, **changes) -> PrismRun:
        """Graph-legal status change with a CAS on the previous status (terminal rows are trigger-protected)."""
        validate_run_transition(run.status, target)
        updated = run.model_copy(update={**changes, "status": target, "updated_at": at})
        cursor = conn.execute(
            "UPDATE prism_run SET status=?,stale=?,runtime_json=?,result_json=?,error_json=?,cancellation_reason=?,"
            "updated_at=?,started_at=?,superseded_at=?,cancelled_at=?,completed_at=? WHERE run_id=? AND status=?",
            (updated.status.value, int(updated.stale), _json(updated.runtime) if updated.runtime is not None else None,
             _json(updated.result) if updated.result is not None else None,
             _json(updated.error) if updated.error is not None else None, updated.cancellation_reason,
             at.isoformat(), _iso(updated.started_at), _iso(updated.superseded_at), _iso(updated.cancelled_at),
             _iso(updated.completed_at), run.run_id, run.status.value))
        if cursor.rowcount != 1:
            raise RuntimeError(f"run {run.run_id} changed concurrently; refusing {target.value}")
        return updated

    # ---- sessions -----------------------------------------------------------
    def create_session(self, *, incident_id: str | None = None, metadata: dict | None = None,
                       session_id: str | None = None) -> tuple[PrismSession, list[PrismEvent]]:
        now = utcnow()
        session = PrismSession(session_id=session_id or new_id(), incident_id=incident_id, current_revision=0,
                               metadata=dict(metadata or {}), created_at=now, updated_at=now)
        with self._write() as conn:
            if incident_id is not None and not conn.execute(
                    "SELECT 1 FROM incident WHERE incident_id=?", (incident_id,)).fetchone():
                raise InvalidReference(f"unknown incident {incident_id}")
            conn.execute("INSERT INTO prism_session (session_id,incident_id,status,current_revision,current_turn_id,"
                         "canonical_revision,canonical_run_id,canonical_json,recovery_json,metadata_json,created_at,"
                         "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (session.session_id, incident_id, "ACTIVE", 0, None, None, None, None, None,
                          _json(session.metadata), now.isoformat(), now.isoformat()))
            events = [self._event(conn, session.session_id, "session_created",
                                  {"incident_id": incident_id}, revision=0, at=now)]
        return session, events

    def get_session(self, session_id: str) -> PrismSession:
        with self._read() as conn:
            return self._session(conn, session_id)

    def list_sessions(self, *, incident_id: str | None = None) -> list[PrismSession]:
        with self._read() as conn:
            sql, params = "SELECT * FROM prism_session", ()
            if incident_id is not None:
                sql, params = sql + " WHERE incident_id=?", (incident_id,)
            return [_row_session(r) for r in conn.execute(sql + " ORDER BY created_at, session_id", params)]

    # ---- turns / revisions --------------------------------------------------
    def accept_turn(self, session_id: str, *, request_id: str, idempotency_key: str, content: str,
                    content_type: str, metadata: dict, fast_path, schedule_slow_path: bool = True,
                    role: str = "slow", deadline_at: datetime | None = None,
                    started_monotonic: float | None = None, clock=None) -> Acceptance:
        """Transactionally accept operator input: dedupe, advance revision N->N+1, supersede N's runs,
        persist the Fast Path acknowledgement and queue the N+1 Slow Path run.

        ``fast_path(turn_fields, session, superseded_revision, schedule) -> FastPathState`` is a pure
        deterministic function evaluated inside the transaction so the acknowledgement is durable with
        the turn. Duplicates (same session + idempotency key) return the original acceptance.
        """
        import time as _time
        request_hash = content_hash({"content": content, "content_type": content_type, "metadata": metadata})
        with self._write() as conn:
            session = self._session(conn, session_id)
            if session.status != "ACTIVE":
                raise InvalidReference(f"session {session_id} is closed")
            row = conn.execute("SELECT * FROM prism_turn WHERE session_id=? AND idempotency_key=?",
                               (session_id, idempotency_key)).fetchone()
            if row is not None:
                turn = _row_turn(row)
                if turn.content_hash != request_hash:
                    raise IdempotencyConflict(f"idempotency key {idempotency_key!r} is bound to a different request")
                run_row = conn.execute("SELECT * FROM prism_run WHERE turn_id=? ORDER BY attempt DESC LIMIT 1",
                                       (turn.turn_id,)).fetchone()
                return Acceptance(session=session, turn=turn, run=_row_run(run_row) if run_row else None,
                                  duplicate=True)
            now = utcnow()
            revision = session.current_revision + 1
            superseded_revision = session.current_revision if session.current_revision >= 1 else None
            turn_id = new_id()
            ack = fast_path({"turn_id": turn_id, "session_id": session_id, "revision": revision,
                             "request_id": request_id, "content": content, "content_type": content_type,
                             "metadata": metadata}, session, superseded_revision, schedule_slow_path)
            if not isinstance(ack, FastPathState) or ack.revision != revision:
                raise RuntimeError("fast path acknowledgement must carry the accepted revision")
            latency = None
            if started_monotonic is not None:
                latency = round(((clock or _time.monotonic)() - started_monotonic) * 1000.0, 3)
            ack = ack.model_copy(update={"latency_ms": latency})
            turn = PrismTurn(turn_id=turn_id, session_id=session_id, revision=revision, request_id=request_id,
                             idempotency_key=idempotency_key, content_type=content_type, content=content,
                             content_hash=request_hash, metadata=dict(metadata), fast_path=ack, created_at=now)
            conn.execute("INSERT INTO prism_turn (turn_id,session_id,revision,request_id,idempotency_key,content_type,"
                         "content,content_hash,metadata_json,fast_path_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (turn.turn_id, session_id, revision, request_id, idempotency_key, content_type, content,
                          request_hash, _json(turn.metadata), ack.model_dump_json(), now.isoformat()))
            # Supersede every still-active run of any older revision, in the same transaction.
            superseded: list[PrismRun] = []
            for run_row in conn.execute("SELECT * FROM prism_run WHERE session_id=? AND status IN ('QUEUED','RUNNING',"
                                        "'CANCELLING') AND revision<? ORDER BY revision, attempt", (session_id, revision)):
                run = _row_run(run_row)
                if run.status == RunStatus.QUEUED:
                    run = self._set_run_status(conn, run, RunStatus.SUPERSEDED, now, stale=True, superseded_at=now,
                                               completed_at=now, cancellation_reason=f"superseded by revision {revision}")
                elif run.status == RunStatus.RUNNING:
                    run = self._set_run_status(conn, run, RunStatus.CANCELLING, now, stale=True, superseded_at=now,
                                               cancellation_reason=f"superseded by revision {revision}")
                else:  # CANCELLING already: stays cancelling; record the newer revision
                    continue
                superseded.append(run)
            session = self._touch_session(conn, session, now, current_revision=revision, current_turn_id=turn_id)
            events = [self._event(conn, session_id, "turn_accepted",
                                  {"request_id": request_id, "idempotency_key": idempotency_key,
                                   "content_type": content_type, "content_chars": len(content)},
                                  revision=revision, turn_id=turn_id, at=now)]
            if superseded_revision is not None:
                events.append(self._event(conn, session_id, "interruption_received",
                                          {"superseded_revision": superseded_revision, "new_revision": revision},
                                          revision=revision, turn_id=turn_id, at=now))
                events.append(self._event(conn, session_id, "revision_superseded",
                                          {"revision": superseded_revision, "superseded_by": revision,
                                           "active_runs": [r.run_id for r in superseded]},
                                          revision=superseded_revision, turn_id=turn_id, at=now))
                for run in superseded:
                    events.append(self._event(conn, session_id, "cancellation_requested",
                                              {"previous_status": "QUEUED" if run.status == RunStatus.SUPERSEDED else "RUNNING",
                                               "new_status": run.status.value, "reason": run.cancellation_reason,
                                               "superseded_by": revision},
                                              revision=run.revision, turn_id=run.turn_id, run_id=run.run_id, at=now))
            events.append(self._event(conn, session_id, "fast_path_acknowledged",
                                      {"status": ack.status, "latency_ms": latency, "deeper_reasoning": ack.deeper_reasoning,
                                       "superseded_revision": ack.superseded_revision},
                                      revision=revision, turn_id=turn_id, at=now))
            run = None
            if schedule_slow_path and ack.deeper_reasoning == "scheduled":
                run = PrismRun(run_id=new_id(), session_id=session_id, turn_id=turn_id, revision=revision, attempt=1,
                               role=role, status=RunStatus.QUEUED, deadline_at=deadline_at, created_at=now, updated_at=now)
                self._insert_run(conn, run)
                events.append(self._event(conn, session_id, "slow_path_queued",
                                          {"attempt": 1, "role": role, "deadline_at": _iso(deadline_at)},
                                          revision=revision, turn_id=turn_id, run_id=run.run_id, at=now))
            return Acceptance(session=session, turn=turn, run=run, superseded_runs=tuple(superseded),
                              events=tuple(events))

    @staticmethod
    def _insert_run(conn, run: PrismRun) -> None:
        conn.execute("INSERT INTO prism_run (run_id,session_id,turn_id,revision,attempt,role,status,stale,runtime_json,"
                     "result_json,error_json,cancellation_reason,recovered_from_run_id,deadline_at,created_at,updated_at,"
                     "started_at,superseded_at,cancelled_at,completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (run.run_id, run.session_id, run.turn_id, run.revision, run.attempt, run.role, run.status.value,
                      int(run.stale), _json(run.runtime) if run.runtime is not None else None, None, None,
                      run.cancellation_reason, run.recovered_from_run_id, _iso(run.deadline_at),
                      run.created_at.isoformat(), run.updated_at.isoformat(), None, None, None, None))

    def get_turn(self, turn_id: str) -> PrismTurn:
        with self._read() as conn:
            return self._turn(conn, turn_id)

    def list_turns(self, session_id: str) -> list[PrismTurn]:
        with self._read() as conn:
            self._session(conn, session_id)
            return [_row_turn(r) for r in conn.execute(
                "SELECT * FROM prism_turn WHERE session_id=? ORDER BY revision", (session_id,))]

    # ---- runs -----------------------------------------------------------------
    def get_run(self, run_id: str) -> PrismRun:
        with self._read() as conn:
            return self._run(conn, run_id)

    def list_runs(self, session_id: str) -> list[PrismRun]:
        with self._read() as conn:
            self._session(conn, session_id)
            return [_row_run(r) for r in conn.execute(
                "SELECT * FROM prism_run WHERE session_id=? ORDER BY revision, attempt", (session_id,))]

    def start_run(self, identity: RunIdentity, *, runtime: dict | None = None) -> tuple[PrismRun | None, list[PrismEvent]]:
        """QUEUED -> RUNNING, only while the run's revision is still canonical. ``None`` = refused."""
        now = utcnow()
        with self._write() as conn:
            session = self._session(conn, identity.session_id)
            run = self._run(conn, identity.run_id)
            if run.status != RunStatus.QUEUED:
                return None, []
            if run.revision != session.current_revision or session.status != "ACTIVE":
                # Superseded between queueing and scheduling (or by a recovery race): never start it.
                run = self._set_run_status(conn, run, RunStatus.SUPERSEDED, now, stale=True, superseded_at=now,
                                           completed_at=now, cancellation_reason="superseded before start")
                events = [self._event(conn, run.session_id, "run_cancelled",
                                      {"previous_status": "QUEUED", "new_status": run.status.value,
                                       "reason": run.cancellation_reason}, revision=run.revision,
                                      turn_id=run.turn_id, run_id=run.run_id, at=now)]
                return None, events
            run = self._set_run_status(conn, run, RunStatus.RUNNING, now, started_at=now, runtime=runtime)
            events = [self._event(conn, run.session_id, "slow_path_started",
                                  {"attempt": run.attempt, "runtime": runtime or {}}, revision=run.revision,
                                  turn_id=run.turn_id, run_id=run.run_id, at=now)]
            return run, events

    def check_eligibility(self, identity: RunIdentity) -> CommitDecision:
        with self._read() as conn:
            try:
                session = self._session(conn, identity.session_id)
            except SessionNotFound:
                session = None
            try:
                run = self._run(conn, identity.run_id)
            except RunNotFound:
                run = None
            return fencing.decide(session, run, identity)

    def commit_result(self, identity: RunIdentity, result: SlowPathResult, *,
                      runtime: dict | None = None, apply=None) -> tuple[CommitDecision, list[PrismEvent]]:
        """THE commit fence transaction: eligibility and mutation under one BEGIN IMMEDIATE.

        Committed: run RUNNING -> COMPLETED, session canonical pointer <- (revision, run, result),
        CAS on ``current_revision``. Not committed: the result is kept on the run row as
        history (STALE / audit) and a ``stale_result_discarded`` event is recorded. A result
        for an already-terminal run changes nothing.

        ``apply(conn)`` (Stage 2) is the application's canonical write for a *current* result:
        it runs inside this same transaction, after the fence decided and before the run and
        session rows change, so an incident write and the PRISM commit are one atomic unit and
        a newer revision can never slip between them. Its return value (a JSON dict or ``None``)
        is stored under ``result.details["applied"]`` and as the durable ``apply:{run_id}``
        effect, which is the exactly-once identity of the application. If ``apply`` raises,
        the whole transaction rolls back: nothing is applied, nothing is committed.
        """
        result = SlowPathResult.model_validate(result.model_dump())
        now = utcnow()
        with self._write() as conn:
            try:
                session = self._session(conn, identity.session_id)
            except SessionNotFound:
                session = None
            try:
                run = self._run(conn, identity.run_id)
            except RunNotFound:
                run = None
            decision = fencing.decide(session, run, identity)
            if decision.committed:
                if apply is not None:
                    applied = apply(conn)
                    if applied is not None:
                        result = result.model_copy(update={"details": {**result.details, "applied": applied}})
                    key = f"apply:{run.run_id}"
                    effect = self._insert_effect(conn, identity, key, key, "canonical_apply",
                                                 content_hash({"run_id": run.run_id, "revision": run.revision}), now)
                    self._finish_effect(conn, identity, effect, "COMPLETED", applied, now)
                payload = result.model_dump(mode="json")
                run = self._set_run_status(conn, run, RunStatus.COMPLETED, now, result=payload, completed_at=now,
                                           runtime=runtime if runtime is not None else run.runtime)
                canonical = {"revision": run.revision, "run_id": run.run_id, "turn_id": run.turn_id,
                             "attempt": run.attempt, "committed_at": now.isoformat(), "result": payload}
                session = self._touch_session(conn, session, now, canonical_revision=run.revision,
                                              canonical_run_id=run.run_id, canonical=canonical)
                events = [self._event(conn, run.session_id, "run_completed",
                                      {"previous_status": "RUNNING", "new_status": "COMPLETED", "canonical": True,
                                       "provenance": result.provenance}, revision=run.revision, turn_id=run.turn_id,
                                      run_id=run.run_id, at=now),
                          self._event(conn, run.session_id, "canonical_state_updated",
                                      {"canonical_revision": run.revision, "run_id": run.run_id,
                                       "summary": result.summary[:200]}, revision=run.revision,
                                      turn_id=run.turn_id, run_id=run.run_id, at=now)]
                return decision, events
            if run is None or session is None or run.status in TERMINAL_RUN_STATUSES:
                return decision, []
            # Stale/discard record: the output is kept as history, never as canonical state.
            payload = result.model_dump(mode="json")
            run = self._set_run_status(conn, run, RunStatus.STALE, now, stale=True, result=payload, completed_at=now,
                                       runtime=runtime if runtime is not None else run.runtime,
                                       cancellation_reason=run.cancellation_reason or decision.reason)
            events = [self._event(conn, run.session_id, "stale_result_discarded",
                                  {"previous_status": decision.run_status.value if decision.run_status else None,
                                   "new_status": "STALE", "reason": decision.reason, "run_revision": run.revision,
                                   "current_revision": session.current_revision, "provenance": result.provenance},
                                  revision=run.revision, turn_id=run.turn_id, run_id=run.run_id, at=now)]
            return decision, events

    def fail_run(self, identity: RunIdentity, error: dict) -> tuple[PrismRun | None, list[PrismEvent]]:
        """Record a failure. A stale (superseded) run's failure stays historical, never the canonical failure."""
        now = utcnow()
        with self._write() as conn:
            session = self._session(conn, identity.session_id)
            run = self._run(conn, identity.run_id)
            if run.status in TERMINAL_RUN_STATUSES:
                return None, []
            stale = run.stale or run.revision != session.current_revision or run.status == RunStatus.CANCELLING
            run = self._set_run_status(conn, run, RunStatus.FAILED, now, stale=stale, error=dict(error), completed_at=now)
            events = [self._event(conn, run.session_id, "run_failed",
                                  {"new_status": "FAILED", "stale": stale, "canonical": not stale,
                                   "error": {k: error[k] for k in ("code", "message") if k in error}},
                                  revision=run.revision, turn_id=run.turn_id, run_id=run.run_id, at=now)]
            return run, events

    def cancel_run(self, identity: RunIdentity, reason: str) -> tuple[PrismRun | None, list[PrismEvent]]:
        """Worker acknowledged cancellation (QUEUED/RUNNING/CANCELLING -> CANCELLED)."""
        now = utcnow()
        with self._write() as conn:
            run = self._run(conn, identity.run_id)
            if run.status in TERMINAL_RUN_STATUSES:
                return None, []
            previous = run.status.value
            run = self._set_run_status(conn, run, RunStatus.CANCELLED, now, cancelled_at=now, completed_at=now,
                                       cancellation_reason=run.cancellation_reason or reason)
            events = [self._event(conn, run.session_id, "run_cancelled",
                                  {"previous_status": previous, "new_status": "CANCELLED", "reason": reason},
                                  revision=run.revision, turn_id=run.turn_id, run_id=run.run_id, at=now)]
            return run, events

    def progress(self, identity: RunIdentity, payload: dict) -> list[PrismEvent]:
        """Progress is audit only; it never changes state."""
        with self._write() as conn:
            run = self._run(conn, identity.run_id)
            return [self._event(conn, run.session_id, "slow_path_progress", dict(payload), revision=run.revision,
                                turn_id=run.turn_id, run_id=run.run_id)]

    # ---- effects ----------------------------------------------------------------
    def transact(self, identity: RunIdentity, *, kind: str, idempotency_key: str, request_hash: str,
                 perform) -> tuple[PrismEffect, bool, list[PrismEvent]]:
        """Atomic fenced write (Stage 2): eligibility, the caller's write and the effect record in ONE
        ``BEGIN IMMEDIATE``.

        ``perform(conn)`` writes through the caller-owned connection (for example the Operon
        incident tables, which share this database) and returns a JSON dict recorded as the
        effect result. If the run's revision is no longer canonical the write never starts
        (``effect_refused`` audited, ``StaleRevisionError`` raised). A duplicate key returns the
        recorded effect without performing anything. If ``perform`` raises, the transaction
        rolls back and nothing, not even the effect row, is left behind.
        Returns ``(effect, performed, events)``.
        """
        now = utcnow()
        refused = None
        events: list[PrismEvent] = []
        with self._write() as conn:
            session = self._session(conn, identity.session_id)
            run = self._run(conn, identity.run_id)
            decision = fencing.decide(session, run, identity)
            row = conn.execute("SELECT * FROM prism_effect WHERE session_id=? AND revision=? AND idempotency_key=?",
                               (identity.session_id, identity.revision, idempotency_key)).fetchone()
            if row is not None:
                existing = _row_effect(row)
                if (existing.kind, existing.request_hash) != (kind, request_hash):
                    raise IdempotencyConflict("effect idempotency key is bound to a different action")
                return existing, False, []
            if not decision.committed:
                events.append(self._event(conn, identity.session_id, "effect_refused",
                                          {"kind": kind, "tool_call_id": idempotency_key, "reason": decision.reason,
                                           "run_revision": identity.revision, "current_revision": session.current_revision},
                                          revision=identity.revision, turn_id=identity.turn_id, run_id=identity.run_id, at=now))
                refused = fencing.StaleRevisionError(decision)
                effect = None
            else:
                effect = self._insert_effect(conn, identity, idempotency_key, idempotency_key, kind, request_hash, now)
                outcome = perform(conn)
                effect = self._finish_effect(conn, identity, effect, "COMPLETED", outcome, now)
        if refused is not None:
            raise refused
        return effect, True, events

    def _finish_effect(self, conn, identity, effect: PrismEffect, status: str, result, now) -> PrismEffect:
        cursor = conn.execute("UPDATE prism_effect SET status=?,result_json=?,updated_at=?,completed_at=? "
                              "WHERE effect_id=? AND status='PENDING'",
                              (status, _json(result) if result is not None else None, now.isoformat(), now.isoformat(),
                               effect.effect_id))
        if cursor.rowcount != 1:
            raise RuntimeError("effect changed concurrently")
        self._event(conn, effect.session_id, "effect_completed", {"effect_id": effect.effect_id, "status": status,
                    "kind": effect.kind}, revision=effect.revision, turn_id=identity.turn_id, run_id=effect.run_id, at=now)
        return effect.model_copy(update={"status": EffectStatus(status), "result": result, "updated_at": now,
                                         "completed_at": now})

    def begin_effect(self, identity: RunIdentity, *, tool_call_id: str, idempotency_key: str, kind: str,
                     request_hash: str) -> tuple[PrismEffect, bool]:
        """Durable effect identity ``(session, revision, idempotency_key)``; fenced on the canonical revision."""
        now = utcnow()
        refused = None
        with self._write() as conn:
            session = self._session(conn, identity.session_id)
            run = self._run(conn, identity.run_id)
            decision = fencing.decide(session, run, identity)
            row = conn.execute("SELECT * FROM prism_effect WHERE session_id=? AND revision=? AND idempotency_key=?",
                               (identity.session_id, identity.revision, idempotency_key)).fetchone()
            if row is not None:
                existing = _row_effect(row)
                if (existing.kind, existing.request_hash) != (kind, request_hash):
                    raise IdempotencyConflict("effect idempotency key is bound to a different action")
                return existing, False
            if not decision.committed:
                # Audit the refusal in this (committed) transaction, then refuse the caller.
                self._event(conn, identity.session_id, "effect_refused",
                            {"kind": kind, "tool_call_id": tool_call_id, "reason": decision.reason,
                             "run_revision": identity.revision, "current_revision": session.current_revision},
                            revision=identity.revision, turn_id=identity.turn_id, run_id=identity.run_id, at=now)
                refused = fencing.StaleRevisionError(decision)
                effect = None
            else:
                effect = self._insert_effect(conn, identity, tool_call_id, idempotency_key, kind, request_hash, now)
        if refused is not None:
            raise refused
        return effect, True

    def _insert_effect(self, conn, identity, tool_call_id, idempotency_key, kind, request_hash, now) -> PrismEffect:
        effect = PrismEffect(effect_id=new_id(), session_id=identity.session_id, revision=identity.revision,
                             run_id=identity.run_id, tool_call_id=tool_call_id, idempotency_key=idempotency_key,
                             kind=kind, request_hash=request_hash, status=EffectStatus.PENDING,
                             created_at=now, updated_at=now)
        conn.execute("INSERT INTO prism_effect (effect_id,session_id,revision,run_id,tool_call_id,idempotency_key,"
                     "kind,request_hash,status,result_json,created_at,updated_at,completed_at) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (effect.effect_id, effect.session_id, effect.revision, effect.run_id, tool_call_id,
                      idempotency_key, kind, request_hash, "PENDING", None, now.isoformat(), now.isoformat(), None))
        self._event(conn, identity.session_id, "effect_started", {"effect_id": effect.effect_id, "kind": kind,
                    "tool_call_id": tool_call_id}, revision=identity.revision, turn_id=identity.turn_id,
                    run_id=identity.run_id, at=now)
        return effect

    def complete_effect(self, identity: RunIdentity, effect_id: str, *, status: str = "COMPLETED",
                        result: dict | None = None) -> tuple[PrismEffect, bool]:
        """Exactly one completion per effect; duplicates return the recorded outcome unchanged."""
        status = EffectStatus(status)
        if status == EffectStatus.PENDING:
            raise ValueError("completion requires a terminal effect status")
        now = utcnow()
        with self._write() as conn:
            row = conn.execute("SELECT * FROM prism_effect WHERE effect_id=?", (effect_id,)).fetchone()
            if row is None:
                raise EffectNotFound(effect_id)
            effect = _row_effect(row)
            if effect.run_id != identity.run_id or effect.session_id != identity.session_id:
                raise InvalidReference("effect belongs to a different run")
            if effect.status != EffectStatus.PENDING:
                return effect, False
            cursor = conn.execute("UPDATE prism_effect SET status=?,result_json=?,updated_at=?,completed_at=? "
                                  "WHERE effect_id=? AND status='PENDING'",
                                  (status.value, _json(result) if result is not None else None, now.isoformat(),
                                   now.isoformat(), effect_id))
            if cursor.rowcount != 1:
                raise RuntimeError("effect changed concurrently")
            effect = effect.model_copy(update={"status": status, "result": result, "updated_at": now, "completed_at": now})
            self._event(conn, effect.session_id, "effect_completed", {"effect_id": effect_id, "status": status.value,
                        "kind": effect.kind}, revision=effect.revision, turn_id=identity.turn_id,
                        run_id=effect.run_id, at=now)
            return effect, True

    def list_effects(self, session_id: str) -> list[PrismEffect]:
        with self._read() as conn:
            self._session(conn, session_id)
            return [_row_effect(r) for r in conn.execute(
                "SELECT * FROM prism_effect WHERE session_id=? ORDER BY created_at, effect_id", (session_id,))]

    # ---- events -----------------------------------------------------------------
    def list_events(self, session_id: str, *, after_id: int = 0, limit: int = 500) -> list[PrismEvent]:
        with self._read() as conn:
            self._session(conn, session_id)
            return [_row_event(r) for r in conn.execute(
                "SELECT * FROM prism_event WHERE session_id=? AND event_id>? ORDER BY event_id LIMIT ?",
                (session_id, after_id, limit))]

    # ---- recovery -----------------------------------------------------------------
    def recover(self, *, policy: str = "retry_current_revision") -> tuple[list[dict], list[PrismRun], list[PrismEvent]]:
        """Classify incomplete work after a restart in one transaction. Never revives superseded work.

        * QUEUED/RUNNING/CANCELLING runs of a non-current revision -> SUPERSEDED/CANCELLED (historical).
        * RUNNING/CANCELLING run of the current revision -> FAILED("process_restart"); with the default
          policy a fresh QUEUED attempt (new run_id, attempt+1, ``recovered_from_run_id``) is created
          unless that revision already has canonical state. Committed effects are never repeated: they
          stay on the old run and are visible to the new attempt through the effect ledger.
        * QUEUED run of the current revision -> returned for scheduling unchanged.
        * PENDING effects of interrupted runs -> UNKNOWN (truthful: outcome not observed).
        Returns (per-session reports, runs to schedule, events).
        """
        now = utcnow()
        reports, to_schedule, events = [], [], []
        with self._write() as conn:
            for srow in conn.execute("SELECT * FROM prism_session WHERE status='ACTIVE' ORDER BY created_at, session_id"):
                session = _row_session(srow)
                report = {"session_id": session.session_id, "current_revision": session.current_revision,
                          "canonical_revision": session.canonical_revision, "policy": policy,
                          "superseded_runs": [], "retried": None, "scheduled": [], "failed_runs": [],
                          "unknown_effects": [], "recovered_at": now.isoformat()}
                active = [_row_run(r) for r in conn.execute(
                    "SELECT * FROM prism_run WHERE session_id=? AND status IN ('QUEUED','RUNNING','CANCELLING') "
                    "ORDER BY revision, attempt", (session.session_id,))]
                if not active:
                    continue
                for run in active:
                    if run.revision != session.current_revision:
                        target = RunStatus.SUPERSEDED if run.status == RunStatus.QUEUED else RunStatus.CANCELLED
                        run = self._set_run_status(conn, run, target, now, stale=True, completed_at=now,
                                                   superseded_at=run.superseded_at or now,
                                                   cancelled_at=now if target == RunStatus.CANCELLED else None,
                                                   cancellation_reason=run.cancellation_reason
                                                   or f"recovery: superseded by revision {session.current_revision}")
                        report["superseded_runs"].append(run.run_id)
                        events.append(self._event(conn, session.session_id, "run_cancelled",
                                                  {"new_status": run.status.value, "reason": run.cancellation_reason,
                                                   "recovery": True}, revision=run.revision, turn_id=run.turn_id,
                                                  run_id=run.run_id, at=now))
                        self._orphan_effects(conn, run, now, report)
                        continue
                    if run.status == RunStatus.QUEUED:
                        to_schedule.append(run)
                        report["scheduled"].append(run.run_id)
                        continue
                    # RUNNING or CANCELLING at the canonical revision: the process died mid-run.
                    failed = self._set_run_status(conn, run, RunStatus.FAILED, now, completed_at=now,
                                                  error={"code": "process_restart",
                                                         "message": "run interrupted by process restart"},
                                                  cancellation_reason=run.cancellation_reason or "process_restart")
                    report["failed_runs"].append(failed.run_id)
                    events.append(self._event(conn, session.session_id, "run_failed",
                                              {"new_status": "FAILED", "stale": False, "reason": "process_restart",
                                               "recovery": True}, revision=run.revision, turn_id=run.turn_id,
                                              run_id=run.run_id, at=now))
                    self._orphan_effects(conn, run, now, report)
                    if (policy == "retry_current_revision" and run.status != RunStatus.CANCELLING
                            and session.canonical_revision != run.revision):
                        retry = PrismRun(run_id=new_id(), session_id=run.session_id, turn_id=run.turn_id,
                                         revision=run.revision, attempt=run.attempt + 1, role=run.role,
                                         status=RunStatus.QUEUED, recovered_from_run_id=run.run_id,
                                         deadline_at=run.deadline_at, created_at=now, updated_at=now)
                        self._insert_run(conn, retry)
                        to_schedule.append(retry)
                        report["retried"] = {"from_run_id": run.run_id, "run_id": retry.run_id, "attempt": retry.attempt}
                        events.append(self._event(conn, session.session_id, "slow_path_queued",
                                                  {"attempt": retry.attempt, "role": retry.role, "recovery": True,
                                                   "recovered_from_run_id": run.run_id}, revision=retry.revision,
                                                  turn_id=retry.turn_id, run_id=retry.run_id, at=now))
                session = self._touch_session(conn, session, now, recovery=report)
                events.append(self._event(conn, session.session_id, "session_recovered", report,
                                          revision=session.current_revision, at=now))
                reports.append(report)
        return reports, to_schedule, events

    def _orphan_effects(self, conn, run: PrismRun, now: datetime, report: dict) -> None:
        for erow in conn.execute("SELECT * FROM prism_effect WHERE run_id=? AND status='PENDING'", (run.run_id,)):
            conn.execute("UPDATE prism_effect SET status='UNKNOWN',updated_at=? WHERE effect_id=? AND status='PENDING'",
                         (now.isoformat(), erow["effect_id"]))
            report["unknown_effects"].append(erow["effect_id"])

    # ---- metrics ---------------------------------------------------------------------
    def fast_path_latencies(self, limit: int = 500) -> list[float]:
        with self._read() as conn:
            rows = conn.execute("SELECT json_extract(fast_path_json,'$.latency_ms') AS ms FROM prism_turn "
                                "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [float(r["ms"]) for r in rows if r["ms"] is not None]
