"""Closed private calendar study on existing Service, attempt/store and worker.

Preflight is metadata-only; source values are first loaded after FIRST_START.
No default retained authority, common public result or second trial registry.
"""
from dataclasses import dataclass,asdict
from pathlib import Path
from datetime import datetime,timezone
import os,re,time,uuid,platform,sys,io
from zoneinfo import ZoneInfo
from .ci_research import require
from .gym_contract import canonical,decode,sha,read_ref
from .gym_service import code_binding
from .ci_research_service import root_identity,bounded_native
from .event_study import (StudyBinding,binding_from_plain,validate_sidecars,produce_study,plain,
    QUESTION,PROTOCOL,DEFINITION,DEFINITION_PINS)
from .event_study_store import publish_study,verify_stored_study
from .event_native import EventPlan,ReferenceClose,DecisionPoint,EventInstruction,LEGS,COSTS
from .scheduled_event_controller import request_from_event
from .research_reference import load_reference,pinned_bytes,reference_schedule
from .history_bundle import read_file

CONFIG='polar.calendar-study-config/1'
PROFILE='polar.calendar-study-profile/1'
SEMANTIC='calendar-study-experiment-'
REFS=('profile','protocol','input','sidecar','roles','study_binding','locators','timezone')


@dataclass(frozen=True)
class StudyRequest:
    plan:EventPlan
    sidecar:dict
    roles:dict
    binding:StudyBinding


def binding(config):return {k:v for k,v in config.items() if k!='execution_authority_ref'}


def config_from_seed(seed):
    def pin(key):
        p=Path(seed[key+'_path']);require(p.is_absolute(),'CALENDAR_SEED_PATH')
        raw=read_file(p.parent,p.name,32*1024**2);return {'path':str(p),'sha256':sha(raw),'bytes':len(raw)}
    return {'schema':CONFIG,'namespace':seed['namespace'],**{k+'_ref':pin(k) for k in REFS},
        'code':code_binding(),'code_revision':seed['code_revision'],'runtime_image_id':seed['runtime_image_id'],
        'candidate_id':seed['candidate_id'],'experiment_id':seed['experiment_id'],
        'artifact_root_identity':root_identity(Path(os.environ.get('POLAR_ARTIFACT_ROOT','/data/artifacts'))),
        'execution_authority_ref':pin('execution_authority') if seed.get('execution_authority_path') else None}


