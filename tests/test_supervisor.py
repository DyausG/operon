"""Offline native supervisor -> SDK tool -> native specialist -> SDK output cycles."""
import asyncio
import json
import threading
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from strands import Agent
from strands.tools.decorator import DecoratedFunctionTool
from strands.tools.executors import SequentialToolExecutor

from core.agents.contracts import (
    AdvisoryInput, DiagnosticAssessment,
    SpecialistContext, SupervisorBounds, SupervisorDecision, SupervisorResult,
)
from core.agents.runtime import StrandsRuntime
from core.agents.supervisor import SUPERVISOR_TOOL_NAMES, create_supervisor_agent, supervise_reliability
from core.agents.tools import SPECIALIST_TOOL_NAMES
from core.reliability import models as m
from core.reliability.assessments import prepare_specialist_context
from core.reliability.orchestration import ROLE_CONTRACTS, SupervisorRun, assessment_dependencies, delegation_context
from core.reliability.repository import ARTIFACT_TYPES, InvalidReference
from tests.test_specialists import payload
from tests.test_strands_agents import ScriptedModel, protected_state, report, scoped, settings


@pytest.fixture
def supervisor_scope(scoped):
    repo, service, base = scoped
    context = prepare_specialist_context(
        repo, base.incident_id, asset_id=base.asset_id, run_id=base.run_id,
        evidence_ids=tuple(item.id for item in base.evidence), question="Investigate reliability and propose next steps.")
    return repo, service, context


def returned_reports(messages):
    results = {}
    for message in messages:
        for block in message['content']:
            for content in block.get('toolResult', {}).get('content', []):
                value = content.get('json', {})
                if 'assessment' in value:
                    for role, cls in ROLE_CONTRACTS.items():
                        if isinstance(AdvisoryInput.model_validate(value).assessment, cls):
                            results[role] = value
    return results


def delegation(role, inputs=(), question=None):
    def turn(messages):
        prior = returned_reports(messages)
        return [(f'delegate_{role}', {'query': dict(
            question=question or f'Assess {role} within the supplied evidence.',
            input_assessment_keys=[prior[key]['key'] for key in inputs])})]
    return turn


def decision(context, disposition='UNRESOLVED', **changes):
    def turn(messages):
        prior = returned_reports(messages)
        fields = {'diagnostic': 'candidate_diagnosis_key', 'engineering': 'engineering_key',
                  'operations': 'operations_key', 'planner': 'maintenance_plan_key'}
        value = dict(incident_id=context.incident_id, run_id=context.run_id, disposition=disposition,
                     reasoning_summary='Advisory reasoning requires application review.',
                     evidence_used=[item.id for item in context.evidence])
        value.update({field: prior[role]['key'] for role, field in fields.items() if role in prior})
        value['critic_keys'] = [prior['critic']['key']] if 'critic' in prior else []
        return [('SupervisorDecision', value | changes)]
    return turn


def evidence_followup(role='diagnostic', index=0, parameters=None):
    def turn(messages):
        prior = returned_reports(messages)
        return [('acquire_requested_evidence', {'request': dict(
            assessment_key=prior[role]['key'], need_index=index, query_parameters=parameters or {})})]
    return turn


