"""Dump Guided Demo snapshots (and the inspector artifact index) as frontend test fixtures.

Drives the real ``DemoEngine`` on a throwaway database exactly as ``POST /api/demo/scenario``
does, with no provider configured, so every frame is the engine's own websocket shape:
deterministic scenario, real lifecycle, labelled deterministic advisory (no model).
Run: python3 frontend/test/make_fixtures.py   (or ``npm run fixtures``)
     uv run python frontend/test/make_fixtures.py   (Windows / any shell, from the repository root)
     ... --out <dir>   writes elsewhere (determinism checks)

Files:
- demo-frames.json / demo-artifacts.json: the approved Guided Demo, healthy to verified recovery.
- demo-frames-reject.json: the approval frame and the frame after a recorded rejection (F1: the
  case returns to PLANNING and the rejected intervention is consumed).
- demo-frames-material.json / demo-frames-blocking.json (F1 typed uncertainty): the same scenario
  with one typed uncertainty on the diagnosis that follows the trusted inspection. Only that
  advisory input is scripted (``UncertaintyAdvisory``, labelled in every run snapshot); promotion,
  the approval requirement and the projection are the real lifecycle. MATERIAL reaches the
  approver as a condition; BLOCKING refuses promotion and the case stays parked.
Generation stops with an error if the engine does not produce those contracts.
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
from core.agents.contracts import SupervisorResult  # noqa: E402
from core.db import init_schema  # noqa: E402
from core.demo_scenario import DeterministicAdvisoryBackend  # noqa: E402
from core.engine import DemoEngine  # noqa: E402
from core.seed_data import seed  # noqa: E402

ASSET = "AC-COMP-01"
INTENT = ("requirement_id", "intervention_id", "intervention_hash", "context_revision")
APPROVED_SEQUENCE = ["factory_healthy", "degrading", "investigating", "awaiting_evidence", "diagnosis_validated",
                     "awaiting_human_approval", "observing", "complete"]
MATERIAL = "Fixture: maintenance history before the last service is incomplete"
BLOCKING = "Fixture: shaft condition has not been inspected"


class UncertaintyAdvisory(DeterministicAdvisoryBackend):
    """Fixture-only advisory: the deterministic advisory plus one typed uncertainty on the
    diagnostic assessment of the diagnosis that follows the trusted inspection (the run that
    would promote). Still no model; it identifies itself as a fixture variant."""

    def __init__(self, severity: str, statement: str):
        super().__init__()
        self.severity, self.statement = severity, statement

    def identity(self) -> dict:
        return super().identity() | {"implementation": f"operon.fixtures.uncertainty-{self.severity.lower()}-v1"}

    async def supervise(self, service, context, **kwargs) -> SupervisorResult:
        result = await super().supervise(service, context, **kwargs)
        confirmed = any(item.source_capability == "operon.confirm_mechanism" for item in context.evidence)
        if context.review_target_id is not None or not confirmed:
            return result
        data = result.model_dump(mode="json")
        for item in data["assessments"]:
            if item["key"] == "diagnostic":
                item["assessment"]["uncertainties"] = [{"statement": self.statement, "severity": self.severity}]
        return SupervisorResult.model_validate(data)


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


# A step is recorded once the engine has finished the work that immediately follows its phase
# change, so the frame does not depend on polling timing: OBSERVING is recorded once the
# observation plan (planned right after the dispatch receipt) exists.
SETTLED = {"OBSERVING": lambda lifecycle: (lifecycle.get("read_model") or {}).get("observation_plans")}


async def capture(engine, frames, terminal):
    """Record one settled snapshot per distinct (status, phase) pair until ``terminal``."""
    seen = None
    while True:
        snapshot = engine.snapshot()
        demo = snapshot.get("demo_scenario") or {}
        lifecycle = (snapshot.get("alerts") or [{}])[0].get("lifecycle") or {}
        key = (demo.get("status"), demo.get("phase"), lifecycle.get("phase"))
        settled = SETTLED.get(lifecycle.get("phase"), lambda _: True)(lifecycle)
        if key != seen and settled:
            frames.append(deepcopy(snapshot))
            seen = key
        if demo.get("status") in terminal:
            return
        if demo.get("status") == "failed":
            raise SystemExit(f"guided demo failed: {demo.get('error')}")
        await asyncio.sleep(0.005)


async def run(decision, runtime=None):
    config.TICK_SECONDS = 0.02
    engine = DemoEngine(runtime=runtime)
    engine.demo_step_delay = 0.08
    frames = []
    assert (await engine.start_guided_demo(ASSET))["ok"]
    if decision == "blocking":
        await capture(engine, frames, {"failed"})
    else:
        await capture(engine, frames, {"awaiting_human_approval"})
    if decision in ("material", "blocking"):
        await engine.reset(restart=False)
        await engine.stop()
        return frames, {}
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
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else Path(__file__).parent / "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    frames, artifacts = await run("approve")
    expect([f["demo_scenario"]["status"] for f in frames] == APPROVED_SEQUENCE,
           f"the approved Guided Demo must record one frame per step: {[f['demo_scenario']['status'] for f in frames]}")
    (out / "demo-frames.json").write_text(json.dumps(frames, default=str))
    (out / "demo-artifacts.json").write_text(json.dumps(artifacts, default=str))
    rframes, _ = await run("reject")
    rejected = lifecycle_of(rframes[-1])
    expect(rejected["phase"] == "PLANNING" and not rejected.get("intervention_id"),
           f"a rejection must return the case to PLANNING with the intervention consumed: {rejected['phase']}")
    (out / "demo-frames-reject.json").write_text(json.dumps(rframes[-2:], default=str))

    mframes, _ = await run("material", UncertaintyAdvisory("MATERIAL", MATERIAL))
    requirement = pending_requirement(mframes[-1])
    expect(lifecycle_of(mframes[-1])["phase"] == "AWAITING_APPROVAL"
           and [item.get("statement") for item in requirement.get("material_uncertainties", [])] == [MATERIAL]
           and any(MATERIAL in condition for condition in requirement.get("conditions", [])),
           "MATERIAL uncertainty must promote and reach the approval requirement and its conditions")
    (out / "demo-frames-material.json").write_text(json.dumps(mframes[-1:], default=str))

    bframes, _ = await run("blocking", UncertaintyAdvisory("BLOCKING", BLOCKING))
    parked = lifecycle_of(bframes[-1])
    expect(parked["phase"] == "AWAITING_EVIDENCE" and not parked.get("requirement_id")
           and "NEEDS_EVIDENCE" in (bframes[-1]["demo_scenario"].get("error") or ""),
           f"BLOCKING uncertainty must refuse promotion and leave the case parked: {parked['phase']}")
    (out / "demo-frames-blocking.json").write_text(json.dumps(bframes[-1:], default=str))

    statuses = [f["demo_scenario"]["status"] for f in frames]
    print(len(frames), "frames;", len(artifacts), "artifacts")
    print(" > ".join(dict.fromkeys(statuses)))
    print("reject >", rejected["phase"], "| material >", lifecycle_of(mframes[-1])["phase"],
          "| blocking >", parked["phase"], "-", bframes[-1]["demo_scenario"].get("error"))


def lifecycle_of(frame) -> dict:
    return ((frame.get("alerts") or [{}])[0].get("lifecycle") or {})


def pending_requirement(frame) -> dict:
    """The requirement the V2 UI reads (frontend/src/v2/model/cases.js pendingRequirement)."""
    lifecycle = lifecycle_of(frame)
    return next((item for item in (lifecycle.get("read_model") or {}).get("requirements", [])
                 if item.get("id") == lifecycle.get("requirement_id")), {})


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"fixture contract not met: {message}")

asyncio.run(main())
