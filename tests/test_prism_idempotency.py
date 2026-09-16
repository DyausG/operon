"""Request and effect idempotency: sequential, concurrent, after reconstruction. Exactly one logical effect."""
from __future__ import annotations

import asyncio

import pytest

from core.prism import PrismRepository, PrismRuntime, RunStatus
from core.prism.testing import ControlledAdapter


@pytest.fixture
def repo(seeded_db):
    return PrismRepository()


async def test_sequential_duplicate_request_creates_no_second_turn_revision_or_run(repo):
    rt = PrismRuntime(repo, adapter=ControlledAdapter())
    sid = (await rt.create_session())["session_id"]
    first = await rt.submit_message(sid, content="first instruction here", request_id="req-1", idempotency_key="key-1")
    replay = await rt.submit_message(sid, content="first instruction here", request_id="req-1b", idempotency_key="key-1")
    assert replay["duplicate"] and not first["duplicate"]
    assert (replay["turn_id"], replay["revision"], replay["slow_path"]["run_id"]) == (
        first["turn_id"], first["revision"], first["slow_path"]["run_id"])
    assert replay["fast_path"]["status"] == first["fast_path"]["status"]
    assert len(repo.list_turns(sid)) == 1 and len(repo.list_runs(sid)) == 1
    assert len(rt.coordinator.handles) == 1
    await rt.shutdown()


async def test_request_id_alone_dedupes_replayed_frames(repo):
    rt = PrismRuntime(repo, adapter=ControlledAdapter())
    sid = (await rt.create_session())["session_id"]
    await rt.submit_message(sid, content="first instruction here", request_id="frame-7")
    replay = await rt.submit_message(sid, content="first instruction here", request_id="frame-7")
    assert replay["duplicate"] and repo.get_session(sid).current_revision == 1
    await rt.shutdown()


async def test_concurrent_duplicate_submissions_dedupe_atomically_in_process(repo):
    rt = PrismRuntime(repo, adapter=ControlledAdapter())
    sid = (await rt.create_session())["session_id"]
    results = await asyncio.gather(*[
        rt.submit_message(sid, content="same instruction here", idempotency_key="dup-key") for _ in range(10)])
    assert sum(1 for r in results if not r["duplicate"]) == 1
    assert len({r["turn_id"] for r in results}) == 1 and len({r["slow_path"]["run_id"] for r in results}) == 1
    assert repo.get_session(sid).current_revision == 1 and len(rt.coordinator.handles) == 1
    await rt.shutdown()


async def test_concurrent_duplicates_across_runtime_instances_share_one_turn(repo):
    """Six runtimes (six worker processes) over one database: the database, not a process lock, dedupes."""
    sid = (await PrismRuntime(repo, adapter=ControlledAdapter()).create_session())["session_id"]

    async def worker():
        rt = PrismRuntime(PrismRepository(repo.path), adapter=ControlledAdapter())
        try:
            return await rt.submit_message(sid, content="same instruction here", idempotency_key="shared-key")
        finally:
            await rt.shutdown()

    results = await asyncio.gather(*[asyncio.to_thread(lambda: asyncio.run(worker())) for _ in range(6)])
    assert sum(1 for r in results if not r["duplicate"]) == 1
    assert len({r["turn_id"] for r in results}) == 1
    assert repo.get_session(sid).current_revision == 1 and len(repo.list_runs(sid)) == 1


async def test_duplicate_effect_completion_records_exactly_one_effect(repo):
    adapter = ControlledAdapter(effect={"ticket": "T-1"}, effect_key="ticket-1", auto_release=True)
    rt = PrismRuntime(repo, adapter=adapter)
    sid = (await rt.create_session())["session_id"]
    one = await rt.submit_message(sid, content="first instruction here")
    assert await rt.wait_idle(5)
    execution = adapter.started[0]
    # Retry the same tool call on the same run: performed nothing, returned the recorded outcome.
    async def perform():
        raise AssertionError("must not perform a duplicate effect")
    outcome = await execution.effect(tool_call_id="ticket-1", kind="simulated_tool", payload={"ticket": "T-1"},
                                     perform=perform, idempotency_key="ticket-1")
    assert outcome.duplicate and not outcome.performed and outcome.effect.result == {"ok": True, "ticket": "T-1"}
    effects = repo.list_effects(sid)
    assert len(effects) == 1 and effects[0].status.value == "COMPLETED"
    assert len(adapter.performed_effects) == 1
    assert repo.get_run(one["slow_path"]["run_id"]).status == RunStatus.COMPLETED


async def test_retry_after_repository_and_runtime_reconstruction_is_idempotent(repo):
    rt = PrismRuntime(repo, adapter=ControlledAdapter(effect={"ticket": "T-9"}, effect_key="ticket-9", auto_release=True))
    sid = (await rt.create_session())["session_id"]
    first = await rt.submit_message(sid, content="first instruction here", idempotency_key="op-1")
    assert await rt.wait_idle(5)
    # New repository + runtime objects over the same database (process restart).
    rebuilt = PrismRuntime(PrismRepository(repo.path),
                           adapter=ControlledAdapter(effect={"ticket": "T-9"}, effect_key="ticket-9", auto_release=True))
    await rebuilt.recover()
    replay = await rebuilt.submit_message(sid, content="first instruction here", idempotency_key="op-1")
    assert replay["duplicate"] and replay["turn_id"] == first["turn_id"]
    assert repo.get_session(sid).current_revision == 1 and len(repo.list_runs(sid)) == 1
    assert len(repo.list_effects(sid)) == 1     # the committed effect was not repeated
    assert rebuilt.coordinator.adapter.performed_effects == []
