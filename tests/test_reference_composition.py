"""Invented projection union; source pointers and cent/vol boundary semantics."""
import json
from pathlib import Path
from copy import deepcopy
import pytest
from test_reference_input import put
from test_selected_reference_input import selected_fixture
from polar.reference_input import prepare_input,schedule_binding_matches
from polar.reference_composition import PROFILE,composition_metadata
from polar.research_reference import load_reference


def composition_fixture(tmp_path,second_targets=None):
    refs=[];configs=[]
    for name,targets in [('first',['AAA','BBB']),('second',second_targets or ['DDD','EEE'])]:
        directory=tmp_path/name;directory.mkdir()
        store,cfg,_,_=selected_fixture(directory,targets=targets)
        refs.append(prepare_input(cfg,store,10**8)['input_ref']);configs.append(cfg)
    first=configs[0]
    purpose=put(tmp_path/'purpose.json',{'schema':'polar.reference-input-composition-purpose/1',
        'inputs':refs,'symbols':['AAA','BBB','DDD','EEE'],'schedule':first['schedule'],'date_range':first['date_range'],
        'consumer_protocol':json.loads(Path(first['purpose']['path']).read_text())['consumer_protocol'],
        'source_acceptance':json.loads(Path(first['purpose']['path']).read_text())['source_acceptance'],
        'rights_source_refs':json.loads(Path(first['purpose']['path']).read_text())['rights_source_refs'],
        'rights':'INVENTED_PUBLIC_TEST'})
    cfg={'schema':'polar.reference-input-conversion-config/3','profile_id':PROFILE,'namespace':'INVENTED',
        'inputs':refs,'purpose':purpose,'schedule':first['schedule'],'date_range':first['date_range']}
    return tmp_path/'out',cfg


def test_compose_exact_original_lines_pointers_clock_graph_and_idempotency(tmp_path,monkeypatch):
    root,cfg=composition_fixture(tmp_path)
    before={}
    for pin in cfg['inputs']:
        m=json.loads(Path(pin['path']).read_text());before.update({(json.loads(l)['date'],json.loads(l)['symbol']):l
            for l in Path(m['quotes']['path']).read_bytes().splitlines(keepends=True)})
    # Original acquisition payloads are absent. Only already validated projections are required.
    import shutil
    for name in ['first','second']:shutil.rmtree(tmp_path/name/'source')
    root.mkdir()
    result=prepare_input(cfg,root,10**8);market=load_reference(result['input_ref'])
    assert market['symbols']==['AAA','BBB','DDD','EEE'] and result['rows']==12
    m=json.loads(Path(result['input_ref']['path']).read_text())
    for line in Path(m['quotes']['path']).read_bytes().splitlines(keepends=True):
        v=json.loads(line);assert line==before[v['date'],v['symbol']]
        assert v['observed_historical_available_at'] is v['observed_published_at'] is None
    assert len(m['conversion_metadata']['source_components'])==2
    assert schedule_binding_matches(m,cfg['schedule'])
    assert prepare_input(cfg,root,10**8)==result


@pytest.mark.parametrize('change,error',[
    ('extra','CONFIG'),('duplicate','DUPLICATE_INPUT'),('rights','RIGHTS'),
    ('symbols','SYMBOL_SET'),('dates','CALENDAR'),('namespace','RIGHTS')])
def test_metadata_failures_before_numeric_source_read(tmp_path,monkeypatch,change,error):
    root,cfg=composition_fixture(tmp_path)
    if change=='extra':cfg['unbound']=True
    elif change=='duplicate':cfg['inputs'][1]=cfg['inputs'][0]
    elif change=='namespace':cfg['namespace']='RETAINED'
    else:
        purpose=json.loads(Path(cfg['purpose']['path']).read_text())
        if change=='rights':purpose['rights']='PUBLIC'
        elif change=='symbols':purpose['symbols']=['AAA','BBB']
        else:
            cfg['date_range']={**cfg['date_range'],'count':2};purpose['date_range']=cfg['date_range']
        cfg['purpose']=put(tmp_path/'mutated-purpose.json',purpose)
    import polar.reference_composition as module
    def forbidden(*args,**kwargs):raise AssertionError('NUMERIC_SOURCE_OPEN')
    monkeypatch.setattr(module,'load_reference',forbidden)
    with pytest.raises(ValueError,match=error):prepare_input(cfg,root,10**8)
    assert not root.exists()


