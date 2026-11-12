"""Invented A2 daily state/clock/native/accounting path; no retained policy data."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from polar.research_reference import load_reference
from polar.scheduled_policy import calendar_value, plan_phase, evaluate_policy
from scheduled_fixture import sma_fixture


def test_sma_nofit_two_phases_counts_publication_and_stored_only(tmp_path,monkeypatch):
    root,cfg,p,c=sma_fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    assert service.preflight(cfg)['expected_native_accounts']==8
    output=service.run(cfg)
    assert output['status']=='SUCCESS' and output['native_accounts']==8
    assert output['fit_calls']==output['predict_calls']==output['model_calls']==0
    directory=root/'reference-research-experiments'/output['semantic_id']
    phases=json.loads((directory/'phases.json').read_bytes())
    month_ends={r['date']:r['month_end_in_reference_range'] for r in load_reference(cfg['input_ref'])['schedule']}
    for name,data in phases.items():
        n=len(c['phases'][name]['nav_dates']);plan=data['plan'];counts=plan['gate_accounting']
        assert len(plan['signals'])==counts['observations']==n-2
        assert len(plan['decisions'])==n-1
        assert plan['signals'][0]['first_observation'] and plan['signals'][0]['previous_observed_active'] is None
        assert all(counts['target_count'][i]+counts['hold_count'][i]==n-2 and counts['exit_count'][i]==1 for i in plan['profile']['legs'])
        assert all(not any(t['nav'][-1]['positions'].values()) for t in data['simulation']['legs'])
        for d in plan['decisions'][:-1]:
            month_end=month_ends[d['formation']]
            assert (d['instructions']['EW']['kind']=='TARGET') == month_end
        detail=ResearchResults(root,128*1024**2).read(output['results'][name]['result_id']);record=detail['record']
        assert len(record['series'])==4 and len(record['grid'])==n
        assert len(record['metrics'])==(40 if name=='FINAL' else 32)
        assert len(record['criteria'])==(5 if name=='FINAL' else 0)
        assert any(x['id']=='daily_gate_hold_count' for x in record['metrics'])
        assert any(x['code']=='DAILY_GATE_STATE_ACCOUNTING' for x in record['limitations'])
        assert not any(x['role']=='trained_model' for x in record['provenance'])
        assert detail['assessment']['financial']=='NOT_REVIEWED'
    before={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
    import polar.scheduled_service as module
    def forbidden(*a,**kw):raise AssertionError('STORED_ONLY_CALLED_POLICY_SOURCE_NATIVE')
    for key in ('plan_phase','bounded_native','load_reference'):monkeypatch.setattr(module,key,forbidden)
    reproduced=service.recompute(output['semantic_id'])
    assert reproduced['status']=='REPRODUCED' and all(reproduced[k]==0 for k in ('native_calls','fit_calls','predict_calls','store_writes'))
    assert before=={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_sma_observed_vector_first_change_monthend_hold_and_future_firewall(tmp_path,monkeypatch):
    _,cfg,p,c=sma_fixture(tmp_path,monkeypatch);market=load_reference(cfg['input_ref']);grids=calendar_value(c,market['schedule']);g=grids['FINAL'];tz=ZoneInfo('America/New_York')
    first=g['decisions'][0]['signal_index'];days=market['dates'];symbols=p['symbols']
    # Independent literal 200-flat window: equality inactive, then a single
    # strictly higher close activates only AAA, followed by an unchanged vector.
    market['prices_micro']={d:{s:10000000 for s in symbols} for d in days}
    market['prices_micro'][days[first+1]]['AAA']=11000000
    market['prices_micro'][days[first+2]]['AAA']=11000000
    plan=plan_phase(market,p,g,tz);a,b,d=plan['decisions'][:3]
    assert plan['signals'][0]['active']=={s:False for s in symbols}
    assert a['instructions']['SMA']['kind']=='TARGET'
    assert a['instructions']['SMA']['signal']['target_triggers']==['FIRST','MONTH_END']
    assert b['instructions']['SMA']['kind']=='TARGET' and plan['signals'][1]['vector_changed']
    assert b['instructions']['SMA']['weights']=={s:([1,4] if s=='AAA' else [0,1]) for s in symbols}
    assert plan['signals'][2]['previous_observed_active']==plan['signals'][1]['active']
    assert d['instructions']['SMA']['kind']=='HOLD' and not plan['signals'][2]['vector_changed']
    assert b['instructions']['EW']=={'kind':'HOLD'} and d['instructions']['EW_HALF']=={'kind':'HOLD'}
    assert all(x['kind']=='EXIT' for x in plan['decisions'][-1]['instructions'].values())
    changed=deepcopy(market)
    for day in days[first+1:]:changed['prices_micro'][day]={s:999999999 for s in symbols}
    second=plan_phase(changed,p,g,tz)
    assert plan['decisions'][0]==second['decisions'][0] and plan['signals'][0]==second['signals'][0]
    assert all(x['known_ns']<x['decision_ns']<x['open_ns'] for x in plan['decisions'])


def test_sma_hold_is_observed_state_not_fill_success(tmp_path,monkeypatch):
    from polar.ci_research_native import simulate
    from polar.research_allocation import desired_targets
    _,cfg,p,c=sma_fixture(tmp_path,monkeypatch);market=load_reference(cfg['input_ref']);g=calendar_value(c,market['schedule'])['FINAL'];tz=ZoneInfo('America/New_York')
    first=g['decisions'][0]['signal_index'];execution=market['dates'][first+1]
    market['prices_micro'][execution]={s:110000000000 for s in p['symbols']}
    plan=plan_phase(market,p,g,tz)
    assert plan['decisions'][0]['instructions']['SMA']['kind']=='TARGET'
    assert plan['decisions'][1]['instructions']['SMA']['kind']=='HOLD'
    tape=next(x for x in simulate(plan)['legs'] if x['id']=='SMA')
    assert not any(f['id'].split('/')[1]==execution for f in tape['fills'])
    assert plan['signals'][1]['previous_observed_active']==plan['signals'][0]['active']
    assert desired_targets(10000000,{s:0 for s in p['symbols']},{s:20000000 for s in p['symbols']},{s:Fraction(1,4) for s in p['symbols']})=={s:1250 for s in p['symbols']}


@pytest.mark.parametrize('mutation',['missing','reordered','terminal','wrong_reference'])
def test_sma_daily_calendar_rejects_missing_reordered_or_terminal_observation(tmp_path,monkeypatch,mutation):
    _,cfg,p,c=sma_fixture(tmp_path,monkeypatch);m=load_reference(cfg['input_ref']);g=c['phases']['FINAL']
    if mutation=='missing':g['daily_gate_decisions'].pop()
    elif mutation=='reordered':g['daily_gate_decisions'][:2]=reversed(g['daily_gate_decisions'][:2])
    elif mutation=='terminal':g['daily_gate_decisions'].append({'formation':g['terminal_decision_reference'],'execution_day':g['terminal']})
    else:g['terminal_decision_reference']=g['initial']
    with pytest.raises(ValueError,match='SCHEDULED_DAILY_DECISION_GRID'):calendar_value(c,m['schedule'])


def test_sma_drawdown_uses_exact_four_fifths_boundary(tmp_path,monkeypatch):
    _,_,p,_=sma_fixture(tmp_path,monkeypatch)
    import polar.scheduled_policy as module
    ids=[x['id'] for x in p['legs']]
    metrics={i:{k:{'value':'0.2' if i=='SMA' else '0.1'} for k in ('sharpe_252_rf0','terminal_nav_usd','net_cagr_act36525','max_drawdown','total_cost_usd')} for i in ids}
    exact={i:{'terminal':10000001 if i=='SMA' else 10000000,'max_drawdown':Fraction(1,5) if i=='SMA' else Fraction(1,4)} for i in ids}
    monkeypatch.setattr(module,'evaluate_legs',lambda s:([{'id':i,'metrics':metrics[i]} for i in ids],exact))
    result=evaluate_policy({'legs':[{'nav':[{},{}]}]},p,'FINAL');assert all(x['status']=='MET' for x in result['criteria'])
    exact['SMA']['max_drawdown']=Fraction(2000001,10000000)
    assert evaluate_policy({'legs':[{'nav':[{},{}]}]},p,'FINAL')['criteria'][-1]['status']=='NOT_MET'
