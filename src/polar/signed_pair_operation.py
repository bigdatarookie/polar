"""Closed B11 admission and finite streaming private operation on existing store.

Metadata preflight never opens encoded input. No operative default or new trial
registry: one immutable scheduled-reference START plus explicit saved START.
"""
from pathlib import Path
import os,sys,time,uuid,json,re,platform,resource
from .gym_contract import canonical,decode,sha,read_ref,MAX_BYTES
from .gym_service import code_binding
from .gym_store import GymStore
from .ci_research_service import root_identity
from .signed_native_bridge import require
from .signed_pair_input import MERGED,CONTROLS,CASES
from .signed_event_saved import encode,restore
from .signed_pair_wire import wire_plain
from .history_bundle import read_file
from .process_budget import supervise

CONFIG='polar.private-pair-operation-config/1'
SEMANTIC='pair-stream-operation-'
CANDIDATE='V043-B11-AAPL-AMZN-RELATIVE-MOM-LS-V1'
SELECTION='f747da3f6cfacd05031815cf267ad00d50d5460654b512ae2233a8b42275c7f0'
CUSTODY='e6b25622cfe08fad21ed341fdcc666d1761adc7939d8695c9d8522707960fcc5'
SOURCE='6114ec5f6665b517e0cc6b4ef7897c3ea807943a38312832254b3cb331256e97'
APPENDICES=('dabff077714bd02055520ec31f7e0d9d988eb785963f8c6eed5b0fe2ffc29013',
 'a2e201a54a2d47ccda16e87cba5543359c3104f0d72573593bb538606b6de11d',
 '024c1f5054b7d3f97d0796105bc137d4e3150598cab58b9ce4b376cd1af829c3',
 '0d80f3fd478b6b03d6172a73967c3ce41974e03fb63f0e08fefa39a76429a070',
 '5f5061b00f63fd962517f3278f03e64d9b9f75523389a53fcb4bc3d8f7a7c009')


def binding(config):return {k:v for k,v in config.items() if k!='authority_ref'}
def positive(v):return type(v) is int and v>0

def family(config):
    # Stable scientific identity, not an input/outcome-dependent retry namespace.
    return sha(canonical({'candidate_id':config['candidate_id'],'experiment_id':config['experiment_id'],
        'protocol':MERGED,'namespace':config['namespace']}))


def registry(store,config):
    found=[];base=store.root/'scheduled-reference-attempts'
    if not base.exists():return found
    require(not base.is_symlink(),'PAIR_OPERATION_REGISTRY_SYMLINK')
    for path in sorted(base.glob('*/*/start/record.json')):
        require(not path.is_symlink(),'PAIR_OPERATION_REGISTRY_SYMLINK')
        start=decode(read_file(store.root,str(path.relative_to(store.root)),MAX_BYTES));b=start.get('binding',{})
        if b.get('candidate_id')==config['candidate_id'] or b.get('experiment_id')==config['experiment_id']:
            attempt=path.parent.parent
            finish=attempt/'finish/record.json'
            status=json.loads(read_file(store.root,str(finish.relative_to(store.root)),MAX_BYTES))['status'] if finish.exists() else 'UNFINALIZED'
            found.append({'family':attempt.parent.name,'attempt_id':attempt.name,'stage':start.get('stage','ORIGINAL'),
                'status':status,'start_sha256':sha(path.read_bytes())})
    return found


def supervision_phases(stage):
    require(stage in ('ORIGINAL','SAVED'),'PAIR_OPERATION_STAGE')
    return ('original','saved','collector','collector') if stage=='ORIGINAL' else ('saved','collector')


def operation_storage_bound(value,stage):
    # Each work/collector supervisor has a distinct log and journal. ORIGINAL
    # reserves its prospective success-only SAVED pair as well as its own pair.
    return value['operation_store_bytes']+len(supervision_phases(stage))*(value['log_bytes']+value['journal_bytes'])


