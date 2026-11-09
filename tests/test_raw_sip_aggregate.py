"""Invented aggregate/partition/index harness; review before first invocation."""
import json
from pathlib import Path

import pytest

from polar.import_contract import canonical,sha,ImportError
from polar.import_service import ImportService
from polar.import_store import ImportStore
from polar.import_raw_sip import ENDPOINT,job_id
from polar.import_raw_profile import AGGREGATE_ADAPTER,AGGREGATE_POLICY
from polar.hyp003_availability import write_availability,read_availability
from polar.hyp003_availability import pointer_state
from polar.hyp003_source import Sources,object_value,PreparationError

START=1767225600


def ref(root,name,value,*,lines=False):
    raw=b''.join(canonical(r)+b'\n' for r in value) if lines else canonical(value)
    path=(root/name).resolve();path.write_bytes(raw)
    return {'path':str(path),'sha256':sha(raw)}


def setup(root,n=3):
    root.mkdir(exist_ok=True)
    jobs=[]
    for i in range(n):
        request={'endpoint':ENDPOINT,'symbols':'INVENTED'+str(i),'adjustment':'raw','feed':'sip',
                 'currency':'USD','timeframe':'1Day','asof':'2020-09-02','limit':10000,'sort':'asc',
                 'start':'2020-01-01T00:00:00Z','end':'2020-01-03T00:00:00Z'}
        jobs.append({'job_id':'source-plan-'+str(i),'population_record_id':'record-'+str(i),'request':request})
    cfg={'schema':'polar.raw-sip-aggregate-config/1','adapter':AGGREGATE_ADAPTER,'mode':'fixture',
         'aggregate_ref':ref(root,'aggregate.json',{'counter_lineage':{'prior_completed_GET':20}}),
         'jobs_ref':ref(root,'jobs.ndjson',jobs,lines=True),'seed_refs':[]}
    service=ImportService(ImportStore(root,64*1024**3,fixture=True,raw_sip=True,raw_profile='remaining3490'))
    return service,cfg,jobs


def execute(service,pid,bodies):
    return service.execute(pid,fixture={'schema':'polar.raw-sip-fixture/1','start_seconds':START,
                                       'responses':[{'body':body} for body in bodies]})


def body(symbol='INVENTED0',n=1,cursor=None):
    return {'bars':{symbol:[{'t':'2020-01-01T04:00:00Z','o':10,'h':12,'l':9,'c':11,'v':0}
                           for _ in range(n)]},'next_page_token':cursor}


def collection(service,result):
    manifest,_=service.terminal(result['attempt_id'],result['manifest_sha256'])
    path=Path(service.store.root/service.store.path(manifest['source_manifest']))
    return path,json.loads(path.read_bytes())


def index_config(root,source,rows=None):
    rows=rows or [{'population_record_id':'record-'+str(i),'literal_symbol':'INVENTED'+str(i)} for i in range(3)]
    return {'schema':'polar.hyp003-availability-config/1','mode':'INVENTED',
            'population_ref':ref(root,'population.ndjson',rows,lines=True),
            'grid_ref':ref(root,'grid.json',{'all':['2020-01-01','2020-01-02']}),
            'inputs':[{'directory':str(source.parent),'manifest':source.name,
                       'manifest_sha256':sha(source.read_bytes()),'links_ref':None}]}


def test_aggregate_extends_scope_without_changing_request_identity(tmp_path):
    service,cfg,jobs=setup(tmp_path,21);pid=service.plan(cfg)['plan_id']
    assert pid.startswith('rawsipaggregatefixture-')
    plan=service.load(pid)
    assert len(plan['jobs'])==21 and plan['policy']['jobs']==3490
    assert plan['policy']['gets']==6980 and plan['policy']['wall_seconds']==10800
    assert plan['jobs'][0]['job_id']==job_id(jobs[0]['request'])
    assert plan['jobs'][0]['relation']['job_id']=='source-plan-0'


def test_provider_cannot_use_invented_scope_or_fixture_namespace(tmp_path):
    service,cfg,_=setup(tmp_path)
    cfg['mode']='provider'
    with pytest.raises(ImportError):service.plan(cfg)
    provider=ImportService(ImportStore(tmp_path,64*1024**3,raw_sip=True,raw_profile='remaining3490'))
    with pytest.raises(ImportError,match='IMPORT_SCOPE_MISMATCH'):provider.plan(cfg)