class SpecialistsModel(ScriptedModel):
    """Respond at the Model boundary; actual specialist entry points are untouched."""
    def __init__(self, *, transform=None, reads=False, supported=False):
        super().__init__()
        self.transform, self.reads, self.supported = transform, reads, supported
        self.packets = []

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        names = {item['name'] for item in tool_specs}
        role = next(role for role, cls in ROLE_CONTRACTS.items() if cls.__name__ in names)
        context = SpecialistContext.model_validate_json(messages[0]['content'][0]['text'])
        if len(messages) == 1:
            self.packets.append((role, context))
        value = payload(role, context)
        if role != 'diagnostic':
            value['input_assessment_keys'] = [item.key for item in context.advisory_inputs]
        if role == 'critic':
            targets = [item for item in context.advisory_inputs if isinstance(item.assessment, DiagnosticAssessment)]
            engineering = [item for item in context.advisory_inputs if isinstance(item.assessment, ROLE_CONTRACTS['engineering'])]
            value['subject_id'] = (engineering or targets)[-1].key
        if self.supported:
            value['uncertainties'] = []
            if role == 'diagnostic':
                value.update(recommended_hypothesis='inspection-needed', missing_evidence_requests=[])
            elif role == 'engineering':
                value.update(intervention_feasibility='FEASIBLE', missing_constraints=[], blockers=[], safety_concerns=[])
            elif role == 'operations':
                value.update(resource_feasibility='FEASIBLE', blockers=[])
            elif role == 'critic':
                value.update(recommendation='ACCEPT', evidence_gaps=[], contradictions=[], unsupported_claims=[],
                             requested_additional_evidence=[])
            else:
                value.update(unresolved_blockers=[], estimated_exposure=100.0, exposure_currency='USD',
                             reversible=True, external_commitment=False)
        if self.reads and len(messages) == 1:
            response = [(name, {}) for name in sorted(SPECIALIST_TOOL_NAMES[role] - {'request_evidence'})]
            response += [(name, {}) for name in ('reserve_inventory', 'assign_technician', 'block_schedule',
                                                 'create_work_order', 'transition', 'approve', 'execute_governed_intervention')]
        else:
            response = [(ROLE_CONTRACTS[role].__name__, value)]
        if self.transform:
            response = self.transform(role, context, messages, response)
        self.turns = iter([response])
        async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
            yield event


async def run(scope, turns, *, specialists=None, bounds=None, supervisor_settings=None, specialist_settings=None):
    _, service, context = scope
    model = ScriptedModel(turns)
    specialists = specialists or SpecialistsModel()
    result = await supervise_reliability(
        StrandsRuntime(supervisor_settings or settings(), model=model), service, context,
        bounds=bounds, specialist_runtime=StrandsRuntime(specialist_settings or settings(), model=specialists))
    return result, model, specialists


def workflow(context, *, disposition='UNRESOLVED'):
    return [delegation('diagnostic'), delegation('critic', ('diagnostic',)),
            delegation('engineering', ('diagnostic',)), delegation('operations', ('engineering',)),
            delegation('critic', ('diagnostic', 'engineering', 'operations')),
            delegation('planner', ('diagnostic', 'engineering', 'operations', 'critic')),
            decision(context, disposition)]


def test_supervisor_is_native_and_tools_are_sdk_decorated(supervisor_scope):
    _, service, context = supervisor_scope
    runtime = StrandsRuntime(settings(), model=ScriptedModel())
    session = SupervisorRun(runtime, runtime, service, context, SupervisorBounds())
    agent = create_supervisor_agent(session)
    assert isinstance(agent, Agent)
    assert isinstance(agent.tool_executor, SequentialToolExecutor)
    assert set(agent.tool_names) == SUPERVISOR_TOOL_NAMES
    assert all(isinstance(item, DecoratedFunctionTool) for item in agent.tool_registry.registry.values())
    assert not issubclass(SupervisorDecision, m.Artifact)
    assert not issubclass(SupervisorResult, m.Artifact)
    assert 'SupervisorResult' not in ARTIFACT_TYPES


async def test_all_five_nested_native_agents_preserve_every_authority_boundary(supervisor_scope):
    repo, _, context = supervisor_scope
    before = protected_state(repo, context.incident_id)
    incident_before = repo.fetch_incident(context.incident_id)
    events_before = repo.list_events(context.incident_id)
    result, model, specialists = await run(supervisor_scope, workflow(context), specialists=SpecialistsModel(reads=True))
    assert len(result.delegations) == 6
    assert all(item.status == 'SUCCEEDED' for item in result.delegations)
    assert {item.role for item in result.delegations} == set(ROLE_CONTRACTS)
    assert {spec['name'] for spec in model.calls[0]['tools']} == SUPERVISOR_TOOL_NAMES | {'SupervisorDecision'}
    assert len(specialists.calls) == 12  # six fresh agents each performed a real tool and output turn
    for call, (role, _) in zip(specialists.calls[::2], specialists.packets):
        assert {spec['name'] for spec in call['tools']} == SPECIALIST_TOOL_NAMES[role] | {ROLE_CONTRACTS[role].__name__}
    for call in specialists.calls[1::2]:
        tool_results = [block['toolResult'] for block in call['messages'][-1]['content']]
        assert all(item['status'] == 'error' for item in tool_results[-7:])
        assert all(item['status'] == 'success' for item in tool_results[:-7])
    assert protected_state(repo, context.incident_id) == before
    assert repo.fetch_incident(context.incident_id) == incident_before
    assert repo.list_events(context.incident_id) == events_before
    assert not any(isinstance(item, (m.Diagnosis, m.Intervention, m.ValidationVerdict, m.Outcome))
                   for item in repo.list_artifacts(context.incident_id))
    assert result.human_review_required is True
    assert result.disposition == 'NEEDS_EVIDENCE'
    engineering = next(item.assessment for item in result.assessments if isinstance(item.assessment, ROLE_CONTRACTS['engineering']))
    assert engineering.intervention_feasibility == 'UNKNOWN' and engineering.constraints_considered == ()
    assert engineering.missing_constraints == ('OEM operating limits',)
    plan = result.assessments[-1].assessment
    assert plan.estimated_exposure is None and plan.external_commitment is None
    assert 'OEM operating limits' in result.blockers
    assert any(need.capability == 'inspection' for need in result.unresolved_evidence_needs)


