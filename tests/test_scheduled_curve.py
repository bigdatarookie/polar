"""Invented-only curve adapter and actual native/accounting/stored controls."""
from copy import deepcopy
from datetime import date,timedelta
from pathlib import Path
from fractions import Fraction
import json
import pytest

from curve_fixture import fixture
from reference_fixture import write
from test_scheduled_service import snapshot
from polar.gym_contract import canonical,sha
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from polar.scheduled_policy import profile_value,calendar_value,evaluate_policy
from polar.scheduled_service import load_market
from polar.scheduled_curve import metadata,context,date_joins,plan_phase,verify_plan,expected_counts,CurveError,diagnose_curve


def setup_plan(tmp_path,monkeypatch):
    root,cfg,p,c,d=fixture(tmp_path,monkeypatch)
    market=load_market(cfg,p);grid=c['phases']['FINAL']
    return root,cfg,p,c,d,market,grid


def test_metadata_lag_clock_no_value_reader_and_source_only_dates(tmp_path,monkeypatch):
    root,cfg,p,c,d=fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    import polar.scheduled_curve as curve
    original=curve.pinned_bytes
    def no_tokens(pin):
        assert pin['sha256']!=d['macro_records_ref']['sha256']
        return original(pin)
    monkeypatch.setattr(curve,'pinned_bytes',no_tokens)
    monkeypatch.setattr(module,'load_market',lambda *a:(_ for _ in ()).throw(AssertionError('VALUE_LOAD_BEFORE_START')))
    ready=ReferenceResearchService(root,256*1024**2).preflight(cfg)
    assert ready['expected_native_accounts']==8 and ready['expected_feature_counts']==expected_counts(47)
    assert not (root/'scheduled-reference-attempts').exists()
    value=metadata(cfg['input_ref'],'INVENTED');equity=json.loads(Path(d['reference_input_ref']['path']).read_bytes())
    schedule=json.loads(Path(equity['schedule']['path']).read_bytes())['rows']
    joins=date_joins(value,p,schedule,c['phases'])
    assert len(joins)==47 and all(j['known_ns']<j['decision_ns']<j['close_ns'] for j in joins)
    monday=next(j for j in joins if date.fromisoformat(j['formation_date']).weekday()==0)
    assert monday['cutoff_date']!=(date.fromisoformat(monday['formation_date'])-timedelta(days=2)).isoformat()
    assert any(date.fromisoformat(j['source_date']).weekday()==6 for j in joins)


def test_exact_positive_zero_negative_and_cached_target_certificates(tmp_path,monkeypatch):
    _,_,p,c,_,market,g=setup_plan(tmp_path,monkeypatch)
    plan=plan_phase(market,p,g,None);verify_plan(plan,p,market['schedule'],g)
    weights=set()
    for w,e in zip(plan['signals'],plan['decisions']):
        tokens=w['source_row']['tokens'];spread=Fraction(tokens['BC_10YEAR'])-Fraction(tokens['BC_2YEAR'])
        assert w['spread']==[str(spread.numerator),str(spread.denominator)]
        weight=w['targets']['CURVE_VTI']['VTI'];weights.add(tuple(weight));assert weight==[int(spread>0),1]
        assert all(x['kind']=='TARGET' for x in e['instructions'].values())
        assert e['instructions']['CASH']['weights']=={'VTI':[0,1]}
        assert w['targets']['HALF_VTI']=={'VTI':[1,2]}
    assert weights=={(0,1),(1,1)}
    assert any(w['spread'][0]=='0' for w in plan['signals'])
    assert any(Fraction(*map(int,w['spread']))==Fraction(1,10**37) for w in plan['signals'])
    assert plan['actual_feature_counts']==expected_counts(47)
    assert len(plan['decisions'])==48 and all(x=={'kind':'EXIT'} for x in plan['decisions'][-1]['instructions'].values())
    for mutation in ('target','clock','raw'):
        bad=deepcopy(plan)
        if mutation=='target':bad['signals'][0]['targets']['CASH']['VTI']=[1,1]
        elif mutation=='clock':bad['decisions'][0]['decision_ns']+=1
        else:bad['signals'][0]['source_row']['tokens']['BC_10YEAR']='999'
        w=bad['signals'][0];w['seal_sha256']=sha(canonical({k:v for k,v in w.items() if k!='seal_sha256'}))
        with pytest.raises(ValueError,match='CURVE_SAVED_'):verify_plan(bad,p,market['schedule'],g)


@pytest.mark.parametrize('mutation',['duplicate','missing','conflict','terminal'])
def test_bad_metadata_before_start_or_price_load(tmp_path,monkeypatch,mutation):
    root,cfg,p,c,d=fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as service
    monkeypatch.setattr(service,'load_market',lambda *a:(_ for _ in ()).throw(AssertionError('NO_VALUES')))
    if mutation!='terminal':
        ix=json.loads(Path(d['macro_index_ref']['path']).read_bytes())
        if mutation=='duplicate':ix['records'][1]['date']=ix['records'][0]['date']
        elif mutation=='missing':ix['records'][0]['fields']=['BC_2YEAR']
        else:ix['records'][0]['conflict']=True
        d['macro_index_ref']=write(tmp_path/'bad-index.json',ix);cfg['input_ref']=write(tmp_path/'bad-input.json',d)
        p['input_sha256']=cfg['input_ref']['sha256'];cfg['profile_ref']=write(tmp_path/'bad-profile.json',p)
        with pytest.raises(ValueError):ReferenceResearchService(root,256*1024**2).preflight(cfg)
    else:
        equity=json.loads(Path(d['reference_input_ref']['path']).read_bytes());rows=json.loads(Path(equity['schedule']['path']).read_bytes())['rows']
        rows[-1]['reference_close_utc']=rows[-1]['date']+'T00:00:00+00:00'
        with pytest.raises(ValueError,match='CURVE_TERMINAL_K_D_Q'):date_joins(metadata(cfg['input_ref'],'INVENTED'),p,rows,c['phases'])
    assert not (root/'scheduled-reference-attempts').exists()


