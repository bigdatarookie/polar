"""Invented explicit denomination: immutable source, one bound model price view."""
from copy import deepcopy
from pathlib import Path
import json
import hashlib

import pytest

from reference_fixture import write
from test_scheduled_fixed import fixed_fixture
from test_scheduled_service import snapshot
from polar.scheduled_policy import profile_value,plan_phase,calendar_value
from polar.reference_model_price import view,verify_plan
from polar.research_reference import load_reference
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults


def model_fixture(tmp_path,monkeypatch):
    root,cfg,p,cal=fixed_fixture(tmp_path,monkeypatch)
    a,b,c,d=p['symbols'];zero={s:[0,1] for s in p['symbols']}
    p.update(schema='polar.scheduled-reference-profile/10',
        legs=[{'id':i,'label':i,'rule':'CASH' if i=='CASH' else 'FIXED_WEIGHTS','weights':weights}
            for i,weights in [('DEPLOY',{**zero,a:[1,3],b:[2,3]}),('PRIMARY',{**zero,a:[1,3]}),
                ('FULL',{**zero,a:[1,1]}),('SHORT',{**zero,b:[1,1]}),('CASH',zero)]],
        primary_strategy='DEPLOY',primary_benchmark='PRIMARY',
        model_price_mapping={'schema':'polar.reference-model-price-mapping/1','source_input_sha256':cfg['input_ref']['sha256'],
            'multipliers':{a:[100,1],b:[100,1],c:[1,1],d:[1,1]},'lot_size':1,
            'active_unit':'COARSE100_SYNTHETIC_REFERENCE_UNIT_NOT_PHYSICAL_SHARE'})
    p['criteria']=[{'id':key,'description':key,'left_id':'DEPLOY',**extra} for key,extra in [
        ('WEALTH',{'kind':'TERMINAL_SCALED_GE','right_id':'PRIMARY','factor':[11,10]}),
        ('SR',{'kind':'SR_DELTA_GE','right_id':'PRIMARY','threshold':'0'}),
        ('VOL',{'kind':'VOL_SCALED_LE','right_id':'PRIMARY','factor':[6,5]}),
        ('DD',{'kind':'DRAWDOWN_SCALED_LE','right_id':'PRIMARY','factor':[6,5]}),
        ('GROWTH',{'kind':'POSITIVE_GROWTH'})]]
    pp=write(tmp_path/'model-profile.json',p)
    return root,{**cfg,'profile_ref':pp,'candidate_id':'INVENTED-MODEL100','experiment_id':'INVENTED-MODEL100-ORIGINAL'},p,cal


def test_explicit_model_view_and_exact_targets_leave_source_unchanged(tmp_path,monkeypatch):
    _,cfg,p,cal=model_fixture(tmp_path,monkeypatch);profile_value(p)
    source=load_reference(cfg['input_ref']);before=deepcopy(source['prices_micro']);mapping=p['model_price_mapping']
    model=view(source,mapping)
    assert source['prices_micro']==before and model['source_prices_micro']==before
    a,b,c,d=p['symbols']
    for day,row in before.items():
        assert model['prices_micro'][day]=={a:row[a]*100,b:row[b]*100,c:row[c],d:row[d]}
    grid=calendar_value(cal,source['schedule'])['FINAL'];plan=plan_phase(model,p,grid,None)
    assert verify_plan(plan,p)['status']=='VERIFIED_SAVED_MODEL_MAPPING'
    from polar.research_allocation import desired_targets
    from fractions import Fraction
    prices=model['prices_micro'][grid['initial']]
    desired=desired_targets(10000000,{s:0 for s in p['symbols']},prices,{a:Fraction(1,3),b:Fraction(2,3),c:Fraction(),d:Fraction()})
    assert desired[a]==10000000*10000//(3*prices[a])
    bad=deepcopy(plan);day=next(iter(bad['prices']));bad['prices'][day][a]['close_micro']+=1
    with pytest.raises(ValueError,match='MODEL_SAVED_PRICE_CORRESPONDENCE'):verify_plan(bad,p)
    for mutate in ('fractional','bool','inactive','coarse_inactive','unbound','legacy'):
        bad=deepcopy(p)
        if mutate=='fractional':bad['model_price_mapping']['multipliers'][a]=[3,2]
        if mutate=='bool':bad['model_price_mapping']['multipliers'][c]=[True,1]
        if mutate=='inactive':bad['legs'][0]['weights'][c]=[1,100];bad['legs'][0]['weights'][b]=[1,2]
        if mutate=='coarse_inactive':bad['model_price_mapping']['multipliers'][c]=[100,1]
        if mutate=='unbound':bad['model_price_mapping']['source_input_sha256']='0'*64
        if mutate=='legacy':bad['schema']='polar.scheduled-reference-profile/5'
        with pytest.raises(ValueError):profile_value(bad)


