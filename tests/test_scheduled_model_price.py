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
    for mutate in ('fractional','bool','inactive','unbound','legacy'):
        bad=deepcopy(p)
        if mutate=='fractional':bad['model_price_mapping']['multipliers'][a]=[3,2]
        if mutate=='bool':bad['model_price_mapping']['multipliers'][c]=[True,1]
        if mutate=='inactive':bad['legs'][0]['weights'][c]=[1,100];bad['legs'][0]['weights'][b]=[1,2]
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