def test_overlapping_aliases_fail_closed(tmp_path):
    root,cfg=composition_fixture(tmp_path,second_targets=['BBB','CCC'])
    with pytest.raises(ValueError,match='SYMBOL_OVERLAP'):prepare_input(cfg,root,10**8)


def test_scaled_wealth_is_terminal_not_profit_and_vol_uses_d50_order(tmp_path,monkeypatch):
    from fractions import Fraction
    from test_scheduled_fixed import fixed_fixture
    import polar.scheduled_policy as module
    _,_,profile,_=fixed_fixture(tmp_path,monkeypatch)
    profile['criteria']=[{'id':i,'description':i,'kind':kind,'left_id':'THIRDS','right_id':'FULL','factor':factor}
        for i,kind,factor in [('wealth','TERMINAL_SCALED_GE',[9,10]),('vol','VOL_SCALED_LE',[4,5])]]
    module.profile_value(profile)
    ids=[leg['id'] for leg in profile['legs']]
    metrics={i:{k:{'value':'0'} for k in ('terminal_nav_usd','net_cagr_act36525','sharpe_252_rf0','max_drawdown','total_cost_usd','annual_vol_252')} for i in ids}
    exact={i:{'terminal':10000000,'max_drawdown':Fraction(0)} for i in ids}
    exact['THIRDS']['terminal']=9000000
    metrics['THIRDS']['annual_vol_252']['value']='0.08';metrics['FULL']['annual_vol_252']['value']='0.1'
    monkeypatch.setattr(module,'evaluate_legs',lambda _ :([{'id':i,'metrics':metrics[i]} for i in ids],exact))
    fake={'legs':[{'nav':[{},{}]}]}
    result=module.evaluate_policy(fake,profile,'FINAL');assert [c['status'] for c in result['criteria']]==['MET','MET']
    exact['THIRDS']['terminal']-=1
    metrics['THIRDS']['annual_vol_252']['value']='0.080000000000000000000000000000000000000000000000001'
    assert [c['status'] for c in module.evaluate_policy(fake,profile,'FINAL')['criteria']]==['NOT_MET','NOT_MET']
    metrics['FULL']['annual_vol_252']['value']=None
    assert module.evaluate_policy(fake,profile,'FINAL')['criteria'][1]['status']=='UNAVAILABLE'
    bad=deepcopy(profile);bad['criteria'][0]['factor']=[9,0]
    with pytest.raises(ValueError,match='FACTOR'):module.profile_value(bad)


def test_five_constant_accounts_native_and_stored_only_unchanged_path(tmp_path,monkeypatch):
    from test_scheduled_fixed import fixed_fixture
    from reference_fixture import write
    from polar.reference_service import ReferenceResearchService
    from polar.research_results import ResearchResults
    import polar.scheduled_service as module
    root,cfg,profile,_=fixed_fixture(tmp_path,monkeypatch)
    profile['legs'].insert(1,{**deepcopy(profile['legs'][0]),'id':'ALT_THIRDS','label':'Alternate thirds'})
    profile['additional_limitations']=[]
    profile['criteria'][1].update(kind='TERMINAL_SCALED_GE',factor=[9,10]);profile['criteria'][1].pop('threshold',None)
    profile['criteria'][2].update(kind='VOL_SCALED_LE',factor=[4,5]);profile['criteria'][2].pop('threshold',None)
    cfg['profile_ref']=write(tmp_path/'five-profile.json',profile)
    service=ReferenceResearchService(root,128*1024**2)
    assert service.preflight(cfg)['expected_native_accounts']==5
    result=service.run(cfg)
    assert result['status']=='SUCCESS' and result['native_accounts']==5
    assert result['fit_calls']==result['predict_calls']==result['model_calls']==0
    public=ResearchResults(root,128*1024**2).read(result['results']['FINAL']['result_id'])
    assert len(public['record']['series'])==5 and public['assessment']['financial']=='NOT_REVIEWED'
    def forbidden(*a,**k):raise AssertionError('STORED_SOURCE_POLICY_NATIVE_CALL')
    for name in ('load_reference','plan_phase','bounded_native'):monkeypatch.setattr(module,name,forbidden)
    replay=service.recompute(result['semantic_id'])
    assert replay['status']=='REPRODUCED' and replay['native_calls']==replay['store_writes']==0
