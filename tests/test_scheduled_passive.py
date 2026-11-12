"""Invented initial-only controls: real native tape, equal initial state, saved replay."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from reference_fixture import write
from test_scheduled_fixed_costs import cost_fixture
from test_scheduled_service import snapshot
from polar.reference_service import ReferenceResearchService
from polar.scheduled_policy import profile_value, calendar_value, plan_phase, evaluate_policy
from polar.scheduled_passive import matched_initial_state
from polar.research_reference import load_reference


def passive_fixture(tmp_path,monkeypatch):
    root,cfg,p,cal=cost_fixture(tmp_path,monkeypatch)
    p['schema']='polar.scheduled-reference-profile/9'
    p['policy']={'kind':'FIXED_ANNUAL_WITH_PASSIVE_CONTROLS'}
    for leg in p['legs']:
        if leg['id'] in ('ALTERNATE','FULL','THIRD'):leg['rule']='INITIAL_TARGET_ONLY'
    p['primary_benchmark']='ALTERNATE'
    p['criteria']=[{'id':kind,'description':kind,'kind':kind,'left_id':'THIRDS',
                   **({} if kind=='POSITIVE_GROWTH' else {'right_id':'ALTERNATE'}),
                   **({'factor':[101,100]} if kind=='TERMINAL_SCALED_GE' else
                      {'threshold':'0'} if kind=='SR_DELTA_GE' else {})}
                  for kind in ['TERMINAL_SCALED_GE','SR_DELTA_GE','DRAWDOWN_LE','VOL_LE','POSITIVE_GROWTH']]
    cfg['profile_ref']=write(tmp_path/'passive-profile.json',p)
    return root,cfg,p,cal


def test_passive_planner_exact_one_target_no_backfill_and_exit(tmp_path,monkeypatch):
    _,cfg,p,_=passive_fixture(tmp_path,monkeypatch)
    m=load_reference(cfg['input_ref']);grid=calendar_value(json.loads(Path(cfg['calendar_ref']['path']).read_bytes()),m['schedule'])['FINAL']
    plan=plan_phase(m,p,grid,None);events=plan['decisions'][:-1];n=len(events)
    assert events[0]['instructions']['ALTERNATE']==events[0]['instructions']['THIRDS']
    for leg in ('ALTERNATE','FULL','THIRD'):
        assert [e['instructions'][leg]['kind'] for e in events]==['TARGET']+['HOLD']*(n-1)
    assert all(e['instructions']['THIRDS']['kind']=='TARGET' and e['instructions']['CASH']['kind']=='HOLD' for e in events)
    assert all(i['kind']=='EXIT' for i in plan['decisions'][-1]['instructions'].values())
    assert sum(i['kind']=='TARGET' for e in events for i in e['instructions'].values())==n+3
    assert sum(i['kind']=='HOLD' for e in events for i in e['instructions'].values())==4*n-3
    changed=deepcopy(m)
    for row in changed['prices_micro'].values():
        for symbol in row:row[symbol]*=7
    assert plan_phase(changed,p,grid,None)['decisions']==plan['decisions']


def test_true_cost_pair_guard_and_source_free_immutable_replay(tmp_path,monkeypatch):
    import polar.scheduled_service as m
    root,cfg,p,_=passive_fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    def forbidden(*a,**k):raise AssertionError('UNEXPECTED_SOURCE_POLICY_NATIVE_BOOTSTRAP')
    real=m.load_reference;monkeypatch.setattr(m,'load_reference',forbidden)
    assert service.preflight(cfg)['expected_native_accounts']==10
    monkeypatch.setattr(m,'load_reference',real);monkeypatch.setattr(m,'uncertainty_for',forbidden)
    result=service.run(cfg);assert result['status']=='SUCCESS' and result['native_accounts']==10
    directory=root/'reference-research-experiments'/result['semantic_id'];phases=json.loads((directory/'phases.json').read_bytes())
    for phase,data in phases.items():
        assert data['initial_state_control']['status']=='PASS'
        assert matched_initial_state(data['simulation'],p,data['plan'])==data['initial_state_control']
        day=data['plan']['decisions'][0]['day'];other_days={e['day'] for e in data['plan']['decisions'][1:-1]}
        for tape in data['simulation']['legs']:
            if tape['id'] in ('ALTERNATE','FULL','THIRD'):
                allowed={f"{tape['id']}/{day}/",f"{tape['id']}/{data['plan']['grid'][-1]['date']}/"}
                assert all(any(f['id'].startswith(a) for a in allowed) for f in tape['fills'])
            if tape['id']=='CASH':assert tape['orders']==tape['fills']==[]
    before=snapshot(root)
    for name in ('load_reference','plan_phase','bounded_native'):monkeypatch.setattr(m,name,forbidden)
    replay=service.recompute(result['semantic_id']);assert replay['status']=='REPRODUCED' and replay['native_calls']==replay['store_writes']==0
    assert snapshot(root)==before


@pytest.mark.parametrize('key',['cash_cents','positions','flat_cents','nav_cents','sample_ns'])
def test_actual_initial_state_mismatch_invalid_no_publication_or_retry(tmp_path,monkeypatch,key):
    import polar.scheduled_service as m
    root,cfg,p,_=passive_fixture(tmp_path,monkeypatch);real=m.bounded_native
    def mismatch(plan):
        simulation=real(plan);t=next(x for x in simulation['legs'] if x['id']=='ALTERNATE')
        mark=next(x for x in t['nav'] if x['date']==plan['decisions'][0]['day'])
        if key=='positions':mark[key][p['symbols'][0]]+=1
        else:mark[key]+=1
        return simulation
    monkeypatch.setattr(m,'bounded_native',mismatch)
    with pytest.raises(ValueError,match='INITIAL_STATE_MISMATCH_INVALID'):ReferenceResearchService(root,128*1024**2).run(cfg)
    finish=[json.loads(x.read_bytes()) for x in root.rglob('finish/record.json')]
    assert len(finish)==1 and finish[0]['scientific_status']=='INVALID' and finish[0]['automatic_retry'] is False and finish[0]['refund'] is False
    assert finish[0]['completed_native_accounts']==5
    assert not list(root.glob('research-results/*'))


@pytest.mark.parametrize('change',['unequal_intended','annual_benchmark','extra_uncertainty','zero_denominator','negative_factor'])
def test_closed_passive_profile_rejects_drift(tmp_path,monkeypatch,change):
    _,_,p,_=passive_fixture(tmp_path,monkeypatch)
    if change=='unequal_intended':p['legs'][1]['weights'][p['symbols'][0]]=[1,4]
    elif change=='annual_benchmark':p['legs'][1]['rule']='FIXED_WEIGHTS'
    elif change=='extra_uncertainty':p['uncertainty']={'seed':1}
    else:p['criteria'][0]['factor']=[101,0] if change=='zero_denominator' else [-101,100]
    with pytest.raises(ValueError):profile_value(p)


def test_terminal_factor_exact_boundary_and_legacy_rejection(tmp_path,monkeypatch):
    import polar.scheduled_policy as m
    _,_,p,_=passive_fixture(tmp_path,monkeypatch);profile_value(p)
    legacy=deepcopy(p);legacy['schema']='polar.scheduled-reference-profile/8';legacy['policy']={'kind':'FIXED_ANNUAL_RATIONAL_WEIGHTS'}
    for x in legacy['legs']:
        if x['rule']=='INITIAL_TARGET_ONLY':x['rule']='FIXED_WEIGHTS'
    with pytest.raises(ValueError,match='CRITERION_FACTOR'):profile_value(legacy)
    p['criteria']=p['criteria'][:1]
    # Only criterion arithmetic under test, no source or native engine.
    metrics={k:{'value':'0','status':'OK','reason':None} for k in ('terminal_nav_usd','net_cagr_act36525','sharpe_252_rf0','max_drawdown','total_cost_usd')}
    def evaluation(terminal):
        monkeypatch.setattr(m,'evaluate_legs',lambda sim:([{'id':x['id'],'metrics':metrics} for x in p['legs']],
          {x['id']:{'terminal':terminal if x['id']=='THIRDS' else 10000,'max_drawdown':0} for x in p['legs']}))
        return evaluate_policy({'legs':[{'nav':[{},{}]}]},p,'FINAL')['criteria'][0]['status']
    assert evaluation(10100)=='MET' and evaluation(10099)=='NOT_MET'


@pytest.mark.parametrize('tamper,error',[('instructions','PASSIVE_SAVED_INSTRUCTIONS'),('control','INITIAL_STATE_CONTROL_BINDING')])
def test_rehashed_saved_passive_or_control_drift_rejected_without_source(tmp_path,monkeypatch,tamper,error):
    import polar.scheduled_service as m
    root,cfg,_,_=passive_fixture(tmp_path,monkeypatch);service=ReferenceResearchService(root,128*1024**2)
    result=service.run(cfg);directory=root/'reference-research-experiments'/result['semantic_id']
    manifest=json.loads((directory/'manifest.json').read_bytes());files={n:(directory/n).read_bytes() for n in manifest['files']}
    phases=json.loads(files['phases.json'])
    if tamper=='control':
        for phase in phases.values():del phase['initial_state_control']
    else:
        for phase in phases.values():
            phase['plan']['decisions'][1]['instructions']['ALTERNATE']={'kind':'TARGET','weights':phase['plan']['decisions'][0]['instructions']['ALTERNATE']['weights'],'signal':{'kind':'FIXED_DECLARED_WEIGHTS'}}
    files['phases.json']=m.canonical(phases);manifest['files']={n:{'sha256':m.sha(b),'bytes':len(b)} for n,b in files.items()}
    raw=m.canonical(manifest);sid=m.SEMANTIC+m.sha(raw);target=root/'reference-research-experiments'/sid;target.mkdir()
    for name,body in {**files,'manifest.json':raw}.items():(target/name).write_bytes(body)
    def forbidden(*a,**k):raise AssertionError('UNEXPECTED_SOURCE_POLICY_NATIVE')
    for name in ('load_reference','plan_phase','bounded_native'):monkeypatch.setattr(m,name,forbidden)
    before=snapshot(root)
    with pytest.raises(ValueError,match=error):service.recompute(sid)
    assert snapshot(root)==before
