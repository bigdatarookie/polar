"""Invented actual-shape single capture, with no fabricated importer jobs."""
import json
from pathlib import Path
from copy import deepcopy
import pytest
from test_reference_input import put
from test_selected_reference_input import selected_fixture
from polar.reference_input import prepare_input
from polar.captured_reference_input import PROFILE
from polar.research_reference import load_reference
from polar.import_raw_sip import page


def captured_fixture(tmp_path,mutate=None):
    selected=tmp_path/'selected';selected.mkdir()
    root,shy,_,_=selected_fixture(selected,targets=['SHY'])
    oldpurpose=json.loads(Path(shy['purpose']['path']).read_bytes())
    days=['2024-01-31','2024-02-01','2024-02-02']
    raw={'bars':{'BIL':[{'t':d+'T05:00:00Z','o':10.12,'h':10.14,'l':10.11,'c':10.13,'v':100,'n':10,'vw':10.125} for d in days]},'next_page_token':None}
    plan={'schema':'polar.bounded-provider-full-range-source-plan/1','mode':'fixture',
          'endpoint':'https://data.alpaca.markets/v2/stocks/bars','method':'GET',
          'query':{'symbols':'BIL','timeframe':'1Day','feed':'sip','currency':'USD','adjustment':'all','sort':'asc'}}
    http={'status':200,'complete_at_capture':True,'published_at':None,'historical_available_at':None,'source_version':None}
    if mutate:mutate(raw,plan,http)
    body=put(tmp_path/'body.json',raw);rp=put(tmp_path/'request.json',plan)
    parsed=page(Path(body['path']).read_bytes())
    exact={'schema':'polar.selected-provider-full-snapshot-exact-tokens/1','source':body,'request_plan':rp,
           'numeric_policy':'PRESERVE_SOURCE_LEXEMES','rows':[{'source_pointer':f'/bars/BIL/{i}','tokens':r,'quality':'LEXICAL_DOMAIN_CHECKED'} for i,r in enumerate(parsed['bars']['BIL'])],
           'original_top_level_other_fields':{'next_page_token':None}}
    if mutate and getattr(mutate,'token_mismatch',False):exact['rows'][0]['tokens']['c']='10.14'
    ep=put(tmp_path/'exact.json',exact)
    capture=put(tmp_path/'capture.json',{'schema':'polar.BIL-full-range-single-GET-capture-return/1',
        'status':'HTTP_RESPONSE_ARCHIVED','body_ref':body,'plan_ref':rp,'HTTP_metadata':{**http,'captured_body_bytes':Path(body['path']).stat().st_size},
        'provenance':{'kind':'DETERMINISTIC_INVENTED_FIXTURE','source_payloads':'NONE'}})
    protocol_binding=put(tmp_path/'protocol-binding.json',{'schema':'polar.captured-reference-protocol-binding/1',
        'protocol':oldpurpose['consumer_protocol'],'packet':oldpurpose['consumer_protocol']})
    oldpurpose['consumer_protocol']=protocol_binding
    purpose={'schema':'polar.captured-reference-source-purpose/1','capture_return':capture,'exact_tokens':ep,
             'symbols':['BIL'],'schedule':shy['schedule'],'date_range':shy['date_range'],
             **{k:oldpurpose[k] for k in ('consumer_protocol','source_acceptance','rights_source_refs','rights')}}
    pp=put(tmp_path/'purpose.json',purpose)
    return root,{'schema':'polar.reference-input-conversion-config/4','profile_id':PROFILE,'namespace':'INVENTED',
        'capture_return':capture,'exact_tokens':ep,'purpose':pp,'schedule':shy['schedule'],'date_range':shy['date_range']},shy


def test_captured_exact_source_then_existing_composition_preserves_distinct_origins(tmp_path):
    root,cfg,shy=captured_fixture(tmp_path)
    before={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.rglob('*.json')}
    bil=prepare_input(cfg,root,10**8);m=load_reference(bil['input_ref'])
    assert m['prices_micro']['2024-01-31']['BIL']==10130000
    manifest=json.loads(Path(bil['input_ref']['path']).read_bytes())
    rel=m['source_relations'];assert not rel['jobs'] and not rel['parent_relations']
    assert 'source_collection' not in manifest['conversion_metadata']
    assert rel['captures'][cfg['capture_return']['sha256']]['capture_return']==cfg['capture_return']
    assert prepare_input(cfg,root,10**8)==bil
    other=prepare_input(shy,root,10**8)['input_ref'];inputs=[other,bil['input_ref']]
    pp=json.loads(Path(cfg['purpose']['path']).read_bytes())
    cp=put(tmp_path/'composition-purpose.json',{'schema':'polar.reference-input-composition-purpose/1','inputs':inputs,
        'symbols':['BIL','SHY'],'schedule':cfg['schedule'],'date_range':cfg['date_range'],
        **{k:pp[k] for k in ('consumer_protocol','source_acceptance','rights_source_refs','rights')}})
    union=prepare_input({'schema':'polar.reference-input-conversion-config/3',
        'profile_id':'COMPOSED-ALL-ADJUSTED-REFERENCE-INPUT-V1','namespace':'INVENTED','inputs':inputs,
        'purpose':cp,'schedule':cfg['schedule'],'date_range':cfg['date_range']},root,10**8)
    composed=load_reference(union['input_ref']);assert composed['symbols']==['BIL','SHY']
    assert 'source_collection' in composed['source_relations']['source_components'][0]
    assert 'source_capture' in composed['source_relations']['source_components'][1]
    assert composed['source_evidence']['2024-01-31']['BIL']==m['source_evidence']['2024-01-31']['BIL']
    assert all(p.read_bytes()==b and p.stat().st_mtime_ns==t for name,(b,t) in before.items() for p in [Path(name)])


