"""Invented-only selected-source profile; never opens owner credentials/network."""
from copy import deepcopy
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
import uuid

import pytest

from polar.import_adjusted_sip import (SELECTED_ADAPTER,SELECTED_PROFILE,TEMPLATE,POLICY,
                                       selected_policy,selected_request)
from polar.import_contract import ImportError,canonical,sha,digest,timestamp
from polar.import_service import ImportService,plan_name
from polar.import_store import ImportStore
from polar.import_raw_sip import job_id,records
from polar.service import Service

START=1767225600


def setup(root,targets=None,mutation=None,mode='fixture'):
    root.mkdir(exist_ok=True)
    targets=targets or ['INVENTED0','INVENTED1','INVENTED2']
    template={**TEMPLATE,'asof':'2026-11-06'}
    owner={'schema':'polar.quant-selected-source-operation/1','fixed_targets':targets,
           'request_profile':{**template,'symbols':'one literal target per job','limit':'10000'}}
    owner_path=root/'owner.json';owner_path.write_bytes(canonical(owner))
    scope={'schema':'polar.selected-adjusted-sip-scope/1','targets':targets,
           'request_template':template,'policy':selected_policy(len(targets)),
           'selection_ref':{'path':str(owner_path),'sha256':sha(owner_path.read_bytes())}}
    if mutation:mutation(scope)
    scope_path=root/'scope.json';scope_path.write_bytes(canonical(scope))
    cfg={'schema':'polar.selected-adjusted-sip-import-config/1','adapter':SELECTED_ADAPTER,
         'mode':mode,'scope_ref':{'path':str(scope_path),'sha256':sha(scope_path.read_bytes())},'seed_refs':[]}
    facade=Service.__new__(Service);facade.artifacts=SimpleNamespace(root=root,limit=64*1024**3)
    result=facade.import_plan(cfg)
    return facade,facade._import_plan_service(result['plan_id']),result['plan_id'],cfg,scope


def body(symbol='INVENTED0',cursor=None):
    return {'bars':{symbol:[{'t':'2020-01-02T00:00:00Z','o':1,'h':2,'l':1,'c':2,'v':0}]},
            'next_page_token':cursor}


def run(facade,pid,replies):
    return facade.import_execute(pid,fixture={'schema':'polar.raw-sip-fixture/1',
                                            'start_seconds':START,'responses':replies})


def test_declared_three_target_request_order_budget_and_source_identity(tmp_path,monkeypatch):
    import polar.import_raw_transport as transport
    monkeypatch.setattr(transport,'RawHttpTransport',lambda *a,**k:pytest.fail('network transport constructed'))
    facade,s,pid,cfg,scope=setup(tmp_path)
    plan=s.load(pid)
    assert pid.startswith('adjustedsipselectedfixture-'+cfg['scope_ref']['sha256']+'-')
    assert plan_name(pid)==pid and plan['scope']=='imports-adjustedsip-selected-fixture-v1/'+cfg['scope_ref']['sha256']
    assert [j['request']['symbols'] for j in plan['jobs']]==scope['targets']
    assert all(j['request']['asof']=='2026-11-06' and j['request']['adjustment']=='all' for j in plan['jobs'])
    assert plan['policy']['jobs']==3 and plan['policy']['gets']==6 and plan['policy']['pages']==2
    assert plan['policy']['total_bytes']==6*1024**2 and plan['policy']['wall_seconds']==400
    assert plan['policy']['additional_bytes']==128*1024**2
    assert all(j['relation']['population_record_id'] is None and j['relation']['source_records']==[]
               and j['relation']['source_target_id'].startswith('selected-source-target-')
               and j['relation']['economic_identity_admission']=='NOT_ISSUED' for j in plan['jobs'])
    assert facade.import_status(pid)['scope_physical_gets']==0
    # Provider-mode metadata planning is generic, without the legacy100 SHA/count.
    other=tmp_path/'provider'
    _,provider,pp,_,_=setup(other,mode='provider')
    assert pp.startswith('adjustedsipselected-') and provider.status(pp)['scope_physical_gets']==0


