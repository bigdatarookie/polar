"""Invented annual rational policy: metadata gate, exact targets, saved-only replay."""
from copy import deepcopy
from datetime import date,datetime,time,timedelta,timezone
from fractions import Fraction
import json
from pathlib import Path

import pytest

from reference_fixture import write
from scheduled_fixture import fixture
from test_scheduled_service import snapshot
from polar.reference_service import ReferenceResearchService
from polar.scheduled_policy import profile_value,calendar_value,plan_phase
from polar.scheduled_fixed import diagnose_fixed
from polar.research_reference import load_reference
from polar.research_results import ResearchResults
from polar.research_allocation import desired_targets


def fixed_fixture(tmp_path,monkeypatch):
    root,cfg,profile,old=fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    schedule=json.loads(Path(manifest['schedule']['path']).read_bytes())['rows']
    days=[r['date'] for r in schedule]
    def event(day):
        i=days.index(day);entry=schedule[i]['next_reference_date']
        k=datetime.combine(date.fromisoformat(day)+timedelta(days=1),time(),tzinfo=timezone.utc)
        return {'formation_date':day,'K':k.isoformat(),'D':(k+timedelta(seconds=60)).isoformat(),
                'execution_date':entry,'reference_execution_close_utc':schedule[i+1]['reference_close_utc']}
    annual=[days[0],max(d for d in days if d.startswith('2018'))]
    calendar={'schema':'polar.prospective-fixed-allocation-calendar/1','parent_schedule':manifest['schedule'],
        'dates':days,'initial_date':days[0],'terminal_date':days[-1],'nav_points':len(days),'returns':len(days)-1,
        'annual_targets':[event(d) for d in annual],'terminal_EXIT':event(days[-2]),'clock_scope':'UTC_MIDNIGHT_PLUS_60S'}
    cp=write(tmp_path/'fixed-calendar.json',calendar)
    symbols=profile['symbols']
    thirds={s:([1,3] if s!='DDD' else [0,1]) for s in symbols}
    zero={s:[0,1] for s in symbols}
    profile.update(schema='polar.scheduled-reference-profile/5',protocol_id='INVENTED-FIXED-ANNUAL-V1',
        calendar_sha256=cp['sha256'],policy={'kind':'FIXED_ANNUAL_RATIONAL_WEIGHTS'},
        legs=[{'id':i,'label':i,'rule':'CASH' if i=='CASH' else 'FIXED_WEIGHTS','weights':w}
              for i,w in [('THIRDS',thirds),('FULL',{**zero,'AAA':[1,1]}),('THIRD',{**zero,'AAA':[1,3]}),('CASH',zero)]],
        primary_strategy='THIRDS',primary_benchmark='FULL',
        question_label='Invented exact fixed annual allocation',
        question_summary='Exact rational thirds on public invented reference closes; no signals or estimates.',
        clock_description='UTC next midnight, sixty seconds later decision, next reference close.',
        partition_description='FINAL only fresh capital; no training, validation, fitting or selection.',
        subperiods=[[days[0],annual[-1]],[days[days.index(annual[-1])+1],days[-1]]])
    for c in profile['criteria']:
        c['left_id']='THIRDS'
        if 'right_id' in c:c['right_id']='THIRD' if c['right_id']=='EW_HALF' else 'FULL'
        if c['kind']=='DRAWDOWN_LE':c.update(kind='DRAWDOWN_SCALED_LE',factor=[3,4])
    pp=write(tmp_path/'fixed-profile.json',profile)
    return root,{**cfg,'profile_ref':pp,'calendar_ref':cp,'candidate_id':'INVENTED-FIXED',
                 'experiment_id':'INVENTED-FIXED-ANNUAL-ORIGINAL'},profile,calendar


