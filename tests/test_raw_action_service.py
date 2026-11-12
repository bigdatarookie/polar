"""Invented source schema/native lifecycle/private graph and source-absent replay."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
from dataclasses import replace
import json
import os
import subprocess

import pytest

from polar.gym_contract import canonical,sha
from polar.gym_service import code_binding
from polar.ci_research_service import root_identity
from polar.reference_service import ReferenceResearchService
from polar.raw_action_input import metadata,calendar
from polar.raw_action_service import COSTS
from polar.raw_action_native import LEGS,terminal_check
from polar.raw_action_evaluation import initial_control
from polar.distribution_claims import Action,State,Phase,recognize,pay,settled_snapshot,valuation


def write(path,value):
    raw=canonical(value) if not isinstance(value,bytes) else value
    path.write_bytes(raw);return {'path':str(path),'sha256':sha(raw),'bytes':len(raw)}


def fixture(tmp_path):
    days=['2019-12-30','2019-12-31','2020-01-02','2020-01-03','2020-12-31','2021-01-04','2021-01-05']
    rows=[]
    for i,d in enumerate(days):
        rows.append({'date':d,'reference_open_utc':d+'T14:30:00Z','reference_close_utc':d+'T21:00:00Z',
            'next_reference_date':days[i+1] if i+1<len(days) else None,'month_end_in_reference_range':d.endswith('12-31')})
    dates=write(tmp_path/'dates.json',days);clocks=write(tmp_path/'clocks.ndjson',b''.join(canonical(r) for r in rows))
    instrument='INVENTED';quotes=[]
    for d,p in zip(days,['100','101','97','98','99','105','106']):
        quotes.append({'instrument':instrument,'source_symbol':'INVENTED.US','session_date':d,
            'open_token':p,'close_token':p,'open_micro':int(p)*10**6,'close_micro':int(p)*10**6,
            'currency':'USD','basis':'VENDOR_RAW_UNADJUSTED_USD_PER_SHARE','historical_known_by':None,
            'source_ref':{'sha256':sha(b'INVENTED')},'source_revision':'INVENTED',
            'source_snapshot_id':'INVENTED','normalised_source':{},'provider_raw_record':{},'field_pointers':{},
            'source_published_at':None,'source_available_at':None,'currency_scope':'INVENTED'})
    quote_pin=write(tmp_path/'quotes.ndjson',b''.join(canonical(r) for r in quotes))
    wrappers=[];event_dates=[]
    # q0 on initial day; same calendar date as annual formation; a prior-holder
    # entitlement with arbitrary nominal precision. No real source values.
    for index,ex,paydate,amount in [(0,days[0],days[0],'0.005'),(1,days[2],days[2],'1.0050000000000000000000000000000000001')]:
        raw={'path':'/INVENTED-NOT-READ','sha256':sha(b'INVENTED-SOURCE'),'bytes':15}
        rec={'json_pointer':'/'+str(index),'sha256':sha(str(index).encode()),'byte_offset':index,'byte_length':1}
        eid='eodhd-vti-div-'+sha(canonical({'source_sha256':raw['sha256'],'json_pointer':rec['json_pointer'],'record_sha256':rec['sha256']}))
        action={'event_id':eid,'instrument':instrument,'source_ref':'sha256:'+raw['sha256'],'raw_pointer':rec['json_pointer'],
            'ex_date':ex,'payment_date':paydate,'amount_token':amount,'reference_dates':days,'currency':'USD',
            'basis':'RAW_USD_PER_CONTEMPORANEOUS_SHARE'}
        avail=next(d for d in days if d>paydate)
        wrappers.append({'action':action,'original_fields_as_supplied':{'date':ex,'paymentDate':paydate,
            'unadjustedValue':amount,'currency':'USD'},'numeric_representation':'INVENTED_EXACT_TOKEN',
            'source_raw':raw,'raw_record':rec,'field_pointers':{},'modeled_cash_availability':{
                'date':avail,'historical_known_by':None,'actual_broker_receipt':None}})
        event_dates.append({'event_id':eid,'ex_date':ex,'payment_date':paydate,'availability_date':avail})
    action_pin=write(tmp_path/'actions.ndjson',b''.join(canonical(w) for w in wrappers))
    packet=write(tmp_path/'packet.json',{'schema':'polar.private-raw-price-action-consumer-dataset/1',
        'source_instrument':instrument,'source_symbol':'INVENTED.US','observed_historical_K':None,
        'members':[dates,clocks,quote_pin,action_pin],
        'window':{'start_inclusive':days[0],'end_inclusive':days[-1]}})
    desc={'schema':'polar.raw-action-input/1','packet_ref':packet,'dates_ref':dates,'clocks_ref':clocks,
        'quotes_ref':quote_pin,'actions_ref':action_pin,'source_instrument':instrument,'source_symbol':'INVENTED.US',
        'event_dates':event_dates,'split_records':0,'rights':'INVENTED_PUBLIC_TEST',
        'provenance':{'kind':'DETERMINISTIC_INVENTED_FIXTURE','source_payloads':'NONE'},
        'historical_K':None,'limitations':['INVENTED ONLY; raw/action metadata shapes, not financial evidence.']}
    inp=write(tmp_path/'input.json',desc);cal=calendar(desc,days,rows);calpin=write(tmp_path/'calendar.json',cal)
    protocol=write(tmp_path/'protocol.json',{'id':'INVENTED-RAW-ACTION','only':'PUBLIC_INVENTED_CONTROL'})
    tz=write(tmp_path/'UTC',Path('/usr/share/zoneinfo/UTC').read_bytes())
    profile={'schema':'polar.raw-action-profile/1','protocol_id':'INVENTED-RAW-ACTION',
        'protocol_sha256':protocol['sha256'],'input_sha256':inp['sha256'],'calendar_sha256':calpin['sha256'],
        'timezone_sha256':tz['sha256'],'legs':list(LEGS),'cost_scenarios':COSTS,
        'policy':'CLOSED_PAYMENT_RETAIN_ANNUAL_CASH_D60','capital_cents':10000000}
    pp=write(tmp_path/'profile.json',profile)
    root=tmp_path/'store';root.mkdir()
    cfg={'schema':'polar.raw-action-config/1','namespace':'INVENTED','profile_ref':pp,'protocol_ref':protocol,
        'input_ref':inp,'calendar_ref':calpin,'timezone_ref':tz,'code':code_binding(),
        'code_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'runtime_image_id':os.environ.get('POLAR_CI_RUNTIME_IMAGE_ID','sha256:'+'0'*64),
        'candidate_id':'INVENTED-RAW-ACTION','experiment_id':'INVENTED-RAW-ACTION-ORIGINAL',
        'execution_authority_ref':None,'artifact_root_identity':root_identity(root)}
    return root,cfg,desc,cal


def test_structural_preflight_before_value_parse_and_original_debit(tmp_path,monkeypatch):
    root,cfg,desc,cal=fixture(tmp_path)
    import polar.raw_action_service as module
    def forbidden(*a,**k):raise AssertionError('FINANCIAL_VALUE_PARSE_OR_NATIVE_BEFORE_START')
    monkeypatch.setattr(module,'load',forbidden);monkeypatch.setattr(module,'bounded_native',forbidden)
    service=ReferenceResearchService(root,128*1024**2)
    ready=service.preflight(cfg);assert ready['expected_native_accounts']==8 and ready['scientific_starts']==0
    assert not (root/'scheduled-reference-attempts').exists()
    invalid=deepcopy(cal);invalid['events'][0]['decision_ns']=invalid['events'][0]['close_ns']
    bad=deepcopy(cfg);bad['calendar_ref']=write(tmp_path/'bad-calendar.json',invalid)
    profile=json.loads(Path(cfg['profile_ref']['path']).read_bytes());profile['calendar_sha256']=bad['calendar_ref']['sha256']
    bad['profile_ref']=write(tmp_path/'bad-profile.json',profile)
    with pytest.raises(ValueError,match='RAW_CALENDAR_BINDING'):service.run(bad)
    assert not (root/'scheduled-reference-attempts').exists()
    # Once metadata is valid, a failing original's debit remains and cannot retry.
    with pytest.raises(AssertionError,match='FINANCIAL_VALUE_PARSE'):service.run(cfg)
    assert len(list(root.rglob('start.json')))==1 and len(list(root.rglob('finish/record.json')))==1
    with pytest.raises(ValueError,match='RAW_ORIGINAL_ALREADY_RECORDED'):service.run(cfg)


def test_full_native_private_graph_then_source_absent_readonly_reproduction(tmp_path,monkeypatch):
    root,cfg,desc,cal=fixture(tmp_path);service=ReferenceResearchService(root,256*1024**2)
    import polar.raw_action_service as module
    real=module.load
    def after_start(*a,**k):
        assert len(list(root.rglob('start.json')))==1
        return real(*a,**k)
    monkeypatch.setattr(module,'load',after_start)
    try:
        result=service.run(cfg)
    except BaseException as exc:
        if Path('/reports').is_dir():
            write(Path('/reports/raw-package-failure.json'),{'error':str(exc),'events':getattr(exc,'events',[])})
        raise
    assert result['status']=='SUCCESS' and result['native_accounts']==8
    assert all(result[k]==0 for k in ('fit_calls','predict_calls','model_calls','score_calls','rank_calls','estimator_calls','optimizer_calls','bootstrap_samples'))
    assert not (root/'research-results').exists() and set(result['private_results'])=={'BASE','STRESS'}
    home=root/'reference-research-experiments'/result['semantic_id']
    base=json.loads((home/'BASE-PAYMENT_CASH_REINVEST.json').read_bytes())
    cash=json.loads((home/'BASE-CASH.json').read_bytes())
    assert base['component_counts']['recognize']==base['component_counts']['pay']==2
    assert base['component_counts']['native_positive_balance_updates']==1
    assert cash['component_counts']['native_positive_balance_updates']==0
    assert len(base['intents'])==len(cal['events'])
    assert base['terminal']['strict_component_flag'] is True
    assert all(s['external_cash_flow_cents']==0 and s['nav_before_cents']==s['nav_after_cents'] for s in base['settlements'])
    private=json.loads((home/'BASE-result.json').read_bytes())
    assert private['schema']=='polar.private-raw-action-result/1' and private['financial']=='NOT_REVIEWED'
    assert private['initial_state_control']['status']=='PASS'
    assert private['diagnostics'][LEGS[0]]['subperiods'][0]['status']=='OK'
    assert all('receivable_cents' in r for s in private['series'] for r in s['ledger'])
    from test_scheduled_service import snapshot
    before=snapshot(root)
    for p in tmp_path.iterdir():
        if p.is_file():p.unlink()
    def forbidden(*a,**k):raise AssertionError('STORED_SOURCE_POLICY_OR_NATIVE')
    for name in ('load','metadata','calendar','bounded_native'):monkeypatch.setattr(module,name,forbidden)
    replay=service.recompute(result['semantic_id'])
    assert replay['status']=='REPRODUCED' and all(replay[k]==0 for k in ('native_calls','source_calls','policy_calls','store_writes'))
    assert snapshot(root)==before
    modified=deepcopy({'legs':[json.loads((home/('BASE-'+leg+'.json')).read_bytes()) for leg in LEGS]})
    modified['legs'][1]['nav'][1]['cash_cents']+=1
    with pytest.raises(ValueError,match='RAW_INITIAL_STATE_MISMATCH'):initial_control(modified)


def test_due_zero_and_positive_terminal_are_distinct_without_changing_pure_flag():
    days=('2020-01-01','2020-01-02','2020-01-03','2020-01-04')
    a=Action('Q0','X','INVENTED','/0',days[1],days[2],'0.0000000000000000000000000001',days)
    state=recognize(State(days[0],Phase.CLOSE_SETTLED,100,(('X',0),)),a,days[1])
    future=settled_snapshot(state,days[2],(('X',0),),100)
    assert valuation(future,{'X':0},terminal=True)['cash_only_terminal'] is False
    # Generic future zero claim retains strict flag; exact B7 has all due before terminal.
    assert terminal_check(future,1)['strict_component_flag'] is False
    overdue=settled_snapshot(future,days[3],(('X',0),),100)
    with pytest.raises(ValueError,match='RAW_DUE_LIFECYCLE_INCOMPLETE'):terminal_check(overdue,1)
    paid=pay(state,'Q0',days[3]);assert terminal_check(paid,1)['strict_component_flag'] is True
    with pytest.raises(ValueError,match='CLAIM_DOUBLE_PAYMENT'):pay(paid,'Q0',days[3])
