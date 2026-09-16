"""Fast Path: the immediate, deterministic acknowledgement contract.

Stage 1 implements the *contract*, not Fast Path intelligence: accepted /
accepted_superseding / clarification_required, the current context and whether
deeper (Slow Path) reasoning was scheduled. It is a pure function evaluated inside
the acceptance transaction, so it can never wait on a model, a tool or the Slow
Path. It carries ``role="fast"`` so a later stage can bind a provider through
``registry.build(role="fast")``; nothing here imports a provider.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import FastPathState, PrismSession, ROLE_FAST

FAST_PATH_IDENTITY = {"role": ROLE_FAST, "implementation": "operon.prism.fast-path.deterministic-v1",
                      "provenance": "DETERMINISTIC", "provider": "none", "live_model": False}
MIN_WORDS_FOR_REASONING = 2


class DeterministicFastPath:
    """Deterministic acknowledgement over the accepted turn and the session's current state."""

    identity = FAST_PATH_IDENTITY

    def __call__(self, turn: dict, session: PrismSession, superseded_revision: int | None,
                 schedule_slow_path: bool) -> FastPathState:
        content = str(turn.get("content", "")).strip()
        revision = int(turn["revision"])
        words = [w for w in content.split() if w.strip("?.!,;:")]
        now = datetime.now(timezone.utc)
        context = {"incident_id": session.incident_id, "canonical_revision": session.canonical_revision,
                   "content_type": turn.get("content_type", "text")}
        if len(words) < MIN_WORDS_FOR_REASONING:
            return FastPathState(
                status="clarification_required", revision=revision, superseded_revision=superseded_revision,
                deeper_reasoning="not_scheduled", runtime={**FAST_PATH_IDENTITY, "context": context},
                acknowledged_at=now,
                message="Acknowledged. Please add what you want investigated or changed; no deeper reasoning was started.")
        if superseded_revision is not None:
            message = (f"Acknowledged as revision {revision}; revision {superseded_revision} is superseded and its "
                       f"reasoning is being cancelled. Deeper reasoning for the new instruction is "
                       f"{'running' if schedule_slow_path else 'not scheduled'}.")
            status = "accepted_superseding"
        else:
            message = (f"Acknowledged as revision {revision}. Deeper reasoning is "
                       f"{'running' if schedule_slow_path else 'not scheduled'}.")
            status = "accepted"
        return FastPathState(status=status, revision=revision, superseded_revision=superseded_revision,
                             deeper_reasoning="scheduled" if schedule_slow_path else "not_scheduled",
                             runtime={**FAST_PATH_IDENTITY, "context": context}, acknowledged_at=now, message=message)
