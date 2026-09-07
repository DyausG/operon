"""Governance (policy) + Monitoring (correlation) peer logic — local adapters."""
from __future__ import annotations

from core.services.adapters.local import LocalGovernanceAdapter, LocalMonitoringAdapter

GOV = LocalGovernanceAdapter()
MON = LocalMonitoringAdapter()


def _proposal(*, tech=True, critical_ok=True, exposure=50_000, prob=0.91):
    return {
        "prediction": {"failure_prob": prob},
        "business": {"unplanned_loss": exposure},
        "actions": {
            "technician": {"technician_id": "TECH-201"} if tech else None,
            "parts": {"critical_available": critical_ok},
        },
    }


def test_governance_approve_clean_plan():
    v = GOV.review_plan(_proposal())
    assert v["decision"] == "APPROVE"
    assert v["policy_version"] == "gov-policy-1"


def test_governance_veto_without_technician():
    v = GOV.review_plan(_proposal(tech=False))
    assert v["decision"] == "VETO"
    assert any("technician" in r.lower() for r in v["reasons"])


def test_governance_conditions_on_short_spare():
    v = GOV.review_plan(_proposal(critical_ok=False))
    assert v["decision"] == "CONDITIONS"
    assert any("spare" in c.lower() for c in v["conditions"])


def test_governance_conditions_on_exposure_over_authority():
    v = GOV.review_plan(_proposal(exposure=500_000))
    assert v["decision"] == "CONDITIONS"
    assert any("co-sign" in c.lower() or "authority" in c.lower() for c in v["conditions"])


def test_governance_veto_beats_conditions():
    # no technician (veto) AND short spare (condition) -> still VETO
    v = GOV.review_plan(_proposal(tech=False, critical_ok=False))
    assert v["decision"] == "VETO"


def _alerts(*specs):
    return {"alerts": [{"equipment_id": e, "equipment_class": c, "predicted_mode": m,
                        "failure_prob": 0.9, "criticality": "HIGH"} for e, c, m in specs]}


def test_monitoring_no_escalation_for_single_alert():
    a = MON.assess(_alerts(("AC-COMP-01", "COMPRESSOR", "OSF")))
    assert a["escalate"] is False and a["correlations"] == []


def test_monitoring_escalates_same_class():
    a = MON.assess(_alerts(("HYD-PUMP-03", "PUMP", "HDF"), ("COOL-PMP-09", "PUMP", "PWF")))
    assert a["escalate"] is True
    assert any(c["pattern"] == "same-equipment-class" for c in a["correlations"])


def test_monitoring_escalates_same_failure_mode():
    a = MON.assess(_alerts(("CNC-MILL-07", "CNC_MACHINE", "TWF"), ("GRIND-04", "GRINDER", "TWF")))
    assert a["escalate"] is True
    assert any(c["pattern"] == "same-failure-mode" for c in a["correlations"])
