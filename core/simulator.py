"""
Multi-equipment fleet simulator.

Every asset streams telemetry in the AI4I feature space (air/process temperature,
rotational speed, torque, tool wear) so the AI4I-trained model scores them directly.
Sensors are physically correlated (process temperature tracks air temperature; power
follows torque × speed), and three assets walk *distinct* degradation trajectories
toward real AI4I failure modes on staggered timelines — so several alerts overlap and
the agent must triage. The rest run healthy with realistic noise.

Degradation modes are driven by the demo engine:
    degrading    -> risk climbs each tick
    arrested     -> hold (agent has proposed; awaiting human approval)
    recovering   -> SIMULATED plant response to a confirmed work package; signals relax to healthy
    unresponsive -> SIMULATED plant that does not respond to the confirmed work package; risk holds
    failing      -> human rejected/ignored; runs to unplanned failure

Step 14: a confirmed execution never sets "recovering" directly. The engine calls
``respond_to_intervention`` and the asset profile's ``intervention_response`` decides
whether the simulated plant recovers or stays degraded, so tests and demos can show
verified recovery, persistent failure and inconclusive observation without hard-
coding "maintenance always succeeds". Everything here is simulated provenance; the
application's outcome verification reads only persisted evidence.
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field, replace

from . import dataset as ds

# Per-scenario feature deltas applied at full degradation (prog = 1.0). Each targets
# the documented AI4I trigger region for that failure mode.
SCENARIO_DELTAS = {
    #            d_air, d_proc_off, d_speed, d_torque, d_toolwear
    # OSF: overstrain (tool-wear·torque) crosses the tier limit while mechanical
    # power stays in-band — torque rises modestly and speed drops to hold power < trip.
    "OSF": dict(air=0.5,  proc_off=0.0,  speed=-55,  torque=+12, tool=+88),
    "TWF": dict(air=0.5,  proc_off=0.0,  speed=-25,  torque=+16, tool=+78),   # tool end-of-life
    "HDF": dict(air=4.2,  proc_off=-3.4, speed=-165, torque=+4,  tool=+15),   # ΔT collapses, low speed
    "PWF": dict(air=0.5,  proc_off=0.0,  speed=+60,  torque=+26, tool=+10),   # power over the safe band
    "healthy": dict(air=0.0, proc_off=0.0, speed=0, torque=0, tool=0),
}

FAIL_PROG = 1.15          # degradation progress at which an un-actioned asset seizes
RECOVER_STEP = 0.28       # prog shed per tick while recovering


@dataclass
class AssetProfile:
    equipment_id: str
    equipment_class: str
    product_tier: str
    scenario: str          # OSF | TWF | HDF | PWF | healthy
    start_tick: int        # tick at which degradation begins
    ramp_ticks: int        # ticks from onset to full degradation (staggers alerts)
    base: dict             # healthy baseline feature values
    # SIMULATED response to a confirmed work package (demo provenance only):
    #   RECOVERS -> "recovering" mode; PERSISTS -> "unresponsive" mode (risk holds).
    intervention_response: str = "RECOVERS"


# Healthy baselines per asset (AI4I feature space) + degradation scenario.
FLEET = [
    AssetProfile("AC-COMP-01",  "COMPRESSOR",  "H", "PWF", start_tick=2, ramp_ticks=8,
                 base=dict(air=300.5, proc=310.5, speed=1500, torque=45, tool=90)),
    AssetProfile("CNC-MILL-07", "CNC_MACHINE", "H", "OSF", start_tick=4, ramp_ticks=12,
                 base=dict(air=299.8, proc=309.6, speed=1470, torque=44, tool=168)),
    AssetProfile("HYD-PUMP-03", "PUMP",        "M", "HDF", start_tick=6, ramp_ticks=15,
                 base=dict(air=300.0, proc=309.4, speed=1510, torque=42, tool=95)),
    # A second pump walks the SAME heat-dissipation trajectory on an overlapping
    # timeline — so the Monitoring peer detects a systemic (common-cause) pattern
    # across the two pumps, not two coincidences.
    AssetProfile("COOL-PMP-09", "PUMP",        "L", "HDF", start_tick=9, ramp_ticks=16,
                 base=dict(air=299.5, proc=309.0, speed=1495, torque=38, tool=60)),
    AssetProfile("WELD-ROB-05", "ROBOT",       "M", "healthy", start_tick=0, ramp_ticks=1,
                 base=dict(air=299.2, proc=308.9, speed=1420, torque=30, tool=40)),
    AssetProfile("CONV-02",     "CONVEYOR",    "L", "healthy", start_tick=0, ramp_ticks=1,
                 base=dict(air=298.9, proc=308.6, speed=1380, torque=25, tool=20)),
    AssetProfile("GRIND-04",    "GRINDER",     "M", "healthy", start_tick=0, ramp_ticks=1,
                 base=dict(air=300.1, proc=310.2, speed=1560, torque=41, tool=120)),
    AssetProfile("PRESS-08",    "PRESS",       "H", "healthy", start_tick=0, ramp_ticks=1,
                 base=dict(air=300.3, proc=310.0, speed=1440, torque=48, tool=80)),
]


@dataclass
class AssetState:
    profile: AssetProfile
    mode: str = "healthy"        # engine-driven lifecycle mode
    tick: int = 0
    prog: float = 0.0            # degradation progress (0 = healthy, 1 = at failure region)

    @property
    def equipment_id(self):
        return self.profile.equipment_id


class PlantSimulator:
    def __init__(self, seed: int = 7):
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.assets: dict[str, AssetState] = {}
        for p in FLEET:
            mode = "degrading" if p.scenario != "healthy" else "healthy"
            # Per-instance profile copy: demo tweaks (e.g. intervention_response) never leak across simulators.
            self.assets[p.equipment_id] = AssetState(profile=replace(p), mode=mode)

    def set_mode(self, equipment_id: str, mode: str):
        self.assets[equipment_id].mode = mode

    def respond_to_intervention(self, equipment_id: str) -> str:
        """SIMULATED plant response to a confirmed work package; returns the mode applied.

        Demo provenance only: whether the simulated asset recovers is a property of
        its scenario profile, never an assumption that maintenance succeeded. The
        application verifies outcomes from persisted evidence, not from this state.
        """
        st = self.assets[equipment_id]
        response = st.profile.intervention_response
        if response not in ("RECOVERS", "PERSISTS"):
            raise ValueError(f"unknown simulated intervention response {response!r}")
        st.mode = "recovering" if response == "RECOVERS" else "unresponsive"
        return st.mode

    def _noise(self, sd: float) -> float:
        return float(self.rng.normal(0, sd))

    def _features_for(self, st: AssetState) -> dict:
        p = st.profile
        b = p.base
        d = SCENARIO_DELTAS[p.scenario]
        g = st.prog
        # slow natural tool-wear accumulation on every machine
        natural_wear = 0.25 * st.tick
        air = b["air"] + d["air"] * g + self._noise(0.15)
        proc = b["proc"] + (d["air"] + d["proc_off"]) * g + self._noise(0.25)
        speed = b["speed"] + d["speed"] * g + self._noise(4.0)
        torque = b["torque"] + d["torque"] * g + self._noise(0.4)
        tool = b["tool"] + natural_wear + d["tool"] * g + self._noise(0.6)
        feats = {
            "type_code": ds.TYPE_CODE.get(p.product_tier, 0),
            "air_temp": round(max(295.0, air), 2),
            "process_temp": round(max(air + 3.0, proc), 2),   # process never below air+3
            "rot_speed": round(max(1160.0, speed), 1),
            "torque": round(max(3.5, torque), 2),
            "tool_wear": round(max(0.0, tool), 1),
        }
        return feats

    def tick(self) -> dict[str, dict]:
        out = {}
        for eid, st in self.assets.items():
            st.tick += 1
            p = st.profile
            step = (1.0 / max(1, p.ramp_ticks))
            if st.mode == "degrading":
                if st.tick >= p.start_tick:
                    st.prog = min(FAIL_PROG, st.prog + step)
            elif st.mode == "failing":
                st.prog = min(FAIL_PROG, st.prog + step * 1.6)
            elif st.mode == "recovering":
                st.prog = max(0.0, st.prog - RECOVER_STEP)
                if st.prog <= 0.02:
                    st.prog = 0.0
                    st.mode = "healthy"
            # 'arrested', 'unresponsive' and 'healthy' hold prog flat
            out[eid] = self._features_for(st)
        return out

    def failed(self, equipment_id: str) -> bool:
        st = self.assets[equipment_id]
        return st.mode == "failing" and st.prog >= FAIL_PROG
