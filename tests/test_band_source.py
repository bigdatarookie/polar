"""Invented source-only Band provenance; no real source, finance or provider."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from polar import band_source as band
from polar import native_selected_tool as tool
from polar.ci_research_service import root_identity
from polar.gym_service import code_binding
from polar.history_bundle import canonical, sha
from polar.reference_input import prepare_input
from polar.research_reference import load_reference
from test_reference_input import put
from test_native_selected_input import fixture as source_fixture

QUESTION = 'VTI-BIL-NO-TRADE-BAND-01'
ACTOR = 'engineering-data@engineering-rig'
TASK = 'qitem-INVENTED-band-source'


def fixture(tmp_path, monkeypatch):
    root, old, _, parent, _ = source_fixture(tmp_path, monkeypatch)
    protocol = put(tmp_path/'band-protocol.md', b'INVENTED METHOD ONLY')
    contract = put(tmp_path/'band-contract.json', {'source_free': True})
    fit = put(tmp_path/'band-fit.json', {'schema': 'polar.band-invented-source-fit/1',
                                       'namespace': 'INVENTED', 'source_payloads': 'NONE'})
    monkeypatch.setattr(band, 'method_binding', lambda: (QUESTION, contract['sha256'], protocol['sha256'], 'a'*40))
    import polar.candidate_binding as candidate
    import polar.offline_author_binding as offline
    monkeypatch.setattr(candidate, 'loaded_revision', lambda: 'a'*40)
    monkeypatch.setattr(offline, 'pair_runtime', lambda ns: 'sha256:'+'b'*64)
    domain = {'start': '2024-02-01', 'end': '2024-02-02', 'count': 2}
    purpose = {'schema': 'polar.band-selected-source-purpose-metadata/1',
        'question_id': QUESTION, 'candidate_revision': 'a'*40, 'author_contract': contract,
        'protocol': protocol, 'DR_fit': fit, 'symbols': ['BIL', 'VTI'],
        'rights': 'INVENTED_PUBLIC_TEST', 'reference_schedule': parent['schedule'],
        'intended_reference_domain_private': domain, 'source_qualification_refs': [fit]}
    spec = {'schema': 'polar.selected-component-materialization/1', 'namespace': 'INVENTED',
        'leaf_inputs': [{'input_ref': old['bil_input_ref'], 'symbol': 'BIL'}],
        'normalized_inputs': [{'input_ref': old['vti_parent_ref'], 'binding_ref': old['vti_binding_ref'], 'symbol': 'VTI'}],
        'schedule': parent['schedule'], 'date_range': domain,
        'purpose_ref': put(tmp_path/'band-purpose.json', purpose), 'qualification_refs': [fit]}
    cfg = {'schema': band.SOURCE_SCHEMA, 'profile_id': band.SOURCE_PROFILE, 'namespace': 'INVENTED',
        'question_id': QUESTION, 'candidate_id': 'INVENTED-BAND', 'experiment_id': 'INVENTED-SOURCE',
        'code': code_binding(), 'code_revision': 'a'*40, 'runtime_image_id': 'sha256:'+'b'*64,
        'artifact_root_identity': root_identity(root), 'consumer_task': TASK, 'actor_session': ACTOR,
        'spec_ref': put(tmp_path/'band-spec.json', spec), 'contract_ref': contract,
        'protocol_ref': protocol, 'source_fit_ref': fit}
    return root, cfg, spec, parent


def band_rights():
    from polar.selected_reference_input import RIGHTS
    return RIGHTS


def test_actual_source_only_dispatch_and_reader_exclude_mixed_parent_raw_and_offrange(tmp_path, monkeypatch):
    root, cfg, spec, parent = fixture(tmp_path, monkeypatch)
    import polar.selected_component_input as component
    original_read, original_decode = component.pinned_bytes, component.decode
    seen = []
    def read(pin):
        assert pin['path'] != parent['quotes']['path'], 'MIXED_PARENT_QUOTES_OPENED'
        assert '/objects/' not in pin['path'], 'RAW_SOURCE_BODY_OPENED'
        seen.append(pin['path']); return original_read(pin)
    def decode(raw):
        value = original_decode(raw)
        if isinstance(value, dict) and ('query_symbol' in value or 'reference_quote' in value):
            assert value.get('query_symbol', value.get('symbol')) in ('BIL', 'VTI')
            assert value.get('reference_date', value.get('date')) != '2024-01-31'
        return value
    monkeypatch.setattr(component, 'pinned_bytes', read)
    monkeypatch.setattr(component, 'decode', decode)
    out = prepare_input(cfg, root, 10**8)
    market = load_reference(out['input_ref'])
    assert market['symbols'] == ['BIL', 'VTI']
    assert market['dates'] == ['2024-02-01', '2024-02-02']
    assert market['prices_micro']['2024-02-01']['VTI'] == 20100000
    assert prepare_input(cfg, root, 10**8) == out
    manifest = json.loads(Path(out['input_ref']['path']).read_bytes())
    assert manifest['conversion_metadata']['source_native_binding']['config'] == cfg
    assert band.prepared_authorization(manifest)
    assert seen and parent['quotes']['path'] not in seen
    # Read-time exact spec binding rejects a changed purpose before quote bytes.
    manifest['conversion_metadata']['spec']['date_range']['count'] = 1
    with pytest.raises(ValueError, match='BAND_PREPARED_SOURCE_BINDING'):
        load_reference(put(tmp_path/'tampered-manifest.json', manifest))


@pytest.mark.parametrize('field,value', [
    ('question_id', 'OTHER'), ('profile_id', 'FOMC-CALENDAR-SELECTED-INPUT-V1'),
    ('schema', 'polar.reference-input-conversion-config/10'), ('actor_session', 'forged@polar-rig'),
    ('code_revision', 'f'*40), ('code', {}), ('runtime_image_id', 'sha256:'+'f'*64),
    ('artifact_root_identity', {}), ('namespace', 'OTHER'), ('consumer_task', 'not-a-task'),
])
def test_wrong_current_scope_rejected_before_any_private_pin(tmp_path, monkeypatch, field, value):
    root, cfg, _, _ = fixture(tmp_path, monkeypatch)
    cfg[field] = value
    monkeypatch.setattr(band, 'read_ref', lambda _: pytest.fail('PRIVATE_PIN_OPENED_BEFORE_CURRENT_SCOPE'))
    with pytest.raises(ValueError, match='BAND_SOURCE_'):
        band.prepare_source_input(cfg, root, 10**8)


def test_old_grant_not_a_config_field_and_wrong_source_purpose_before_value_reads(tmp_path, monkeypatch):
    root, cfg, spec, _ = fixture(tmp_path, monkeypatch)
    bad = {**cfg, 'source_admission_ref': 'qitem-old-fomc#71705'}
    with pytest.raises(ValueError, match='BAND_SOURCE_CONFIG'):
        band.prepare_source_input(bad, root, 10**8)
    purpose = json.loads(Path(spec['purpose_ref']['path']).read_bytes())
    purpose['question_id'] = 'OTHER'
    spec['purpose_ref'] = put(tmp_path/'other-purpose.json', purpose)
    cfg['spec_ref'] = put(tmp_path/'other-spec.json', spec)
    import polar.selected_component_input as component
    monkeypatch.setattr(component, 'prepare_selected_components', lambda *a, **k: pytest.fail('VALUE_ACCESS_ON_WRONG_PURPOSE'))
    with pytest.raises(ValueError, match='BAND_SOURCE_PURPOSE'):
        band.prepare_source_input(cfg, root, 10**8)


class Queue:
    def __init__(self):
        self.actor = ACTOR; self.generation = 'invented-generation'
        self.task = {'qitemId': TASK, 'state': 'in-progress', 'destinationSession': ACTOR,
            'claimedByGeneration': self.generation, 'claimedAt': '2026-01-01T00:00:00Z', 'tags': sorted(band.TAGS)}
        self.events = [{'transitionId': 2, 'state': 'in-progress', 'transitionNote': 'claimed',
                        'actorSession': ACTOR, 'identityProvenance': 'transport:v1'}]
        self.calls = []
    def read(self, *args):
        self.calls.append(args)
        rig, logical = band.ACTORS[self.actor]
        if args == ('whoami',):
            return {'identity': {'sessionName': self.actor, 'rigName': rig, 'logicalId': logical, 'nodeId': 'invented'}}
        if args == ('seat', 'status', self.actor):
            return {'current_occupant': self.actor, 'logical_id': logical, 'rig_name': rig}
        if args == band.generation_read(self.actor):
            return {'entries': [{'rigName': rig, 'logicalId': logical, 'canonicalSessionName': self.actor,
                'sessionStatus': 'running', 'agentActivity': {'generation': self.generation,
                'generationProvenance': 'resolved', 'evidenceSource': 'native_owner'}}]}
        if args == ('queue', 'show', TASK, '--full'):return deepcopy(self.task)
        if args == ('queue', 'transitions', TASK, '--full'):return deepcopy(self.events)
        raise AssertionError(args)


def test_current_data_custody_then_terminal_quant_source_read_not_new_preparation(tmp_path, monkeypatch):
    _, cfg, _, _ = fixture(tmp_path, monkeypatch); queue = Queue()
    proof = band.task_custody(cfg, queue)
    queue.task.update(state='done', closureReason='handed_off_to', handedOffTo='engineering-platform@engineering-rig')
    queue.events.append({'transitionId': 3, 'state': 'done', 'actorSession': ACTOR, 'identityProvenance': 'transport:v1'})
    queue.actor = 'quant-a@polar-rig'; queue.generation = 'next-quant-generation'
    result = {'schema': 'polar.band-source-result/1', 'status': 'INVENTED_TYPED_RESULT'}
    queue.task['resolution'] = json.dumps(result)
    assert band.task_custody(cfg, queue, prior=proof, terminal_result=result) == proof
    with pytest.raises(ValueError, match='BAND_SOURCE_TERMINAL_CUSTODY'):
        band.task_custody(cfg, queue, prior=proof)
    queue.task['closureReason'] = 'canceled'
    with pytest.raises(ValueError, match='BAND_SOURCE_TERMINAL_CUSTODY'):
        band.task_custody(cfg, queue, prior=proof, terminal_result=result)


@pytest.mark.parametrize('part', ['actor', 'generation', 'claim', 'task', 'tags', 'closed', 'fallback'])
def test_native_wrong_identity_assignment_and_custody_never_reach_source(tmp_path, monkeypatch, part):
    root, cfg, _, _ = fixture(tmp_path, monkeypatch); queue = Queue();cfg['namespace'] = 'RETAINED'
    monkeypatch.setattr(band, 'actual_runtime', lambda c: None)
    if part == 'actor':queue.actor = 'quant-a@polar-rig'
    if part == 'generation':queue.task['claimedByGeneration'] = 'old-generation'
    if part == 'claim':queue.events[0]['identityProvenance'] = 'request-body'
    if part == 'task':queue.task['destinationSession'] = 'quant-a@polar-rig'
    if part == 'tags':queue.task['tags'] = ['slice:fomc-calendar']
    if part == 'closed':queue.task.update(state='done', closureReason='no-follow-on')
    if part == 'fallback':
        original = queue.read
        def read(*args):
            result = original(*args)
            if args == band.generation_read(queue.actor):result['entries'][0]['agentActivity']['fallback'] = True
            return result
        queue.read = read
    monkeypatch.setattr(band, 'read_ref', lambda _: pytest.fail('PRIVATE_PIN_OPENED_WITH_UNTRUSTED_NATIVE_SCOPE'))
    with pytest.raises(ValueError, match='BAND_SOURCE_'):
        band.prepare_source_input(cfg, root, 10**8, queue=queue)


def test_custody_race_and_terminal_transport_forgery_rejected(tmp_path, monkeypatch):
    _, cfg, _, _ = fixture(tmp_path, monkeypatch); queue=Queue(); original=queue.read; n=0
    def race(*args):
        nonlocal n
        result=original(*args)
        if args == ('queue', 'show', TASK, '--full'):
            n+=1
            if n==2:result['claimedAt']='2026-02-01T00:00:00Z'
        return result
    queue.read=race
    with pytest.raises(ValueError, match='BAND_SOURCE_CUSTODY_CHANGED'):band.task_custody(cfg,queue)
    queue=Queue();proof=band.task_custody(cfg,queue)
    queue.task.update(state='done',closureReason='no-follow-on')
    queue.events.append({'transitionId':3,'state':'done','actorSession':ACTOR,'identityProvenance':'caller-field'})
    with pytest.raises(ValueError, match='BAND_SOURCE_TERMINAL_CUSTODY'):
        band.task_custody(cfg,queue,prior=proof,terminal_result={'schema':'INVENTED'})


def test_band_stdio_read_allowlist_and_old_context_unchanged(tmp_path, monkeypatch):
    _,cfg,_,_=fixture(tmp_path,monkeypatch)
    assert tool.selected_config('research-input-prepare',cfg)==cfg
    for actor in band.ACTORS:
        assert tool.permitted(list(band.generation_read(actor)),cfg)
    assert tool.permitted(['queue','show',TASK,'--full'],cfg)
    for args in (['queue','claim',TASK], ['queue','show','qitem-other','--full'], ['whoami','--source','forged']):
        assert not tool.permitted(args,cfg)
    from polar.native_selected_input import generation_read
    with pytest.raises(ValueError,match='NATIVE_SELECTED_ACTOR'):generation_read(ACTOR)


def test_terminal_source_result_must_bind_actual_input_not_merely_completed_task(tmp_path, monkeypatch):
    _, cfg, _, _ = fixture(tmp_path, monkeypatch);queue=Queue();proof=band.task_custody(cfg,queue)
    queue.task.update(state='done',closureReason='no-follow-on',resolution=json.dumps({'schema':'polar.band-source-result/1','input':'OTHER'}))
    queue.events.append({'transitionId':3,'state':'done','actorSession':ACTOR,'identityProvenance':'transport:v1'})
    expected=band.producer_result(cfg,{'parent_dataset_revision':'INVENTED-reference-input-x'})
    with pytest.raises(ValueError,match='BAND_SOURCE_TERMINAL_RESULT'):
        band.task_custody(cfg,queue,prior=proof,terminal_result=expected)
    queue.task['resolution']=json.dumps(expected)
    assert band.task_custody(cfg,queue,prior=proof,terminal_result=expected)==proof


def test_close_during_preparation_does_not_accept_partial_output(tmp_path, monkeypatch):
    root,cfg,_,_=fixture(tmp_path,monkeypatch);cfg['namespace']='RETAINED';queue=Queue()
    monkeypatch.setattr(band,'actual_runtime',lambda c:None)
    monkeypatch.setattr(band,'checked_spec',lambda c:{'source_free':'CONTROL_FLOW_ONLY'})
    import polar.selected_component_input as component
    def materialize(*a,**k):
        queue.task.update(state='done',closureReason='no-follow-on')
        queue.events.append({'transitionId':3,'state':'done','actorSession':ACTOR,'identityProvenance':'transport:v1'})
        return {'input_ref':{'path':'/never/read/partial.json','sha256':'0'*64}}
    monkeypatch.setattr(component,'prepare_selected_components',materialize)
    with pytest.raises(ValueError,match='BAND_SOURCE_TERMINAL_CUSTODY'):
        band.prepare_source_input(cfg,root,10**8,queue=queue)


@pytest.mark.parametrize('failure', [None,'domain','components','fit'])
def test_retained_metadata_contract_rejects_changed_domain_and_component_before_value_access(tmp_path,monkeypatch,failure):
    # Entirely invented metadata exercises retained contract branches, without
    # authorizing or reading a retained member or running the materializer.
    root,cfg,spec,_=fixture(tmp_path,monkeypatch)
    bilfolder=tmp_path/'bil';bilfolder.mkdir()
    vfolder=tmp_path/'vti';vfolder.mkdir()
    bil=put(bilfolder/'manifest.json',Path(spec['leaf_inputs'][0]['input_ref']['path']).read_bytes())
    binding=put(vfolder/'selected-source-binding-v1.json',Path(spec['normalized_inputs'][0]['binding_ref']['path']).read_bytes())
    phases=[{'startup_formation_session':'2024-02-01','last_session':'2024-02-02'}]
    fit=put(tmp_path/'invented-retained-fit.json',{'inputs':{'BIL':{'pins':[bil]},'VTI':{'pins':[binding]}},'phase_geometry':phases})
    monkeypatch.setattr(band,'DR_FIT_SHA',fit['sha256'])
    monkeypatch.setattr(band,'VTI_PARENT_SHA',spec['normalized_inputs'][0]['input_ref']['sha256'])
    cfg.update(namespace='RETAINED',source_fit_ref=fit)
    spec.update(namespace='RETAINED',qualification_refs=[fit])
    spec['leaf_inputs'][0]['input_ref']=bil;spec['normalized_inputs'][0]['binding_ref']=binding
    purpose=json.loads(Path(spec['purpose_ref']['path']).read_bytes())
    purpose.update(DR_fit=fit,source_qualification_refs=[fit],phase_geometry_private=phases,rights=band_rights())
    if failure=='domain':
        spec['date_range']={'start':'2024-02-02','end':'2024-02-02','count':1}
        purpose['intended_reference_domain_private']=spec['date_range']
    if failure=='components':spec['leaf_inputs'][0]['input_ref']={**bil,'sha256':'0'*64}
    spec['purpose_ref']=put(tmp_path/'retained-branch-purpose.json',purpose)
    cfg['spec_ref']=put(tmp_path/'retained-branch-spec.json',spec)
    if failure=='fit':monkeypatch.setattr(band,'DR_FIT_SHA','0'*64)
    if failure:
        with pytest.raises(ValueError,match='BAND_SOURCE_FROZEN_DOMAIN|BAND_SOURCE_RETAINED_COMPONENTS|BAND_SOURCE_FIT_PIN'):
            band.checked_spec(cfg)
    else:assert band.checked_spec(cfg)==spec


def test_historical_producer_code_stays_distinct_from_current_financial_build(tmp_path,monkeypatch):
    root,source,_,_=fixture(tmp_path,monkeypatch)
    source.update(namespace='RETAINED',code_revision='d'*40,runtime_image_id='sha256:'+'d'*64)
    source['code']={**source['code'],'band_source.py':'d'*64}
    # Old producer build is provenance, not today's loaded-build identity.
    band.current_binding(source,root,historical=True)
    with pytest.raises(ValueError,match='BAND_SOURCE_CURRENT_BINDING'):
        band.current_binding(source,root)
    source['code']={}
    with pytest.raises(ValueError,match='BAND_SOURCE_PRODUCER_BUILD'):
        band.current_binding(source,root,historical=True)


@pytest.mark.parametrize('failure',[None,'code','runtime','root','profile','source_protocol','consumer_race'])
def test_financial_consumer_is_independent_current_binding_not_producer_relabel(tmp_path,monkeypatch,failure):
    root,source,_,_=fixture(tmp_path,monkeypatch)
    source.update(namespace='RETAINED',code_revision='d'*40,runtime_image_id='sha256:'+'d'*64)
    financial={k:source[k] for k in ('namespace','code','artifact_root_identity','protocol_ref')}
    financial.update(schema='polar.band-reference-config/1',code_revision='a'*40,
        runtime_image_id='sha256:'+'b'*64,consumer_task='qitem-INVENTED-financial',execution_authority_ref=None)
    profile={'schema':'polar.scheduled-reference-profile/17','protocol_id':QUESTION,
        'protocol_sha256':source['protocol_ref']['sha256'],
        'policy':{'contract_sha256':source['contract_ref']['sha256']}}
    manifest={'provenance':{'source_native_binding':{'config':source}}}
    import polar.native_selected_input as native
    import polar.offline_author_binding as offline
    monkeypatch.setattr(band,'actual_runtime',lambda c:pytest.fail('SOURCE_PRODUCER_RUNTIME_REUSED') if c['runtime_image_id']!='sha256:'+'b'*64 else None)
    task={'qitemId':financial['consumer_task'],'tags':sorted(band.TAGS),'state':'in-progress'}
    calls=[]
    def custody(task_id,*,queue=None):
        assert task_id=='qitem-INVENTED-financial'
        calls.append(task_id)
        return ('quant-a@polar-rig','CHANGED' if failure=='consumer_race' and len(calls)>1 else 'current-financial-generation',deepcopy(task))
    monkeypatch.setattr(native,'consumer_custody',custody)
    def source_proof(value,*,queue=None):
        assert value['provenance']['source_native_binding']['config']['code_revision']=='d'*40
        return {'actor':ACTOR,'generation':'original-source-generation'}
    monkeypatch.setattr(band,'prepared_authorization',source_proof)
    if failure=='code':financial['code']={}
    if failure=='runtime':
        monkeypatch.setattr(band,'actual_runtime',lambda c:(_ for _ in ()).throw(ValueError('BAND_SOURCE_RUNTIME')))
    if failure=='root':financial['artifact_root_identity']={}
    if failure=='profile':profile['protocol_id']='OTHER'
    if failure=='source_protocol':source['protocol_ref']={**source['protocol_ref'],'sha256':'0'*64}
    if failure:
        with pytest.raises(ValueError,match='BAND_'):
            band.authorize_financial(financial,profile,manifest,root,queue=object())
    else:
        proof=band.authorize_financial(financial,profile,manifest,root,queue=object())
        assert proof['generation']=='current-financial-generation'
        assert proof['source_producer']['generation']=='original-source-generation'
        assert len(calls)==2


def test_financial_bridge_reads_only_exact_consumer_and_source_tasks(tmp_path,monkeypatch):
    import sys
    from types import ModuleType
    _,cfg,_,_=fixture(tmp_path,monkeypatch)
    contract=ModuleType('polar.band_contract');contract.QUESTION=QUESTION
    monkeypatch.setitem(sys.modules,'polar.band_contract',contract)
    financial={'schema':'polar.band-reference-config/1','consumer_task':'qitem-INVENTED-finance',
        'input_ref':put(tmp_path/'financial-input-metadata.json',{'provenance':{'source_native_binding':{'config':cfg}}}),
        'profile_ref':put(tmp_path/'financial-profile.json',{'schema':'polar.scheduled-reference-profile/17','protocol_id':QUESTION})}
    assert tool.selected_config('research-preflight',financial)==financial
    for task in (financial['consumer_task'],cfg['consumer_task']):
        assert tool.permitted(['queue','show',task,'--full'],financial)
    assert not tool.permitted(['queue','show','qitem-unrelated','--full'],financial)