def test_annual_grid_exact_thirds_no_signal_future_dependence_and_exit(tmp_path,monkeypatch):
    _,cfg,profile,calendar=fixed_fixture(tmp_path,monkeypatch)
    market=load_reference(cfg['input_ref']);grid=calendar_value(calendar,market['schedule'])['FINAL']
    one=plan_phase(market,profile,grid,None)
    assert len(one['decisions'])==3 and not one['signals']
    assert all(x['kind']=='EXIT' for x in one['decisions'][-1]['instructions'].values())
    assert all(d['decision_ns']-d['known_ns']==60*10**9 and d['decision_ns']<d['open_ns'] for d in one['decisions'])
    weights=one['decisions'][0]['instructions']['THIRDS']['weights']
    assert weights['AAA']==[1,3] and weights['DDD']==[0,1]
    # Floor only the final exact quantity: a 12dp weight truncation loses one unit here.
    assert desired_targets(30000000,{'AAA':0},{'AAA':1000000000},{'AAA':Fraction(1,3)})['AAA']==100
    altered=deepcopy(market)
    for row in altered['prices_micro'].values():
        for s in row:row[s]*=17
    assert plan_phase(altered,profile,grid,None)['decisions']==one['decisions']
    bad=deepcopy(calendar);bad['annual_targets'].pop()
    with pytest.raises(ValueError,match='ANNUAL_GRID'):calendar_value(bad,market['schedule'])
    bad=deepcopy(calendar);bad['annual_targets'][0]['K']='2018-01-02T05:00:00+00:00'
    with pytest.raises(ValueError,match='FIXED_CLOCK'):calendar_value(bad,market['schedule'])
    bad=deepcopy(profile);bad['legs'][0]['weights']['DDD']=[1,1]
    with pytest.raises(ValueError,match='FIXED_WEIGHTS'):profile_value(bad)


def test_preflight_and_full_four_account_native_then_saved_only_reproduction(tmp_path,monkeypatch):
    root,cfg,profile,calendar=fixed_fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    actual=module.load_reference
    def forbidden(*a,**k):raise AssertionError('PRE_START_OR_STORED_SOURCE_POLICY_NATIVE_CALL')
    monkeypatch.setattr(module,'load_reference',forbidden)
    service=ReferenceResearchService(root,128*1024**2)
    ready=service.preflight(cfg)
    assert ready['expected_native_accounts']==4 and ready['scientific_starts']==0
    assert not (root/'scheduled-reference-attempts').exists()
    def after_start(*a,**k):
        assert len(list((root/'scheduled-reference-attempts').rglob('start.json')))==1
        return actual(*a,**k)
    monkeypatch.setattr(module,'load_reference',after_start)
    result=service.run(cfg)
    assert result['status']=='SUCCESS' and result['native_accounts']==4
    assert result['fit_calls']==result['predict_calls']==result['model_calls']==0
    assert set(result['results'])=={'FINAL'}
    r=ResearchResults(root,128*1024**2).read(result['results']['FINAL']['result_id'])
    assert len(r['record']['grid'])==400 and len(r['record']['series'])==4 and len(r['record']['criteria'])==5
    assert r['assessment']['financial']=='NOT_REVIEWED'
    diagnostic=json.loads((root/'reference-research-experiments'/result['semantic_id']/'diagnostics.json').read_bytes())['FINAL']
    assert diagnostic['CASH']['drawdown']['peak']['date']==calendar['initial_date']
    assert all(d['subperiods'][0]['status']=='OK' for d in diagnostic.values())
    before=snapshot(root)
    for name in ('load_reference','plan_phase','bounded_native'):monkeypatch.setattr(module,name,forbidden)
    replay=service.recompute(result['semantic_id'])
    assert replay['status']=='REPRODUCED' and replay['native_calls']==replay['store_writes']==0
    assert snapshot(root)==before
    with pytest.raises(ValueError,match='ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_fixed_saved_recipe_exact_marks_ties_zero_and_censored_drawdown():
    dates=['2020-01-01','2020-01-02','2020-01-03','2020-01-04']
    def tape(values):
        return {'id':'X','nav':[{'date':d,'nominal_ns':i*10**9,'sample_ns':i*10**9+1,'nav_cents':v,
            'cash_cents':v-2,'positions':{'AAA':1,'BBB':1},'position_cents':{'AAA':1,'BBB':1},
            'flat_cents':0,'bps_cents':0} for i,(d,v) in enumerate(zip(dates,values))],'fills':[]}
    prices={d:{'AAA':{'close_micro':10001},'BBB':{'close_micro':10001}} for d in dates}
    r=diagnose_fixed(tape([100,100,80,90]),[],prices)
    assert r['drawdown']['peak']['date']==dates[0] and r['drawdown']['trough']['date']==dates[2]
    assert r['drawdown']['censored_trough_to_terminal_intervals']==1
    assert r['drawdown']['trough_to_recovery_intervals'] is None
    assert r['exposure']['maximum_single_asset_point']=={'date':dates[2],'symbol':'AAA'}
    assert r['exposure']['maximum_single_asset_fraction']['value']!='0.0125'
    r=diagnose_fixed(tape([100,100,100,100]),[],prices)
    assert r['drawdown']['peak']==r['drawdown']['trough']==r['drawdown']['recovery']
    assert r['drawdown']['peak_to_recovery_intervals']==0
