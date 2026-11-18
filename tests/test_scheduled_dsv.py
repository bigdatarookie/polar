"""Invented common native DSV path and source-absent saved arithmetic."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from polar import scheduled_dsv as dsv
from polar import qb_downside_semideviation_prototype as author
from polar.reference_service import ReferenceResearchService
from polar.scheduled_signals import AllocationError
from reference_fixture import write
from test_scheduled_erc import fixture as erc_fixture


def fixture(tmp_path,monkeypatch):
    root,cfg,p,c=erc_fixture(tmp_path,monkeypatch)
    p.update(schema=dsv.SCHEMA,protocol_id=author.PROTOCOL_ID,policy=deepcopy(dsv.POLICY),
        legs=[dict(id=leg,label=leg,rule=leg,scale=[1,1]) for leg in dsv.IDS],
        primary_strategy='DSV',primary_benchmark='EW',
        criteria=[dict(id='C'+str(i),description='Frozen invented downside screen '+str(i),
                       left_id='DSV',**spec) for i,spec in enumerate(dsv.SPECS)],
        uncertainty=dict(kind='BASE_ONLY_PAIRED_SAVED_RETURN_CONDITIONAL_DESCRIPTIVE',
                         block=63,replicates=1000,seed=37006))
    cfg.update(profile_ref=write(tmp_path/'dsv-profile.json',p),
               candidate_id='INVENTED-DSV',experiment_id='INVENTED-DSV-ORIGINAL')
    return root,cfg,p,c


def prices(*,positive=()):
    rows=[];held=[100_000_000]*4
    for t in range(61):
        row={}
        for j,s in enumerate(dsv.SYMBOLS):
            if j in positive:
                held[j]+=100+(t*t*(j+7)*137+t*(j+1)*29)%10000
                value=held[j]
            else:value=(100+10*j)*10**6+(t*t*(j+3)*7919+t*(j+1)*3571)%1_000_000
            row[s]=value
        rows.append(row)
    return rows


@pytest.mark.parametrize('positive',[(),(0,),(0,1,2,3)])
def test_genuine_price_returns_certificate_and_zero_boundary_without_frozen_author_calls(monkeypatch,positive):
    rows=prices(positive=positive)
    signal=dsv.targets(rows,list(dsv.SYMBOLS))['diagnostics']
    zeros=signal['rule']['certificate']['zero_downside_indices'];assert zeros==list(positive)
    def forbidden(*a,**k):raise AssertionError('SAVED_ESTIMATOR_AUTHOR_OR_GRID_SEARCH')
    monkeypatch.setattr(dsv,'sample_covariance',forbidden)
    for name in ('downside_targets','_construct','_inverse_root','matrix','_ldl','_scale','quadratic'):
        monkeypatch.setattr(author,name,forbidden)
    targets=dsv.verify_signal(signal,rows)
    assert set(targets)==set(dsv.IDS)
    raw=signal['rule']['raw_weights']['DSV']
    if positive:
        assert all(raw[s]==([1,len(positive)] if i in positive else [0,1])
                   for i,s in enumerate(dsv.SYMBOLS))


@pytest.mark.parametrize('field',['price','return','covariance','moment','denominator','zero','branch',
                                 'scalar','raw','target','cash','grid','next','counts','extra'])
def test_saved_source_return_moment_scalar_and_grid_tampering(field):
    rows=prices();s=dsv.targets(rows,list(dsv.SYMBOLS))['diagnostics'];c=s['rule']['certificate']
    if field=='price':s['converted_prices_binary64'][0][0]='10.0'
    elif field=='return':s['return_rows_binary64'][0][0]='0.0'
    elif field=='covariance':s['sample_covariance_binary64'][0][0]='1.0'
    elif field=='moment':c['lower_partial_second_moments'][0]=[0,1]
    elif field=='denominator':c['downside_denominator']=59
    elif field=='zero':c['zero_downside_indices']=[0]
    elif field=='branch':c['downside_branch']='FALLBACK'
    elif field=='scalar':c['scalar_convention']['precision']=50
    elif field=='raw':s['rule']['raw_weights']['DSV']['BIL']=[1,1]
    elif field=='target':c['annual_common_target_variance']=[1,1]
    elif field=='cash':c['scales']['DSV']['cash']=[1,1]
    elif field=='grid':c['scales']['DSV']['index']=0
    elif field=='next':c['scales']['DSV']['annual_next_grid_variance']=[0,1]
    elif field=='counts':s['actual_counts']['estimator_calls']=2
    else:c['epsilon']=[1,10000]
    with pytest.raises(ValueError):dsv.verify_signal(s,rows)


@pytest.mark.parametrize('bad',['nonfinite','asymmetric','nonpositive','nonpsd','return'])
def test_partial_invalid_real_call_counts_not_favorable_defaults(monkeypatch,bad):
    original=dsv.sample_covariance
    def invalid(*args,**kwargs):
        converted,means,m=original(*args,**kwargs)
        if bad=='nonfinite':m[0][0]=float('nan')
        elif bad=='asymmetric':m[0][1]=0.5
        elif bad=='nonpositive':m[0][0]=0.0
        elif bad=='nonpsd':m[0][1]=m[1][0]=1.0
        else:converted[1][0]=float('inf')
        return converted,means,m
    monkeypatch.setattr(dsv,'sample_covariance',invalid)
    with pytest.raises(AllocationError) as error:dsv.targets(prices(),list(dsv.SYMBOLS))
    counts=error.value.events['actual_counts']
    assert counts['estimator_calls']==counts['completed_estimates']==1
    assert counts['completed_prototypes']==0
    if bad=='return':
        assert counts['prototype_calls']==0 and counts['return_ratio_attempts']==1
        assert counts['completed_return_ratios']==0
    else:
        assert counts['prototype_calls']==1 and counts['completed_return_ratios']==240
        assert counts['completed_covariance_admissions']==0


def test_actual_native_both_costs_duplicate_and_saved_only_no_estimator_policy_samples_or_writes(tmp_path,monkeypatch):
    root,cfg,p,c=fixture(tmp_path,monkeypatch)
    service=ReferenceResearchService(root,128*1024**2)
    calls=[];original=author.downside_targets
    def observed(cov,returns):
        assert len(list((root/'scheduled-reference-attempts').glob('*/*/start.json')))==1
        calls.append(1);assert len(returns)==60 and all(len(row)==4 for row in returns)
        return original(cov,returns)
    monkeypatch.setattr(author,'downside_targets',observed)
    ready=service.preflight(cfg)
    assert ready['expected_native_accounts']==6 and ready['expected_dsv_work']['prototype_calls']==len(c['phases']['FINAL']['decisions'])
    assert calls==[]
    result=service.run(cfg);assert result['status']=='SUCCESS'
    assert len(calls)==len(c['phases']['FINAL']['decisions'])
    directory=root/'reference-research-experiments'/result['semantic_id']
    phases=json.loads((directory/'phases.json').read_bytes());base=phases['FINAL'];stress=phases['FINAL_COST_STRESS']
    assert {k:v for k,v in base['plan'].items() if k!='cost_profile'}=={k:v for k,v in stress['plan'].items() if k!='cost_profile'}
    finish=json.loads(next(root.glob('scheduled-reference-attempts/*/*/finish/record.json')).read_bytes())
    assert finish['native_accounts']==6 and finish['actual_dsv_counts']==dsv.counts(base['plan']['signals'])
    assert finish['actual_dsv_native_invocations']==dict(attempted=2,completed=2)
    assert finish['actual_dsv_bootstrap_work']==dict(invocations=1,replicates_started=1000,indices_produced=1000,replicates_completed=1000)
    from polar.model_price_consumed import verify
    calendar=json.loads((directory/'calendar.json').read_bytes())
    for data in phases.values():
        assert len(data['evaluation']['criteria'])==9
        assert data['simulation']['cost_profile']==data['plan']['cost_profile']
        verify(data['plan'],data['simulation'],p,calendar)
        for leg in data['simulation']['legs']:
            assert leg['nav'][-1]['cash_cents']==leg['nav'][-1]['nav_cents']
            assert not any(leg['nav'][-1]['positions'].values())
    for field in ('sizing','fill','order','clock','cash'):
        sim=deepcopy(base['simulation']);leg=sim['legs'][0]
        if field=='sizing':leg['intents'][0]['sizing_witness']['nav_cents']+=1
        elif field=='fill':leg['fills'][0]['q']+=1
        elif field=='order':leg['orders'][0]['routed_quantity']+=1
        elif field=='clock':leg['intents'][0]['decision_ns']+=1
        else:leg['nav'][-1]['cash_cents']+=1
        with pytest.raises(ValueError):verify(base['plan'],sim,p,calendar)
    uncertainty=json.loads((directory/'uncertainty.json').read_bytes())
    assert uncertainty['seed']==37006 and uncertainty['primary_id']=='DSV'
    from polar.scheduled_dsv_uncertainty import verify_saved
    for field in ('index','return_binding','statistic'):
        changed=deepcopy(uncertainty)
        if field=='index':changed['replicates'][0]['saved_indices'][0]+=1
        elif field=='return_binding':changed['base_return_binding']['DSV']['return_literals_sha256']='0'*64
        else:changed['replicates'][0]['comparisons'][0]['sr_delta']['value']='999'
        with pytest.raises(ValueError):verify_saved(base['simulation'],changed)
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)
    source=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    for ref in (source['quotes'],source['schedule'],*[cfg[k] for k in
                ('input_ref','profile_ref','protocol_ref','calendar_ref','timezone_ref')]):
        Path(ref['path']).unlink()
    before={str(f):sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}
    def forbidden(*a,**k):raise AssertionError('SAVED_SOURCE_AUTHOR_ESTIMATOR_GRID_RNG_NATIVE_OR_WRITE')
    import polar.scheduled_service as module
    for name in ('load_reference','load_market','plan_phase','bounded_native','read_ref','uncertainty_for'):
        monkeypatch.setattr(module,name,forbidden)
    monkeypatch.setattr(dsv,'sample_covariance',forbidden)
    for name in ('downside_targets','_construct','_inverse_root','matrix','_ldl','_scale','quadratic'):
        monkeypatch.setattr(author,name,forbidden)
    import polar.scheduled_uncertainty as bootstrap
    monkeypatch.setattr(bootstrap,'bootstrap',forbidden);monkeypatch.setattr(bootstrap,'_indices',forbidden)
    monkeypatch.setattr(bootstrap.random,'Random',forbidden);monkeypatch.setattr(service.store,'_publish',forbidden)
    saved=service.recompute(result['semantic_id'])
    assert saved['status']=='REPRODUCED' and saved['estimator_calls']==saved['prototype_calls']==saved['bootstrap_samples']==0
    assert saved['newly_sampled_replicates']==0 and saved['verified_saved_replicates']==1000
    assert before=={str(f):sha256(f.read_bytes()).hexdigest() for f in root.rglob('*') if f.is_file()}


def test_retained_namespace_automatic_preflight_and_intent_are_source_free_not_legacy_quotas(tmp_path,monkeypatch):
    """Control-flow test on invented metadata, never retained qualification."""
    from zoneinfo import ZoneInfo
    import polar.scheduled_service as module
    root,cfg,p,calendar=fixture(tmp_path,monkeypatch)
    cfg['namespace']='RETAINED'
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID',cfg['runtime_image_id'])
    calls=[]
    def prepared(service,config,*,load_prices=True):
        assert load_prices is False and config is cfg
        calls.append('SOURCE_FREE_PREPARE_STUB')
        return p,calendar,[],calendar['phases'],ZoneInfo('America/New_York'),None
    def forbidden(*a,**k):raise AssertionError('SOURCE_FINANCE_OR_LEGACY_PERMISSION_READ')
    monkeypatch.setattr(module,'prepare',prepared)
    for name in ('load_reference','load_market','read_ref','bounded_native'):
        monkeypatch.setattr(module,name,forbidden)
    monkeypatch.setattr(author,'downside_targets',forbidden)
    service=ReferenceResearchService(root,128*1024**2)
    # Actual automatic intent helper, not a mock returning a legacy grant.
    ready=module.preflight(service,cfg)
    assert ready['execution_binding_status']=='AUTOMATIC_OFFLINE_BINDING_READY_NOT_REVIEWED'
    assert ready['expected_native_accounts']==6 and len(calls)==1
    intent=module.authority_for(service,cfg,p,calendar['phases'])
    assert intent['schema']=='polar.offline-author-binding/1'
    assert intent['scientific_acceptance']=='NOT_REVIEWED' and intent['expected_native_accounts']==6
    assert not any(k.startswith('allowed_') for k in intent)
    assert not list(root.glob('scheduled-reference-attempts/*/*/start.json'))
    legacy={**cfg,'execution_authority_ref':{'path':'/never/open/legacy.json','sha256':'0'*64}}
    with pytest.raises(ValueError,match='DSV_AUTOMATIC_OFFLINE_BINDING'):
        module.authority_for(service,legacy,p,calendar['phases'])