def limits(value,stage):
    fields={'original','saved','collector','cleanup_seconds','remaining_family_wall_seconds','remaining_family_cpu_seconds',
        'rss_bytes','log_bytes','journal_bytes','counter_bytes','partial_bytes','checkpoint_interval_events',
        'operation_store_bytes','object_bytes','chunk_bytes'}
    require(type(value) is dict and set(value)==fields,'PAIR_OPERATION_RESOURCE_FIELDS')
    for phase in ('original','saved','collector'):
        require(type(value[phase]) is dict and set(value[phase])=={'wall_seconds','cpu_seconds'} and
            all(positive(v) for v in value[phase].values()),'PAIR_OPERATION_STAGE_LIMIT')
    require(all(positive(v) for k,v in value.items() if k not in ('original','saved','collector')),
        'PAIR_OPERATION_FINITE_RESOURCES')
    phases=supervision_phases(stage)
    cleanups=len(phases)
    require(sum(value[p]['wall_seconds'] for p in phases)+cleanups*value['cleanup_seconds']<=value['remaining_family_wall_seconds'] and
        sum(value[p]['cpu_seconds'] for p in phases)<=value['remaining_family_cpu_seconds'],
        'PAIR_OPERATION_CUMULATIVE_ALLOWANCE')
    require(value['object_bytes']<=MAX_BYTES and value['chunk_bytes']==MAX_BYTES//4 and
        value['partial_bytes']<=value['operation_store_bytes'] and value['counter_bytes']<=value['operation_store_bytes'],
        'PAIR_OPERATION_STORAGE_BOUNDS')
    return value