async def test_supported_advisory_conclusion_still_requires_human_review(supervisor_scope):
    context = supervisor_scope[2]
    result, _, _ = await run(supervisor_scope, workflow(context, disposition='ADVISORY_CONCLUSION'),
                             specialists=SpecialistsModel(supported=True))
    assert result.disposition == 'ADVISORY_CONCLUSION'
    assert not result.blockers and not result.unresolved_evidence_needs
    assert result.human_review_required and result.termination_reason == 'MODEL_COMPLETED'


async def test_supervisor_can_choose_a_different_short_workflow_and_stop(supervisor_scope):
    context = supervisor_scope[2]
    result, _, specialists = await run(supervisor_scope, [delegation('diagnostic'), decision(context, 'NEEDS_EVIDENCE')])
    assert [role for role, _ in specialists.packets] == ['diagnostic']
    assert result.disposition == 'NEEDS_EVIDENCE'
    assert result.maintenance_plan_key is None


async def test_optimistic_summary_cannot_erase_unknowns_or_skip_review(supervisor_scope):
    context = supervisor_scope[2]
    result, _, _ = await run(supervisor_scope, [delegation('diagnostic'), decision(context, 'ADVISORY_CONCLUSION')])
    assert result.disposition == 'NEEDS_EVIDENCE'
    assert result.decision.disposition == 'ADVISORY_CONCLUSION'
    assert result.unresolved_evidence_needs


async def test_supervisor_rejects_consequential_and_direct_specialist_capabilities(supervisor_scope):
    repo, _, context = supervisor_scope
    before = protected_state(repo, context.incident_id)
    forbidden = ['transition', 'add_artifact', 'approve', 'reserve_inventory', 'assign_technician',
                 'block_schedule', 'create_work_order', 'execute_governed_intervention', 'request_evidence',
                 'get_asset_context', 'close_incident', 'create_outcome']
    result, model, specialists = await run(supervisor_scope, [[(name, {}) for name in forbidden], decision(context)])
    assert all(block['toolResult']['status'] == 'error' for block in model.calls[-1]['messages'][-1]['content'])
    assert not specialists.calls
    assert protected_state(repo, context.incident_id) == before
    assert result.disposition == 'BLOCKED'


@pytest.mark.parametrize('change', [
    {'disposition': 'APPROVED'}, {'execute': True}, {'reasoning_summary': ''}, {'run_id': ' '},
    {'evidence_used': ['']}, {'critic_keys': [None]},
])
def test_malformed_supervisor_contract_is_rejected(change):
    with pytest.raises(ValidationError):
        SupervisorDecision.model_validate(dict(incident_id='incident', run_id='run', disposition='UNRESOLVED',
                                               reasoning_summary='Missing evidence') | change)


@pytest.mark.parametrize('changes', [
    {'incident_id': 'foreign-incident'}, {'run_id': 'foreign-run'}, {'evidence_used': ['arbitrary-object-id']},
    {'candidate_diagnosis_key': 'invented-assessment'}, {'engineering_key': 'invented-assessment'},
])
async def test_supervisor_foreign_or_invented_output_references_fail_safely(supervisor_scope, changes):
    result, _, _ = await run(supervisor_scope, [decision(supervisor_scope[2], **changes)])
    assert result.termination_reason == 'INVALID_OUTPUT'
    assert result.decision is None and result.disposition == 'ESCALATED'


