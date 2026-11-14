"""Source-shaped invented reference metadata and actual native component paths."""
from dataclasses import replace, asdict
from copy import deepcopy
import json
import subprocess
import sys
import os
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
import pytest

from polar.event_native import (
    ReferenceClose, DecisionPoint, EventInstruction, EventPlan, sma_vti_category,
    simulate_event_component, _simulate_account, verify_saved_event_witnesses, COSTS, key,
)
from polar.scheduled_event_controller import Request


def at(day,h=21,m=0):
    d=datetime.fromisoformat(day).replace(hour=h,minute=m,tzinfo=timezone.utc)
    return int(d.timestamp())*10**9


def fixture(*, overlap=True, equal=False, censor=False, days=None):
    days=days or ['2024-01-02','2024-01-03','2024-01-04','2024-01-05','2024-01-08','2024-01-09','2024-01-10','2024-01-11','2024-01-12']
    source=[]
    warm=[(date(2024,1,2)-timedelta(days=i)).isoformat() for i in range(200,0,-1)]
    for s in ('BIL','VTI'):
        for i,day in enumerate(warm):
            px=1000000000 if s=='VTI' and i==0 else 10000000
            source.append(ReferenceClose(s,day,at(day),at((date.fromisoformat(day)+timedelta(days=1)).isoformat(),0),px,
                f'INVENTED/{s}/{day}','VTI_WARMUP_CANDIDATE' if s=='VTI' else 'BIL_UNUSED_WARMUP_CONTEXT'))
        for i,day in enumerate(days):
            px=10000000 if s=='BIL' else [11000000,20000000,21000000,19000000,23000000,22000000,26000000,25000000,27000000][i]
            source.append(ReferenceClose(s,day,at(day),at((date.fromisoformat(day)+timedelta(days=1)).isoformat(),0),px,
                                         f'INVENTED/{s}/{day}','NAV'))
    events=[EventInstruction(Request('e1',at(days[2],14,1),at(days[4]),at(days[5],0,1),at(days[5]),'clock-e1'),at(days[2]))]
    if overlap:events.append(EventInstruction(Request('e2',at(days[2],15),at(days[5]),at(days[6],0,1),at(days[6]),'clock-e2'),at(days[2])))
    if equal:
        events.append(EventInstruction(Request('equal',at(days[6]),at(days[7]),at(days[8],0,1),at(days[8]),'clock-equal'),at(days[7])))
    elif overlap:
        events.append(EventInstruction(Request('pre-reentry',at(days[6],0,2),at(days[7]),at(days[8],0,1),at(days[8]),'clock-pre'),at(days[6])))
    if censor:
        events.append(EventInstruction(Request('censored',at(days[7],14,1),at('2024-01-16'),at('2024-01-17',0,1),at('2024-01-17'),'clock-censor'),at('2024-01-16')))
    return bound(EventPlan('INVENTED_COMPONENT','INVENTED_INPUT','INVENTED_CALENDAR','INVENTED_PROTOCOL',tuple(source),tuple(at(d) for d in days),
                     tuple(DecisionPoint(at(d,0,1),at(d)) for d in days[1:]),tuple(events),tuple(at(d) for d in days[1:-1])))


def bound(plan,label='standard'):
    source=key([asdict(r) for r in plan.source])
    calendar=key([plan.nav_closes,[asdict(d) for d in plan.daily_decisions],[asdict(e) for e in plan.events],plan.required_anchors])
    return replace(plan,input_id='INVENTED/'+source,calendar_id='INVENTED/'+calendar,
                   account_scope='INVENTED/'+label+'/'+key([source,calendar]))


@pytest.fixture(scope='module')
def component_accounts():
    return simulate_event_component(fixture())


@pytest.fixture(scope='module')
def native_account(component_accounts):
    return next(a for a in component_accounts['accounts'] if a['leg']=='CALENDAR_PROTECTION' and a['cost_id']=='BASE')


def save_native(record_property,value):
    from polar.event_native_witness import encode
    record_property('invented_event_native_component',json.dumps(encode(value),sort_keys=True))