def test_debited_native_common_projection_and_source_absent_saved_mapping(tmp_path,monkeypatch):
    root,cfg,p,cal=model_fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,256*1024**2)
    source=Path(cfg['input_ref']['path']);manifest=json.loads(source.read_bytes());quotes=Path(manifest['quotes']['path'])
    original=hashlib.sha256(quotes.read_bytes()).hexdigest()
    import polar.scheduled_service as module
    actual=module.load_market
    def forbidden(*a,**k):raise AssertionError('SOURCE_MODEL_OR_NATIVE_BEFORE_DEBIT_OR_STORED')
    monkeypatch.setattr(module,'load_market',forbidden)
    ready=service.preflight(cfg);assert ready['expected_native_accounts']==5
    assert not (root/'scheduled-reference-attempts').exists()
    def after_start(*a,**k):
        assert len(list(root.rglob('start.json')))==1
        return actual(*a,**k)
    monkeypatch.setattr(module,'load_market',after_start)
    result=service.run(cfg);assert result['status']=='SUCCESS' and result['native_accounts']==5
    assert hashlib.sha256(quotes.read_bytes()).hexdigest()==original
    record=ResearchResults(root,256*1024**2).read(result['results']['FINAL']['result_id'])['record']
    assert any(v['role']=='model_price_mapping' for v in record['provenance'])
    limit=next(v['text'] for v in record['limitations'] if v['code']=='DECLARED_MODEL_PRICE_DENOMINATION')
    assert 'COARSE100' in limit and 'not a coordinate-only relabel' in limit
    assert 'denomination-invariance' in record['financial_claim']
    home=root/'reference-research-experiments'/result['semantic_id']
    data=json.loads((home/'phases.json').read_bytes())['FINAL']
    assert data['simulation']['quantity_unit']==p['model_price_mapping']['active_unit']
    verify_plan(data['plan'],p)
    # All executed model prices and native marks use the same model view, not source prices.
    for tape in data['simulation']['legs']:
        for f in tape['fills']:
            day=next(e['day'] for e in data['plan']['decisions'] if e['open_ns']<=f['at_ns']<e['open_ns']+1000)
            assert f['price_micro']==data['plan']['prices'][day][f['symbol']]['close_micro']
    before=snapshot(root)
    for name in ('load_reference','load_market','plan_phase','bounded_native'):monkeypatch.setattr(module,name,forbidden)
    for path in tmp_path.iterdir():
        if path.is_file():path.unlink()
    replay=service.recompute(result['semantic_id'])
    assert replay['status']=='REPRODUCED' and replay['native_calls']==replay['store_writes']==0
    assert snapshot(root)==before


