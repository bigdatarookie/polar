"""Selected PPO family in the existing store, with immutable per-fit checkpoints."""
import time
import uuid
from decimal import Decimal
from .ci_research import require
from .gym_contract import canonical,sha,decode
from .history_bundle import read_file
from .reference_ppo import fit_select_test,LEGS
from .reference_projection import public_reference
from .reference_evaluation import evaluate_reference


def run_ppo(service,config,market,calendar,tz,authority):
    from .reference_service import binding,portable
    partitions={p['partition']:p for p in calendar['partitions']}
    family=sha(canonical({'profile':config['profile_id'],'input':config['input_ref']['sha256'],'namespace':config['namespace']}))
    parent='reference-research-attempts/'+family;aid=str(uuid.uuid4());directory=service.store.root/parent
    with service.store.locked():
        prior=sorted(p.name for p in directory.iterdir()) if directory.exists() else []
        require(not directory.is_symlink() and not prior,'REFERENCE_ORIGINAL_ALREADY_RECORDED')
        if authority is not None:require(authority.get('expected_prior_attempts')==prior,'REFERENCE_ATTEMPT_HISTORY')
        service.store._publish(parent,aid,{'start.json':canonical({'schema':'polar.reference-start/1','attempt_id':aid,
            'binding':binding(config),'status':'INTENT_CONSERVATIVE_DEBIT','actual_fit_state':'UNKNOWN_UNTIL_MATCHED_MODELS',
            'started_ns':time.time_ns()}),'config.json':canonical(config),'authority.json':canonical(authority)})
    files={};fit_ids=[]
    def persist(name,value):
        raw=value if type(value) is bytes else canonical(portable(value))
        require(len(raw)<=32*1024**2,'PPO_CHECKPOINT_SIZE')
        key='checkpoint-'+sha(name.encode())
        with service.store.locked():service.store._publish(parent+'/'+aid+'/checkpoints',key,{'member-name.txt':name.encode(),'content':raw},file_limit=32*1024**2)
        files[name]=raw
        if name.endswith('/model.zip'):fit_ids.append(name.split('/')[0])
    try:
        result=fit_select_test(market,partitions,tz,persist,
            invented_steps=calendar['invented_train_steps'] if config['namespace']=='INVENTED' else None)
        files['bindings.json']=canonical(binding(config))
        manifest={'schema':'polar.reference-ppo-semantic-manifest/1','files':{n:{'sha256':sha(b),'bytes':len(b)} for n,b in files.items()}}
        raw=canonical(manifest);sid='reference-experiment-'+sha(raw)
        with service.store.locked():service.store._publish('reference-research-experiments',sid,{**files,'manifest.json':raw},file_limit=32*1024**2)
        publications={}
        if result['status']=='SUCCESS':
            selected=result['selection']['selected_seed'];modelhash=sha(files[f'seed-{selected}/model.zip'])
            public=public_config(config,modelhash,selected)
            record=public_reference(public,result['simulation'],result['evaluation'],semantic_id=sid,semantic_hash=sha(raw),phase='FINAL')
            publications['FINAL']=service.results.publish(record)
        finish={'status':result['status'],'attempt_id':aid,'semantic_id':sid,'results':publications,
            'fit_calls':len(fit_ids),'fit_ids':fit_ids,'development_runs':3,'selected_seed':result['selection']['selected_seed'],
            'native_accounts':5 if result['status']=='SUCCESS' else 0,'financial_acceptance':'NOT_REVIEWED',
            'actual_fit_state':'COMPLETED_MATCHED_MODELS','finished_ns':time.time_ns()}
    except BaseException as exc:
        finish={'status':'FAILED_UNFINALIZED','attempt_id':aid,'error':str(exc)[:240],'completed_fit_ids':fit_ids,
            'actual_fit_state':'PARTIAL_MATCHED_MODELS_OR_UNKNOWN','refund':False,'automatic_retry':False,'finished_ns':time.time_ns()}
        with service.store.locked():service.store._publish(parent+'/'+aid,'finish',{'record.json':canonical(finish)})
        raise
    with service.store.locked():service.store._publish(parent+'/'+aid,'finish',{'record.json':canonical(finish)})
    return finish


