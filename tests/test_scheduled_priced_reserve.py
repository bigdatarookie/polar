"""Invented finite shared-rule, native service and immutable saved verification proof."""
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from polar import qb_priced_reserve_prototype as author
from polar import scheduled_priced_reserve as priced
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from polar.scheduled_policy import profile_value, plan_phase
from polar.research_reference import load_reference
from polar.scheduled_signals import AllocationError
from reference_fixture import write
from scheduled_fixture import inverse_fixture


def fixture(tmp_path,monkeypatch):
    root,cfg,p,c=inverse_fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    quotes=Path(manifest['quotes']['path'])
    rows=[json.loads(line) for line in quotes.read_text().splitlines()]
    mapping={'AAA':'BIL','BBB':'VTI'}
    rows=[{**r,'symbol':mapping[r['symbol']]} for r in rows if r['symbol'] in mapping]
    # Invented unequal return geometry, with no external source or private dates.
    for i,row in enumerate(rows):
        day=i//2
        token=(f'{10+day//100}.{day%100:02d}0000' if row['symbol']=='BIL' else
               f'{20+(day*13)%7}.{(day*7919)%1000000:06d}')
        row['reference_quote']=token;row['source_adjusted_close_token']=token
    quotes.write_bytes(b''.join((json.dumps(r,sort_keys=True,separators=(',',':'))+'\n').encode() for r in rows))
    manifest['quotes']={'path':str(quotes),'sha256':sha256(quotes.read_bytes()).hexdigest(),'bytes':quotes.stat().st_size}
    manifest['symbols']=['BIL','VTI'];manifest['rows']=len(rows)
    mp=write(tmp_path/'priced-input.json',manifest)
    p.update(schema=priced.SCHEMA,protocol_id=author.PROTOCOL_ID,input_sha256=mp['sha256'],symbols=['BIL','VTI'],
        policy=dict(kind=priced.KIND,lookback=60,annual_cap='0.10',weight_units=1_000_000,prototype_sha256=priced.PROTOTYPE_SHA256),
        legs=[dict(id=i,label=i,rule=i,scale=[1,1]) for i in priced.IDS],
        primary_strategy='SWEPT',primary_benchmark='CASH_TARGET',subperiods=[],additional_limitations=[],
        uncertainty=dict(kind='PAIRED_CIRCULAR_SAVED_RETURNS',block=63,replicates=1000,seed=37004),
        criteria=[dict(id='C'+str(i),description='Frozen invented screen '+str(i),left_id='SWEPT',**spec)
                  for i,spec in enumerate(priced.SPECS)])
    pp=write(tmp_path/'priced-profile.json',p)
    return root,{**cfg,'profile_ref':pp,'input_ref':mp,'candidate_id':'INVENTED-PRICED','experiment_id':'INVENTED-PRICED-ORIGINAL'},p,c


def diagnostic(matrix):
    rule=author.reserve_targets(matrix)
    gap=Fraction(*rule['certificate']['target_variance'])-Fraction(*rule['certificate']['selected_variance'])
    return dict(forecast_variance_gap=[gap.numerator,gap.denominator],kind=priced.KIND,prototype_sha256=priced.PROTOTYPE_SHA256,
        annual_covariance_binary64=[[repr(float(x)) for x in row] for row in matrix],rule=rule,
        actual_counts=dict(estimator_calls=1,completed_estimates=1,rule_calls=1,completed_rules=1,
                           risk_evaluations=rule['certificate']['priced_reserve_risk_evaluations']))


@pytest.mark.parametrize('matrix',[
    [[0.0001,0.0],[0.0,0.04]], [[0.04,0.04],[0.04,0.04]],
    [[0.01,0.0],[0.0,0.0]], [[0.0,0.0],[0.0,0.0]],
    [[0.04,-0.04],[-0.04,0.04]], [[0.0,0.0],[0.0,0.04]]])
def test_exact_certificate_no_selection(matrix,monkeypatch):
    signal=diagnostic(matrix)
    def forbidden(*a,**k):raise AssertionError('SAVED_RULE_SEARCH')
    monkeypatch.setattr(author,'reserve_targets',forbidden);monkeypatch.setattr(author,'_select',forbidden)
    weights=priced.verify_signal(signal)
    assert weights['CASH_TARGET']['BIL']==0 and sum(weights['BIL_ONLY'].values())==1
    if signal['rule']['status']!='PRICED_RESERVE_GRID_FEASIBLE':
        assert weights['SWEPT']==weights['CASH_TARGET']


