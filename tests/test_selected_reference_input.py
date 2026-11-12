"""Invented selected-purpose converter, preserving source graph and downstream format."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from test_reference_input import fixture,put,sha
from polar.import_adjusted_sip import SELECTED_ADAPTER,TEMPLATE,selected_policy,selected_unit
from polar.reference_input import prepare_input
from polar.research_reference import load_reference
from polar.selected_reference_input import PROFILE


def selected_fixture(tmp_path,mutate=None,*,targets=None):
    targets=targets or ['BBB','AAA'];template={**TEMPLATE,'start':'2024-01-31T00:00:00Z','end':'2024-02-03T00:00:00Z','asof':'2024-02-02'}
    ref=lambda p:{k:p[k] for k in ('path','sha256')}
    owner=put(tmp_path/'selected-owner.json',{'schema':'polar.quant-selected-source-operation/1',
        'fixed_targets':targets,'request_profile':{k:v for k,v in template.items() if k!='symbols'}})
    scope=put(tmp_path/'selected-scope.json',{'schema':'polar.selected-adjusted-sip-scope/1','targets':targets,
        'request_template':template,'policy':selected_policy(2),'selection_ref':ref(owner)})
    source_config=put(tmp_path/'selected-source-config.json',{'schema':'polar.selected-adjusted-sip-import-config/1',
        'adapter':SELECTED_ADAPTER,'mode':'fixture','scope_ref':ref(scope),'seed_refs':[]})
    unit=selected_unit(json.loads(Path(source_config['path']).read_bytes()),True)
    pid='adjustedsipselectedfixture-'+scope['sha256']+'-'+'a'*64
    store,old,records,rows=fixture(tmp_path,mutate,selected_unit_value=unit,selected_plan_id=pid)
    for r in records:r['selected_for_purpose']=r.pop('eligible_for_C')
    binding=json.loads(Path(old['binding']['path']).read_bytes());binding.update(
        schema='polar.selected-source-consumer-metadata-binding/1',records=records)
    bp=put(tmp_path/'selected-binding.json',binding)
    dates=['2024-01-31','2024-02-01','2024-02-02']
    grid=put(tmp_path/'selected-grid.json',{'schema':'polar.invented-selected-calendar/1','dates':dates,'parent_schedule':old['schedule']})
    protocol=put(tmp_path/'consumer-protocol.json',{'schema':'polar.invented-consumer-protocol/1','values':'NO_FINANCIAL_EXECUTION'})
    acceptance=put(tmp_path/'source-acceptance.json',{'schema':'polar.invented-source-acceptance/1','status':'INVENTED_SOURCE_ONLY'})
    rights=put(tmp_path/'rights.json',{'schema':'polar.invented-rights/1','rights':'INVENTED_PUBLIC_TEST'})
    purpose={'schema':'polar.selected-reference-source-purpose/1','source_collection':binding['source_collection'],
        'source_plan_id':pid,'source_config':source_config,'acquisition_order':targets,'portfolio_symbol_order':sorted(targets),
        'schedule':old['schedule'],'date_grid':grid,'date_range':old['date_range'],
        'consumer_protocol':protocol,'source_acceptance':acceptance,'rights_source_refs':[rights], 'rights':'INVENTED_PUBLIC_TEST'}
    pp=put(tmp_path/'selected-purpose.json',purpose)
    cfg={'schema':'polar.reference-input-conversion-config/2','profile_id':PROFILE,'namespace':'INVENTED',
        'binding':bp,'purpose':pp,'schedule':old['schedule'],'date_range':old['date_range']}
    return store,cfg,records,rows


def test_selected_source_only_lossless_graph_namespace_and_idempotency(tmp_path):
    store,cfg,records,rows=selected_fixture(tmp_path)
    out=prepare_input(cfg,store,10**8)
    assert out['status']=='PREPARED_SOURCE_ONLY' and out['strategy_execution']=='NOT_RUN'
    manifest=json.loads(Path(out['input_ref']['path']).read_bytes());m=load_reference(out['input_ref'])
    assert manifest['schema']=='polar.synthetic-reference-source-input/2' and m['symbols']==['AAA','BBB']
    assert manifest['parent_dataset_revision'].startswith('INVENTED-')
    assert m['prices_micro']['2024-01-31']=={'AAA':1234567,'BBB':20100000}
    assert manifest['provenance']=={'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'}
    relations=json.loads(Path(manifest['source_relations']['path']).read_bytes())
    assert relations['source_purpose']==cfg['purpose'] and 'definition_packet' not in relations
    assert relations['records']==records and all(r['source_records']==r['source_record_ids']==[] for r in records)
    quotes=[json.loads(l) for l in Path(manifest['quotes']['path']).read_bytes().splitlines()]
    assert quotes[0]['source_ref']['line_sha256']==sha(rows['AAA'][0])
    assert all(q['observed_historical_available_at'] is q['observed_published_at'] is None for q in quotes)
    assert prepare_input(cfg,store,10**8)==out


@pytest.mark.parametrize('where,key,value,error',[
    ('purpose','acquisition_order',['AAA','BBB'],'TARGET_ORDER'),
    ('purpose','portfolio_symbol_order',['BBB','AAA'],'TARGET_ORDER'),
    ('purpose','source_plan_id','adjustedsipselectedfixture-'+'0'*64+'-'+'a'*64,'SELECTED_PLAN'),
    ('purpose','rights','PRIVATE_RESEARCH','SELECTED_RIGHTS'),
    ('binding','provenance',{'kind':'RETAINED_SOURCE'},'INVENTED_POSITIVE_PROVENANCE'),
    ('binding','portfolio_symbol_order',['AAA'],'SELECTED_BINDING'),
])
def test_selected_mismatch_rejects_before_any_payload_open(tmp_path,where,key,value,error):
    store,cfg,_,_=selected_fixture(tmp_path)
    path=Path(cfg[where]['path']);body=json.loads(path.read_bytes());body[key]=value;cfg[where]=put(path,body)
    for p in (tmp_path/'source').rglob('bars.ndjson'):p.unlink()
    with pytest.raises(ValueError,match=error):prepare_input(cfg,store,10**8)
    assert not (store/'reference-inputs').exists()


def test_selected_dates_source_mode_and_missing_source_hash_fail_closed(tmp_path):
    store,cfg,_,_=selected_fixture(tmp_path)
    purpose=json.loads(Path(cfg['purpose']['path']).read_bytes())
    grid=json.loads(Path(purpose['date_grid']['path']).read_bytes());grid['dates'].pop()
    purpose['date_grid']=put(Path(purpose['date_grid']['path']),grid)
    cfg['purpose']=put(Path(cfg['purpose']['path']),purpose)
    with pytest.raises(ValueError,match='SELECTED_DATE_GRID'):prepare_input(cfg,store,10**8)
    assert not (store/'reference-inputs').exists()


def test_selected_scope_revalidation_and_source_only_record_identity(tmp_path):
    store,cfg,_,_=selected_fixture(tmp_path)
    b=json.loads(Path(cfg['binding']['path']).read_bytes());b['records'][0]['source_records']=[{'fabricated':'identity'}]
    cfg['binding']=put(Path(cfg['binding']['path']),b)
    with pytest.raises(ValueError,match='SOURCE_ONLY_RECORD'):prepare_input(cfg,store,10**8)
    assert not (store/'reference-inputs').exists()


def test_selected_never_uses_C_or_counterfeit_invented_namespace(tmp_path):
    store,cfg,_,_=selected_fixture(tmp_path)
    cfg['namespace']='RETAINED'
    with pytest.raises(ValueError,match='SOURCE_MODE'):prepare_input(cfg,store,10**8)
    cfg['namespace']='INVENTED';cfg['profile_id']='V033-C-BROAD-REFERENCE-INPUT-V1'
    with pytest.raises(ValueError,match='CONVERSION_CONFIG'):prepare_input(cfg,store,10**8)


def test_input2_admitted_by_fixed_profile_metadata_without_quote_read(tmp_path,monkeypatch):
    # Isolate the interface boundary: valid v2 input plus bound fixed calendar/profile,
    # and fail loudly if metadata preflight opens numeric source.
    from test_scheduled_fixed import fixed_fixture
    from reference_fixture import write
    from polar.reference_service import ReferenceResearchService
    root,config,profile,calendar=fixed_fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(config['input_ref']['path']).read_bytes())
    manifest['schema']='polar.synthetic-reference-source-input/2'
    manifest['quote_basis']='VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE'
    config['input_ref']=write(tmp_path/'v2-manifest.json',manifest)
    profile['input_sha256']=config['input_ref']['sha256']
    config['profile_ref']=write(tmp_path/'v2-profile.json',profile)
    import polar.scheduled_service as module
    def forbidden(*a,**k):raise AssertionError('PREFLIGHT_OPENED_NUMERIC_SOURCE')
    monkeypatch.setattr(module,'load_reference',forbidden)
    assert ReferenceResearchService(root,10**8).preflight(config)['expected_native_accounts']==4


def test_selected_conversion_to_fixed_input2_native_and_saved_only(tmp_path,monkeypatch):
    from test_scheduled_fixed import fixed_fixture
    from test_scheduled_service import snapshot
    from reference_fixture import write
    from polar.reference_service import ReferenceResearchService
    from polar.research_results import ResearchResults
    from datetime import datetime,timedelta
    store,cfg,_,_=selected_fixture(tmp_path)
    converted=prepare_input(cfg,store,10**8)
    separate=tmp_path/'account';separate.mkdir()
    root,config,profile,_=fixed_fixture(separate,monkeypatch)
    manifest=json.loads(Path(converted['input_ref']['path']).read_bytes())
    schedule=json.loads(Path(manifest['schedule']['path']).read_bytes())['rows'];days=[r['date'] for r in schedule]
    def event(i):
        k=datetime.fromisoformat(days[i]+'T00:00:00+00:00')+timedelta(days=1)
        return {'formation_date':days[i],'K':k.isoformat(),'D':(k+timedelta(seconds=60)).isoformat(),
            'execution_date':days[i+1],'reference_execution_close_utc':schedule[i+1]['reference_close_utc']}
    calendar={'schema':'polar.prospective-fixed-allocation-calendar/1','parent_schedule':cfg['schedule'],
        'dates':days,'initial_date':days[0],'terminal_date':days[-1],'nav_points':3,'returns':2,
        'annual_targets':[event(0)],'terminal_EXIT':event(1),'clock_scope':'UTC_MIDNIGHT_PLUS_60S'}
    cp=write(separate/'selected-calendar.json',calendar)
    profile.update(input_sha256=converted['input_ref']['sha256'],calendar_sha256=cp['sha256'],symbols=['AAA','BBB'],subperiods=[])
    for leg in profile['legs']:
        leg['weights']={'AAA':[0,1],'BBB':[0,1]} if leg['id']=='CASH' else {'AAA':[1,3],'BBB':[1,3]} if leg['id']=='THIRDS' else {'AAA':[1,3] if leg['id']=='THIRD' else [1,1],'BBB':[0,1]}
    pp=write(separate/'selected-profile.json',profile)
    config.update(input_ref=converted['input_ref'],calendar_ref=cp,profile_ref=pp)
    service=ReferenceResearchService(root,10**8)
    assert service.preflight(config)['expected_native_accounts']==4
    answer=service.run(config)
    assert answer['native_accounts']==4 and answer['fit_calls']==answer['predict_calls']==answer['model_calls']==0
    record=ResearchResults(root,10**8).read(answer['results']['FINAL']['result_id'])
    assert len(record['record']['grid'])==3 and record['assessment']['financial']=='NOT_REVIEWED'
    import polar.scheduled_service as module
    def forbidden(*a,**k):raise AssertionError('STORED_SOURCE_POLICY_NATIVE_CALL')
    for name in ('load_reference','plan_phase','bounded_native'):monkeypatch.setattr(module,name,forbidden)
    before=snapshot(root);replayed=service.recompute(answer['semantic_id'])
    assert replayed['status']=='REPRODUCED' and replayed['native_calls']==replayed['store_writes']==0
    assert before==snapshot(root)


def test_frozen_parent_calendar_requires_exact_lossless_derived_clock_grid(tmp_path):
    from polar.reference_input import schedule_binding_matches
    store,cfg,_,_=selected_fixture(tmp_path)
    result=prepare_input(cfg,store,10**8)
    manifest=json.loads(Path(result['input_ref']['path']).read_bytes())
    assert manifest['schedule']['sha256']!=cfg['schedule']['sha256']
    assert schedule_binding_matches(manifest,cfg['schedule'])
    projected=json.loads(Path(manifest['schedule']['path']).read_bytes())
    projected['rows'][1]['reference_close_utc']='2024-02-01T20:00:00+00:00'
    # Rehashed, otherwise valid metadata is still not the frozen parent's projection.
    manifest['schedule']=put(tmp_path/'substituted-clock-schedule.json',projected)
    assert not schedule_binding_matches(manifest,cfg['schedule'])


def test_selected_reference_symbol_domain_rejected_before_payload_read(tmp_path):
    store,cfg,_,_=selected_fixture(tmp_path,targets=['aaa','BBB'])
    for p in (tmp_path/'source').rglob('bars.ndjson'):p.unlink()
    with pytest.raises(ValueError,match='REFERENCE_CONVERSION_SYMBOLS'):prepare_input(cfg,store,10**8)
    assert not (store/'reference-inputs').exists()