def test_sma_exact200_uses_jan2_plus199_not201_or_short_prefix():
    plan=fixture();d=plan.daily_decisions[0].decision_ns
    signal=sma_vti_category(plan.source,d)
    assert signal['category']=='NORMAL' and signal['window']==200 and len(signal['source_ids'])==200
    assert signal['source_ids'][-1]=='INVENTED/VTI/2024-01-02'
    assert signal['source_ids'][0]!='INVENTED/VTI/'+plan.source[0].date
    assert 201*signal['last_micro']-(signal['sum_micro']+1000000000)<0
    vti=tuple(r for r in plan.source if r.symbol=='VTI' and r.close_ns<d)[-199:]
    assert sma_vti_category(vti,d)['category']=='UNAVAILABLE'
    missing=tuple(replace(r,available_ns=None) if r.symbol=='VTI' else r for r in plan.source)
    assert sma_vti_category(missing,d)['category']=='UNAVAILABLE'


def test_sma_equality_defensive_and_future_quote_not_borrowed():
    p=fixture();d=p.daily_decisions[0].decision_ns
    rows=tuple(replace(r,price_micro=10000000) for r in p.source)
    assert sma_vti_category(rows,d)['category']=='BIL'
    changed=tuple(replace(r,price_micro=999000000) if r.close_ns>=d else r for r in rows)
    assert sma_vti_category(changed,d)==sma_vti_category(rows,d)


def test_actual_native_pending_coalescing_hold_anchors_and_consumed_quantities(native_account,record_property):
    p=fixture();r=native_account;save_native(record_property,r)
    assert len(r['nav'])==len(p.nav_closes) and len(r['anchors'])==len(p.nav_closes)
    assert all(v['positions']=={'BIL':0,'VTI':0} for v in [r['nav'][0],r['nav'][-1]])
    assert r['nav'][0]['date']=='2024-01-02' and not any(v['date']<'2024-01-02' for v in r['nav'])
    assert len({o['order_id'] for o in r['orders'] if o['routed_quantity']})==len([o for o in r['orders'] if o['routed_quantity']])
    assert any(d['reason']=='OVERLAP_NO_REBALANCE' for d in r['decisions'])
    assert any(w.get('coalesced_from') for w in r['sizing'].values())
    cancellation=next(d for d in r['decisions'] if d['decision_ns']==at('2024-01-10',0,2))
    assert cancellation['action']=='HOLD' and cancellation['cancelled_or_superseded_ids']
    assert not any(o['q_ns']==at('2024-01-10') for o in r['orders'])
    first=next(w for w in r['sizing'].values() if w['decision_ns']==p.daily_decisions[0].decision_ns)
    assert first['targets']['VTI']==9090
    first_buy=next(o for o in r['orders'] if o['side']=='BUY' and o['symbol']=='VTI')
    assert first_buy['desired']==9090 and first_buy['routed_quantity']<9090
    assert verify_saved_event_witnesses(r)['native_calls']==0


def test_equal_q_barrier_first_and_no_same_q_future_target(record_property):
    p=fixture(equal=True);r=_simulate_account(p,'CALENDAR_PROTECTION',*COSTS[0]);save_native(record_property,r);q=at('2024-01-10')
    barrier=next(d for d in r['decisions'] if d['decision_ns']==q and d['action']=='ROUTE_INTENT')
    decision=next(d for d in r['decisions'] if d['decision_ns']==q and d.get('reason')=='NEW_REDUCTION')
    assert barrier['sequence']<decision['sequence']
    later=[w for w in r['sizing'].values() if w['decision_ns']==q]
    assert later and all(v['close_ns']<q for v in later[0]['source_rows'].values())
    assert len([x for x in r['receipts'] if x.q_ns==q])==1


def test_five_controls_two_costs_have_independent_actual_cents_and_anchors(component_accounts,record_property):
    r=component_accounts;save_native(record_property,r)
    assert len(r['accounts'])==10 and len({a['context'].account_id for a in r['accounts']})==10
    vti=[a for a in r['accounts'] if a['leg']=='FULL_VTI']
    assert vti[0]['fills'][0]['quantity']!=vti[1]['fills'][0]['quantity']
    for a in r['accounts']:
        assert all(an.context==a['context'] for an in a['anchors'])
        assert not any(a['nav'][-1]['positions'].values())
        assert all(sum(1 for x in a['receipts'] if x.q_ns==q)<=1 for q in fixture().nav_closes)
        if a['leg']=='SMA200':assert len(a['sma'][0]['source_ids'])==200
        for an in a['anchors']:
            orders=[o for o in a['orders'] if o['q_ns']==an.q_ns]
            assert all(an.mark_ns<o['at_ns'] and an.mark_sequence<o['sequence'] for o in orders)


