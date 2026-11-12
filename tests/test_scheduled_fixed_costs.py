"""Invented fixed annual true-cost scenarios; no bootstrap or private operands."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from reference_fixture import write
from test_scheduled_fixed import fixed_fixture
from test_scheduled_service import snapshot
from polar.reference_service import ReferenceResearchService
from polar.scheduled_policy import profile_value
from polar.research_results import ResearchResults


def cost_fixture(tmp_path,monkeypatch):
    root,cfg,p,cal=fixed_fixture(tmp_path,monkeypatch)
    p['schema']='polar.scheduled-reference-profile/8'
    p['cost_scenarios']=[{'id':'BASE','cost_profile':{'flat_cents':100,'bps':10}},
                         {'id':'COST_STRESS','cost_profile':{'flat_cents':200,'bps':20}}]
    p['legs'].insert(1,{**deepcopy(p['legs'][0]),'id':'ALTERNATE','label':'Other constant thirds'})
    p['additional_limitations']=[]
    cfg['profile_ref']=write(tmp_path/'cost-profile.json',p)
    return root,cfg,p,cal


def test_ten_account_actual_cost_reexecution_and_saved_only_no_bootstrap(tmp_path,monkeypatch):
    import polar.scheduled_service as m
    root,cfg,p,cal=cost_fixture(tmp_path,monkeypatch)
    real=m.load_reference;native=m.bounded_native;calls=[]
    def forbidden(*a,**k):raise AssertionError('UNEXPECTED_SOURCE_POLICY_NATIVE_OR_BOOTSTRAP')
    monkeypatch.setattr(m,'uncertainty_for',forbidden)
    monkeypatch.setattr(m,'load_reference',forbidden)
    service=ReferenceResearchService(root,128*1024**2)
    assert service.preflight(cfg)['expected_native_accounts']==10
    assert not list(root.rglob('start.json'))
    def source(*a,**k):
        assert len(list(root.rglob('start.json')))==1
        return real(*a,**k)
    monkeypatch.setattr(m,'load_reference',source)
    def counted(plan):calls.append(plan['cost_profile']);return native(plan)
    monkeypatch.setattr(m,'bounded_native',counted)
    result=service.run(cfg)
    assert result['status']=='SUCCESS' and result['native_accounts']==10
    assert calls==[x['cost_profile'] for x in p['cost_scenarios']]
    assert all(result[k]==0 for k in ('fit_calls','predict_calls','model_calls','score_calls','rank_calls','estimator_calls','optimizer_calls','bootstrap_samples'))
    directory=root/'reference-research-experiments'/result['semantic_id']
    phases=json.loads((directory/'phases.json').read_bytes());diag=json.loads((directory/'diagnostics.json').read_bytes())
    assert set(phases)=={'FINAL','FINAL_COST_STRESS'} and not (directory/'uncertainty.json').exists()
    for phase,data in phases.items():
        assert data['plan']['signals']==[] and data['simulation']['cost_profile']==data['plan']['cost_profile']
        assert all(t['nav'][0]['nav_cents']==10000000 for t in data['simulation']['legs'])
        assert all(len(d['subperiods'])==(2 if phase=='FINAL' else 0) for d in diag[phase].values())
        for d in data['plan']['decisions'][:-1]:
            assert [i['kind'] for i in d['instructions'].values()].count('TARGET')==4
            assert d['instructions']['CASH']['kind']=='HOLD'
        assert all(i['kind']=='EXIT' for i in data['plan']['decisions'][-1]['instructions'].values())
        record=ResearchResults(root,128*1024**2).read(result['results'][phase]['result_id'])
        assert len(record['record']['series'])==5 and record['assessment']['financial']=='NOT_REVIEWED'
    assert phases['FINAL']['plan']['decisions']==phases['FINAL_COST_STRESS']['plan']['decisions']
    base=snapshot(root)
    for name in ('load_reference','plan_phase','bounded_native'):monkeypatch.setattr(m,name,forbidden)
    replay=service.recompute(result['semantic_id'])
    assert replay['status']=='REPRODUCED' and replay['native_calls']==replay['store_writes']==0
    assert snapshot(root)==base


@pytest.mark.parametrize('change', ['extra_bootstrap','wrong_cost','reverse_cost','zero_weight_cash'])
def test_fixed_cost_profile_rejects_semantic_drift(tmp_path,monkeypatch,change):
    _,_,p,_=cost_fixture(tmp_path,monkeypatch)
    if change=='extra_bootstrap':p['uncertainty']={'seed':1}
    elif change=='wrong_cost':p['cost_scenarios'][1]['cost_profile']['bps']=10
    elif change=='reverse_cost':p['cost_scenarios'].reverse()
    else:p['legs'][-1]['weights'][p['symbols'][0]]=[1,3]
    with pytest.raises(ValueError):profile_value(p)


@pytest.mark.parametrize('tamper,error',[('missing_phase','FIXED_COST_PHASES'),('cost','FIXED_COST_BINDING'),('bootstrap','PROFILE_MEMBER_SET')])
def test_rehashed_saved_scenario_drift_is_not_reproduced(tmp_path,monkeypatch,tamper,error):
    import polar.scheduled_service as m
    root,cfg,_,_=cost_fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    result=service.run(cfg);directory=root/'reference-research-experiments'/result['semantic_id']
    manifest=json.loads((directory/'manifest.json').read_bytes())
    files={name:(directory/name).read_bytes() for name in manifest['files']}
    if tamper=='bootstrap':files['uncertainty.json']=m.canonical({'not_requested':True})
    else:
        phases=json.loads(files['phases.json'])
        if tamper=='missing_phase':del phases['FINAL_COST_STRESS']
        else:
            phases['FINAL_COST_STRESS']['simulation']['cost_profile']={'flat_cents':100,'bps':10}
            phases['FINAL_COST_STRESS']['plan']['cost_profile']={'flat_cents':100,'bps':10}
        files['phases.json']=m.canonical(phases)
    manifest['files']={name:{'sha256':m.sha(raw),'bytes':len(raw)} for name,raw in files.items()}
    raw=m.canonical(manifest);sid=m.SEMANTIC+m.sha(raw);destination=root/'reference-research-experiments'/sid;destination.mkdir()
    for name,body in {**files,'manifest.json':raw}.items():(destination/name).write_bytes(body)
    with pytest.raises(ValueError,match=error):service.recompute(sid)
