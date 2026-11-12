"""Invented exact relative-lag, shared-service lifecycle and saved-certificate checks."""
from copy import deepcopy
from fractions import Fraction
import hashlib,json
from pathlib import Path
from zoneinfo import ZoneInfo,TZPATH
import pytest
from reference_fixture import write
from scheduled_fixture import inverse_fixture
from test_scheduled_service import snapshot
from polar.scheduled_policy import profile_value,calendar_value,plan_phase
from polar.scheduled_relative import verify_plan,expected_counts,RelativeSignalError,diagnose_relative
from polar.reference_service import ReferenceResearchService
from polar.research_reference import load_reference
from polar.research_results import ResearchResults
from polar.gym_contract import canonical,sha


def relative_fixture(tmp_path,monkeypatch):
    root,cfg,p,c=inverse_fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes());symbols=manifest['symbols'][:3]
    quotes=[json.loads(line) for line in Path(manifest['quotes']['path']).read_text().splitlines()]
    quotes=[q for q in quotes if q['symbol'] in symbols]
    qp=tmp_path/'relative-quotes.ndjson';qp.write_bytes(b''.join(canonical(q) for q in quotes))
    manifest.update(symbols=symbols,rows=len(quotes),quotes={'path':str(qp),'sha256':sha(qp.read_bytes()),'bytes':qp.stat().st_size})
    mp=write(tmp_path/'relative-input.json',manifest)
    tz=tmp_path/'UTC';source=next((Path(d)/'UTC' for d in TZPATH if (Path(d)/'UTC').is_file()),None)
    if source:tz.write_bytes(source.read_bytes())
    else:
        from importlib.resources import files
        tz.write_bytes(files('tzdata').joinpath('zoneinfo/UTC').read_bytes())
    tzref={'path':str(tz),'sha256':sha(tz.read_bytes()),'bytes':tz.stat().st_size}
    nav=c['phases']['FINAL']['nav_dates']
    p.update(schema='polar.scheduled-reference-profile/7',protocol_id='INVENTED-EXACT-RELATIVE-V1',
        input_sha256=mp['sha256'],timezone_sha256=tzref['sha256'],symbols=symbols,decision_delay_seconds=60,
        policy={'kind':'RELATIVE_MOMENTUM_EXACT_LAGS','lookback':252,'skip':21,'full_symbol':'CCC','drawdown_peak':'LATEST_EQUAL_PEAK'},
        legs=[{'id':i,'label':i,'rule':r,'scale':[1,1]} for i,r in
            [('MOM','RELATIVE_MOMENTUM'),('EW','EQUAL_WEIGHT'),('FULL','FULL'),('CASH','CASH')]],
        primary_strategy='MOM',primary_benchmark='EW',
        uncertainty={'kind':'RELATIVE_PAIRED_DESCRIPTIVE','block':63,'replicates':1000,'seed':37004},
        clock_description='Counterfactual UTC midnight K, D+60 seconds and pinned reference close.',
        subperiods=[[nav[1],nav[15]],[nav[16],nav[30]],[nav[31],nav[-1]]])
    p['criteria']=[{'kind':k,'id':k,'description':k,'left_id':'MOM',
        **({'right_id':'EW'} if k!='POSITIVE_GROWTH' else {}),**({'threshold':'0.10'} if k=='SR_DELTA_GE' else {})}
        for k in ['TERMINAL_GT','SR_DELTA_GE','DRAWDOWN_LE','VOL_LE','POSITIVE_GROWTH']]
    pp=write(tmp_path/'relative-profile.json',p)
    return root,{**cfg,'input_ref':mp,'profile_ref':pp,'timezone_ref':tzref,'candidate_id':'INVENTED-RELATIVE',
                'experiment_id':'INVENTED-RELATIVE-ORIGINAL'},p,c


def prepared(tmp_path,monkeypatch):
    root,cfg,p,c=relative_fixture(tmp_path,monkeypatch);m=load_reference(cfg['input_ref']);g=calendar_value(c,m['schedule'])['FINAL']
    return root,cfg,p,c,m,g


