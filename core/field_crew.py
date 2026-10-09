"""Simulated field crew (F1.2, D6): the sandbox scenario's technicians.

A scenario driver. It is not a person, and its work is not physical work. It
acknowledges, declines and reports work only through the ordinary ``LifecycleService``
work commands, so the same validation, eligibility policy (operon-work-eligibility-1),
revision checks and audit apply as for any caller. It acts as
``ActorRef(kind="SCENARIO")``, with SIMULATED provenance and summaries that say so.

Its behaviour is the asset profile's ``field_response``:

``COMPLETES``      acknowledge, then report COMPLETED (all instructions, physical work attested)
``PARTIAL``        acknowledge, then report PARTIAL (the first half of the instructions)
``NOT_PERFORMED``  acknowledge, then report NOT_PERFORMED (ineligible: no observation starts)
``DECLINES``       decline the request (no observation starts)
``NO_SHOW``        never respond (the case truthfully waits; acknowledgement becomes overdue)

Every decision depends only on durable work facts and the engine clock, so the crew is
deterministic and restart-safe. Its requests carry deterministic request keys, so a
repeated step is an idempotent replay. It never runs in production, where the SCENARIO
actor kind is refused anyway. When the crew is disabled, cases wait for work
(``AWAITING_WORK``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .reliability import models as m
from .reliability.repository import utcnow

ACTOR = m.ActorRef(kind="SCENARIO", id="sim.field-crew", role="technician")
RESPONSES = ("COMPLETES", "PARTIAL", "NOT_PERFORMED", "DECLINES", "NO_SHOW")
LABEL = "[SIMULATED field crew]"


@dataclass(frozen=True)
class CrewAction:
    """One work command the crew issues, with its exact lifecycle arguments (without actor/revision)."""
    command: str
    arguments: dict = field(default_factory=dict)


def _at(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


class SimulatedFieldCrew:
    def __init__(self, *, ack_after: timedelta, report_after: timedelta):
        self.ack_after, self.report_after = ack_after, report_after

    def next_action(self, work: dict, response: str, now: datetime, *, ack_after: timedelta | None = None,
                    report_after: timedelta | None = None) -> CrewAction | None:
        """The crew's next step for one durable assignment state, or None (pure)."""
        if response not in RESPONSES:
            raise ValueError(f"unknown simulated field response {response!r}")
        if not work.get("current") or response == "NO_SHOW":
            return None
        ack_after = self.ack_after if ack_after is None else ack_after
        report_after = self.report_after if report_after is None else report_after
        assignment_id, state = work["assignment_id"], work["state"]
        key = f"sim-crew:{assignment_id}"
        if state == "ASSIGNED":
            if now < _at(work["assigned_at"]) + ack_after:
                return None
            if response == "DECLINES":
                return CrewAction("decline_work", {"assignment_id": assignment_id, "request_key": f"{key}:decline",
                                                   "reason": f"{LABEL} scenario crew declined the request"})
            return CrewAction("acknowledge_work", {"assignment_id": assignment_id, "request_key": f"{key}:ack",
                                                   "note": f"{LABEL} scenario crew acknowledged the request"})
        if state != "ACKNOWLEDGED" or now < _at(work["acknowledged_at"]) + report_after:
            return None
        report = {"assignment_id": assignment_id, "request_key": f"{key}:report", "provenance": "SIMULATED"}
        total = len(work.get("instructions") or ())
        if response == "COMPLETES":
            return CrewAction("report_work", {**report, "result": "COMPLETED", "asset_intervened": True,
                                              "performed_at": utcnow(),
                                              "summary": f"{LABEL} scenario crew performed every work-package instruction "
                                                         "on the simulated asset (simulated work, not physical work)"})
        if response == "PARTIAL":
            done = tuple(range(max(1, total // 2))) if total else None
            return CrewAction("report_work", {**report, "result": "PARTIAL", "asset_intervened": True,
                                              "performed_at": utcnow(), "completed_instructions": done,
                                              "findings": (f"{LABEL} remaining instructions were not performed",),
                                              "summary": f"{LABEL} scenario crew performed part of the work package "
                                                         "(simulated work, not physical work)"})
        return CrewAction("report_work", {**report, "result": "NOT_PERFORMED",
                                          "findings": (f"{LABEL} the work could not be carried out",),
                                          "summary": f"{LABEL} scenario crew did not perform the work"})