@pytest.mark.parametrize('field',['selected_variance','next_grid_variance','grid_minimum_variance','cash_grid_index','swept_equity_grid_index'])
def test_certificate_mutations(field):
    signal=diagnostic([[0.0001,0.0],[0.0,0.04]])
    c=signal['rule']['certificate'];c[field]=0 if field.endswith('index') else [999,1]
    with pytest.raises(ValueError):priced.verify_signal(signal)


@pytest.mark.parametrize('matrix', [[[float('nan'),0.0],[0.0,1.0]],[[1.,2.],[2.,1.]],[[1.,0.],[1.,1.]], [[-1.,0.],[0.,1.]]])
def test_invalid_geometry_is_typed_after_estimator(matrix,monkeypatch):
    monkeypatch.setattr(priced,'sample_covariance',lambda *a,**k:(None,None,matrix))
    with pytest.raises(AllocationError) as error:priced.targets([],['BIL','VTI'])
    assert error.value.events['status']=='INVALID'
    assert error.value.events['actual_counts']==dict(estimator_calls=1,completed_estimates=1,rule_calls=1,completed_rules=0,risk_evaluations=0)


def test_service_actual_author_native_stress_saved_source_absent_and_duplicate(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    original=author.reserve_targets; calls=[]
    def observed(matrix):
        assert list((root/'scheduled-reference-attempts').glob('*/*/start.json'))
        calls.append(1);return original(matrix)
    monkeypatch.setattr(author,'reserve_targets',observed)
    ready=service.preflight(cfg);assert ready['expected_native_accounts']==6 and calls==[]
    result=service.run(cfg);assert result['status']=='SUCCESS'
    assert len(calls)==len(c['phases']['FINAL']['decisions']) and 'native_accounts' not in result
    directory=root/'reference-research-experiments'/result['semantic_id']
    phases=json.loads((directory/'phases.json').read_bytes());base=phases['FINAL'];stress=phases['FINAL_COST_STRESS']
    assert {k:v for k,v in base['plan'].items() if k!='cost_profile'}=={k:v for k,v in stress['plan'].items() if k!='cost_profile'}
    assert stress['simulation']['cost_profile']==dict(flat_cents=200,bps=20)
    uncertainty=json.loads((directory/'uncertainty.json').read_bytes())
    assert [x['benchmark_id'] for x in uncertainty['comparisons']]==['CASH_TARGET'] and uncertainty['seed']==37004
    for data in phases.values():
        assert len(data['evaluation']['criteria'])==6
        assert all(x['metric_id']=='terminal_nav_usd' for x in data['evaluation']['comparisons'] if x['right_id']=='BIL_ONLY')
        for leg in data['simulation']['legs']:
            cost=data['simulation']['cost_profile']
            for fill in leg['fills']:
                assert type(fill['q']) is int and fill['q']>0
                assert fill['fee_cents']==cost['flat_cents']+(fill['q']*fill['price_micro']*cost['bps']+99_999_999)//100_000_000
                cents,remainder=divmod(fill['q']*fill['price_micro'],10000)
                assert fill['settled_cents']==cents+int(remainder>5000 or remainder==5000 and cents%2==1)
            assert leg['nav'][-1]['flat_cents']==len(leg['fills'])*cost['flat_cents']
            assert not any(leg['nav'][-1]['positions'].values()) and leg['nav'][-1]['nav_cents']==leg['nav'][-1]['cash_cents']
    for pub in result['results'].values():
        record=ResearchResults(root,128*1024**2).read(pub['result_id'])['record']
        assert len(record['criteria'])==6 and len(record['series'])==3
        assert any(x['code']=='PRICED_RESERVE_FORECAST_CERTIFICATE' for x in record['limitations'])
    finishes=list((root/'scheduled-reference-attempts').glob('*/*/finish/record.json'))
    finish=json.loads(finishes[0].read_bytes());assert finish['native_accounts']==6
    assert finish['actual_priced_reserve_counts']==priced.counts(base['plan']['signals'])
    source=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    Path(source['quotes']['path']).unlink();Path(source['schedule']['path']).unlink()
    for ref in ('input_ref','profile_ref','protocol_ref','calendar_ref','timezone_ref'):
        Path(cfg[ref]['path']).unlink()
    before={str(path):sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}
    def forbidden(*a,**k):raise AssertionError('SAVED_EXECUTION_OR_SOURCE')
    import polar.scheduled_service as module
    for name in ('load_reference','load_market','plan_phase','bounded_native','read_ref'):
        monkeypatch.setattr(module,name,forbidden)
    monkeypatch.setattr(priced,'sample_covariance',forbidden)
    monkeypatch.setattr(author,'reserve_targets',forbidden);monkeypatch.setattr(author,'_select',forbidden)
    reproduced=service.recompute(result['semantic_id'])
    assert reproduced['status']=='REPRODUCED' and all(reproduced[k]==0 for k in
        ('estimator_calls','rule_calls','risk_search_calls','native_calls','store_writes'))
    assert before=={str(path):sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}


def test_preflight_quotes_absent_profile_closed_and_causal_prefix(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch);market=load_reference(cfg['input_ref'])
    plan=plan_phase(market,p,c['phases']['FINAL'],ZoneInfo('America/New_York'))
    other=deepcopy(market);cut=c['phases']['FINAL']['decisions'][0]['signal_index']
    for d in other['dates'][cut+1:]:other['prices_micro'][d]={'BIL':999000000,'VTI':777000000}
    second=plan_phase(other,p,c['phases']['FINAL'],ZoneInfo('America/New_York'))
    assert plan['signals'][0]==second['signals'][0] and plan['decisions'][0]==second['decisions'][0]
    manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes());Path(manifest['quotes']['path']).unlink()
    assert ReferenceResearchService(root,128*1024**2).preflight(cfg)['policy_execution']=='NOT_RUN'
    for key,value in [('weight_units',100),('annual_cap','0.11'),('prototype_sha256','0'*64)]:
        bad=deepcopy(p);bad['policy'][key]=value
        with pytest.raises(ValueError):profile_value(bad)


