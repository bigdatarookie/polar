"""Invented metadata/first-start checks; no retained values or pair campaign."""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from polar import offline_author_binding as author
from polar import signed_pair_operation as operation
from polar.gym_contract import canonical,decode,sha
from polar.signed_event_saved import encode
from polar.signed_pair_saved import binding_for
from polar.config import Settings
from polar.service import Service
from test_signed_pair_operation import fixture,put


def automatic(tmp_path,monkeypatch):
    service,cfg,data=fixture(tmp_path)
    cfg['authority_ref']=None
    # Explicitly invented revision/runtime/qualification, not a real admission.
    monkeypatch.setattr(author,'loaded_revision',lambda:'a'*40)
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID',cfg['runtime_image_id'])
    return service,cfg,data


def no_values(monkeypatch,cfg):
    source=decode(Path(cfg['source_manifest_ref']['path']).read_bytes())
    read=operation.read_ref
    def metadata(ref):
        assert ref!=source['encoded_input'],'encoded values opened before FIRST_START'
        return read(ref)
    monkeypatch.setattr(operation,'read_ref',metadata)


def test_automatic_preflight_has_no_grant_values_or_run_debit(tmp_path,monkeypatch):
    service,cfg,_=automatic(tmp_path,monkeypatch);no_values(monkeypatch,cfg)
    ready=service.preflight(cfg)
    intent=ready['execution_binding']
    assert ready['execution_binding_status']=='AUTOMATIC_OFFLINE_BINDING_READY_NOT_REVIEWED'
    assert intent['execution_intent_only'] and intent['scientific_acceptance']=='NOT_REVIEWED'
    assert intent['candidate_sha']==cfg['code_revision'] and intent['config_sha256']==sha(canonical(operation.binding(cfg)))
    assert intent['data_content_sha256']==decode(Path(cfg['source_manifest_ref']['path']).read_bytes())['input_content_sha256']
    assert intent['resources_sha256']==cfg['resources_ref']['sha256'] and intent['run_id'] is None
    assert service.preflight(cfg)==ready
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_automatic_first_start_records_actual_attempt_and_no_retry_refund(tmp_path,monkeypatch):
    service,cfg,_=automatic(tmp_path,monkeypatch);no_values(monkeypatch,cfg)
    def stopped(*args,**kwargs):
        return {'failure':'INVENTED_NO_CHILD_STARTED','exit_code':1,'cleanup':'COMPLETE'}
    monkeypatch.setattr(operation,'supervise',stopped)
    result=service.run(cfg)
    assert result['status']=='FAILED_UNFINALIZED'
    starts=list((service.store.root/'scheduled-reference-attempts').glob('*/*/start/record.json'))
    assert len(starts)==1
    start=decode(starts[0].read_bytes())
    assert start['execution_binding']['run_id']==start['attempt_id']==result['attempt_id']
    assert start['scientific_calls_charged']==1 and start['no_retry_refund'] is True
    with pytest.raises(ValueError,match='ACTUAL_PRIOR_REGISTRY'):service.run(cfg)
    assert len(list((service.store.root/'scheduled-reference-attempts').glob('*/*/start/record.json')))==1


