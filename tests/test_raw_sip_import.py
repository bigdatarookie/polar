"""Frozen invented first-unit checks; no secrets/network/provider/native inputs."""
import json
from pathlib import Path
import uuid

import pytest

from polar.import_contract import canonical,sha,digest,timestamp,ImportError
from polar.import_service import ImportService
from polar.import_store import ImportStore
from polar.import_raw_sip import ADAPTER,ENDPOINT,page,job_id,records,disposition

START=1767225600


def setup(tmp_path,n=1,seeds=None):
    root=tmp_path.resolve()
    request={'endpoint':ENDPOINT,'symbols':'INVENTED','adjustment':'raw','feed':'sip','currency':'USD',
             'timeframe':'1Day','asof':'2020-09-02','limit':10000,'sort':'asc',
             'start':'2019-08-30T00:00:00Z','end':'2023-09-01T00:00:00Z'}
    unit={'jobs':[{'job_id':'invented-'+str(i),'population_record_id':'invented-row-'+str(i),
                    'frozen_ordinal':i,'request':{**request,'symbols':'INVENTED'+str(i)}} for i in range(n)]}
    def ref(name,value):
        path=root/name;raw=canonical(value);path.write_bytes(raw)
        return {'path':str(path),'sha256':sha(raw)}
    cfg={'schema':'polar.raw-sip-import-config/1','adapter':ADAPTER,'mode':'fixture',
         'unit_ref':ref('unit.json',unit),'reuse_ref':ref('reuse.json',{'scope':'invented'}),
         'seed_refs':seeds or []}
    service=ImportService(ImportStore(root,64*1024**3,fixture=True,raw_sip=True))
    return service,service.plan(cfg)['plan_id'],cfg


def run(service,pid,responses):
    return service.execute(pid,fixture={'schema':'polar.raw-sip-fixture/1',
                                       'start_seconds':START,'responses':responses})


def body(symbol='INVENTED0',cursor=None):
    return {'bars':{symbol:[{'t':'2019-08-30T04:00:00Z','o':10,'h':11,'l':9,'c':10,'v':0}]},
            'next_page_token':cursor}


def test_empty_complete_reuse_and_terminal_consume(tmp_path):
    service,pid,_=setup(tmp_path)
    first=run(service,pid,[{'body':{'bars':{},'next_page_token':None}}])
    assert first['status']=='complete' and first['counts']['no_rows']==1
    manifest,state=service.terminal(first['attempt_id'],first['manifest_sha256'])
    assessment={'consumer':'invented-consumer','outcome':'STRUCTURAL_ONLY','next_action':'no finance'}
    assert service.consume(pid,first['attempt_id'],first['manifest_sha256'],assessment)['status']=='CONSUMED'
    assert service.consume(pid,first['attempt_id'],first['manifest_sha256'],assessment)['status']=='ALREADY_CONSUMED'
    second=run(service,pid,[])
    assert second['status']=='complete'
    assert service.status(pid)['scope_physical_gets']==1


def test_exact_tokens_two_pages_outside_and_consumer(tmp_path):
    service,pid,_=setup(tmp_path)
    first='{"bars":{"INVENTED0":[{"t":"2019-08-30T04:00:00Z","o":1.2300,"h":2e0,"l":1,"c":1.5,"v":0,"n":7,"vw":1.234567890123456789}]},"next_page_token":"opaque"}'
    final=body();final['bars']['INVENTED0'][0]['t']='2023-09-01T04:00:00Z'
    result=run(service,pid,[{'body':first},{'body':final}]);assert result['status']=='complete'
    manifest,_=service.terminal(result['attempt_id'],result['manifest_sha256'])
    source=Path(service.store.root/service.store.path(manifest['source_manifest']))
    from polar.hyp003_source import Sources,object_value
    info=Sources().add({'adapter':'polar.partial-raw-pv-source-content/1',
        'directory':str(source.parent),'manifest_sha256':sha(source.read_bytes())},True)
    rows=object_value(info,'bars.ndjson')
    assert rows[0]['raw_open']=='1.2300' and rows[0]['raw_high']=='2e0'
    assert rows[0]['raw_fields_exact_tokens']['vw']=='1.234567890123456789'
    assert rows[1]['window_classification']=='OUTSIDE_OR_UNKNOWN_WINDOW'
    assert rows[0]['observed_historical_available_at'] is None
    assert len(object_value(info,'parent-coverage-ledger.ndjson'))==1
    starts=records(service)
    assert starts[1][0]['request_cursor']=='opaque'
    assert starts[1][0]['started_at']>starts[0][0]['started_at']


