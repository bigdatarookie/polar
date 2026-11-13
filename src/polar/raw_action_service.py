"""Closed raw-action branch of ReferenceResearchService; PRIVATE outputs only.

Reuses existing attempt/store locks, native worker, money and evaluation. No
provider, queue/controller, public-result publication or automatic retry.
"""
from pathlib import Path
from datetime import datetime
import importlib.metadata
import os
import platform
import re
import sys
import time
import uuid

from .ci_research import require
from .ci_research_service import root_identity, bounded_native
from .gym_contract import canonical, decode, sha, read_ref
from .gym_service import code_binding
from .history_bundle import read_file
from .scheduled_service import binding, authority_for
from .raw_action_input import metadata, calendar, load
from .raw_action_native import LEGS
from .raw_action_evaluation import evaluate, diagnose, initial_control, verify_tape

CONFIG = 'polar.raw-action-config/1'
SEMANTIC = 'raw-action-experiment-'
COSTS = [{'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
         {'id':'STRESS','cost_profile':{'flat_cents':200,'bps':20}}]


def config_from_seed(seed):
    from .scheduled_service import config_from_seed as existing
    return {**existing(seed),'schema':CONFIG}


def prepare(service, config):
    fields={'schema','namespace','profile_ref','protocol_ref','input_ref','calendar_ref','timezone_ref',
        'code','code_revision','runtime_image_id','candidate_id','experiment_id','execution_authority_ref','artifact_root_identity'}
    require(type(config) is dict and set(config)==fields and config['schema']==CONFIG and
        config['namespace'] in ('INVENTED','RETAINED'),'RAW_CONFIG_SCHEMA')
    require(config['artifact_root_identity']==root_identity(service.store.root) and config['code']==code_binding() and
        re.fullmatch('[a-f0-9]{40}',config['code_revision']) and re.fullmatch('sha256:[a-f0-9]{64}',config['runtime_image_id']),
        'RAW_CURRENT_CODE_ROOT_RUNTIME')
    profile=decode(read_ref(config['profile_ref']))
    require(type(profile) is dict and set(profile)=={'schema','protocol_id','protocol_sha256','input_sha256',
        'calendar_sha256','timezone_sha256','legs','cost_scenarios','policy','capital_cents'} and
        profile['schema']=='polar.raw-action-profile/1' and profile['legs']==list(LEGS) and
        profile['cost_scenarios']==COSTS and profile['policy']=='CLOSED_PAYMENT_RETAIN_ANNUAL_CASH_D60' and
        type(profile['capital_cents']) is int and profile['capital_cents']==10000000,'RAW_CLOSED_PROFILE')
    require(profile['protocol_sha256']==sha(read_ref(config['protocol_ref'])) and
        profile['input_sha256']==config['input_ref']['sha256'] and
        profile['calendar_sha256']==sha(read_ref(config['calendar_ref'])) and
        profile['timezone_sha256']==sha(read_ref(config['timezone_ref'])),'RAW_PROFILE_BINDINGS')
    require(type(profile['protocol_id']) is str and re.fullmatch('[A-Za-z0-9_.:-]{1,100}',profile['protocol_id']),
        'RAW_PROTOCOL_ID')
    # Timezone bytes are bound; decisions deliberately use modeled UTC, not local NY K.
    import io
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    tz=ZoneInfo.from_file(io.BytesIO(read_ref(config['timezone_ref'])),key='UTC')
    require(tz.utcoffset(datetime(2020,1,1))==timedelta(0),'RAW_UTC_TIMEZONE')
    if config['namespace']=='RETAINED':
        require(platform.system()=='Linux' and platform.machine() in ('aarch64','x86_64') and
            platform.python_version()=='3.13.18' and os.environ.get('POLAR_RUNTIME_IMAGE_ID')==config['runtime_image_id'] and
            sys.pycache_prefix is not None and os.environ.get('PYTHONDONTWRITEBYTECODE')=='1','RAW_ACTUAL_RUNTIME')
        require(importlib.metadata.version('nautilus-trader')=='1.231.0','RAW_NATIVE_VERSION')
    d,days,rows=metadata(config['input_ref'],config['namespace'])
    grid=calendar(d,days,rows)
    require(decode(read_ref(config['calendar_ref']))==grid,'RAW_CALENDAR_BINDING')
    return profile,d,grid,rows


def authority(service, config, profile, descriptor=None):
    value=authority_for(service,config,profile,{'FINAL':{}})
    if value is not None:
        require(all(value.get(k)==0 for k in ('allowed_score_calls','allowed_rank_calls','allowed_estimator_calls',
            'allowed_optimizer_calls','allowed_bootstrap_samples')),'RAW_NO_MODEL_OPERATION')
        review=decode(read_ref(value['independent_review_ref']))
        require(review.get('schema')=='polar.raw-action-technical-review/1' and review.get('status')=='PASS' and
            review.get('candidate_sha')==config['code_revision'] and review.get('protocol_sha256')==config['protocol_ref']['sha256'] and
            review.get('input_sha256')==config['input_ref']['sha256'] and
            review.get('reviewer') not in (None,'','platform-engineer@polar-rig') and
            type(review.get('report_ref')) is dict,'RAW_INDEPENDENT_TECHNICAL_BINDING')
        read_ref(review['report_ref'])
        if value.get('action')=='CORRECTIVE_RAW_ACTION_E1':
            from .raw_action_corrective import amendment
            amendment(value,config,profile,descriptor)
    return value


def preflight(service,config):
    p,d,g,r=prepare(service,config);authority(service,config,p,d)
    return {'schema':'polar.raw-action-preflight/1','status':'READY_FOR_BOUND_OPERATION',
        'operation_binding_sha256':sha(canonical(binding(config))),'scientific_starts':0,
        'expected_native_accounts':8,'expected_ex_recognitions':8*len(d['event_dates']),
        'expected_payments':8*len(d['event_dates']),'formation_dates':len(g['events']),
        'financial_values':'NOT_PARSED','common_result_publication':'NOT_SUPPORTED_PRIVATE_TYPED_ARTIFACT_ONLY'}


def private_result(config, phase, simulation, evaluation, diagnostics, initial, source_context):
    from .raw_action_result import validate
    return validate({'schema':'polar.private-raw-action-result/1','phase':phase,
        'bindings':binding(config),'basis':{'currency':'USD','quantity':'WHOLE_RAW_SHARE_DECLARED_CURRENT_SOURCE_IDENTITY',
            'wealth':'RAW_MARKS_PLUS_CAPTURED_NOMINAL_RECEIVABLES','payment':'MODELED_FIRST_REFERENCE_CLOSE_CIVIL_STRICTLY_AFTER_PAYDATE',
            'cash':'AVAILABLE_NATIVE_CASH_ONLY','receivable':'SEPARATE_NOMINAL_CENTS_NO_DISCOUNT_TAX',
            'historical_K':None,'physical_investor_total_return':'NOT_CERTIFIED'},
        'source_context':source_context,
        'series':[{'id':t['id'],'role':'STRATEGY' if t['id']==LEGS[0] else 'BENCHMARK' if t['id']==LEGS[1] else 'CONTROL',
            'ledger':[{k:r[k] for k in ('date','nominal_ns','cash_cents','exposure_cents','receivable_cents',
                'position_cents','positions','nav_cents','flat_cents','bps_cents')} for r in t['nav']]} for t in simulation['legs']],
        'primary_benchmark':LEGS[1],'evaluation':evaluation,'diagnostics':diagnostics,'initial_state_control':initial,
        'financial':'NOT_REVIEWED','adoption':'INSUFFICIENT_EVIDENCE','robustness':'INSUFFICIENT_EVIDENCE',
        'rights':'PRIVATE_ONEOFF_DEMO_NO_DATA_CONTAINING_REDISTRIBUTION_OR_CONTINUING_FEED',
        'common_research_result':'NOT_PUBLISHED_NO_LEGACY_FIELD_REDEFINITION'})


def run(service,config):
    p,d,g,rows=prepare(service,config);grant=authority(service,config,p,d)
    family=sha(canonical({'protocol_id':p['protocol_id'],'input':config['input_ref']['sha256'],'namespace':config['namespace']}))
    parent='scheduled-reference-attempts/'+family;aid=str(uuid.uuid4())
    lineage=None
    started_ns=time.time_ns()
    with service.store.locked():
        directory=service.store.root/parent
        prior=sorted(x.name for x in directory.iterdir()) if directory.exists() else []
        require(not directory.is_symlink(),'RAW_ORIGINAL_ALREADY_RECORDED')
        if grant is not None and grant.get('action')=='CORRECTIVE_RAW_ACTION_E1':
            from .raw_action_corrective import admit_locked
            lineage=admit_locked(service,config,p,d,grant,parent,family,prior)
        else:require(not prior,'RAW_ORIGINAL_ALREADY_RECORDED')
        if grant is not None:require(grant.get('expected_prior_attempts')==prior,'RAW_PRIOR_ATTEMPTS')
        started_ns=time.time_ns()
        start={'status':'FIRST_START_CONSERVATIVE_DEBIT','attempt_id':aid,'binding':binding(config),'started_ns':started_ns}
        if lineage is not None:start['corrective_lineage']=lineage
        service.store._publish(parent,aid,{'start.json':canonical(start),'config.json':canonical(config),
            'authority.json':canonical(grant)})
    completed=0;completed_lifecycle={'recognize':0,'pay':0}
    try:
        market=load(d,g['dates'],rows)  # FIRST financial-value parse, after durable debit.
        plan={'profile':{'kind':'RAW_ACTION_REINVEST'},'instrument':d['source_instrument'],
            'dates':g['dates'],'schedule':rows,'events':g['events'],'prices':market['prices'],'actions':market['actions']}
        files={'profile.json':canonical(p),'bindings.json':canonical(binding(config)),
            'calendar.json':canonical(g),'plan.json':canonical(plan),'source-evidence.json':canonical(market)}
        projections={}
        for scenario in COSTS:
            phase=scenario['id'];current={**plan,'cost_profile':scenario['cost_profile']}
            simulation=bounded_native(current);completed+=len(simulation['legs'])
            for tape in simulation['legs']:
                verify_tape(tape,current)
                if lineage is not None:
                    for key in completed_lifecycle:
                        actual=sum(e['operation']==key for e in tape['claim_events'])
                        require(type(tape['component_counts'][key]) is int and tape['component_counts'][key]==actual,'RAW_CORRECTIVE_LIFECYCLE_COUNT')
                        completed_lifecycle[key]+=actual
            initial=initial_control(simulation);evaluation=evaluate(simulation)
            diagnostics={t['id']:diagnose(t,rows,base=phase=='BASE') for t in simulation['legs']}
            result=private_result(config,phase,simulation,evaluation,diagnostics,initial,d)
            raw=canonical(result);rid='private-raw-action-result-'+sha(raw)
            projections[phase]={'result_id':rid,'sha256':sha(raw),'file':phase+'-result.json'}
            phasefiles={phase+'-'+t['id']+'.json':canonical(t) for t in simulation['legs']}
            phasefiles[phase+'-result.json']=raw
            files.update(phasefiles)
            with service.store.locked():
                service.store._publish(parent+'/'+aid+'/phases',phase,phasefiles,file_limit=32*1024**2)
        if lineage is not None:
            require(completed==8 and completed_lifecycle=={'recognize':lineage['allowed_ex_recognitions'],'pay':lineage['allowed_payments']},'RAW_CORRECTIVE_LIFECYCLE_COUNT')
        manifest={'schema':'polar.raw-action-semantic-manifest/1','files':
            {name:{'sha256':sha(body),'bytes':len(body)} for name,body in files.items()}}
        raw=canonical(manifest);sid=SEMANTIC+sha(raw)
        with service.store.locked():
            service.store._publish('reference-research-experiments',sid,{**files,'manifest.json':raw},file_limit=32*1024**2)
        finish={'status':'SUCCESS','attempt_id':aid,'semantic_id':sid,'private_results':projections,
            'native_accounts':completed,'fit_calls':0,'predict_calls':0,'model_calls':0,'score_calls':0,
            'rank_calls':0,'estimator_calls':0,'optimizer_calls':0,'bootstrap_samples':0,
            'financial_acceptance':'NOT_REVIEWED','finished_ns':time.time_ns()}
    except BaseException as exc:
        events=getattr(exc,'events',[])
        if not isinstance(events,list):events=[]
        finish={'status':'FAILED_UNFINALIZED','attempt_id':aid,'error':str(exc)[:240],
            'completed_native_accounts':completed+sum(e.get('phase')=='ACCOUNT_COMPLETED' for e in events),
            'native_run_entries_in_failed_phase':sum(e.get('phase')=='NATIVE_RUN_ENTERED' for e in events),
            'refund':False,'automatic_retry':False,'finished_ns':time.time_ns()}
        if lineage is not None:
            finish['completed_verified_lifecycle_counts']=dict(completed_lifecycle)
            from .raw_action_corrective import account_finish
            account_finish(finish,lineage,started_ns)
        with service.store.locked():service.store._publish(parent+'/'+aid,'finish',
            {'record.json':canonical(finish),'diagnostics.json':canonical(getattr(exc,'events',[]))},file_limit=32*1024**2)
        raise
    if lineage is not None:
        finish['completed_verified_lifecycle_counts']=dict(completed_lifecycle)
        from .raw_action_corrective import account_finish
        account_finish(finish,lineage,started_ns)
    with service.store.locked():service.store._publish(parent+'/'+aid,'finish',{'record.json':canonical(finish)})
    return finish


def recompute(service,sid):
    require(re.fullmatch(SEMANTIC+'[a-f0-9]{64}',sid),'RAW_SEMANTIC_ID')
    parent='reference-research-experiments/'+sid;raw=read_file(service.store.root,parent+'/manifest.json',32*1024**2)
    require(sid==SEMANTIC+sha(raw),'RAW_MANIFEST_ID');manifest=decode(raw)
    names={'profile.json','bindings.json','calendar.json','plan.json','source-evidence.json'}|{
        phase+'-'+leg+'.json' for phase in ('BASE','STRESS') for leg in LEGS}|{'BASE-result.json','STRESS-result.json'}
    require(manifest['schema']=='polar.raw-action-semantic-manifest/1' and set(manifest['files'])==names,'RAW_MANIFEST_MEMBERS')
    files={}
    for name,pin in manifest['files'].items():
        body=read_file(service.store.root,parent+'/'+name,32*1024**2)
        require(sha(body)==pin['sha256'] and len(body)==pin['bytes'],'RAW_MEMBER_INTEGRITY');files[name]=decode(body)
    config=files['bindings.json'];require(config['code']==code_binding(),'RAW_STORED_CODE_BINDING')
    plan=files['plan.json'];results={}
    for scenario in COSTS:
        phase=scenario['id'];current={**plan,'cost_profile':scenario['cost_profile']}
        simulation={'legs':[files[phase+'-'+leg+'.json'] for leg in LEGS],'cost_profile':scenario['cost_profile']}
        for tape in simulation['legs']:verify_tape(tape,current)
        initial=initial_control(simulation);evaluation=evaluate(simulation)
        diagnostics={t['id']:diagnose(t,plan['schedule'],base=phase=='BASE') for t in simulation['legs']}
        expected=private_result(config,phase,simulation,evaluation,diagnostics,initial,
            files['source-evidence.json']['source_identity'])
        require(expected==files[phase+'-result.json'],'RAW_PRIVATE_RESULT_REPRODUCTION')
        results[phase]='private-raw-action-result-'+sha(canonical(expected))
    return {'status':'REPRODUCED','semantic_id':sid,'private_results':results,'native_calls':0,
        'source_calls':0,'policy_calls':0,'fit_calls':0,'predict_calls':0,'model_calls':0,'store_writes':0}


if __name__ == '__main__':
    import argparse,json
    from .reference_service import ReferenceResearchService
    parser=argparse.ArgumentParser(description='Existing local reference service raw/action PRIVATE branch')
    parser.add_argument('operation',choices=('config','preflight','run','recompute'))
    parser.add_argument('input',help='Seed/config JSON path, or immutable semantic ID for recompute')
    parser.add_argument('--root',required=True);parser.add_argument('--limit-bytes',type=int,default=64*1024**3)
    args=parser.parse_args();service=ReferenceResearchService(Path(args.root),args.limit_bytes)
    if args.operation=='config':result=config_from_seed(json.loads(Path(args.input).read_bytes()))
    elif args.operation=='recompute':result=recompute(service,args.input)
    else:result=globals()[args.operation](service,json.loads(Path(args.input).read_bytes()))
    print(json.dumps(result,sort_keys=True))