def test_partitions_preserve_every_row_and_both_job_namespaces(tmp_path,monkeypatch):
    # Invented harness lowers only its fixture partition size to hit the same
    # encoded-byte boundary; it never changes production scope/config files.
    monkeypatch.setitem(AGGREGATE_POLICY,'partition_bytes',4096)
    service,cfg,_=setup(tmp_path);pid=service.plan(cfg)['plan_id']
    result=execute(service,pid,[body(n=12),{'bars':{},'next_page_token':None},body('INVENTED2',2)])
    path,index=collection(service,result);assert index['normalized_rows']==14 and len(index['packets'])>1
    seen=[]
    for packet in index['packets']:
        info=Sources().add({'adapter':'polar.partial-raw-pv-source-content/1','directory':str(path.parent),
            'manifest':packet['manifest'],'manifest_sha256':packet['sha256']},True)
        assert info['inventory']['bars.ndjson']['bytes']<=4096
        seen+=object_value(info,'bars.ndjson')
    assert len(seen)==14 and all(r['raw_volume']=='0' for r in seen)
    ledger=[json.loads(line) for line in (path.parent/'job-status-index.ndjson').read_bytes().splitlines()]
    assert [r['source_plan_job_id'] for r in ledger]==['source-plan-0','source-plan-1','source-plan-2']
    assert [r['transport_state'] for r in ledger]==['RECEIVED_COMPLETE','RECEIVED_EMPTY','RECEIVED_COMPLETE']
    assert all(r['canonical_job_id']!=r['source_plan_job_id'] for r in ledger)
    assert all(r['source_reference']['source_array']=='bars/'+r['source_symbol'] for r in seen)


def test_complete_empty_reuse_never_refetches(tmp_path):
    service,cfg,_=setup(tmp_path);pid=service.plan(cfg)['plan_id']
    first=execute(service,pid,[{'bars':{},'next_page_token':None}]*3)
    budget=service.store.raw('budget.json');assert first['counts']['no_rows']==3
    second=execute(service,pid,[])
    assert second['counts']['success']==3 and service.status(pid)['scope_physical_gets']==3
    assert service.store.raw('budget.json')==budget


@pytest.mark.parametrize('coordinate',['gets','total_bytes'])
def test_aggregate_cumulative_bound_survives_new_attempt(tmp_path,monkeypatch,coordinate):
    monkeypatch.setitem(AGGREGATE_POLICY,coordinate,2 if coordinate=='gets' else 1048577)
    service,cfg,_=setup(tmp_path);pid=service.plan(cfg)['plan_id']
    first=execute(service,pid,[{'bars':{},'next_page_token':None}]*3)
    before=service.status(pid)['scope_physical_gets'];budget=service.store.raw('budget.json')
    assert first['reason']=='OPERATION_REQUEST_OR_BYTE_LIMIT'
    second=execute(service,pid,[])
    assert second['reason']==first['reason'] and service.status(pid)['scope_physical_gets']==before
    assert service.store.raw('budget.json')==budget


def test_original_aggregate_deadline_is_not_per_batch(tmp_path):
    service,cfg,_=setup(tmp_path);pid=service.plan(cfg)['plan_id']
    service.control(pid,'pause');execute(service,pid,[]);budget=service.store.raw('budget.json')
    service.clock.sleep(10800);service.control(pid,'resume')
    later=execute(service,pid,[])
    assert later['reason']=='OPERATION_DEADLINE'
    assert service.store.raw('budget.json')==budget and service.status(pid)['scope_physical_gets']==0


def test_rate_limit_stops_pending_scope_without_retry(tmp_path):
    service,cfg,_=setup(tmp_path);pid=service.plan(cfg)['plan_id']
    fixture={'schema':'polar.raw-sip-fixture/1','start_seconds':START,'responses':[{'status':429}]}
    first=service.execute(pid,fixture=fixture)
    assert first['reason']=='PROVIDER_RATE_LIMIT_PAUSED'
    assert execute(service,pid,[])['reason']=='PROVIDER_RATE_LIMIT_PAUSED'
    assert service.status(pid)['scope_physical_gets']==1


def test_dense_index_preserves_unrequested_empty_and_exact_pointers(tmp_path):
    service,cfg,_=setup(tmp_path/'capture');pid=service.plan(cfg)['plan_id']
    result=execute(service,pid,[body(),{'bars':{},'next_page_token':None},{'bars':{},'next_page_token':None}])
    source,_=collection(service,result)
    config=index_config(tmp_path,source,rows=[
        *[{'population_record_id':'record-'+str(i),'literal_symbol':'INVENTED'+str(i)} for i in range(3)],
        {'population_record_id':'record-unrequested','literal_symbol':'NEVER_REQUESTED'}])
    dest=tmp_path/'availability';written=write_availability(config,dest);report=read_availability(dest)
    assert report['source_record_date_slots']==8 and sum(report['states'].values())==8
    assert report['states']=={'OBSERVED_SOURCE_ROWS':1,'MISSING_WITHIN_COMPLETE_REQUEST':1,
                              'COMPLETE_EMPTY':4,'UNREQUESTED':2}
    cells=[json.loads(r) for r in (dest/'availability/00000.ndjson').read_bytes().splitlines()]
    assert cells[0]['observations'][0]['pointer_status']=='VERIFIED_EXACT_BODY_POSITION'
    obs=json.loads((dest/'rows/00000/00000.ndjson').read_bytes().splitlines()[0])
    assert all(value is None for value in obs['clocks'].values())
    assert written['financial']=='NOT_RUN' and report['economic_universe']=='UNRESOLVED'