def test_pagination_lossless_terminal_consume_and_no_refetch(tmp_path):
    facade,s,pid,cfg,scope=setup(tmp_path)
    lexical='{"bars":{"INVENTED0":[{"t":"2020-01-02T00:00:00Z","o":1.2300000,"h":2e0,"l":1,"c":1.23456789,"v":0,"vw":1.234567890123456789}]},"next_page_token":"next"}'
    result=run(facade,pid,[{'body':lexical},{'body':body()},
                         {'body':{'bars':{},'next_page_token':None}}, {'body':body('INVENTED2')}])
    assert result['status']=='complete' and result['counts']['success']==3 and result['counts']['no_rows']==1
    assert facade.import_status(pid)['scope_physical_gets']==4
    terminal=facade.import_terminal(pid,result['attempt_id'],result['manifest_sha256'])
    manifest=terminal['manifest'];source=s.store.root/s.store.path(str(Path(manifest['source_manifest']).parent))
    collection=json.loads((source/'content-manifest.json').read_bytes())
    assert collection['schema']=='polar.vendor-all-adjusted-source-collection/1' and collection['jobs']==3
    rows=[json.loads(line) for p in sorted((source/'parts').glob('*/bars.ndjson')) for line in p.read_bytes().splitlines()]
    assert rows[0]['vendor_adjusted_close']=='1.23456789'  # Never round to future6dp consumer fitness.
    assert rows[0]['vendor_adjusted_open']=='1.2300000' and rows[0]['vendor_adjusted_high']=='2e0'
    assert rows[0]['source_fields_exact_tokens']['vw']=='1.234567890123456789'
    assert rows[0]['asof']=='2026-11-06' and rows[0]['estimated_K'] is None
    assert rows[0]['observed_historical_available_at'] is None and rows[0]['economic_security_id'] is None
    assert rows[0]['asof_semantics']=='REQUEST_ALIAS_MAPPING_NOT_HISTORICAL_VINTAGE'
    assert rows[0]['investor_total_return']=='NOT_ESTABLISHED' and rows[0]['adjustment']=='all'
    index=[json.loads(line) for line in (source/'job-status-index.ndjson').read_bytes().splitlines()]
    assert [v['request']['symbols'] for v in index]==scope['targets']
    assert len({v['source_target_id'] for v in index})==3 and all(v['population_record_id'] is None for v in index)
    assessment={'consumer':'invented-DE','outcome':'source-only transport test, not financial acceptance',
                'next_action':'No provider or financial call'}
    assert facade.import_consume(pid,result['attempt_id'],result['manifest_sha256'],assessment)['status']=='CONSUMED'
    assert facade.import_consume(pid,result['attempt_id'],result['manifest_sha256'],assessment)['status']=='ALREADY_CONSUMED'
    before=s.store.raw('budget.json');old_terminal=s.store.raw('attempts/'+result['attempt_id']+'/content-manifest.json')
    again=run(facade,pid,[])
    assert again['status']=='complete' and s.store.raw('budget.json')==before
    assert facade.import_status(pid)['scope_physical_gets']==4
    assert s.store.raw('attempts/'+result['attempt_id']+'/content-manifest.json')==old_terminal
    assert len(facade.import_attempts(pid)['attempts'])==2


@pytest.mark.parametrize('mutate',[
    lambda x:x.update(extra='unknown'),
    lambda x:x.update(targets=['INVENTED0','INVENTED0']),
    lambda x:x.update(targets=list(reversed(x['targets']))),
    lambda x:x['request_template'].update(asof='2020-09-02'),
    lambda x:x['request_template'].update(adjustment='raw'),
    lambda x:x['request_template'].update(feed='iex'),
    lambda x:x['request_template'].update(currency='EUR'),
    lambda x:x['policy'].update(gets=7),
    lambda x:x['policy'].update(retries=1),
    lambda x:x['policy'].update(redirects=True),
])
def test_scope_unknown_changed_targets_requests_and_budget_reject(tmp_path,mutate):
    with pytest.raises(ImportError):setup(tmp_path,mutation=mutate)
    assert not list(tmp_path.glob('imports-*/**/requests/*.json'))


