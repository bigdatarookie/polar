"""Closed B8 E1 admission; immutable failed original remains charged in-family."""
import re
from .ci_research import require
from .gym_contract import canonical,sha,decode,read_ref
from .history_bundle import read_file

ACTION='CORRECTIVE_E1'
MEMBERS={'start.json','config.json','authority.json','finish/record.json','finish/diagnostics.json'}
OLD_COUNTS={'feature_calls':1,'rate_operand_reads':0,'completed_features':0,'sign_decisions':0,'completed_decisions':0}
NEW_COUNTS={'feature_calls':47,'rate_operand_reads':94,'completed_features':47,'sign_decisions':47,'completed_decisions':47}


def science_binding(config):
    # New qualified code/runtime/operative authority may differ; science, root,
    # candidate, registration and all original source/profile refs may not.
    return {k:v for k,v in config.items() if k not in ('code','code_revision','runtime_image_id','execution_authority_ref')}


def amendment(authority,config,profile,family):
    require(profile['schema']=='polar.scheduled-reference-profile/11' and authority.get('action')==ACTION,'CORRECTIVE_PROFILE_ACTION')
    value=decode(read_ref(authority['corrective_amendment_ref']))
    fields={'schema','status','action','family','candidate_id','experiment_id','prior_attempt_id','prior_members',
            'science_binding_sha256','current_binding_sha256','prior_audit_ref','custody_ref','invariants_ref',
            'owner_id','maximum_family_starts','allowed_feature_counts','allowed_native_accounts',
            'total_work_budget_ns','prior_charged_work_ns','allowed_e1_work_ns'}
    require(type(value) is dict and set(value)==fields and value['schema']=='polar.scheduled-corrective-amendment/1' and
            value['status']=='BOUND_FOR_EXECUTION' and value['action']==ACTION,'CORRECTIVE_AMENDMENT_SCHEMA')
    require(value['family']==family and value['candidate_id']==config['candidate_id'] and value['experiment_id']==config['experiment_id'] and
            type(value['owner_id']) is str and 0<len(value['owner_id'])<=100 and
            bool(re.fullmatch('[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',value['prior_attempt_id'])), 'CORRECTIVE_IDENTITY')
    from .scheduled_service import binding
    require(value['current_binding_sha256']==sha(canonical(binding(config))) and
            value['science_binding_sha256']==sha(canonical(science_binding(config))), 'CORRECTIVE_BINDING')
    require(type(value['allowed_feature_counts']) is dict and all(type(value['allowed_feature_counts'].get(k)) is int for k in NEW_COUNTS) and
            all(type(authority.get(k)) is int and authority[k]==0 for k in ('allowed_fit_calls','allowed_predict_calls','allowed_score_calls','allowed_rank_calls','allowed_estimator_calls','allowed_optimizer_calls','allowed_bootstrap_samples')), 'CORRECTIVE_TYPED_ALLOWANCE')
    require(type(value['maximum_family_starts']) is int and value['maximum_family_starts']==2 and
            value['allowed_feature_counts']==NEW_COUNTS and value['allowed_native_accounts']==8,'CORRECTIVE_ALLOWANCE')
    require(all(type(value[k]) is int for k in ('total_work_budget_ns','prior_charged_work_ns','allowed_e1_work_ns')) and
            value['total_work_budget_ns']==1200*10**9 and value['prior_charged_work_ns']>0 and
            0<value['allowed_e1_work_ns']<=value['total_work_budget_ns']-value['prior_charged_work_ns'], 'CORRECTIVE_WORK_ALLOWANCE')
    # These are integrity-pinned existing audit/custody/invariant references, not
    # a new audit PASS or cryptographic authentication of an owner assertion.
    for key in ('prior_audit_ref','custody_ref','invariants_ref'):read_ref(value[key])
    require(type(value['prior_members']) is dict and set(value['prior_members'])==MEMBERS,'CORRECTIVE_PRIOR_MEMBER_SET')
    return value


