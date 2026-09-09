"""Independent specialists exercise real SDK loops with only the model scripted."""
import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from core import db
from core.agents.contracts import (
    AdvisoryInput, CriticAssessment, DiagnosticAssessment, EngineeringAssessment,
    MaintenancePlanAssessment, OperationsAssessment, SpecialistContext,
)
from core.agents.diagnostic import assess_diagnosis
from core.agents.engineering import assess_engineering
from core.agents.operations import assess_operations
from core.agents.critic import review_assessment
from core.agents.planner import plan_maintenance
from core.agents.invocation import SpecialistInvocationError
from core.agents.runtime import StrandsRuntime
from core.agents.tools import SPECIALIST_TOOL_NAMES, RESOURCE_TOOL_NAMES
from core.reliability import models as m
from core.reliability.assessments import prepare_specialist_context
from core.reliability.repository import InvalidReference, new_id, utcnow
from core.reliability.resources import ResourceCapabilities
from tests.test_strands_agents import ScriptedModel, protected_state, report, scoped, settings

SPECIALISTS = [
    ('diagnostic', assess_diagnosis, DiagnosticAssessment),
    ('engineering', assess_engineering, EngineeringAssessment),
    ('operations', assess_operations, OperationsAssessment),
    ('critic', review_assessment, CriticAssessment),
    ('planner', plan_maintenance, MaintenancePlanAssessment),
]


def packet(scoped):
    repo, service, base = scoped
    advice = AdvisoryInput(key='diagnostic-input', assessment=DiagnosticAssessment.model_validate(
        report(base.incident_id, (base.evidence[0].id,))))
    context = prepare_specialist_context(
        repo, base.incident_id, asset_id=base.asset_id, run_id=base.run_id,
        evidence_ids=tuple(item.id for item in base.evidence), advisory_inputs=(advice,),
    )
    return repo, service, context


def payload(role, context):
    common = dict(incident_id=context.incident_id, evidence_reviewed=[context.evidence[0].id],
                  reasoning_summary='Available context leaves uncertainty; only inspection is supported.',
                  uncertainties=['Cause and operating limits remain unconfirmed.'],
                  input_assessment_keys=['diagnostic-input'])
    if role == 'diagnostic':
        result = report(context.incident_id, (context.evidence[0].id,))
        result['competing_hypotheses'].append(dict(
            key='sensor-fault', mechanism='Measurement error is an alternative explanation',
            supporting_evidence_ids=[], contradicting_evidence_ids=[context.evidence[0].id],
            confidence=0.1, falsification_tests=['Compare an independent measurement']))
        return result
    if role == 'engineering':
        return common | dict(diagnosis_id=None, constraints_considered=[], missing_constraints=['OEM operating limits'],
            intervention_feasibility='UNKNOWN', blockers=['Applicable constraints absent'],
            safety_concerns=['Isolation needs review'], recommended_intervention_elements=['Propose inspection'])
    if role == 'operations':
        return common | dict(intervention_id=None, resource_feasibility='UNKNOWN', inventory_observations=[],
            workforce_observations=[], scheduling_observations=['No confirmed production window'],
            blockers=['Calendar unavailable'], operational_recommendations=['Coordinate a confirmed window'])
    if role == 'critic':
        return common | dict(subject_id='diagnostic-input', subject_kind='assessment',
            evidence_gaps=['Independent inspection missing'], contradictions=[],
            unsupported_claims=['Predictive risk is not a confirmed diagnosis'], recommendation='NEEDS_EVIDENCE',
            requested_additional_evidence=[dict(capability='inspection', question='Check the suspected component')])
    return common | dict(validated_input_ids=[], proposed_steps=[
        dict(description='Propose inspection after isolation review', equipment_ids=[context.asset_id],
             evidence_ids=[context.evidence[0].id], preconditions=['Application safety review'],
             verification_criteria=['Record actual component condition']),
        dict(description='Reassess maintenance need using inspection findings', equipment_ids=[context.asset_id],
             evidence_ids=[], depends_on=[0], preconditions=['Inspection evidence available'],
             verification_criteria=['Record unresolved blockers']),
    ], estimated_exposure=None, exposure_currency=None, exposure_assumptions=['Cost and downtime unavailable'],
       reversible=None, safety_relevant=True, external_commitment=None,
       approval_considerations=['Application must determine approvals'], unresolved_blockers=['Inspection pending'],
       expected_operational_exposure=['Production effects require calendar review'])


