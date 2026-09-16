"""PRISM repository: atomic revision advance, legal run states, the commit fence transaction,
durable effect identity and real (threaded, multi-connection) SQLite races."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3

import pytest

from core import db
from core.prism import PrismRepository, RunIdentity, RunStatus, SlowPathResult
from core.prism.fast_path import DeterministicFastPath
from core.prism.fencing import StaleRevisionError, decide
from core.prism.models import IllegalRunTransition, PrismRun, PrismSession, validate_run_transition
from core.prism.repository import IdempotencyConflict, InvalidReference, SessionNotFound

FAST = DeterministicFastPath()


@pytest.fixture
def repo(seeded_db):
    return PrismRepository()


def accept(repo, session_id, content, key=None, request_id=None):
    key = key or content
    return repo.accept_turn(session_id, request_id=request_id or key, idempotency_key=key, content=content,
                            content_type="text", metadata={}, fast_path=FAST)


def identity(acceptance) -> RunIdentity:
    run, turn = acceptance.run, acceptance.turn
    return RunIdentity(session_id=run.session_id, turn_id=run.turn_id, revision=run.revision, run_id=run.run_id,
                       attempt=run.attempt, request_id=turn.request_id)


def result(text="done") -> SlowPathResult:
    return SlowPathResult(summary=text, provenance="INJECTED")


def test_run_state_graph_is_explicit_and_terminal_states_are_final():
    validate_run_transition("QUEUED", "RUNNING")
    validate_run_transition("RUNNING", "CANCELLING")
    validate_run_transition("CANCELLING", "STALE")
    for terminal in ("COMPLETED", "FAILED", "CANCELLED", "SUPERSEDED", "STALE"):
        for target in RunStatus:
            with pytest.raises(IllegalRunTransition):
                validate_run_transition(terminal, target)
    with pytest.raises(IllegalRunTransition):
        validate_run_transition("QUEUED", "COMPLETED")   # a result needs a started run
    with pytest.raises(IllegalRunTransition):
        validate_run_transition("CANCELLING", "COMPLETED")  # superseded work can never complete canonically


def test_session_and_turn_identity_are_server_generated_and_revisions_monotonic(repo):
    session, events = repo.create_session()
    assert session.current_revision == 0 and [e.event_type for e in events] == ["session_created"]
    first = accept(repo, session.session_id, "investigate the compressor")
    second = accept(repo, session.session_id, "prioritize the vibration spike")
    assert (first.turn.revision, second.turn.revision) == (1, 2)
    assert first.turn.turn_id != second.turn.turn_id and first.run.run_id != second.run.run_id
    assert repo.get_session(session.session_id).current_revision == 2
    assert [t.revision for t in repo.list_turns(session.session_id)] == [1, 2]
    assert {e.event_type for e in second.events} >= {"turn_accepted", "interruption_received", "revision_superseded",
                                                     "cancellation_requested", "fast_path_acknowledged", "slow_path_queued"}


def test_unknown_session_or_incident_are_refused(repo):
    with pytest.raises(SessionNotFound):
        accept(repo, "missing", "hello there")
    with pytest.raises(InvalidReference):
        repo.create_session(incident_id="no-such-incident")


def test_acceptance_supersedes_active_runs_atomically(repo):
    session, _ = repo.create_session()
    first = accept(repo, session.session_id, "first instruction")
    started, _ = repo.start_run(identity(first))
    assert started.status == RunStatus.RUNNING
    second = accept(repo, session.session_id, "second instruction")
    assert [r.status for r in second.superseded_runs] == [RunStatus.CANCELLING]
    run = repo.get_run(first.run.run_id)
    assert run.status == RunStatus.CANCELLING and run.stale and run.superseded_at is not None
    third = accept(repo, session.session_id, "third instruction")   # second never started -> SUPERSEDED
    assert repo.get_run(second.run.run_id).status == RunStatus.SUPERSEDED
    assert repo.get_run(first.run.run_id).status == RunStatus.CANCELLING   # unchanged; still owed a cancel/stale
    assert third.turn.revision == 3


def test_queued_run_superseded_before_start_cannot_start(repo):
    session, _ = repo.create_session()
    first = accept(repo, session.session_id, "first instruction")
    accept(repo, session.session_id, "second instruction")
    started, events = repo.start_run(identity(first))
    assert started is None and repo.get_run(first.run.run_id).status == RunStatus.SUPERSEDED
    assert events == []   # already recorded as SUPERSEDED by the acceptance transaction


def test_commit_fence_commits_only_the_current_running_revision(repo):
    session, _ = repo.create_session()
    first = accept(repo, session.session_id, "first instruction")
    repo.start_run(identity(first))
    decision, events = repo.commit_result(identity(first), result("one"))
    assert decision.committed and decision.reason == "committed"
    assert [e.event_type for e in events] == ["run_completed", "canonical_state_updated"]
    session = repo.get_session(session.session_id)
    assert session.canonical_revision == 1 and session.canonical["result"]["summary"] == "one"
    # A second completion of the same run is a no-op.
    again, events = repo.commit_result(identity(first), result("one again"))
    assert not again.committed and again.reason == "already_terminal" and events == []
    assert repo.get_session(session.session_id).canonical["result"]["summary"] == "one"


def test_commit_fence_records_stale_results_without_mutating_canonical_state(repo):
    session, _ = repo.create_session()
    first = accept(repo, session.session_id, "first instruction")
    repo.start_run(identity(first))
    second = accept(repo, session.session_id, "second instruction")
    repo.start_run(identity(second))
    decision, events = repo.commit_result(identity(first), result("late result of revision 1"))
    assert not decision.committed and decision.reason == "stale_revision"
    assert decision.run_revision == 1 and decision.current_revision == 2
    assert [e.event_type for e in events] == ["stale_result_discarded"]
    run = repo.get_run(first.run.run_id)
    assert run.status == RunStatus.STALE and run.stale and run.result["summary"] == "late result of revision 1"
    session = repo.get_session(session.session_id)
    assert session.canonical_revision is None and session.canonical is None
    ok, _ = repo.commit_result(identity(second), result("two"))
    assert ok.committed and repo.get_session(session.session_id).canonical_revision == 2


def test_decide_fails_closed_on_any_uncertainty():
    now = datetime.now(timezone.utc)
    session = PrismSession(session_id="s", current_revision=2, created_at=now, updated_at=now)
    run = PrismRun(run_id="r", session_id="s", turn_id="t", revision=2, attempt=1, status=RunStatus.RUNNING,
                   created_at=now, updated_at=now)
    ident = RunIdentity(session_id="s", turn_id="t", revision=2, run_id="r", attempt=1, request_id="q")
    assert decide(session, run, ident).committed
    assert decide(None, run, ident).reason == "session_missing"
    assert decide(session, None, ident).reason == "run_missing"
    assert decide(session, run.model_copy(update={"revision": 1}), ident).reason == "run_missing"  # identity mismatch
    assert decide(session.model_copy(update={"current_revision": 3}), run, ident).reason == "stale_revision"
    assert decide(session, run.model_copy(update={"status": RunStatus.CANCELLING}), ident).reason == "stale_revision"
    assert decide(session, run.model_copy(update={"status": RunStatus.QUEUED}), ident).reason == "run_not_active"
    assert decide(session, run.model_copy(update={"status": RunStatus.COMPLETED}), ident).reason == "already_terminal"
    assert decide(session.model_copy(update={"status": "CLOSED"}), run, ident).reason == "session_closed"
    assert decide(session, run.model_copy(update={"superseded_at": now}), ident).reason == "stale_revision"


def test_terminal_runs_and_events_are_immutable_in_the_database(repo):
    session, _ = repo.create_session()
    first = accept(repo, session.session_id, "first instruction")
    repo.start_run(identity(first))
    repo.commit_result(identity(first), result())
    with db.get_conn(repo.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="terminal prism runs are immutable"):
            conn.execute("UPDATE prism_run SET status='RUNNING' WHERE run_id=?", (first.run.run_id,))
        with pytest.raises(sqlite3.IntegrityError, match="prism events are immutable"):
            conn.execute("UPDATE prism_event SET event_type='forged' WHERE session_id=?", (session.session_id,))
        with pytest.raises(sqlite3.IntegrityError, match="prism turns are immutable"):
            conn.execute("UPDATE prism_turn SET content='forged' WHERE turn_id=?", (first.turn.turn_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE prism_session SET current_revision=0 WHERE session_id=?", (session.session_id,))
            conn.execute("INSERT INTO prism_turn (turn_id,session_id,revision,request_id,idempotency_key,content_type,"
                         "content,content_hash,metadata_json,fast_path_json,created_at) VALUES "
                         "('x',?,1,'r','first instruction','text','c','h','{}','{}','now')", (session.session_id,))


def test_failure_of_a_superseded_run_is_historical_not_canonical(repo):
    session, _ = repo.create_session()
    first = accept(repo, session.session_id, "first instruction")
    repo.start_run(identity(first))
    second = accept(repo, session.session_id, "second instruction")
    failed, events = repo.fail_run(identity(first), {"code": "boom", "message": "worker crashed late"})
    assert failed.status == RunStatus.FAILED and failed.stale and events[0].payload["canonical"] is False
    repo.start_run(identity(second))
    failed2, events = repo.fail_run(identity(second), {"code": "boom", "message": "current worker failed"})
    assert failed2.status == RunStatus.FAILED and not failed2.stale and events[0].payload["canonical"] is True
    assert repo.get_session(session.session_id).current_revision == 2   # failure never moves the revision


def test_effect_ledger_is_fenced_and_completes_exactly_once(repo):
    session, _ = repo.create_session()
    first = accept(repo, session.session_id, "first instruction")
    repo.start_run(identity(first))
    effect, created = repo.begin_effect(identity(first), tool_call_id="tc-1", idempotency_key="tc-1",
                                        kind="simulated_tool", request_hash="h1")
    assert created and effect.status.value == "PENDING"
    same, created_again = repo.begin_effect(identity(first), tool_call_id="tc-1", idempotency_key="tc-1",
                                            kind="simulated_tool", request_hash="h1")
    assert not created_again and same.effect_id == effect.effect_id
    with pytest.raises(IdempotencyConflict):
        repo.begin_effect(identity(first), tool_call_id="tc-1", idempotency_key="tc-1", kind="other", request_hash="h2")
    done, applied = repo.complete_effect(identity(first), effect.effect_id, result={"ok": True})
    assert applied and done.status.value == "COMPLETED"
    dup, applied_again = repo.complete_effect(identity(first), effect.effect_id, result={"ok": False})
    assert not applied_again and dup.result == {"ok": True}
    assert len(repo.list_effects(session.session_id)) == 1
    # After supersession the same run may not start a new effect.
    accept(repo, session.session_id, "second instruction")
    with pytest.raises(StaleRevisionError):
        repo.begin_effect(identity(first), tool_call_id="tc-2", idempotency_key="tc-2", kind="simulated_tool",
                          request_hash="h3")


def test_two_messages_arriving_simultaneously_get_distinct_ordered_revisions(repo):
    session, _ = repo.create_session()
    contents = [f"simultaneous instruction {i}" for i in range(12)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda c: accept(PrismRepository(repo.path), session.session_id, c), contents))
    revisions = sorted(a.turn.revision for a in results)
    assert revisions == list(range(1, 13))
    runs = repo.list_runs(session.session_id)
    active = [r for r in runs if r.status in (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.CANCELLING)]
    assert [r.revision for r in active] == [12] and repo.get_session(session.session_id).current_revision == 12
    assert all(r.status == RunStatus.SUPERSEDED for r in runs if r.revision < 12)


def test_concurrent_duplicate_requests_dedupe_atomically(repo):
    session, _ = repo.create_session()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: accept(PrismRepository(repo.path), session.session_id, "same instruction",
                                                 key="op-key-1", request_id="req-1"), range(16)))
    assert sum(1 for a in results if not a.duplicate) == 1
    assert len({a.turn.turn_id for a in results}) == 1 and len({a.run.run_id for a in results}) == 1
    assert repo.get_session(session.session_id).current_revision == 1
    with pytest.raises(IdempotencyConflict):
        accept(repo, session.session_id, "different content", key="op-key-1")


def test_stale_commit_racing_new_revision_never_wins(repo):
    """Repeatedly race a revision-N commit against acceptance of N+1 from separate connections."""
    stale_commits, canonical_commits = 0, 0
    for i in range(40):
        session, _ = repo.create_session()
        first = accept(repo, session.session_id, f"instruction {i}")
        repo.start_run(identity(first))
        ident = identity(first)
        with ThreadPoolExecutor(max_workers=2) as pool:
            commit = pool.submit(lambda: PrismRepository(repo.path).commit_result(ident, result(f"result {i}")))
            newer = pool.submit(lambda: accept(PrismRepository(repo.path), session.session_id, f"correction {i}"))
            decision, _ = commit.result()
            newer.result()
        final = repo.get_session(session.session_id)
        assert final.current_revision == 2
        run = repo.get_run(first.run.run_id)
        if decision.committed:
            canonical_commits += 1
            # Committed strictly before N+1 was accepted: canonical revision 1 is historical truth,
            # and the newer acceptance found no active run to supersede.
            assert run.status == RunStatus.COMPLETED and final.canonical_revision == 1
        else:
            stale_commits += 1
            assert run.status == RunStatus.STALE and final.canonical_revision is None
        # In no case may revision 1's result be canonical while revision 1 is superseded-in-flight.
        assert not (run.stale and final.canonical_revision == 1)
    assert stale_commits + canonical_commits == 40
