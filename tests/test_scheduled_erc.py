"""Public invented ERC common service, exact witnesses and nonresetting partial work."""
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from polar import qb_equal_risk_contribution_prototype as author
from polar import scheduled_erc as erc
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from polar.research_reference import load_reference
from polar.scheduled_policy import plan_phase, profile_value
from polar.scheduled_signals import AllocationError
from reference_fixture import write
from scheduled_fixture import inverse_fixture


def fixture(tmp_path,monkeypatch):
    root,cfg,p,c=inverse_fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes());quotes=Path(manifest['quotes']['path'])
    mapping=dict(zip(p['symbols'],erc.SYMBOLS));rows=[json.loads(line) for line in quotes.read_text().splitlines()]
    for i,row in enumerate(rows):
        t,j=divmod(i,4);micro=(100+10*j)*10**6+(t*t*(j+3)*7919+t*(j+1)*3571)%1_000_000
        token=f'{micro//10**6}.{micro%10**6:06d}'
        row.update(symbol=mapping[row['symbol']],reference_quote=token,source_adjusted_close_token=token)
    quotes.write_bytes(b''.join((json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode() for row in rows))
    manifest.update(symbols=list(erc.SYMBOLS),quotes=dict(path=str(quotes),sha256=sha256(quotes.read_bytes()).hexdigest(),bytes=quotes.stat().st_size))
    mp=write(tmp_path/'erc-input.json',manifest)
    p.update(schema=erc.SCHEMA,protocol_id=author.PROTOCOL_ID,symbols=list(erc.SYMBOLS),input_sha256=mp['sha256'],policy=deepcopy(erc.POLICY),
        legs=[dict(id=leg,label=leg,rule=leg,scale=[1,1]) for leg in erc.IDS],primary_strategy='ERC',primary_benchmark='EW',
        criteria=[dict(id='C'+str(i),description='Frozen invented screen '+str(i),left_id='ERC',**spec) for i,spec in enumerate(erc.SPECS)],
        uncertainty=dict(kind='BASE_ONLY_PAIRED_SAVED_RETURN_CONDITIONAL_DESCRIPTIVE',block=63,replicates=1000,seed=37005),
        additional_limitations=[],subperiods=[])
    pp=write(tmp_path/'erc-profile.json',p)
    return root,{**cfg,'profile_ref':pp,'input_ref':mp,'candidate_id':'INVENTED-ERC','experiment_id':'INVENTED-ERC-ORIGINAL'},p,c


def diagnostic(matrix):
    result=author.equal_risk_targets(matrix)
    return dict(kind=erc.KIND,prototype_sha256=erc.PROTOTYPE_SHA256,
        sample_covariance_binary64=[[repr(x) for x in row] for row in matrix],rule=result,
        actual_counts=dict(estimator_calls=1,completed_estimates=1,prototype_calls=1,completed_prototypes=1,**result['actual_counts']))


def diagonal():
    return [[(i+1)**2/10000 if i==j else 0.0 for j in range(4)] for i in range(4)]


@pytest.mark.parametrize('matrix',[diagonal(),[[0.01]*4 for _ in range(4)],
    [[0.01 if i==j else -0.002 for j in range(4)] for i in range(4)]])
def test_arithmetic_certificate_without_author_or_selection(matrix,monkeypatch):
    signal=diagnostic(matrix)
    def forbidden(*a,**k):raise AssertionError('SAVED_AUTHOR_SOLVER_OR_SEARCH')
    for name in ('equal_risk_targets','_solve','_scale','matrix','_ldl','quadratic','contribution_certificate'):
        monkeypatch.setattr(author,name,forbidden)
    targets=erc.verify_signal(signal)
    assert set(targets)==set(erc.IDS)
    assert all(0<sum(row.values())<=1 for row in targets.values())


@pytest.mark.parametrize('field',['covariance','shrinkage','ldl','budget','tolerance','inverse','equal','target','index','cash','next','raw_erc'])
def test_saved_exact_witness_tampering(field):
    s=diagnostic(diagonal());c=s['rule']['certificate']
    if field=='covariance':c['sample_covariance'][0][0]=[1,1]
    elif field=='shrinkage':c['shrunk_covariance'][0][1]=[1,1]
    elif field=='ldl':c['shrunk_ldl_pivots'][0]=[1,1]
    elif field=='budget':c['erc_contributions'][0]=[1,1]
    elif field=='tolerance':c['relative_budget_tolerance']=[1,1]
    elif field in ('inverse','equal','raw_erc'):
        leg={'inverse':'INV','equal':'EW','raw_erc':'ERC'}[field];row=s['rule']['raw_weights'][leg]
        row['BIL']=[1,8];row['SHY']=[1,8];row['TLT']=[1,8];row['VTI']=[5,8]
    elif field=='target':c['annual_common_target_variance']=[1,1]
    elif field=='index':c['scales']['ERC']['index']=0
    elif field=='cash':c['scales']['ERC']['cash']=[1,1]
    else:c['scales']['ERC']['annual_next_grid_variance']=[0,1]
    with pytest.raises(ValueError):erc.verify_signal(s)


@pytest.mark.parametrize('bad',['nonfinite','asymmetric','nonpositive','nonpsd'])
def test_invalid_geometry_keeps_actual_attempted_work(bad,monkeypatch):
    m=diagonal()
    if bad=='nonfinite':m[0][0]=float('inf')
    elif bad=='asymmetric':m[0][1]=0.5
    elif bad=='nonpositive':m[0][0]=0.0
    else:m[0][1]=m[1][0]=1.0
    monkeypatch.setattr(erc,'sample_covariance',lambda *a,**k:(None,None,m))
    with pytest.raises(AllocationError) as error:erc.targets([],list(erc.SYMBOLS))
    counts=error.value.events['actual_counts']
    assert counts['estimator_calls']==counts['completed_estimates']==counts['prototype_calls']==1
    assert counts['completed_prototypes']==0 and all(counts[k]==0 for k in erc.WORK_KEYS)


def test_actual_native_service_then_immutable_source_absent_reproduction(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    calls=[];original=author.equal_risk_targets
    def observed(matrix):
        assert len(list((root/'scheduled-reference-attempts').glob('*/*/start.json')))==1
        calls.append(1);return original(matrix)
    monkeypatch.setattr(author,'equal_risk_targets',observed)
    assert service.preflight(cfg)['expected_native_accounts']==6 and calls==[]
    result=service.run(cfg);assert set(result)=={'status','attempt_id','semantic_id','results','financial_acceptance'}
    assert result['status']=='SUCCESS' and len(calls)==len(c['phases']['FINAL']['decisions'])
    directory=root/'reference-research-experiments'/result['semantic_id']
    phases=json.loads((directory/'phases.json').read_bytes());base=phases['FINAL'];stress=phases['FINAL_COST_STRESS']
    assert {k:v for k,v in base['plan'].items() if k!='cost_profile'}=={k:v for k,v in stress['plan'].items() if k!='cost_profile'}
    finish=json.loads(next((root/'scheduled-reference-attempts').glob('*/*/finish/record.json')).read_bytes())
    assert finish['native_accounts']==6 and finish['actual_erc_counts']==erc.counts(base['plan']['signals'])
    assert finish['actual_erc_native_invocations']=={'attempted':2,'completed':2}
    for data in phases.values():
        cost=data['simulation']['cost_profile'];assert len(data['evaluation']['criteria'])==9
        for leg in data['simulation']['legs']:
            nav=leg['nav'];assert not any(nav[0]['positions'].values()) and not any(nav[-1]['positions'].values())
            assert nav[-1]['cash_cents']==nav[-1]['nav_cents']
            for fill in leg['fills']:
                assert type(fill['q']) is int and fill['q']>0
                assert fill['fee_cents']==cost['flat_cents']+(fill['q']*fill['price_micro']*cost['bps']+99_999_999)//100_000_000
                cents,remainder=divmod(fill['q']*fill['price_micro'],10000)
                assert fill['settled_cents']==cents+int(remainder>5000 or remainder==5000 and cents%2==1)
            assert nav[-1]['flat_cents']==len(leg['fills'])*cost['flat_cents']
    from polar.model_price_consumed import verify as verify_consumed
    saved_calendar=json.loads((directory/'calendar.json').read_bytes())
    for field in ('fill','nav','sizing','order','clock'):
        altered=deepcopy(base['simulation']);leg=altered['legs'][0]
        if field=='fill':leg['fills'][0]['q']+=1
        elif field=='nav':leg['nav'][-1]['cash_cents']+=1
        elif field=='sizing':leg['intents'][0]['sizing_witness']['nav_cents']+=1
        elif field=='order':leg['orders'][0]['routed_quantity']+=1
        else:leg['intents'][0]['decision_ns']+=1
        with pytest.raises(ValueError):verify_consumed(base['plan'],altered,p,saved_calendar)
    uncertainty=json.loads((directory/'uncertainty.json').read_bytes())
    assert uncertainty['benchmark_ids']==['EW','INV'] and uncertainty['seed']==37005 and uncertainty['robustness']=='INSUFFICIENT_EVIDENCE'
    for pub in result['results'].values():
        record=ResearchResults(root,128*1024**2).read(pub['result_id'])['record']
        assert len(record['series'])==3 and len(record['criteria'])==9
        assert any(x['code']=='ERC_EXACT_BUDGET_CERTIFICATE' for x in record['limitations'])
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)
    source=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    for ref in (source['quotes'],source['schedule'],*[cfg[k] for k in ('input_ref','profile_ref','protocol_ref','calendar_ref','timezone_ref')]):
        Path(ref['path']).unlink()
    before={str(path):sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}
    def forbidden(*a,**k):raise AssertionError('SAVED_SOURCE_SOLVER_SEARCH_NATIVE_OR_WRITE')
    import polar.scheduled_service as module
    for name in ('load_reference','load_market','plan_phase','bounded_native','read_ref'):monkeypatch.setattr(module,name,forbidden)
    monkeypatch.setattr(erc,'sample_covariance',forbidden)
    for name in ('equal_risk_targets','_solve','_scale','matrix','_ldl','quadratic','contribution_certificate'):
        monkeypatch.setattr(author,name,forbidden)
    monkeypatch.setattr(service.store,'_publish',forbidden)
    reproduced=service.recompute(result['semantic_id'])
    assert reproduced['status']=='REPRODUCED' and all(reproduced[k]==0 for k in ('estimator_calls','prototype_calls','coordinate_solver_calls','risk_search_calls','native_calls','store_writes'))
    assert reproduced['actual_erc_counts']==erc.counts([])
    assert before=={str(path):sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}


def test_metadata_only_causal_prefix_and_closed_profile(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch);market=load_reference(cfg['input_ref'])
    plan=plan_phase(market,p,c['phases']['FINAL'],ZoneInfo('America/New_York'))
    altered=deepcopy(market);cut=c['phases']['FINAL']['decisions'][0]['signal_index']
    for d in altered['dates'][cut+1:]:altered['prices_micro'][d]={s:100000000 for s in erc.SYMBOLS}
    # Only the first formation is relevant to this causal comparison.
    g=deepcopy(c['phases']['FINAL']);g['decisions']=g['decisions'][:1]
    second=plan_phase(altered,p,g,ZoneInfo('America/New_York'))
    assert plan['signals'][0]==second['signals'][0] and plan['decisions'][0]==second['decisions'][0]
    source=json.loads(Path(cfg['input_ref']['path']).read_bytes());Path(source['quotes']['path']).unlink()
    assert ReferenceResearchService(root,128*1024**2).preflight(cfg)['policy_execution']=='NOT_RUN'
    for key,value in [('solver','OTHER'),('weight_units',10),('relative_budget_tolerance',[1,100]),('shrinkage',[1,3])]:
        bad=deepcopy(p);bad['policy'][key]=value
        with pytest.raises(ValueError):profile_value(bad)


def test_solver_partial_failure_retains_attempts_and_debit(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    def failed(*a):raise author.RiskBudgetError('INVENTED_CERTIFICATE_FAILURE')
    monkeypatch.setattr(author,'contribution_certificate',failed)
    with pytest.raises(AllocationError):service.run(cfg)
    finishpath=next((root/'scheduled-reference-attempts').glob('*/*/finish/record.json'))
    finish=json.loads(finishpath.read_bytes());counts=finish['actual_erc_counts']
    assert finish['refund'] is False and finish['scientific_status']=='INVALID' and finish['completed_native_accounts']==0
    assert counts['coordinate_sweeps']==1 and counts['coordinate_update_attempts']==counts['coordinate_updates']==4
    assert counts['exact_budget_checks']==0 and counts['completed_prototypes']==0 and counts['prototype_calls']==1
    diagnostics=json.loads(finishpath.with_name('diagnostics.json').read_bytes())
    assert diagnostics['failed_signal']['prototype_events']['actual_counts']['coordinate_update_attempts']==4
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_partial_native_failure_keeps_shared_original_work(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    original=module.bounded_native;calls=[]
    def fail_stress(plan):
        calls.append(1)
        if len(calls)==2:
            plan=deepcopy(plan)
            for decision in plan['decisions']:del decision['instructions']['EW']
        return original(plan)
    monkeypatch.setattr(module,'bounded_native',fail_stress)
    service=ReferenceResearchService(root,128*1024**2)
    from polar.ci_research_service import NativeFailure
    with pytest.raises(NativeFailure):service.run(cfg)
    finish=json.loads(next((root/'scheduled-reference-attempts').glob('*/*/finish/record.json')).read_bytes())
    assert finish['completed_native_accounts']==4 and finish['refund'] is False and 'scientific_status' not in finish
    assert finish['actual_erc_native_invocations']=={'attempted':2,'completed':1}
    assert finish['native_account_count_scope'].endswith('UNOBSERVED_WORK_NOT_INFERRED')
    assert finish['actual_erc_counts']['completed_prototypes']==len(c['phases']['FINAL']['decisions'])
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_invented_retained_contract_auto_intent_and_strict_explicit_artifact(tmp_path,monkeypatch):
    import os
    from polar.candidate_binding import loaded_revision
    root,cfg,p,c=fixture(tmp_path,monkeypatch);manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    assert manifest['provenance']['kind']=='DETERMINISTIC_INVENTED_FIXTURE'
    manifest['rights']='SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION'
    cfg['input_ref']=write(tmp_path/'invented-retained-contract.json',manifest)
    p['input_sha256']=cfg['input_ref']['sha256'];cfg['profile_ref']=write(tmp_path/'retained-profile.json',p)
    cfg['namespace']='RETAINED';cfg['code_revision']=loaded_revision();cfg['runtime_image_id']=os.environ['POLAR_CI_RUNTIME_IMAGE_ID']
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID',cfg['runtime_image_id']);service=ReferenceResearchService(root,128*1024**2)
    assert cfg['execution_authority_ref'] is None
    assert service.preflight(cfg)['execution_binding_status']=='AUTOMATIC_OFFLINE_BINDING_READY_NOT_REVIEWED'
    bad={**cfg,'execution_authority_ref':write(tmp_path/'bad-legacy.json',{'schema':'INVALID'})}
    with pytest.raises(ValueError,match='SCHEDULED_OPERATION_NOT_BOUND'):service.run(bad)
    assert not list(root.rglob('start.json'))
    result=service.run(cfg);assert result['status']=='SUCCESS'
    authority=json.loads(next(root.rglob('authority.json')).read_bytes())
    assert authority['schema']=='polar.offline-author-binding/1' and authority['candidate_sha']==loaded_revision()
    assert authority['run_id']==result['attempt_id']
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.preflight(cfg)


@pytest.mark.parametrize('field',['clock','grid','terminal','instruction','signal'])
def test_saved_plan_binding_rejects_changes(tmp_path,monkeypatch,field):
    _,cfg,p,c=fixture(tmp_path,monkeypatch);market=load_reference(cfg['input_ref']);tz=ZoneInfo('America/New_York')
    plan=plan_phase(market,p,c['phases']['FINAL'],tz);calendar={**c,'source_schedule_rows':market['schedule']}
    erc.verify_plan(plan,p,calendar,tz)
    if field=='clock':plan['decisions'][0]['known_ns']+=1
    elif field=='grid':plan['grid'][0]['sample_ns']+=1
    elif field=='terminal':plan['decisions'][-1]['instructions']['ERC']={'kind':'HOLD'}
    elif field=='instruction':plan['decisions'][0]['instructions']['ERC']['weights']['BIL']=[1,1]
    else:plan['signals'][0]['formation']=plan['signals'][0]['execution']
    with pytest.raises(ValueError):erc.verify_plan(plan,p,calendar,tz)


def test_exact_stall_is_invalid_with_completed_private_budget_work(monkeypatch):
    original=author.contribution_certificate
    def uncertified(*args):
        variance,contributions,_=original(*args)
        return variance,contributions,[Fraction(1)]*4
    monkeypatch.setattr(author,'contribution_certificate',uncertified)
    with pytest.raises(author.RiskBudgetError,match='DECIMAL_STALL_WITHOUT_EXACT_CERTIFICATE') as error:
        author.equal_risk_targets(diagonal())
    counts=error.value.events['actual_counts']
    assert counts['coordinate_sweeps']>=1 and counts['coordinate_update_attempts']==counts['coordinate_updates']==4*counts['coordinate_sweeps']
    assert counts['exact_budget_checks']==counts['coordinate_sweeps'] and counts['risk_scale_evaluations']==0


def test_failed_screen_precedes_undefined_metrics(tmp_path,monkeypatch):
    from polar.scheduled_policy import evaluate_policy
    from polar.ci_research import INITIAL_CENTS
    _,_,p,_=fixture(tmp_path,monkeypatch)
    simulation={'legs':[dict(id=leg,fills=[],nav=[dict(nav_cents=INITIAL_CENTS,nominal_ns=i*86400*10**9,
        exposure_cents=0,positions={s:0 for s in erc.SYMBOLS},position_cents={s:0 for s in erc.SYMBOLS},flat_cents=0,bps_cents=0)
        for i in range(3)]) for leg in erc.IDS]}
    evaluation=evaluate_policy(simulation,p,'FINAL')
    assert any(c['status']=='UNAVAILABLE' for c in evaluation['criteria'])
    assert any(c['status']=='NOT_MET' for c in evaluation['criteria'])
    assert evaluation['point_interpretation']=='NOT_SUPPORTIVE_ON_THIS_LIMITED_SCREEN'


def test_prior_completed_formations_and_failed_solver_work_are_both_retained(tmp_path,monkeypatch):
    _,cfg,p,c=fixture(tmp_path,monkeypatch);market=load_reference(cfg['input_ref'])
    original=author.equal_risk_targets;calls=[]
    from unittest.mock import patch
    def observed(matrix):
        if calls:
            with patch.object(author,'contribution_certificate',side_effect=author.RiskBudgetError('INVENTED_SECOND_FORMATION_FAILURE')):
                return original(matrix)
        result=original(matrix);calls.append(result['actual_counts']);return result
    monkeypatch.setattr(author,'equal_risk_targets',observed)
    with pytest.raises(AllocationError) as error:plan_phase(market,p,c['phases']['FINAL'],ZoneInfo('America/New_York'))
    events=error.value.events;counts=events['actual_counts']
    assert len(events['completed_signals'])==1 and counts['estimator_calls']==counts['completed_estimates']==counts['prototype_calls']==2
    assert counts['completed_prototypes']==1
    assert counts['coordinate_update_attempts']==calls[0]['coordinate_update_attempts']+4
    assert counts['coordinate_updates']==calls[0]['coordinate_updates']+4
    assert counts['exact_budget_checks']==calls[0]['exact_budget_checks']