def test_required_missing_anchor_rejects_before_native_and_censored_event_not_filled(record_property):
    p=fixture(censor=True)
    r=_simulate_account(p,'CALENDAR_PROTECTION',*COSTS[0]);save_native(record_property,r)
    assert next(e for e in r['event_census'] if e['event_id']=='censored')['protection_censored']
    assert all(x.q_ns<=p.nav_closes[-1] for x in r['receipts'])
    with pytest.raises(Exception,match='EVENT_REQUIRED_ANCHORS'):
        simulate_event_component(replace(p,required_anchors=(at('2024-01-16'),)))


@pytest.mark.parametrize('mutation,reason',[
    (lambda a:a['anchors'].pop(1),'ANCHOR_MISSING'),
    (lambda a:a['receipts'].__setitem__(0,replace(a['receipts'][0],context=replace(a['context'],cost_id='OTHER'))),'RECEIPT_BINDING'),
    (lambda a:a['receipts'].__setitem__(0,replace(a['receipts'][0],generation=999)),'RECEIPT_BINDING'),
    (lambda a:a['receipts'].__setitem__(0,replace(a['receipts'][0],symbol_evaluations=a['receipts'][0].symbol_evaluations[:1])),'SYMBOL_ROUTING_CENSUS'),
    (lambda a:a['orders'][0].__setitem__('routed_quantity',a['orders'][0]['routed_quantity']+1),'TERMINAL_NATIVE_JOIN'),
    (lambda a:a['nav'][1].__setitem__('date','2024-01-04'),'NAV_ROLE_GRID'),
    (lambda a:a['orders'][0]['clip_witness'].__setitem__('cash_cents',1),'AFFORDABILITY'),
])
def test_saved_actual_operand_identity_and_census_mutants(native_account,mutation,reason):
    a=deepcopy(native_account);mutation(a)
    with pytest.raises(Exception,match=reason):verify_saved_event_witnesses(a)


def test_sma_saved_window_mutant_cannot_be_reported_as_valid(component_accounts):
    a=deepcopy(next(a for a in component_accounts['accounts'] if a['leg']=='SMA200'))
    a['sma'][0]['prices_micro']=a['sma'][0]['prices_micro'][:-1]
    with pytest.raises(Exception,match='SMA_PREFIX'):verify_saved_event_witnesses(a)


def test_true_native_zero_delta_vs_nonzero_target_zero_affordable(record_property):
    p=fixture();q=p.nav_closes[1]
    p=replace(p,source=tuple(replace(r,price_micro=10**12) if r.symbol=='VTI' and r.close_ns==q else r for r in p.source))
    a=_simulate_account(bound(p,'allzero-executable'),'FULL_VTI',*COSTS[0]);save_native(record_property,a)
    assert a['receipts'][0].outcome=='NO_FILL' and a['receipts'][0].order_count==0
    assert any(d!=0 for _,d in a['receipts'][0].desired_deltas)
    assert a['receipts'][-1].outcome=='ZERO_DELTA_NO_ORDER' and not a['fills']
    assert a['status']=='COMPLETE_TRACE_WITH_UNCONFIRMED_TARGET'


def test_native_sma_change_and_missing_prefix_are_not_drift_rebalance(record_property):
    p=fixture();q=p.nav_closes[2]
    changed=replace(p,source=tuple(replace(r,price_micro=1000000) if r.symbol=='VTI' and r.close_ns==q else r for r in p.source))
    a=_simulate_account(bound(changed,'sma-category'),'SMA200',*COSTS[0]);save_native(record_property,a)
    assert any(v['category']=='BIL' for v in a['sma']) and any(v['category']=='NORMAL' for v in a['sma'])
    assert any(v['reason']=='SMA_UNCHANGED_NO_RETRY' for v in a['decisions'])
    # Exactly199 eligible observations at the first decision, no shortened gate.
    first=p.daily_decisions[0].decision_ns
    eligible=sorted([r for r in p.source if r.symbol=='VTI' and r.close_ns<first],key=lambda r:r.close_ns)
    missing_ids={eligible[0].source_id,eligible[1].source_id}
    missing=replace(p,source=tuple(replace(r,available_ns=None) if r.source_id in missing_ids else r for r in p.source))
    b=_simulate_account(bound(missing,'sma-unavailable'),'SMA200',*COSTS[0]);save_native(record_property,b)
    assert b['sma'][0]['category']=='UNAVAILABLE' and not b['sma_control_complete']
    assert b['nav'][1]['positions']=={'BIL':0,'VTI':0}