async def test_cross_incident_input_rejected_before_any_model(supervisor_scope):
    repo, service, context = supervisor_scope
    other = repo.create_incident(('AC-COMP-01',), admission_key='other-supervisor')
    foreign = service.request_and_collect(other.id, requested_by='diagnostic', equipment_ids=other.equipment_ids,
                                        question='Other incident evidence', capability='get_asset_context', required_for='diagnosis')
    bad = context.model_copy(update={'evidence': (foreign.evidence,)})
    model = ScriptedModel()
    with pytest.raises((ValidationError, InvalidReference)):
        await supervise_reliability(StrandsRuntime(settings(), model=model), service, bad)
    assert not model.calls


async def test_cross_incident_assessment_input_rejected_before_model(supervisor_scope):
    _, service, context = supervisor_scope
    foreign = AdvisoryInput(key='foreign', assessment=DiagnosticAssessment.model_validate(report('other-incident')))
    model = ScriptedModel()
    with pytest.raises((ValidationError, InvalidReference)):
        await supervise_reliability(StrandsRuntime(settings(), model=model), service,
                                    context.model_copy(update={'advisory_inputs': (foreign,)}))
    assert not model.calls


async def test_unprovided_same_incident_evidence_and_role_reference_rejected(supervisor_scope):
    _, service, context = supervisor_scope
    extra = service.request_and_collect(context.incident_id, requested_by='diagnostic', equipment_ids=(context.asset_id,),
                                       question='Unselected evidence', capability='get_operating_context', required_for='diagnosis')
    result, _, _ = await run(supervisor_scope, [decision(context, evidence_used=[extra.evidence.id])])
    assert result.termination_reason == 'INVALID_OUTPUT'

    def wrong_role(messages):
        key = returned_reports(messages)['diagnostic']['key']
        return decision(context, engineering_key=key)(messages)
    result, _, _ = await run(supervisor_scope, [delegation('diagnostic'), wrong_role])
    assert result.termination_reason == 'INVALID_OUTPUT'


async def test_malformed_native_supervisor_output_is_never_accepted(supervisor_scope):
    result, _, _ = await run(supervisor_scope, [[('SupervisorDecision', {'disposition': 'APPROVED'})]],
                             bounds=SupervisorBounds(max_iterations=1))
    assert result.decision is None and result.disposition == 'ESCALATED'
    assert result.termination_reason in {'INVALID_OUTPUT', 'LIMIT_EXHAUSTED'}


@pytest.mark.parametrize('failure', ['malformed', 'exception', 'foreign', 'invented_evidence'])
async def test_specialist_failure_never_becomes_a_valid_assessment(supervisor_scope, failure):
    context = supervisor_scope[2]
    def corrupt(role, packet, messages, response):
        if failure == 'exception':
            return RuntimeError('provider failed')
        if failure == 'malformed':
            return [('DiagnosticAssessment', {'incident_id': packet.incident_id})]
        response[0][1].update({'incident_id': 'foreign'} if failure == 'foreign' else {'evidence_reviewed': ['invented']})
        return response
    result, _, _ = await run(supervisor_scope, [delegation('diagnostic'), decision(context)],
                             specialists=SpecialistsModel(transform=corrupt), specialist_settings=settings(max_turns=1))
    assert not result.assessments and result.delegations[0].status == 'FAILED'
    assert result.disposition in {'BLOCKED', 'ESCALATED'}


def supported_need(role, packet, messages, response):
    if role == 'diagnostic':
        response[0][1]['missing_evidence_requests'] = [dict(capability='get_telemetry_window', question='Collect vibration readings')]
        response[0][1]['evidence_reviewed'] = [item.id for item in packet.evidence]
    return response


async def test_evidence_loop_uses_application_service_then_refines_diagnosis(supervisor_scope, monkeypatch):
    from tests.test_evidence import _readings
    _readings()
    repo, service, context = supervisor_scope
    before = protected_state(repo, context.incident_id)
    collect = Mock(wraps=service.request_and_collect)
    monkeypatch.setattr(service, 'request_and_collect', collect)
    result, _, specialists = await run(supervisor_scope, [delegation('diagnostic'), delegation('critic', ('diagnostic',)),
        evidence_followup(), delegation('diagnostic', question='Refine using newly collected evidence'), decision(context)],
        specialists=SpecialistsModel(transform=supported_need))
    collect.assert_called_once()
    assert collect.call_args.kwargs['requested_by'] == 'supervisor'
    record = result.evidence_requests[0]
    assert record.status == 'COLLECTED'
    assert record.evidence_id in {item.id for item in specialists.packets[-1][1].evidence}
    assert record.evidence_id in result.evidence_used
    evidence = repo.get_artifact(context.incident_id, record.evidence_id)
    request = repo.get_artifact(context.incident_id, record.request_id)
    assert evidence.content_hash and evidence.source_capability == 'get_telemetry_window'
    assert request.resolved_by_evidence_ids == (record.evidence_id,)
    assert protected_state(repo, context.incident_id) == before
    assert result.unresolved_evidence_needs  # collection alone does not establish sufficiency