@pytest.mark.parametrize('cursor,expected',[('same','REPEATED_CURSOR'),('next','PAGE_LIMIT_PARTIAL')])
def test_page_stops_are_partial_no_retry(tmp_path,cursor,expected):
    service,pid,_=setup(tmp_path)
    result=run(service,pid,[{'body':body(cursor='same')},{'body':body(cursor=cursor)}])
    assert result['status']=='partial'
    state=next(iter(service.status(pid)['states'].values()))
    assert state['reason']==expected and len(state['pages'])==2
    run(service,pid,[])
    assert service.status(pid)['scope_physical_gets']==2


@pytest.mark.parametrize('status,reason',[(401,'AUTH_OR_RIGHTS_REFUSAL'),(429,'HTTP_FAILURE_NO_RETRY'),
                                      (302,'HTTP_FAILURE_NO_RETRY'),(500,'HTTP_FAILURE_NO_RETRY')])
def test_failure_scopes_no_retry(tmp_path,status,reason):
    service,pid,_=setup(tmp_path,2)
    replies=[{'status':status},{'body':body(symbol='INVENTED1')}]
    run(service,pid,replies)
    state=service.status(pid);first=next(iter(state['states'].values()))
    assert first['reason']==reason
    assert state['scope_physical_gets']==(1 if status==401 else 2)
    run(service,pid,[])
    assert service.status(pid)['scope_physical_gets']==state['scope_physical_gets']


def test_unknown_inflight_is_not_implicitly_reissued(tmp_path):
    service,pid,_=setup(tmp_path);job=service.load(pid)['jobs'][0]
    start={'schema':'polar.raw-sip-request-start/1','request_id':str(uuid.uuid4()),
           'attempt_id':str(uuid.uuid4()),'sequence':0,'job_id':job['job_id'],
           'request':job['request'],'page':0,'request_cursor':None,'started_at':timestamp(START),
           'timeout_seconds':45}
    service.store.write('requests/'+start['request_id']+'.json',start)
    run(service,pid,[])
    state=service.status(pid)
    assert state['scope_physical_gets']==1
    assert state['states'][job['job_id']]['reason']=='UNKNOWN_IN_FLIGHT'


def test_saved_body_replayed_before_checkpoint(tmp_path):
    service,pid,_=setup(tmp_path);job=service.load(pid)['jobs'][0]
    start={'schema':'polar.raw-sip-request-start/1','request_id':str(uuid.uuid4()),
           'attempt_id':str(uuid.uuid4()),'sequence':0,'job_id':job['job_id'],
           'request':job['request'],'page':0,'request_cursor':None,'started_at':timestamp(START),
           'timeout_seconds':45}
    service.store.write('requests/'+start['request_id']+'.json',start)
    response={'request_start_sha256':digest(start),'body':service.store.object(canonical(body())),
              'status':200,'headers':{'content-type':'application/json'},'error':None,'truncated':False}
    service.store.write('responses/'+start['request_id']+'.json',response)
    result=run(service,pid,[])
    assert result['status']=='complete' and service.status(pid)['scope_physical_gets']==1


def test_cumulative_deadline_survives_new_attempt(tmp_path):
    service,pid,_=setup(tmp_path,20)
    replies=[]
    for i in range(20):
        replies += [{'duration_seconds':45,'body':body(symbol='INVENTED'+str(i),cursor='c'+str(i))},
                    {'duration_seconds':45,'body':body(symbol='INVENTED'+str(i))}]
    first=run(service,pid,replies)
    budget=service.store.raw('budget.json')
    before=service.status(pid)['scope_physical_gets']
    assert first['reason']=='OPERATION_DEADLINE' and before==20
    second=run(service,pid,[])
    assert second['reason']=='OPERATION_DEADLINE'
    assert service.store.raw('budget.json')==budget and service.status(pid)['scope_physical_gets']==before


