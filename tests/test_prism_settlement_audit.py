"""F1.1: PRISM's audit record states the action it actually applied, separately from the classification.

Each case runs the real fenced-apply settlement against a real repository and then checks the
recorded audit fields against the incident's actual phase, artifacts and events.
"""
from __future__ import annotations

import pytest

from core.prism.operon import OperonSlowPathAdapter
from core.reliability import models as m
from tests.test_promotion import result_payload
from tests.test_reliability_lifecycle import Flow

REVISION = 3  # the PRISM session revision the candidate belongs to (audit text only)


@pytest.fixture
def flow(seeded_db):
    return Flow()


def adapter(flow):
    return OperonSlowPathAdapter(incident_repository=flow.repo, backend_factory=lambda: None,
                                 lifecycle=flow.lifecycle, promotion=flow.service)


def report_for(flow, change=None, edit=None):
    snapshot = flow.start()
    payload = result_payload(flow, snapshot) | (change or {})
    if edit:
        edit(payload)
    return flow.complete(snapshot, payload)


def settle(flow, report):
    with flow.repo._write() as conn:
        return adapter(flow)._settle(conn, flow.incident_id, report, REVISION)


def lifecycle_actions(flow):
    """Retry bookkeeping, escalation and runs that a settlement could have caused."""
    events = flow.repo.list_events(flow.incident_id)
    return {"analysis_events": [e.event_type for e in events if e.event_type.startswith("ANALYSIS_")],
            "escalations": [e for e in events if e.event_type == "INCIDENT_ESCALATED"],
            "snapshots": len(flow.kinds(m.SupervisorRunSnapshot))}


def test_promotion_is_recorded_as_promoted(flow):
    flow.confirm()
    record = settle(flow, report_for(flow))
    incident = flow.incident()
    assert record["audit_version"] == 2 and record["disposition"] == "PROMOTED"
    assert record["classification"]["disposition"] == "PROMOTE" and record["classification"]["code"] == "ADVISORY_CONCLUSION"
    assert incident.phase == m.IncidentPhase.DIAGNOSIS_VALIDATED == m.IncidentPhase(record["incident_phase"])
    promotion = next(p for p in flow.kinds(m.PromotionRecord) if p.stage == "diagnosis")
    assert record["promotion_id"] == promotion.id and incident.current_diagnosis_id == promotion.target_id


def test_evidence_parking_is_recorded_as_needs_evidence_and_really_parks(flow):
    record = settle(flow, report_for(flow))  # no trusted confirmation exists
    assert record["disposition"] == "NEEDS_EVIDENCE" and record["incident_phase"] == "AWAITING_EVIDENCE"
    assert (record["classification"]["category"], record["classification"]["code"]) == ("EVIDENCE", "CONFIRMATION_REQUIRED")
    assert flow.incident().phase == m.IncidentPhase.AWAITING_EVIDENCE
    registered = [e for e in flow.repo.list_events(flow.incident_id) if e.event_type == "HYPOTHESES_REGISTERED"]
    assert registered and registered[-1].payload["recommended"] == "HYP-001"
    assert set(flow.service.current_hypotheses(flow.incident_id)) == {"HYP-001", "HYP-002"}


def test_technical_failure_is_classified_retry_but_nothing_is_scheduled_or_counted(flow):
    report = report_for(flow, {"termination_reason": "TIMEOUT"})
    before = lifecycle_actions(flow)
    record = settle(flow, report)
    assert record["disposition"] == "NOT_APPLIED"
    assert (record["classification"]["disposition"], record["classification"]["category"],
            record["classification"]["code"]) == ("RETRY", "TECHNICAL", "TIMEOUT")
    assert "scheduled no retry" in record["reason"] and "retry budget" in record["reason"]
    incident = flow.incident()
    assert incident.phase == m.IncidentPhase.INVESTIGATING and incident.analysis is None
    assert lifecycle_actions(flow) == before  # no ANALYSIS_* event, no escalation, no new run


def test_escalation_is_classified_but_the_case_is_not_escalated(flow):
    report = report_for(flow, {"disposition": "ESCALATED", "decision": None, "blockers": ["Unsafe isolation"]})
    before = lifecycle_actions(flow)
    record = settle(flow, report)
    assert record["disposition"] == "NOT_APPLIED"
    assert (record["classification"]["disposition"], record["classification"]["category"]) == ("ESCALATED", "ESCALATION")
    assert "never escalates" in record["reason"]
    assert flow.incident().phase == m.IncidentPhase.INVESTIGATING and lifecycle_actions(flow) == before


def test_unresolved_incomplete_review_is_not_applied(flow):
    def no_review_of_the_diagnostic(payload):
        payload["assessments"][1]["assessment"]["subject_id"] = "plan"
    report = report_for(flow, {"disposition": "UNRESOLVED"}, no_review_of_the_diagnostic)
    before = lifecycle_actions(flow)
    record = settle(flow, report)
    assert record["disposition"] == "NOT_APPLIED"
    assert (record["classification"]["category"], record["classification"]["code"]) == ("TECHNICAL", "INCOMPLETE_REVIEW")
    assert flow.incident().phase == m.IncidentPhase.INVESTIGATING and lifecycle_actions(flow) == before


def test_gate_refusal_is_unresolved_and_not_applied(flow):
    flow.confirm()

    def drop_reference(payload):
        payload["assessments"][0]["assessment"]["competing_hypotheses"][0]["hypothesis_ref"] = None
    report = report_for(flow, edit=drop_reference)
    before = lifecycle_actions(flow)
    record = settle(flow, report)
    assert record["disposition"] == "NOT_APPLIED" and record["promotion_id"] is None
    assert (record["classification"]["disposition"], record["classification"]["code"]) == ("RETRY", "HYPOTHESIS_REF_MISSING")
    assert not flow.kinds(m.Diagnosis) and flow.incident().phase == m.IncidentPhase.INVESTIGATING
    assert flow.incident().analysis is None and lifecycle_actions(flow) == before


def test_stale_candidate_is_history_only_and_not_applied(flow):
    first = flow.start()
    flow.start()  # a newer run supersedes the first while it reasons
    report = flow.complete(first, result_payload(flow, first))
    assert report.stale_reasons
    with flow.repo._write() as conn:
        record = adapter(flow)._stale_settlement(conn, flow.incident_id, report, REVISION)
    assert record["disposition"] == "NOT_APPLIED"
    assert (record["classification"]["code"], record["classification"]["disposition"]) == ("STALE_INPUTS", "RETRY")
    assert "did not reason again" in record["reason"] and flow.incident().phase == m.IncidentPhase.INVESTIGATING
