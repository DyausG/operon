"""Dump Guided Demo snapshots (and the inspector artifact index) as frontend test fixtures.

Drives the real ``DemoEngine`` on a throwaway database exactly as ``POST /api/demo/scenario``
does, with no provider configured, so every frame is the engine's own websocket shape:
deterministic scenario, real lifecycle, labelled deterministic advisory (no model).
Run: python3 frontend/test/make_fixtures.py   (or ``npm run fixtures``)
"""
import asyncio
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="operon-fixtures-")
os.environ["POC_DB_PATH"] = str(Path(TMP) / "fixtures.db")
os.environ.setdefault("POC_MODEL_PATH", str(ROOT / "data" / "health_model.joblib"))
os.environ["POC_FORCE_DETERMINISTIC"] = "1"
os.environ["POC_TICK_SECONDS"] = "0.02"
for key in ("OPERON_AI_PROVIDER", "OPERON_REASONING_BACKEND", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPERON_OLLAMA_MODEL"):
    os.environ.pop(key, None)

from core import config  # noqa: E402
from core.db import init_schema  # noqa: E402
from core.engine import DemoEngine  # noqa: E402
from core.seed_data import seed  # noqa: E402

ASSET = "AC-COMP-01"
INTENT = ("requirement_id", "intervention_id", "intervention_hash", "context_revision")


async def wait_status(engine, status, timeout=60):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        projection = engine._demo_projection()
        if projection.get("status") == status:
            return projection
        if projection.get("status") == "failed":
            raise SystemExit(f"guided demo failed: {projection.get('error')}")
        await asyncio.sleep(0.01)
    raise SystemExit(f"guided demo did not reach {status}: {engine._demo_projection()}")


async def capture(engine, frames, terminal):
    """Record one snapshot per distinct (status, phase) pair until ``terminal``."""
    seen = None
    while True:
        snapshot = engine.snapshot()
        demo = snapshot.get("demo_scenario") or {}
        key = (demo.get("status"), demo.get("phase"), (snapshot.get("alerts") or [{}])[0].get("lifecycle", {}).get("phase"))
        if key != seen:
            frames.append(deepcopy(snapshot))
            seen = key
        if demo.get("status") in terminal:
            return
        await asyncio.sleep(0.005)


async def run(decision):
    config.TICK_SECONDS = 0.02
    engine = DemoEngine(runtime=None)
    engine.demo_step_delay = 0.08
    frames = []
    assert (await engine.start_guided_demo(ASSET))["ok"]
    await capture(engine, frames, {"awaiting_human_approval"})
    lifecycle = engine.snapshot()["alerts"][0]["lifecycle"]
    intent = {key: lifecycle[key] for key in INTENT}
    if decision == "approve":
        assert (await engine.approve(ASSET, intent))["ok"]
        await capture(engine, frames, {"complete"})
    else:
        assert (await engine.reject(ASSET, intent))["ok"]
        await capture(engine, frames, {"cancelled"})
    view = engine.snapshot()["alerts"][0]["lifecycle"]["read_model"]
    ids = set()
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("id", "artifact_id", "snapshot_id") and isinstance(item, str):
                    ids.add(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(view)
    artifacts = {}
    for artifact_id in sorted(ids):
        try:
            artifacts[artifact_id] = engine.demo_artifact(artifact_id)
        except LookupError:
            continue
    await engine.reset(restart=False)
    await engine.stop()
    return frames, artifacts


async def main():
    init_schema()
    seed(reset=True)
    out = Path(__file__).parent / "fixtures"
    frames, artifacts = await run("approve")
    (out / "demo-frames.json").write_text(json.dumps(frames, default=str))
    (out / "demo-artifacts.json").write_text(json.dumps(artifacts, default=str))
    rframes, _ = await run("reject")
    (out / "demo-frames-reject.json").write_text(json.dumps(rframes[-2:], default=str))
    statuses = [f["demo_scenario"]["status"] for f in frames]
    print(len(frames), "frames;", len(artifacts), "artifacts")
    print(" > ".join(dict.fromkeys(statuses)))

asyncio.run(main())
