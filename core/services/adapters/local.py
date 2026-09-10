"""
Local reference adapters — the default, zero-dependency implementation of every
service interface, backed by the SQLite semantic model (``core/db.py``).

This is the "batteries-included" backend so the repo runs for anyone who clones
it, and it doubles as a worked example: to integrate a real system, copy one of
these classes, implement the same interface against your API, and register it
(see docs/EXTENDING.md). The agent code never changes.

Selected by default (``SENTINEL_<DOMAIN>_ADAPTER`` unset, or ``=local``).
"""
from __future__ import annotations
from datetime import datetime, timedelta

from ...db import get_conn
from ..base import (InventoryService, WorkforceService, SchedulingService,
                    CmmsService, NotificationService, GovernanceService,
                    MonitoringService)
from ..registry import register


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
class LocalInventoryAdapter(InventoryService):
    def check_parts(self, equipment_id: str) -> dict:
        with get_conn() as c:
            rows = c.execute(
                """SELECT p.part_id, p.part_number, p.description, p.on_hand_qty,
                          p.lead_time_days, ep.qty_per_service, ep.is_critical_spare
                     FROM equipment_part ep JOIN part p ON p.part_id = ep.part_id
                    WHERE ep.equipment_id = ?
                    ORDER BY ep.is_critical_spare DESC""", (equipment_id,)).fetchall()
        parts = [dict(r) for r in rows]
        critical = [p for p in parts if p["is_critical_spare"]]
        critical_available = (all(p["on_hand_qty"] >= p["qty_per_service"] for p in critical)
                              if critical else True)
        key = critical[0] if critical else (parts[0] if parts else None)
        if key:
            short = key["on_hand_qty"] < key["qty_per_service"]
            summary = (f"{key['part_number']} ({key['description']}): {key['on_hand_qty']} on hand"
                       + (f" — SHORT, {key['lead_time_days']}d lead time" if short else " — in stock"))
        else:
            summary = "No bill-of-materials found."
        return {"parts": parts, "critical_available": critical_available, "summary": summary}


# ---------------------------------------------------------------------------
# Workforce
# ---------------------------------------------------------------------------
_ROTATING_CLASSES = {"COMPRESSOR", "PUMP", "GRINDER"}


class LocalWorkforceAdapter(WorkforceService):
    def assign_technician(self, equipment_class: str, current_shift: str = "A") -> dict:
        with get_conn() as c:
            rows = c.execute("SELECT * FROM technician WHERE available=1").fetchall()
        best, best_score, considered = None, -1, 0
        for r in rows:
            considered += 1
            skills = (r["skills"] or "").upper().split(",")
            score = 0
            if equipment_class in skills:
                score += 3
            if equipment_class in _ROTATING_CLASSES and "ROTATING" in skills:
                score += 2
            if r["shift"] == current_shift:
                score += 1
            if score > best_score:
                best, best_score = r, score
        if not best or best_score <= 0:
            return {"technician": None,
                    "reason": f"No available technician certified on {equipment_class}.",
                    "candidates_considered": considered}
        reason = (f"{best['full_name']} ({best['job_title']}) is certified on {equipment_class} "
                  f"and available on shift {best['shift']}. Selected from {considered} available technicians.")
        return {"technician": dict(best), "reason": reason, "candidates_considered": considered}


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
class LocalSchedulingAdapter(SchedulingService):
    def block_schedule(self, equipment_id: str, window_min: int = 45) -> dict:
        start = datetime.now() + timedelta(hours=2)  # next planned micro-stop
        end = start + timedelta(minutes=window_min)
        return {
            "equipment_id": equipment_id,
            "window": f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}",
            "window_min": window_min,
            "note": (f"Reserve a {window_min}-min planned stop at the next shift changeover so "
                     f"the repair avoids an in-process line-down."),
        }


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
class LocalNotificationAdapter(NotificationService):
    failure_is_definitive = True  # each SQLite send is one atomic transaction

    def raise_alert(self, *, equipment_id: str, severity: str,
                    summary: str, source: str = "agent") -> dict:
        now = datetime.now().isoformat(timespec="seconds")
        with get_conn() as c:
            cur = c.execute(
                """INSERT INTO alert (equipment_id, severity, summary, source, status, raised_at)
                   VALUES (?,?,?,?,?,?)""",
                (equipment_id, severity, summary, source, "OPEN", now))
            alert_id = cur.lastrowid
        return {"alert_id": alert_id, "equipment_id": equipment_id, "severity": severity,
                "status": "OPEN", "summary": summary}

    def notify(self, *, recipient_id, subject: str, body: str,
               channel: str = "sms", send: bool = True, wo_id=None,
               authorization=None) -> dict:
        preview = f"[{channel}] -> {recipient_id or 'unassigned'}: {subject}"
        if not send:
            return {"notification_id": None, "recipient_id": recipient_id, "channel": channel,
                    "subject": subject, "status": "DRAFT", "preview": preview}
        from ...reliability.execution import require_execution_authorization
        require_execution_authorization(authorization, capability="notification dispatch")
        with get_conn() as c:
            nid = self._insert(c, recipient_id, channel, subject, body, wo_id)
        return {"notification_id": nid, "recipient_id": recipient_id, "channel": channel,
                "subject": subject, "status": "SENT", "preview": preview}

    @staticmethod
    def _insert(c, recipient_id, channel, subject, body, wo_id) -> int:
        """Insert a SENT notification on an existing connection ``c`` — lets a
        composite write (e.g. a work package) record the dispatch inside the same
        atomic transaction instead of opening a second, self-locking connection."""
        now = datetime.now().isoformat(timespec="seconds")
        cur = c.execute(
            """INSERT INTO notification
               (recipient_id, channel, subject, body, status, wo_id, sent_at)
               VALUES (?,?,?,?,?,?,?)""",
            (recipient_id, channel, subject, body, "SENT", wo_id, now))
        return cur.lastrowid


