"""Invented temporal-policy integration on the existing no-fit service."""
from copy import deepcopy
from datetime import date,timedelta
import hashlib,json
from pathlib import Path
from fractions import Fraction

import pytest
from reference_fixture import write
from scheduled_fixture import inverse_fixture
from test_scheduled_service import snapshot
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from polar.scheduled_policy import profile_value,calendar_value,plan_phase
from polar.scheduled_temporal_plan import verify_plan
from polar.scheduled_uncertainty import _temporal_interval
from polar.research_reference import load_reference
from zoneinfo import ZoneInfo


def temporal_fixture(tmp_path,monkeypatch):
    root,cfg,profile,_=inverse_fixture(tmp_path,monkeypatch)
    manifest=json.loads(Path(cfg['input_ref']['path']).read_bytes())
    days=[(date(2014,1,1)+timedelta(days=i)).isoformat() for i in range(1800)]
    rows=[];quotes=[]
    for i,d in enumerate(days):
        rows.append({'date':d,'reference_open_utc':d+'T14:30:00+00:00','reference_close_utc':d+'T21:00:00+00:00',
            'next_reference_date':days[i+1] if i+1<len(days) else None,
            'month_end_in_reference_range':days[i+1][:7]!=d[:7] if i+1<len(days) else None})
        for j,s in enumerate(manifest['symbols']):
            token=f'{100+(i//100)}.{(i*7+j*3)%99:02d}0000'
            quotes.append({'symbol':s,'date':d,'reference_quote':token,'source_adjusted_close_token':token,
                'source_ref':{'normalized_member_sha256':'a'*64,'line_1based':i+1,'line_sha256':'b'*64,
                    'raw_object_sha256':'c'*64,'source_row_index':i},'observed_published_at':None,'observed_historical_available_at':None})
    sp=write(tmp_path/'temporal-schedule.json',{'schema':'polar.xnys-reference-schedule/1','rows':rows})
    qp=tmp_path/'temporal-quotes.ndjson';qp.write_bytes(b''.join((json.dumps(q,sort_keys=True,separators=(',',':'))+'\n').encode() for q in quotes))
    manifest.update(schedule=sp,quotes={'path':str(qp),'sha256':hashlib.sha256(qp.read_bytes()).hexdigest(),'bytes':qp.stat().st_size},
        dates={'count':len(days),'start':days[0],'end':days[-1]},rows=len(quotes))
    mp=write(tmp_path/'temporal-manifest.json',manifest)
    nav=days[-50:];decisions=[{'signal_date':d,'signal_index':days.index(d),'execution_date':days[days.index(d)+1],
        'execution_reference_close_utc':rows[days.index(d)+1]['reference_close_utc']} for d in nav[:-2]
        if rows[days.index(d)]['month_end_in_reference_range']]
    calendar={'schema':'polar.scheduled-policy-calendar/1','source_schedule':sp,
        'phases':{'FINAL':{'initial':nav[0],'terminal':nav[-1],'nav_dates':nav,'nav_points':len(nav),
            'return_count':len(nav)-1,'decisions':decisions,'decision_count':len(decisions)}}}
    cp=write(tmp_path/'temporal-calendar.json',calendar)
    profile.update(schema='polar.scheduled-reference-profile/6',protocol_id='INVENTED-TEMPORAL-V1',
        symbols=['AAA'],input_sha256=mp['sha256'],calendar_sha256=cp['sha256'],
        policy={'kind':'TEMPORAL_VOLATILITY','lookback':60,'annual_cap':'0.10','calibration':[days[0],days[1258]]},
        legs=[{'id':i,'label':i,'rule':rule,'scale':[1,1]} for i,rule in
            [('TIME','TEMPORAL_VOL'),('STATIC','STATIC_VOL'),('FULL','FULL'),('CASH','CASH')]],
        primary_strategy='TIME',primary_benchmark='STATIC',
        uncertainty={'kind':'TEMPORAL_PAIRED_DESCRIPTIVE','block':63,'replicates':1000,'seed':37003},
        subperiods=[[nav[1],nav[20]],[nav[21],nav[-1]]])
    profile['criteria']=[{'kind':kind,'id':kind,'description':kind,'left_id':'TIME',
        **({'right_id':'STATIC'} if kind!='POSITIVE_GROWTH' else {}),**extra} for kind,extra in
        [('TERMINAL_GT',{}),('SR_DELTA_GE',{'threshold':'0.10'}),('DRAWDOWN_LE',{}),
         ('VOL_RATIO_BETWEEN',{'lower':'0.8','upper':'1.25'}),('POSITIVE_GROWTH',{})]]
    pp=write(tmp_path/'temporal-profile.json',profile)
    return root,{**cfg,'input_ref':mp,'profile_ref':pp,'calendar_ref':cp,'candidate_id':'INVENTED-TEMPORAL',
        'experiment_id':'INVENTED-TEMPORAL-ORIGINAL'},profile,calendar


