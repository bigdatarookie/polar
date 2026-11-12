"""Saved tapes, not inferred trades; public invented fixtures only."""
from copy import deepcopy
import json
import pytest
from fastapi.testclient import TestClient
from polar.history_bundle import canonical, sha
from polar.research_results import ResearchResults, ResearchError
from polar.research_executions import project
from polar.api import create_app
from polar.service import Service
from polar.config import Settings
from test_research_results import invented_result


def fixture(tmp_path, kind='scheduled', *, cash=False, clipped=False):
    tmp_path.mkdir(exist_ok=True)
    results=ResearchResults(tmp_path,128*1024**2);r=invented_result()
    legs=[]
    for series in r['series']:
        series['values'][1]['value']='100000'
        nav=[{'nominal_ns':1577998800000000000+i*86400*10**9,'nav_cents':10000000,'cash_cents':10000000,'exposure_cents':0,'positions':{},'flat_cents':0,'bps_cents':0} for i in range(2)]
        oid=series['id']+'/2020-01-03/BUY/AAA';ns=1578085200000000000
        orders=[] if cash else [{'id':oid,'symbol':'AAA','side':'BUY','at_ns':ns,'intended_quantity':2,'routed_quantity':0 if clipped else 2,'reason':'FEE_AWARE_BUDGET_CAP' if clipped else None}]
        fills=[] if cash or clipped else [{'id':oid,'symbol':'AAA','side':'BUY','at_ns':ns,'q':2,'price_micro':12345678,'fee_cents':103,'settled_cents':2469}]
        legs.append({'id':series['id'],'nav':nav,'orders':orders,'fills':fills})
    simulation={'schema':'polar.ci-research-simulation/1','legs':legs}
    if kind!='ci':
        simulation['quote_basis']='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT';simulation['quantity_unit']='WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE'
        r['basis']['wealth_basis']=simulation['quote_basis'];r['question']['id']='invented.FINAL'
    if kind=='ci':name='simulation.json';data=simulation;schema='polar.ci-research-semantic-manifest/1';prefix='ci-experiment-';parent='ci-research-experiments';r['question']['id']='invented'
    elif kind=='ppo':name='final.json';data={'simulation':simulation};schema='polar.reference-ppo-semantic-manifest/1';prefix='reference-experiment-';parent='reference-research-experiments'
    else:
        name='phases.json';data={'FINAL':{'simulation':simulation}};schema='polar.'+('scheduled-reference' if kind=='scheduled' else 'reference')+'-semantic-manifest/1';prefix=('scheduled-reference' if kind=='scheduled' else 'reference')+'-experiment-';parent='reference-research-experiments'
    body=canonical(data);manifest={'schema':schema,'files':{name:{'sha256':sha(body),'bytes':len(body)}}};raw=canonical(manifest);sid=prefix+sha(raw)
    with results.locked():results._publish(parent,sid,{name:body,'manifest.json':raw},file_limit=32*1024**2)
    r['provenance']=[{'role':'semantic_manifest','id':sid,'sha256':sha(raw)}]
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
