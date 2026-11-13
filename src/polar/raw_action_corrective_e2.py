"""Closed two-prior B7 E2 admission; no value reader or generic retry."""
import re
from .ci_research import require
from .gym_contract import canonical,sha,decode,read_ref
from .scheduled_corrective import science_binding,read_prior_members,MEMBERS
from .raw_action_corrective import ACTION as E1_ACTION,account_finish as e1_account

ACTION='CORRECTIVE_RAW_ACTION_E2'


def same(a,b):return canonical(a)==canonical(b)


def amendment(authority,config,profile,descriptor,family=None):
    require(profile['schema']=='polar.raw-action-profile/1' and config['schema']=='polar.raw-action-config/1' and
            authority.get('action')==ACTION,'RAW_E2_PROFILE_ACTION')
    expected=sha(canonical({'protocol_id':profile['protocol_id'],'input':config['input_ref']['sha256'],'namespace':config['namespace']}))
    require(family is None or family==expected,'RAW_E2_FAMILY')
    v=decode(read_ref(authority['corrective_amendment_ref']))
    fields={'schema','status','action','family','candidate_id','experiment_id','original_attempt_id','e1_attempt_id','prior_members',
        'science_binding_sha256','current_binding_sha256','prior_audit_refs','custody_ref','invariants_ref','applicability_ref',
        'charge_history_ref','owner_id','maximum_family_starts','allowed_ex_recognitions','allowed_payments',
        'allowed_native_accounts','total_work_budget_ns','prior_charged_work_ns','allowed_e2_work_ns'}
    require(type(v) is dict and set(v)==fields and v['schema']=='polar.raw-action-corrective-amendment/2' and
            v['status']=='BOUND_FOR_EXECUTION' and v['action']==ACTION,'RAW_E2_AMENDMENT')
    ids=[v['original_attempt_id'],v['e1_attempt_id']]
    require(all(type(x) is str and re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',x) for x in ids) and
            len(set(ids))==2 and v['family']==expected and v['candidate_id']==config['candidate_id'] and
            v['experiment_id']==config['experiment_id'] and type(v['owner_id']) is str and 0<len(v['owner_id'])<=100,'RAW_E2_IDENTITY')
    from .scheduled_service import binding
    require(v['current_binding_sha256']==sha(canonical(binding(config))) and
            v['science_binding_sha256']==sha(canonical(science_binding(config))),'RAW_E2_BINDING')
    require(all(type(authority.get(k)) is int and authority[k]==0 for k in ('allowed_fit_calls','allowed_predict_calls',
            'allowed_score_calls','allowed_rank_calls','allowed_estimator_calls','allowed_optimizer_calls','allowed_bootstrap_samples')),
            'RAW_E2_ZERO_ALLOWANCE')
    count=8*len(descriptor['event_dates'])
    require(all(type(v[k]) is int for k in ('maximum_family_starts','allowed_ex_recognitions','allowed_payments','allowed_native_accounts')) and
            v['maximum_family_starts']==3 and v['allowed_native_accounts']==8 and
            v['allowed_ex_recognitions']==v['allowed_payments']==count,'RAW_E2_ALLOWANCE')
    require(all(type(v[k]) is int for k in ('total_work_budget_ns','prior_charged_work_ns','allowed_e2_work_ns')) and
            v['total_work_budget_ns']==1200*10**9 and 323*10**9<=v['prior_charged_work_ns']<v['total_work_budget_ns'] and
            0<v['allowed_e2_work_ns']<=v['total_work_budget_ns']-v['prior_charged_work_ns'],'RAW_E2_WORK')
    require(type(v['prior_members']) is dict and set(v['prior_members'])==set(ids) and
            all(type(pins) is dict and set(pins)==MEMBERS for pins in v['prior_members'].values()),'RAW_E2_PRIOR_MEMBER_SET')
    require(type(v['prior_audit_refs']) is dict and set(v['prior_audit_refs'])==set(ids),'RAW_E2_PRIOR_AUDITS')
    for ref in list(v['prior_audit_refs'].values())+[v[k] for k in ('custody_ref','invariants_ref','charge_history_ref')]:read_ref(ref)
    a=decode(read_ref(v['applicability_ref']))
    require(type(a) is dict and a.get('schema')=='polar.validator-financial-repeat-applicability/1' and
            a.get('disposition')=='APPLICABLE_SAME_FROZEN_CHOICE_TECHNICAL_RECHECK_E2_WITH_PARTIAL_NATIVE_EXPOSURE' and
            a.get('scientific_scope_status')=='PASS_BOUNDED_PROSPECTIVE_APPLICABILITY' and
            a.get('candidate_id')==config['candidate_id'] and a.get('experiment_registration_id')==config['experiment_id'] and
            a.get('family')==expected and a.get('unmet_prospective_scientific_choice_predicates')==[],'RAW_E2_APPLICABILITY')
    return v


def admit_locked(service,config,profile,descriptor,authority,parent,family,prior):
    """Under existing store lock, before a third debit and before any values."""
    v=amendment(authority,config,profile,descriptor,family);old=v['original_attempt_id'];e1=v['e1_attempt_id']
    require(prior==sorted([old,e1]) and authority.get('expected_prior_attempts')==prior,'RAW_E2_PRIOR_HISTORY')
    saved={aid:read_prior_members(service,parent,aid,v['prior_members'][aid]) for aid in (old,e1)}
    from .scheduled_service import binding
    walls=[]
    for aid in (old,e1):
        data=saved[aid];start=data['start.json'];finish=data['finish/record.json'];cfg=data['config.json'];auth=data['authority.json']
        require(all(type(x) is dict for x in (start,finish,cfg)),'RAW_E2_PRIOR_METADATA')
        require(start.get('attempt_id')==finish.get('attempt_id')==aid and start.get('status')=='FIRST_START_CONSERVATIVE_DEBIT' and
                finish.get('status')=='FAILED_UNFINALIZED' and finish.get('refund') is False and finish.get('automatic_retry') is False and
                not finish.get('semantic_id') and not finish.get('private_results') and not finish.get('results'), 'RAW_E2_PRIOR_STATUS')
        require(same(start.get('binding'),binding(cfg)) and same(science_binding(cfg),science_binding(config)), 'RAW_E2_UNCHANGED_SCIENCE')
        expected='ORIGINAL' if aid==old else E1_ACTION
        require((aid==old and cfg.get('namespace')=='INVENTED' and auth is None) or
                (type(auth) is dict and auth.get('action')==expected and
                 all(same(auth.get(k),authority.get(k)) for k in ('method_ref','candidate_ref'))), 'RAW_E2_SAME_METHOD_CARD')
        require(type(start.get('started_ns')) is int and type(finish.get('finished_ns')) is int and
                0<finish['finished_ns']-start['started_ns'],'RAW_E2_PRIOR_CLOCK')
        walls.append(finish['finished_ns']-start['started_ns'])
    os=saved[old]['start.json'];of=saved[old]['finish/record.json'];es=saved[e1]['start.json'];ef=saved[e1]['finish/record.json']
    require(of['finished_ns']<=es['started_ns'] and sum(walls)<=v['prior_charged_work_ns'],'RAW_E2_PRIOR_CHARGE')
    require(of.get('error')=='RAW_CONTENT_EVENT_ID' and type(of.get('completed_native_accounts')) is int and
            of['completed_native_accounts']==0 and type(of.get('native_run_entries_in_failed_phase')) is int and
            of['native_run_entries_in_failed_phase']==0 and saved[old]['finish/diagnostics.json']==[], 'RAW_E2_ORIGINAL_STATUS')
    require(ef.get('error')=='NATIVE_WALL_TIMEOUT' and type(ef.get('completed_native_accounts')) is int and
            ef['completed_native_accounts']==3 and type(ef.get('native_run_entries_in_failed_phase')) is int and
            ef['native_run_entries_in_failed_phase']==4 and same(ef.get('completed_verified_lifecycle_counts'),{'recognize':0,'pay':0}) and
            ef.get('cumulative_lifecycle_counts') is None, 'RAW_E2_E1_PARTIAL_STATUS')
    lineage=es.get('corrective_lineage')
    require(type(lineage) is dict and same(lineage,ef.get('corrective_lineage')) and lineage.get('action')==E1_ACTION and
            lineage.get('family')==family and lineage.get('prior_attempt_id')==old and
            same(lineage.get('prior_members'),v['prior_members'][old]) and type(lineage.get('family_start_count')) is int and
            lineage['family_start_count']==2 and lineage.get('old_stored_allocation')=='INELIGIBLE_NOT_RECYCLED', 'RAW_E2_E1_LINK')
    # Only bounded native checkpoint metadata is required, not private tapes or amounts.
    from .raw_action_native import LEGS
    checkpoints=saved[e1]['finish/diagnostics.json'];expected=[]
    for j,leg in enumerate(LEGS):
        expected.append(('NATIVE_RUN_ENTERED',leg))
        if j<3:expected.append(('ACCOUNT_COMPLETED',leg))
    require(type(checkpoints) is list and len(checkpoints)==7 and
            all(type(x) is dict and set(x)<= {'phase','id','nav_points','fills'} for x in checkpoints) and
            [(x.get('phase'),x.get('id')) for x in checkpoints]==expected and
            all(type(x.get('nav_points')) is int and x['nav_points']==2728 and type(x.get('fills')) is int and x['fills']>=0
                for x in checkpoints if x['phase']=='ACCOUNT_COMPLETED'), 'RAW_E2_E1_CHECKPOINTS')
    return {'schema':'polar.raw-action-corrective-lineage/2','action':ACTION,'family':family,
        'prior_attempt_ids':[old,e1],'prior_members':v['prior_members'],'amendment_sha256':sha(canonical(v)),
        'family_start_count':3,'prior_completed_native_accounts':3,'prior_recorded_native_entries':4,
        'prior_lifecycle_counts':'UNAVAILABLE_OLD_NOT_EMITTED_E1_VERIFIED_ZERO_NOT_ACTIVITY_ZERO',
        'allowed_ex_recognitions':v['allowed_ex_recognitions'],'allowed_payments':v['allowed_payments'],
        'prior_charged_work_ns':v['prior_charged_work_ns'],'allowed_e2_work_ns':v['allowed_e2_work_ns'],
        'total_work_budget_ns':v['total_work_budget_ns'],'old_stored_allocations':'BOTH_INELIGIBLE_NOT_RECYCLED',
        'exposure':'SOURCE_AND_PARTIAL_NATIVE_NOT_PRISTINE_OR_INDEPENDENT_CONFIRMATION',
        'historical_exclusive_timeout_cause':'UNKNOWN'}


def account_finish(finish,lineage,started_ns,completed_phases):
    e1_account(finish,lineage,started_ns)
    finish['native_run_entries_in_completed_phases']=completed_phases
    finish.setdefault('native_run_entries_in_failed_phase',0)
    finish['cumulative_recorded_native_entries']=4+completed_phases+finish['native_run_entries_in_failed_phase']
    finish['cumulative_lifecycle_reason']='UNAVAILABLE_OLD_NOT_EMITTED_AND_PRIOR_PARTIAL_VERIFICATION_NOT_ACTIVITY_CENSUS'
