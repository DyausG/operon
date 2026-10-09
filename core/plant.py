"""Plant execution boundary (F1.2): the only way the lifecycle changes the plant.

dispatch != work performed != plant response != recovery != verified recovery

OPERON never assumes that dispatching a work package changes the asset. In a sandbox
(and in the historical unspecified local mode) the plant is the in-process
``PlantSimulator``. The engine asks it to respond only through ``PlantActuator``,
always with a named cause:

* ``ANALYSIS_HOLD`` / ``HOLD_REAPPLIED``: the demo pauses the simulated degradation while
  a case is analysed or re-investigated. This is a simulation convenience, never a claim
  about a real plant.
* ``HOLD_RELEASED``: a cancelled case releases that hold.
* ``RUN_TO_FAILURE``: an explicitly escalated rejection lets the simulated fault run on.
* ``WORK_PERFORMED``: an eligible work report (operon-work-eligibility-1) makes the
  simulated plant respond as its scenario profile dictates (``intervention_response``
  for COMPLETED, ``partial_response`` for PARTIAL). Nothing else ever makes the
  simulated plant recover.

In production there is no plant actuator. Physical work happens outside OPERON, so
``NullActuator`` reports ``NOT_SUPPORTED`` for every effect and never a successful
execution. Outcome verification never reads anything produced here: it reads persisted
telemetry and health scores only.

``SimulatorStateStore`` is the sandbox plant's own durable memory (migration 009). A real
plant does not reset when OPERON restarts, so neither does the simulator. A restart
restores each asset's mode, degradation progress, tick and scenario profile, and can
therefore never manufacture a recovery.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Callable, Literal

from . import db
from .seed_data import SENSOR_FEATURES
from .simulator import PlantSimulator, estimate_progress

logger = logging.getLogger(__name__)

PlantCause = Literal["ANALYSIS_HOLD", "HOLD_RELEASED", "HOLD_REAPPLIED", "RUN_TO_FAILURE", "WORK_PERFORMED"]
ActuationStatus = Literal["APPLIED", "NOT_SUPPORTED"]


class PlantActuationError(RuntimeError):
    """The actuator could not apply an effect; nothing about the plant may be assumed."""


@dataclass(frozen=True)
class PlantEffect:
    """What the lifecycle asks the plant to do, and why. ``WORK_PERFORMED`` names its eligible report."""
    cause: PlantCause
    equipment_id: str
    work_result: str | None = None
    report_id: str | None = None

    def __post_init__(self):
        if self.cause == "WORK_PERFORMED" and (self.work_result not in ("COMPLETED", "PARTIAL") or not self.report_id):
            raise ValueError("WORK_PERFORMED requires an eligible COMPLETED/PARTIAL work report")


@dataclass(frozen=True)
class ActuationResult:
    """What the actuator actually did. ``NOT_SUPPORTED`` means nothing was applied by OPERON."""
    status: ActuationStatus
    actuator: str
    actuator_kind: Literal["simulator", "none"]
    cause: PlantCause
    equipment_id: str
    reason: str
    mode_before: str | None = None
    mode_after: str | None = None
    response_profile: str | None = None

    @property
    def applied(self) -> bool:
        return self.status == "APPLIED"


class PlantActuator(ABC):
    kind: Literal["simulator", "none"]

    @property
    def identity(self) -> str:
        return f"{type(self).__module__}.{type(self).__qualname__}"

    @abstractmethod
    def apply(self, effect: PlantEffect, *, durable: bool = True) -> ActuationResult:
        """Apply one effect. ``durable=False`` defers persistence to the caller's next plant-state
        save (the engine tick); work effects are always persisted before they are recorded."""
        raise NotImplementedError


class SimulatorActuator(PlantActuator):
    """Sandbox plant: applies effects to the simulator and makes them durable before anything records them."""
    kind = "simulator"

    def __init__(self, simulator: Callable[[], PlantSimulator], store: "SimulatorStateStore | None" = None):
        self._simulator, self._store = simulator, store

    def apply(self, effect: PlantEffect, *, durable: bool = True) -> ActuationResult:
        sim = self._simulator()
        state = sim.assets.get(effect.equipment_id)
        if state is None:
            raise PlantActuationError(f"unknown simulated asset {effect.equipment_id}")
        before, profile = state.mode, None
        if effect.cause in ("ANALYSIS_HOLD", "HOLD_REAPPLIED"):
            sim.set_mode(effect.equipment_id, "arrested")
            reason = "simulated degradation held while the case is analysed (demo convenience, not a plant fact)"
        elif effect.cause == "HOLD_RELEASED":
            if state.mode == "arrested":
                sim.set_mode(effect.equipment_id, "degrading" if state.profile.scenario != "healthy" else "healthy")
            reason = "analysis hold released; the simulated asset follows its own profile again"
        elif effect.cause == "RUN_TO_FAILURE":
            sim.set_mode(effect.equipment_id, "failing")
            reason = "explicitly escalated rejection: the simulated fault runs on"
        else:
            profile, _ = sim.respond_to_work(effect.equipment_id, effect.work_result)
            reason = (f"simulated plant response to eligible {effect.work_result} work report {effect.report_id}: "
                      f"scenario profile {profile}")
        if self._store is not None and (durable or effect.cause == "WORK_PERFORMED"):
            # Durable before the effect is recorded anywhere: a crash can lose the record (then it is
            # replayed idempotently), never leave a record of an effect the plant does not remember.
            self._store.save(sim)
        return ActuationResult(status="APPLIED", actuator=self.identity, actuator_kind=self.kind, cause=effect.cause,
                               equipment_id=effect.equipment_id, reason=reason, mode_before=before,
                               mode_after=state.mode, response_profile=profile)


class NullActuator(PlantActuator):
    """Production: OPERON has no plant actuator. Every effect is NOT_SUPPORTED; nothing is ever applied."""
    kind = "none"

    def apply(self, effect: PlantEffect, *, durable: bool = True) -> ActuationResult:
        return ActuationResult(status="NOT_SUPPORTED", actuator=self.identity, actuator_kind=self.kind,
                               cause=effect.cause, equipment_id=effect.equipment_id,
                               reason="no plant actuator in this environment: physical work happens outside OPERON; "
                                      "nothing was applied and no execution is implied")


def actuator_for(environment: str, simulator: Callable[[], PlantSimulator],
                 store: "SimulatorStateStore | None" = None) -> PlantActuator:
    """Production never drives a simulated plant; every other environment's plant is the simulator."""
    if environment == "production":
        return NullActuator()
    return SimulatorActuator(simulator, store)