@pytest.mark.parametrize('changes',[
    {'asof':'2026-02-30'},{'asof':'2026-11-6'},{'asof':None},{'limit':10000.0},
    {'start':'2026-11-07T00:00:00Z'},{'end':'not-a-time'},{'symbols':'A,B'},
    {'symbols':'*'},{'endpoint':'https://other.invalid/bars'},{'sort':'desc'},
])
def test_selected_request_is_exact_and_no_fallback(changes):
    with pytest.raises(ImportError):selected_request({**TEMPLATE,'symbols':'INVENTED','asof':'2026-11-06',**changes})


def test_binding_drift_stops_before_attempt_or_request(tmp_path):
    facade,s,pid,_,scope=setup(tmp_path)
    owner=Path(scope['selection_ref']['path']);owner.write_bytes(b'{}')
    with pytest.raises(Exception):run(facade,pid,[])
    assert facade.import_status(pid)['scope_physical_gets']==0
    assert facade.import_attempts(pid)['attempts']==[]


def test_rate_limit_pauses_without_automatic_retry_and_unknown_inflight_never_reissued(tmp_path):
    facade,s,pid,_,_=setup(tmp_path)
    first=run(facade,pid,[{'status':429}]);assert first['status']=='failed'
    assert facade.import_status(pid)['scope_physical_gets']==1
    run(facade,pid,[]);assert facade.import_status(pid)['scope_physical_gets']==1
    root=tmp_path/'unknown';facade,s,pid,_,_=setup(root)
    j=s.load(pid)['jobs'][0]
    start={'schema':'polar.adjusted-sip-request-start/1','request_id':str(uuid.uuid4()),
           'attempt_id':str(uuid.uuid4()),'sequence':0,'job_id':j['job_id'],'request':j['request'],
           'page':0,'request_cursor':None,'started_at':timestamp(START),'timeout_seconds':45}
    with s.store.locked():s.store.write('requests/'+start['request_id']+'.json',start)
    # Remaining two jobs may run, but the unknown first job is never sent again.
    run(facade,pid,[{'body':{}},{'body':body('INVENTED1')},{'body':body('INVENTED2')}])
    state=facade.import_status(pid)
    assert state['states'][j['job_id']]['reason']=='UNKNOWN_IN_FLIGHT'
    assert len([a for a,_ in records(s) if a['job_id']==j['job_id']])==1
    assert state['counts']['success']==2


def test_scope_namespace_and_legacy_request_identity_stay_distinct(tmp_path):
    from polar.import_adjusted_sip import PROFILE,SCOPE_SHA,ADAPTER
    from polar.import_raw_sip import request as raw_request
    _,s,pid,cfg,_=setup(tmp_path)
    req={**TEMPLATE,'symbols':'INVENTED0'}
    broad=ImportStore(tmp_path,64*1024**3,raw_sip=True,raw_profile=PROFILE)
    assert broad.base=='imports-adjustedsip100-v1/'+SCOPE_SHA
    assert SCOPE_SHA=='d123cb78e0e1e5e091bbc6de04e1693ebc08181775eb72ebe3434fd89d21c077'
    assert job_id({**TEMPLATE,'symbols':'VTI'},PROFILE)=='673daa8e3d3b9ae62af4a75af0672e40bbfb864b33e44a20016e71996f9fe115'
    assert job_id(req,PROFILE)==digest({'adapter':ADAPTER,'request':req})
    assert job_id(req,PROFILE)!=job_id(req,SELECTED_PROFILE)
    with pytest.raises(ImportError):raw_request(req)
    # A new owner/date declaration gets its own scope; no broad cache migration.
    other=tmp_path/'other'
    _,second,_,_,_=setup(other,targets=['DIFFERENT'])
    assert second.store.base!=s.store.base
    seed={'schema':'polar.adjusted-sip-seed/1','request':req,'pages':[{}],
          'completeness':'COMPLETE','provenance':{'invented':True}}
    seedpath=tmp_path/'wrong-asof-seed.json';seedpath.write_bytes(canonical(seed))
    cfg['seed_refs']=[{'path':str(seedpath),'sha256':sha(seedpath.read_bytes())}]
    with pytest.raises(ImportError):s.plan(cfg)
    with pytest.raises(ImportError):plan_name('adjustedsipselected-../bad')