def prepare(service,config):
    fields={'schema','namespace',*(k+'_ref' for k in REFS),'code','code_revision','runtime_image_id','candidate_id',
        'experiment_id','artifact_root_identity','execution_authority_ref'}
    require(type(config) is dict and set(config)==fields and config['schema']==CONFIG and
        config['namespace'] in ('INVENTED','RETAINED'),'CALENDAR_CONFIG_SCHEMA')
    require(config['artifact_root_identity']==root_identity(service.store.root) and config['code']==code_binding() and
        type(config['code_revision']) is str and re.fullmatch('[a-f0-9]{40}',config['code_revision']) and
        type(config['runtime_image_id']) is str and re.fullmatch('sha256:[a-f0-9]{64}',config['runtime_image_id']),
        'CALENDAR_CURRENT_CODE_ROOT_RUNTIME')
    raw={k:read_ref(config[k+'_ref']) for k in REFS};p=decode(raw['profile'])
    require(type(p) is dict and set(p)=={'schema','protocol_id','question_id','definition','definition_pins',
        'legs','cost_scenarios','capital_cents','file_pins','daily_clock','public_projection'} and
        p['schema']==PROFILE and p['protocol_id']==PROTOCOL and p['question_id']==QUESTION and p['definition']==DEFINITION and
        p['definition_pins']==DEFINITION_PINS and p['legs']==list(LEGS) and
        canonical(p['cost_scenarios'])==canonical(plain(COSTS)) and type(p['capital_cents']) is int and p['capital_cents']==10000000 and
        p['daily_clock']=='FIXED_UTC00_01_NEXT_ELIGIBLE_CLOSE' and p['public_projection']=='PRIVATE_STUDY_ONLY',
        'CALENDAR_CLOSED_PROFILE')
    require(p['file_pins']=={k:sha(raw[k]) for k in REFS if k!='profile'},'CALENDAR_PROFILE_FILE_PINS')
    b=binding_from_plain(decode(raw['study_binding']));side=decode(raw['sidecar']);roles=decode(raw['roles'])
    require(b.namespace==config['namespace'],'CALENDAR_NAMESPACE_BINDING')
    calendars,clusters,rowmap,by_symbol=validate_sidecars(side,roles,b)
    # Existing fixed00:01 profile, not the unqualified coincidentD==NAVQ branch.
    require(all(d['decision_ns']%(86400*10**9)==60*10**9 and d['decision_ns']<d['q_ns'] for d in roles['daily_decisions']),
        'CALENDAR_FIXED_UTC_DAILY_SCOPE')
    ny=ZoneInfo.from_file(io.BytesIO(raw['timezone']),key='America/New_York')
    for e in calendars['conditional'].events:
        if not e.cancelled and e.decision_ns is not None:
            local=datetime.fromtimestamp(e.decision_ns//10**9,timezone.utc).astimezone(ny)
            require((local.hour,local.minute,local.second)==(14,1,0),'CALENDAR_NY14_CUTOFF_PLUS60')
    manifest=decode(raw['input']);require(manifest['schema']=='polar.synthetic-reference-source-input/2' and
        manifest['parent_dataset_revision']==b.input_id and manifest['symbols']==['BIL','VTI'] and
        manifest['quote_basis']=='VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE' and manifest['unit_type']=='SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE' and
        manifest['double_action_policy']=='NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL', 'CALENDAR_SOURCE_ID_BASIS')
    schedule,days=reference_schedule(decode(pinned_bytes(manifest['schedule'])))
    source_dates=tuple(r['date'] for r in by_symbol['VTI']);require(tuple(days)==source_dates,'CALENDAR_SOURCE_DATE_ROLES')
    require(manifest['rows']==len(rowmap),'CALENDAR_SOURCE_ROW_COUNT')
    closes={r['date']:int(datetime.fromisoformat(r['reference_close_utc'].replace('Z','+00:00')).timestamp())*10**9 for r in schedule}
    require(all(closes[r['date']]==r['close_ns'] for r in rowmap.values()),'CALENDAR_ORIGINAL_SCHEDULE_CLOSE_JOIN')
    conversion=manifest.get('conversion_metadata',manifest.get('provenance',{}))
    original_role_pin=conversion.get('date_roles');original_roles=decode(pinned_bytes(original_role_pin))
    require(original_roles['schema']=='polar.reference-source-date-roles/1' and original_roles['source_dates']==days and
        original_roles['symbols']==['BIL','VTI'] and original_roles['NAV']=={'dates':list(b.nav_dates),'symbols':['BIL','VTI']} and
        original_roles['WARMUP_CANDIDATE']=={'dates':[r['date'] for r in by_symbol['VTI'] if r['role']=='VTI_WARMUP_CANDIDATE'],'symbols':['VTI']} and
        original_roles['UNUSED_WARMUP_CONTEXT']=={'dates':[r['date'] for r in by_symbol['BIL'] if r['role']=='BIL_UNUSED_WARMUP_CONTEXT'],'symbols':['BIL']},
        'CALENDAR_ORIGINAL_SOURCE_ROLE_DERIVATIVE')
    loc=decode(raw['locators']);require(type(loc) is dict and set(loc)=={'schema','rows','source_values_read','observed_quote_K','source_id_contract'} and
        loc['schema']=='polar.source-date-role-metadata-locators/1' and loc['source_values_read'] is False and loc['observed_quote_K'] is None and len(loc['rows'])==len(rowmap), 'CALENDAR_SOURCE_LOCATOR_SCHEMA')
    seen=set()
    for v in loc['rows']:
        require(v['source_id'] in rowmap and v['source_id'] not in seen,'CALENDAR_SOURCE_LOCATOR_CENSUS');seen.add(v['source_id']);r=rowmap[v['source_id']]
        require(v['identity_kind']=='CALLER_METADATA_LOCATOR_NOT_PROVIDER_PERMANENT_ID' and v['input_manifest']==config['input_ref'] and
            v['original_role_pin']==original_role_pin and v['symbol']==r['symbol'] and v['original_schedule_row_date']==r['date'] and v['observed_quote_K'] is None and
            v['modeled_quote_K']==r['available_ns'] and r['source_id']==b.input_id+'/'+r['symbol']+'/'+r['date'],
            'CALENDAR_AUTHENTIC_SOURCE_LOCATOR_JOIN')
    if config['namespace']=='INVENTED':
        require(manifest['rights']=='INVENTED_PUBLIC_TEST' and manifest['provenance']==
            {'kind':'DETERMINISTIC_INVENTED_FIXTURE','producer':'polar-public-tests','source_payloads':'NONE'},'CALENDAR_INVENTED_NAMESPACE')
    else:
        require(manifest['rights']=='SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION' and
            len(b.member_statuses)==33 and len(b.nav_ns)==716 and len(rowmap)==1832 and len(roles['daily_decisions'])==715,
            'CALENDAR_RETAINED_METADATA_SCOPE')
        require(os.getuid()==10001 and platform.system()=='Linux' and platform.python_version()=='3.13.18' and
            os.environ.get('POLAR_RUNTIME_IMAGE_ID')==config['runtime_image_id'] and
            sys.pycache_prefix is not None and os.environ.get('PYTHONDONTWRITEBYTECODE')=='1','CALENDAR_RETAINED_RUNTIME')
    return p,b,side,roles,loc,manifest,calendars


def family(config,p):return sha(canonical({'protocol_id':p['protocol_id'],'input':config['input_ref']['sha256'],'namespace':config['namespace']}))


def authority(service,config,p,b):
    if config['namespace']=='INVENTED' and config['execution_authority_ref'] is None:return None
    require(config['execution_authority_ref'] is not None,'CALENDAR_OPERATIVE_AUTHORITY_REQUIRED')
    from .scheduled_service import authority_for
    grant=authority_for(service,config,p,{'FINAL':{}})
    require(grant['action']=='ORIGINAL' and all(type(grant.get(k)) is int and grant[k]==0 for k in
        ('allowed_fit_calls','allowed_predict_calls','allowed_model_calls','allowed_rank_calls','allowed_optimizer_calls','allowed_bootstrap_samples')),
        'CALENDAR_ZERO_MODEL_BOUND')
    require(type(grant.get('allowed_native_accounts')) is int and grant['allowed_native_accounts']==10 and
        type(grant.get('allowed_sma_observations')) is int and grant['allowed_sma_observations']==2*(len(b.nav_ns)-2),
        'CALENDAR_NATIVE_SMA_BOUND')
    require(grant.get('family')==family(config,p) and grant.get('artifact_root_identity')==root_identity(service.store.root) and
        type(grant.get('actor_uid')) is int and grant['actor_uid']==os.getuid() and
        type(grant.get('actor_gid')) is int and grant['actor_gid']==os.getgid(),'CALENDAR_ACTUAL_ACTOR_FAMILY_ROOT')
    return grant


def preflight(service,config):
    p,b,*_=prepare(service,config)
    grant=None
    if config['execution_authority_ref'] is not None:grant=authority(service,config,p,b)
    return {'schema':'polar.calendar-study-preflight/1','status':'METADATA_VALID_NOT_RUNNABLE' if config['namespace']=='RETAINED' and grant is None else 'READY_FOR_BOUND_OPERATION',
        'operation_binding_sha256':sha(canonical(binding(config))),'native_accounts':10,'sma_observations':2*(len(b.nav_ns)-2),
        'source_values_read':0,'strategy_execution':'NOT_RUN','scientific_starts':0,
        'fit_calls':0,'predict_calls':0,'model_calls':0,'execution_authority':grant is not None,
        'public_projection':'PRIVATE_ONLY_NO_PUBLICATION','zero_target_sizing':'UNQUALIFIED_UNFINALIZED_IF_ENCOUNTERED',
        'coincident_D_Q':'REFUSED_BY_PROFILE'}


def load_plan(config,b,roles,calendars):
    # First financial-value read only after durable FIRST_START.
    market=load_reference(config['input_ref']);source=[]
    for r in roles['source_rows']:
        evidence=market['source_evidence'][r['date']][r['symbol']]
        require(evidence['observed_historical_available_at'] is None and evidence['observed_published_at'] is None,
            'CALENDAR_OBSERVED_NULL_CLOCKS')
        source.append(ReferenceClose(r['symbol'],r['date'],r['close_ns'],r['available_ns'],
            market['prices_micro'][r['date']][r['symbol']],r['source_id'],r['role']))
    events=tuple(EventInstruction(request_from_event(e),e.candidate_ns) for e in calendars['conditional'].events
        if not e.cancelled and e.clock_status in ('OBSERVED_METADATA_ELIGIBLE','CONDITIONALLY_MODELED'))
    return EventPlan(b.account_scope,b.input_id,b.calendar_sha256,b.protocol_id,tuple(source),b.nav_ns,
        tuple(DecisionPoint(**d) for d in roles['daily_decisions']),events,b.nav_ns[1:-1])


def run(service,config):
    p,b,side,roles,loc,manifest,calendars=prepare(service,config);grant=authority(service,config,p,b)
    f=family(config,p);parent='scheduled-reference-attempts/'+f;aid=str(uuid.uuid4())
    with service.store.locked():
        # All current metadata/code/root/actor pins rechecked inside admission.
        prepare(service,config);authority(service,config,p,b)
        directory=service.store.root/parent;require(not directory.is_symlink(),'CALENDAR_ATTEMPT_SYMLINK')
        prior=sorted(v.name for v in directory.iterdir()) if directory.exists() else []
        require(not prior,'CALENDAR_ORIGINAL_ALREADY_RECORDED')
        if grant is not None:require(grant.get('expected_prior_attempts')==prior,'CALENDAR_CURRENT_PRIOR_ATTEMPTS')
        start={'schema':'polar.scheduled-reference-start/1','status':'FIRST_START_CONSERVATIVE_DEBIT','attempt_id':aid,
            'binding':binding(config),'started_ns':time.time_ns(),'native_accounts_allowed':10,'fit_calls':0,'predict_calls':0,'model_calls':0}
        service.store._publish(parent,aid,{'start.json':canonical(start),'config.json':canonical(config),'authority.json':canonical(grant)})
    events=[];completed=None
    try:
        plan=load_plan(config,b,roles,calendars)
        value=bounded_native(StudyRequest(plan,side,roles,b));events=value.pop('physical_native_events',[])
        completed=len(value['accounts']);require(completed==10,'CALENDAR_COMPLETE_NATIVE_CENSUS')
        graph=publish_study(service.store,value)
        index={'schema':'polar.calendar-study-semantic-manifest/1','binding':binding(config),'study_binding':plain(asdict(b)),
            'graph':graph,'attempt_family':f,'attempt_id':aid,'native_accounts':10,'public_projection':'PRIVATE_STUDY_ONLY'}
        raw=canonical(index);sid=SEMANTIC+sha(raw)
        with service.store.locked():service.store._publish('reference-research-experiments',sid,{'manifest.json':raw})
        finish={'status':'SUCCESS','attempt_id':aid,'semantic_id':sid,'private_study':graph,'native_accounts':completed,
            'fit_calls':0,'predict_calls':0,'model_calls':0,'financial_acceptance':'NOT_REVIEWED','finished_ns':time.time_ns()}
    except BaseException as exc:
        observed=getattr(exc,'events',events)
        if not isinstance(observed,list):observed=[]
        count=sum(v.get('phase')=='ACCOUNT_COMPLETED' for v in observed)
        finish={'status':'FAILED_UNFINALIZED','attempt_id':aid,'error':str(exc)[:240],
            'completed_native_accounts':completed if completed is not None else count if observed else None,
            'native_entry_count':sum(v.get('phase')=='NATIVE_RUN_ENTERED' for v in observed) if observed else None,
            'absent_counter_is_zero':False,'refund':False,'automatic_retry':False,'finished_ns':time.time_ns()}
        with service.store.locked():service.store._publish(parent+'/'+aid,'finish',{'record.json':canonical(finish),
            'diagnostics.json':canonical(observed)},file_limit=32*1024**2)
        raise
    with service.store.locked():service.store._publish(parent+'/'+aid,'finish',{'record.json':canonical(finish),'diagnostics.json':canonical(events)},file_limit=32*1024**2)
    return finish


def recompute(service,sid):
    require(type(sid) is str and re.fullmatch(SEMANTIC+'[a-f0-9]{64}',sid),'CALENDAR_SEMANTIC_ID')
    parent='reference-research-experiments/'+sid;raw=read_file(service.store.root,parent+'/manifest.json',32*1024**2)
    require(sid==SEMANTIC+sha(raw),'CALENDAR_SEMANTIC_PIN');index=decode(raw)
    require(index['schema']=='polar.calendar-study-semantic-manifest/1' and index['binding']['code']==code_binding(),
        'CALENDAR_SAVED_CODE_BINDING')
    start_parent='scheduled-reference-attempts/'+index['attempt_family']+'/'+index['attempt_id']
    finish=decode(read_file(service.store.root,start_parent+'/finish/record.json',32*1024**2))
    require(finish['status']=='SUCCESS' and finish['semantic_id']==sid and finish['private_study']==index['graph'],
        'CALENDAR_SUCCESS_ONLY_STORED_ELIGIBILITY')
    result=verify_stored_study(service.store.root,index['graph']['id'],binding_from_plain(index['study_binding']))
    return {'status':'REPRODUCED','semantic_id':sid,'private_study':index['graph'],'evaluation':__import__('polar.event_native_witness',fromlist=['encode']).encode(result['evaluation']),
        'source_reads':0,'native_calls':0,'model_calls':0,'writes':0,'financial_assessment':'NOT_ISSUED'}
