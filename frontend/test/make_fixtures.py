"""Dump every scripted-demo snapshot (and the artifact index) as frontend test fixtures.

Uses only the disposable DemoScenarioRunner; touches no database, model, or reasoning code.
Run: python3 frontend/test/make_fixtures.py
"""
import asyncio, json, sys
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.demo.runner import DemoScenarioRunner

FLEET = [
    {"equipment_id": "AC-COMP-01", "name": "Instrument Air Compressor 01", "equipment_class": "COMPRESSOR", "criticality": "HIGH"},
    {"equipment_id": "CNC-MILL-07", "name": "CNC Machining Center 07", "equipment_class": "CNC_MACHINE", "criticality": "HIGH"},
    {"equipment_id": "HYD-PUMP-03", "name": "Hydraulic Power Unit 03", "equipment_class": "PUMP", "criticality": "MEDIUM"},
    {"equipment_id": "COOL-PMP-09", "name": "Coolant Circulation Pump 09", "equipment_class": "PUMP", "criticality": "MEDIUM"},
    {"equipment_id": "WELD-ROB-05", "name": "Spot-Weld Robot 05", "equipment_class": "ROBOT", "criticality": "MEDIUM"},
    {"equipment_id": "CONV-02", "name": "Main Transfer Conveyor 02", "equipment_class": "CONVEYOR", "criticality": "LOW"},
    {"equipment_id": "GRIND-04", "name": "Surface Grinder 04", "equipment_class": "GRINDER", "criticality": "MEDIUM"},
    {"equipment_id": "PRESS-08", "name": "Hydraulic Press 08", "equipment_class": "PRESS", "criticality": "HIGH"},
]

async def run(decision):
    frames = []
    runner = DemoScenarioRunner(FLEET, time_scale=0.001)
    async def publish():
        s = runner.snapshot()
        if s: frames.append(deepcopy(s))
    runner._publish = publish
    await runner.start("AC-COMP-01")
    for _ in range(4000):
        await asyncio.sleep(0.002)
        s = runner.snapshot()
        if s and s["demo_scenario"]["status"] == "awaiting_human_approval": break
    lc = runner.snapshot()["alerts"][0]["lifecycle"]
    intent = {k: lc[k] for k in ("requirement_id", "intervention_id", "intervention_hash", "context_revision")}
    if decision == "approve":
        assert (await runner.approve("AC-COMP-01", intent))["ok"]
        for _ in range(4000):
            await asyncio.sleep(0.002)
            if runner.snapshot()["demo_scenario"]["status"] == "complete": break
    else:
        assert (await runner.reject("AC-COMP-01", intent))["ok"]
    artifacts = runner.artifacts()
    await runner.reset(publish=False)
    return frames, artifacts

async def main():
    out = Path(__file__).parent / "fixtures"
    frames, artifacts = await run("approve")
    (out / "demo-frames.json").write_text(json.dumps(frames, default=str))
    (out / "demo-artifacts.json").write_text(json.dumps({a["id"]: a for a in artifacts}, default=str))
    rframes, _ = await run("reject")
    (out / "demo-frames-reject.json").write_text(json.dumps(rframes[-2:], default=str))
    statuses = [f["demo_scenario"]["status"] for f in frames]
    print(len(frames), "frames;", len(artifacts), "artifacts")
    print(" > ".join(dict.fromkeys(statuses)))

asyncio.run(main())