def test_static_month_end_native_anchor_before_actual_orders(record_property):
    days=['2024-01-02','2024-01-03','2024-01-30','2024-01-31','2024-02-01','2024-02-02','2024-02-05','2024-02-06','2024-02-07']
    p=fixture(days=days,overlap=False);a=_simulate_account(p,'STATIC_50',*COSTS[0]);save_native(record_property,a)
    assert any(d['reason']=='STATIC_MONTH_END' for d in a['decisions'])
    q=at('2024-01-31');anchor=next(v for v in a['anchors'] if v.q_ns==q)
    assert all(anchor.mark_sequence<o['sequence'] and anchor.mark_ns<o['at_ns'] for o in a['orders'] if o['q_ns']==q)


def test_native_partial_is_unfinalized_with_actual_book_observation_not_success(record_property):
    from nautilus_trader.backtest.models import FillModel
    from nautilus_trader.model.book import OrderBook
    from nautilus_trader.model.data import BookOrder
    from nautilus_trader.model.objects import Quantity
    from nautilus_trader.model.enums import OrderSide,BookType
    from polar.event_native import EventNativeFailure
    class Thin(FillModel):
        def get_orderbook_for_fill_simulation(self,instrument,order,best_bid,best_ask):
            b=OrderBook(instrument_id=instrument.id,book_type=BookType.L2_MBP)
            b.add(BookOrder(OrderSide.BUY,best_bid,Quantity.from_int(1),1),0,0)
            b.add(BookOrder(OrderSide.SELL,best_ask,Quantity.from_int(1),2),0,0)
            return b
    with pytest.raises(EventNativeFailure,match='PARTIAL_OR_MISMATCH') as error:
        _simulate_account(bound(fixture(),'partial-unfinalized'),'CALENDAR_PROTECTION',*COSTS[0],fill_model=Thin())
    a=error.value.evidence;save_native(record_property,a)
    assert a['status']=='FAILED_UNFINALIZED' and len(a['fills'])==1 and not a['receipts']
    observed=a['actual_native_partial_observation']
    assert observed['positions']['VTI']==1 and observed['controller_expected_positions']['VTI']==0
    assert a['state'].committed is None and observed['cash_cents']<observed['controller_expected_cash_cents']
    with pytest.raises(Exception,match='FINAL_STATE'):verify_saved_event_witnesses(a)


