"""Closed same-family B7 correction admission; no source-value reader or retry."""
import re
from .ci_research import require
from .gym_contract import canonical,sha,decode,read_ref
from .scheduled_corrective import science_binding,read_prior_members,MEMBERS

ACTION='CORRECTIVE_RAW_ACTION_E1'


def amendment(authority,config,profile,descriptor,family=None):
    require(profile['schema']=='polar.raw-action-profile/1' and config['schema']=='polar.raw-action-config/1' and
            authority.get('action')==ACTION,'RAW_CORRECTIVE_PROFILE_ACTION')
    expected=sha(canonical({'protocol_id':profile['protocol_id'],'input':config['input_ref']['sha256'],'namespace':config['namespace']}))
    require(family is None or family==expected,'RAW_CORRECTIVE_FAMILY')
    value=decode(read_ref(authority['corrective_amendment_ref']))
    fields={'schema','status','action','family','candidate_id','experiment_id','prior_attempt_id','prior_members',
            'science_binding_sha256','current_binding_sha256','prior_audit_ref','custody_ref','invariants_ref',
            'owner_id','maximum_family_starts','allowed_ex_recognitions','allowed_payments','allowed_native_accounts',
            'total_work_budget_ns','prior_charged_work_ns','allowed_e1_work_ns'}
    require(type(value) is dict and set(value)==fields and value['schema']=='polar.raw-action-corrective-amendment/1' and
            value['status']=='BOUND_FOR_EXECUTION' and value['action']==ACTION,'RAW_CORRECTIVE_AMENDMENT_SCHEMA')
    require(value['family']==expected and value['candidate_id']==config['candidate_id'] and value['experiment_id']==config['experiment_id'] and
            type(value['owner_id']) is str and 0<len(value['owner_id'])<=100 and type(value['prior_attempt_id']) is str and
            bool(re.fullmatch('[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',value['prior_attempt_id'])),'RAW_CORRECTIVE_IDENTITY')
    from .scheduled_service import binding
    require(value['current_binding_sha256']==sha(canonical(binding(config))) and
            value['science_binding_sha256']==sha(canonical(science_binding(config))),'RAW_CORRECTIVE_BINDING')
    require(all(type(authority.get(k)) is int and authority[k]==0 for k in ('allowed_fit_calls','allowed_predict_calls',
            'allowed_score_calls','allowed_rank_calls','allowed_estimator_calls','allowed_optimizer_calls','allowed_bootstrap_samples')),
            'RAW_CORRECTIVE_ZERO_ALLOWANCE')
    expected_events=8*len(descriptor['event_dates'])
    require(all(type(value[k]) is int for k in ('maximum_family_starts','allowed_ex_recognitions','allowed_payments','allowed_native_accounts')) and
            value['maximum_family_starts']==2 and value['allowed_native_accounts']==8 and
            value['allowed_ex_recognitions']==value['allowed_payments']==expected_events,'RAW_CORRECTIVE_ALLOWANCE')
    require(all(type(value[k]) is int for k in ('total_work_budget_ns','prior_charged_work_ns','allowed_e1_work_ns')) and
            value['total_work_budget_ns']==1200*10**9 and value['prior_charged_work_ns']>0 and
            0<value['allowed_e1_work_ns']<=value['total_work_budget_ns']-value['prior_charged_work_ns'],'RAW_CORRECTIVE_WORK_ALLOWANCE')
    for key in ('prior_audit_ref','custody_ref','invariants_ref'):read_ref(value[key])
    require(type(value['prior_members']) is dict and set(value['prior_members'])==MEMBERS,'RAW_CORRECTIVE_PRIOR_MEMBER_SET')
    return value


def admit_locked(service,config,profile,descriptor,authority,parent,family,prior):
    """Existing store lock, exactly one prior; no values or new debit yet."""
    value=amendment(authority,config,profile,descriptor,family);old=value['prior_attempt_id']
    require(prior==[old] and authority.get('expected_prior_attempts')==prior,'RAW_CORRECTIVE_PRIOR_HISTORY')
    saved=read_prior_members(service,parent,old,value['prior_members'])
    start=saved['start.json'];finish=saved['finish/record.json'];oldconfig=saved['config.json']
    require(start.get('attempt_id')==finish.get('attempt_id')==old and start.get('status')=='FIRST_START_CONSERVATIVE_DEBIT' and
            finish.get('status')=='FAILED_UNFINALIZED' and finish.get('error')=='RAW_CONTENT_EVENT_ID' and
            finish.get('refund') is False and finish.get('automatic_retry') is False and
            type(finish.get('completed_native_accounts')) is int and finish['completed_native_accounts']==0 and
            type(finish.get('native_run_entries_in_failed_phase')) is int and finish['native_run_entries_in_failed_phase']==0 and
            not finish.get('semantic_id') and not finish.get('private_results'),'RAW_CORRECTIVE_PRIOR_STATUS')
    require(saved['finish/diagnostics.json']==[],'RAW_CORRECTIVE_PRIOR_DIAGNOSTIC')
    from .scheduled_service import binding
    require(start.get('binding')==binding(oldconfig) and science_binding(oldconfig)==science_binding(config),'RAW_CORRECTIVE_UNCHANGED_SCIENCE')
    oldauthority=saved['authority.json']
    require((oldconfig.get('namespace')=='INVENTED' and oldauthority is None) or
            (type(oldauthority) is dict and oldauthority.get('action')=='ORIGINAL'),'RAW_CORRECTIVE_OLD_ORIGINAL')
    if oldauthority is not None:
        require(all(oldauthority.get(k)==authority.get(k) for k in ('method_ref','candidate_ref')),'RAW_CORRECTIVE_SAME_METHOD_CARD')
    require(type(start.get('started_ns')) is int and type(finish.get('finished_ns')) is int and
            0<finish['finished_ns']-start['started_ns']<=value['prior_charged_work_ns'],'RAW_CORRECTIVE_PRIOR_WORK_CHARGE')
    return {'schema':'polar.raw-action-corrective-lineage/1','action':ACTION,'family':family,'prior_attempt_id':old,
            'prior_members':value['prior_members'],'amendment_sha256':sha(canonical(value)),'family_start_count':2,
            'prior_completed_native_accounts':0,'prior_recorded_native_entries':0,
            'prior_lifecycle_counts':'NOT_EMITTED_NOT_INFERRED_ZERO','allowed_ex_recognitions':value['allowed_ex_recognitions'],
            'allowed_payments':value['allowed_payments'],'prior_charged_work_ns':value['prior_charged_work_ns'],
            'allowed_e1_work_ns':value['allowed_e1_work_ns'],'total_work_budget_ns':value['total_work_budget_ns'],
            'old_stored_allocation':'INELIGIBLE_NOT_RECYCLED'}


def account_finish(finish,lineage,started_ns):
    if lineage is None:return
    finish['corrective_lineage']=lineage
    finish['cumulative_completed_native_accounts']=lineage['prior_completed_native_accounts']+finish.get('completed_native_accounts',finish.get('native_accounts',0))
    finish['cumulative_lifecycle_counts']=None
    finish['cumulative_lifecycle_reason']='UNAVAILABLE_PRIOR_COUNTERS_NOT_EMITTED'
    finish['recorded_work_wall_ns']=max(0,finish['finished_ns']-started_ns)
    finish['cumulative_charged_work_ns']=lineage['prior_charged_work_ns']+finish['recorded_work_wall_ns']
    finish['work_budget_exceeded']=finish['cumulative_charged_work_ns']>lineage['total_work_budget_ns']