def test_body_limit_and_wrong_returned_symbol(tmp_path):
    service,pid,_=setup(tmp_path,2)
    run(service,pid,[{'body':'x'*1048577},{'body':body(symbol='UNREQUESTED')}])
    values=list(service.status(pid)['states'].values())
    assert [v['reason'] for v in values]==['RESPONSE_BODY_LIMIT','UNEXPECTED_RETURNED_SYMBOL']
    assert records(service)[0][1]['body']['bytes']==1048577


def test_network_flag_and_fixture_mode_fail_closed(tmp_path):
    service,pid,_=setup(tmp_path)
    with pytest.raises(ImportError,match='IMPORT_NETWORK_NOT_AUTHORIZED'):
        service.execute(pid,network=True,fixture={'schema':'polar.raw-sip-fixture/1','start_seconds':START,'responses':[]})


def test_seed_request_and_body_revalidated_before_reuse(tmp_path):
    service,pid,cfg=setup(tmp_path)
    req=service.load(pid)['jobs'][0]['request']
    raw=canonical(body());path=tmp_path/'seed-body.json';path.write_bytes(raw)
    seed={'schema':'polar.raw-sip-seed/1','request':req,'completeness':'COMPLETE',
          'provenance':{'original_receipt':'invented-only'},'pages':[{'request_cursor':None,
          'body_ref':{'path':str(path.resolve()),'sha256':sha(raw)}}]}
    seedpath=tmp_path/'seed.json';seedpath.write_bytes(canonical(seed))
    cfg['seed_refs']=[{'path':str(seedpath.resolve()),'sha256':sha(seedpath.read_bytes())}]
    seeded=service.plan(cfg)['plan_id']
    assert run(service,seeded,[])['status']=='complete'
    assert service.status(seeded)['scope_physical_gets']==0


def test_duplicate_fields_rejected_and_requests_typed():
    with pytest.raises(ImportError):page(b'{"bars":{},"bars":{}}')
    with pytest.raises(ImportError):job_id({'symbols':'INVENTED'})


def test_forty_gets_spent_and_new_plan_cannot_reset(tmp_path):
    service,pid,cfg=setup(tmp_path,20)
    replies=[]
    for i in range(20):
        replies += [{'body':body(symbol='INVENTED'+str(i),cursor='p'+str(i))},
                    {'body':body(symbol='INVENTED'+str(i))}]
    assert run(service,pid,replies)['status']=='complete'
    assert service.status(pid)['scope_physical_gets']==40
    unit=service.load(pid)['unit']
    for job in unit['jobs']:job['request']['symbols']+='NEW'
    path=tmp_path/'second-unit.json';path.write_bytes(canonical(unit))
    cfg['unit_ref']={'path':str(path.resolve()),'sha256':sha(path.read_bytes())}
    second=service.plan(cfg)['plan_id']
    result=run(service,second,[])
    assert result['reason']=='OPERATION_REQUEST_OR_BYTE_LIMIT'
    assert service.status(second)['scope_physical_gets']==40


def test_malformed_body_retained_outside_parseable_source_manifest(tmp_path):
    service,pid,_=setup(tmp_path)
    result=run(service,pid,[{'body':'<html>upstream failure</html>'}])
    manifest,_=service.terminal(result['attempt_id'],result['manifest_sha256'])
    ref=records(service)[0][1]['body']
    assert service.store.object_read(ref)==b'<html>upstream failure</html>'
    assert ref['path'] in manifest['objects']
    source=Path(service.store.root/service.store.path(manifest['source_manifest']))
    from polar.hyp003_source import Sources,object_value
    info=Sources().add({'adapter':'polar.partial-raw-pv-source-content/1',
        'directory':str(source.parent),'manifest_sha256':sha(source.read_bytes())},True)
    assert object_value(info,'bars.ndjson')==[]
    assert ref['path'] not in info['manifest']['objects']


def test_terminal_hash_rejects_tampered_capture(tmp_path):
    service,pid,_=setup(tmp_path)
    result=run(service,pid,[{'body':body()}])
    ref=records(service)[0][1]['body']
    target=service.store.root/service.store.path(ref['path'])
    target.chmod(0o600);target.write_bytes(b'{}')
    with pytest.raises(ImportError,match='IMPORT_TERMINAL_OBJECT_HASH'):
        service.terminal(result['attempt_id'],result['manifest_sha256'])