@pytest.mark.parametrize('role,invoke,contract', SPECIALISTS)
async def test_native_specialists_allowlists_and_no_authoritative_effect(scoped, monkeypatch, role, invoke, contract):
    repo, service, context = packet(scoped)
    before = protected_state(repo, context.incident_id)
    incident_before = repo.fetch_incident(context.incident_id)
    events_before = repo.list_events(context.incident_id)
    reads = sorted(SPECIALIST_TOOL_NAMES[role] - {'request_evidence'})
    forbidden = ['commit_actions', 'transition', 'add_artifact', 'create_work_package', 'notify',
                 'reserve_inventory', 'assign_technician', 'block_schedule', 'approve', 'execute_governed_intervention']

    def final(messages):
        results = [block['toolResult'] for block in messages[-1]['content']]
        assert all(item['status'] == 'success' for item in results[:len(reads)]), results
        assert all(item['status'] == 'error' for item in results[len(reads):])
        assert all('Unknown tool' in json.dumps(item) for item in results[len(reads):])
        return [(contract.__name__, payload(role, context))]

    model = ScriptedModel([[(name, {}) for name in reads + forbidden], final])
    runtime = StrandsRuntime(settings(), model=model)
    factory = Mock(wraps=runtime.create_agent)
    monkeypatch.setattr(runtime, 'create_agent', factory)
    result = await invoke(runtime, service, context)
    assert isinstance(result, contract) and not isinstance(result, m.Artifact)
    factory.assert_called_once()
    assert factory.call_args.kwargs['name'] == f'operon_{role}'
    assert factory.call_args.kwargs['output_model'] is contract
    assert {item['name'] for item in model.calls[0]['tools']} == SPECIALIST_TOOL_NAMES[role] | {contract.__name__}
    assert protected_state(repo, context.incident_id) == before
    assert repo.fetch_incident(context.incident_id) == incident_before
    assert repo.list_events(context.incident_id) == events_before
    with pytest.raises(ValueError, match='unsupported artifact type'):
        repo.add_artifact(result, expected_revision=incident_before.revision)
    assert not any(isinstance(item, (m.Diagnosis, m.Intervention, m.Outcome, m.ValidationVerdict,
                                     m.ApprovalRequirement)) for item in repo.list_artifacts(context.incident_id))
    with db.get_conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM execution_claim').fetchone()[0] == 0


@pytest.mark.parametrize('role,invoke,contract', SPECIALISTS)
async def test_malformed_native_output_fails_safely(scoped, role, invoke, contract):
    repo, service, context = packet(scoped)
    before = protected_state(repo, context.incident_id)
    model = ScriptedModel([[(contract.__name__, {'incident_id': context.incident_id})]])
    with pytest.raises(SpecialistInvocationError, match='limit_turns'):
        await invoke(StrandsRuntime(settings(max_turns=1), model=model), service, context)
    assert protected_state(repo, context.incident_id) == before


@pytest.mark.parametrize('role,invoke,contract', SPECIALISTS)
@pytest.mark.parametrize('foreign_incident', [False, True])
async def test_cross_incident_outputs_rejected(scoped, role, invoke, contract, foreign_incident):
    repo, service, context = packet(scoped)
    other = repo.create_incident((context.asset_id,), admission_key='other-same-asset')
    collection = service.request_and_collect(other.id, requested_by='diagnostic',
        equipment_ids=(context.asset_id,), question='Other incident', capability='get_asset_context', required_for='diagnosis')
    data = payload(role, context)
    if foreign_incident:
        data['incident_id'] = other.id
    else:
        data['evidence_reviewed'].append(collection.evidence.id)
    model = ScriptedModel([[(contract.__name__, data)]])
    before = protected_state(repo, context.incident_id)
    with pytest.raises(InvalidReference):
        await invoke(StrandsRuntime(settings(), model=model), service, context)
    assert protected_state(repo, context.incident_id) == before


@pytest.mark.parametrize('role,invoke,contract', SPECIALISTS)
async def test_fabricated_snapshot_rejected_before_model_call(scoped, role, invoke, contract):
    _, service, context = packet(scoped)
    bad = context.model_copy(deep=True)
    bad.evidence[0].payload['fabricated_limit'] = 1000
    model = ScriptedModel()
    with pytest.raises(InvalidReference, match='differs from durable'):
        await invoke(StrandsRuntime(settings(), model=model), service, bad)
    assert model.calls == []