def test_selected_http_child_uses_exact_new_asof_before_mock_network(tmp_path,monkeypatch):
    import polar.import_raw_http as child
    credential=tmp_path/'invented-credential.json';credential.write_bytes(canonical({'key_id':'invented','secret_key':'invented'}))
    request={**TEMPLATE,'symbols':'INVENTED','asof':'2026-11-06'}
    inp={'request':request,'cursor':None,'timeout_seconds':45,'credential_reference':str(credential),'adapter':SELECTED_ADAPTER}
    observed={}
    class Response:
        status=200
        def read(self,limit):return canonical(body('INVENTED'))
        def getheaders(self):return [('content-type','application/json')]
    class Connection:
        def __init__(self,host,**kwargs):assert host=='data.alpaca.markets'
        def request(self,method,path,headers):observed.update(method=method,query=parse_qs(urlsplit(path).query))
        def getresponse(self):return Response()
        def close(self):observed['closed']=True
    output=io.BytesIO()
    with monkeypatch.context() as m:
        m.setattr(child,'CREDENTIAL',credential)
        m.setattr(child.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(canonical(inp))))
        m.setattr(child.sys,'stdout',SimpleNamespace(buffer=output))
        m.setattr(child.http.client,'HTTPSConnection',Connection)
        child.main()
    assert observed['method']=='GET' and observed['query']['asof']==['2026-11-06']
    assert observed['query']['symbols']==['INVENTED'] and observed['query']['adjustment']==['all']
    assert observed['closed'] and json.loads(output.getvalue())['status']==200



def test_selected_provider_execution_authority_and_transport_dispatch(tmp_path,monkeypatch):
    import sys
    import polar.import_raw_transport as transport
    from polar.import_service import code_projection
    facade,s,pid,cfg,_=setup(tmp_path,mode='provider')
    aid=str(uuid.uuid4())
    authority={'schema':'polar.adjusted-sip-execution-authority/1',
      'unit_sha256':cfg['scope_ref']['sha256'],'source_projection':code_projection(),
      'python_sha256':sha(Path(sys.executable).read_bytes()),'binding_refs':[cfg['scope_ref']],
      'attempt_id':aid,'credential_reference':s.load(pid)['unit']['credentials']['reference'],
      'terminal_owner':'invented-DE'}
    ap=tmp_path/'authority.json';ap.write_bytes(canonical(authority))
    observed=[]
    class MockTransport:
        def __init__(self,credential_reference,profile):
            assert profile==SELECTED_PROFILE
            observed.append(('initialized',credential_reference))  # path only; never opened
        def get(self,start,index,timeout):
            # The physical-start record is durable before the selected request.
            assert s.store.exists('requests/'+start['request_id']+'.json')
            observed.append(start['request'])
            return {'status':200,'headers':{'content-type':'application/json'},
                    'body':canonical(body(start['request']['symbols'])),'truncated':False,'error':None}
    monkeypatch.setattr(transport,'RawHttpTransport',MockTransport)
    bad={**authority,'unit_sha256':'0'*64};ap.write_bytes(canonical(bad))
    with pytest.raises(ImportError):facade.import_execute(pid,network=True,attempt_id=aid,
        scope={'path':str(ap),'sha256':sha(ap.read_bytes())})
    assert observed==[] and facade.import_attempts(pid)['attempts']==[]
    ap.write_bytes(canonical(authority))
    # Synthetic clock used only by this mocked provider test; no real sleeps/GETs.
    from polar.import_transport import FixtureClock
    s.clock=FixtureClock(START)
    result=s.execute(pid,network=True,attempt_id=aid,scope={'path':str(ap),'sha256':sha(ap.read_bytes())})
    assert result['status']=='complete' and result['counts']['success']==3
    assert [r['symbols'] for r in observed[1:]]==['INVENTED0','INVENTED1','INVENTED2']
    assert all(r['asof']=='2026-11-06' for r in observed[1:])