@pytest.mark.parametrize('kind', ['service_failure', 'unavailable', 'unsupported'])
async def test_evidence_failure_and_missing_capabilities_preserve_uncertainty(supervisor_scope, monkeypatch, kind):
    repo, service, context = supervisor_scope
    before = protected_state(repo, context.incident_id)
    if kind == 'service_failure':
        monkeypatch.setattr(service.capabilities, 'collect', Mock(side_effect=RuntimeError('sensor store unavailable')))
    def need(role, packet, messages, response):
        if role == 'diagnostic':
            capability = 'inspection' if kind == 'unsupported' else 'get_related_incidents' if kind == 'unavailable' else 'get_telemetry_window'
            response[0][1]['missing_evidence_requests'] = [dict(capability=capability, question='Collect missing observations')]
        return response
    result, _, _ = await run(supervisor_scope, [delegation('diagnostic'), evidence_followup(), decision(context)],
                             specialists=SpecialistsModel(transform=need))
    assert result.disposition != 'ADVISORY_CONCLUSION'
    assert result.unresolved_evidence_needs
    assert result.evidence_requests[0].status in {'FAILED', 'UNAVAILABLE'}
    assert protected_state(repo, context.incident_id) == before
    if kind == 'service_failure':
        assert any(isinstance(item, m.EvidenceRequest) and item.status == 'OPEN' for item in repo.list_artifacts(context.incident_id))


async def test_shared_evidence_budget_covers_nested_diagnostic_critic_and_supervisor(supervisor_scope):
    context = supervisor_scope[2]
    def nested(role, packet, messages, response):
        if role in {'diagnostic', 'critic'} and len(messages) == 1:
            return [('request_evidence', {'query': dict(capability='get_maintenance_history',
                question=f'{role} needs history')})]
        return supported_need(role, packet, messages, response)
    result, _, _ = await run(supervisor_scope,
        [delegation('diagnostic'), delegation('critic', ('diagnostic',)), evidence_followup(), decision(context)],
        specialists=SpecialistsModel(transform=nested), bounds=SupervisorBounds(max_evidence_requests=1))
    assert len(result.evidence_requests) == 1
    assert 'evidence_requests' in result.exhausted_limits
    assert result.disposition == 'ESCALATED' and result.termination_reason == 'LIMIT_EXHAUSTED'


async def test_evidence_requests_and_delegation_duplicates_do_not_repeat_work(supervisor_scope, monkeypatch):
    _, service, context = supervisor_scope
    collect = Mock(wraps=service.request_and_collect)
    monkeypatch.setattr(service, 'request_and_collect', collect)
    result, _, specialists = await run(supervisor_scope,
        [delegation('diagnostic'), delegation('diagnostic', question='Rephrase identical work'),
         evidence_followup(), evidence_followup(), decision(context)], specialists=SpecialistsModel(transform=supported_need))
    assert len(result.delegations) == len(specialists.packets) == 1
    assert len(result.evidence_requests) == collect.call_count == 1


async def test_delegation_total_and_repeated_role_limits(supervisor_scope):
    context = supervisor_scope[2]
    result, _, specialists = await run(supervisor_scope,
        [delegation('diagnostic'), delegation('engineering', ('diagnostic',)), decision(context)],
        bounds=SupervisorBounds(max_delegations=1))
    assert len(specialists.packets) == 1 and 'specialist_delegations' in result.exhausted_limits
    result, _, specialists = await run(supervisor_scope,
        [delegation('diagnostic'), evidence_followup(), delegation('diagnostic'), decision(context)],
        specialists=SpecialistsModel(transform=supported_need), bounds=SupervisorBounds(max_role_invocations=1))
    assert len(specialists.packets) == 1 and 'diagnostic_invocations' in result.exhausted_limits
    assert result.disposition == 'ESCALATED'