def test_immutable_saved_only_witness_packet_without_native_or_source(native_account,tmp_path):
    from polar.gym_store import GymStore
    from polar.event_native_witness import publish_witnesses,verify_stored_witnesses,witness_bytes,verify_witness_bytes
    store=GymStore(tmp_path,64*1024**2);ref=publish_witnesses(store,native_account)
    before={str(p.relative_to(tmp_path)):(p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}
    checked=verify_stored_witnesses(tmp_path,ref['id'],native_account['context'])
    assert checked['native_calls']==checked['market_source_reads']==0 and checked['saved_member_reads']==2
    assert publish_witnesses(store,native_account)['id']==ref['id']
    assert before=={str(p.relative_to(tmp_path)):(p.read_bytes(),p.stat().st_mtime_ns) for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(Exception,match='EXTERNAL_CONTEXT'):
        verify_witness_bytes(witness_bytes(native_account),replace(native_account['context'],leg_id='OTHER'))
    # Fresh source-absent process: only stored packet/context args, no plan or
    # quote rows, prohibit every native import and every write-open.
    script=r"""
import sys,json,os,importlib.abc
class NoNative(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith('nautilus_trader'):raise RuntimeError('NATIVE_IMPORT_FORBIDDEN')
sys.meta_path.insert(0,NoNative())
from polar.event_native_witness import verify_stored_witnesses
from polar.scheduled_event_controller import Context
old=os.open

def readonly(path,flags,*args,**kw):
 if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
 return old(path,flags,*args,**kw)
os.open=readonly
result=verify_stored_witnesses(sys.argv[1],sys.argv[2],Context(**json.loads(sys.argv[3])))
print(json.dumps({k:v for k,v in result.items() if k!='account'}))
"""
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
    run=subprocess.run([sys.executable,'-c',script,str(tmp_path),ref['id'],json.dumps(asdict(native_account['context']))],
                       cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert run.returncode==0,run.stderr
    assert json.loads(run.stdout)['native_calls']==0


def test_obsolete_pending_protection_has_no_fictional_fill_or_commit(record_property):
    p=fixture(overlap=False);e=p.events[0]
    p=bound(replace(p,events=(replace(e,q_ns=e.request.reentry_candidate_ns),)),'obsolete')
    a=_simulate_account(p,'CALENDAR_PROTECTION',*COSTS[0]);save_native(record_property,a)
    assert any(d.get('obsolete_pending_cancelled') for d in a['decisions'])
    assert not any(v.destination=='REDUCED' for v in a['issued_intents'])
    assert not any(o['q_ns']==at('2024-01-04') for o in a['orders'])


def test_lower_future_price_never_enlarges_original_d_target(record_property):
    p=fixture();q=p.nav_closes[1]
    p=bound(replace(p,source=tuple(replace(r,price_micro=5000000) if r.symbol=='VTI' and r.close_ns==q else r for r in p.source)),'falling-execution-price')
    a=_simulate_account(p,'FULL_VTI',*COSTS[0]);save_native(record_property,a)
    first=next(o for o in a['orders'] if o['side']=='BUY')
    assert first['desired']==first['routed_quantity']==9090
    assert first['price_micro']==5000000


def test_sma_public_helper_rejects_unsorted_duplicate_or_boolean_price():
    p=fixture();rows=tuple(r for r in p.source if r.symbol=='VTI')
    with pytest.raises(Exception,match='ELIGIBILITY_ORDER'):
        sma_vti_category(tuple(reversed(rows)),p.daily_decisions[0].decision_ns)
    with pytest.raises(Exception,match='ELIGIBILITY_ROWS'):
        sma_vti_category((replace(rows[0],price_micro=True),),p.daily_decisions[0].decision_ns)


def test_saved_witness_hash_and_closed_type_reject_before_native(native_account,tmp_path):
    from polar.event_native_witness import publish_witnesses,verify_stored_witnesses,witness_bytes,verify_witness_bytes
    from polar.gym_contract import decode,canonical
    from polar.gym_store import GymStore
    ref=publish_witnesses(GymStore(tmp_path,64*1024**2),native_account)
    member=tmp_path/'event-component-witnesses'/ref['id']/'witnesses.json'
    member.chmod(0o600);member.write_bytes(member.read_bytes()+b' ')
    with pytest.raises(Exception,match='MEMBER_HASH'):
        verify_stored_witnesses(tmp_path,ref['id'],native_account['context'])
    value=decode(witness_bytes(native_account));value['account']['context']['$type']='UNSUPPORTED_EXECUTABLE_TYPE'
    with pytest.raises(Exception,match='CLOSED_TYPE'):
        verify_witness_bytes(canonical(value),native_account['context'])


def test_invented_full916_source716nav_sma_witness_capacity(record_property):
    from polar.event_native_witness import witness_bytes,verify_witness_bytes
    from polar.gym_contract import sha,MAX_BYTES
    first=date(2024,1,2);days=[(first+timedelta(days=i)).isoformat() for i in range(716)]
    source=[]
    for symbol in ('BIL','VTI'):
        for i in range(-200,716):
            day=(first+timedelta(days=i)).isoformat();role='NAV' if i>=0 else 'VTI_WARMUP_CANDIDATE' if symbol=='VTI' else 'BIL_UNUSED_WARMUP_CONTEXT'
            source.append(ReferenceClose(symbol,day,at(day),at((date.fromisoformat(day)+timedelta(days=1)).isoformat(),0),
                                         10000000,'INVENTED/CAPACITY/'+symbol+'/'+day,role))
    p=bound(EventPlan('INVENTED_FULL_FRAME','input','calendar','protocol',tuple(source),tuple(at(d) for d in days),
                      tuple(DecisionPoint(at(d,0,1),at(d)) for d in days[1:]),(),(at(days[10]),)),'full-capacity')
    a=_simulate_account(p,'SMA200',*COSTS[0]);raw=witness_bytes(a);restored,check=verify_witness_bytes(raw,a['context'])
    assert len(p.source)==1832 and len(a['nav'])==716 and len(a['nav'])-1==715
    assert len(a['anchors'])==716 and all(v['window']==200 for v in a['sma'])
    assert a['nav'][0]['positions']=={'BIL':0,'VTI':0} and a['nav'][0]['date']=='2024-01-02'
    assert len(raw)<MAX_BYTES and restored['context']==a['context'] and check['native_calls']==0
    record_property('invented_full_frame_capacity',json.dumps({'source_rows':1832,'source_dates':916,'NAV':716,'returns':715,
        'actual_native_accounts':1,'native_account_id':a['native_account_id'],'witness_bytes':len(raw),'sha256':sha(raw),
        'source_absent_verifier':check,'scope':'INVENTED_CAPACITY_NOT_ACTUAL_SOURCE_CALENDAR_OR_FINANCIAL_POINT'}))
