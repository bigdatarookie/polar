"""Invented-only profile/namespace regressions over the shared importer executor."""
import json
import uuid
from pathlib import Path

import pytest
from polar.import_contract import canonical,sha,digest,timestamp,ImportError
from polar.import_service import ImportService
from polar.import_store import ImportStore
from polar.import_raw_sip import job_id,records
from polar.import_adjusted_sip import ADAPTER,TEMPLATE,PROFILE,POLICY

START=1767225600

def setup(root,n=2,seed_refs=None):
    root.mkdir(exist_ok=True)
    aliases=['INVENTED'+str(i) for i in range(n)]
    relations=[{'literal_symbol':a,'population_record_id':'row-'+str(i),'source_row_ordinal':i}
               for i,a in enumerate(aliases)]
    relations.append({'literal_symbol':aliases[0],'population_record_id':'separate-row','source_row_ordinal':999})
    scope={'schema':'polar.v033-broad-acquisition-scope/1','aliases':aliases,
           'source_records':relations,'request_template':TEMPLATE}
    raw=canonical(scope);p=root/'scope.json';p.write_bytes(raw)
    cfg={'schema':'polar.adjusted-sip-import-config/1','adapter':ADAPTER,'mode':'fixture',
         'scope_ref':{'path':str(p),'sha256':sha(raw)},'seed_refs':seed_refs or []}
    service=ImportService(ImportStore(root,64*1024**3,fixture=True,raw_sip=True,raw_profile=PROFILE))
    return service,service.plan(cfg)['plan_id'],cfg

def run(s,p,replies):
    return s.execute(p,fixture={'schema':'polar.raw-sip-fixture/1','start_seconds':START,'responses':replies})

def body(i=0,cursor=None):
    return {'bars':{'INVENTED'+str(i):[{'t':'2020-01-02T00:00:00Z','o':10,'h':11,'l':9,'c':10,'v':1}]},'next_page_token':cursor}

def collection(s,result):
    manifest,_=s.terminal(result['attempt_id'],result['manifest_sha256'])
    root=s.store.root/s.store.path(str(Path(manifest['source_manifest']).parent))
    return root,json.loads((root/'content-manifest.json').read_bytes())

def test_namespaced_adjusted_fields_and_all_relations(tmp_path):
    s,p,_=setup(tmp_path)
    request=s.load(p)['jobs'][0]['request']
    assert p.startswith('adjustedsip100fixture-') and s.store.base.startswith('imports-adjustedsip100-fixture-v1/')
    assert s.load(p)['policy']==POLICY
    raw={**request,'adjustment':'raw'}
    assert job_id(request,PROFILE)!=job_id(raw)
    with pytest.raises(ImportError):job_id(request)
    with pytest.raises(ImportError):job_id(raw,PROFILE)
    text='{"bars":{"INVENTED0":[{"t":"2020-01-02T00:00:00Z","o":1.2300,"h":2e0,"l":1,"c":1.5,"v":0,"vw":1.234567890123456789}]},"next_page_token":null}'
    result=run(s,p,[{'body':text},{'body':{'bars':{},'next_page_token':None}}])
    assert result['status']=='complete' and result['counts']['no_rows']==1
    root,index=collection(s,result)
    assert index['schema']=='polar.vendor-all-adjusted-source-collection/1'
    rows=[json.loads(line) for line in (root/'parts/00000/bars.ndjson').read_text().splitlines()]
    row=rows[0]
    assert row['vendor_adjusted_open']=='1.2300' and row['vendor_adjusted_high']=='2e0'
    assert row['source_fields_exact_tokens']['vw']=='1.234567890123456789'
    assert not any(k.startswith('raw_') for k in row)
    assert row['adjustment']=='all' and 'NOT_RAW_SHARES' in row['volume_basis']
    assert row['observed_historical_available_at'] is None and row['estimated_K'] is None
    assert len(row['parent_relation']['source_records'])==2
    assert row['economic_security_id'] is None and row['investor_total_return']=='NOT_ESTABLISHED'
    parents=[json.loads(line) for line in (root/'parts/00000/parent-coverage-ledger.ndjson').read_text().splitlines()]
    assert sum(len(x['source_records']) for x in parents)==3
    before=s.store.raw('budget.json');run(s,p,[])
    assert s.store.raw('budget.json')==before and s.status(p)['scope_physical_gets']==2
    assert all(x[0]['schema']=='polar.adjusted-sip-request-start/1' for x in records(s))

@pytest.mark.parametrize('replies,reason',[
 ([{'body':'{"bars":{},"bars":{}}'}],'IMPORT_DUPLICATE_FIELD'),
 ([{'body':body(77)}],'UNEXPECTED_RETURNED_SYMBOL'),
 ([{'body':body(cursor='x')},{'body':body(cursor='x')}],'REPEATED_CURSOR'),
 ([{'status':401}],'AUTH_OR_RIGHTS_REFUSAL'),
 ([{'status':302}],'HTTP_FAILURE_NO_RETRY')])
def test_existing_failure_and_no_retry_semantics(tmp_path,replies,reason):
    s,p,_=setup(tmp_path,1);run(s,p,replies)
    assert next(iter(s.status(p)['states'].values()))['reason']==reason
    before=s.status(p)['scope_physical_gets'];run(s,p,[])
    assert s.status(p)['scope_physical_gets']==before

def test_unknown_inflight_not_reissued_and_raw_seed_rejected(tmp_path):
    s,p,cfg=setup(tmp_path,1);j=s.load(p)['jobs'][0]
    start={'schema':'polar.adjusted-sip-request-start/1','request_id':str(uuid.uuid4()),
      'attempt_id':str(uuid.uuid4()),'sequence':0,'job_id':j['job_id'],'request':j['request'],
      'page':0,'request_cursor':None,'started_at':timestamp(START),'timeout_seconds':45}
    with s.store.locked():s.store.write('requests/'+start['request_id']+'.json',start)
    run(s,p,[]);assert s.status(p)['scope_physical_gets']==1
    assert s.status(p)['states'][j['job_id']]['reason']=='UNKNOWN_IN_FLIGHT'
    seed={'schema':'polar.raw-sip-seed/1','request':{**j['request'],'adjustment':'raw'},
          'pages':[{}],'completeness':'COMPLETE','provenance':{'invented':True}}
    path=tmp_path/'seed.json';path.write_bytes(canonical(seed))
    with pytest.raises(ImportError):s.plan({**cfg,'seed_refs':[{'path':str(path),'sha256':sha(path.read_bytes())}]})

def test_count_bound_and_deadline_survive_resume(tmp_path):
    s,p,_=setup(tmp_path,100)
    replies=[]
    for i in range(100):replies += [{'duration_seconds':45,'body':body(i,cursor='next')},{'duration_seconds':45,'body':body(i)}]
    first=run(s,p,replies);assert first['reason']=='OPERATION_DEADLINE'
    before=s.store.raw('budget.json');count=s.status(p)['scope_physical_gets'];run(s,p,[])
    assert s.store.raw('budget.json')==before and s.status(p)['scope_physical_gets']==count
    with pytest.raises(ImportError):setup(tmp_path/'oversized',101)