# ---------------------------------------------------------------------------
# CMMS — work-order authoring + governed write-back + work package
# ---------------------------------------------------------------------------
class LocalCmmsAdapter(CmmsService):
    failure_is_definitive = True  # work-package assembly is one SQLite transaction

    def propose_work_order(self, equipment_id, failure_mode_id, technician_id,
                           detail, priority="HIGH") -> dict:
        return {
            "equipment_id": equipment_id, "failure_mode_id": failure_mode_id,
            "technician_id": technician_id, "priority": priority, "detail": detail,
            "status": "DRAFT", "wo_number": "WO-US01-DRAFT",
        }

    # -- minimal governed write-back (WO + maintenance event) --------------
    def commit_work_order(self, proposal: dict, *, authorization=None) -> dict:
        from ...reliability.execution import require_execution_authorization
        require_execution_authorization(authorization, capability="CMMS work-order commit")
        a = proposal["actions"]
        eid = proposal["equipment_id"]
        fm = proposal["failure_mode"]["failure_mode_id"]
        tech = a["technician"]["technician_id"] if a.get("technician") else None
        now = datetime.now().isoformat(timespec="seconds")
        with get_conn() as c:
            wo_id, wo_number = self._insert_work_order(c, eid, fm, tech, a, now, proposal)
        return {"wo_id": wo_id, "wo_number": wo_number, "status": "OPEN"}

    # -- full repair work package (WO + parts + labor + schedule + notify) --
    def create_work_package(self, proposal: dict, *, authorization=None) -> dict:
        from ...reliability.execution import require_execution_authorization
        from ...reliability.resources import (require_no_booking_conflict, require_part_stock,
                                              require_qualified_technician)
        require_execution_authorization(authorization, capability="CMMS work-package commit")
        a = proposal["actions"]
        eid = proposal["equipment_id"]
        fm = proposal["failure_mode"]["failure_mode_id"]
        tech_rec = a.get("technician") or None
        tech = tech_rec["technician_id"] if tech_rec else None
        sched = a.get("schedule", {})
        critical = [(p, int(p.get("qty_per_service", 1) or 1))
                    for p in a.get("parts", {}).get("parts", []) if p.get("is_critical_spare")]
        now = datetime.now().isoformat(timespec="seconds")

        with get_conn() as c:
            # BEGIN IMMEDIATE takes the write lock before the availability reads, so
            # the revalidation below and the reservations/booking that depend on it
            # are one serialized unit: two packages can never both pass on the same
            # last unit of stock or the same technician window. Earlier validation
            # (promotion, governance) is deliberately not trusted here. Any failure
            # raises before a single consequential row exists and get_conn rolls
            # back, so the failure is definitive for the caller.
            c.execute("BEGIN IMMEDIATE")
            for p, qty in critical:
                require_part_stock(c, p["part_id"], qty)
            if tech:
                require_qualified_technician(c, eid, tech)
                # Limitation: only dated start/end window labels prove an overlap;
                # see require_no_booking_conflict.
                require_no_booking_conflict(c, tech, sched.get("window"))

            wo_id, wo_number = self._insert_work_order(c, eid, fm, tech, a, now, proposal)

            # 1. reserve the critical spares from the asset's bill-of-materials
            reserved = []
            for p, qty in critical:
                c.execute(
                    """INSERT INTO part_reservation (wo_id, part_id, qty, status, reserved_at)
                       VALUES (?,?,?,?,?)""", (wo_id, p["part_id"], qty, "RESERVED", now))
                reserved.append({"part_number": p.get("part_number"), "qty": qty})

            # 2. book the assigned technician into the planned window
            booking = None
            if tech:
                c.execute(
                    """INSERT INTO labor_booking
                       (wo_id, technician_id, window_label, window_min, status, booked_at)
                       VALUES (?,?,?,?,?,?)""",
                    (wo_id, tech, sched.get("window"), sched.get("window_min"), "BOOKED", now))
                booking = {"technician_id": tech, "window": sched.get("window"),
                           "window_min": sched.get("window_min")}

            # 3. dispatch a notification to the assigned technician (same txn)
            subject = f"Dispatch {wo_number} · {eid}"
            body = (f"Repair work package {wo_number} for {eid}. "
                    f"Window {sched.get('window', 'TBD')}. {a.get('work_order', {}).get('detail', '')}")
            preview = f"[sms] -> {tech or 'unassigned'}: {subject}"
            if tech:
                nid = LocalNotificationAdapter._insert(c, tech, "sms", subject, body, wo_id)
                notif = {"notification_id": nid, "recipient_id": tech, "channel": "sms",
                         "subject": subject, "status": "SENT", "preview": preview}
            else:
                notif = {"notification_id": None, "recipient_id": None, "channel": "sms",
                         "subject": subject, "status": "SKIPPED", "preview": preview}

            # 4. link everything under a package header
            cur = c.execute(
                """INSERT INTO work_package (package_number, wo_id, equipment_id, status, created_at)
                   VALUES (?,?,?,?,?)""", ("PKG-PENDING", wo_id, eid, "READY", now))
            package_id = cur.lastrowid
            package_number = f"PKG-US01-{package_id:05d}"
            c.execute("UPDATE work_package SET package_number=? WHERE package_id=?",
                      (package_number, package_id))

        return {"wo_id": wo_id, "wo_number": wo_number, "package_number": package_number,
                "status": "READY", "reserved_parts": reserved, "labor_booking": booking,
                "notification": notif}

    # -- shared work-order insert -----------------------------------------
    @staticmethod
    def _insert_work_order(c, eid, fm, tech, actions, now, proposal):
        cur = c.execute(
            """INSERT INTO work_order
               (wo_number, equipment_id, failure_mode_id, technician_id, status, priority, created_at, detail)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("PENDING", eid, fm, tech, "OPEN", actions["work_order"]["priority"], now,
             actions["work_order"]["detail"]))
        wo_id = cur.lastrowid
        wo_number = f"WO-US01-{wo_id:05d}"
        c.execute("UPDATE work_order SET wo_number=? WHERE wo_id=?", (wo_number, wo_id))
        c.execute(
            """INSERT INTO maintenance_event
               (equipment_id, failure_mode_id, wo_id, event_type, created_at, note)
               VALUES (?,?,?,?,?,?)""",
            (eid, fm, wo_id, "PREDICTIVE", now,
             f"Auto-raised by maintenance agent from failure_prob="
             f"{proposal['prediction']['failure_prob']:.2f}."))
        return wo_id, wo_number


# ---------------------------------------------------------------------------
# Governance — a deterministic policy engine (also the local Governance peer)
# ---------------------------------------------------------------------------
class LocalGovernanceAdapter(GovernanceService):
    POLICY_VERSION = "gov-policy-1"

    def review_plan(self, proposal: dict) -> dict:
        from ...config import GOVERNANCE_AUTO_APPROVE_LIMIT
        a = proposal.get("actions", {}) or {}
        business = proposal.get("business", {}) or {}
        reasons: list[str] = []
        conditions: list[str] = []
        decision = "APPROVE"

        # 1. a certified technician must be assigned
        if not a.get("technician"):
            decision = "VETO"
            reasons.append("No certified technician is available for this asset class.")

        # 2. critical spares must be on hand
        parts = a.get("parts", {}) or {}
        if parts and not parts.get("critical_available", True):
            conditions.append("Expedite the short critical spare and confirm it is on hand "
                              "before dispatch.")
            reasons.append("A critical spare is below the required quantity.")

        # 3. financial exposure vs delegated auto-approval authority
        exposure = float(business.get("unplanned_loss") or business.get("recovered_value") or 0)
        if exposure > GOVERNANCE_AUTO_APPROVE_LIMIT:
            conditions.append(f"Exposure ${exposure:,.0f} exceeds the "
                              f"${GOVERNANCE_AUTO_APPROVE_LIMIT:,.0f} auto-approval authority — "
                              f"maintenance-manager co-sign required.")
            reasons.append("Financial exposure above delegated authority.")

        # 4. the prediction must justify pre-emptive spend
        prob = float((proposal.get("prediction") or {}).get("failure_prob") or 0)
        if prob < 0.80:
            conditions.append("Failure probability is below the 80% action threshold — "
                              "re-confirm before committing spend.")
        else:
            reasons.append(f"Failure probability {prob:.0%} justifies pre-emptive action.")

        if decision != "VETO" and conditions:
            decision = "CONDITIONS"
        if decision == "APPROVE":
            reasons.append("Within policy — parts, labor and window are all in order.")
        return {"decision": decision, "reasons": reasons, "conditions": conditions,
                "policy_version": self.POLICY_VERSION}


# ---------------------------------------------------------------------------
# Monitoring — a deterministic correlation engine (also the local Monitoring peer)
# ---------------------------------------------------------------------------
class LocalMonitoringAdapter(MonitoringService):
    def assess(self, snapshot: dict) -> dict:
        alerts = snapshot.get("alerts", []) or []
        by_class: dict[str, list] = {}
        by_mode: dict[str, list] = {}
        for al in alerts:
            cls = al.get("equipment_class")
            if cls:
                by_class.setdefault(cls, []).append(al.get("equipment_id"))
            mode = al.get("predicted_mode")
            if mode and mode != "NONE":
                by_mode.setdefault(mode, []).append(al.get("equipment_id"))

        correlations = []
        for cls, ids in by_class.items():
            if len(ids) >= 2:
                correlations.append({"pattern": "same-equipment-class", "equipment_ids": ids,
                    "note": f"{len(ids)} {cls} assets alerting together — possible common-cause "
                            f"(utility, ambient, or batch) issue."})
        for mode, ids in by_mode.items():
            if len(ids) >= 2:
                correlations.append({"pattern": "same-failure-mode", "equipment_ids": ids,
                    "note": f"{len(ids)} assets trending to {mode} — a systemic failure mode, "
                            f"not isolated wear."})

        escalate = bool(correlations)
        rationale = (("Systemic pattern detected. " + " ".join(c["note"] for c in correlations)
                      + " Recommend a fleet-level review.")
                     if escalate else "Alerts appear independent; no systemic pattern.")
        return {"escalate": escalate, "correlations": correlations, "rationale": rationale}


# ---------------------------------------------------------------------------
# Register the reference adapters under the name "local" (the default).
# ---------------------------------------------------------------------------
register("inventory", "local", LocalInventoryAdapter)
register("workforce", "local", LocalWorkforceAdapter)
register("scheduling", "local", LocalSchedulingAdapter)
register("cmms", "local", LocalCmmsAdapter)
register("notifications", "local", LocalNotificationAdapter)
register("governance", "local", LocalGovernanceAdapter)
register("monitoring", "local", LocalMonitoringAdapter)