def test_temporal_metadata_no_read_original_once_stress_reuse_and_stored_zero(tmp_path,monkeypatch):
    root,cfg,profile,calendar=temporal_fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as service_module
    import polar.scheduled_temporal_plan as planner
    actual=service_module.load_reference
    def forbidden(*a,**k):raise AssertionError('FORBIDDEN_STORED_OR_PRESTART_CALL')
    monkeypatch.setattr(service_module,'load_reference',forbidden)
    service=ReferenceResearchService(root,256*1024**2)
    ready=service.preflight(cfg);n=calendar['phases']['FINAL']['decision_count']
    assert ready['expected_native_accounts']==8
    assert ready['expected_estimator_counts']=={'estimator_calls':n+1,'calibration_estimates':1,'rolling_estimates':n,'completed_estimates':n+1}
    def after_start(*a,**k):
        assert len(list((root/'scheduled-reference-attempts').rglob('start.json')))==1
        return actual(*a,**k)
    monkeypatch.setattr(service_module,'load_reference',after_start)
    original=planner.estimate_temporal;calls=[]
    def observed(*a,**k):calls.append(k['kind']);return original(*a,**k)
    monkeypatch.setattr(planner,'estimate_temporal',observed)
    answer=service.run(cfg)
    assert answer['native_accounts']==8 and answer['actual_estimator_counts']==ready['expected_estimator_counts']
    assert calls==['STATIC_CALIBRATION']+['ROLLING_60']*n
    folder=root/'reference-research-experiments'/answer['semantic_id']
    phases=json.loads((folder/'phases.json').read_bytes())
    base=phases['FINAL']['plan'];stress=phases['FINAL_COST_STRESS']['plan']
    assert {k:v for k,v in base.items() if k!='cost_profile'}=={k:v for k,v in stress.items() if k!='cost_profile'}
    uncertainty=json.loads((folder/'uncertainty.json').read_bytes())
    assert uncertainty['samples']==1000 and uncertainty['seed']==37003 and uncertainty['robustness']=='INSUFFICIENT_EVIDENCE'
    assert uncertainty['benchmark_ids']==['STATIC','FULL']
    assert all('median' in c['sr_delta'] for c in uncertainty['comparisons'])
    for phase,pub in answer['results'].items():
        d=ResearchResults(root,256*1024**2).read(pub['result_id'])
        assert len(d['record']['series'])==4 and len(d['record']['criteria'])==5
        assert d['assessment']['financial']=='NOT_REVIEWED'
    before=snapshot(root)
    for name in ('load_reference','plan_phase','bounded_native'):monkeypatch.setattr(service_module,name,forbidden)
    monkeypatch.setattr(planner,'estimate_temporal',forbidden)
    result=service.recompute(answer['semantic_id'])
    assert result['status']=='REPRODUCED' and not any(result['actual_estimator_counts'].values())
    assert snapshot(root)==before
    with pytest.raises(ValueError,match='ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_temporal_causal_cutoff_and_saved_target_tamper(tmp_path,monkeypatch):
    _,cfg,p,c=temporal_fixture(tmp_path,monkeypatch)
    m=load_reference(cfg['input_ref']);g=calendar_value(c,m['schedule'])['FINAL'];tz=ZoneInfo('America/New_York')
    a=plan_phase(m,p,g,tz);altered=deepcopy(m);cutoff=g['decisions'][0]['signal_date']
    for d in altered['dates']:
        if d>cutoff:altered['prices_micro'][d]['AAA']*=2
    b=plan_phase(altered,p,g,tz)
    assert a['decisions'][0]==b['decisions'][0] and a['signals'][0]==b['signals'][0]
    assert a['temporal_calibration']==b['temporal_calibration']
    verify_plan(a,p,m['schedule'])
    bad=deepcopy(a);bad['decisions'][0]['instructions']['TIME']['weights']['AAA']=[1,1]
    # This invented sample caps some weights at one; force a distinct target.
    bad['decisions'][0]['instructions']['TIME']['weights']['AAA']=[0,1]
    with pytest.raises(ValueError,match='TARGET_BINDING'):verify_plan(bad,p,m['schedule'])
    bad=deepcopy(a);bad['prices'][p['policy']['calibration'][0]]['AAA']['close_micro']+=1
    with pytest.raises(ValueError,match='OPERAND_BINDING'):verify_plan(bad,p,m['schedule'])


def test_temporal_invalid_estimate_retains_partial_debit_and_count(tmp_path,monkeypatch):
    root,cfg,p,c=temporal_fixture(tmp_path,monkeypatch)
    import polar.scheduled_service as module
    real=module.load_reference
    def constant(*a,**k):
        m=real(*a,**k)
        for d in m['dates']:m['prices_micro'][d]['AAA']=100000000
        return m
    monkeypatch.setattr(module,'load_reference',constant)
    service=ReferenceResearchService(root,256*1024**2)
    with pytest.raises(ValueError,match='NONPOSITIVE_VARIANCE'):service.run(cfg)
    finish=json.loads(next((root/'scheduled-reference-attempts').rglob('record.json')).read_bytes())
    assert finish['scientific_status']=='INVALID' and finish['refund'] is False
    assert finish['actual_estimator_counts']=={'estimator_calls':1,'calibration_estimates':1,'rolling_estimates':0,'completed_estimates':0}
    with pytest.raises(ValueError,match='ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_inverse_cdf_quantiles_and_latest_equal_peak_are_versioned():
    from polar.scheduled_diagnostics import _drawdown
    assert _temporal_interval([Fraction(i) for i in range(1000)],{},1000)['upper_order_index']==974
    assert _temporal_interval([Fraction(i) for i in range(1000)],{},1000)['median_order_index']==499
    assert _temporal_interval([],{'ZERO_VARIANCE':1000},1000)['status']=='UNAVAILABLE'
    nav=[{'date':str(i),'nav_cents':n,'nominal_ns':i*10**9} for i,n in enumerate([100,100,80,100])]
    assert _drawdown(nav)['peak']['date']=='0'
    assert _drawdown(nav,latest_equal_peak=True)['peak']['date']=='1'
