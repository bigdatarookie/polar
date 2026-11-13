"""Saved tapes, not inferred trades; public invented fixtures only."""
from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
from polar.history_bundle import canonical, sha
from polar.gym_contract import canonical as model_canonical
from polar.research_results import ResearchResults, ResearchError
from polar.research_executions import project
from polar.api import create_app
from polar.service import Service
from polar.config import Settings
from test_research_results import invented_result


def fixture(tmp_path, kind='scheduled', *, cash=False, clipped=False, model=False, zero=False):
    tmp_path.mkdir(exist_ok=True)
    results=ResearchResults(tmp_path,128*1024**2);r=invented_result()
    legs=[]
    for series in r['series']:
        series['values'][1]['value']='100000'
        nav=[{'nominal_ns':1577998800000000000+i*86400*10**9,'nav_cents':10000000,'cash_cents':10000000,'exposure_cents':0,'positions':{},'flat_cents':0,'bps_cents':0} for i in range(2)]
        oid=series['id']+'/2020-01-03/BUY/AAA';ns=1578085200000000000
        orders=[] if cash else [{'id':oid,'symbol':'AAA','side':'BUY','at_ns':ns,'intended_quantity':2,'routed_quantity':0 if clipped else 2,'reason':'FEE_AWARE_BUDGET_CAP' if clipped else None}]
        fills=[] if cash or clipped else [{'id':oid,'symbol':'AAA','side':'BUY','at_ns':ns,'q':2,'price_micro':12345678,'fee_cents':103,'settled_cents':2469}]
        if zero:
            orders.insert(0,{'id':series['id']+'/2020-01-03/SELL/AAA','symbol':'AAA','side':'SELL',
                'at_ns':ns-100,'intended_quantity':0,'routed_quantity':0,'reason':'ZERO_DELTA_NO_ORDER',
                'consumed_operands':{'decision_id':series['id']+'/2020-01-03','desired_delta':0,
                    'target':0,'holdings_before':{'AAA':0}}})
        legs.append({'id':series['id'],'nav':nav,'orders':orders,'fills':fills})
    simulation={'schema':'polar.ci-research-simulation/1','legs':legs}
    if kind!='ci':
        simulation['quote_basis']='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT';simulation['quantity_unit']='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE'
        r['basis']['wealth_basis']=simulation['quote_basis'];r['question']['id']='invented.FINAL'
    if kind=='ci':name='simulation.json';data=simulation;schema='polar.ci-research-semantic-manifest/1';prefix='ci-experiment-';parent='ci-research-experiments';r['question']['id']='invented'
    elif kind=='ppo':name='final.json';data={'simulation':simulation};schema='polar.reference-ppo-semantic-manifest/1';prefix='reference-experiment-';parent='reference-research-experiments'
    else:
        name='phases.json';data={'FINAL':{'simulation':simulation}};schema='polar.'+('scheduled-reference' if kind=='scheduled' else 'reference')+'-semantic-manifest/1';prefix=('scheduled-reference' if kind=='scheduled' else 'reference')+'-experiment-';parent='reference-research-experiments'
    binding={'code_revision':r['bindings']['code_revision'],'runtime_image_id':r['bindings']['runtime_id'],
             'pins':{'input_sha256':r['bindings']['data_sha256'],'protocol_sha256':r['bindings']['protocol_sha256']},
             'input_ref':{'sha256':r['bindings']['data_sha256']},'protocol_ref':{'sha256':r['bindings']['protocol_sha256']},
             'candidate_id':r['bindings']['candidate_id'],'experiment_id':r['bindings']['experiment_id']}
    extra={}
    if model:
        mapping={'schema':'polar.reference-model-price-mapping/1','source_input_sha256':r['bindings']['data_sha256'],
                 'multipliers':{'AAA':[100,1]},'lot_size':1,'active_unit':'COARSE100_SYNTHETIC_REFERENCE_UNIT_NOT_PHYSICAL_SHARE'}
        profile={'schema':'polar.scheduled-reference-profile/10','input_sha256':r['bindings']['data_sha256'],
                 'symbols':['AAA'],'legs':[{'weights':{'AAA':[1,1]}}], 'model_price_mapping':mapping}
        simulation['quantity_unit']=mapping['active_unit']
        data['FINAL']['plan']={'model_price_mapping':mapping,'capture_consumed_sizing':True,
            'consumed_witness_schema':'polar.model-price-consumed-operands/1','quantity_unit':mapping['active_unit']}
        extra={'profile.json':canonical(profile)}
        r['provenance'].append({'role':'model_price_mapping','id':'COARSE100_MODEL_NOT_SOURCE_PRICE','sha256':sha(model_canonical(mapping))})
    body=canonical(data);bound=canonical(binding);manifest={'schema':schema,'files':{name:{'sha256':sha(body),'bytes':len(body)},'bindings.json':{'sha256':sha(bound),'bytes':len(bound)}}};manifest['files'].update({k:{'sha256':sha(v),'bytes':len(v)} for k,v in extra.items()});raw=canonical(manifest);sid=prefix+sha(raw)
    with results.locked():results._publish(parent,sid,{name:body,'bindings.json':bound,'manifest.json':raw,**extra},file_limit=32*1024**2)
    r['provenance']=[x for x in r['provenance'] if x['role']=='model_price_mapping']+[{'role':'semantic_manifest','id':sid,'sha256':sha(raw)}]
    published=results.publish(r)
    return results,published['result_id'],tmp_path/parent/sid,name