@pytest.mark.parametrize('problem',['runtime','candidate','global','store','unbound'])
def test_automatic_binding_does_not_bypass_runtime_or_full_resource_guards(tmp_path,monkeypatch,problem):
    service,cfg,_=automatic(tmp_path,monkeypatch);no_values(monkeypatch,cfg)
    error='PAIR_OPERATION_CURRENT_RESOURCE_ADMISSION'
    if problem=='runtime':
        monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID','sha256:'+'c'*64);error='RUNTIME_MISMATCH'
    elif problem=='candidate':
        monkeypatch.setattr(author,'loaded_revision',lambda:'c'*40);error='REVISION_MISMATCH'
    else:
        r=decode(Path(cfg['resources_ref']['path']).read_bytes());b=r['limits']
        one=b['operation_store_bytes']+b['log_bytes']+b['journal_bytes']
        if problem=='global':r['global_storage_headroom_bytes']=one
        elif problem=='store':service.store.limit=one
        elif problem=='unbound':r['status']='NOT_CERTIFIABLE'
        cfg['resources_ref']=put(tmp_path/'changed-resource.json',r)
    with pytest.raises(Exception,match=error):service.preflight(cfg)
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_explicit_legacy_authority_never_falls_back_to_automatic(tmp_path,monkeypatch):
    service,cfg,_=fixture(tmp_path)
    monkeypatch.setattr(author,'create_pair',lambda *a,**k:pytest.fail('legacy grant upgraded to automatic'))
    assert 'execution_binding' not in service.preflight(cfg)
    cfg['authority_ref']['sha256']='0'*64
    with pytest.raises(Exception):service.preflight(cfg)
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_closed_pair_seed_uses_existing_service_and_reads_no_source_refs(tmp_path,monkeypatch):
    service,cfg,_=automatic(tmp_path,monkeypatch)
    monkeypatch.setattr(operation,'read_ref',lambda *a:pytest.fail('seed followed a source ref'))
    from polar import candidate_binding
    monkeypatch.setattr(candidate_binding,'loaded_revision',lambda:'a'*40)
    seed={k:v for k,v in cfg.items() if k not in ('code','code_revision','runtime_image_id','artifact_root_identity','authority_ref')}
    seed['schema']='polar.private-pair-operation-seed/1'
    result=Service(Settings('unused',service.store.root)).research_config(seed)
    assert result==cfg and result['authority_ref'] is None
    for field in ('run_id','code','runtime_image_id','command'):
        with pytest.raises(ValueError,match='PAIR_OPERATION_SEED'):
            Service(Settings('unused',service.store.root)).research_config({**seed,field:'forged'})


def test_automatic_saved_requires_original_automatic_lineage_and_separate_debit(tmp_path,monkeypatch):
    service,cfg,data=automatic(tmp_path,monkeypatch)
    fam=operation.family(cfg);aid='11111111-2222-4333-8444-555555555555'
    path='scheduled-reference-attempts/'+fam+'/'+aid
    resources=decode(Path(cfg['resources_ref']['path']).read_bytes())
    intent=author.create_pair(cfg,binding_for(data),run_id=aid)
    start={'schema':'polar.private-pair-start/1','stage':'ORIGINAL','binding':operation.binding(cfg),
        'attempt_id':aid,'input_binding':binding_for(data),'resource_limits':resources['limits'],
        'execution_binding':intent,'store_used_before':0,
        'scope':'INVENTED_METADATA_FIXTURE_NOT_ACTUAL_NATIVE_SUCCESS'}
    index={'schema':'polar.private-pair-stream-operation/1','candidate_id':cfg['candidate_id'],
        'experiment_id':cfg['experiment_id'],'code':cfg['code'],'runtime_image_id':cfg['runtime_image_id'],
        'input_binding':binding_for(data),'attempt_path':path,'attempt_id':aid,
        'graph':{'id':'INVENTED_ABSENT_GRAPH','sha256':'0'*64}}
    raw=canonical(encode(index));sid=operation.SEMANTIC+sha(raw)
    with service.store.locked():
        service.store._publish(path,'start',{'record.json':canonical(encode(start))})
        service.store._publish('reference-research-experiments',sid,{'manifest.json':raw})
        service.store._publish(path,'finish',{'record.json':canonical({'status':'SUCCESS','semantic_id':sid,
            'graph':index['graph'],'containing_parent_wall_seconds':10,'containing_parent_cpu_seconds':10})})
    saved={**deepcopy(cfg),'stage':'SAVED','semantic_id':sid,'source_manifest_ref':None,
           'expected_registry':operation.registry(service.store,cfg)}
    resources['limits']['remaining_family_wall_seconds']=resources['limits']['remaining_family_cpu_seconds']=590
    saved['resources_ref']=put(tmp_path/'saved-resource.json',resources)
    assert service.preflight(saved)['execution_binding']['original_run_id']==aid
    monkeypatch.setattr(operation,'supervise',lambda *a,**k:{'failure':'INVENTED_NO_CHILD','exit_code':1,'cleanup':'COMPLETE'})
    result=service.run(saved)
    assert result['status']=='FAILED_UNFINALIZED'
    records=list((service.store.root/path/'saved-verification').glob('*/start/record.json'))
    assert len(records)==1
    receipt=decode(records[0].read_bytes())
    assert receipt['saved_calls_charged']==1 and receipt['scientific_calls_charged']==0
    assert receipt['execution_binding']['original_run_id']==aid
    assert receipt['execution_binding']['run_id']==result['attempt_id']
    with pytest.raises(ValueError,match='SAVED_ALREADY_CHARGED'):service.run(saved)
    with pytest.raises(Exception,match='SAVED_LINEAGE_REQUIRED'):
        author.create_pair(saved,binding_for(data),prior={**intent,'candidate_sha':'f'*40},original_run_id=aid)
    with pytest.raises(Exception,match='SAVED_LINEAGE_REQUIRED'):
        author.create_pair(saved,binding_for(data),prior=None,original_run_id=aid)


