"""Invented B11 metadata/admission/supervision and bounded streaming controls.

Actual native tests below are separately labeled. Structural48 fixtures never
claim48 native accounts or a financial/admission grant.
"""
from pathlib import Path
from dataclasses import asdict,replace
from copy import deepcopy
from fractions import Fraction as F
import json,os,sys,subprocess,threading
import pytest
from polar.gym_contract import canonical,decode,sha,MAX_BYTES
from polar.gym_service import code_binding
from polar.signed_event_saved import encode,restore
from polar.signed_pair_saved import binding_for,candidate_receipt,publish_account,verify_stored_account
from polar.signed_pair_operation import PairOperationService,binding,family,registry,CONFIG
from polar.ci_research_service import root_identity
from test_signed_pair_producer import fixture as pair_fixture

OWNER=Path('/owner-definitions')


def put(path,value):
    path=Path(path);raw=value if type(value) is bytes else canonical(value);path.write_bytes(raw)
    return {'path':str(path),'sha256':sha(raw),'bytes':len(raw)}


def fixture(tmp_path,*,data=None):
    tmp_path.mkdir(exist_ok=True);data=pair_fixture() if data is None else data;b=binding_for(data)
    # First-party protocol and appendices are source definitions, not retained
    # payloads. Tests use copied committed test literals for metadata otherwise.
    owner=Path(__file__).resolve().parents[1]/'src/polar'
    from polar.signed_pair_operation import APPENDICES,MERGED
    definitions=json.loads((Path(__file__).parent/'fixtures'/'b11-definition-refs.json').read_text())
    def definition_ref(r):return {'path':str(Path(__file__).parent/'fixtures'/'b11-definitions'/r['name']),'sha256':r['sha256'],'bytes':r['bytes']}
    definitions={'protocol':definition_ref(definitions['protocol']),'appendices':[definition_ref(r) for r in definitions['appendices']]}
    encoded=put(tmp_path/'input-encoded.json',canonical(encode(asdict(data))))
    bp=put(tmp_path/'input-binding.json',canonical(encode(b)))
    manifest={'schema':'polar.private-materialized-pair-source-manifest/1','input_id':data.input_id,
        'input_content_sha256':b['input_content_sha256'],'encoded_input':encoded,'accepted_binding':bp,
        'execution_authority':False,'historical_access':'UNQUALIFIED'}
    ip=put(tmp_path/'input-manifest.json',manifest)
    candidate='INVENTED_B11';experiment=candidate+'-EXPERIMENT'
    selection={'schema':'polar.prospective-private-study-selection/1','candidate_id':candidate,
        'experiment_registration_id':experiment,'protocol':definitions['protocol'],'controlling_appendices':definitions['appendices'],
        'source':{'input_content_sha256':b['input_content_sha256'],'binding_sha256':bp['sha256'],'manifest_sha256':ip['sha256']},
        'candidate_accounting':{'controls':4,'cases':12,'native_accounts_per_complete_original':48,'fits':0,'models':0,
            'optimizers':0,'bootstrap':0,'planned_original_invocations':1,'planned_success_only_saved_verifications':1},
        'scope':'INVENTED_TEST_NOT_FINANCIAL_AUTHORITY'}
    sp=put(tmp_path/'selection.json',selection)
    card={'schema':'polar.native-hypothesis-reservation/1','state':'RESERVED','candidate_id':candidate,
        'experiment_registration_id':experiment,'selection':sp,'protocol':definitions['protocol'],'scope':'INVENTED_TEST'}
    cp=put(tmp_path/'custody.json',card)
    method=put(tmp_path/'method.json',{'schema':'polar.prospective-method-disposition/1','method_verdict':'PASS',
        'candidate_id':candidate,'protocol':definitions['protocol'],'scope':'INVENTED_NOT_ACTUAL_METHOD_REVIEW'})
    qa=put(tmp_path/'qa.json',{'schema':'polar.ci-result/1','status':'PASS','candidate_sha':'a'*40,
        'selection':['tests/test_signed_pair_operation.py'],'scope':'INVENTED_NOT_ACTUAL_QA'})
    root=tmp_path/'artifacts';root.mkdir();service=PairOperationService(root,1024**3)
    limits={'original':{'wall_seconds':180,'cpu_seconds':180},'saved':{'wall_seconds':120,'cpu_seconds':120},
        'collector':{'wall_seconds':30,'cpu_seconds':30},'cleanup_seconds':3,'remaining_family_wall_seconds':600,
        'remaining_family_cpu_seconds':600,'rss_bytes':2*1024**3,'log_bytes':1024**2,'journal_bytes':2*1024**2,
        'counter_bytes':16*1024**2,'partial_bytes':128*1024**2,'checkpoint_interval_events':128,
        'operation_store_bytes':512*1024**2,'object_bytes':MAX_BYTES,'chunk_bytes':MAX_BYTES//4}
    resources={'schema':'polar.private-pair-resource-admission/1','status':'SUFFICIENT_CERTIFIED','limits':limits,
        'artifact_root_identity':root_identity(root),'actor_uid':os.getuid(),'actor_gid':os.getgid(),
        'runtime_image_id':'sha256:'+'b'*64,'global_storage_headroom_bytes':2*1024**3,
        'scope':'INVENTED_TECHNICAL_ENVELOPE_NOT_REAL_GLOBAL_HEADROOM_OR_B11_ALLOWANCE'}
    rp=put(tmp_path/'resources.json',resources)
    cfg={'schema':CONFIG,'namespace':'INVENTED','stage':'ORIGINAL','candidate_id':candidate,'experiment_id':experiment,
        'selection_ref':sp,'custody_ref':cp,'source_manifest_ref':ip,'method_ref':method,'qualification_ref':qa,
        'resources_ref':rp,'authority_ref':None,'code':code_binding(),'code_revision':'a'*40,
        'runtime_image_id':resources['runtime_image_id'],'artifact_root_identity':root_identity(root),
        'expected_registry':[],'semantic_id':None}
    grant={'schema':'polar.private-pair-operation-authority/1','stage':'ORIGINAL','binding_sha256':sha(canonical(binding(cfg))),
        'resources_sha256':rp['sha256'],'family':family(cfg),'expected_registry':[],'actor_uid':os.getuid(),'actor_gid':os.getgid(),
        'scientific_calls':1,'native_accounts':48,'saved_calls':0,'fit_calls':0,'model_calls':0,
        'feature_calls_max':48*len(data.formations),'decision_calls_max':48*len(data.formations),'scope':'INVENTED_TEST_ONLY'}
    cfg['authority_ref']=put(tmp_path/'authority.json',grant)
    return service,cfg,data


def test_preflight_does_not_open_encoded_input_or_start(tmp_path,monkeypatch):
    import polar.signed_pair_operation as module
    service,cfg,data=fixture(tmp_path);manifest=decode(Path(cfg['source_manifest_ref']['path']).read_bytes())
    old=module.read_ref
    def metadata_only(ref):
        assert ref!=manifest['encoded_input'],'PRIVATE_VALUES_FORBIDDEN'
        return old(ref)
    monkeypatch.setattr(module,'read_ref',metadata_only)
    assert service.preflight(cfg)['source_values_read']==0
    assert registry(service.store,cfg)==[]
    assert not (service.store.root/'scheduled-reference-attempts').exists()


@pytest.mark.parametrize('field',['root','code','prior','custody','source','method','qa','quota','unknown_headroom','unbound','boolean','wall','authority'])
def test_invalid_current_admission_never_debits_or_loads(tmp_path,monkeypatch,field):
    import polar.signed_pair_operation as module
    service,cfg,_=fixture(tmp_path)
    if field=='root':cfg['artifact_root_identity']['inode']='wrong'
    elif field=='code':cfg['code']={}
    elif field=='prior':cfg['expected_registry']=[{'fabricated':True}]
    elif field in ('custody','source','method','qa'):
        key={'custody':'custody_ref','source':'source_manifest_ref','method':'method_ref','qa':'qualification_ref'}[field]
        cfg[key]['sha256']='0'*64
    elif field=='authority':cfg['authority_ref']['sha256']='0'*64
    else:
        r=decode(Path(cfg['resources_ref']['path']).read_bytes())
        if field=='quota':r['limits']['operation_store_bytes']=service.store.limit*2
        elif field=='unknown_headroom':r['status']='NOT_CERTIFIABLE'
        elif field=='unbound':r['limits']['original']['wall_seconds']=None
        elif field=='boolean':r['limits']['saved']['cpu_seconds']=True
        elif field=='wall':r['limits']['remaining_family_wall_seconds']=1
        cfg['resources_ref']=put(Path(cfg['resources_ref']['path']),r)
    with pytest.raises(Exception):service.preflight(cfg)
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_atomic_concurrent_duplicate_start_no_second_debit(tmp_path,monkeypatch):
    import polar.signed_pair_operation as module
    service,cfg,_=fixture(tmp_path);entered=threading.Event();release=threading.Event();results=[]
    def supervisor(*a,**kw):
        entered.set();release.wait(10)
        return {'failure':'INVENTED_NO_CHILD_INJECTED','exit_code':1,'cleanup':'COMPLETE'}
    monkeypatch.setattr(module,'supervise',supervisor)
    t=threading.Thread(target=lambda:results.append(service.run(cfg)));t.start();assert entered.wait(10)
    with pytest.raises(Exception):service.run(cfg)
    release.set();t.join(10);assert not t.is_alive()
    assert len(registry(service.store,cfg))==1 and results[0]['status']=='FAILED_UNFINALIZED'
    assert len(list((service.store.root/'scheduled-reference-attempts').glob('*/*/start/record.json')))==1


def test_structural48_stream_evicts_before_next_account_without_native(monkeypatch):
    import polar.signed_pair_stream as stream
    from polar.signed_pair_input import CONTROLS,CASES
    live={'now':0,'peak':0,'produced':0,'emitted':0}
    class Lifetime:
        def __init__(self):live['now']+=1;live['peak']=max(live['peak'],live['now'])
        def __del__(self):live['now']-=1
    def produce(data,control,case,**kwargs):
        assert live['now']==0,'PRIOR_FULL_ACCOUNT_STILL_LIVE'
        live['produced']+=1
        return {'control':control,'case':case,'activation':{'status':'INVENTED_STRUCTURAL_NOT_NATIVE'},'token':Lifetime()}
    def emit(account,proof):
        live['emitted']+=1
        return {'control':account['control'],'case':account['case'],'id':str(live['emitted'])},{'reference_only':True}
    monkeypatch.setattr(stream,'produce_account',produce)
    refs,activations=stream.stream_members(None,emit,lambda *a:None)
    assert len(refs)==live['produced']==live['emitted']==48 and len(activations)==12
    assert live['peak']==1 and live['now']==0


def test_stream_criteria_use_same_exact_evaluator_and_candidate_reference(tmp_path):
    from polar.signed_pair_producer import produce_account
    from polar.signed_pair_metrics import metrics,evaluate,evaluate_reports
    data=pair_fixture();service,_,_=fixture(tmp_path);b=binding_for(data)
    candidate=produce_account(data,'DYNAMIC_SPREAD','RECALL_BLACKOUT2')
    ref=publish_account(service.store,candidate,b);proof=candidate_receipt(candidate,b,ref)
    candidate_activation=deepcopy(candidate['activation']);del candidate
    control=produce_account(data,'RF0_CASH','RECALL_BLACKOUT2',activation=candidate_activation)
    ref2=publish_account(service.store,control,b,_candidate_receipt=proof)
    assert verify_stored_account(service.store.root,ref2,b,_candidate_receipt=proof)==control
    report=metrics(control);legacy=evaluate([control])
    assert legacy==evaluate_reports({'RF0_CASH/RECALL_BLACKOUT2':report},{})
    wrong=replace(proof,ref={**proof.ref,'id':'wrong'})
    with pytest.raises(Exception,match='CANDIDATE_REFERENCE'):verify_stored_account(service.store.root,ref2,b,_candidate_receipt=wrong)


def fullshape_input():
    from datetime import datetime,timezone,timedelta
    from polar.signed_pair_input import Quote
    from polar.signed_event_driver import Action
    data=pair_fixture(nav_count=967,formations=47)
    actions=tuple(Action('INVENTED_DIV_'+str(i),'AAPL','CASH_DISTRIBUTION',F(1,100),
        data.quotes[252+100+i*40].date,data.quotes[252+102+i*40].date,'USD','INVENTED/'+str(i)) for i in range(15))
    first=datetime.fromtimestamp(data.quotes[0].close_ns//10**9,timezone.utc)
    extra=1551;rows=[]
    for name in ('AAPL','AMZN'):
        for i in range(extra,0,-1):
            d=first-timedelta(days=i);t=int(d.timestamp())*10**9
            rows.append(Quote(name,d.date().isoformat(),t,t+3*3600*10**9,'10','10' if name=='AAPL' else '9',
                '/INVENTED/raw/'+str(i),'/INVENTED/signal/'+str(i),'INVENTED_RAW','INVENTED_SIGNAL',f'INVENTED_EXTRA/{name}/{i}'))
        rows.extend(q for q in data.quotes if q.name==name)
    return replace(data,quotes=tuple(rows),formations=tuple(replace(f,g_index=f.g_index+extra,
        endpoint21_index=f.endpoint21_index+extra,endpoint252_index=f.endpoint252_index+extra) for f in data.formations),
        actions=actions,nominal_action_tokens=tuple((a.id,'0.01') for a in actions))


def test_actual_fullshape_supervised_stream_partial_and_source_absent_read(tmp_path,monkeypatch,record_property):
    import polar.signed_pair_operation as module
    from polar.process_budget import supervise as actual_supervise
    data=fullshape_input();assert len(data.quotes)==5540
    service,cfg,_=fixture(tmp_path,data=data)
    # Explicit deterministic failure before SECOND native, not a retry or a
    # production test switch. The first actual967/47/15 account is supervised.
    injected=r'''
import sys
import polar.signed_pair_stream as stream
original=stream.produce_account
calls=0
def one_then_fail(*a,**kw):
 global calls
 calls+=1
 if calls==2:raise RuntimeError('INVENTED_STOP_BEFORE_SECOND_NATIVE')
 return original(*a,**kw)
stream.produce_account=one_then_fail
from polar.signed_pair_operation_worker import main
main()
'''
    def wrapped(argv,**kwargs):
        if argv[-2]=='work':argv=[sys.executable,'-c',injected,*argv[-4:]]
        return actual_supervise(argv,**kwargs)
    monkeypatch.setattr(module,'supervise',wrapped)
    finish=service.run(cfg)
    assert finish['status']=='FAILED_UNFINALIZED',finish
    assert finish['durable_counters']['native_call_entries']==finish['durable_counters']['native_completed']==1,finish
    assert finish['durable_counters']['account_completed']==finish['durable_counters']['account_persisted']==1
    assert len(finish['completed_member_refs'])==1
    ref=finish['completed_member_refs'][0]['account'];b=binding_for(data)
    assert len(verify_stored_account(service.store.root,ref,b)['NAV'])==967
    assert finish['process']['cleanup']==finish['collector']['cleanup']=='COMPLETE'
    assert finish['process']['failure'] is None and finish['process']['sampled_group_rss_peak_bytes']>0
    private_input=decode(Path(cfg['source_manifest_ref']['path']).read_bytes())['encoded_input']
    Path(private_input['path']).unlink()
    before={str(p):(sha(p.read_bytes()),p.stat().st_mtime_ns) for p in service.store.root.rglob('*') if p.is_file()}
    code=r'''
import sys,json,os,importlib.abc,builtins,io
class NoNative(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith('nautilus_trader'):raise RuntimeError('NATIVE_IMPORT_FORBIDDEN')
sys.meta_path.insert(0,NoNative())
from polar.signed_pair_saved import verify_stored_account
from polar.signed_event_saved import restore
old=os.open
def ro(p,flags,*a,**kw):
 if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
 return old(p,flags,*a,**kw)
os.open=ro
def guard(fn):
 def wrapped(p,mode='r',*a,**kw):
  if any(c in mode for c in 'wa+x'):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
  return fn(p,mode,*a,**kw)
 return wrapped
builtins.open=guard(builtins.open);io.open=guard(io.open)
a=verify_stored_account(sys.argv[1],json.loads(sys.argv[2]),restore(json.loads(sys.argv[3])))
print(json.dumps({'NAV':len(a['NAV']),'source_calls':0,'native_calls':0,'writes':0}))
'''
    proof=subprocess.run([sys.executable,'-c',code,str(service.store.root),json.dumps(ref),json.dumps(encode(b))],
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=60)
    assert proof.returncode==0,proof.stderr
    assert before=={str(p):(sha(p.read_bytes()),p.stat().st_mtime_ns) for p in service.store.root.rglob('*') if p.is_file()}
    record_property('invented_supervised_stream_capacity',json.dumps({'full_source_rows':5540,'NAV':967,'formations':47,'actions':15,
        'actual_new_native':1,'completed_before_injected_stop':1,'process':finish['process'],'collector':finish['collector'],
        'counter_scope':finish['counter_scope'],'store_bytes':service.store.used(),'partial_bytes':finish['partial_bytes'],
        'source_absent_read':json.loads(proof.stdout),'full48native':'NOT_RUN'},sort_keys=True))


def rebind(tmp_path,cfg):
    grant=decode(Path(cfg['authority_ref']['path']).read_bytes())
    grant.update(binding_sha256=sha(canonical(binding(cfg))),resources_sha256=cfg['resources_ref']['sha256'])
    cfg['authority_ref']=put(Path(cfg['authority_ref']['path']),grant)


@pytest.mark.parametrize('fault',['timeout','oom_surrogate','serialization'])
def test_supervised_injected_entry_prefix_survives_no_native_retry(tmp_path,monkeypatch,fault):
    import polar.signed_pair_operation as module
    from polar.process_budget import supervise as actual_supervise
    service,cfg,_=fixture(tmp_path);r=decode(Path(cfg['resources_ref']['path']).read_bytes())
    r['limits']['original']['wall_seconds']=1 if fault=='timeout' else 10
    if fault=='oom_surrogate':r['limits']['rss_bytes']=64*1024**2
    cfg['resources_ref']=put(Path(cfg['resources_ref']['path']),r);rebind(tmp_path,cfg)
    script=r'''
import sys,time
from pathlib import Path
from polar.signed_pair_operation_worker import context,Collector
root,path,mode,limit=sys.argv[1:]
store,config,start,limits=context(Path(root),path,int(limit));obs=Collector(store,path,limits)
obs('SCIENTIFIC_ENTRY',{});obs('ACCOUNT_ENTRY',{'control':'DYNAMIC_SPREAD','case':'BASE'})
obs('NATIVE_CALL_ENTRY',{'details':{'scope':'INJECTED_METADATA_NOT_NATIVE_EXECUTION'}})
obs('NATIVE_ACCOUNT_OBSERVED',{'details':{'native_account_id':'INJECTED-NO-REAL-NATIVE'},
 'snapshot':lambda:{'native':{'records':[],'bridge_events':[],'scope':'INVENTED_PREFIX'},'NAV':[],'D_receipts':[]}})
FAULT
'''
    script=script.replace('FAULT',"time.sleep(20)" if fault=='timeout' else "x=bytearray(256*1024**2);time.sleep(20)" if fault=='oom_surrogate' else "obs('NATIVE_PARTIAL',{'snapshot':lambda:{'native':{'records':[object()]}}})")
    def wrapped(argv,**kwargs):
        if argv[-2]=='work':argv=[sys.executable,'-c',script,*argv[-4:]]
        return actual_supervise(argv,**kwargs)
    monkeypatch.setattr(module,'supervise',wrapped)
    finish=service.run(cfg);assert finish['status']=='FAILED_UNFINALIZED',finish
    assert finish['durable_counters']['native_call_entries']==1 and finish['durable_counters']['native_completed']==0
    assert finish['latest_prefix'] is not None and finish['actual_counter_records']==4
    assert finish['process']['cleanup']=='COMPLETE' and finish['collector']['cleanup']=='COMPLETE'
    if fault!='serialization':assert finish['process']['failure']==('WALL_LIMIT' if fault=='timeout' else 'RSS_LIMIT')
    with pytest.raises(Exception):service.run(cfg)
    assert len(registry(service.store,cfg))==1


def test_structural48_saved_reader_lifetime_complete_census_and_tamper(tmp_path,monkeypatch):
    import polar.signed_pair_stream as stream
    from polar.signed_pair_saved import VerifiedCandidate
    from polar.signed_pair_input import CONTROLS,CASES
    from polar.signed_pair_metrics import evaluate_reports
    service,cfg,data=fixture(tmp_path);b=binding_for(data)
    report={'terminal_cents':10000001,'mean':{'status':'OK','value':F(1,100)},
        'variance':{'status':'OK','value':F(1,100)},'drawdown':{'maximum':F(1,100)},
        'ES':{'status':'OK','value':F(1,100)},'survival':True}
    mref=stream.put_object(service.store,'pair-stream-reports','pair-metrics-',report)
    members=[{'control':c,'case':p,'account':{'id':c+'/'+p},'metrics':mref,'criteria':report} for p in CASES for c in CONTROLS]
    activations={p:{'status':'NOT_ACTIVATED','scope':'INVENTED_STRUCTURAL_NO_NATIVE'} for p in CASES}
    ref=stream.publish_graph(service.store,members,activations,b)
    live={'now':0,'peak':0,'read':0}
    class Lifetime:
        def __init__(self):live['now']+=1;live['peak']=max(live['peak'],live['now'])
        def __del__(self):live['now']-=1
    def read(root,ref,binding,*,_candidate_receipt=None):
        assert live['now']==0
        c,p=ref['id'].split('/');live['read']+=1
        if c!='DYNAMIC_SPREAD' and p not in CASES[:2]:
            assert _candidate_receipt.ref=={'id':'DYNAMIC_SPREAD/'+p}
        return {'control':c,'case':p,'activation':activations[p],'lifetime':Lifetime()}
    def proof(a,binding,ref):return VerifiedCandidate(a['case'],sha(canonical(encode(binding))),deepcopy(a['activation']),deepcopy(ref))
    monkeypatch.setattr(stream,'verify_stored_account',read);monkeypatch.setattr(stream,'candidate_receipt',proof)
    monkeypatch.setattr(stream,'metrics',lambda a:deepcopy(report))
    r=stream.verify_stream(service.store.root,ref,b)
    assert r['verified_members']==48 and r['native_calls']==r['source_reads']==r['writes']==0
    assert live['peak']==1 and live['now']==0 and live['read']==48
    graph=stream.read_object(service.store.root,ref)
    for mutation in ('missing','duplicate','order','metrics','activation','hash'):
        bad=deepcopy(graph)
        if mutation=='missing':bad['members'].pop()
        elif mutation=='duplicate':bad['members'][-1]=deepcopy(bad['members'][0])
        elif mutation=='order':bad['members'][0],bad['members'][1]=bad['members'][1],bad['members'][0]
        elif mutation=='metrics':bad['members'][0]['criteria']['terminal_cents']=1
        elif mutation=='activation':bad['activations'][CASES[0]]={'status':'ACTIVATED'}
        if mutation=='hash':badref={**ref,'sha256':'0'*64}
        else:badref=stream.put_object(service.store,'pair-study-components','pair-stream-study-',bad)
        with pytest.raises(Exception):stream.verify_stream(service.store.root,badref,b)
        # Failed reads can retain traceback locals until the exception leaves scope;
        # the next run starts only after the full fixture exception is released.
        import gc;gc.collect();assert live['now']==0


def test_current_prefix_reuses_immutable_chunks_and_preserves_old_snapshot(tmp_path):
    from polar.signed_pair_stream import save_prefix,verify_prefix
    from polar.gym_store import GymStore
    store=GymStore(tmp_path,64*1024**2)
    value={'native':{'records':[{'n':i,'payload':'X'*40000} for i in range(250)],'bridge_events':[]},'NAV':[],'D_receipts':[]}
    one=save_prefix(store,'checkpoints',value,max_bytes=32*1024**2,max_logical_bytes=32*1024**2)
    before=store.used();value['native']['records'].append({'n':250,'payload':'Y'*40000})
    two=save_prefix(store,'checkpoints',value,max_bytes=32*1024**2,max_logical_bytes=32*1024**2)
    assert store.used()-before==two['new_bytes']<two['aggregate_bytes']
    assert len(verify_prefix(tmp_path,one)['native']['records'])==250
    assert len(verify_prefix(tmp_path,two)['native']['records'])==251
    bad={**two,'sha256':'0'*64}
    with pytest.raises(Exception):verify_prefix(tmp_path,bad)