@pytest.mark.parametrize('purpose', ['diagnosis', 'intervention'])
async def test_critic_requests_durable_evidence_with_fixed_role(scoped, purpose):
    repo, service, context = packet(scoped)
    context = context.model_copy(update={'evidence_purpose': purpose})
    before = protected_state(repo, context.incident_id)
    def final(messages):
        result = messages[-1]['content'][0]['toolResult']
        assert result['status'] == 'success'
        collection = result['content'][0]['json']
        assert collection['request']['requested_by'] == 'critic'
        assert collection['request']['required_for'] == purpose
        evidence = repo.get_artifact(context.incident_id, collection['evidence']['id'])
        data = payload('critic', context)
        data['evidence_reviewed'].append(evidence.id)
        return [('CriticAssessment', data)]
    model = ScriptedModel([[('request_evidence', {'query': dict(
        capability='get_maintenance_history', question='Seek evidence against the suggested mechanism', parameters={'limit': 1})})], final])
    result = await review_assessment(StrandsRuntime(settings(), model=model), service, context)
    assert result.requested_additional_evidence
    assert protected_state(repo, context.incident_id) == before


@pytest.mark.parametrize('role,invoke,contract', SPECIALISTS[1:])
async def test_missing_required_subject_or_input_rejected(scoped, role, invoke, contract):
    _, service, context = packet(scoped)
    data = payload(role, context)
    data['input_assessment_keys'] = []
    with pytest.raises(InvalidReference):
        await invoke(StrandsRuntime(settings(), model=ScriptedModel([[(contract.__name__, data)]])), service, context)


def test_bounded_context_rejects_foreign_advice_and_artifacts(scoped):
    repo, _, context = packet(scoped)
    foreign = repo.create_incident(('HYD-PUMP-03',), admission_key='foreign')
    bad = AdvisoryInput(key='bad', assessment=DiagnosticAssessment.model_validate(report(foreign.id)))
    with pytest.raises(ValidationError, match='different incident'):
        prepare_specialist_context(repo, context.incident_id, asset_id=context.asset_id, run_id='run',
                                   evidence_ids=(), advisory_inputs=(bad,))
    with pytest.raises(InvalidReference):
        prepare_specialist_context(repo, context.incident_id, asset_id=context.asset_id, run_id='run',
                                   evidence_ids=(), artifact_ids=('invented',))
    oversized = context.model_dump()
    oversized['evidence'][0]['payload'] = {'large': 'x' * 64000}
    with pytest.raises(ValidationError, match='64000'):
        SpecialistContext.model_validate(oversized)


def test_resource_reads_distinguish_stock_roster_calendar_and_missing(scoped):
    repo, service, context = packet(scoped)
    reads = ResourceCapabilities(service.capabilities)
    before = protected_state(repo, context.incident_id)
    inventory = reads.check_part_availability(context.asset_id)
    assert inventory.availability == 'AVAILABLE' and inventory.parts
    assert all(part.sufficient_for_service for part in inventory.parts)
    assert reads.check_part_availability('missing').availability == 'UNKNOWN'
    workforce = reads.inspect_available_technicians(context.asset_id)
    assert workforce.availability == 'UNKNOWN' and workforce.technicians
    assert all('COMPRESSOR' in person.recorded_skills for person in workforce.technicians)
    assert reads.inspect_available_technicians('missing').availability == 'UNKNOWN'
    windows = reads.inspect_maintenance_windows(context.asset_id)
    assert windows.availability == 'UNKNOWN' and windows.confirmed_windows == ()
    history = service.capabilities.get_maintenance_history(context.asset_id)
    assert history.records[0].work_order_number == 'DEMO-HIST-WO-0001'
    assert protected_state(repo, context.incident_id) == before


def test_resource_conflicts_and_read_bounds(scoped):
    repo, service, context = packet(scoped)
    reads = ResourceCapabilities(service.capabilities)
    inventory = reads.check_part_availability(context.asset_id)
    part = inventory.parts[0]
    workforce = reads.inspect_available_technicians(context.asset_id)
    tech = workforce.technicians[0]
    with db.get_conn() as conn:
        wo_id = conn.execute('SELECT wo_id FROM work_order WHERE equipment_id=?', (context.asset_id,)).fetchone()[0]
        conn.execute("INSERT INTO part_reservation (wo_id,part_id,qty,status) VALUES (?,?,?,'RESERVED')",
                     (wo_id, part.part_id, part.on_hand_qty))
        conn.execute("INSERT INTO labor_booking (wo_id,technician_id,window_label,window_min,status) VALUES (?,?,'10:00-10:45',45,'BOOKED')", (wo_id, tech.technician_id))
    before = protected_state(repo, context.incident_id)
    assert reads.check_part_availability(context.asset_id).availability == 'UNAVAILABLE'
    assert any(t.active_booking_count == 1 for t in reads.inspect_available_technicians(context.asset_id).technicians)
    windows = reads.inspect_maintenance_windows(context.asset_id)
    assert windows.availability == 'UNKNOWN'
    assert windows.existing_bookings[0].work_order_id == wo_id
    for name in RESOURCE_TOOL_NAMES:
        with pytest.raises(ValidationError):
            getattr(reads, name)(context.asset_id, limit=51)
    assert protected_state(repo, context.incident_id) == before
    with db.get_conn() as conn:
        conn.execute('UPDATE technician SET available=0')
    assert reads.inspect_available_technicians(context.asset_id).availability == 'UNAVAILABLE'


