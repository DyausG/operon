"""PRISM runtime invariants with deterministic adapters (no model, no network).

Central invariant: once revision N is superseded by N+1, no result produced for N
may mutate canonical state, whatever the worker does.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from core.prism import PrismRepository, PrismRuntime, RunStatus
from core.prism.slow_path import DeterministicSlowPathAdapter
from core.prism.testing import ControlledAdapter


@pytest.fixture
def repo(seeded_db):
    return PrismRepository()


def runtime_with(repo, adapter, **kwargs):
    events = []
    rt = PrismRuntime(repo, adapter=adapter, **kwargs)
    rt.publisher.subscribe(events.append)
    rt.events = events
    return rt


async def wait_status(repo, run_id, status, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = repo.get_run(run_id)
        if run.status == status:
            return run
        await asyncio.sleep(0.005)
    raise AssertionError(f"run {run_id} is {repo.get_run(run_id).status}, expected {status}")


def types(events, session_id=None):
    return [e["event"]["event_type"] for e in events if session_id is None or e["event"]["session_id"] == session_id]


async def test_stale_completion_cannot_mutate_canonical_state(repo):
    adapter = ControlledAdapter()
    rt = runtime_with(repo, adapter)
    session = await rt.create_session()
    sid = session["session_id"]
    one = await rt.submit_message(sid, content="Investigate the compressor temperature anomaly.")
    await wait_status(repo, one["slow_path"]["run_id"], RunStatus.RUNNING)
    two = await rt.submit_message(sid, content="Correction: prioritize the vibration spike.")
    assert two["fast_path"]["status"] == "accepted_superseding" and two["revision"] == 2
    assert two["superseded"] == {"revision": 1, "run_ids": [one["slow_path"]["run_id"]]}
    adapter.release.set()
    assert await rt.wait_idle(5)
    first, second = repo.get_run(one["slow_path"]["run_id"]), repo.get_run(two["slow_path"]["run_id"])
    assert first.status == RunStatus.CANCELLED and first.stale and first.result is None
    assert second.status == RunStatus.COMPLETED
    state = repo.get_session(sid)
    assert state.current_revision == 2 and state.canonical_revision == 2 and state.canonical_run_id == second.run_id
    assert "result of revision 1" not in state.canonical["result"]["summary"]
    assert "stale_result_discarded" not in types(rt.events) and "run_cancelled" in types(rt.events)


async def test_non_cooperative_worker_result_is_fenced_as_stale(repo):
    adapter = ControlledAdapter(ignore_cancellation=True)
    rt = runtime_with(repo, adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="Investigate the compressor temperature anomaly.")
    await wait_status(repo, one["slow_path"]["run_id"], RunStatus.RUNNING)
    two = await rt.submit_message(sid, content="Correction: prioritize the vibration spike.")
    assert repo.get_run(one["slow_path"]["run_id"]).status == RunStatus.CANCELLING
    # Let revision 2 finish first, then the ignored-cancel revision 1 result arrives late.
    adapter.release.set()
    assert await rt.wait_idle(5)
    first, second = repo.get_run(one["slow_path"]["run_id"]), repo.get_run(two["slow_path"]["run_id"])
    assert first.status == RunStatus.STALE and first.result["summary"].startswith("result of revision 1")
    assert second.status == RunStatus.COMPLETED
    state = repo.get_session(sid)
    assert state.canonical_revision == 2 and state.canonical["run_id"] == second.run_id
    assert "stale_result_discarded" in types(rt.events)
    view = rt.session_view(sid)
    assert view["stale_results"] == 1 and view["stale_run_ids"] == [first.run_id]
    assert view["runtime_state"] == "completed" and view["canonical_current"]


async def test_late_result_after_revision_two_completed_still_cannot_overwrite(repo):
    adapter = ControlledAdapter(ignore_cancellation=True)
    rt = runtime_with(repo, adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    await wait_status(repo, one["slow_path"]["run_id"], RunStatus.RUNNING)
    # Revision 2 uses a separate, auto-releasing adapter instance so it completes immediately.
    rt.coordinator.adapter = ControlledAdapter(auto_release=True)
    two = await rt.submit_message(sid, content="second instruction here")
    await wait_status(repo, two["slow_path"]["run_id"], RunStatus.COMPLETED)
    canonical_before = repo.get_session(sid).canonical
    adapter.release.set()
    assert await rt.wait_idle(5)
    assert repo.get_run(one["slow_path"]["run_id"]).status == RunStatus.STALE
    assert repo.get_session(sid).canonical == canonical_before


@pytest.mark.parametrize("ignore_cancellation", [False, True])
async def test_completion_supersession_race_repeated(repo, ignore_cancellation):
    """Release revision N and accept N+1 in the same loop step, many times. No stale commit may win."""
    for i in range(25):
        adapter = ControlledAdapter(ignore_cancellation=ignore_cancellation)
        rt = runtime_with(repo, adapter)
        sid = (await rt.create_session())["session_id"]
        one = await rt.submit_message(sid, content=f"instruction {i} one")
        await wait_status(repo, one["slow_path"]["run_id"], RunStatus.RUNNING)
        adapter.release.set()                      # worker wakes up on the next loop step
        two = await rt.submit_message(sid, content=f"instruction {i} two")   # accepted now, in this step
        assert await rt.wait_idle(5)
        first, second = repo.get_run(one["slow_path"]["run_id"]), repo.get_run(two["slow_path"]["run_id"])
        state = repo.get_session(sid)
        assert state.current_revision == 2 and second.status == RunStatus.COMPLETED
        assert state.canonical_revision == 2 and state.canonical["run_id"] == second.run_id
        assert first.status in (RunStatus.STALE, RunStatus.CANCELLED) and first.stale


async def test_cancellation_racing_completion_ends_in_one_terminal_state(repo):
    for _ in range(15):
        adapter = ControlledAdapter()
        rt = runtime_with(repo, adapter)
        sid = (await rt.create_session())["session_id"]
        one = await rt.submit_message(sid, content="first instruction here")
        await wait_status(repo, one["slow_path"]["run_id"], RunStatus.RUNNING)
        adapter.release.set()
        await rt.submit_message(sid, content="second instruction here")
        assert await rt.wait_idle(5)
        run = repo.get_run(one["slow_path"]["run_id"])
        assert run.status in (RunStatus.CANCELLED, RunStatus.STALE)
        assert repo.get_session(sid).canonical_revision == 2


async def test_duplicate_completion_commits_once(repo):
    adapter = ControlledAdapter(duplicate_completion=True, auto_release=True)
    rt = runtime_with(repo, adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    assert await rt.wait_idle(5)
    run = repo.get_run(one["slow_path"]["run_id"])
    assert run.status == RunStatus.COMPLETED
    assert types(rt.events).count("canonical_state_updated") == 1
    assert rt.coordinator.completed == 1 and rt.coordinator.stale == 0   # the runtime's second commit was a no-op


async def test_slow_path_failure_is_recorded_without_corrupting_state_and_newer_revisions_proceed(repo):
    adapter = ControlledAdapter(fail_with="model exploded", auto_release=True)
    rt = runtime_with(repo, adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    assert await rt.wait_idle(5)
    run = repo.get_run(one["slow_path"]["run_id"])
    assert run.status == RunStatus.FAILED and run.error["message"] == "model exploded" and not run.stale
    view = rt.session_view(sid)
    assert view["runtime_state"] == "failed" and view["last_failure"]["run_id"] == run.run_id
    rt.coordinator.adapter = ControlledAdapter(auto_release=True)
    two = await rt.submit_message(sid, content="second instruction here")
    assert await rt.wait_idle(5)
    assert repo.get_run(two["slow_path"]["run_id"]).status == RunStatus.COMPLETED
    view = rt.session_view(sid)
    assert view["canonical_revision"] == 2 and view["last_failure"] is None


async def test_stale_run_failing_after_supersession_is_not_the_current_failure(repo):
    adapter = ControlledAdapter(fail_with="late crash", ignore_cancellation=True)
    rt = runtime_with(repo, adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    await wait_status(repo, one["slow_path"]["run_id"], RunStatus.RUNNING)
    rt.coordinator.adapter = ControlledAdapter(auto_release=True)
    two = await rt.submit_message(sid, content="second instruction here")
    adapter.release.set()
    assert await rt.wait_idle(5)
    first = repo.get_run(one["slow_path"]["run_id"])
    assert first.status == RunStatus.FAILED and first.stale
    view = rt.session_view(sid)
    assert view["last_failure"] is None and view["canonical_revision"] == 2
    assert repo.get_run(two["slow_path"]["run_id"]).status == RunStatus.COMPLETED


async def test_effect_refused_once_revision_superseded_and_never_duplicated(repo):
    adapter = ControlledAdapter(effect={"work_order": "WO-1"}, effect_key="wo-1")
    rt = runtime_with(repo, adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    await wait_status(repo, one["slow_path"]["run_id"], RunStatus.RUNNING)
    await rt.submit_message(sid, content="second instruction here")
    adapter.release.set()
    assert await rt.wait_idle(5)
    first = repo.get_run(one["slow_path"]["run_id"])
    assert first.status == RunStatus.CANCELLED
    assert repo.list_effects(sid) == [] or all(e.revision != 1 or e.status.value != "COMPLETED" for e in repo.list_effects(sid))
    # Revision 2 performed its own effect exactly once.
    effects = [e for e in repo.list_effects(sid) if e.revision == 2]
    assert len(effects) == 1 and effects[0].status.value == "COMPLETED"
    assert len(adapter.performed_effects) == 1 and adapter.performed_effects[0]["revision"] == 2


async def test_non_cooperative_effect_after_supersession_is_refused_by_the_fence(repo):
    adapter = ControlledAdapter(ignore_cancellation=True, effect={"work_order": "WO-2"}, effect_key="wo-2")
    rt = runtime_with(repo, adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    await wait_status(repo, one["slow_path"]["run_id"], RunStatus.RUNNING)
    rt.coordinator.adapter = ControlledAdapter(auto_release=True)
    await rt.submit_message(sid, content="second instruction here")
    adapter.release.set()
    assert await rt.wait_idle(5)
    first = repo.get_run(one["slow_path"]["run_id"])
    assert first.status == RunStatus.CANCELLED and first.stale
    assert adapter.performed_effects == []      # the tool never ran for the superseded revision
    assert [e for e in repo.list_effects(sid) if e.revision == 1] == []
    refused = [e for e in repo.list_events(sid) if e.event_type == "effect_refused"]
    assert len(refused) == 1 and refused[0].run_id == first.run_id and refused[0].payload["reason"] == "stale_revision"


async def test_fast_path_never_waits_for_a_blocked_slow_path_and_loop_stays_responsive(repo):
    adapter = ControlledAdapter()   # blocks until released; never released in this test
    rt = runtime_with(repo, adapter)
    sid = (await rt.create_session())["session_id"]
    latencies = []
    for i in range(5):
        started = time.perf_counter()
        ack = await rt.submit_message(sid, content=f"instruction number {i} while slow path blocks")
        latencies.append((time.perf_counter() - started) * 1000)
        assert ack["fast_path"]["status"] in ("accepted", "accepted_superseding")
        assert ack["fast_path"]["latency_ms"] is not None and ack["acceptance_ms"] < 250
    # A trivially short await on the same loop completes promptly while the worker is blocked.
    started = time.perf_counter()
    await asyncio.sleep(0)
    assert (time.perf_counter() - started) * 1000 < 50
    assert max(latencies) < 250, latencies
    metrics = rt.metrics()
    assert metrics["fast_path_acknowledgement"]["count"] == 5 and metrics["fast_path_acknowledgement"]["max_ms"] < 250
    await rt.shutdown()


async def test_deterministic_adapter_delay_does_not_block_acceptance(repo):
    rt = runtime_with(repo, DeterministicSlowPathAdapter(delay_seconds=0.3, cooperative=False))
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="Investigate the compressor temperature anomaly.")
    await asyncio.sleep(0.05)
    started = time.perf_counter()
    two = await rt.submit_message(sid, content="Correction: prioritize the vibration spike and ignore temperature.")
    assert (time.perf_counter() - started) < 0.2
    assert await rt.wait_idle(5)
    assert repo.get_run(one["slow_path"]["run_id"]).status == RunStatus.STALE
    assert repo.get_run(two["slow_path"]["run_id"]).status == RunStatus.COMPLETED
    assert repo.get_session(sid).canonical["result"]["provenance"] == "DETERMINISTIC"


async def test_clarification_required_creates_a_revision_but_no_slow_path(repo):
    rt = runtime_with(repo, ControlledAdapter(auto_release=True))
    sid = (await rt.create_session())["session_id"]
    ack = await rt.submit_message(sid, content="why?")
    assert ack["fast_path"]["status"] == "clarification_required" and ack["slow_path"] is None
    assert ack["revision"] == 1 and repo.list_runs(sid) == []


async def test_deadline_fails_the_run_without_moving_the_revision(repo):
    rt = runtime_with(repo, ControlledAdapter(), deadline_seconds=0.1)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    assert await rt.wait_idle(5)
    run = repo.get_run(one["slow_path"]["run_id"])
    assert run.status == RunStatus.FAILED and run.error["code"] == "deadline_exceeded"
    assert repo.get_session(sid).current_revision == 1


async def test_events_carry_identity_and_are_versioned(repo):
    rt = runtime_with(repo, ControlledAdapter(auto_release=True))
    sid = (await rt.create_session())["session_id"]
    ack = await rt.submit_message(sid, content="first instruction here", request_id="req-1")
    assert await rt.wait_idle(5)
    for message in rt.events:
        assert message["type"] == "prism" and message["prism_version"] == 1
        assert message["event"]["session_id"] == sid and "created_at" in message["event"]
    accepted = next(m for m in rt.events if m["event"]["event_type"] == "turn_accepted")
    assert accepted["event"]["revision"] == 1 and accepted["event"]["turn_id"] == ack["turn_id"]
    assert accepted["event"]["payload"]["request_id"] == "req-1" and "content" not in accepted["event"]["payload"]
    assert types(rt.events)[-2:] == ["run_completed", "canonical_state_updated"]
    durable = [e.event_type for e in repo.list_events(sid)]
    assert durable == types(rt.events)


async def test_shutdown_cancels_in_process_runs_and_records_them(repo):
    adapter = ControlledAdapter()
    rt = runtime_with(repo, adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    await wait_status(repo, one["slow_path"]["run_id"], RunStatus.RUNNING)
    await rt.shutdown()
    run = repo.get_run(one["slow_path"]["run_id"])
    assert run.status == RunStatus.CANCELLED and run.cancellation_reason == "runtime_shutdown"
