"""PRISM runtime identity model: sessions, turns, revisions, runs, effects, events.

Every record carries the identities the Stage 1 spec requires (session_id, turn_id,
revision, run_id, request_id, tool_call_id, idempotency_key and the lifecycle
timestamps). IDs are server-generated UUID4s; revisions advance only inside the
repository transaction that accepts a turn. Nothing here holds a provider secret.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

JsonDict = dict[str, Any]
CONTENT_TYPES: tuple[str, ...] = ("text", "voice_transcript", "image_reference")
ContentType = Literal["text", "voice_transcript", "image_reference"]
ROLE_SLOW = "slow"
ROLE_FAST = "fast"
MAX_CONTENT_CHARS = 8000
MAX_METADATA_KEYS = 16
MAX_METADATA_BYTES = 4096


class RunStatus(str, Enum):
    """Legal Slow Path run states. Transitions are validated by ``validate_run_transition``."""
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"   # superseded before it ever started
    STALE = "STALE"             # produced a result after supersession; result kept as history only


TERMINAL_RUN_STATUSES = frozenset({RunStatus.CANCELLED, RunStatus.COMPLETED, RunStatus.FAILED,
                                   RunStatus.SUPERSEDED, RunStatus.STALE})
ACTIVE_RUN_STATUSES = frozenset({RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLING})
RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.SUPERSEDED, RunStatus.CANCELLED, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLING,
                                  RunStatus.CANCELLED, RunStatus.STALE}),
    RunStatus.CANCELLING: frozenset({RunStatus.CANCELLED, RunStatus.STALE, RunStatus.FAILED}),
    RunStatus.CANCELLED: frozenset(), RunStatus.COMPLETED: frozenset(), RunStatus.FAILED: frozenset(),
    RunStatus.SUPERSEDED: frozenset(), RunStatus.STALE: frozenset(),
}


class IllegalRunTransition(ValueError):
    pass


def validate_run_transition(current: RunStatus, target: RunStatus) -> None:
    current, target = RunStatus(current), RunStatus(target)
    if target not in RUN_TRANSITIONS[current]:
        raise IllegalRunTransition(f"run status {current.value} cannot become {target.value}")


class EffectStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrismSession(_Record):
    session_id: str
    incident_id: str | None = None
    status: Literal["ACTIVE", "CLOSED"] = "ACTIVE"
    current_revision: int = Field(ge=0)
    current_turn_id: str | None = None
    canonical_revision: int | None = None
    canonical_run_id: str | None = None
    canonical: JsonDict | None = None
    recovery: JsonDict | None = None
    metadata: JsonDict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class FastPathState(_Record):
    """Immediate deterministic acknowledgement persisted with the turn it answers."""
    status: Literal["accepted", "accepted_superseding", "clarification_required"]
    message: str
    revision: int = Field(ge=1)
    superseded_revision: int | None = None
    deeper_reasoning: Literal["scheduled", "not_scheduled"]
    role: str = ROLE_FAST
    runtime: JsonDict = Field(default_factory=dict)
    acknowledged_at: datetime
    latency_ms: float | None = None


class PrismTurn(_Record):
    turn_id: str
    session_id: str
    revision: int = Field(ge=1)
    request_id: str
    idempotency_key: str
    content_type: ContentType
    content: str
    content_hash: str
    metadata: JsonDict = Field(default_factory=dict)
    fast_path: FastPathState
    created_at: datetime


class PrismRun(_Record):
    run_id: str
    session_id: str
    turn_id: str
    revision: int = Field(ge=1)
    attempt: int = Field(ge=1)
    role: str = ROLE_SLOW
    status: RunStatus
    stale: bool = False
    runtime: JsonDict | None = None
    result: JsonDict | None = None
    error: JsonDict | None = None
    cancellation_reason: str | None = None
    recovered_from_run_id: str | None = None
    deadline_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    superseded_at: datetime | None = None
    cancelled_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_RUN_STATUSES


class PrismEffect(_Record):
    effect_id: str
    session_id: str
    revision: int = Field(ge=1)
    run_id: str
    tool_call_id: str
    idempotency_key: str
    kind: str
    request_hash: str
    status: EffectStatus
    result: JsonDict | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class PrismEvent(_Record):
    event_id: int
    session_id: str
    revision: int | None = None
    turn_id: str | None = None
    run_id: str | None = None
    event_type: str
    payload: JsonDict = Field(default_factory=dict)
    created_at: datetime


class RunIdentity(_Record):
    """What every Slow Path execution knows about itself; also the commit-fence key."""
    session_id: str
    turn_id: str
    revision: int = Field(ge=1)
    run_id: str
    attempt: int = Field(ge=1)
    request_id: str
    role: str = ROLE_SLOW


class SlowPathResult(BaseModel):
    """The advisory output of one Slow Path run. Committed only through the fence."""
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=4000)
    findings: list[str] = Field(default_factory=list, max_length=32)
    proposed_actions: list[JsonDict] = Field(default_factory=list, max_length=16)
    provenance: Literal["DETERMINISTIC", "LIVE", "INJECTED", "SIMULATED", "APPLICATION"] = "DETERMINISTIC"
    runtime: JsonDict = Field(default_factory=dict)
    details: JsonDict = Field(default_factory=dict)


class CommitDecision(_Record):
    """Outcome of the authoritative commit fence for one result."""
    committed: bool
    reason: Literal["committed", "stale_revision", "run_not_active", "already_terminal", "session_missing",
                    "run_missing", "session_closed"]
    session_id: str
    run_id: str
    run_revision: int | None = None
    current_revision: int | None = None
    run_status: RunStatus | None = None


class Acceptance(_Record):
    """Prompt response to an operator message; never waits for the Slow Path."""
    session: PrismSession
    turn: PrismTurn
    run: PrismRun | None
    superseded_runs: tuple[PrismRun, ...] = ()
    duplicate: bool = False
    events: tuple[PrismEvent, ...] = ()
