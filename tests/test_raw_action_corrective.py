"""Invented B7 E1 admission only; no retained graph or operative grant."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import pytest
from test_raw_action_service import fixture,write
from test_scheduled_service import snapshot
from polar.gym_contract import canonical,sha
from polar.reference_service import ReferenceResearchService
from polar.raw_action_corrective import ACTION,amendment
from polar.scheduled_corrective import science_binding,MEMBERS
from polar.scheduled_service import binding


def setup(tmp_path,monkeypatch):
    root,cfg,d,cal=fixture(tmp_path);service=ReferenceResearchService(root,256*1024**2)
    import polar.raw_action_service as module
    with monkeypatch.context() as m:
        def bad(*a):raise ValueError('RAW_CONTENT_EVENT_ID')
        m.setattr(module,'load',bad)
        with pytest.raises(ValueError,match='RAW_CONTENT_EVENT_ID'):service.run(cfg)
    old=next(root.rglob('finish/record.json')).parent.parent;family=old.parent.name
    pins={name:{'sha256':sha((old/name).read_bytes()),'bytes':(old/name).stat().st_size} for name in MEMBERS}
    p=json.loads(Path(cfg['profile_ref']['path']).read_bytes())
    meta=write(tmp_path/'INVENTED-custody-audit.json',{'scope':'INVENTED metadata only'})
    method=write(tmp_path/'INVENTED-method.json',{'schema':'polar.prospective-method-disposition/1','method_verdict':'PASS','protocol':{'sha256':cfg['protocol_ref']['sha256']},'candidate_id':cfg['candidate_id']})
    card=write(tmp_path/'INVENTED-card.json',{'schema':'polar.native-hypothesis-reservation/1','state':'RESERVED','candidate_id':cfg['candidate_id'],'experiment_registration_id':cfg['experiment_id']})
    qualification=write(tmp_path/'INVENTED-qualification.json',{'schema':'polar.ci-result/1','status':'PASS','candidate_sha':cfg['code_revision'],'selection':['tests']})
    report=write(tmp_path/'INVENTED-review-report.json',{'scope':'INVENTED controls, not actual independent qualification'})
    review=write(tmp_path/'INVENTED-review.json',{'schema':'polar.raw-action-technical-review/1','status':'PASS','candidate_sha':cfg['code_revision'],'protocol_sha256':cfg['protocol_ref']['sha256'],'input_sha256':cfg['input_ref']['sha256'],'reviewer':'INVENTED-NONAUTHOR','report_ref':report})
    a={'schema':'polar.raw-action-corrective-amendment/1','status':'BOUND_FOR_EXECUTION','action':ACTION,
       'family':family,'candidate_id':cfg['candidate_id'],'experiment_id':cfg['experiment_id'],'prior_attempt_id':old.name,
       'prior_members':pins,'science_binding_sha256':sha(canonical(science_binding(cfg))),
       'current_binding_sha256':sha(canonical(binding(cfg))),'prior_audit_ref':meta,'custody_ref':meta,'invariants_ref':meta,
       'owner_id':'INVENTED-OWNER','maximum_family_starts':2,'allowed_native_accounts':8,
       'allowed_ex_recognitions':24,'allowed_payments':24,'total_work_budget_ns':1200*10**9,
       'prior_charged_work_ns':10**9,'allowed_e1_work_ns':1199*10**9}
    g={'schema':'polar.scheduled-reference-operation/1','action':ACTION,'binding_sha256':sha(canonical(binding(cfg))),
       **{k:0 for k in ('allowed_fit_calls','allowed_predict_calls','allowed_score_calls','allowed_rank_calls','allowed_estimator_calls','allowed_optimizer_calls','allowed_bootstrap_samples')},
       'allowed_native_accounts':8,'expected_prior_attempts':[old.name],'method_ref':method,'candidate_ref':card,'qualification_ref':qualification,'independent_review_ref':review}
    return root,cfg,p,d,service,old,a,g


def bind(tmp_path,cfg,a,g):
    pin=write(tmp_path/'INVENTED-amendment.json',a)
    return {**cfg,'execution_authority_ref':write(tmp_path/'INVENTED-E1-authority.json',{**g,'corrective_amendment_ref':pin})}


def test_failed_e1_keeps_original_immutable_and_cannot_start_third(tmp_path,monkeypatch):
    root,cfg,p,d,service,old,a,g=setup(tmp_path,monkeypatch);before=snapshot(old)
    with pytest.raises(ValueError,match='RAW_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)
    current=bind(tmp_path,cfg,a,g)
    import polar.raw_action_service as module
    def fail(*args):
        assert len(list(root.rglob('start.json')))==2
        raise ValueError('INVENTED_E1_FAILURE')
    monkeypatch.setattr(module,'load',fail)
    with pytest.raises(ValueError,match='INVENTED_E1_FAILURE'):service.run(current)
    new=next(json.loads(f.read_bytes()) for f in root.rglob('finish/record.json') if f.parent.parent!=old)
    assert new['refund'] is new['automatic_retry'] is False and new['status']=='FAILED_UNFINALIZED'
    assert new['corrective_lineage']['family_start_count']==2
    assert new['corrective_lineage']['prior_lifecycle_counts']=='NOT_EMITTED_NOT_INFERRED_ZERO'
    assert new['cumulative_lifecycle_counts'] is None and new['cumulative_completed_native_accounts']==0
    assert new['completed_verified_lifecycle_counts']=={'recognize':0,'pay':0} and snapshot(old)==before
    with pytest.raises(ValueError,match='RAW_CORRECTIVE_PRIOR_HISTORY'):service.run(current)
    assert len(list(root.rglob('start.json')))==2


def test_success_native_private_lifecycle_counts_and_saved_reproduction(tmp_path,monkeypatch):
    root,cfg,p,d,service,old,a,g=setup(tmp_path,monkeypatch);before=snapshot(old);current=bind(tmp_path,cfg,a,g)
    result=service.run(current)
    assert result['status']=='SUCCESS' and result['native_accounts']==8
    assert result['completed_verified_lifecycle_counts']=={'recognize':24,'pay':24}
    assert result['cumulative_lifecycle_counts'] is None and result['cumulative_completed_native_accounts']==8
    assert result['cumulative_charged_work_ns']>=10**9 and result['work_budget_exceeded'] is False
    assert snapshot(old)==before and not (root/'research-results').exists()
    state=snapshot(root)
    import polar.raw_action_service as module
    def no(*a,**k):raise AssertionError('SAVED_SOURCE_OR_NATIVE')
    monkeypatch.setattr(module,'load',no);monkeypatch.setattr(module,'bounded_native',no)
    stored=service.recompute(result['semantic_id'])
    assert stored['status']=='REPRODUCED' and stored['native_calls']==stored['source_calls']==stored['store_writes']==0
    assert snapshot(root)==state
    with pytest.raises(ValueError,match='RAW_CORRECTIVE_PRIOR_HISTORY'):service.run(current)


@pytest.mark.parametrize('mutation',['missing_pin','bad_pin','old_success','old_error','old_native','old_diagnostic','old_method','old_card','science','work','family','prior','status','allowance','bool_zero','missing_review','audit_pin','unknown_field','b8_action'])
def test_invalid_metadata_never_debits_or_loads_values(tmp_path,monkeypatch,mutation):
    root,cfg,p,d,service,old,a,g=setup(tmp_path,monkeypatch)
    if mutation=='missing_pin':del a['prior_members']['start.json']
    if mutation=='bad_pin':a['prior_members']['start.json']['sha256']='0'*64
    if mutation in ('old_success','old_error','old_native'):
        f=old/'finish/record.json';v=json.loads(f.read_bytes());v[{'old_success':'status','old_error':'error','old_native':'native_run_entries_in_failed_phase'}[mutation]]={'old_success':'SUCCESS','old_error':'OTHER','old_native':1}[mutation];f.chmod(0o600);f.write_bytes(canonical(v));a['prior_members']['finish/record.json']={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size}
    if mutation=='old_diagnostic':
        f=old/'finish/diagnostics.json';f.chmod(0o600);f.write_bytes(canonical([{'unknown':'diagnostic'}]));a['prior_members']['finish/diagnostics.json']={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size}
    if mutation in ('old_card','old_method'):
        prior={'action':'ORIGINAL','method_ref':g['method_ref'],'candidate_ref':g['candidate_ref']};key='method_ref' if mutation=='old_method' else 'candidate_ref';prior[key]={**prior[key],'sha256':'0'*64};f=old/'authority.json';f.chmod(0o600);f.write_bytes(canonical(prior));a['prior_members']['authority.json']={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size}
    if mutation=='science':
        cfg={**cfg,'candidate_id':'INVENTED-CHANGED'};a['candidate_id']=cfg['candidate_id'];a['science_binding_sha256']=sha(canonical(science_binding(cfg)));a['current_binding_sha256']=sha(canonical(binding(cfg)));g['binding_sha256']=sha(canonical(binding(cfg)))
        for key in ('method_ref','candidate_ref'):
            v=json.loads(Path(g[key]['path']).read_bytes());v['candidate_id']=cfg['candidate_id'];g[key]=write(tmp_path/('INVENTED-changed-'+key+'.json'),v)
    if mutation=='work':a['allowed_e1_work_ns']=1200*10**9
    if mutation=='family':a['family']='0'*64
    if mutation=='prior':g['expected_prior_attempts']=[]
    if mutation=='status':a['status']='DRAFT'
    if mutation=='allowance':a['allowed_payments']=25
    if mutation=='bool_zero':g['allowed_fit_calls']=False
    if mutation=='missing_review':del g['independent_review_ref']
    if mutation=='audit_pin':a['prior_audit_ref']={**a['prior_audit_ref'],'sha256':'0'*64}
    if mutation=='unknown_field':a['retry']=True
    if mutation=='b8_action':g['action']='CORRECTIVE_E1'
    current=bind(tmp_path,cfg,a,g)
    import polar.raw_action_service as module
    def no(*args):raise AssertionError('INVALID_ADMISSION_VALUE_READER')
    monkeypatch.setattr(module,'load',no)
    with pytest.raises(Exception) as exc:service.run(current)
    assert not isinstance(exc.value,AssertionError) and len(list(root.rglob('start.json')))==1


def test_concurrent_calls_create_one_additional_debit(tmp_path,monkeypatch):
    root,cfg,p,d,service,old,a,g=setup(tmp_path,monkeypatch);current=bind(tmp_path,cfg,a,g)
    import polar.raw_action_service as module
    def fail(*args):raise ValueError('INVENTED_E1_FAILURE')
    monkeypatch.setattr(module,'load',fail)
    def one(_):
        try:service.run(current)
        except Exception as e:return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(one,range(2)))
    assert sorted(results)==['INVENTED_E1_FAILURE','RAW_CORRECTIVE_PRIOR_HISTORY']
    assert len(list(root.rglob('start.json')))==2


def test_injected_native_failure_keeps_partial_completed_phase_counts_and_diagnostics(tmp_path,monkeypatch):
    root,cfg,p,d,service,old,a,g=setup(tmp_path,monkeypatch);current=bind(tmp_path,cfg,a,g);before=snapshot(old)
    import polar.raw_action_service as module
    from polar.ci_research_service import NativeFailure
    native=module.bounded_native;calls=[]
    injected=[{'phase':'NATIVE_RUN_ENTERED'},{'phase':'ACCOUNT_COMPLETED'}]
    def partial(plan):
        calls.append(plan['cost_profile'])
        if len(calls)==2:raise NativeFailure('INVENTED_NATIVE_PHASE_FAILURE',injected)
        return native(plan)
    monkeypatch.setattr(module,'bounded_native',partial)
    with pytest.raises(NativeFailure,match='INVENTED_NATIVE_PHASE_FAILURE'):service.run(current)
    path=next(f for f in root.rglob('finish/record.json') if f.parent.parent!=old)
    finish=json.loads(path.read_bytes())
    assert finish['completed_native_accounts']==finish['cumulative_completed_native_accounts']==5
    assert finish['native_run_entries_in_failed_phase']==1
    assert finish['completed_verified_lifecycle_counts']=={'recognize':12,'pay':12}
    assert json.loads(path.with_name('diagnostics.json').read_bytes())==injected
    assert snapshot(old)==before and finish['refund'] is finish['automatic_retry'] is False