def test_exact_skip_endpoint_negative_top1_ties_and_no_quantization(tmp_path,monkeypatch):
    _,_,p,_,m,g=prepared(tmp_path,monkeypatch)
    d=g['decisions'][0]['signal_date'];i=m['dates'].index(d);a,b=m['dates'][i-252],m['dates'][i-21]
    for s in p['symbols']:m['prices_micro'][a][s]=10**18;m['prices_micro'][b][s]=10**18-2
    m['prices_micro'][b]['BBB']+=1
    # All negative, a one-in-1e18 difference wins even though 12dp quantizes it.
    plan=plan_phase(m,p,g,ZoneInfo('UTC'));w=plan['signals'][0]
    assert w['rank']==['BBB','AAA','CCC'] and w['winner']=='BBB'
    assert w['operand_dates']==[a,b] and w['targets']['CASH']=={s:[0,1] for s in p['symbols']}
    changed=deepcopy(m)
    for date in m['dates'][i-20:]:
        for s in p['symbols']:changed['prices_micro'][date][s]*=7
    other=plan_phase(changed,p,g,ZoneInfo('UTC'))
    assert other['signals'][0]==w and other['decisions'][0]==plan['decisions'][0]
    m['prices_micro'][b]['BBB']-=1
    assert plan_phase(m,p,g,ZoneInfo('UTC'))['signals'][0]['rank']==['AAA','BBB','CCC']
    assert all(x['kind']=='TARGET' for e in plan['decisions'][:-1] for x in e['instructions'].values())
    assert all(x=={'kind':'EXIT'} for x in plan['decisions'][-1]['instructions'].values())
    assert plan['actual_signal_counts']==expected_counts(len(g['decisions']))
    assert plan['decisions'][0]['known_ns']%86400000000000==0
    assert plan['decisions'][0]['decision_ns']-plan['decisions'][0]['known_ns']==60000000000


def test_saved_certificate_rejects_rehashed_operand_rank_target_and_clock_tamper(tmp_path,monkeypatch):
    _,_,p,_,m,g=prepared(tmp_path,monkeypatch);plan=plan_phase(m,p,g,ZoneInfo('UTC'))
    verify_plan(plan,p,m['schedule'],g)
    for mutation in ['operand','rank','target','clock']:
        bad=deepcopy(plan);w=bad['signals'][0]
        if mutation=='operand':w['operands'][0]['end_micro']+=1
        if mutation=='rank':w['rank'].reverse();w['winner']=w['rank'][0]
        if mutation=='target':w['targets']['CASH']['AAA']=[1,1]
        if mutation=='clock':bad['decisions'][0]['known_ns']+=1
        w['seal_sha256']=sha(canonical({k:v for k,v in w.items() if k!='seal_sha256'}))
        with pytest.raises(ValueError,match='SCHEDULED_RELATIVE_'):verify_plan(bad,p,m['schedule'],g)


def test_invalid_signal_keeps_partial_counts_and_durable_debit(tmp_path,monkeypatch):
    root,cfg,p,c,m,g=prepared(tmp_path,monkeypatch)
    i=m['dates'].index(g['decisions'][0]['signal_date']);m['prices_micro'][m['dates'][i-21]]['BBB']=0
    import polar.scheduled_service as service
    monkeypatch.setattr(service,'load_reference',lambda *a,**k:m)
    with pytest.raises(RelativeSignalError):ReferenceResearchService(root,256*1024**2).run(cfg)
    finish=json.loads(next((root/'scheduled-reference-attempts').rglob('record.json')).read_bytes())
    assert finish['scientific_status']=='INVALID' and finish['refund'] is False
    assert finish['actual_signal_counts']=={'score_calls':2,'completed_scores':1,'operand_reads':4,'rank_calls':0,'completed_decisions':0}
    with pytest.raises(ValueError,match='ORIGINAL_ALREADY_RECORDED'):ReferenceResearchService(root,256*1024**2).run(cfg)


