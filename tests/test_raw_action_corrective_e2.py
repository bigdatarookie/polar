"""Invented E2 admission; injected checkpoint metadata is not a retained run."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import pytest
from test_raw_action_corrective import setup as setup_e1,bind as bind_e1
from test_raw_action_service import write
from test_scheduled_service import snapshot
from polar.gym_contract import canonical,sha
from polar.ci_research_service import NativeFailure
from polar.scheduled_service import binding
from polar.scheduled_corrective import science_binding,MEMBERS
from polar.raw_action_corrective_e2 import ACTION


def setup(tmp_path,monkeypatch):
    root,cfg,p,d,svc,old,e1a,e1g=setup_e1(tmp_path,monkeypatch)
    import polar.raw_action_service as module
    from polar.raw_action_native import LEGS
    checkpoints=[]
    for j,leg in enumerate(LEGS):
        checkpoints.append({'phase':'NATIVE_RUN_ENTERED','id':leg})
        if j<3:checkpoints.append({'phase':'ACCOUNT_COMPLETED','id':leg,'nav_points':2728,'fills':j+1})
    with monkeypatch.context() as m:
        def injected(*args):raise NativeFailure('NATIVE_WALL_TIMEOUT',checkpoints)
        m.setattr(module,'bounded_native',injected)
        with pytest.raises(NativeFailure):svc.run(bind_e1(tmp_path,cfg,e1a,e1g))
    e1=next(x.parent for x in root.rglob('start.json') if x.parent!=old)
    pins={x.name:{name:{'sha256':sha((x/name).read_bytes()),'bytes':(x/name).stat().st_size} for name in MEMBERS} for x in (old,e1)}
    meta=e1a['custody_ref']
    app=write(tmp_path/'INVENTED-E2-applicability.json',{'schema':'polar.validator-financial-repeat-applicability/1',
        'disposition':'APPLICABLE_SAME_FROZEN_CHOICE_TECHNICAL_RECHECK_E2_WITH_PARTIAL_NATIVE_EXPOSURE',
        'scientific_scope_status':'PASS_BOUNDED_PROSPECTIVE_APPLICABILITY','candidate_id':cfg['candidate_id'],
        'experiment_registration_id':cfg['experiment_id'],'family':old.parent.name,'unmet_prospective_scientific_choice_predicates':[]})
    a={'schema':'polar.raw-action-corrective-amendment/2','status':'BOUND_FOR_EXECUTION','action':ACTION,'family':old.parent.name,
        'candidate_id':cfg['candidate_id'],'experiment_id':cfg['experiment_id'],'original_attempt_id':old.name,'e1_attempt_id':e1.name,
        'prior_members':pins,'science_binding_sha256':sha(canonical(science_binding(cfg))),'current_binding_sha256':sha(canonical(binding(cfg))),
        'prior_audit_refs':{old.name:meta,e1.name:meta},'custody_ref':meta,'invariants_ref':meta,'applicability_ref':app,
        'charge_history_ref':meta,'owner_id':'INVENTED-owner','maximum_family_starts':3,'allowed_ex_recognitions':8*len(d['event_dates']),
        'allowed_payments':8*len(d['event_dates']),'allowed_native_accounts':8,'total_work_budget_ns':1200*10**9,
        'prior_charged_work_ns':323*10**9,'allowed_e2_work_ns':360*10**9}
    g={**e1g,'action':ACTION,'expected_prior_attempts':sorted([old.name,e1.name])}
    return root,cfg,p,d,svc,old,e1,a,g


def bind(tmp_path,cfg,a,g):
    ref=write(tmp_path/'INVENTED-E2-amendment.json',a)
    return {**cfg,'execution_authority_ref':write(tmp_path/'INVENTED-E2-authority.json',{**g,'corrective_amendment_ref':ref})}


def mutate_prior(path,a,key,value):
    f=path/key;data=json.loads(f.read_bytes());data.update(value);f.chmod(0o600);f.write_bytes(canonical(data))
    a['prior_members'][path.name][key]={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size}


@pytest.mark.parametrize('mutation',['missing','tamper','success','wrong_error','entries','completions','lineage','science','method',
    'work','bool','retry','wrongprior','applicability','diagnostic','allowance'])
def test_bad_two_prior_admission_rejects_before_third_debit_or_values(tmp_path,monkeypatch,mutation):
    root,cfg,p,d,svc,old,e1,a,g=setup(tmp_path,monkeypatch)
    if mutation=='missing':del a['prior_members'][e1.name]['finish/record.json']
    if mutation=='tamper':a['prior_members'][e1.name]['finish/record.json']['sha256']='0'*64
    if mutation in ('success','wrong_error','entries','completions','lineage'):
        field={'success':'status','wrong_error':'error','entries':'native_run_entries_in_failed_phase','completions':'completed_native_accounts','lineage':'corrective_lineage'}[mutation]
        value={'success':'SUCCESS','wrong_error':'OTHER','entries':3,'completions':4,'lineage':{}}[mutation]
        mutate_prior(e1,a,'finish/record.json',{field:value})
    if mutation=='science':
        mutate_prior(e1,a,'config.json',{'experiment_id':'INVENTED-DIFFERENT'})
    if mutation=='method':mutate_prior(e1,a,'authority.json',{'method_ref':a['custody_ref']})
    if mutation=='work':a['prior_charged_work_ns']=322*10**9
    if mutation=='bool':g['allowed_score_calls']=False
    if mutation=='retry':a['retry']=True
    if mutation=='wrongprior':g['expected_prior_attempts']=[old.name]
    if mutation=='applicability':a['applicability_ref']=a['custody_ref']
    if mutation=='allowance':a['maximum_family_starts']=4
    if mutation=='diagnostic':
        f=e1/'finish/diagnostics.json';data=json.loads(f.read_bytes());data[-1]['id']='INVENTED-DIFFERENT';f.chmod(0o600);f.write_bytes(canonical(data));a['prior_members'][e1.name]['finish/diagnostics.json']={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size}
    import polar.raw_action_service as module
    monkeypatch.setattr(module,'load',lambda *a:(_ for _ in ()).throw(AssertionError('VALUES_BEFORE_LINKED_ADMISSION')))
    with pytest.raises(Exception) as exc:svc.run(bind(tmp_path,cfg,a,g))
    assert not isinstance(exc.value,AssertionError)
    assert len(list(root.rglob('start.json')))==2


def test_one_additive_failure_concurrent_no_fourth_or_old_mutation(tmp_path,monkeypatch):
    root,cfg,p,d,svc,old,e1,a,g=setup(tmp_path,monkeypatch);before=[snapshot(x) for x in (old,e1)]
    current=bind(tmp_path,cfg,a,g)
    import polar.raw_action_service as module
    def fail(*args):raise ValueError('INVENTED_E2_PARTIAL')
    monkeypatch.setattr(module,'load',fail)
    with pytest.raises(ValueError,match='RAW_ORIGINAL_ALREADY_RECORDED'):svc.run(cfg)
    def one(_):
        try:svc.run(current)
        except Exception as e:return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:errors=list(pool.map(one,range(2)))
    assert sorted(errors)==['INVENTED_E2_PARTIAL','RAW_E2_PRIOR_HISTORY']
    new=next(json.loads(f.read_bytes()) for f in root.rglob('finish/record.json') if f.parent.parent not in (old,e1))
    assert new['corrective_lineage']['family_start_count']==3 and new['cumulative_completed_native_accounts']==3
    assert new['cumulative_recorded_native_entries']==4 and new['cumulative_lifecycle_counts'] is None
    assert new['completed_verified_lifecycle_counts']=={'recognize':0,'pay':0} and new['refund'] is new['automatic_retry'] is False
    assert [snapshot(x) for x in (old,e1)]==before and len(list(root.rglob('start.json')))==3


def test_e2_invented_complete_private_and_source_absent_saved(tmp_path,monkeypatch):
    root,cfg,p,d,svc,old,e1,a,g=setup(tmp_path,monkeypatch);before=[snapshot(x) for x in (old,e1)]
    result=svc.run(bind(tmp_path,cfg,a,g))
    assert result['status']=='SUCCESS' and result['native_accounts']==8
    assert result['cumulative_completed_native_accounts']==11 and result['cumulative_recorded_native_entries']==12
    assert result['cumulative_lifecycle_counts'] is None
    assert result['completed_verified_lifecycle_counts']=={'recognize':8*len(d['event_dates']),'pay':8*len(d['event_dates'])}
    assert [snapshot(x) for x in (old,e1)]==before and len(list(root.rglob('start.json')))==3
    snap=snapshot(root)
    import polar.raw_action_service as module
    for name in ('load','bounded_native'):
        monkeypatch.setattr(module,name,lambda *a:(_ for _ in ()).throw(AssertionError('SAVED_SOURCE_OR_NATIVE')))
    for f in tmp_path.iterdir():
        if f.is_file():f.unlink()
    replay=svc.recompute(result['semantic_id'])
    assert replay['native_calls']==replay['store_writes']==0 and snapshot(root)==snap


def test_composed_actions_do_not_admit_the_other_profile(tmp_path,monkeypatch):
    from polar.scheduled_service import authority_for
    root,cfg,p,d,svc,old,e1,a,g=setup(tmp_path,monkeypatch)
    wrong={**g,'action':'CORRECTIVE_MODEL_PRICE_E1'}
    bad={**cfg,'execution_authority_ref':write(tmp_path/'INVENTED-wrong-model-action.json',wrong)}
    with pytest.raises(ValueError,match='SCHEDULED_OPERATION_NOT_BOUND'):authority_for(svc,bad,p,{'FINAL':{}})
    from test_scheduled_model_price import model_fixture
    home=tmp_path/'INVENTED-model';home.mkdir()
    _,model_cfg,model,_=model_fixture(home,monkeypatch)
    bad={**model_cfg,'execution_authority_ref':write(home/'INVENTED-wrong-raw-action.json',{**g,'binding_sha256':sha(canonical(binding(model_cfg)))})}
    with pytest.raises(ValueError,match='SCHEDULED_OPERATION_NOT_BOUND'):authority_for(svc,bad,model,{'FINAL':{}})
    assert len(list(root.rglob('start.json')))==2