def test_real_cli_seed_and_preflight_are_current_and_value_free(tmp_path):
    import os,subprocess,sys
    from polar.candidate_binding import loaded_revision
    service,cfg,_=fixture(tmp_path)
    runtime=os.environ.get('POLAR_CI_RUNTIME_IMAGE_ID') or 'sha256:'+'b'*64
    resources=decode(Path(cfg['resources_ref']['path']).read_bytes())
    resources['runtime_image_id']=runtime
    cfg['resources_ref']=put(tmp_path/'current-resources.json',resources)
    cfg['qualification_ref']=put(tmp_path/'current-qa.json',{'schema':'polar.ci-result/1','status':'PASS',
        'candidate_sha':loaded_revision(),'selection':['tests/test_signed_pair_operation.py'],
        'scope':'INVENTED_METADATA_NOT_ACTUAL_FINANCIAL_QUALIFICATION'})
    seed={k:v for k,v in cfg.items() if k not in ('code','code_revision','runtime_image_id','artifact_root_identity','authority_ref')}
    seed['schema']='polar.private-pair-operation-seed/1'
    seedpin=put(tmp_path/'seed.json',seed)
    env={**os.environ,'POLAR_ARTIFACT_ROOT':str(service.store.root),'POLAR_RUNTIME_IMAGE_ID':runtime}
    result=subprocess.run([sys.executable,'-m','polar.cli','research-config',seedpin['path']],
                          capture_output=True,text=True,env=env,timeout=30)
    assert result.returncode==0,result.stderr
    current=json.loads(result.stdout)
    assert current['authority_ref'] is None and current['code_revision']==loaded_revision()
    source=decode(Path(current['source_manifest_ref']['path']).read_bytes())
    Path(source['encoded_input']['path']).unlink()
    pin=put(tmp_path/'current-config.json',current)
    ready=subprocess.run([sys.executable,'-m','polar.cli','research-preflight',pin['path']],
                         capture_output=True,text=True,env=env,timeout=30)
    assert ready.returncode==0,ready.stderr
    value=json.loads(ready.stdout)
    assert value['execution_binding_status']=='AUTOMATIC_OFFLINE_BINDING_READY_NOT_REVIEWED'
    assert value['source_values_read']==value['scientific_calls']==0
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_ci_image_fallback_is_invented_only(monkeypatch):
    monkeypatch.delenv('POLAR_RUNTIME_IMAGE_ID',raising=False)
    monkeypatch.setenv('POLAR_CI_RUNTIME_IMAGE_ID','sha256:'+'b'*64)
    assert author.pair_runtime('INVENTED')=='sha256:'+'b'*64
    with pytest.raises(Exception,match='RUNTIME_MISMATCH'):author.pair_runtime('RETAINED')
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID','not-an-image-hash')
    with pytest.raises(Exception,match='RUNTIME_MISMATCH'):author.pair_runtime('INVENTED')


def test_concurrent_automatic_starts_keep_one_immutable_debit(tmp_path,monkeypatch):
    import threading
    service,cfg,_=automatic(tmp_path,monkeypatch)
    entered=threading.Event();release=threading.Event();results=[]
    def stopped(*args,**kwargs):
        entered.set();release.wait(10)
        return {'failure':'INVENTED_NO_CHILD','exit_code':1,'cleanup':'COMPLETE'}
    monkeypatch.setattr(operation,'supervise',stopped)
    thread=threading.Thread(target=lambda:results.append(service.run(cfg)))
    thread.start()
    try:
        assert entered.wait(10)
        with pytest.raises(ValueError,match='ACTUAL_PRIOR_REGISTRY'):service.run(cfg)
    finally:
        release.set();thread.join(10)
    assert not thread.is_alive() and len(results)==1
    assert len(operation.registry(service.store,cfg))==1
    assert len(list((service.store.root/'scheduled-reference-attempts').glob('*/*/start/record.json')))==1