@pytest.mark.parametrize('age,valid',[(10,True),(11,False)])
def test_exact_age_boundary_metadata_only(tmp_path,monkeypatch,age,valid):
    _,cfg,p,c,d=fixture(tmp_path,monkeypatch)
    equity=json.loads(Path(d['reference_input_ref']['path']).read_bytes());rows=json.loads(Path(equity['schedule']['path']).read_bytes())['rows']
    value=metadata(cfg['input_ref'],'INVENTED');ix=json.loads(value['index_raw']);proof=json.loads(value['joins_raw'])
    cutoff=proof['joins'][0]['cutoff_date'];old=proof['joins'][0]['selected_treasury_date']
    old_age=proof['joins'][0]['civil_age_days'];shift=age-old_age
    for r in ix['records']:
        if r['date']<=cutoff:r['date']=(date.fromisoformat(r['date'])-timedelta(days=shift)).isoformat()
    proof['joins'][0]['selected_treasury_date']=(date.fromisoformat(old)-timedelta(days=shift)).isoformat();proof['joins'][0]['civil_age_days']=age
    value['index_raw']=canonical(ix).decode();value['joins_raw']=canonical(proof).decode()
    desc=json.loads(value['descriptor_raw']);desc['macro_index_ref']['sha256']=sha(value['index_raw'].encode());desc['source_date_join_ref']['sha256']=sha(value['joins_raw'].encode())
    value['descriptor_raw']=canonical(desc).decode();p['input_sha256']=sha(value['descriptor_raw'].encode())
    if valid:assert date_joins(value,p,rows,c['phases'])[0]['civil_age_days']==10
    else:
        with pytest.raises(ValueError,match='CURVE_SOURCE_AGE'):date_joins(value,p,rows,c['phases'])


def test_eight_native_true_costs_consumed_operands_and_source_absent_stored(tmp_path,monkeypatch):
    root,cfg,p,c,d=fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    actual=module.plan_phase;called=[]
    def once(*a,**k):called.append(1);assert len(list(root.rglob('start.json')))==1;return actual(*a,**k)
    monkeypatch.setattr(module,'plan_phase',once)
    service=ReferenceResearchService(root,256*1024**2);result=service.run(cfg)
    assert result['status']=='SUCCESS' and result['native_accounts']==8 and len(called)==1
    assert result['actual_feature_counts']==expected_counts(47)
    home=root/'reference-research-experiments'/result['semantic_id'];phases=json.loads((home/'phases.json').read_bytes())
    base,stress=phases['FINAL'],phases['FINAL_COST_STRESS']
    assert {k:v for k,v in base['plan'].items() if k!='cost_profile'}=={k:v for k,v in stress['plan'].items() if k!='cost_profile'}
    for phase in (base,stress):
        for leg in phase['simulation']['legs']:
            assert len(leg['intents'])==48 and len(leg['intents'][:-1])==47
            assert leg['intents'][-1]['sizing_status']=='NOT_APPLICABLE_EXIT'
            for intent in leg['intents'][:-1]:
                w=intent['sizing_witness'];assert w['nav_cents']==w['cash_cents']+sum(round(Fraction(w['holdings'][s]*w['eligible_prices_micro'][s],10000)) for s in w['holdings'])
                assert w['targets']==intent['targets'] and w['eligible_quote']['date']==intent['formation']
                for s,t in w['targets'].items():assert t==w['nav_cents']*10000*w['weights'][s][0]//(w['eligible_prices_micro'][s]*w['weights'][s][1])
            for order in leg['orders']:
                w=order['consumed_operands'];assert w['desired_delta']==order['intended_quantity']
                assert w['cost_profile']==phase['cost_scenario']['cost_profile']
                if order['side']=='BUY':assert w['affordability']['returned_quantity']==order['routed_quantity']
            assert all(f['fee_cents']>=phase['cost_scenario']['cost_profile']['flat_cents'] for f in leg['fills'])
        rec=ResearchResults(root,256*1024**2).read(result['results']['FINAL' if phase is base else 'FINAL_COST_STRESS']['result_id'])['record']
        assert len(rec['metrics'])<=40 and len(rec['limitations'])<=30 and len(rec['series'])==4
    diag=json.loads((home/'diagnostics.json').read_bytes())
    for name,v in diag['FINAL'].items():
        assert v['subperiods'][1]['initial_date']=='2024-12-31'
        assert v['subperiods'][1]['first_return_date']>'2024-12-31'
    assert all(x['subperiods']==[] for x in diag['FINAL_COST_STRESS'].values())
    before=snapshot(root)
    def forbidden(*a,**k):raise AssertionError('SOURCE_OR_ORIGINAL_POLICY_NATIVE_DURING_STORED')
    import polar.scheduled_curve as curve
    for n in ('load_reference','load_market','plan_phase','bounded_native'):monkeypatch.setattr(module,n,forbidden)
    monkeypatch.setattr(curve,'load_market',forbidden);monkeypatch.setattr(curve,'plan_phase',forbidden)
    for path in tmp_path.iterdir():
        if path.is_file():path.unlink()
    stored=service.recompute(result['semantic_id']);assert stored['status']=='REPRODUCED' and stored['actual_feature_counts']==expected_counts(0)
    assert stored['native_calls']==stored['store_writes']==stored['model_calls']==0 and snapshot(root)==before
