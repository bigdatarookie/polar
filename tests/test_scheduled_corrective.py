"""Invented-only linked admission; no retained inputs or operative allowance."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import pytest

from curve_fixture import fixture
from reference_fixture import write
from test_scheduled_service import snapshot
from polar.gym_contract import canonical,sha
from polar.reference_service import ReferenceResearchService
from polar.scheduled_curve import CurveError,expected_counts
from polar.scheduled_corrective import science_binding,OLD_COUNTS,NEW_COUNTS
from polar.scheduled_service import binding


def setup_e1(tmp_path,monkeypatch):
    root,cfg,p,c,d=fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    service=ReferenceResearchService(root,256*1024**2)
    def bad_original(*args):
        raise CurveError('CURVE_INVALID_OPERAND_OR_DOMAIN',{'cause':'CURVE_RAW_SOURCE_REF','actual_counts':dict(OLD_COUNTS),'failed_signal':{'scope':'INVENTED'},'completed_signals':[]})
    with monkeypatch.context() as m:
        m.setattr(module,'plan_phase',bad_original)
        with pytest.raises(CurveError):service.run(cfg)
    old_path=next(root.rglob('finish/record.json')).parent.parent
    old=old_path.name;family=old_path.parent.name
    pins={}
    for name in ('start.json','config.json','authority.json','finish/record.json','finish/diagnostics.json'):
        raw=(old_path/name).read_bytes();pins[name]={'sha256':sha(raw),'bytes':len(raw)}
    metadata=write(tmp_path/'INVENTED-existing-custody-audit.json',{'scope':'INVENTED source-only predicate, not real review/grant'})
    method=write(tmp_path/'INVENTED-method.json',{'schema':'polar.prospective-method-disposition/1','method_verdict':'PASS','protocol':{'sha256':cfg['protocol_ref']['sha256']},'candidate_id':cfg['candidate_id']})
    card=write(tmp_path/'INVENTED-card.json',{'schema':'polar.native-hypothesis-reservation/1','state':'RESERVED','candidate_id':cfg['candidate_id'],'experiment_registration_id':cfg['experiment_id']})
    qualification=write(tmp_path/'INVENTED-qualification.json',{'schema':'polar.ci-result/1','status':'PASS','candidate_sha':cfg['code_revision'],'selection':['tests']})
    amendment={'schema':'polar.scheduled-corrective-amendment/1','status':'BOUND_FOR_EXECUTION','action':'CORRECTIVE_E1',
        'family':family,'candidate_id':cfg['candidate_id'],'experiment_id':cfg['experiment_id'],'prior_attempt_id':old,
        'prior_members':pins,'science_binding_sha256':sha(canonical(science_binding(cfg))),
        'current_binding_sha256':sha(canonical(binding(cfg))),'prior_audit_ref':metadata,'custody_ref':metadata,'invariants_ref':metadata,
        'owner_id':'INVENTED-OWNER','maximum_family_starts':2,'allowed_feature_counts':dict(NEW_COUNTS),'allowed_native_accounts':8,
        'total_work_budget_ns':1200*10**9,'prior_charged_work_ns':10**9,'allowed_e1_work_ns':1199*10**9}
    grant={'schema':'polar.scheduled-reference-operation/1','action':'CORRECTIVE_E1','binding_sha256':sha(canonical(binding(cfg))),
        'allowed_fit_calls':0,'allowed_predict_calls':0,'allowed_native_accounts':8,'allowed_feature_counts':dict(NEW_COUNTS),
        **{k:0 for k in ('allowed_score_calls','allowed_rank_calls','allowed_estimator_calls','allowed_optimizer_calls','allowed_bootstrap_samples')},
        'expected_prior_attempts':[old],'method_ref':method,'candidate_ref':card,'qualification_ref':qualification}
    return root,cfg,p,service,old_path,amendment,grant


def bind(tmp_path,cfg,amendment,grant):
    a=write(tmp_path/'INVENTED-E1-amendment.json',amendment)
    g=write(tmp_path/'INVENTED-E1-authority.json',{**grant,'corrective_amendment_ref':a})
    return {**cfg,'execution_authority_ref':g}


def test_original_duplicate_still_rejects_and_failed_e1_is_charged_once(tmp_path,monkeypatch):
    root,cfg,p,service,old_path,a,g=setup_e1(tmp_path,monkeypatch);before=snapshot(old_path)
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)
    current=bind(tmp_path,cfg,a,g)
    import polar.scheduled_service as module
    def fail(*args):raise CurveError('INVENTED_E1_FAILURE',{'actual_counts':{**expected_counts(0),'feature_calls':1}})
    monkeypatch.setattr(module,'plan_phase',fail)
    with pytest.raises(CurveError,match='INVENTED_E1_FAILURE'):service.run(current)
    finishes=[json.loads(p.read_bytes()) for p in root.rglob('finish/record.json')]
    e1=next(f for f in finishes if f['attempt_id']!=old_path.name)
    assert e1['status']=='FAILED_UNFINALIZED' and e1['refund'] is e1['automatic_retry'] is False
    assert e1['cumulative_recorded_feature_counts']=={**OLD_COUNTS,'feature_calls':2}
    assert e1['corrective_lineage']['prior_native_entry_counter']=='NOT_EMITTED_NOT_INFERRED_ZERO'
    assert e1['corrective_lineage']['family_start_count']==2 and e1['cumulative_completed_native_accounts']==0
    assert snapshot(old_path)==before
    monkeypatch.setattr(module,'load_market',lambda *a:(_ for _ in ()).throw(AssertionError('THIRD_START_MUST_NOT_LOAD')))
    with pytest.raises(ValueError,match='CORRECTIVE_PRIOR_HISTORY'):service.run(current)
    assert len(list(root.rglob('start.json')))==2


def test_e1_success_adds_counts_without_changing_old_graph(tmp_path,monkeypatch):
    root,cfg,p,service,old_path,a,g=setup_e1(tmp_path,monkeypatch);before=snapshot(old_path)
    current=bind(tmp_path,cfg,a,g)
    import polar.scheduled_service as module
    original=module.load_market
    def after_debit(*args):
        starts=list(root.rglob('start.json'));assert len(starts)==2
        e1=next(json.loads(p.read_bytes()) for p in starts if p.parent!=old_path)
        assert e1['corrective_lineage']['prior_attempt_id']==old_path.name
        return original(*args)
    monkeypatch.setattr(module,'load_market',after_debit)
    result=service.run(current)
    assert result['status']=='SUCCESS' and result['native_accounts']==8
    assert result['actual_feature_counts']==NEW_COUNTS
    assert result['cumulative_recorded_feature_counts']=={**NEW_COUNTS,'feature_calls':48}
    assert result['cumulative_completed_native_accounts']==8 and result['corrective_lineage']['old_stored_allocation']=='INELIGIBLE_NOT_RECYCLED'
    assert result['cumulative_charged_work_ns']>=10**9 and result['work_budget_exceeded'] is False
    assert snapshot(old_path)==before
    with pytest.raises(ValueError,match='CORRECTIVE_PRIOR_HISTORY'):service.run(current)


@pytest.mark.parametrize('mutation',['missing_pin','bad_pin','wrong_prior','success','missing_finish','missing_diagnostic','changed_science','missing_amendment_status','unknown_retry_flag','counts','work_budget','audit_integrity'])
def test_changed_or_unbound_prior_rejects_before_debit_and_values(tmp_path,monkeypatch,mutation):
    root,cfg,p,service,old_path,a,g=setup_e1(tmp_path,monkeypatch)
    if mutation=='missing_pin':del a['prior_members']['start.json']
    if mutation=='bad_pin':a['prior_members']['start.json']['sha256']='0'*64
    if mutation=='wrong_prior':a['prior_attempt_id']='11111111-1111-1111-1111-111111111111';g['expected_prior_attempts']=[a['prior_attempt_id']]
    if mutation=='success':
        f=old_path/'finish/record.json';f.chmod(0o600);v=json.loads(f.read_bytes());v['status']='SUCCESS';f.write_bytes(canonical(v));a['prior_members']['finish/record.json']={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size}
    if mutation=='missing_finish':(old_path/'finish/record.json').unlink()
    if mutation=='missing_diagnostic':(old_path/'finish/diagnostics.json').unlink()
    if mutation=='changed_science':
        cfg={**cfg,'experiment_id':'INVENTED-CHANGED-SCIENCE'};a['experiment_id']=cfg['experiment_id'];a['science_binding_sha256']=sha(canonical(science_binding(cfg)));a['current_binding_sha256']=sha(canonical(binding(cfg)));g['binding_sha256']=sha(canonical(binding(cfg)));card=json.loads(Path(g['candidate_ref']['path']).read_bytes());card['experiment_registration_id']=cfg['experiment_id'];g['candidate_ref']=write(tmp_path/'INVENTED-changed-card.json',card)
    if mutation=='missing_amendment_status':del a['status']
    if mutation=='unknown_retry_flag':a['retry_allowed']=True
    if mutation=='counts':a['allowed_feature_counts']['rate_operand_reads']=95
    if mutation=='work_budget':a['allowed_e1_work_ns']=1200*10**9
    if mutation=='audit_integrity':a['prior_audit_ref']={**a['prior_audit_ref'],'sha256':'0'*64}
    current=bind(tmp_path,cfg,a,g)
    import polar.scheduled_service as module
    monkeypatch.setattr(module,'load_market',lambda *a:(_ for _ in ()).throw(AssertionError('VALUE_LOADER_BEFORE_LINKED_ADMISSION')))
    with pytest.raises(Exception) as exc:service.run(current)
    assert not isinstance(exc.value,AssertionError)
    assert len(list(root.rglob('start.json')))==1


def test_two_concurrent_e1_calls_only_one_can_debit(tmp_path,monkeypatch):
    root,cfg,p,service,old_path,a,g=setup_e1(tmp_path,monkeypatch);current=bind(tmp_path,cfg,a,g)
    import polar.scheduled_service as module
    def fail(*args):raise CurveError('INVENTED_E1_FAILURE',{'actual_counts':expected_counts(0)})
    monkeypatch.setattr(module,'plan_phase',fail)
    def one(_):
        try:service.run(current)
        except Exception as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(one,range(2)))
    assert sorted(results)==['CORRECTIVE_PRIOR_HISTORY','INVENTED_E1_FAILURE']
    assert len(list(root.rglob('start.json')))==2
