"""The authoritative commit fence: the ONE place that decides whether a result may
mutate canonical PRISM state.

    result arrives
      -> authoritative session/revision lookup (inside BEGIN IMMEDIATE)
      -> ``decide`` verifies session/run/revision eligibility
      -> atomic canonical commit (CAS on current_revision and run status)
         OR stale/discard record

``decide`` is a pure function of the durable session and run rows. The repository
calls it *inside* the write transaction so the check and the mutation cannot be
separated by a newer revision (no TOCTOU window). The runtime never touches the
repository's commit primitives directly: ``CommitFence``/``RunFence`` are its only
handle, and they carry the run identity the result claims to belong to.

Cancellation is an optimization. This fence is the correctness mechanism. When
anything about the lookup is uncertain the decision is "not committed".
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import ACTIVE_RUN_STATUSES, CommitDecision, PrismEffect, PrismRun, PrismSession, RunIdentity, RunStatus, SlowPathResult

if TYPE_CHECKING:  # pragma: no cover
    from .repository import PrismRepository


class StaleRevisionError(RuntimeError):
    """Raised to a worker that tries to start an external effect for a superseded revision."""

    def __init__(self, decision: CommitDecision):
        super().__init__(f"revision {decision.run_revision} of session {decision.session_id} is not canonical "
                         f"(current {decision.current_revision}); {decision.reason}")
        self.decision = decision


def decide(session: PrismSession | None, run: PrismRun | None, identity: RunIdentity | None = None) -> CommitDecision:
    """Eligibility of ``run`` to mutate the canonical state of ``session``. Pure; fails closed."""
    if session is None:
        return CommitDecision(committed=False, reason="session_missing",
                              session_id=identity.session_id if identity else "?",
                              run_id=identity.run_id if identity else "?")
    if run is None:
        return CommitDecision(committed=False, reason="run_missing", session_id=session.session_id,
                              run_id=identity.run_id if identity else "?", current_revision=session.current_revision)
    base = dict(session_id=session.session_id, run_id=run.run_id, run_revision=run.revision,
                current_revision=session.current_revision, run_status=run.status)
    if identity is not None and (identity.session_id, identity.run_id, identity.revision) != (
            run.session_id, run.run_id, run.revision):
        # The result claims an identity the durable record contradicts: never trust it.
        return CommitDecision(committed=False, reason="run_missing", **base)
    if run.session_id != session.session_id:
        return CommitDecision(committed=False, reason="run_missing", **base)
    if session.status != "ACTIVE":
        return CommitDecision(committed=False, reason="session_closed", **base)
    if run.status not in ACTIVE_RUN_STATUSES:
        return CommitDecision(committed=False, reason="already_terminal", **base)
    if run.revision != session.current_revision or run.superseded_at is not None or run.status == RunStatus.CANCELLING:
        return CommitDecision(committed=False, reason="stale_revision", **base)
    if run.status != RunStatus.RUNNING:
        return CommitDecision(committed=False, reason="run_not_active", **base)
    return CommitDecision(committed=True, reason="committed", **base)


class CommitFence:
    """Runtime-facing authority. Every Slow Path result and effect passes through here."""

    def __init__(self, repository: "PrismRepository"):
        self._repository = repository

    def for_run(self, identity: RunIdentity) -> "RunFence":
        return RunFence(self, identity)

    def commit(self, identity: RunIdentity, result: SlowPathResult, *, runtime: dict | None = None):
        """Atomic canonical commit or stale/discard record. Returns (decision, events)."""
        return self._repository.commit_result(identity, result, runtime=runtime)

    def check(self, identity: RunIdentity) -> CommitDecision:
        """Advisory, non-mutating eligibility (for cooperative workers). Never a substitute for commit."""
        return self._repository.check_eligibility(identity)

    def begin_effect(self, identity: RunIdentity, *, tool_call_id: str, idempotency_key: str, kind: str,
                     request_hash: str) -> tuple[PrismEffect, bool]:
        """Durable effect identity, allowed only while the run's revision is canonical."""
        return self._repository.begin_effect(identity, tool_call_id=tool_call_id, idempotency_key=idempotency_key,
                                             kind=kind, request_hash=request_hash)

    def complete_effect(self, identity: RunIdentity, effect_id: str, *, status: str = "COMPLETED",
                        result: dict | None = None) -> tuple[PrismEffect, bool]:
        return self._repository.complete_effect(identity, effect_id, status=status, result=result)


class RunFence:
    """``CommitFence`` bound to one run identity; the handle an execution receives."""

    def __init__(self, fence: CommitFence, identity: RunIdentity):
        self.fence, self.identity = fence, identity

    def commit(self, result: SlowPathResult, *, runtime: dict | None = None):
        return self.fence.commit(self.identity, result, runtime=runtime)

    def check(self) -> CommitDecision:
        return self.fence.check(self.identity)

    def begin_effect(self, **kwargs) -> tuple[PrismEffect, bool]:
        return self.fence.begin_effect(self.identity, **kwargs)

    def complete_effect(self, effect_id: str, **kwargs) -> tuple[PrismEffect, bool]:
        return self.fence.complete_effect(self.identity, effect_id, **kwargs)