@pytest.mark.parametrize('role,field,value', [
    ('engineering', 'intervention_feasibility', 'FEASIBLE'),
    ('critic', 'recommendation', 'ACCEPT'),
    ('planner', 'safety_relevant', 'false'),
    ('planner', 'estimated_exposure', 100),
])
def test_inconsistent_or_coerced_claims_rejected(scoped, role, field, value):
    _, _, context = packet(scoped)
    contract = next(contract for name, _, contract in SPECIALISTS if name == role)
    with pytest.raises(ValidationError):
        contract.model_validate(payload(role, context) | {field: value})


def test_planner_rejects_forward_dependencies_and_foreign_step_citations(scoped):
    _, _, context = packet(scoped)
    data = payload('planner', context)
    data['proposed_steps'][0]['depends_on'] = [1]
    with pytest.raises(ValidationError, match='preceding'):
        MaintenancePlanAssessment.model_validate(data)
    data = payload('planner', context)
    data['proposed_steps'][0]['evidence_ids'] = ['invented']
    with pytest.raises(ValidationError, match='citations'):
        MaintenancePlanAssessment.model_validate(data)


def domain_packet(scoped):
    """Application-created test artifacts; specialists never create these."""
    repo, service, context = packet(scoped)
    def persist(artifact):
        repo.add_artifact(artifact, expected_revision=repo.fetch_incident(context.incident_id).revision)
        return artifact
    def identity():
        return dict(id=new_id(), created_at=utcnow(), incident_id=context.incident_id)
    hypothesis = persist(m.Hypothesis(**identity(), equipment_ids=(context.asset_id,), mechanism='Test candidate',
        confidence=0.2, confidence_basis='Uncalibrated test hypothesis', falsification_tests=('Inspect',)))
    diagnosis = persist(m.Diagnosis(**identity(), equipment_ids=(context.asset_id,), hypothesis_ids=(hypothesis.id,),
        conclusion='Unconfirmed candidate', evidence_ids=(context.evidence[0].id,), confidence=0.2))
    intervention = persist(m.Intervention(**identity(), diagnosis_id=diagnosis.id, revision=1,
        steps=(m.InterventionStep(id=new_id(), created_at=utcnow(), capability='inspect',
            equipment_ids=(context.asset_id,), parameters={}),), risk='LOW', estimated_cost=0,
        estimated_downtime_minutes=0, estimated_avoided_loss=0, business_assumption_version='test-fixture'))
    context = prepare_specialist_context(repo, context.incident_id, asset_id=context.asset_id, run_id='domain-test',
        evidence_ids=(context.evidence[0].id,), artifact_ids=(diagnosis.id, intervention.id),
        advisory_inputs=context.advisory_inputs)
    return repo, service, context, diagnosis, intervention


@pytest.mark.parametrize('role,invoke,contract', SPECIALISTS[1:])
@pytest.mark.parametrize('reference', ['valid', 'foreign', 'wrong-type'])
async def test_durable_subject_references_are_scoped_and_typed(scoped, role, invoke, contract, reference):
    repo, service, context, diagnosis, intervention = domain_packet(scoped)
    other = repo.create_incident((context.asset_id,), admission_key='foreign-domain')
    foreign_hypothesis = m.Hypothesis(id=new_id(), created_at=utcnow(), incident_id=other.id,
        equipment_ids=(context.asset_id,), mechanism='Other hypothesis', confidence=0.1,
        confidence_basis='Test only', falsification_tests=())
    other = repo.add_artifact(foreign_hypothesis, expected_revision=other.revision)
    foreign_diagnosis = m.Diagnosis(id=new_id(), created_at=utcnow(), incident_id=other.id,
        equipment_ids=(context.asset_id,), hypothesis_ids=(foreign_hypothesis.id,),
        conclusion='Other candidate', evidence_ids=(), confidence=0.1)
    repo.add_artifact(foreign_diagnosis, expected_revision=other.revision)
    data = payload(role, context)
    data['input_assessment_keys'] = []
    key = intervention.id if role == 'operations' else diagnosis.id
    if reference == 'foreign':
        key = foreign_diagnosis.id
    elif reference == 'wrong-type':
        key = context.evidence[0].id
    if role == 'engineering':
        data['diagnosis_id'] = key
    elif role == 'operations':
        data['intervention_id'] = key
    elif role == 'critic':
        data.update(subject_kind='diagnosis', subject_id=key)
    else:
        data['validated_input_ids'] = [key]
    before = protected_state(repo, context.incident_id)
    invocation = invoke(StrandsRuntime(settings(), model=ScriptedModel([[(contract.__name__, data)]])), service, context)
    if reference == 'valid':
        assert isinstance(await invocation, contract)
    else:
        with pytest.raises(InvalidReference):
            await invocation
    assert protected_state(repo, context.incident_id) == before