def public_config(config,modelhash,selected):
    return {'protocol_id':config['profile_id'],'primary_strategy':LEGS[0],'primary_benchmark':LEGS[1],
        'question_label':'Bounded chronological PPO reference-unit allocation',
        'question_summary':'Three fixed training seeds, frozen development selection, one selected final test versus initial equal weight and fixed controls.',
        'bindings':{'protocol_id':config['profile_id'],'protocol_sha256':config['protocol_ref']['sha256'],
            'data_revision':'selected-'+config['input_ref']['sha256'],'data_sha256':config['input_ref']['sha256'],
            'code_revision':config['code_revision'],'evaluator_revision':config['code_revision'],'runtime_id':config['runtime_image_id'],
            'producer_id':'polar-reference-ppo','candidate_id':config['candidate_id'],'experiment_id':config['experiment_id']},
        'clock_description':'B models 16:00 New York closes even on early sessions; K next civil midnight and D one second later; next modeled close execution.',
        'partition_description':'Three fixed TRAIN policies on 2016-2020; deterministic 2021-2022 development selects maximum canonical Sharpe with lower-seed ties; selected seed '+str(selected)+' alone tested on 2023-2026. No refit. TRAIN discounted log reward differs from final wealth, Sharpe and drawdown criteria.',
        'provenance':[{'role':'trained_policy','id':'policy-'+modelhash,'sha256':modelhash},
            {'role':'reference_input','id':'source-projection','sha256':config['input_ref']['sha256']},
            {'role':'calendar_contract','id':'calendar-contract','sha256':config['calendar_ref']['sha256']}],
        'evidence_level':'RETAINED_DESCRIPTIVE' if config['namespace']=='RETAINED' else 'INVENTED_CONTROL'}


def recompute_ppo(files):
    from .reference_ppo import select_development
    from .ci_research_evaluation import evaluate_legs
    candidates=[]
    for seed in (0,1,2):
        dev=decode(files[f'seed-{seed}/development.json']);episode=dev['episode']
        metrics,_=evaluate_legs({'legs':[{'id':LEGS[0],'nav':episode['nav'],'fills':episode['fills']}]})
        require(canonical(metrics[0]['metrics'])==canonical(dev['metrics']),'PPO_DEVELOPMENT_RECOMPUTE')
        candidates.append({'seed':seed,'metrics':metrics[0]['metrics']})
        training=decode(files[f'seed-{seed}/training.json'])
        rows=[]
        for roll in range(training['actual_rollouts']):rows.extend(decode(files[f'seed-{seed}/rollout-{roll:03d}.json']))
        require(len(rows)==training['actual_timesteps'] and all(r['index']==i and not r['truncated'] for i,r in enumerate(rows)), 'PPO_STORED_BUDGET')
        require(training['actual_epoch_updates']==training['actual_rollouts']*10 and training['actual_optimizer_steps']==training['actual_rollouts']*40,'PPO_STORED_UPDATES')
    selection=decode(files['selection.json']);selected=select_development(candidates)
    require(selection['selected_seed']==selected and canonical(selection['candidates'])==canonical(candidates),'PPO_SELECTION_RECOMPUTE')
    if selected is not None:
        from .reference_ppo import reconcile_selected
        final=decode(files['final.json']);reconcile_selected(final['episode'],final['simulation'])
        evaluation=evaluate_reference(final['simulation'],kind='PPO',strategy=LEGS[0],benchmark=LEGS[1])
        require(canonical(evaluation)==canonical(final['evaluation']),'PPO_FINAL_RECOMPUTE')
    return {'status':'REPRODUCED','selected_seed':selected,'model_calls':0,'native_calls':0,'store_writes':0}
