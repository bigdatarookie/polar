"""Invented B2 same-engine orchestration, accounting and saved certificate path."""
from copy import deepcopy
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

import pytest
from polar.gym_contract import canonical
from polar.reference_service import ReferenceResearchService
from polar.research_reference import load_reference
from polar.research_results import ResearchResults
from polar.scheduled_policy import calendar_value,plan_phase,optimization_counts,profile_value
from polar.scheduled_signals import shrunk_gmv_targets,verify_gmv_signal,AllocationError
from scheduled_fixture import gmv_fixture


def test_gmv_full_service_one_plan_true_stress_certificates_counts_and_stored_only(tmp_path,monkeypatch):
    root,cfg,profile,calendar=gmv_fixture(tmp_path,monkeypatch)
    service=ReferenceResearchService(root,128*1024**2)
    n=len(calendar['phases']['FINAL']['decisions'])
    ready=service.preflight(cfg)
    assert ready['expected_native_accounts']==6 and ready['expected_optimizer_counts']=={
        'covariance_estimates':n,'spd_certifications':n,'portfolio_optimizations':n,'support_linear_system_attempts':15*n}
    import polar.scheduled_gmv as solver
    original=solver.solve;calls=[]
    def observed(matrix):
        assert len(list((root/'scheduled-reference-attempts').glob('*/*/start.json')))==1
        calls.append(1)
        return original(matrix)
    monkeypatch.setattr(solver,'solve',observed)
    result=service.run(cfg)
    assert len(calls)==n and result['actual_optimizer_counts']==ready['expected_optimizer_counts']
    assert result['fit_calls']==result['predict_calls']==result['model_calls']==0 and result['native_accounts']==6
    directory=root/'reference-research-experiments'/result['semantic_id']
    phases=json.loads((directory/'phases.json').read_bytes());base=phases['FINAL'];stress=phases['FINAL_COST_STRESS']
    assert {k:v for k,v in base['plan'].items() if k!='cost_profile'}=={k:v for k,v in stress['plan'].items() if k!='cost_profile'}
    assert stress['plan']['cost_profile']=={'flat_cents':200,'bps':20}
    assert all(len(s['certificate']['supports'])==15 and verify_gmv_signal(s,profile['symbols']) for s in base['plan']['signals'])
    assert json.loads((directory/'uncertainty.json').read_bytes())['seed']==37002
    for phase,pub in result['results'].items():
        record=ResearchResults(root,128*1024**2).read(pub['result_id'])['record']
        assert len(record['series'])==3 and len(record['criteria'])==10
        assert any(x['role']=='portfolio_optimizer' for x in record['provenance'])
        assert any(x['code']=='PORTFOLIO_OPTIMIZATION_ACCOUNTING' for x in record['limitations'])
        assert not any(x['role']=='trained_model' for x in record['provenance'])
    before={str(p):sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    def forbidden(*a,**k):raise AssertionError('STORED_ONLY_EXECUTION')
    import polar.scheduled_service as module
    for key in ('load_reference','plan_phase','bounded_native'):monkeypatch.setattr(module,key,forbidden)
    for key in ('solve','_gauss_jordan','_ldl'):monkeypatch.setattr(solver,key,forbidden)
    reproduced=service.recompute(result['semantic_id'])
    assert reproduced['status']=='REPRODUCED' and all(v==0 for v in reproduced['actual_optimizer_counts'].values())
    assert all(reproduced[k]==0 for k in ('native_calls','store_writes','fit_calls','predict_calls'))
    assert before=={str(p):sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_gmv_causal_prefix_projection_and_tampered_certificate(tmp_path,monkeypatch):
    _,cfg,p,c=gmv_fixture(tmp_path,monkeypatch);market=load_reference(cfg['input_ref']);g=c['phases']['FINAL']
    plan=plan_phase(market,p,g,ZoneInfo('America/New_York'));cut=g['decisions'][0]['signal_index']
    altered=deepcopy(market)
    for day in market['dates'][cut+1:]:altered['prices_micro'][day]={s:999999999 for s in p['symbols']}
    second=plan_phase(altered,p,g,ZoneInfo('America/New_York'))
    assert plan['signals'][0]==second['signals'][0] and plan['decisions'][0]==second['decisions'][0]
    bad=deepcopy(plan['signals'][0]);bad['certificate']['weights'][0]['numerator']='999'
    with pytest.raises(ValueError,match='CERTIFICATE_VERIFY'):verify_gmv_signal(bad,p['symbols'])
    bad=deepcopy(plan['signals'][0]);bad['common_tau_binary64']='0.01'
    with pytest.raises(ValueError,match='SAVED_PROJECTION'):verify_gmv_signal(bad,p['symbols'])


def test_gmv_preflight_no_optimizer_failure_partial_and_duplicate_preserved(tmp_path,monkeypatch):
    root,cfg,p,c=gmv_fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    import polar.scheduled_gmv as solver
    original=solver.solve;calls=[]
    def fail_second(matrix):
        calls.append(1)
        if len(calls)==2:return original([[1.,2.,0.,0.],[2.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]])
        return original(matrix)
    monkeypatch.setattr(solver,'solve',fail_second)
    service.preflight(cfg);assert calls==[]
    # The short fixture may contain only two formations; fail at the second.
    with pytest.raises(AllocationError):service.run(cfg)
    finishes=list((root/'scheduled-reference-attempts').glob('*/*/finish/record.json'))
    finish=json.loads(finishes[0].read_bytes())
    assert finish['status']=='FAILED_UNFINALIZED' and finish['refund'] is False
    assert finish['actual_optimizer_counts']=={'covariance_estimates':2,'spd_certifications':2,
        'portfolio_optimizations':1,'support_linear_system_attempts':15}
    diagnostics=json.loads(finishes[0].with_name('diagnostics.json').read_bytes())
    assert len(diagnostics['completed_signals'])==1 and diagnostics['failed_signal']['certificate']['status']=='INVALID'
    assert not list((root/'research-results').glob('*'))
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


@pytest.mark.parametrize('mutation',['shrinkage','solver','seed','rule','delay'])
def test_gmv_profile_is_explicit_and_closed(tmp_path,monkeypatch,mutation):
    _,_,p,_=gmv_fixture(tmp_path,monkeypatch)
    if mutation=='shrinkage':p['policy']['shrinkage']=[1,3]
    elif mutation=='solver':p['policy']['solver']='PSEUDOINVERSE'
    elif mutation=='seed':p['uncertainty']['seed']=37001
    elif mutation=='rule':p['legs'][0]['rule']='MOMENTUM'
    else:p['decision_delay_seconds']=60
    with pytest.raises(ValueError):profile_value(p)


def test_gmv_47_literal_invented_formations_account_705_supports():
    symbols=['A','B','C','D']
    rows=[{s:10000000+(t*7919*(i+1)+t*t*101+i*917)%3000000 for i,s in enumerate(symbols)} for t in range(61)]
    signals=[shrunk_gmv_targets(rows,symbols)['diagnostics'] for _ in range(47)]
    assert optimization_counts(signals)=={'covariance_estimates':47,'spd_certifications':47,
        'portfolio_optimizations':47,'support_linear_system_attempts':705}
    assert all(len(s['certificate']['supports'])==15 for s in signals)
    assert all(float(s['post_round_risk_spread_binary64'])<=1e-8 for s in signals)
