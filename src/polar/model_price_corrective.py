"""Closed profile10 E1 admission; old exposed outcome graph stays immutable."""
import re
from .ci_research import require
from .gym_contract import canonical,sha,decode,read_ref
from .history_bundle import read_file
from .scheduled_corrective import science_binding,read_prior_members,MEMBERS

ACTION='CORRECTIVE_MODEL_PRICE_E1'
PHASES={'phases/FINAL/phase.json','phases/FINAL/diagnostics.json'}
SEMANTIC={'profile.json','calendar.json','phases.json','diagnostics.json','bindings.json'}


def pinned(service,path,pin):
    require(type(pin) is dict and set(pin)=={'sha256','bytes'} and type(pin['bytes']) is int and
            0<pin['bytes']<=32*1024**2 and type(pin['sha256']) is str and
            re.fullmatch('[a-f0-9]{64}',pin['sha256']), 'MODEL_E1_PIN')
    raw=read_file(service.store.root,path,32*1024**2)
    require(len(raw)==pin['bytes'] and sha(raw)==pin['sha256'],'MODEL_E1_INTEGRITY')
    return raw


def admit_locked(service,config,profile,authority,parent,family,prior):
    from .scheduled_service import binding
    require(profile['schema']=='polar.scheduled-reference-profile/10' and
            authority.get('action')==ACTION,'MODEL_E1_PROFILE_ACTION')
    v=decode(read_ref(authority['corrective_amendment_ref']))
    fields={'schema','status','action','family','candidate_id','experiment_id','prior_attempt_id','prior_members',
        'prior_semantic_id','prior_semantic_members','science_binding_sha256','current_binding_sha256',
        'prior_audit_ref','custody_ref','invariants_ref','applicability_ref','charge_history_ref','owner_id',
        'maximum_family_starts','allowed_native_accounts','prior_charged_work_ns','allowed_e1_work_ns','total_work_budget_ns'}
    require(type(v) is dict and set(v)==fields and v['schema']=='polar.model-price-corrective-amendment/1' and
            v['status']=='BOUND_FOR_EXECUTION' and v['action']==ACTION,'MODEL_E1_AMENDMENT')
    old=v['prior_attempt_id'];sid=v['prior_semantic_id']
    require(type(old) is str and re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',old) and
            type(sid) is str and re.fullmatch('scheduled-reference-experiment-[a-f0-9]{64}',sid) and
            v['family']==family and v['candidate_id']==config['candidate_id'] and v['experiment_id']==config['experiment_id'] and
            type(v['owner_id']) is str and 0<len(v['owner_id'])<=100,'MODEL_E1_IDENTITY')
    require(prior==[old] and authority.get('expected_prior_attempts')==prior,'MODEL_E1_PRIOR_HISTORY')
    require(v['science_binding_sha256']==sha(canonical(science_binding(config))) and
            v['current_binding_sha256']==sha(canonical(binding(config))),'MODEL_E1_BINDING')
    require(type(v['maximum_family_starts']) is int and v['maximum_family_starts']==2 and
            type(v['allowed_native_accounts']) is int and v['allowed_native_accounts']==len(profile['legs'])==5 and
            all(type(authority.get(k)) is int and authority[k]==0 for k in ('allowed_fit_calls','allowed_predict_calls',
                'allowed_score_calls','allowed_rank_calls','allowed_estimator_calls','allowed_optimizer_calls','allowed_bootstrap_samples')),
            'MODEL_E1_ALLOWANCE')
    require(all(type(v[k]) is int for k in ('prior_charged_work_ns','allowed_e1_work_ns','total_work_budget_ns')) and
            0<v['prior_charged_work_ns']<v['total_work_budget_ns'] and
            0<v['allowed_e1_work_ns']<=v['total_work_budget_ns']-v['prior_charged_work_ns'],'MODEL_E1_WORK')
    for key in ('prior_audit_ref','custody_ref','invariants_ref','charge_history_ref'):read_ref(v[key])
    a=decode(read_ref(v['applicability_ref']))
    require(type(a) is dict and a.get('schema')=='polar.validator-financial-repeat-applicability/1' and
            a.get('scientific_scope_status')=='PASS_BOUNDED_PROSPECTIVE_APPLICABILITY' and
            a.get('disposition')=='APPLICABLE_SAME_FROZEN_CHOICE_E1_WITH_FULL_OUTCOME_EXPOSURE' and
            a.get('candidate_id')==config['candidate_id'] and a.get('experiment_registration_id')==config['experiment_id'] and
            a.get('family')==family and a.get('old_semantic')==sid and
            a.get('additive_accounting',{}).get('old_attempt')==old and
            a.get('unmet_prospective_scientific_choice_predicates')==[], 'MODEL_E1_APPLICABILITY')
    pins=v['prior_members']
    require(type(pins) is dict and set(pins)==MEMBERS|PHASES,'MODEL_E1_PRIOR_MEMBERS')
    saved=read_prior_members(service,parent,old,{k:pins[k] for k in MEMBERS})
    # Prior economic payloads are only hashed/byte-joined, never decoded here.
    opaque={k:pinned(service,parent+'/'+old+'/'+k,pins[k]) for k in PHASES}
    start=saved['start.json'];finish=saved['finish/record.json'];oldcfg=saved['config.json'];oldauth=saved['authority.json']
    require(type(start) is dict and type(finish) is dict and type(oldcfg) is dict,'MODEL_E1_PRIOR_METADATA_TYPES')
    require(start.get('attempt_id')==finish.get('attempt_id')==old and start.get('status')=='FIRST_START_CONSERVATIVE_DEBIT' and
            finish.get('status')=='FAILED_UNFINALIZED' and finish.get('error')=='RESEARCH_INVALID_RESULT' and
            finish.get('refund') is False and finish.get('automatic_retry') is False and
            type(finish.get('completed_native_accounts')) is int and finish['completed_native_accounts']==5 and
            not finish.get('semantic_id') and not finish.get('results') and saved['finish/diagnostics.json']==[], 'MODEL_E1_PRIOR_STATUS')
    require(canonical(start.get('binding'))==canonical(binding(oldcfg)) and
            canonical(science_binding(oldcfg))==canonical(science_binding(config)), 'MODEL_E1_UNCHANGED_SCIENCE')
    require((oldcfg['namespace']=='INVENTED' and oldauth is None) or
            (type(oldauth) is dict and oldauth.get('action')=='ORIGINAL' and
             all(canonical(oldauth.get(k))==canonical(authority.get(k)) for k in ('method_ref','candidate_ref'))),'MODEL_E1_OLD_METHOD_CARD')
    require(type(start.get('started_ns')) is int and type(finish.get('finished_ns')) is int and
            0<finish['finished_ns']-start['started_ns']<=v['prior_charged_work_ns'],'MODEL_E1_PRIOR_WORK')
    sp=v['prior_semantic_members']
    require(type(sp) is dict and set(sp)==SEMANTIC|{'manifest.json'},'MODEL_E1_SEMANTIC_MEMBERS')
    raw={k:pinned(service,'reference-research-experiments/'+sid+'/'+k,sp[k]) for k in sp}
    manifest=decode(raw['manifest.json'])
    require(sid=='scheduled-reference-experiment-'+sha(raw['manifest.json']) and
            type(manifest) is dict and manifest.get('schema')=='polar.scheduled-reference-semantic-manifest/1' and
            canonical(manifest.get('files'))==canonical({k:sp[k] for k in SEMANTIC}), 'MODEL_E1_SEMANTIC_MANIFEST')
    require(raw['profile.json']==canonical(profile) and raw['bindings.json']==canonical(binding(oldcfg)) and
            raw['phases.json']==b'{"FINAL":'+opaque['phases/FINAL/phase.json'].rstrip(b'\n')+b'}\n' and
            raw['diagnostics.json']==b'{"FINAL":'+opaque['phases/FINAL/diagnostics.json'].rstrip(b'\n')+b'}\n',
            'MODEL_E1_SEMANTIC_JOIN')
    return {'schema':'polar.model-price-corrective-lineage/1','action':ACTION,'family':family,
        'prior_attempt_id':old,'prior_members':pins,'prior_semantic_id':sid,'prior_semantic_members':sp,
        'amendment_sha256':sha(canonical(v)),'family_start_count':2,'prior_completed_native_accounts':5,
        'prior_charged_work_ns':v['prior_charged_work_ns'],'allowed_e1_work_ns':v['allowed_e1_work_ns'],
        'total_work_budget_ns':v['total_work_budget_ns'],'prior_optional_counters':'NOT_EMITTED_NOT_INFERRED_ZERO',
        'exposure':'ALL_FIVE_OLD_OUTCOMES_EXPOSED_NOT_INDEPENDENT_CONFIRMATION',
        'old_missing_witnesses':'UNAVAILABLE_NOT_BACKFILLED','old_stored_allocation':'INELIGIBLE_NOT_RECYCLED'}


def account_finish(finish,lineage,started_ns):
    if not lineage or lineage.get('action')!=ACTION:return
    finish['corrective_lineage']=lineage
    finish['cumulative_completed_native_accounts']=5+finish.get('completed_native_accounts',finish.get('native_accounts',0))
    finish['prior_optional_counters']='NOT_EMITTED_NOT_INFERRED_ZERO'
    finish['recorded_work_wall_ns']=max(0,finish['finished_ns']-started_ns)
    finish['cumulative_charged_work_ns']=lineage['prior_charged_work_ns']+finish['recorded_work_wall_ns']
    finish['work_budget_exceeded']=finish['cumulative_charged_work_ns']>lineage['total_work_budget_ns']
