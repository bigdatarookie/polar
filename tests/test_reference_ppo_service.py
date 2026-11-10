"""Small invented three-fit family, deterministic selection, native and immutable publication."""
import hashlib,json
from pathlib import Path
import pytest
from test_reference_service import fixture,write
from polar.reference_service import ReferenceResearchService,INVENTED_B
from polar.reference_ppo import select_development


def test_exact_canonical_selection_and_tie():
    def item(seed,value):return {'seed':seed,'metrics':{'sharpe_252_rf0':{'value':value,'status':'OK' if value else 'UNAVAILABLE'}}}
    assert select_development([item(2,'1.00000000000000000000000000000000000000000000001'),item(0,'1')])==2
    assert select_development([item(2,'1'),item(0,'1')])==0
    assert select_development([item(0,None),item(1,None),item(2,None)]) is None


def test_three_seed_service_one_selected_test_and_stored_only(tmp_path,monkeypatch):
    root,cfg=fixture(tmp_path,monkeypatch)
    mp=Path(cfg['input_ref']['path']);manifest=json.loads(mp.read_text())
    # Same bounded invented tokens/lineage; selected B's public four-symbol identity.
    old=manifest['symbols'];symbols=['AAPL','AMZN','TSLA','VTI'];mapping=dict(zip(old,symbols))
    qp=Path(manifest['quotes']['path']);quotes=[json.loads(x) for x in qp.read_text().splitlines()]
    for q in quotes:q['symbol']=mapping[q['symbol']]
    qp.write_bytes(b''.join((json.dumps(q,sort_keys=True,separators=(',',':'))+'\n').encode() for q in quotes))
    manifest['quotes']['sha256']=hashlib.sha256(qp.read_bytes()).hexdigest();manifest['quotes']['bytes']=qp.stat().st_size
    manifest['symbols']=symbols;cfg['input_ref']=write(mp,manifest)
    schedule=json.loads(Path(manifest['schedule']['path']).read_text());days=[r['date'] for r in schedule['rows']]
    def partition(label,lo,hi):return {'partition':label,'cash_anchor_date':days[lo],'terminal_date':days[hi],
        'date_grid':days[lo:hi+1],'nav_points':hi-lo+1,'step_intervals':hi-lo}
    cp=Path(cfg['calendar_ref']['path']);cfg['calendar_ref']=write(cp,{
        'source_reference_schedule_sha256':manifest['schedule']['sha256'],'invented_train_steps':256,
        'partitions':[partition('TRAIN',60,70),partition('DEV',70,80),partition('TEST',80,90)]})
    pp=Path(cfg['protocol_ref']['path']);protocol=json.loads(pp.read_text());protocol.update(
        profile_id=INVENTED_B,calendar_sha256=cfg['calendar_ref']['sha256'],input_sha256=cfg['input_ref']['sha256'])
    cfg['protocol_ref']=write(pp,protocol);cfg['profile_id']=INVENTED_B
    service=ReferenceResearchService(root,128*1024**2);assert service.preflight(cfg)['scientific_starts']==0
    out=service.run(cfg);assert out['fit_calls']==3 and out['development_runs']==3
    assert out['status']=='SUCCESS' # This invented fixture exercises actual saved FINAL publication.
    if out['status']=='SUCCESS':assert out['native_accounts']==5 and len(out['results'])==1
    import polar.reference_ppo as ppo
    def forbidden(*a,**k):raise AssertionError('RECOMPUTE_EXECUTED_FIT_OR_POLICY')
    monkeypatch.setattr(ppo,'train_seed',forbidden);monkeypatch.setattr(ppo,'deterministic_episode',forbidden)
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    assert service.recompute(out['semantic_id'])['status']=='REPRODUCED'
    after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()};assert before==after
    with pytest.raises(ValueError,match='REFERENCE_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


@pytest.mark.parametrize('profile,selection,accepted', [
    ('PPO',['tests/test_reference_service.py'],False),
    ('PPO',['tests/test_reference_ppo_service.py'],True),
    ('PPO',['tests'],True),
    ('PPO',[],False),
    ('RIDGE',['tests/test_reference_ppo_service.py'],False),
    ('RIDGE',['tests/test_reference_service.py'],True),
    ('RIDGE',['tests'],True)])
def test_retained_authority_requires_the_applicable_learner_exam(tmp_path,monkeypatch,profile,selection,accepted):
    # Pure authority boundary: entirely invented metadata, no source, model or native invocation.
    import polar.reference_service as module
    from polar.gym_contract import canonical,sha
    identity=module.B if profile=='PPO' else module.A
    expected=module.PROFILES[identity]
    method={'method_definition_verdict':'PASS','protocol_sha256':expected['protocol']}
    method_ref=write(tmp_path/'method.json',method)
    monkeypatch.setitem(module.PROFILES,identity,{**expected,'method':method_ref['sha256']})
    candidate_ref=write(tmp_path/'candidate.json',{'schema':'polar.native-hypothesis-reservation/1',
        'state':'RESERVED','candidate_id':identity,'experiment_registration_id':expected['registration']})
    revision='a'*40
    qualification_ref=write(tmp_path/'qualification.json',{'schema':'polar.ci-result/1',
        'status':'PASS','candidate_sha':revision,'selection':selection})
    cfg={'namespace':'RETAINED','profile_id':identity,'candidate_id':identity,'code_revision':revision,
         'execution_authority_ref':None}
    authority={'schema':'polar.reference-research-operation/1','action':'ORIGINAL',
        'binding_sha256':sha(canonical(module.binding(cfg))),'method_ref':method_ref,
        'candidate_ref':candidate_ref,'qualification_ref':qualification_ref}
    cfg['execution_authority_ref']=write(tmp_path/'authority.json',authority)
    def forbidden(*a,**k):raise AssertionError('QUALIFICATION_CHECK_CALLED_MODEL_NATIVE_OR_SOURCE')
    monkeypatch.setattr(module,'fit_ridge',forbidden);monkeypatch.setattr(module,'bounded_native',forbidden)
    monkeypatch.setattr(module,'load_reference',forbidden)
    service=ReferenceResearchService(tmp_path/'store',1024**2)
    if accepted:assert service._authority(cfg)['action']=='ORIGINAL'
    else:
        with pytest.raises(ValueError,match='REFERENCE_EXACT_TECHNICAL_QUALIFICATION'):service._authority(cfg)
    assert not (service.store.root/'reference-research-attempts').exists()