@pytest.mark.parametrize('limit', ['turns', 'output_tokens', 'total_tokens', 'tools'])
async def test_native_supervisor_loop_and_same_turn_calls_are_bounded(supervisor_scope, limit):
    context = supervisor_scope[2]
    runtime_settings = settings(**({'max_output_tokens': 1} if limit == 'output_tokens' else
                                   {'max_total_tokens': 1} if limit == 'total_tokens' else {}))
    bounds = SupervisorBounds(max_iterations=2, max_tool_calls=2 if limit == 'tools' else 24)
    turns = [[('unknown_tool', {})] * (6 if limit == 'tools' else 1)] * 10
    result, model, _ = await run(supervisor_scope, turns, bounds=bounds, supervisor_settings=runtime_settings)
    assert len(model.calls) <= 2
    assert result.disposition == 'ESCALATED' and result.termination_reason == 'LIMIT_EXHAUSTED'
    assert result.exhausted_limits
    assert result.tool_calls <= bounds.max_tool_calls


async def test_timeout_returns_snapshot_and_cancels_nested_invocation(supervisor_scope):
    context = supervisor_scope[2]
    cancelled = asyncio.Event()
    class HangingSpecialist(ScriptedModel):
        async def stream(self, *args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            yield  # pragma: no cover
    result, _, _ = await run(supervisor_scope, [delegation('diagnostic')], specialists=HangingSpecialist(),
                             bounds=SupervisorBounds(timeout_seconds=0.1))
    assert cancelled.is_set()
    assert result.termination_reason == 'TIMEOUT' and result.disposition == 'ESCALATED'
    assert result.delegations[0].status == 'CANCELLED' and not result.assessments


async def test_supervisor_model_failure_returns_escalation(supervisor_scope):
    result, _, _ = await run(supervisor_scope, [RuntimeError('provider unavailable')])
    assert result.termination_reason == 'MODEL_FAILED' and result.decision is None


async def test_invalid_delegation_and_evidence_subject_never_reaches_services(supervisor_scope, monkeypatch):
    _, service, context = supervisor_scope
    forbidden = Mock(side_effect=AssertionError('no service call expected'))
    monkeypatch.setattr(service, 'request_and_collect', forbidden)
    result, _, specialists = await run(supervisor_scope, [
        [('delegate_engineering', {'query': dict(question='Inspect another subject', input_assessment_keys=['foreign'])})],
        [('acquire_requested_evidence', {'request': dict(assessment_key='foreign', need_index=0)})], decision(context)])
    assert not specialists.calls and not result.delegations
    forbidden.assert_not_called()


def test_dependency_closure_is_bounded_and_provenance_is_not_stripped(supervisor_scope):
    repo, _, context = supervisor_scope
    advice = {}
    for i in range(6):
        item = DiagnosticAssessment.model_validate(report(context.incident_id) | {
            'input_assessment_keys': [f'd{i - 1}'] if i else []})
        advice[f'd{i}'] = AdvisoryInput(key=f'd{i}', assessment=item)
    assert assessment_dependencies(('d5',), advice) == tuple(advice)
    with pytest.raises(ValueError, match='five-report'):
        delegation_context(repo, context, evidence_ids=tuple(item.id for item in context.evidence),
                           advice=advice, keys=('d5',), question='Refine')
    advice['d0'] = AdvisoryInput(key='d0', assessment=DiagnosticAssessment.model_validate(
        report(context.incident_id) | {'input_assessment_keys': ['d5']}))
    with pytest.raises(InvalidReference, match='cyclic'):
        assessment_dependencies(('d5',), advice)


async def test_application_store_mismatch_fails_before_model(supervisor_scope, tmp_path):
    from core.reliability.evidence import EvidenceCapabilities, EvidenceService
    repo, _, context = supervisor_scope
    model = ScriptedModel()
    with pytest.raises(ValueError, match='same application store'):
        await supervise_reliability(StrandsRuntime(settings(), model=model),
                                    EvidenceService(repo, EvidenceCapabilities(tmp_path / 'other.db')), context)
    assert not model.calls


async def test_full_workflow_can_revise_after_critic_evidence_request(supervisor_scope):
    from tests.test_evidence import _readings
    _readings()
    context = supervisor_scope[2]
    def refinement(role, packet, messages, response):
        value = response[0][1]
        need = dict(capability='get_telemetry_window', question='Collect discriminating telemetry')
        if role == 'diagnostic':
            value['evidence_reviewed'] = [item.id for item in packet.evidence]
            if len(packet.evidence) == 1:
                value.update(recommended_hypothesis=None, missing_evidence_requests=[need])
        if role == 'critic' and len(packet.evidence) == 1:
            value.update(recommendation='NEEDS_EVIDENCE', evidence_gaps=['Telemetry missing'],
                         requested_additional_evidence=[need])
        return response
    result, _, specialists = await run(supervisor_scope, [
        delegation('diagnostic'), delegation('critic', ('diagnostic',)), evidence_followup('critic'),
        delegation('diagnostic', question='Refine causal advice from acquired telemetry'),
        delegation('engineering', ('diagnostic',)), delegation('operations', ('engineering',)),
        delegation('critic', ('diagnostic', 'engineering', 'operations')),
        delegation('planner', ('diagnostic', 'engineering', 'operations', 'critic')),
        decision(context, 'ADVISORY_CONCLUSION')], specialists=SpecialistsModel(supported=True, transform=refinement))
    assert [role for role, _ in specialists.packets] == [
        'diagnostic', 'critic', 'diagnostic', 'engineering', 'operations', 'critic', 'planner']
    assert result.disposition == 'ADVISORY_CONCLUSION'
    assert result.unresolved_evidence_needs == ()
    assert len(result.critic_keys) == 2  # the earlier objection remains in the audit


async def test_later_agreement_cannot_erase_critic_objections_on_unchanged_subject(supervisor_scope):
    context = supervisor_scope[2]
    def reject_first(role, packet, messages, response):
        if role == 'critic' and len(packet.advisory_inputs) == 1:
            response[0][1].update(recommendation='REJECT', unsupported_claims=['Causal claim is unsupported'])
        return response
    result, _, _ = await run(supervisor_scope, workflow(context, disposition='ADVISORY_CONCLUSION'),
                             specialists=SpecialistsModel(supported=True, transform=reject_first))
    assert result.disposition == 'UNRESOLVED'
    assert 'Causal claim is unsupported' in result.blockers


async def test_multiple_evidence_requests_in_one_turn_are_bounded(supervisor_scope, monkeypatch):
    _, service, context = supervisor_scope
    collect = Mock(wraps=service.request_and_collect)
    monkeypatch.setattr(service, 'request_and_collect', collect)
    def many(messages):
        return [call for limit in (1, 2, 3, 4) for call in evidence_followup(parameters={'sample_limit': limit})(messages)]
    result, _, _ = await run(supervisor_scope, [delegation('diagnostic'), many, decision(context)],
                             specialists=SpecialistsModel(transform=supported_need),
                             bounds=SupervisorBounds(max_evidence_requests=2))
    assert len(result.evidence_requests) == collect.call_count == 2
    assert result.disposition == 'ESCALATED' and 'evidence_requests' in result.exhausted_limits


async def test_failed_evidence_request_is_not_retried_under_rephrasing(supervisor_scope, monkeypatch):
    _, service, context = supervisor_scope
    collect = Mock(side_effect=RuntimeError('evidence backend unavailable'))
    monkeypatch.setattr(service, 'request_and_collect', collect)
    result, _, _ = await run(supervisor_scope, [delegation('diagnostic'), evidence_followup(), evidence_followup(), decision(context)],
                             specialists=SpecialistsModel(transform=supported_need))
    assert collect.call_count == len(result.evidence_requests) == 1
    assert result.evidence_requests[0].status == 'FAILED'


async def test_foreign_evidence_service_return_is_rejected(supervisor_scope, monkeypatch):
    repo, service, context = supervisor_scope
    other = repo.create_incident(('HYD-PUMP-03',), admission_key='foreign-service-return')
    collection = service.request_and_collect(other.id, requested_by='diagnostic', equipment_ids=other.equipment_ids,
                                            question='Other asset', capability='get_asset_context', required_for='diagnosis')
    monkeypatch.setattr(service, 'request_and_collect', Mock(return_value=collection))
    result, _, _ = await run(supervisor_scope, [delegation('diagnostic'), evidence_followup(), decision(context)],
                             specialists=SpecialistsModel(transform=supported_need))
    assert result.evidence_requests[0].status == 'FAILED'
    assert result.evidence_requests[0].evidence_id is None
    assert collection.evidence.id not in result.evidence_used


async def test_nested_specialist_acquisition_preserves_durable_citations(supervisor_scope):
    context = supervisor_scope[2]
    def nested(role, packet, messages, response):
        if len(messages) == 1:
            return [('request_evidence', {'query': dict(capability='get_operating_context', question='Read operating context')})]
        collection = messages[-1]['content'][0]['toolResult']['content'][0]['json']
        response[0][1]['evidence_reviewed'].append(collection['evidence']['id'])
        return response
    result, _, _ = await run(supervisor_scope, [delegation('diagnostic'), decision(context)],
                             specialists=SpecialistsModel(transform=nested))
    assert result.delegations[0].status == 'SUCCEEDED'
    assert result.evidence_requests[0].requested_by == 'diagnostic'
    assert result.evidence_requests[0].evidence_id in result.evidence_used


async def test_existing_authoritative_artifacts_and_lifecycle_remain_unchanged(supervisor_scope):
    from tests.test_execution import prepared
    repo, service, base = supervisor_scope
    incident, intervention = prepared(repo)
    collection = service.request_and_collect(incident.id, requested_by='diagnostic', equipment_ids=incident.equipment_ids,
                                            question='Read asset', capability='get_asset_context', required_for='diagnosis')
    context = prepare_specialist_context(repo, incident.id, asset_id=base.asset_id, run_id='existing-artifacts',
        evidence_ids=(collection.evidence.id,), artifact_ids=(intervention.diagnosis_id, intervention.id))
    before = protected_state(repo, incident.id)
    artifacts_before = repo.list_artifacts(incident.id)
    events_before = repo.list_events(incident.id)
    result, _, _ = await run((repo, service, context), workflow(context), specialists=SpecialistsModel(reads=True))
    assert len(result.delegations) == 6
    assert protected_state(repo, incident.id) == before
    assert repo.list_artifacts(incident.id) == artifacts_before
    assert repo.list_events(incident.id) == events_before


async def test_wrong_invocation_state_and_closed_run_block_native_tools(supervisor_scope):
    _, service, context = supervisor_scope
    specialist = SpecialistsModel()
    runtime = StrandsRuntime(settings(), model=ScriptedModel([delegation('diagnostic')]))
    session = SupervisorRun(runtime, StrandsRuntime(settings(), model=specialist), service, context, SupervisorBounds())
    agent = create_supervisor_agent(session)
    result = await agent.invoke_async(context.model_dump_json(), invocation_state={'incident_id': 'foreign'}, limits={'turns': 1})
    assert result.stop_reason == 'limit_turns' and not specialist.calls
    session.closed = True
    agent = create_supervisor_agent(session)
    runtime._model.turns = iter([delegation('diagnostic')])
    await agent.invoke_async(context.model_dump_json(), invocation_state=session.invocation_state(), limits={'turns': 1})
    assert not specialist.calls


async def test_cancelled_evidence_thread_cannot_change_returned_advisory_snapshot(supervisor_scope, monkeypatch):
    repo, service, context = supervisor_scope
    before = protected_state(repo, context.incident_id)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = service.request_and_collect
    def slow(*args, **kwargs):
        started.set()
        try:
            assert release.wait(2), 'test must release evidence worker'
            return original(*args, **kwargs)
        finally:
            finished.set()
    monkeypatch.setattr(service, 'request_and_collect', slow)
    try:
        result, _, _ = await run(supervisor_scope, [delegation('diagnostic'), evidence_followup()],
            specialists=SpecialistsModel(transform=supported_need), bounds=SupervisorBounds(timeout_seconds=0.2))
        assert started.is_set()
        snapshot = result.model_dump_json()
        assert result.termination_reason == 'TIMEOUT'
        assert result.evidence_requests[0].status == 'CANCELLED'
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
    assert result.model_dump_json() == snapshot
    assert protected_state(repo, context.incident_id) == before


async def test_caller_cancellation_propagates_and_cleans_up(supervisor_scope):
    _, service, context = supervisor_scope
    started, stopped = asyncio.Event(), asyncio.Event()
    class WaitingSupervisor(ScriptedModel):
        async def stream(self, *args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
            yield  # pragma: no cover
    task = asyncio.create_task(supervise_reliability(StrandsRuntime(settings(), model=WaitingSupervisor()), service, context))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()