def prepare(service,config,*,check_registry=True):
    fields={'schema','namespace','stage','candidate_id','experiment_id','selection_ref','custody_ref','source_manifest_ref',
        'method_ref','qualification_ref','resources_ref','authority_ref','code','code_revision','runtime_image_id',
        'artifact_root_identity','expected_registry','semantic_id'}
    require(type(config) is dict and set(config)==fields and config['schema']==CONFIG and
        config['namespace'] in ('INVENTED','RETAINED') and config['stage'] in ('ORIGINAL','SAVED'),'PAIR_OPERATION_CONFIG')
    require(type(config['candidate_id']) is str and type(config['experiment_id']) is str and
        config['candidate_id'].startswith('INVENTED')==(config['namespace']=='INVENTED') and
        config['experiment_id'].startswith(config['candidate_id']),'PAIR_OPERATION_IDENTITY')
    require(config['code']==code_binding() and config['artifact_root_identity']==root_identity(service.store.root) and
        re.fullmatch('[a-f0-9]{40}',config['code_revision']) and re.fullmatch('sha256:[a-f0-9]{64}',config['runtime_image_id']),
        'PAIR_OPERATION_CURRENT_CODE_ROOT_RUNTIME')
    # Only metadata refs are read here. encoded_input is deliberately not followed.
    selection=decode(read_ref(config['selection_ref']));custody=decode(read_ref(config['custody_ref']))
    require(selection['schema']=='polar.prospective-private-study-selection/1' and
        selection['candidate_id']==custody['candidate_id']==config['candidate_id'] and
        selection['experiment_registration_id']==custody['experiment_registration_id']==config['experiment_id'] and
        custody['schema']=='polar.native-hypothesis-reservation/1' and custody['state']=='RESERVED' and
        selection['protocol']['sha256']==custody['protocol']['sha256']==MERGED and
        [r['sha256'] for r in selection['controlling_appendices']]==list(APPENDICES) and
        custody['selection']['sha256']==config['selection_ref']['sha256'], 'PAIR_OPERATION_SELECTION_CUSTODY')
    require(all(sha(read_ref(r))==r['sha256'] for r in selection['controlling_appendices']) and
        sha(read_ref(selection['protocol']))==MERGED,'PAIR_OPERATION_CONTROLLING_DEFINITIONS')
    expected=selection['candidate_accounting']
    require(all(expected.get(k)==v and type(expected.get(k)) is int for k,v in
        [('controls',4),('cases',12),('native_accounts_per_complete_original',48),('fits',0),('models',0),('optimizers',0),
         ('bootstrap',0),('planned_original_invocations',1),('planned_success_only_saved_verifications',1)]),
        'PAIR_OPERATION_CLOSED_SHAPE')
    source=None;expected_binding=None;index=None
    if config['stage']=='ORIGINAL':
        require(config['semantic_id'] is None,'PAIR_OPERATION_ORIGINAL_SEMANTIC')
        source=decode(read_ref(config['source_manifest_ref']))
        require(source['schema']=='polar.private-materialized-pair-source-manifest/1' and
            source['input_content_sha256']==selection['source']['input_content_sha256'] and
            source['accepted_binding']['sha256']==selection['source']['binding_sha256'] and
            config['source_manifest_ref']['sha256']==selection['source']['manifest_sha256'] and
            source['execution_authority'] is False and source['historical_access']=='UNQUALIFIED',
            'PAIR_OPERATION_SOURCE_DESCRIPTOR')
        expected_binding=restore(decode(read_ref(source['accepted_binding'])))
        require(expected_binding['input_content_sha256']==source['input_content_sha256'] and
            expected_binding['namespace']==config['namespace'] and expected_binding['input_id']==source['input_id'] and
            expected_binding['protocol_sha256']==MERGED,'PAIR_OPERATION_EXPECTED_INPUT_BINDING')
    else:
        require(config['source_manifest_ref'] is None,'PAIR_OPERATION_SAVED_SOURCE_ABSENT')
        index=read_index(service.store.root,config['semantic_id'])
        require(index['candidate_id']==config['candidate_id'] and index['experiment_id']==config['experiment_id'] and
            index['code']==config['code'] and index['runtime_image_id']==config['runtime_image_id'],
            'PAIR_OPERATION_SAVED_CURRENT_BINDING')
        expected_binding=index['input_binding']
        original=json.loads(read_file(service.store.root,index['attempt_path']+'/finish/record.json',MAX_BYTES))
        require(original['status']=='SUCCESS' and original['semantic_id']==config['semantic_id'] and
            original['graph']==index['graph'],'PAIR_OPERATION_SUCCESS_ONLY_SAVED')
    if config['namespace']=='RETAINED':
        require(config['candidate_id']==CANDIDATE and config['selection_ref']['sha256']==SELECTION and
            config['custody_ref']['sha256']==CUSTODY and (source is None or config['source_manifest_ref']['sha256']==SOURCE),
            'PAIR_OPERATION_FROZEN_B11')
        require(os.getuid()==10001 and platform.system()=='Linux' and platform.python_version()=='3.13.18' and
            os.environ.get('POLAR_RUNTIME_IMAGE_ID')==config['runtime_image_id'],'PAIR_OPERATION_ACTUAL_RUNTIME')
    method=decode(read_ref(config['method_ref']));qa=decode(read_ref(config['qualification_ref']))
    require(method['schema']=='polar.prospective-method-disposition/1' and method['method_verdict']=='PASS' and
        method['candidate_id']==config['candidate_id'] and method['protocol']['sha256']==MERGED,'PAIR_OPERATION_METHOD')
    require(qa['schema']=='polar.ci-result/1' and qa['status']=='PASS' and qa['candidate_sha']==config['code_revision'] and
        any(v in ('tests','tests/test_signed_pair_operation.py') for v in qa['selection']),'PAIR_OPERATION_CURRENT_QUALIFICATION')
    resources=decode(read_ref(config['resources_ref']));bound=limits(resources['limits'],config['stage'])
    require(resources['schema']=='polar.private-pair-resource-admission/1' and resources['status']=='SUFFICIENT_CERTIFIED' and
        resources['artifact_root_identity']==config['artifact_root_identity'] and resources['actor_uid']==os.getuid() and
        resources['actor_gid']==os.getgid() and resources['runtime_image_id']==config['runtime_image_id'] and
        resources['global_storage_headroom_bytes']>=operation_storage_bound(bound,config['stage']) and
        service.store.limit-service.store.used()>=operation_storage_bound(bound,config['stage']),
        'PAIR_OPERATION_CURRENT_RESOURCE_ADMISSION')
    if config['stage']=='SAVED':
        prior_start=restore(decode(read_file(service.store.root,index['attempt_path']+'/start/record.json',MAX_BYTES)))
        old=prior_start['resource_limits']
        require(all(bound[p][k]<=old[p][k] for p in ('saved','collector') for k in ('wall_seconds','cpu_seconds')) and
            bound['remaining_family_wall_seconds']<=old['remaining_family_wall_seconds']-original['containing_parent_wall_seconds'] and
            bound['remaining_family_cpu_seconds']<=old['remaining_family_cpu_seconds']-original['containing_parent_cpu_seconds'],
            'PAIR_OPERATION_SAVED_CUMULATIVE_REMAINING')
        require(not (service.store.root/index['attempt_path']/'saved-verification').exists(),'PAIR_OPERATION_SAVED_ALREADY_CHARGED')
    if config['namespace']=='RETAINED':
        require(Path('/sys/fs/cgroup/memory.max').read_text().strip()==str(resources['actual_cgroup_memory_max_bytes']) and
            Path('/sys/fs/cgroup/cpu.max').read_text().strip()==resources['actual_cgroup_cpu_max'] and
            bound['rss_bytes']<=resources['actual_cgroup_memory_max_bytes'] and
            resources['guard_status']=='ACTIVE_BOUND_EXTERNAL_HOSTING' and
            resources['guard_id']==os.environ.get('POLAR_OPERATION_GUARD_ID'), 'PAIR_OPERATION_ACTUAL_HOSTING_LIMITS')
    actual=registry(service.store,config)
    if check_registry:require(actual==config['expected_registry'],'PAIR_OPERATION_ACTUAL_PRIOR_REGISTRY')
    if config['stage']=='ORIGINAL':require(not actual,'PAIR_OPERATION_ORIGINAL_ALREADY_SPENT')
    else:require(len(actual)==1 and actual[0]['status']=='SUCCESS' and actual[0]['attempt_id']==index['attempt_id'],
        'PAIR_OPERATION_SAVED_ORIGINAL_REGISTRY')
    grant=decode(read_ref(config['authority_ref']))
    require(grant['schema']=='polar.private-pair-operation-authority/1' and grant['stage']==config['stage'] and
        grant['binding_sha256']==sha(canonical(binding(config))) and grant['resources_sha256']==config['resources_ref']['sha256'] and
        grant['family']==family(config) and grant['expected_registry']==config['expected_registry'] and
        grant['actor_uid']==os.getuid() and grant['actor_gid']==os.getgid() and
        all(type(grant.get(k)) is int and grant[k]==v for k,v in [('scientific_calls',1 if config['stage']=='ORIGINAL' else 0),
            ('native_accounts',48 if config['stage']=='ORIGINAL' else 0),('saved_calls',1 if config['stage']=='SAVED' else 0),
            ('fit_calls',0),('model_calls',0),('feature_calls_max',48*len(expected_binding['formations']) if config['stage']=='ORIGINAL' else 0),
            ('decision_calls_max',48*len(expected_binding['formations']) if config['stage']=='ORIGINAL' else 0)]),'PAIR_OPERATION_OPERATIVE_AUTHORITY')
    return selection,source,expected_binding,bound,index