@pytest.mark.parametrize('kind',['scheduled','ridge','ppo','ci'])
def test_actual_fill_projection_all_saved_families(tmp_path,kind):
    results,rid,_,_=fixture(tmp_path,kind)
    output=project(results,rid)
    assert output['status']=='OK' and output['total']==1
    event=output['items'][0]
    assert event['symbol']=='AAA' and event['price_micro']=='12345678' and event['filled_quantity']=='2'
    assert event['timestamp_ns']=='1578085200000000000' and event['timestamp']=='2020-01-03T21:00:00Z'
    assert not output['raw_ohlc_overlay_compatible']
    assert output['result_id']==rid and output['series_id']=='invented-strategy'
    assert project(results,rid,'invented-benchmark')['series_id']=='invented-benchmark'


def test_cash_empty_is_known_and_clipped_intent_is_not_a_fill(tmp_path):
    results,rid,_,_=fixture(tmp_path/'cash',cash=True)
    assert project(results,rid)['total']==0 and project(results,rid)['status']=='OK'
    results,rid,_,_=fixture(tmp_path/'clipped',clipped=True)
    e=project(results,rid)['items'][0]
    assert e['status']=='NOT_ROUTED' and e['price_micro'] is None and e['fee_cents'] is None and e['filled_quantity']=='0'


def test_unbound_is_unknown_not_empty(tmp_path):
    results=ResearchResults(tmp_path,128*1024**2);rid=results.publish(invented_result())['result_id']
    output=project(results,rid)
    assert output['status']=='UNAVAILABLE' and output['total'] is None


def rewrite(path,content):
    path.chmod(0o600);path.write_bytes(content)


@pytest.mark.parametrize('mutation',['member','manifest','symlink'])
def test_saved_member_hash_and_symlink_fail_closed(tmp_path,mutation):
    results,rid,d,name=fixture(tmp_path)
    if mutation=='member':rewrite(d/name,(d/name).read_bytes()+b' ')
    elif mutation=='manifest':rewrite(d/'manifest.json',(d/'manifest.json').read_bytes()+b' ')
    else:
        original=(d/name).read_bytes();(d/name).unlink();other=tmp_path/'external';other.write_bytes(original);(d/name).symlink_to(other)
    with pytest.raises((ResearchError,ValueError)):project(results,rid)


