"""
LLM-backed peer adapters — Governance and Monitoring reasoning powered by Google
Gemini, with an automatic **deterministic fallback**.

These are the DEFAULT for the governance/monitoring domains: when a Gemini key is
present they reason with the LLM; when it isn't (offline, CI), or a call is
rate-limited past its retries, or the reply can't be parsed, they transparently
fall back to the deterministic engines in ``local.py``. So selecting ``llm`` is
always safe — it never breaks the loop, it just uses the best available brain.

The Gemini client + rate limiter + backoff are shared with the main agent
(``core/gemini.py``), so the whole app respects one free-tier budget. To pin the
deterministic engines regardless of key, set ``SENTINEL_GOVERNANCE_ADAPTER=local``
/ ``SENTINEL_MONITORING_ADAPTER=local``.
"""
from __future__ import annotations
import json

from ... import config, gemini
from ..base import GovernanceService, MonitoringService
from ..registry import register
from .local import LocalGovernanceAdapter, LocalMonitoringAdapter


_GOV_SYSTEM = (
    "You are the Governance authority for an industrial maintenance operation. "
    "Rule on a proposed predictive-maintenance work package and return a policy "
    "decision. Apply this policy exactly:\n"
    " - VETO if no certified technician is assigned.\n"
    " - CONDITIONS if a critical spare is short (must be expedited), OR the "
    "financial exposure exceeds the stated auto-approval authority (manager "
    "co-sign required), OR the failure probability is below 0.80.\n"
    " - Otherwise APPROVE.\n"
    "Ground every reason in the facts given — never invent parts, people, or "
    "numbers. Respond with ONLY a JSON object of the form "
    '{"decision": "APPROVE|CONDITIONS|VETO", "reasons": [str, ...], '
    '"conditions": [str, ...]}. Keep each string to one concise sentence.'
)

_MON_SYSTEM = (
    "You are the Monitoring analyst for an industrial plant. Given the currently "
    "active equipment alerts, decide whether they reveal a SYSTEMIC pattern "
    "(e.g. several assets of the same class, or several trending to the same "
    "failure mode — a common-cause or fleet-wide issue) that warrants escalation "
    "beyond handling each alert individually. Ground everything in the alerts "
    "given. Respond with ONLY a JSON object of the form "
    '{"escalate": bool, "correlations": [{"pattern": str, "equipment_ids": '
    '[str, ...], "note": str}], "rationale": str}.'
)


class LLMGovernanceAdapter(GovernanceService):
    POLICY_VERSION = "gov-llm-1"

    def __init__(self):
        self._fallback = LocalGovernanceAdapter()

    def review_plan(self, proposal: dict) -> dict:
        if not config.gemini_available():
            return self._fallback.review_plan(proposal)
        try:
            a = proposal.get("actions", {}) or {}
            tech = a.get("technician") or None
            business = proposal.get("business", {}) or {}
            facts = {
                "equipment_id": proposal.get("equipment_id"),
                "criticality": proposal.get("criticality"),
                "failure_mode": (proposal.get("failure_mode") or {}).get("mode_code"),
                "failure_prob": (proposal.get("prediction") or {}).get("failure_prob"),
                "technician_assigned": bool(tech),
                "technician": (tech or {}).get("full_name"),
                "critical_spare_available": (a.get("parts") or {}).get("critical_available", True),
                "financial_exposure": business.get("unplanned_loss") or business.get("recovered_value"),
                "auto_approval_authority": config.GOVERNANCE_AUTO_APPROVE_LIMIT,
            }
            out = gemini.structured_json(_GOV_SYSTEM, json.dumps(facts))
            decision = str(out.get("decision", "")).upper()
            if decision not in ("APPROVE", "CONDITIONS", "VETO"):
                raise ValueError(f"bad decision {decision!r}")
            # hard safety rule: never let the model approve without a technician
            if not tech:
                decision = "VETO"
            return {"decision": decision,
                    "reasons": [str(r) for r in (out.get("reasons") or [])][:4],
                    "conditions": [str(c) for c in (out.get("conditions") or [])][:4],
                    "policy_version": self.POLICY_VERSION}
        except Exception:  # noqa: BLE001 — any failure degrades to deterministic policy
            return self._fallback.review_plan(proposal)


class LLMMonitoringAdapter(MonitoringService):
    def __init__(self):
        self._fallback = LocalMonitoringAdapter()
        self._cache: dict[frozenset, dict] = {}

    def assess(self, snapshot: dict) -> dict:
        alerts = snapshot.get("alerts", []) or []
        # Nothing to correlate with < 2 alerts — skip the LLM (and its quota).
        if len(alerts) < 2 or not config.gemini_available():
            return self._fallback.assess(snapshot)
        key = frozenset(a.get("equipment_id") for a in alerts)
        if key in self._cache:              # same alert set — don't re-spend a call
            return self._cache[key]
        try:
            out = gemini.structured_json(_MON_SYSTEM, json.dumps({"alerts": alerts}))
            result = {
                "escalate": bool(out.get("escalate")),
                "correlations": out.get("correlations") or [],
                "rationale": str(out.get("rationale", "")).strip()
                             or "No systemic pattern identified.",
            }
            self._cache[key] = result
            return result
        except Exception:  # noqa: BLE001
            return self._fallback.assess(snapshot)


register("governance", "llm", LLMGovernanceAdapter)
register("monitoring", "llm", LLMMonitoringAdapter)
