"""Restart reconstruction: canonical revision restored, superseded work never revived, explicit policy."""
from __future__ import annotations

import asyncio

import pytest

from core import db
from core.prism import PrismRepository, PrismRuntime, RunStatus
from core.prism.testing import ControlledAdapter


@pytest.fixture
def repo(seeded_db):
    return PrismRepository()


def simulate_crash(repo, session_id):
    """Leave the rows exactly as a killed process would: RUNNING/CANCELLING/QUEUED/PENDING stay put."""
    with db.get_conn(repo.path) as conn:
        return conn.execute("SELECT run_id,revision,status FROM prism_run WHERE session_id=? ORDER BY revision,attempt",
                            (session_id,)).fetchall()


async def crashed_session(repo, *, with_effect=False):
    adapter = ControlledAdapter(ignore_cancellation=True,
                                **({"effect": {"ticket": "T-1"}, "effect_key": "ticket-1"} if with_effect else {}))
    rt = PrismRuntime(repo, adapter=adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    while repo.get_run(one["slow_path"]["run_id"]).status != RunStatus.RUNNING:
        await asyncio.sleep(0.005)
    two = await rt.submit_message(sid, content="second instruction here")
    while repo.get_run(two["slow_path"]["run_id"]).status != RunStatus.RUNNING:
        await asyncio.sleep(0.005)
    if with_effect:
        # Revision 2 performs (and durably records) its tool effect, then the process dies before the commit.
        async def perform():
            return {"ok": True, "ticket": "T-1"}
        await adapter.started[1].effect(tool_call_id="ticket-1", kind="simulated_tool", payload={"ticket": "T-1"},
                                        perform=perform, idempotency_key="ticket-1")
    # Abandon the runtime without shutdown: tasks are dropped like a killed process.
    for handle in rt.coordinator.handles.values():
        handle.task.cancel()
    await asyncio.sleep(0)
    # The non-cooperative adapter swallowed the cancel and keeps the rows RUNNING/CANCELLING; drop the tasks now.
    for handle in rt.coordinator.handles.values():
        handle.task.cancel()
    await asyncio.sleep(0.01)
    return sid, one, two


async def test_restart_restores_canonical_revision_and_retries_only_the_current_run(repo):
    sid, one, two = await crashed_session(repo)
    rows = simulate_crash(repo, sid)
    assert [(r["revision"], r["status"]) for r in rows] == [(1, "CANCELLING"), (2, "RUNNING")]
    adapter = ControlledAdapter(auto_release=True)
    rebuilt = PrismRuntime(PrismRepository(repo.path), adapter=adapter)
    reports = await rebuilt.recover()
    assert len(reports) == 1 and reports[0]["policy"] == "retry_current_revision"
    assert reports[0]["superseded_runs"] == [one["slow_path"]["run_id"]]
    assert reports[0]["failed_runs"] == [two["slow_path"]["run_id"]]
    assert reports[0]["retried"]["from_run_id"] == two["slow_path"]["run_id"]
    assert await rebuilt.wait_idle(5)
    runs = repo.list_runs(sid)
    assert [(r.revision, r.attempt, r.status) for r in runs] == [
        (1, 1, RunStatus.CANCELLED), (2, 1, RunStatus.FAILED), (2, 2, RunStatus.COMPLETED)]
    assert runs[2].recovered_from_run_id == two["slow_path"]["run_id"]
    session = repo.get_session(sid)
    assert session.current_revision == 2 and session.canonical_revision == 2 and session.canonical["attempt"] == 2
    assert [e.revision for e in adapter.started] == [2]       # revision 1 was never revived
    view = rebuilt.session_view(sid)
    assert view["recovery"]["retried"]["attempt"] == 2 and "retried as attempt 2" in view["recovery"]["description"]
    assert "session_recovered" in [e.event_type for e in repo.list_events(sid)]


async def test_fail_only_policy_never_schedules_work(repo):
    sid, one, two = await crashed_session(repo)
    rebuilt = PrismRuntime(PrismRepository(repo.path), adapter=ControlledAdapter(auto_release=True),
                           recovery_policy="fail_only")
    reports = await rebuilt.recover()
    assert reports[0]["retried"] is None and rebuilt.coordinator.handles == {}
    assert [(r.revision, r.status) for r in repo.list_runs(sid)] == [(1, RunStatus.CANCELLED), (2, RunStatus.FAILED)]
    assert repo.get_session(sid).canonical_revision is None


async def test_superseded_revision_is_never_revived_even_when_current_already_canonical(repo):
    adapter = ControlledAdapter(ignore_cancellation=True)
    rt = PrismRuntime(repo, adapter=adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    while repo.get_run(one["slow_path"]["run_id"]).status != RunStatus.RUNNING:
        await asyncio.sleep(0.005)
    rt.coordinator.adapter = ControlledAdapter(auto_release=True)
    two = await rt.submit_message(sid, content="second instruction here")
    while repo.get_run(two["slow_path"]["run_id"]).status != RunStatus.COMPLETED:
        await asyncio.sleep(0.005)
    for handle in rt.coordinator.handles.values():
        handle.task.cancel()
    await asyncio.sleep(0.01)
    assert repo.get_run(one["slow_path"]["run_id"]).status == RunStatus.CANCELLING
    rebuilt = PrismRuntime(PrismRepository(repo.path), adapter=ControlledAdapter(auto_release=True))
    reports = await rebuilt.recover()
    assert reports[0]["retried"] is None and reports[0]["superseded_runs"] == [one["slow_path"]["run_id"]]
    assert repo.get_run(one["slow_path"]["run_id"]).status == RunStatus.CANCELLED
    assert repo.get_session(sid).canonical_revision == 2


async def test_committed_effects_are_not_repeated_and_pending_ones_become_unknown(repo):
    sid, one, two = await crashed_session(repo, with_effect=True)
    # Revision 2's effect was performed and recorded; then the process died before the result commit.
    effects = repo.list_effects(sid)
    assert [(e.revision, e.status.value) for e in effects] == [(2, "COMPLETED")]
    # A pending effect left by the crash (simulated) must become UNKNOWN, never replayed.
    with db.get_conn(repo.path) as conn:
        conn.execute("INSERT INTO prism_effect (effect_id,session_id,revision,run_id,tool_call_id,idempotency_key,kind,"
                     "request_hash,status,result_json,created_at,updated_at,completed_at) VALUES "
                     "('pending-1',?,2,?,'tc-p','tc-p','simulated_tool','h','PENDING',NULL,?,?,NULL)",
                     (sid, two["slow_path"]["run_id"], "2026-09-16T00:00:00+00:00", "2026-09-16T00:00:00+00:00"))
    adapter = ControlledAdapter(auto_release=True, effect={"ticket": "T-1"}, effect_key="ticket-1")
    rebuilt = PrismRuntime(PrismRepository(repo.path), adapter=adapter)
    reports = await rebuilt.recover()
    assert reports[0]["unknown_effects"] == ["pending-1"]
    assert await rebuilt.wait_idle(5)
    effects = {e.effect_id: e for e in repo.list_effects(sid)}
    assert effects["pending-1"].status.value == "UNKNOWN"
    assert sum(1 for e in effects.values() if e.status.value == "COMPLETED") == 1
    assert adapter.performed_effects == []            # retry attempt found the committed effect in the ledger
    assert repo.get_session(sid).canonical_revision == 2


async def test_queued_run_at_current_revision_is_rescheduled_not_retried(repo):
    rt = PrismRuntime(repo, adapter=ControlledAdapter())
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here", schedule_slow_path=True)
    # Kill before the task ever started (QUEUED row).
    for handle in rt.coordinator.handles.values():
        handle.task.cancel()
    await asyncio.sleep(0.01)
    with db.get_conn(repo.path) as conn:
        status = conn.execute("SELECT status FROM prism_run WHERE run_id=?", (one["slow_path"]["run_id"],)).fetchone()[0]
    if status != "QUEUED":
        pytest.skip("task started before it could be dropped; covered by the retry test")
    rebuilt = PrismRuntime(PrismRepository(repo.path), adapter=ControlledAdapter(auto_release=True))
    reports = await rebuilt.recover()
    assert reports[0]["scheduled"] == [one["slow_path"]["run_id"]] and reports[0]["retried"] is None
    assert await rebuilt.wait_idle(5)
    assert repo.get_run(one["slow_path"]["run_id"]).status == RunStatus.COMPLETED


async def test_recovery_without_incomplete_work_is_a_no_op(repo):
    rt = PrismRuntime(repo, adapter=ControlledAdapter(auto_release=True))
    sid = (await rt.create_session())["session_id"]
    await rt.submit_message(sid, content="first instruction here")
    assert await rt.wait_idle(5)
    rebuilt = PrismRuntime(PrismRepository(repo.path), adapter=ControlledAdapter(auto_release=True))
    assert await rebuilt.recover() == []
    assert rebuilt.session_view(sid)["recovery"] is None and rebuilt.recovered == []