def test_original_stress_shared_once_metadata_prestart_and_stored_zero(tmp_path,monkeypatch):
    root,cfg,p,c=relative_fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    import polar.scheduled_relative as planner
    def forbidden(*a,**k):raise AssertionError('SOURCE_POLICY_NATIVE_OR_TARGET_CALL_FORBIDDEN')
    actual=module.load_reference;monkeypatch.setattr(module,'load_reference',forbidden)
    service=ReferenceResearchService(root,256*1024**2);ready=service.preflight(cfg)
    n=c['phases']['FINAL']['decision_count'];assert ready['expected_native_accounts']==8 and ready['expected_signal_counts']==expected_counts(n)
    def after_start(*a,**k):
        assert len(list((root/'scheduled-reference-attempts').rglob('start.json')))==1
        return actual(*a,**k)
    monkeypatch.setattr(module,'load_reference',after_start)
    real=planner.plan_phase;calls=[]
    def observed(*a,**k):calls.append('ONCE');return real(*a,**k)
    monkeypatch.setattr(planner,'plan_phase',observed)
    result=service.run(cfg);assert calls==['ONCE'] and result['native_accounts']==8
    assert result['actual_signal_counts']==expected_counts(n) and result['estimator_calls']==result['optimizer_calls']==0
    folder=root/'reference-research-experiments'/result['semantic_id'];phases=json.loads((folder/'phases.json').read_bytes())
    base=phases['FINAL']['plan'];stress=phases['FINAL_COST_STRESS']['plan']
    assert {k:v for k,v in base.items() if k!='cost_profile'}=={k:v for k,v in stress.items() if k!='cost_profile'}
    diagnostics=json.loads((folder/'diagnostics.json').read_bytes())
    assert len(diagnostics['FINAL']['MOM']['subperiods'])==3 and diagnostics['FINAL_COST_STRESS']['MOM']['subperiods']==[]
    assert diagnostics['FINAL']['CASH']['drawdown']['status']=='NO_DRAWDOWN'
    assert all(diagnostics['FINAL']['CASH']['drawdown'][k] is None for k in ['peak','trough','recovery'])
    assert len([x for x in phases['FINAL']['evaluation']['comparisons'] if x['metric_id']=='annual_vol_252'])==3
    uncertainty=json.loads((folder/'uncertainty.json').read_bytes())
    assert uncertainty['seed']==37004 and uncertainty['benchmark_ids']==['EW','FULL']
    assert uncertainty['robustness']=='INSUFFICIENT_EVIDENCE' and len(uncertainty['replicates'])==1000
    assert all('median' in c['sr_delta'] for c in uncertainty['comparisons'])
    for pub in result['results'].values():
        record=ResearchResults(root,256*1024**2).read(pub['result_id'])['record']
        assert len(record['series'])==4 and len(record['criteria'])==5 and len(record['metrics'])<=40 and len(record['limitations'])<=30
        assert any(l['code']=='EXACT_RELATIVE_SIGNAL_ACCOUNTING' for l in record['limitations'])
    before=snapshot(root)
    for name in ['load_reference','plan_phase','bounded_native']:monkeypatch.setattr(module,name,forbidden)
    monkeypatch.setattr(planner,'plan_phase',forbidden);monkeypatch.setattr(planner,'_weights',forbidden)
    answer=service.recompute(result['semantic_id']);assert answer['status']=='REPRODUCED' and answer['actual_signal_counts']==expected_counts(0)
    assert snapshot(root)==before


def test_relative_latest_equal_peak_and_legacy_unchanged():
    from polar.scheduled_diagnostics import _drawdown
    rows=[{'date':str(i),'nav_cents':n,'nominal_ns':i*10**9} for i,n in enumerate([100,100,80,100])]
    assert _drawdown(rows)['peak']['date']=='0' and _drawdown(rows,latest_equal_peak=True)['peak']['date']=='1'


@pytest.mark.parametrize('field,value',[('skip',0),('lookback',251),('drawdown_peak','EARLIEST_PEAK')])
def test_profile_rejects_alternate_lookback_skip_or_peak(tmp_path,monkeypatch,field,value):
    _,_,p,_=relative_fixture(tmp_path,monkeypatch);p['policy'][field]=value
    with pytest.raises(ValueError,match='RELATIVE_POLICY'):profile_value(p)


def test_metadata_rejects_wrong_timezone_before_any_source_read(tmp_path,monkeypatch):
    root,cfg,p,_=relative_fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    source=next((Path(d)/'America/New_York' for d in TZPATH if (Path(d)/'America/New_York').is_file()),None)
    if source:raw=source.read_bytes()
    else:
        from importlib.resources import files
        raw=files('tzdata').joinpath('zoneinfo/America/New_York').read_bytes()
    tz=tmp_path/'wrong-zone';tz.write_bytes(raw);ref={'path':str(tz),'bytes':len(raw),'sha256':sha(raw)}
    p['timezone_sha256']=ref['sha256'];cfg={**cfg,'timezone_ref':ref,'profile_ref':write(tmp_path/'wrong-zone-profile.json',p)}
    def forbidden(*a,**k):raise AssertionError('QUOTE_READ_BEFORE_START')
    monkeypatch.setattr(module,'load_reference',forbidden)
    with pytest.raises(ValueError,match='RELATIVE_UTC_METADATA'):ReferenceResearchService(root,256*1024**2).preflight(cfg)
    assert not (root/'scheduled-reference-attempts').exists()
