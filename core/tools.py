"""
The maintenance agent's governed tools — a thin facade over the services layer
(``core/services/``). Whether the agent is driven by AWS Bedrock or the
deterministic planner, these are the ONLY ways it can act, so every action is
grounded in real governed data (the anti-hallucination "semantic layer" pattern).

    check_parts()          -> spare-parts availability      (InventoryService)
    assign_technician()    -> best certified & available tech (WorkforceService)
    block_schedule()       -> propose a planned hold         (SchedulingService)
    propose_work_order()   -> draft a CMMS work order        (CmmsService)
    notify_technician()    -> draft a dispatch page          (NotificationService)

commit_actions() accepts only durable incident/intervention IDs and delegates to
the application-owned executor. Generic proposal dictionaries are never executable.

These functions keep their original signatures so callers stay decoupled from
the backend; swap the backend per-domain with SENTINEL_<DOMAIN>_ADAPTER.
"""
from __future__ import annotations
from . import services
from .db import get_conn


# ---------------------------------------------------------------------------
# Master-data reads (grounding lookups; not agent "actions")
# ---------------------------------------------------------------------------
def get_equipment(equipment_id: str) -> dict:
    with get_conn() as c:
        r = c.execute("SELECT * FROM equipment WHERE equipment_id=?", (equipment_id,)).fetchone()
        return dict(r) if r else {}


def get_failure_mode_by_code(mode_code: str) -> dict:
    with get_conn() as c:
        r = c.execute("SELECT * FROM failure_mode WHERE mode_code=?", (mode_code,)).fetchone()
        return dict(r) if r else {}


# ---------------------------------------------------------------------------
# Governed tools — delegate to the selected service adapters
# ---------------------------------------------------------------------------
def check_parts(equipment_id: str) -> dict:
    return services.inventory().check_parts(equipment_id)


def assign_technician(equipment_class: str, current_shift: str = "A") -> dict:
    return services.workforce().assign_technician(equipment_class, current_shift)


def block_schedule(equipment_id: str, window_min: int = 45) -> dict:
    return services.scheduling().block_schedule(equipment_id, window_min)


def propose_work_order(equipment_id: str, failure_mode_id: str, technician_id: str | None,
                       detail: str, priority: str = "HIGH") -> dict:
    return services.cmms().propose_work_order(equipment_id, failure_mode_id,
                                              technician_id, detail, priority)


def notify_technician(recipient_id: str | None, subject: str, body: str,
                      channel: str = "sms", send: bool = False, wo_id: int | None = None) -> dict:
    if send:
        raise PermissionError("dispatch requires a persisted Intervention and governed execution")
    return services.notifications().notify(recipient_id=recipient_id, subject=subject,
                                           body=body, channel=channel, send=False, wo_id=wo_id)


def raise_alert(equipment_id: str, severity: str, summary: str, source: str = "agent") -> dict:
    raise PermissionError("operational alert writes are application-owned")


# ---------------------------------------------------------------------------
# Governed write-back (only after human approval)
# ---------------------------------------------------------------------------
def commit_actions(incident_id: str, intervention_id: str) -> dict:
    """Execute one exact persisted Intervention through the trusted boundary."""
    if not isinstance(incident_id, str) or not isinstance(intervention_id, str):
        raise TypeError("commit_actions requires incident_id and intervention_id strings")
    from .reliability.execution import GovernedExecutor
    from .reliability.repository import IncidentRepository
    return GovernedExecutor(IncidentRepository()).execute(incident_id, intervention_id).model_dump(mode="json")