def test_http_page_validation_no_original_mutation(tmp_path):
    results,rid,_,_=fixture(tmp_path)
    before={str(p):sha(p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file()}
    client=TestClient(create_app(Service(Settings('unused',tmp_path))))
    path='/v1/research/results/'+rid+'/executions'
    assert client.get(path+'?limit=1').json()['total']==1
    assert client.get(path+'?offset=1').json()['items']==[]
    assert client.get(path+'?series_id=missing').status_code==422
    assert client.get(path+'?limit=101').status_code==422
    assert before=={str(p):sha(p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file()}


def test_input_bound_navigation_never_ticker_only():
    from polar.research_executions import navigation
    r=invented_result();r['bindings']['data_sha256']='070ea3eb9363894aa37ec4254997be34116b745166b173e1ab1e7dcc4182e3cd'
    x=navigation(r,'AAPL')
    assert x['status']=='BOUND' and x['instrument_id']=='hist-us-0001' and x['mapping_status']=='DECLARED_CURRENT_ONLY'
    assert 'histrev-8513' in x['dataset_revision']
    r['bindings']['data_sha256']='9'*64
    assert navigation(r,'AAPL')['status']=='UNRESOLVED'
    assert navigation(r,'UNKNOWN')['instrument_id'] is None


@pytest.mark.parametrize('mutation',['phase_nav','input_binding','fill_symbol','fill_quantity','fill_timestamp'])
def test_rehashed_wrong_phase_source_or_fill_still_rejected(tmp_path,mutation):
    results,rid,d,name=fixture(tmp_path)
    record=deepcopy(results.read(rid)['record']);phase=json.loads((d/name).read_bytes());binding=json.loads((d/'bindings.json').read_bytes())
    leg=phase['FINAL']['simulation']['legs'][0]
    if mutation=='phase_nav':leg['nav'][1]['nav_cents']+=1
    elif mutation=='input_binding':binding['input_ref']['sha256']='f'*64
    elif mutation=='fill_symbol':leg['fills'][0]['symbol']='OTHER'
    elif mutation=='fill_quantity':leg['fills'][0]['q']+=1
    else:leg['fills'][0]['at_ns']+=1
    files={name:canonical(phase),'bindings.json':canonical(binding)}
    manifest={'schema':'polar.scheduled-reference-semantic-manifest/1','files':{k:{'sha256':sha(v),'bytes':len(v)} for k,v in files.items()}}
    raw=canonical(manifest);sid='scheduled-reference-experiment-'+sha(raw)
    with results.locked():results._publish('reference-research-experiments',sid,{**files,'manifest.json':raw},file_limit=32*1024**2)
    record['provenance'][0].update(id=sid,sha256=sha(raw));rid=results.publish(record)['result_id']
    with pytest.raises(ResearchError):project(results,rid)


def test_saved_coarse_model_zero_delta_is_unfilled_not_dropped_or_inferred(tmp_path):
    results,rid,_,_=fixture(tmp_path,model=True,zero=True)
    out=project(results,rid)
    assert out['total']==2 and out['quote_basis']=='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT'
    assert out['quantity_unit']=='COARSE100_SYNTHETIC_REFERENCE_UNIT_NOT_PHYSICAL_SHARE'
    zero,filled=out['items']
    assert zero['intended_quantity']==zero['routed_quantity']==zero['filled_quantity']=='0'
    assert zero['status']=='NOT_ROUTED' and zero['reason']=='ZERO_DELTA_NO_ORDER'
    assert zero['price_micro'] is zero['fee_cents'] is zero['settled_notional_cents'] is None
    assert filled['status']=='FILLED' and filled['order_id']!=zero['order_id']
    assert not out['raw_ohlc_overlay_compatible']
    assert project(results,rid,limit=1)['next_offset']==1


def republish_model(results,rid,d,name,mutate):
    record=deepcopy(results.read(rid)['record']);phase=json.loads((d/name).read_bytes())
    profile=json.loads((d/'profile.json').read_bytes());mutate(phase,profile,record)
    files={name:canonical(phase),'bindings.json':(d/'bindings.json').read_bytes(),'profile.json':canonical(profile)}
    manifest={'schema':'polar.scheduled-reference-semantic-manifest/1','files':{k:{'sha256':sha(v),'bytes':len(v)} for k,v in files.items()}}
    raw=canonical(manifest);sid='scheduled-reference-experiment-'+sha(raw)
    with results.locked():results._publish('reference-research-experiments',sid,{**files,'manifest.json':raw},file_limit=32*1024**2)
    next(x for x in record['provenance'] if x['role']=='semantic_manifest').update(id=sid,sha256=sha(raw))
    return results.publish(record)['result_id']


@pytest.mark.parametrize('mutation',['reason','routed','fill','witness','delta','holdings','capture','schema','mapping','public_mapping','bool_lot','unit','delta_bool','target_bool','decision','mapping_no_lf'])
def test_rehashed_zero_delta_cannot_relax_saved_binding(tmp_path,mutation):
    results,rid,d,name=fixture(tmp_path,model=True,zero=True)
    def change(phase,profile,record):
        final=phase['FINAL'];leg=final['simulation']['legs'][0];o=leg['orders'][0]
        if mutation=='reason':o['reason']='FEE_AWARE_BUDGET_CAP'
        elif mutation=='routed':o['routed_quantity']=1
        elif mutation=='fill':leg['fills'].append({**leg['fills'][0],'id':o['id']})
        elif mutation=='witness':del o['consumed_operands']
        elif mutation=='delta':o['consumed_operands']['desired_delta']=1
        elif mutation=='holdings':o['consumed_operands']['holdings_before']['AAA']=1
        elif mutation=='capture':final['plan']['capture_consumed_sizing']=False
        elif mutation=='schema':profile['schema']='polar.scheduled-reference-profile/5'
        elif mutation=='mapping':final['plan']['model_price_mapping']['lot_size']=2
        elif mutation=='public_mapping':next(x for x in record['provenance'] if x['role']=='model_price_mapping')['sha256']='a'*64
        elif mutation=='bool_lot':profile['model_price_mapping']['lot_size']=True
        elif mutation=='unit':final['simulation']['quantity_unit']='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE'
        elif mutation=='delta_bool':o['consumed_operands']['desired_delta']=False
        elif mutation=='target_bool':o['consumed_operands']['target']=False
        elif mutation=='decision':o['consumed_operands']['decision_id']='different/2020-01-03'
        else:next(x for x in record['provenance'] if x['role']=='model_price_mapping')['sha256']=sha(canonical(profile['model_price_mapping']))
    other=republish_model(results,rid,d,name,change)
    with pytest.raises((ResearchError,ValueError)):project(results,other)


def test_legacy_zero_intent_stays_rejected(tmp_path):
    results,rid,_,_=fixture(tmp_path,zero=True)
    with pytest.raises(ResearchError):project(results,rid)


def test_coarse_model_zero_cannot_be_relabelled_as_raw_share_basis(tmp_path):
    results,rid,d,name=fixture(tmp_path,model=True,zero=True)
    def change(phase,profile,record):
        phase['FINAL']['simulation']['quote_basis']='MODELED_RAW_SHARE_PRICE'
        record['basis']['wealth_basis']='PRICE_ONLY'
    other=republish_model(results,rid,d,name,change)
    with pytest.raises(ResearchError):project(results,other)


def test_registered_source_navigation_is_input_scoped_and_cached_per_symbol(tmp_path):
    from polar.research_executions import REGISTERED_NAVIGATION_INPUTS
    results,rid,d,name=fixture(tmp_path,model=True,zero=True)
    # This unit tests dispatch/cache using an invented lookup. Actual registration
    # and immutable-publication correspondence are exercised in history tests.
    import polar.research_executions as mod
    source=results.read(rid)['record']['bindings']['data_sha256'];seen=[]
    old=mod.REGISTERED_NAVIGATION_INPUTS
    mod.REGISTERED_NAVIGATION_INPUTS={source}
    def lookup(ih,symbol):
        seen.append((ih,symbol));return {'dataset_id':'invented-history','dataset_revision':'histrev-'+'a'*64,'instrument_id':'hist-sip-AAA','source_symbol':'AAA','source_member_sha256':'b'*64,'evidence_sha256':'c'*64,'input_sha256':ih,'mapping_status':'DECLARED_CURRENT_ONLY','basis_relation':'Invented dates only; no raw price equivalence'}
    try:
        out=project(results,rid,registered_lookup=lookup)
        assert seen==[(source,'AAA')] and all(x['instrument']['status']=='BOUND' for x in out['items'])
        assert out['items'][0]['status']=='NOT_ROUTED' and out['raw_ohlc_overlay_compatible'] is False
        seen.clear();mod.REGISTERED_NAVIGATION_INPUTS=set();project(results,rid,registered_lookup=lookup);assert seen==[]
    finally:mod.REGISTERED_NAVIGATION_INPUTS=old



def test_service_http_uses_registered_navigation_without_mutating_saved_tape(tmp_path,monkeypatch):
    import polar.research_executions as mod
    results,rid,_,_=fixture(tmp_path)
    source=results.read(rid)['record']['bindings']['data_sha256']
    monkeypatch.setattr(mod,'REGISTERED_NAVIGATION_INPUTS',{source})
    service=Service(Settings('unused',tmp_path));calls=[]
    def lookup(ih,symbol):
        calls.append((ih,symbol));return {'dataset_id':'invented-history','dataset_revision':'histrev-'+'a'*64,
            'instrument_id':'hist-sip-AAA','source_symbol':symbol,'source_member_sha256':'b'*64,
            'evidence_sha256':'c'*64,'input_sha256':ih,'mapping_status':'DECLARED_CURRENT_ONLY',
            'basis_relation':'Invented registered source dates, no price equivalence'}
    monkeypatch.setattr(service.history_registry,'research_navigation',lookup)
    before={str(p):sha(p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file()}
    response=TestClient(create_app(service)).get('/v1/research/results/'+rid+'/executions')
    assert response.status_code==200 and response.json()['items'][0]['instrument']['status']=='BOUND'
    assert calls==[(source,'AAA')]
    assert before=={str(p):sha(p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file()}