class PairOperationService:
    def __init__(self,root,storage_bytes):self.store=GymStore(root,storage_bytes)
    def preflight(self,config):
        prepare(self,config)
        return {'status':'BOUND_METADATA_VALID_NOT_STARTED','source_values_read':0,'native_calls':0,'scientific_calls':0,
            'binding_sha256':sha(canonical(binding(config))),'financial_assessment':'NOT_ISSUED'}
    def run(self,config):return run(self,config)
    def recompute(self,semantic_id):raise ValueError('PAIR_SAVED_OPERATION_AUTHORITY_REQUIRED_USE_RESEARCH_RUN_SAVED_CONFIG')


def read_index(root,sid):
    require(type(sid) is str and re.fullmatch(SEMANTIC+'[a-f0-9]{64}',sid),'PAIR_OPERATION_SEMANTIC_ID')
    raw=read_file(root,'reference-research-experiments/'+sid+'/manifest.json',MAX_BYTES)
    require(sid==SEMANTIC+sha(raw),'PAIR_OPERATION_SEMANTIC_PIN')
    return restore(decode(raw))


def run(service,config):
    started=time.monotonic();cpu0=resource.getrusage(resource.RUSAGE_SELF);children0=resource.getrusage(resource.RUSAGE_CHILDREN)
    selection,source,input_binding,bound,index=prepare(service,config);aid=str(uuid.uuid4());fam=family(config)
    parent='scheduled-reference-attempts/'+fam
    with service.store.locked():
        prepare(service,config)
        if config['stage']=='SAVED':
            parent=index['attempt_path']+'/saved-verification'
            require(not (service.store.root/parent).exists(),'PAIR_OPERATION_SAVED_ALREADY_CHARGED')
        start={'schema':'polar.private-pair-start/1','stage':config['stage'],'status':'FIRST_START_CONSERVATIVE_DEBIT',
            'attempt_id':aid,'binding':binding(config),'started_ns':time.time_ns(),'input_binding':input_binding,
            'scientific_calls_charged':1 if config['stage']=='ORIGINAL' else 0,'saved_calls_charged':1 if config['stage']=='SAVED' else 0,
            'no_retry_refund':True,'registry_before':registry(service.store,config),'store_used_before':service.store.used(),'resource_limits':bound}
        path=parent+'/'+aid
        service.store._publish(path,'start',{'record.json':canonical(encode(start)),'config.json':canonical(config)},file_limit=MAX_BYTES)
    stage_dir=service.store.root/path/'supervision';stage_dir.mkdir(mode=0o700)
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPYCACHEPREFIX':'/tmp/polar-pair-bytecode-disabled'}
    def supervised(mode,stage):
        remaining_wall=bound['remaining_family_wall_seconds']-(time.monotonic()-started)
        require(remaining_wall>bound['cleanup_seconds'],'PAIR_OPERATION_CUMULATIVE_WALL')
        own_now=resource.getrusage(resource.RUSAGE_SELF);child_now=resource.getrusage(resource.RUSAGE_CHILDREN)
        used_cpu=(own_now.ru_utime+own_now.ru_stime-cpu0.ru_utime-cpu0.ru_stime)+(child_now.ru_utime+child_now.ru_stime-children0.ru_utime-children0.ru_stime)
        remaining_cpu=bound['remaining_family_cpu_seconds']-used_cpu
        require(remaining_cpu>0,'PAIR_OPERATION_CUMULATIVE_CPU')
        receipt=supervise([sys.executable,'-m','polar.signed_pair_operation_worker',str(service.store.root),path,mode,str(service.store.limit)],
            env=env,output=stage_dir/(mode+'.log'),cpu_seconds=min(bound[stage]['cpu_seconds'],remaining_cpu),
            wall_seconds=min(bound[stage]['wall_seconds'],remaining_wall-bound['cleanup_seconds']),
            rss_limit_bytes=bound['rss_bytes'],max_output_bytes=bound['log_bytes'],max_journal_bytes=bound['journal_bytes'],
            cleanup_seconds=bound['cleanup_seconds'])
        with service.store.locked():service.store._publish(path,'process-'+mode,{'record.json':canonical(receipt)})
        return receipt
    result=None;stage_receipt=None;collector_receipt=None
    try:
        stage_receipt=supervised('work',config['stage'].lower() if config['stage']=='SAVED' else 'original')
        collector_receipt=supervised('collect','collector')
        result=wire_plain(read_file(service.store.root,path+'/collected/record.json',MAX_BYTES))
        require(collector_receipt['failure'] is None and collector_receipt['exit_code']==0 and collector_receipt['cleanup']=='COMPLETE',
            'PAIR_OPERATION_COLLECTOR_FAILED')
    except Exception as exc:
        result={'status':'FAILED_UNFINALIZED','error':str(exc)[:240],'frontier':'UNKNOWN_AFTER_LAST_DURABLE_COUNTER_OR_PREFIX',
            'refund':False,'automatic_retry':False}
    own=resource.getrusage(resource.RUSAGE_SELF);child=resource.getrusage(resource.RUSAGE_CHILDREN)
    total_cpu=(own.ru_utime+own.ru_stime-cpu0.ru_utime-cpu0.ru_stime)+(child.ru_utime+child.ru_stime-children0.ru_utime-children0.ru_stime)
    wall=time.monotonic()-started
    if wall>bound['remaining_family_wall_seconds'] or total_cpu>bound['remaining_family_cpu_seconds']:
        result={**result,'status':'FAILED_UNFINALIZED','error':'PAIR_OPERATION_CUMULATIVE_RESOURCE_LIMIT'}
    result.update(attempt_id=aid,stage=config['stage'],process=stage_receipt,collector=collector_receipt,
        containing_parent_wall_seconds=wall,containing_parent_cpu_seconds=total_cpu,
        accounting='CONTAINING_PARENT_NOT_ADDITIVE_WITH_CHILD_STAGE_RECEIPTS',refund=False,automatic_retry=False)
    with service.store.locked():service.store._publish(path,'finish',{'record.json':canonical(result)},file_limit=MAX_BYTES)
    return result
