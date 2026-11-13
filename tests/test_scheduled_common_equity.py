"""Public invented B10 portfolio controls; no retained inputs or economic outcomes."""
from copy import deepcopy
from fractions import Fraction
from decimal import Decimal,localcontext
import json
from pathlib import Path
import pytest
from test_reference_input import put
from test_scheduled_parking import profile as parking_profile
from polar.scheduled_common_equity import IDS
from polar.scheduled_policy import profile_value,evaluate_policy


def profile():
    p=parking_profile();p.update(schema='polar.scheduled-reference-profile/13',symbols=['BIL','SHY','VTI'],
        primary_strategy='VTI_BIL',primary_benchmark='VTI_SHY')
    weights=[[[2,3],[0,1],[1,3]],[[0,1],[2,3],[1,3]],[[0,1],[0,1],[1,1]],[[0,1],[0,1],[0,1]]]
    p['legs']=[{'id':i,'label':i,'rule':'CASH' if i=='CASH' else 'FIXED_WEIGHTS',
                'weights':dict(zip(p['symbols'],w))} for i,w in zip(IDS,weights)]
    for c in p['criteria']:
        c['left_id']='VTI_BIL'
        if 'right_id' in c:c['right_id']='VTI_SHY'
        if 'factor' in c:c['factor']=[9,10]
    return p


def test_closed_weights_thresholds_empty_eras_and_typed_metadata():
    p=profile();assert profile_value(p)==p
    for change in [lambda p:p['legs'][0]['weights'].update(VTI=[True,3]),
                   lambda p:p['legs'][0]['weights'].update(VTI=[1,2]),
                   lambda p:p['criteria'][2].update(factor=[1,2]),
                   lambda p:p['criteria'][3].update(factor=[4,5]),
                   lambda p:p.update(subperiods=[['2020-12-31','2021-01-04']]),
                   lambda p:p.update(primary_benchmark='VTI_FULL'),
                   lambda p:p['cost_scenarios'][1]['cost_profile'].update(flat_cents=100)]:
        q=deepcopy(p);change(q)
        with pytest.raises(ValueError):profile_value(q)


def test_exact_criteria_boundary_status_precedence_and_structural_first(monkeypatch):
    import polar.scheduled_policy as m
    from polar.ci_research_evaluation import context
    p=profile();nav=[{'date':d,'nominal_ns':n,'sample_ns':n+1,'nav_cents':10000000,'cash_cents':10000000,
                     'positions':{'BIL':0,'SHY':0,'VTI':0},'exposure_cents':0} for n,d in enumerate(['2020-01-01','2020-01-02'])]
    sim={'legs':[{'id':i,'nav':deepcopy(nav)} for i in IDS]}
    metrics={i:{k:{'value':'0'} for k in ('terminal_nav_usd','net_cagr_act36525','sharpe_252_rf0','max_drawdown','total_cost_usd','annual_vol_252')} for i in IDS}
    exact={i:{'terminal':20000000,'max_drawdown':Fraction(1,10)} for i in IDS}
    exact['VTI_BIL'].update(terminal=18000000,max_drawdown=Fraction(9,100))
    vol='0.12345678901234567890123456789012345678901234567891'
    with localcontext(context()):edge=Decimal(vol)*9/10
    metrics['VTI_SHY']['annual_vol_252']['value']=vol;metrics['VTI_BIL']['annual_vol_252']['value']=str(edge)
    monkeypatch.setattr(m,'evaluate_legs',lambda _:([{'id':i,'metrics':metrics[i]} for i in IDS],exact))
    got=evaluate_policy(sim,p,'FINAL');assert [c['status'] for c in got['criteria']]==['MET']*5
    exact['VTI_BIL']['terminal']-=1;metrics['VTI_BIL']['sharpe_252_rf0']['value']=None
    got=evaluate_policy(sim,p,'FINAL');assert got['criteria'][0]['status']=='NOT_MET' and got['criteria'][1]['status']=='UNAVAILABLE'
    assert got['point_interpretation']=='NOT_SUPPORTIVE_ON_THIS_LIMITED_SCREEN'
    exact['VTI_BIL']['terminal']+=1;assert evaluate_policy(sim,p,'FINAL')['point_interpretation']=='INDETERMINATE'
    with localcontext(context()):metrics['VTI_BIL']['annual_vol_252']['value']=str(edge+Decimal('1e-50'))
    assert evaluate_policy(sim,p,'FINAL')['criteria'][3]['status']=='NOT_MET'
    exact['VTI_BIL']['max_drawdown']=Fraction(0);exact['VTI_SHY']['max_drawdown']=Fraction(0)
    metrics['VTI_BIL']['annual_vol_252']['value']=metrics['VTI_SHY']['annual_vol_252']['value']='0'
    assert [c['status'] for c in evaluate_policy(sim,p,'FINAL')['criteria']][2:4]==['MET','MET']
    def forbidden(_):raise AssertionError('SCALAR_BEFORE_STRUCTURAL')
    monkeypatch.setattr(m,'evaluate_legs',forbidden);bad=deepcopy(sim);bad['legs'][0]['nav'][-1]['positions']['VTI']=1
    with pytest.raises(ValueError,match='TERMINAL_NOT_CASH'):evaluate_policy(bad,p,'FINAL')