def test_source_equality_is_not_replaced_by_mapping_and_domain_failure_is_charged(tmp_path,monkeypatch):
    root,cfg,p,cal=model_fixture(tmp_path,monkeypatch)
    source=load_reference(cfg['input_ref']);huge=deepcopy(source)
    a=p['symbols'][0];day=source['dates'][0];huge['prices_micro'][day][a]=10**24
    with pytest.raises(ValueError,match='MODEL_PRICE_DOMAIN'):view(huge,p['model_price_mapping'])
    # Changing source reference_quote cannot masquerade as a declared model view.
    manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    rows=[json.loads(line) for line in Path(manifest['quotes']['path']).read_bytes().splitlines()]
    rows[0]['reference_quote']='123456.000001'
    from polar.gym_contract import canonical
    changed=tmp_path/'changed-quotes.ndjson';changed.write_bytes(b''.join(canonical(r) for r in rows))
    manifest['quotes']={'path':str(changed),'sha256':hashlib.sha256(changed.read_bytes()).hexdigest(),
        'bytes':changed.stat().st_size}
    pin=write(tmp_path/'changed-manifest.json',manifest)
    with pytest.raises(ValueError,match='REFERENCE_SCALE_CHANGED'):load_reference(pin)
    import polar.scheduled_service as module
    def overflow(*a,**k):
        assert len(list(root.rglob('start.json')))==1
        raise ValueError('MODEL_PRICE_DOMAIN')
    monkeypatch.setattr(module,'load_market',overflow)
    service=ReferenceResearchService(root,128*1024**2)
    with pytest.raises(ValueError,match='MODEL_PRICE_DOMAIN'):service.run(cfg)
    finish=json.loads(next(root.rglob('finish/record.json')).read_bytes())
    assert finish['scientific_status']=='INVALID' and finish['refund'] is False and finish['automatic_retry'] is False
    with pytest.raises(ValueError,match='ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


@pytest.mark.parametrize('allowance',['allowed_score_calls','allowed_rank_calls','allowed_estimator_calls',
    'allowed_optimizer_calls','allowed_bootstrap_samples'])
def test_profile10_authority_requires_zero_nonpolicy_work(tmp_path,monkeypatch,allowance):
    # Inert INVENTED schema-predicate fixtures only: no Service prepare/run,
    # retained paths or native invocation uses these manufactured metadata refs.
    root,cfg,p,cal=model_fixture(tmp_path,monkeypatch)
    from polar.scheduled_service import authority_for,binding
    from polar.gym_contract import canonical,sha
    method=write(tmp_path/'INVENTED-method.json',{'schema':'polar.prospective-method-disposition/1',
        'method_verdict':'PASS','protocol':{'sha256':cfg['protocol_ref']['sha256']},'candidate_id':cfg['candidate_id']})
    card=write(tmp_path/'INVENTED-card.json',{'schema':'polar.native-hypothesis-reservation/1','state':'RESERVED',
        'candidate_id':cfg['candidate_id'],'experiment_registration_id':cfg['experiment_id']})
    ci=write(tmp_path/'INVENTED-ci-predicate.json',{'schema':'polar.ci-result/1','status':'PASS',
        'candidate_sha':cfg['code_revision'],'selection':['tests']})
    closed={**cfg,'namespace':'RETAINED'}
    grant={'schema':'polar.scheduled-reference-operation/1','action':'ORIGINAL',
        'binding_sha256':sha(canonical(binding(closed))),'allowed_fit_calls':0,'allowed_predict_calls':0,
        'allowed_native_accounts':5,'method_ref':method,'candidate_ref':card,'qualification_ref':ci,
        **{k:0 for k in ('allowed_score_calls','allowed_rank_calls','allowed_estimator_calls',
            'allowed_optimizer_calls','allowed_bootstrap_samples')}}
    closed['execution_authority_ref']=write(tmp_path/'INVENTED-authority-predicate.json',grant)
    assert authority_for(None,closed,p,{'FINAL':{}})==grant
    bad={**grant,allowance:1}
    closed['execution_authority_ref']=write(tmp_path/'INVENTED-bad-authority-predicate.json',bad)
    with pytest.raises(ValueError,match='SCHEDULED_FIXED_COST_OPERATION_BOUND'):
        authority_for(None,closed,p,{'FINAL':{}})
    assert not (root/'scheduled-reference-attempts').exists()


def test_invented_coarse_projection_preserves_all31_limitations(tmp_path,monkeypatch):
    # Entirely invented scalar/metadata projection: no retained record, evaluator,
    # market load, native call, or publication is involved.
    from polar.scheduled_service import public_config,project_diagnostics
    from polar.reference_projection import public_reference
    from polar.research_results import ResearchResult,validate_result,ResearchError
    _,cfg,p,_=model_fixture(tmp_path,monkeypatch)
    p['additional_limitations']=[['INVENTED_'+str(i),'Invented limitation '+str(i)] for i in range(3)]
    config=public_config(cfg,p);config['model_price_mapping']=p['model_price_mapping']
    nav=[{'nominal_ns':1577998800000000000+i*86400*10**9,'cash_cents':10000000,
          'exposure_cents':0,'flat_cents':0,'bps_cents':0,'positions':{},'nav_cents':10000000} for i in range(2)]
    token={'value':'0','status':'OK','reason':None}
    simulation={'legs':[{'id':leg['id'],'nav':deepcopy(nav)} for leg in p['legs']]}
    evaluation={'legs':[{'id':leg['id'],'returns':[{'decimal':'0'}],
        'metrics':{key:deepcopy(token) for key in ('terminal_nav_usd','flat_fee_usd','bps_cost_usd')}}
        for leg in p['legs']], 'comparisons':[],'criteria':[],'point_interpretation':'Invented fixture only'}
    record=public_reference(config,simulation,evaluation,semantic_id='invented-semantic',semantic_hash='a'*64,phase='FINAL')
    assert len(record['limitations'])==16  # 12 base + 3 declared + 1 model denomination.
    diagnostics={leg['id']:{'subperiods':[{},{}]} for leg in p['legs']}
    project_diagnostics(record,diagnostics)
    assert len(record['limitations'])==31  # 5 risk + 2*5 carried-era descriptions.
    original=deepcopy(record)
    assert validate_result(record)==original  # All objects and unrelated scientific fields lossless.
    store=ResearchResults(tmp_path/'invented-projection-store',128*1024**2)
    pub=store.publish(record)
    assert store.read(pub['result_id'])['record']==original
    assert store.publish(record)==pub
    record['limitations'].append({'code':'INVENTED_OVERFLOW','scope':'Entire comparison','text':'Do not silently drop me.'})
    with pytest.raises(ResearchError,match='RESEARCH_INVALID_RESULT'):validate_result(record)


def test_profile10_counts_denomination_limitation_before_debit(tmp_path,monkeypatch):
    root,cfg,p,_=model_fixture(tmp_path,monkeypatch)
    assert len(p['legs'])==5 and len(p['subperiods'])==2
    p['additional_limitations']=[['INVENTED_'+str(i),'Invented limitation '+str(i)] for i in range(3)]
    pin=write(tmp_path/'invented-over-bound-profile.json',p);cfg={**cfg,'profile_ref':pin}
    import polar.scheduled_service as module
    def forbidden(*a,**k):raise AssertionError('PRICE_OR_NATIVE_BEFORE_METADATA_BOUND')
    monkeypatch.setattr(module,'load_market',forbidden);monkeypatch.setattr(module,'bounded_native',forbidden)
    assert ReferenceResearchService(root,128*1024**2).preflight(cfg)['status']=='READY_FOR_BOUND_OPERATION'
    assert not (root/'scheduled-reference-attempts').exists()
    assert profile_value(p)==p  # Same five legs, two eras and three extras fit31.
    # Strict next boundary: four extras require32 and reject before any attempt/value read.
    p['additional_limitations'].append(['INVENTED_3','Overflow stays rejected.'])
    cfg['profile_ref']=write(tmp_path/'invented32-profile.json',p)
    with pytest.raises(ValueError,match='SCHEDULED_PUBLIC_WIRE_BOUND'):ReferenceResearchService(root,128*1024**2).preflight(cfg)
    assert not (root/'scheduled-reference-attempts').exists()
    # Legacy profile5 retains its old30 admission bound and its own31 rejection.
    legacy=deepcopy(p);legacy['schema']='polar.scheduled-reference-profile/5';del legacy['model_price_mapping']
    with pytest.raises(ValueError,match='SCHEDULED_PUBLIC_WIRE_BOUND'):profile_value(legacy)
    legacy['additional_limitations'].pop()
    assert profile_value(legacy)==legacy
