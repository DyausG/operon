"""
Service interfaces (the "ports" of a ports-and-adapters design).

The Maintenance Agent depends ONLY on these abstract interfaces — never on a
concrete backend. The demo ships a local, SQLite-backed adapter for each
(see ``core/services/adapters/local.py``), but an adopter can implement the same
interface against their real systems — a CMMS (SAP PM, IBM Maximo), a warehouse
management system, an MES scheduler, a paging/notification service — and select
it per-domain via the ``SENTINEL_<DOMAIN>_ADAPTER`` environment variable
(see ``core/services/registry.py``).

Every method takes and returns plain JSON-serializable ``dict``s. That keeps the
contract transport-agnostic: the same interface can be satisfied by an in-process
adapter today, or an HTTP / MCP-tool adapter later, without the agent changing.
Return-shape contracts are documented on each method.
"""
from __future__ import annotations
from abc import ABC, abstractmethod


class InventoryService(ABC):
    """Spare-parts availability (a WMS / ERP inventory port)."""

    @abstractmethod
    def check_parts(self, equipment_id: str) -> dict:
        """Return the bill-of-materials + availability for an asset.

        Returns:
            {
              "parts": [ {part_number, description, on_hand_qty, lead_time_days,
                          qty_per_service, is_critical_spare}, ... ],
              "critical_available": bool,   # every critical spare is in stock
              "summary": str,               # one-line human summary
            }
        """
        raise NotImplementedError


class WorkforceService(ABC):
    """Certified-labor assignment (an HR / CMMS labor-ontology port)."""

    @abstractmethod
    def assign_technician(self, equipment_class: str, current_shift: str = "A") -> dict:
        """Pick the best available, certified technician for an equipment class.

        Returns:
            {
              "technician": {technician_id, full_name, job_title, skills, shift, ...} | None,
              "reason": str,
              "candidates_considered": int,
            }
        """
        raise NotImplementedError


class SchedulingService(ABC):
    """Planned production-window reservation (an MES / scheduling port)."""

    @abstractmethod
    def block_schedule(self, equipment_id: str, window_min: int = 45) -> dict:
        """Propose a planned maintenance window so the repair avoids a line-down.

        Returns:
            {"equipment_id", "window", "window_min", "note"}
        """
        raise NotImplementedError


class CmmsService(ABC):
    """Work-order authoring + governed write-back (a CMMS port)."""

    @abstractmethod
    def propose_work_order(self, equipment_id: str, failure_mode_id: str,
                           technician_id: str | None, detail: str,
                           priority: str = "HIGH") -> dict:
        """Draft a work order (NOT persisted — human approval gates the write).

        Returns:
            {"equipment_id", "failure_mode_id", "technician_id", "priority",
             "detail", "status": "DRAFT", "wo_number": "...-DRAFT"}
        """
        raise NotImplementedError

    @abstractmethod
    def commit_work_order(self, proposal: dict) -> dict:
        """Persist an approved work order + its maintenance event (the minimal
        governed write-back).

        Returns: {"wo_id", "wo_number", "status": "OPEN"}
        """
        raise NotImplementedError

    @abstractmethod
    def create_work_package(self, proposal: dict) -> dict:
        """Assemble a complete, dispatch-ready **repair work package** atomically:
        the work order, reserved spare parts, a labor booking for the assigned
        technician, the planned schedule hold, and a dispatch notification —
        linked under one package header.

        This is the richer capability an adopter would wire to their CMMS's
        "work package" / "job plan" concept.

        Returns:
            {"wo_id", "wo_number", "package_number", "status",
             "reserved_parts": [...], "labor_booking": {...},
             "notification": {...}}
        """
        raise NotImplementedError


class NotificationService(ABC):
    """Alerting + stakeholder notification (a paging / ITSM port).

    Two responsibilities that a real deployment often splits across systems:
      * ``raise_alert`` — record/emit an operational alert (monitoring feed).
      * ``notify``      — message a specific recipient (page a technician).
    """

    @abstractmethod
    def raise_alert(self, *, equipment_id: str, severity: str,
                    summary: str, source: str = "agent") -> dict:
        """Record/emit an operational alert. Returns {"alert_id", "status", ...}."""
        raise NotImplementedError

    @abstractmethod
    def notify(self, *, recipient_id: str | None, subject: str, body: str,
               channel: str = "sms", send: bool = True, wo_id: int | None = None) -> dict:
        """Message a recipient. With ``send=False`` returns a DRAFT preview and
        writes nothing (used while the agent is still only *proposing*); with
        ``send=True`` performs the send and records it.

        Returns: {"notification_id" | None, "recipient_id", "channel",
                  "subject", "status": "DRAFT" | "SENT", "preview": str}
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Peer agents (not tools) — a Governance authority and a Monitoring analyst the
# Maintenance Agent consults. Their local adapters are deterministic engines; an
# `a2a` adapter reaches them as real peers over the A2A protocol. A2A is for
# *agents* (these reason); MCP is for *tools*.
# ---------------------------------------------------------------------------
class GovernanceService(ABC):
    """Policy authority that rules on a proposed plan before a human approves."""

    @abstractmethod
    def review_plan(self, proposal: dict) -> dict:
        """Rule on a proposed work package against policy.

        Returns:
            {
              "decision": "APPROVE" | "CONDITIONS" | "VETO",
              "reasons": [str, ...],       # why this decision
              "conditions": [str, ...],    # what must hold if CONDITIONS
              "policy_version": str,
            }
        """
        raise NotImplementedError


class MonitoringService(ABC):
    """Analyst that reasons over the live alert set for escalation/correlation."""

    @abstractmethod
    def assess(self, snapshot: dict) -> dict:
        """Assess the active-alert snapshot for systemic patterns.

        Args:
            snapshot: {"alerts": [{equipment_id, equipment_class, predicted_mode,
                       failure_prob, criticality}, ...]}
        Returns:
            {
              "escalate": bool,
              "correlations": [{"pattern": str, "equipment_ids": [...], "note": str}],
              "rationale": str,
            }
        """
        raise NotImplementedError


# Domains keyed for the registry / env-var selection.
DOMAINS = ("inventory", "workforce", "scheduling", "cmms", "notifications",
           "governance", "monitoring")
