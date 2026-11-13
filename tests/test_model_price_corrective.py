"""Invented linked metadata, not a retained graph or operative authority."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import pytest
from reference_fixture import write
from test_scheduled_model_price import model_fixture
from test_scheduled_service import snapshot
from polar.gym_contract import canonical,sha
from polar.reference_service import ReferenceResearchService
from polar.scheduled_service import binding
from polar.scheduled_corrective import science_binding
from polar.model_price_corrective import ACTION


def setup(tmp_path,monkeypatch):
    root,cfg,p,cal=model_fixture(tmp_path,monkeypatch);svc=ReferenceResearchService(root,256*1024**2)
    family=sha(canonical({'protocol_id':p['protocol_id'],'input':cfg['input_ref']['sha256'],'namespace':cfg['namespace']}))
    old='11111111-1111-1111-1111-111111111111';parent='scheduled-reference-attempts/'+family
    # Deliberately tiny opaque invented prior; no old economic witness is available.
    phase={'INVENTED_OPAQUE_OLD_PHASE':'not a real/native result'};diag={'INVENTED':'not an audit'}
    start={'attempt_id':old,'status':'FIRST_START_CONSERVATIVE_DEBIT','binding':binding(cfg),'started_ns':10}
    finish={'attempt_id':old,'status':'FAILED_UNFINALIZED','error':'RESEARCH_INVALID_RESULT',
        'completed_native_accounts':5,'refund':False,'automatic_retry':False,'finished_ns':20}
    files={'start.json':canonical(start),'config.json':canonical(cfg),'authority.json':canonical(None)}
    with svc.store.locked():
        svc.store._publish(parent,old,files)
        svc.store._publish(parent+'/'+old+'/phases','FINAL',{'phase.json':canonical(phase),'diagnostics.json':canonical(diag)})
        svc.store._publish(parent+'/'+old,'finish',{'record.json':canonical(finish),'diagnostics.json':canonical([])})
    oldpath=root/parent/old
    pins={str(x.relative_to(oldpath)):{'sha256':sha(x.read_bytes()),'bytes':x.stat().st_size} for x in oldpath.rglob('*') if x.is_file()}
    semantic={'profile.json':canonical(p),'calendar.json':canonical(cal),'phases.json':canonical({'FINAL':phase}),
        'diagnostics.json':canonical({'FINAL':diag}),'bindings.json':canonical(binding(cfg))}
    manifest={'schema':'polar.scheduled-reference-semantic-manifest/1','files':{k:{'sha256':sha(v),'bytes':len(v)} for k,v in semantic.items()}}
    raw=canonical(manifest);sid='scheduled-reference-experiment-'+sha(raw)
    with svc.store.locked():svc.store._publish('reference-research-experiments',sid,{**semantic,'manifest.json':raw})
    sp={k:{'sha256':sha(v),'bytes':len(v)} for k,v in {**semantic,'manifest.json':raw}.items()}
    metadata=write(tmp_path/'INVENTED-custody.json',{'scope':'INVENTED-only predicate; not an actual financial/authority decision'})
    applicability=write(tmp_path/'INVENTED-applicability.json',{'schema':'polar.validator-financial-repeat-applicability/1',
        'disposition':'APPLICABLE_SAME_FROZEN_CHOICE_E1_WITH_FULL_OUTCOME_EXPOSURE','scientific_scope_status':'PASS_BOUNDED_PROSPECTIVE_APPLICABILITY',
        'candidate_id':cfg['candidate_id'],'experiment_registration_id':cfg['experiment_id'],'family':family,
        'old_semantic':sid,'additive_accounting':{'old_attempt':old},'unmet_prospective_scientific_choice_predicates':[]})
    method=write(tmp_path/'INVENTED-method.json',{'schema':'polar.prospective-method-disposition/1','method_verdict':'PASS','protocol':{'sha256':cfg['protocol_ref']['sha256']},'candidate_id':cfg['candidate_id']})
    card=write(tmp_path/'INVENTED-card.json',{'schema':'polar.native-hypothesis-reservation/1','state':'RESERVED','candidate_id':cfg['candidate_id'],'experiment_registration_id':cfg['experiment_id']})
    ci=write(tmp_path/'INVENTED-CI.json',{'schema':'polar.ci-result/1','status':'PASS','candidate_sha':cfg['code_revision'],'selection':['tests']})
    a={'schema':'polar.model-price-corrective-amendment/1','status':'BOUND_FOR_EXECUTION','action':ACTION,'family':family,
        'candidate_id':cfg['candidate_id'],'experiment_id':cfg['experiment_id'],'prior_attempt_id':old,'prior_members':pins,
        'prior_semantic_id':sid,'prior_semantic_members':sp,'science_binding_sha256':sha(canonical(science_binding(cfg))),
        'current_binding_sha256':sha(canonical(binding(cfg))),'prior_audit_ref':metadata,'custody_ref':metadata,'invariants_ref':metadata,
        'applicability_ref':applicability,'charge_history_ref':metadata,'owner_id':'INVENTED-owner','maximum_family_starts':2,
        'allowed_native_accounts':5,'prior_charged_work_ns':10**9,'allowed_e1_work_ns':599*10**9,'total_work_budget_ns':600*10**9}
    g={'schema':'polar.scheduled-reference-operation/1','action':ACTION,'binding_sha256':sha(canonical(binding(cfg))),
        'allowed_native_accounts':5,'expected_prior_attempts':[old],'method_ref':method,'candidate_ref':card,'qualification_ref':ci,
        **{k:0 for k in ('allowed_fit_calls','allowed_predict_calls','allowed_score_calls','allowed_rank_calls',
            'allowed_estimator_calls','allowed_optimizer_calls','allowed_bootstrap_samples')}}
    return root,cfg,p,svc,oldpath,a,g


def bind(tmp_path,cfg,a,g):
    ref=write(tmp_path/'INVENTED-amendment.json',a)
    return {**cfg,'execution_authority_ref':write(tmp_path/'INVENTED-operation.json',{**g,'corrective_amendment_ref':ref})}


@pytest.mark.parametrize('mutant',['missing_leaf','missing_semantic','bad_leaf','bad_semantic','success','wrong_error',
    'wrong_native','changed_science','bad_prior','bad_family','work','bool','arbitrary_retry','applicability','opaque_phase','bad_old_method'])
def test_mutants_reject_before_values_or_debit(tmp_path,monkeypatch,mutant):
    root,cfg,p,svc,old,a,g=setup(tmp_path,monkeypatch)
    if mutant=='missing_leaf':del a['prior_members']['phases/FINAL/phase.json']
    if mutant=='missing_semantic':del a['prior_semantic_members']['phases.json']
    if mutant=='bad_leaf':a['prior_members']['phases/FINAL/phase.json']['sha256']='0'*64
    if mutant=='bad_semantic':a['prior_semantic_members']['phases.json']['sha256']='0'*64
    if mutant in ('success','wrong_error','wrong_native'):
        f=old/'finish/record.json';v=json.loads(f.read_bytes());v[{'success':'status','wrong_error':'error','wrong_native':'completed_native_accounts'}[mutant]]={'success':'SUCCESS','wrong_error':'NATIVE_WALL_TIMEOUT','wrong_native':0}[mutant]
        f.chmod(0o600);f.write_bytes(canonical(v));a['prior_members']['finish/record.json']={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size}
    if mutant=='changed_science':
        cfg={**cfg,'runtime_image_id':'sha256:'+'f'*64,'experiment_id':'INVENTED-CHANGED'}
        a['experiment_id']=cfg['experiment_id'];a['current_binding_sha256']=g['binding_sha256']=sha(canonical(binding(cfg)))
        a['science_binding_sha256']=sha(canonical(science_binding(cfg)))
        card=json.loads(Path(g['candidate_ref']['path']).read_bytes());card['experiment_registration_id']=cfg['experiment_id'];g['candidate_ref']=write(tmp_path/'INVENTED-new-card.json',card)
        app=json.loads(Path(a['applicability_ref']['path']).read_bytes());app['experiment_registration_id']=cfg['experiment_id'];a['applicability_ref']=write(tmp_path/'INVENTED-new-app.json',app)
    if mutant=='bad_prior':g['expected_prior_attempts']=[]
    if mutant=='bad_family':a['family']='0'*64
    if mutant=='work':a['allowed_e1_work_ns']=a['total_work_budget_ns']
    if mutant=='bool':g['allowed_fit_calls']=False
    if mutant=='arbitrary_retry':a['retry']=True
    if mutant=='applicability':a['applicability_ref']=a['custody_ref']
    if mutant=='opaque_phase':
        f=old/'phases/FINAL/phase.json';f.chmod(0o600);f.write_bytes(canonical({'different':'INVENTED'}));a['prior_members']['phases/FINAL/phase.json']={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size}
    if mutant=='bad_old_method':
        f=old/'authority.json';f.chmod(0o600);f.write_bytes(canonical({'action':'ORIGINAL','method_ref':a['custody_ref'],'candidate_ref':g['candidate_ref']}));a['prior_members']['authority.json']={'sha256':sha(f.read_bytes()),'bytes':f.stat().st_size}
    import polar.scheduled_service as module
    monkeypatch.setattr(module,'load_market',lambda *a:(_ for _ in ()).throw(AssertionError('NO_VALUES_BEFORE_ADMISSION')))
    with pytest.raises(Exception) as exc:svc.run(bind(tmp_path,cfg,a,g))
    assert not isinstance(exc.value,AssertionError)
    assert len(list(root.rglob('start.json')))==1


def test_atomic_failure_stays_charged_no_third_no_old_decode(tmp_path,monkeypatch):
    root,cfg,p,svc,old,a,g=setup(tmp_path,monkeypatch);current=bind(tmp_path,cfg,a,g);before=snapshot(old)
    import polar.scheduled_service as module
    def fail(*args):raise ValueError('MODEL_INVENTED_E1_PARTIAL')
    monkeypatch.setattr(module,'load_market',fail)
    with pytest.raises(ValueError,match='ORIGINAL_ALREADY_RECORDED'):svc.run(cfg)
    def call(_):
        try:svc.run(current)
        except Exception as e:return str(e)
    with ThreadPoolExecutor(max_workers=2) as pool:errors=list(pool.map(call,range(2)))
    assert sorted(errors)==['MODEL_E1_PRIOR_HISTORY','MODEL_INVENTED_E1_PARTIAL']
    finish=[json.loads(f.read_bytes()) for f in root.rglob('finish/record.json') if f.parent.parent!=old][0]
    assert finish['refund'] is finish['automatic_retry'] is False and finish['cumulative_completed_native_accounts']==5
    assert finish['corrective_lineage']['old_missing_witnesses']=='UNAVAILABLE_NOT_BACKFILLED'
    assert snapshot(old)==before and len(list(root.rglob('start.json')))==2


def test_success_new_witnesses_source_absent_ro_and_no_old_backfill(tmp_path,monkeypatch):
    root,cfg,p,svc,old,a,g=setup(tmp_path,monkeypatch);current=bind(tmp_path,cfg,a,g);before=snapshot(old)
    result=svc.run(current)
    assert result['status']=='SUCCESS' and result['native_accounts']==5 and result['cumulative_completed_native_accounts']==10
    assert snapshot(old)==before
    semantic=root/'reference-research-experiments'/result['semantic_id'];phases=json.loads((semantic/'phases.json').read_bytes())
    from polar.model_price_consumed import verify
    data=phases['FINAL'];assert verify(data['plan'],data['simulation'],p)['status']=='VERIFIED_NEW_MODEL_CONSUMED_OPERANDS'
    for mutation in ('missing','nav','model','weights','clip','fill','zero','cash_hold','clock','date'):
        bad=deepcopy(data);sim=bad['simulation'];leg=sim['legs'][0];intent=leg['intents'][0]
        if mutation=='missing':intent.pop('sizing_witness')
        if mutation=='nav':intent['sizing_witness']['nav_cents']+=1
        if mutation=='model':intent['sizing_witness']['eligible_prices_micro'][p['symbols'][0]]//=100
        if mutation=='weights':intent['sizing_witness']['weights'][p['symbols'][0]][0]=True
        if mutation=='clip':next(o for o in leg['orders'] if o['side']=='BUY')['consumed_operands']['cash_before_cents']+=1
        if mutation=='fill':leg['fills'][0]['price_micro']+=1
        if mutation=='zero':next(o for o in leg['orders'] if o['intended_quantity']==0)['reason']=None
        if mutation=='cash_hold':sim['legs'][-1]['intents'][0]['sizing_status']='CONSUMED_TARGET_OPERANDS'
        if mutation=='clock':leg['intents'][0]['decision_ns']+=1
        if mutation=='date':leg['nav'][0]['date']='1900-01-01'
        with pytest.raises((ValueError,KeyError)):verify(bad['plan'],sim,p)
    # Existing source-free replay checks captured witnesses without source/native/policy or writes.
    snap=snapshot(root)
    import polar.scheduled_service as module
    for name in ('load_market','load_reference','plan_phase','bounded_native'):
        monkeypatch.setattr(module,name,lambda *a:(_ for _ in ()).throw(AssertionError('SOURCE_OR_EXECUTION_IN_SAVED')))
    for f in tmp_path.iterdir():
        if f.is_file():f.unlink()
    from polar.model_price_consumed import verify_saved
    assert verify_saved(svc,result['semantic_id'])['financial_evaluations']==0
    assert svc.recompute(result['semantic_id'])['store_writes']==0
    assert snapshot(root)==snap


def test_instrumentation_preserves_executed_money_and_source_model_separation(tmp_path,monkeypatch):
    from polar.scheduled_policy import plan_phase,calendar_value
    from polar.scheduled_service import load_market
    from polar.ci_research_native import simulate
    root,cfg,p,cal=model_fixture(tmp_path,monkeypatch)
    market=load_market(cfg,p);grid=calendar_value(cal,market['schedule'])['FINAL']
    plan=plan_phase(market,p,grid,None);legacy={**plan,'capture_consumed_sizing':False}
    before=deepcopy(market)
    old=simulate(legacy);new=simulate(plan)
    from polar.model_price_consumed import verify
    assert verify(plan,new,p)['native_calls']==0
    for a,b in zip(old['legs'],new['legs']):
        assert a['nav']==b['nav'] and a['fills']==b['fills']
        assert a['orders']==[{k:v for k,v in o.items() if k!='consumed_operands'} for o in b['orders'] if o['intended_quantity']>0]
    assert market==before
    # CASH/HOLD and EXIT witnesses explicitly do not pretend to have TARGET operands.
    cash=new['legs'][-1]
    assert all(i['sizing_witness'] is None for i in cash['intents'])
    assert all(o['routed_quantity']==0 and o['reason']=='ZERO_DELTA_NO_ORDER' for o in cash['orders'])