def admit_locked(service,config,profile,authority,parent,family,prior):
    """Called only while the existing store lock is held, before new debit."""
    value=amendment(authority,config,profile,family);old=value['prior_attempt_id']
    require(prior==[old] and authority.get('expected_prior_attempts')==prior,'CORRECTIVE_PRIOR_HISTORY')
    saved={}
    for name,pin in value['prior_members'].items():
        require(type(pin) is dict and set(pin)=={'sha256','bytes'} and type(pin['bytes']) is int and
                0<pin['bytes']<=32*1024**2 and type(pin['sha256']) is str and bool(re.fullmatch('[a-f0-9]{64}',pin['sha256'])), 'CORRECTIVE_PRIOR_PIN')
        raw=read_file(service.store.root,parent+'/'+old+'/'+name,32*1024**2)
        require(len(raw)==pin['bytes'] and sha(raw)==pin['sha256'],'CORRECTIVE_PRIOR_INTEGRITY');saved[name]=decode(raw)
    start=saved['start.json'];finish=saved['finish/record.json'];diagnostic=saved['finish/diagnostics.json'];oldconfig=saved['config.json']
    require(start.get('attempt_id')==finish.get('attempt_id')==old and start.get('status')=='FIRST_START_CONSERVATIVE_DEBIT' and
            finish.get('status')=='FAILED_UNFINALIZED' and finish.get('scientific_status')=='INVALID' and
            finish.get('error')=='CURVE_INVALID_OPERAND_OR_DOMAIN' and
            finish.get('refund') is False and finish.get('automatic_retry') is False and
            finish.get('completed_native_accounts')==0 and not finish.get('semantic_id') and not finish.get('results') and
            finish.get('actual_feature_counts')==OLD_COUNTS and
            type(finish.get('completed_native_accounts')) is int and
            all(type(finish['actual_feature_counts'].get(k)) is int for k in OLD_COUNTS),'CORRECTIVE_PRIOR_STATUS')
    require(type(diagnostic) is dict and diagnostic.get('cause')=='CURVE_RAW_SOURCE_REF' and diagnostic.get('actual_counts')==OLD_COUNTS,'CORRECTIVE_PRIOR_DIAGNOSTIC')
    from .scheduled_service import binding
    require(start.get('binding')==binding(oldconfig) and science_binding(oldconfig)==science_binding(config),'CORRECTIVE_UNCHANGED_SCIENCE')
    oldauthority=saved['authority.json']
    require((oldconfig.get('namespace')=='INVENTED' and oldauthority is None) or
            (type(oldauthority) is dict and oldauthority.get('action')=='ORIGINAL'), 'CORRECTIVE_OLD_ORIGINAL')
    if oldauthority is not None:
        require(all(oldauthority.get(k)==authority.get(k) for k in ('method_ref','candidate_ref')), 'CORRECTIVE_SAME_METHOD_CARD')
    require(type(start.get('started_ns')) is int and type(finish.get('finished_ns')) is int and
            0<finish['finished_ns']-start['started_ns']<=value['prior_charged_work_ns'],'CORRECTIVE_PRIOR_WORK_CHARGE')
    # Never inspect/invent an absent native-entry count. Completed phase accounts
    # and optional detailed native-entry diagnostics are distinct observations.
    return {'schema':'polar.scheduled-corrective-lineage/1','action':ACTION,'family':family,'prior_attempt_id':old,
            'prior_members':value['prior_members'],'amendment_sha256':sha(canonical(value)),
            'prior_actual_feature_counts':dict(OLD_COUNTS),'prior_completed_native_accounts':0,
            'prior_native_entry_counter':'NOT_EMITTED_NOT_INFERRED_ZERO','family_start_count':2,
            'prior_charged_work_ns':value['prior_charged_work_ns'],'allowed_e1_work_ns':value['allowed_e1_work_ns'],
            'total_work_budget_ns':value['total_work_budget_ns'],'old_stored_allocation':'INELIGIBLE_NOT_RECYCLED'}


def account_finish(finish,lineage,started_ns):
    """Additive observed accounting; no refund/reset or third-start capability."""
    if lineage is None:return
    counts=finish['actual_feature_counts']
    finish['corrective_lineage']=lineage
    if type(counts) is dict and set(counts)==set(OLD_COUNTS) and all(type(counts[k]) is int and counts[k]>=0 for k in OLD_COUNTS):
        finish['cumulative_recorded_feature_counts']={k:lineage['prior_actual_feature_counts'][k]+counts[k] for k in OLD_COUNTS}
    else:
        finish['cumulative_recorded_feature_counts']=None
        finish['cumulative_feature_count_reason']='UNAVAILABLE_CURRENT_COUNTER_SHAPE'
    finish['cumulative_completed_native_accounts']=lineage['prior_completed_native_accounts']+finish.get('completed_native_accounts',finish.get('native_accounts',0))
    finish['recorded_work_wall_ns']=max(0,finish['finished_ns']-started_ns)
    finish['cumulative_charged_work_ns']=lineage['prior_charged_work_ns']+finish['recorded_work_wall_ns']
    finish['work_budget_exceeded']=finish['cumulative_charged_work_ns']>lineage['total_work_budget_ns']