def test_invalid_partial_debit_and_duplicate(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    original=author.reserve_targets;calls=[]
    def fail(matrix):
        calls.append(1)
        if len(calls)==2:raise author.PricedReserveError('NON_PSD_COVARIANCE')
        return original(matrix)
    monkeypatch.setattr(author,'reserve_targets',fail)
    with pytest.raises(AllocationError):service.run(cfg)
    finishpath=next((root/'scheduled-reference-attempts').glob('*/*/finish/record.json'))
    finish=json.loads(finishpath.read_bytes());diagnostics=json.loads(finishpath.with_name('diagnostics.json').read_bytes())
    assert finish['status']=='FAILED_UNFINALIZED' and finish['refund'] is False and finish['scientific_status']=='INVALID'
    assert finish['actual_priced_reserve_counts']['rule_calls']==2 and finish['actual_priced_reserve_counts']['completed_rules']==1
    assert len(diagnostics['completed_signals'])==1 and diagnostics['failed_signal']['status']=='INVALID'
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


@pytest.mark.parametrize('matrix', [[[0.04,0.04],[0.04,0.04]], [[0.0,0.0],[0.0,0.0]]])
def test_fallback_actual_native_accounts_and_negative_precedence(tmp_path,monkeypatch,matrix):
    root,cfg,p,c=fixture(tmp_path,monkeypatch)
    # Observe the actual author selector with controlled invented covariance, not a mirrored rule.
    monkeypatch.setattr(priced,'sample_covariance',lambda *a,**k:(None,None,[[x/252 for x in row] for row in matrix]))
    result=ReferenceResearchService(root,128*1024**2).run(cfg)
    phases=json.loads((root/'reference-research-experiments'/result['semantic_id']/'phases.json').read_bytes())
    for data in phases.values():
        legs=data['simulation']['legs']
        assert legs[0]['nav']==legs[1]['nav']
        for key in ('orders','fills'):
            assert [{k:v for k,v in row.items() if k!='id'} for row in legs[0][key]]==[
                   {k:v for k,v in row.items() if k!='id'} for row in legs[1][key]]
        assert data['evaluation']['point_interpretation']=='NOT_SUPPORTIVE_ON_THIS_LIMITED_SCREEN'
        assert data['plan']['signals'][0]['rule']['status'].endswith('FALLBACK_CASH_TARGET' if matrix[0][0] else 'FALLBACK_CASH')
        assert any(row['positions']['BIL']>0 for row in legs[2]['nav'])
        if not matrix[0][0]:
            assert any(x['status']=='UNAVAILABLE' for x in data['evaluation']['criteria'])
            assert all(row['cash_cents']==row['nav_cents'] for row in legs[0]['nav'])


def test_partial_native_failure_preserves_planned_work_and_debit(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    original=module.bounded_native;calls=[]
    def fail_stress(plan):
        calls.append(1)
        if len(calls)==2:raise ValueError('INVENTED_NATIVE_PARTIAL_FAILURE')
        return original(plan)
    monkeypatch.setattr(module,'bounded_native',fail_stress)
    service=ReferenceResearchService(root,128*1024**2)
    with pytest.raises(ValueError,match='INVENTED_NATIVE_PARTIAL_FAILURE'):service.run(cfg)
    finishpath=next((root/'scheduled-reference-attempts').glob('*/*/finish/record.json'))
    finish=json.loads(finishpath.read_bytes())
    assert finish['completed_native_accounts']==3 and finish['refund'] is False
    assert finish['actual_priced_reserve_counts']['completed_rules']==len(c['phases']['FINAL']['decisions'])
    assert 'scientific_status' not in finish
    assert list((root/'scheduled-reference-attempts').glob('*/*/phases/FINAL/phase.json'))
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_invented_retained_contract_automatic_offline_intent(tmp_path,monkeypatch):
    import os
    from polar.candidate_binding import loaded_revision
    root,cfg,p,c=fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    assert manifest['provenance']['kind']=='DETERMINISTIC_INVENTED_FIXTURE'
    manifest['rights']='SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION'
    cfg['input_ref']=write(tmp_path/'invented-retained-contract.json',manifest)
    p['input_sha256']=cfg['input_ref']['sha256'];cfg['profile_ref']=write(tmp_path/'retained-profile.json',p)
    cfg['namespace']='RETAINED';cfg['code_revision']=loaded_revision()
    cfg['runtime_image_id']=os.environ['POLAR_CI_RUNTIME_IMAGE_ID']
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID',cfg['runtime_image_id'])
    service=ReferenceResearchService(root,128*1024**2)
    assert cfg['execution_authority_ref'] is None
    assert service.preflight(cfg)['execution_binding_status']=='AUTOMATIC_OFFLINE_BINDING_READY_NOT_REVIEWED'
    result=service.run(cfg);assert result['status']=='SUCCESS'
    authority=json.loads(next(root.rglob('authority.json')).read_bytes())
    assert authority['schema']=='polar.offline-author-binding/1' and authority['candidate_sha']==loaded_revision()
    assert authority['run_id']==result['attempt_id']
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


@pytest.mark.parametrize('field',['weight','clock','terminal','minimum','timezone_join','grid'])
def test_saved_plan_arithmetic_rejects_tampering(tmp_path,monkeypatch,field):
    _,cfg,p,c=fixture(tmp_path,monkeypatch);market=load_reference(cfg['input_ref'])
    tz=ZoneInfo('America/New_York');plan=plan_phase(market,p,c['phases']['FINAL'],tz)
    calendar={**c,'source_schedule_rows':market['schedule']}
    priced.verify_plan(plan,p,calendar,tz)
    if field=='weight':plan['decisions'][0]['instructions']['SWEPT']['weights']['BIL']=[1,1]
    elif field=='clock':plan['decisions'][0]['decision_ns']+=1
    elif field=='terminal':plan['decisions'][-1]['instructions']['SWEPT']={'kind':'HOLD'}
    elif field=='minimum':plan['signals'][0]['rule']['certificate']['grid_minimum_index']=-1
    elif field=='timezone_join':plan['signals'][0]['execution']=plan['signals'][0]['formation']
    else:plan['grid'][0]['sample_ns']+=1
    with pytest.raises(ValueError):priced.verify_plan(plan,p,calendar,tz)


def test_bootstrap_priced_recipe_rejects_terminal_hurdle_and_legacy_pair():
    from polar.scheduled_uncertainty import bootstrap
    simulation={'legs':[{'id':x,'returns':[Fraction(1,100),Fraction(-1,200)]} for x in ('SWEPT','BIL_ONLY')]}
    with pytest.raises(ValueError,match='PRICED_RESERVE_IDENTITIES'):
        bootstrap(simulation,'SWEPT',['BIL_ONLY'],seed=37004,recipe='PRICED_RESERVE_DESCRIPTIVE')
    with pytest.raises(ValueError,match='THREE_BASE_LEG_IDENTITIES'):
        bootstrap(simulation,'SWEPT',['BIL_ONLY'],seed=37001)