def test_collection_member_tamper_is_rejected(tmp_path):
    service,cfg,_=setup(tmp_path/'capture');pid=service.plan(cfg)['plan_id']
    result=execute(service,pid,[body(),body('INVENTED1'),body('INVENTED2')]);source,index=collection(service,result)
    packet=index['packets'][0];target=source.parent/Path(packet['manifest']).parent/'bars.ndjson'
    target.chmod(0o600);target.write_bytes(b'{}\n')
    with pytest.raises(PreparationError):write_availability(index_config(tmp_path,source),tmp_path/'availability')


def test_index_object_tamper_is_rejected(tmp_path):
    cfg={'schema':'polar.hyp003-availability-config/1','mode':'INVENTED',
         'population_ref':ref(tmp_path,'population.ndjson',[{'population_record_id':'r','literal_symbol':'X'}],lines=True),
         'grid_ref':ref(tmp_path,'grid.json',{'all':['2020-01-01']}),'inputs':[]}
    dest=tmp_path/'index';write_availability(cfg,dest);target=dest/'availability/00000.ndjson'
    target.chmod(0o600);target.write_bytes(b'{}\n')
    with pytest.raises(PreparationError,match='HYP003_AVAILABILITY_OBJECT_HASH'):read_availability(dest)


def test_source_record_ids_are_not_deduplicated_by_alias(tmp_path):
    cfg={'schema':'polar.hyp003-availability-config/1','mode':'INVENTED',
         'population_ref':ref(tmp_path,'population.ndjson',[
             {'population_record_id':'r1','literal_symbol':'SAME'},
             {'population_record_id':'r2','literal_symbol':'SAME'}],lines=True),
         'grid_ref':ref(tmp_path,'grid.json',{'all':['2020-01-02','2020-01-01']}),'inputs':[]}
    dest=tmp_path/'index';write_availability(cfg,dest);report=read_availability(dest)
    assert report['records']==2 and report['source_record_date_slots']==4
    rows=[json.loads(r) for r in (dest/'availability/00000.ndjson').read_bytes().splitlines()]
    assert [r['reference_date'] for r in rows]==['2020-01-02','2020-01-01']


@pytest.mark.parametrize('separator',['/','.'])
def test_literal_punctuated_alias_pointer(separator):
    raw=canonical({'bars':{'BRK.B':[{'c':1}]},'next_page_token':None});h=sha(raw)
    info={'inventory':{'body.json':{'sha256':h}},'files':{'body.json':raw},'prefix':Path('.')}
    row={'source_symbol':'BRK.B','raw_fields_exact_tokens':{'c':'1'},
         'source_reference':{'source_array':'bars'+separator+'BRK.B','source_row_ordinal':0,
                             'source_body_sha256':h}}
    assert pointer_state(info,row)=='VERIFIED_EXACT_BODY_POSITION'
    row['source_reference']['source_row_ordinal']=1
    assert pointer_state(info,row)=='INVALID_SOURCE_POINTER'


def test_conflicting_revisions_keep_both_positions(tmp_path):
    captures=[]
    for i in range(2):
        service,cfg,_=setup(tmp_path/('capture'+str(i)));pid=service.plan(cfg)['plan_id']
        first=body();first['bars']['INVENTED0'][0]['c']=11-i
        result=execute(service,pid,[first,body('INVENTED1'),body('INVENTED2')])
        source,_=collection(service,result);captures.append(source)
    cfg=index_config(tmp_path,captures[0]);cfg['inputs'].append({
        'directory':str(captures[1].parent),'manifest':captures[1].name,
        'manifest_sha256':sha(captures[1].read_bytes()),'links_ref':None})
    dest=tmp_path/'index';write_availability(cfg,dest);report=read_availability(dest)
    assert report['states']['CONFLICTING']==1
    row=json.loads((dest/'availability/00000.ndjson').read_bytes().splitlines()[0])
    assert len(row['observations'])==2 and len({r['raw_value_sha256'] for r in row['observations']})==2


def test_empty_evidence_does_not_erase_another_partial_profile(tmp_path):
    captures=[]
    for i in range(2):
        service,cfg,_=setup(tmp_path/('capture'+str(i)),1);pid=service.plan(cfg)['plan_id']
        bodies=[{'bars':{},'next_page_token':None}] if i==0 else [
            {'bars':{},'next_page_token':'p1'},{'bars':{},'next_page_token':'p2'}]
        result=execute(service,pid,bodies);source,_=collection(service,result);captures.append(source)
    cfg=index_config(tmp_path,captures[0],rows=[{'population_record_id':'record-0','literal_symbol':'INVENTED0'}])
    cfg['inputs'].append({'directory':str(captures[1].parent),'manifest':captures[1].name,
        'manifest_sha256':sha(captures[1].read_bytes()),'links_ref':None})
    dest=tmp_path/'index';write_availability(cfg,dest)
    assert read_availability(dest)['states']=={'PARTIAL_OR_UNKNOWN':2}
