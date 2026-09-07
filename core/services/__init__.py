"""
Services layer — the agent's governed capabilities behind stable interfaces.

Public API::

    from core import services
    services.inventory().check_parts("AC-COMP-01")
    services.cmms().create_work_package(proposal)
    services.notifications().raise_alert(equipment_id=..., severity="HIGH", summary=...)

Each accessor returns the adapter selected for that domain by
``SENTINEL_<DOMAIN>_ADAPTER`` (default ``local``). See ``registry`` for how to
register a custom adapter, and ``base`` for the interface contracts.
"""
from __future__ import annotations

from .base import (InventoryService, WorkforceService, SchedulingService,
                   CmmsService, NotificationService, GovernanceService,
                   MonitoringService, DOMAINS)
from .registry import register, resolve, reset_cache


def inventory() -> InventoryService:
    return resolve("inventory")            # type: ignore[return-value]


def workforce() -> WorkforceService:
    return resolve("workforce")            # type: ignore[return-value]


def scheduling() -> SchedulingService:
    return resolve("scheduling")           # type: ignore[return-value]


def cmms() -> CmmsService:
    return resolve("cmms")                 # type: ignore[return-value]


def notifications() -> NotificationService:
    return resolve("notifications")        # type: ignore[return-value]


def governance() -> GovernanceService:
    return resolve("governance")           # type: ignore[return-value]


def monitoring() -> MonitoringService:
    return resolve("monitoring")           # type: ignore[return-value]


__all__ = [
    "InventoryService", "WorkforceService", "SchedulingService",
    "CmmsService", "NotificationService", "GovernanceService", "MonitoringService",
    "DOMAINS", "register", "resolve", "reset_cache",
    "inventory", "workforce", "scheduling", "cmms", "notifications",
    "governance", "monitoring",
]