def test_eight_fresh_native_accounts_core18_wire_bounds_and_source_absent_replay(tmp_path,monkeypatch):
    from scheduled_fixture import fixture
    from test_selected_reference_composition import selected_composition_fixture
    from test_scheduled_service import snapshot
    from polar.reference_input import prepare_input
    from polar.research_reference import load_reference
    from polar.reference_service import ReferenceResearchService
    from polar.research_results import ResearchResults
    from datetime import datetime,timedelta
    root,base,_,_=fixture(tmp_path,monkeypatch)
    sub=tmp_path/'three-symbols';sub.mkdir();store,cfg=selected_composition_fixture(sub)
    input_ref=prepare_input(cfg,store,10**8)['input_ref'];market=load_reference(input_ref);days=market['dates'];rows=market['schedule']
    def event(i):
        k=datetime.fromisoformat(days[i]+'T00:00:00+00:00')+timedelta(days=1)
        return {'formation_date':days[i],'K':k.isoformat(),'D':(k+timedelta(seconds=60)).isoformat(),
                'execution_date':days[i+1],'reference_execution_close_utc':rows[i+1]['reference_close_utc']}
    cal={'schema':'polar.prospective-fixed-allocation-calendar/1','parent_schedule':cfg['schedule'],'dates':days,
        'initial_date':days[0],'terminal_date':days[-1],'nav_points':len(days),'returns':len(days)-1,
        'annual_targets':[event(0)],'terminal_EXIT':event(len(days)-2),'clock_scope':'UTC_MIDNIGHT_PLUS_60S'}
    cp=put(sub/'calendar.json',cal);p=profile();p.update(protocol_sha256=base['protocol_ref']['sha256'],
        input_sha256=input_ref['sha256'],calendar_sha256=cp['sha256'],timezone_sha256=base['timezone_ref']['sha256'])
    runconfig={**base,'input_ref':input_ref,'calendar_ref':cp,'profile_ref':put(sub/'profile13.json',p),
        'candidate_id':'INVENTED-B10','experiment_id':'INVENTED-B10-EIGHT-FRESH'}
    service=ReferenceResearchService(root,128*1024**2)
    import polar.scheduled_service as module
    load=module.load_market
    def forbidden(*a,**k):raise AssertionError('SOURCE_POLICY_NATIVE_DURING_PREFLIGHT_OR_SAVED')
    monkeypatch.setattr(module,'load_market',forbidden)
    preflight=service.preflight(runconfig)
    assert preflight['expected_native_accounts']==8 and preflight['feature_calls']==0
    monkeypatch.setattr(module,'load_market',load)
    result=service.run(runconfig);assert result['status']=='SUCCESS' and result['native_accounts']==8 and result['feature_calls']==0
    home=root/'reference-research-experiments'/result['semantic_id']
    phases=json.loads((home/'phases.json').read_bytes());diagnostics=json.loads((home/'diagnostics.json').read_bytes())
    for phase,data in phases.items():
        assert [l['id'] for l in data['simulation']['legs']]==IDS
        assert all(len(l['metrics'])==18 for l in data['evaluation']['legs'])
        assert data['simulation']['legs'][0]['intents'][0]['sizing_witness']['quantity_unit']=='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE'
        from polar.model_price_consumed import verify
        from polar.scheduled_policy import calendar_value
        plan=data['plan'];sim=data['simulation']
        saved_calendar={**cal,'source_schedule_rows':rows}
        assert verify(plan,sim,p,saved_calendar)['status']=='VERIFIED_NEW_FIXED_CONSUMED_OPERANDS'
        bad=deepcopy(sim);bad['legs'][0]['nav'][1]['position_cents']['VTI']+=1
        with pytest.raises(ValueError,match='PARKING_CONSUMED_METRIC_BINDING'):verify(plan,bad,p,saved_calendar)
        bad=deepcopy(sim);bad['legs'][0]['intents'][0]['sizing_witness']['nav_cents']+=1
        with pytest.raises(ValueError,match='D_OPERANDS_FLOOR'):verify(plan,bad,p,saved_calendar)
        assert len(plan['symbols'])==3 and all(len(d['instructions'])==4 for d in plan['decisions'])
        assert not any(d['subperiods'] for d in diagnostics[phase].values())
        record=ResearchResults(root,128*1024**2).read(result['results'][phase]['result_id'])['record']
        assert len(record['metrics'])<=37 and len(record['limitations'])<=30 and len(record['series'])==4
        if phase=='FINAL_COST_STRESS':
            assert all(d['status']=='NOT_REQUESTED' for d in diagnostics[phase].values())
            assert len(record['metrics'])==18
        else:
            assert 'drawdown' in diagnostics[phase]['VTI_BIL'] and len(record['metrics'])==29
    assert phases['FINAL']['simulation']['legs'][0]['fills'][0]['fee_cents']!=phases['FINAL_COST_STRESS']['simulation']['legs'][0]['fills'][0]['fee_cents']
    before=snapshot(root)
    for name in ('load_market','load_reference','plan_phase','bounded_native'):monkeypatch.setattr(module,name,forbidden)
    replay=service.recompute(result['semantic_id']);assert replay['status']=='REPRODUCED'
    assert replay['native_calls']==replay['store_writes']==replay['feature_calls']==0 and snapshot(root)==before