class SimulatorStateStore:
    """Durable memory of the sandbox plant (``simulator_asset_state``, migration 009).

    Plant-side state, written by the engine every tick and by every applied effect. It
    is never read by outcome verification, and the demo reset wipes it.
    """
    COLUMNS = ("equipment_id", "mode", "prog", "tick", "scenario", "start_tick", "ramp_ticks",
               "intervention_response", "partial_response", "field_response", "updated_at")

    def __init__(self, path: Path | None = None):
        self.path = path

    def load(self) -> dict[str, dict]:
        with db.get_conn(self.path) as conn:
            return {row["equipment_id"]: dict(row) for row in conn.execute(
                f"SELECT {','.join(self.COLUMNS)} FROM simulator_asset_state")}

    def save(self, sim: PlantSimulator, *, conn=None) -> None:
        """Upsert every asset; inside ``conn``'s transaction when given (the engine's tick write)."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [(*(row[column] for column in self.COLUMNS[:-1]), now) for row in sim.snapshot()]
        statement = (f"INSERT INTO simulator_asset_state ({','.join(self.COLUMNS)}) "
                     f"VALUES ({','.join('?' * len(self.COLUMNS))}) ON CONFLICT(equipment_id) DO UPDATE SET "
                     + ",".join(f"{column}=excluded.{column}" for column in self.COLUMNS[1:]))
        if conn is not None:
            conn.executemany(statement, rows)
            return
        with db.get_conn(self.path) as own:
            own.executemany(statement, rows)

    def estimate(self, sim: PlantSimulator, equipment_id: str, *, samples: int = 3) -> tuple[float, int] | None:
        """Pre-009 fallback: (progress, tick) from the asset's last persisted telemetry, or None.

        Used only when the store has no row for an asset that holds an active case (a
        database written before migration 009). Deterministic for the same rows; it keeps
        the held condition instead of resetting the asset to healthy.
        """
        state = sim.assets.get(equipment_id)
        if state is None:
            return None
        readings = {}
        with db.get_conn(self.path) as conn:
            for feature, sensor_type, _unit in SENSOR_FEATURES:
                values = [row[0] for row in conn.execute(
                    "SELECT value_eu FROM sensor_reading WHERE sensor_id=? ORDER BY ts DESC, rowid DESC LIMIT ?",
                    (f"{equipment_id}-{sensor_type}", samples))]
                if values:
                    readings[feature] = sum(values) / len(values)
            ticks = conn.execute("SELECT COUNT(*) FROM health_score WHERE equipment_id=?", (equipment_id,)).fetchone()[0]
        if not readings:
            return None
        return estimate_progress(state.profile, readings), int(ticks)