async def test_unregistered_evidence_id_in_snapshot_is_rejected(scoped):
    _, service, context = packet(scoped)
    evidence = context.evidence[0].model_copy(update={'id': 'fabricated-evidence'})
    bad = context.model_copy(update={'evidence': (evidence,), 'advisory_inputs': ()})
    model = ScriptedModel()
    with pytest.raises(InvalidReference):
        await assess_diagnosis(StrandsRuntime(settings(), model=model), service, bad)
    assert not model.calls


async def test_diagnostic_signal_is_only_a_clue_and_competing_causes_remain_open(scoped):
    from tests.test_incident_state import signal
    repo, service, base = scoped
    incident, _ = repo.admit_signal(signal())
    context = prepare_specialist_context(repo, incident.id, asset_id=base.asset_id,
        run_id='signal-test', evidence_ids=incident.signal_evidence_ids)
    data = payload('diagnostic', context)
    model = ScriptedModel([ [('DiagnosticAssessment', data)] ])
    result = await assess_diagnosis(StrandsRuntime(settings(), model=model), service, context)
    assert len(result.competing_hypotheses) == 2
    assert result.recommended_hypothesis is None
    assert result.confidence != context.evidence[0].payload['risk_score']
    assert result.missing_evidence_requests
    assert not any(isinstance(item, m.Diagnosis) for item in repo.list_artifacts(incident.id))


@pytest.mark.parametrize('role,invoke,contract', [SPECIALISTS[2], SPECIALISTS[4]])
async def test_resource_reads_cannot_be_passed_off_as_durable_evidence(scoped, role, invoke, contract):
    _, service, context = packet(scoped)
    def final(messages):
        resource = messages[-1]['content'][0]['toolResult']['content'][0]['json']
        data = payload(role, context)
        data['evidence_reviewed'].append(resource['parts'][0]['part_id'])
        return [(contract.__name__, data)]
    model = ScriptedModel([[('check_part_availability', {})], final])
    with pytest.raises(InvalidReference, match='not supplied or collected'):
        await invoke(StrandsRuntime(settings(), model=model), service, context)


def test_engineering_can_express_each_feasibility_without_inventing_constraints(scoped):
    _, _, context = packet(scoped)
    data = payload('engineering', context)
    for feasibility in ('FEASIBLE', 'CONDITIONAL', 'UNKNOWN', 'INFEASIBLE', 'UNSAFE'):
        candidate = data | {'intervention_feasibility': feasibility}
        if feasibility == 'FEASIBLE':
            candidate.update(missing_constraints=[], blockers=[])
        result = EngineeringAssessment.model_validate(candidate)
        assert result.constraints_considered == ()


def test_resource_snapshot_unknown_values_and_overflow(scoped):
    _, service, context = packet(scoped)
    resources = ResourceCapabilities(service.capabilities)
    with db.get_conn() as conn:
        conn.execute("UPDATE part SET on_hand_qty=NULL WHERE part_id IN (SELECT part_id FROM equipment_part WHERE equipment_id=?)", (context.asset_id,))
    result = resources.check_part_availability(context.asset_id)
    assert result.availability == 'UNKNOWN'
    assert all(part.sufficient_for_service is None for part in result.parts)
    assert len(result.parts) > 1
    with pytest.raises(ValueError, match='exceeds requested limit'):
        resources.check_part_availability(context.asset_id, limit=1)


async def test_mismatched_application_store_fails_before_model_access(scoped, tmp_path):
    from core.reliability.evidence import EvidenceCapabilities, EvidenceService
    repo, _, context = packet(scoped)
    service = EvidenceService(repo, EvidenceCapabilities(tmp_path / 'other.db'))
    model = ScriptedModel()
    with pytest.raises(ValueError, match='same application store'):
        await assess_diagnosis(StrandsRuntime(settings(), model=model), service, context)
    assert not model.calls