@pytest.mark.parametrize('case,error',[
    ('incomplete','CAPTURE_HTTP'),('raw','REQUEST_BASIS'),('precision','BIL_PRECISION'),
    ('duplicate','DATE_DUPLICATE'),('token','EXACT_TOKEN'),('cursor','CAPTURE_COMPLETE')])
def test_rehashed_capture_invalids_never_project_or_publish(tmp_path,case,error):
    def mutate(raw,plan,http):
        if case=='incomplete':http['complete_at_capture']=False
        if case=='raw':plan['query']['adjustment']='raw'
        if case=='precision':raw['bars']['BIL'][0]['c']=10.131
        if case=='duplicate':raw['bars']['BIL'][1]['t']=raw['bars']['BIL'][0]['t']
        if case=='cursor':raw['next_page_token']='more'
    mutate.token_mismatch=case=='token'
    root,cfg,_=captured_fixture(tmp_path,mutate)
    with pytest.raises(ValueError,match=error):prepare_input(cfg,root,10**8)
    assert not (root/'reference-inputs').exists()


def test_bridge_to_profile12_six_native_accounts_and_source_absent_readonly_replay(tmp_path,monkeypatch):
    from scheduled_fixture import fixture
    from test_scheduled_parking import profile
    from test_scheduled_service import snapshot
    from polar.reference_service import ReferenceResearchService
    from polar.research_results import ResearchResults
    root,base,_,_=fixture(tmp_path,monkeypatch)
    sub=tmp_path/'captured';sub.mkdir();store,cfg,shy=captured_fixture(sub)
    bil=prepare_input(cfg,store,10**8)['input_ref'];other=prepare_input(shy,store,10**8)['input_ref']
    pp=json.loads(Path(cfg['purpose']['path']).read_bytes());inputs=[other,bil]
    cp=put(sub/'service-composition-purpose.json',{'schema':'polar.reference-input-composition-purpose/1',
        'inputs':inputs,'symbols':['BIL','SHY'],'schedule':cfg['schedule'],'date_range':cfg['date_range'],
        **{k:pp[k] for k in ('consumer_protocol','source_acceptance','rights_source_refs','rights')}})
    input_ref=prepare_input({'schema':'polar.reference-input-conversion-config/3',
        'profile_id':'COMPOSED-ALL-ADJUSTED-REFERENCE-INPUT-V1','namespace':'INVENTED',
        'inputs':inputs,'purpose':cp,'schedule':cfg['schedule'],'date_range':cfg['date_range']},store,10**8)['input_ref']
    market=load_reference(input_ref);days=market['dates'];schedule={r['date']:r for r in market['schedule']}
    from datetime import datetime,timedelta,timezone
    def event(i):
        k=datetime.fromisoformat(days[i]+'T00:00:00+00:00')+timedelta(days=1)
        return {'formation_date':days[i],'K':k.isoformat(),'D':(k+timedelta(seconds=60)).isoformat(),
            'execution_date':days[i+1],'reference_execution_close_utc':schedule[days[i+1]]['reference_close_utc']}
    calendar={'schema':'polar.prospective-fixed-allocation-calendar/1','parent_schedule':cfg['schedule'],'dates':days,
        'initial_date':days[0],'terminal_date':days[-1],'nav_points':len(days),'returns':len(days)-1,
        'annual_targets':[event(0)],'terminal_EXIT':event(len(days)-2),'clock_scope':'UTC_MIDNIGHT_PLUS_60S'}
    calpin=put(sub/'service-calendar.json',calendar);p=profile()
    p.update(protocol_sha256=base['protocol_ref']['sha256'],input_sha256=input_ref['sha256'],
             calendar_sha256=calpin['sha256'],timezone_sha256=base['timezone_ref']['sha256'])
    profilepin=put(sub/'service-profile.json',p)
    runconfig={**base,'profile_ref':profilepin,'input_ref':input_ref,'calendar_ref':calpin,
        'candidate_id':'INVENTED-B9','experiment_id':'INVENTED-B9-CAPTURE-TO-SAVED'}
    service=ReferenceResearchService(root,128*1024**2)
    import polar.scheduled_service as module
    actual=module.load_market
    def forbidden(*args):raise AssertionError('SOURCE_POLICY_NATIVE_DURING_PREFLIGHT_OR_STORED')
    monkeypatch.setattr(module,'load_market',forbidden)
    ready=service.preflight(runconfig);assert ready['expected_native_accounts']==6
    monkeypatch.setattr(module,'load_market',actual)
    result=service.run(runconfig);assert result['status']=='SUCCESS' and result['native_accounts']==6
    assert set(result['results'])=={'FINAL','FINAL_COST_STRESS'}
    for label,ref in result['results'].items():
        record=ResearchResults(root,128*1024**2).read(ref['result_id'])['record']
        assert len(record['series'])==3 and len(record['criteria'])==5
    before=snapshot(root)
    for name in ('load_market','load_reference','plan_phase','bounded_native'):monkeypatch.setattr(module,name,forbidden)
    replay=service.recompute(result['semantic_id'])
    assert replay['status']=='REPRODUCED' and replay['native_calls']==replay['store_writes']==0
    assert snapshot(root)==before
