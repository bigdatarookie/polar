"""Invented one-path actual pinned-engine event and saved-only controls."""
from fractions import Fraction as F
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal
from copy import deepcopy
import json
import uuid
import pytest

from polar.signed_account_core import State
from polar.signed_native_bridge import SignedNativeBridge,MarkEvent,MarkIdentity,native_types
from polar.signed_event_driver import AccountContext,Rate,Action,Locate,Event,RoutingBoundary,SignedEventDriver,fee_for
from polar.signed_event_saved import verify_packet,encode,verify_bytes
from polar.gym_contract import canonical

CTX=AccountContext('INVENTED_ACCOUNT','INVENTED_PATH','INVENTED_CONFIG','INVENTED_SOURCE',('AAPL','AMZN'))
EMIT=None


@pytest.fixture(autouse=True)
def account_census(record_property):
    global EMIT
    EMIT=lambda row:record_property('invented_signed_driver_native_account',json.dumps(encode(row),sort_keys=True))
    yield
    EMIT=None


def at(date,hour=21):
    return int(datetime.fromisoformat(date).replace(hour=hour,tzinfo=timezone.utc).timestamp())*10**9


def event(id,date,*,kind='CLOSE',instruction='HOLD',targets=None,price=F(10),actions=(),rates=(),terminal=False,
          locate=True,eligible=True,flat=1,observed=None):
    t=at(date,0 if kind=='EX' else 21)
    marks=(('AAPL',price),('AMZN',price))
    identities=tuple(MarkIdentity(n,'INVENTED_QUOTE:'+str(t if observed is None else observed)+':'+n,
        'INVENTED_SOURCE/'+n,t if observed is None else observed,None,
        'PRE_EX_CUM_MARK_WITH_NEW_CLAIM' if kind=='EX' else 'MODELED','INVENTED_CONDITIONAL_REFERENCE') for n,_ in marks)
    formation='formation:'+id if instruction!='HOLD' else None
    locates=() if instruction!='TARGET' or not locate else (Locate('locate:'+id,CTX.path,CTX.account,formation,'AMZN',
        'SHORT',id,abs(dict(targets)['AMZN']),True,'INVENTED_NOT_OBSERVED_INVENTORY'),)
    return Event(id,t,kind,marks,MarkEvent('mark:'+id,t,identities),instruction,formation,
        None if formation is None else t-60*10**9,() if targets is None else tuple(sorted(targets)),
        marks if kind=='CLOSE' and eligible else (),locates,actions,rates,flat_fee_cents=flat,fee_bps=0,terminal=terminal)


def run_driver(events,*,capital=100000,partial=False,inject_unknown_submit=False,inject_late_callback=False,
               native_latency_ns=0,expect_time_failure=False,receive_delay_ns=0,invalid_submission_ns=None):
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FeeModel,FillModel,LatencyModel
    from nautilus_trader.config import BacktestEngineConfig,LoggingConfig,StrategyConfig,RiskEngineConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.identifiers import Venue,InstrumentId,Symbol,ClientId,ClientOrderId
    from nautilus_trader.model.data import QuoteTick,CustomData,DataType
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.objects import Price,Quantity
    from nautilus_trader.model.enums import AccountType,OmsType,OrderSide,TimeInForce,PositionSide,BookType
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.accounting.factory import AccountFactory
    from nautilus_trader.model.book import OrderBook
    from nautilus_trader.model.data import BookOrder
    types=native_types();venue=Venue('SIGNEDDRIVER'+uuid.uuid4().hex.upper())
    ids={n:InstrumentId(Symbol(n),venue) for n in CTX.names}
    class Boundary(Data):
        def __init__(self,t):self.t=t
        @property
        def ts_event(self):return self.t
        @property
        def ts_init(self):return self.t
    class Fee(FeeModel):
        def get_commission(self,order,fill_qty,fill_px,instrument):
            return types['money_from_cents'](fee_for(strategy.driver.event,int(F(fill_qty.as_decimal())),F(fill_px.as_decimal())))
    class Thin(FillModel):
        def get_orderbook_for_fill_simulation(self,instrument,order,best_bid,best_ask):
            book=OrderBook(instrument_id=instrument.id,book_type=BookType.L2_MBP)
            book.add(BookOrder(OrderSide.BUY,best_bid,Quantity.from_int(1),1),0,0)
            book.add(BookOrder(OrderSide.SELL,best_ask,Quantity.from_int(1),2),0,0)
            return book
    engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),run_analysis=False,
        risk_engine=RiskEngineConfig(bypass=False,max_order_submit_rate='100/00:00:01')))
    class Probe(Strategy):
        def __init__(self):
            super().__init__(StrategyConfig(strategy_id='SIGNED_EVENTS',order_id_tag='001',log_events=False,log_commands=False))
            self.driver=None;self.current_order=None;self.error=None
            self.callback_clocks=[]
        def positions(self):
            q={n:0 for n in CTX.names}
            for p in self.cache.positions_open():q[p.instrument_id.symbol.value]+=int(F(p.quantity.as_decimal()))*(-1 if p.side==PositionSide.SHORT else 1)
            return q
        def on_start(self):
            def submit(order):
                if inject_unknown_submit:raise RuntimeError('INVENTED_SUBMIT_UNKNOWN_EFFECT')
                self.submit_order(order)
            bridge=SignedNativeBridge(State(capital),ids,submit,self.positions,
                lambda:engine.portfolio.account(venue),initial_cents=capital,continue_economic_events=True)
            self.driver=SignedEventDriver(CTX,bridge)
            for e in events:
                self.clock.set_time_alert_ns('begin-'+e.id,e.at_ns+100,
                    lambda _,e=e:self.driver.begin_event(e,RoutingBoundary(e.id,e.at_ns,e.at_ns+10000)))
                for k in range(1,18):
                    self.clock.set_time_alert_ns('pump-'+e.id+'-'+str(k),e.at_ns+100+k*100,lambda _:self.pump())
                if native_latency_ns:
                    self.clock.set_time_alert_ns('late-pump-'+e.id,e.at_ns+3*native_latency_ns+5000,lambda _:self.pump())
                    self.clock.set_time_alert_ns('final-pump-'+e.id,e.at_ns+4*native_latency_ns+8000,lambda _:self.pump())
            for iid in ids.values():self.subscribe_quote_ticks(iid)
        def pump(self):
            if self.driver.event is None or self.driver.bridge.pending:return
            c=self.driver.next_order()
            if c is None:return
            self.current_order=self.order_factory.market(instrument_id=ids[c.name],
                order_side=OrderSide.BUY if c.side=='BUY' else OrderSide.SELL,quantity=Quantity.from_int(c.quantity),
                time_in_force=TimeInForce.IOC if partial else TimeInForce.GTC,
                client_order_id=ClientOrderId(c.intent_id))
            self.driver.submit(self.current_order,native_ns=self.clock.timestamp_ns() if invalid_submission_ns is None else invalid_submission_ns)
        def on_order_filled(self,f):
            self.callback_clocks.append({'order':str(f.client_order_id),'trade':str(f.trade_id),
                'execution_ns':f.ts_event,'native_init_ns':f.ts_init,'host_callback_ns':self.clock.timestamp_ns()})
            self.driver.on_fill(f,received_ns=self.clock.timestamp_ns()+receive_delay_ns)
            if expect_time_failure and f.ts_event>=self.driver.event.at_ns+10000:
                raise AssertionError('LATE_ACTUAL_FILL_RETURNED_WITHOUT_POLICY_TIME_FAILURE')
            p=self.driver.bridge.pending
            if p['filled']==p['quantity']:
                self.driver.on_terminal(str(f.client_order_id),'FILLED')
                if inject_late_callback:self.driver.on_fill(f,received_ns=self.clock.timestamp_ns())
        def on_order_canceled(self,e):self.driver.on_terminal(str(e.client_order_id),'CANCELLED')
        def on_order_expired(self,e):self.driver.on_terminal(str(e.client_order_id),'EXPIRED')
        def on_order_rejected(self,e):self.driver.on_terminal(str(e.client_order_id),'REJECTED')
        def on_order_denied(self,e):self.driver.on_terminal(str(e.client_order_id),'DENIED')
    try:
        engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.MARGIN,
            starting_balances=[types['money_from_cents'](capital)],base_currency=USD,default_leverage=Decimal(1),
            fee_model=Fee(),fill_model=Thin() if partial else FillModel(prob_slippage=0.),
            latency_model=LatencyModel(base_latency_nanos=native_latency_ns),bar_execution=False,trade_execution=False,
            allow_cash_borrowing=False,use_random_ids=False)
        AccountFactory.register_account_type(venue.value,types['account_type'])
        for n,iid in ids.items():engine.add_instrument(types['equity_type'](iid,Symbol(n),USD,6,Price.from_str('0.000001'),Quantity.from_int(1),0,0))
        strategy=Probe();engine.add_strategy(strategy);ticks=[]
        for e in events:
            if e.kind=='CLOSE':
                for i,(n,p) in enumerate(e.execution_prices or e.marks):
                    micro=p*10**6;assert micro.denominator==1
                    px=Price.from_str(f'{micro.numerator//10**6}.{micro.numerator%10**6:06d}');t=e.at_ns+i
                    ticks.append(QuoteTick(ids[n],px,px,Quantity.from_int(1000000),Quantity.from_int(1000000),t,t))
        engine.add_data(ticks)
        engine.add_data([CustomData(DataType(Boundary),Boundary(events[0].at_ns-1)),
                         CustomData(DataType(Boundary),Boundary(events[-1].at_ns+4*native_latency_ns+10000))],client_id=ClientId('SIGNED'))
        try:
            engine.run(end=events[-1].at_ns+4*native_latency_ns+10000,streaming=True);engine.end()
        except Exception as exc:
            if inject_unknown_submit or inject_late_callback or expect_time_failure or invalid_submission_ns is not None:
                return strategy.driver.failure_evidence(exc),None
            raise
        packet=strategy.driver.packet();verified=verify_packet(packet,CTX)
        return packet,verified
    finally:
        if 'strategy' in locals() and strategy.driver is not None and EMIT is not None:
            b=strategy.driver.bridge
            EMIT({'native_account_id':str(b._account().id),'context':CTX,'submissions':b.native_submission_count,
                'actual_fills':len(b.used_fills),'native_positions':strategy.positions(),'core_state':b.state,
                'default_ever':strategy.driver.default_ever,'technical_halt':b.halted,
                'active_event':None if strategy.driver.event is None else strategy.driver.event.id,
                'completed_events':len(strategy.driver.history),'native_account_type':type(b._account()).__name__,
                'actual_callback_clocks':strategy.callback_clocks})
        engine.dispose()


def save(record_property,packet):
    record_property('invented_signed_driver',json.dumps(encode(packet),sort_keys=True))


def simple_events():
    rates=(Rate('BORROW','AMZN',F(365,1000),'INVENTED_RATE'),)
    return [event('open','2024-01-05',instruction='TARGET',targets=(('AAPL',40),('AMZN',-40)),rates=rates),
        event('ex','2024-01-06',kind='EX',observed=at('2024-01-05'),rates=rates,
              actions=(Action('div','AAPL','CASH_DISTRIBUTION',F(1,10),'2024-01-06','2024-01-06','USD','INVENTED_ACTION'),)),
        event('exit','2024-01-08',instruction='EXIT',targets=(('AAPL',0),('AMZN',0)),terminal=True)]


def test_actual_driver_weekend_accrual_ex_same_date_payment_only_after_close_liquidation(record_property):
    packet,v=run_driver(simple_events());save(record_property,packet)
    assert v['actual_fills']==4 and v['native_calls']==v['source_reads']==v['writes']==0
    exend=next(r for r in packet['records'] if r['kind']=='END' and r['event']=='ex')
    assert exend['pending_claims']==['div'] and exend['state'].claims[0].paid_at is None
    assert any(r['kind']=='VALUATION_LIMITATION' for r in packet['records'])
    end=packet['records'][-1];assert not end['pending_claims'] and not end['terminal_unresolved_positions']
    assert end['state'].claims[0].paid_at=='2024-01-08'
    stream=end['state'].accruals[0];assert stream.exact_cents==120 and stream.recognized_cents==stream.settled_cents==120


def test_missing_locate_cancels_both_new_increments_without_native_submit(record_property):
    p,v=run_driver([event('no-locate','2024-01-05',instruction='TARGET',targets=(('AAPL',40),('AMZN',-40)),locate=False)])
    save(record_property,p);assert v['actual_fills']==p['native_submission_count']==0
    assert any(r['kind']=='PAIR_CANCELLED' for r in p['records'])


def test_partial_short_limits_long_actual_notional_and_borrow_survives_token_expiry(record_property):
    p,v=run_driver([simple_events()[0]],partial=True);save(record_property,p)
    end=p['records'][-1];assert dict(end['state'].positions)=={'AAPL':1,'AMZN':-1}
    assert end['borrow']['AMZN']==1
    use=next(iter(end['locate_usage'].values()));assert use['expired'] and use['filled']==1 and use['reserved']==40


def different_marks(e,long_price,short_price):
    marks=(('AAPL',F(long_price)),('AMZN',F(short_price)))
    return replace(e,marks=marks,execution_prices=marks if e.execution_prices else ())


def test_actual_forced_cover_sale_one_retry_and_later_nondefault_formation(record_property):
    opening=event('open','2024-01-05',instruction='TARGET',targets=(('AAPL',30),('AMZN',-30)))
    breach=different_marks(event('breach','2024-01-08'),10,40)
    flatten=different_marks(event('flatten','2024-01-09'),10,40)
    later=event('later','2024-01-10',instruction='TARGET',targets=(('AAPL',1),('AMZN',-1)))
    p,v=run_driver([opening,breach,flatten,later]);save(record_property,p)
    rows=[r for r in p['records'] if r.get('event')=='flatten']
    blocked=next(r for r in rows if r['kind']=='PROPOSAL_BLOCKED')
    assert blocked['phase']=='FORCED_COVERS' and blocked['proposal'].operands['funding_shortfall_cents']>0
    commands=[r['command'] for r in rows if r['kind']=='ORDER_COMMAND']
    assert [(c.phase,c.name) for c in commands]==[('FORCED_SALES','AAPL'),('FORCED_RETRY','AMZN')]
    assert any(r['kind']=='FLATTEN_COMPLETED' for r in rows)
    assert not p['records'][-1]['default_ever']
    assert dict(p['final_state'].positions)=={'AAPL':1,'AMZN':-1}


def test_fee_insufficient_long_sale_stays_pending_with_no_credit(record_property):
    opening=event('open','2024-01-05',instruction='TARGET',targets=(('AAPL',1),('AMZN',-1)),price=F(1))
    ex=event('ex','2024-01-06',kind='EX',price=F(1),observed=at('2024-01-05'),
        actions=(Action('payable','AMZN','CASH_DISTRIBUTION',F(98,100),'2024-01-06','2024-01-06','USD','INVENTED'),))
    payment=event('payment','2024-01-08',price=F(1))
    breach=different_marks(event('breach','2024-01-09',flat=2),F(1,100),F(148,100))
    exit=different_marks(event('exit','2024-01-10',instruction='EXIT',targets=(('AAPL',0),('AMZN',0)),flat=2,terminal=True),F(1,100),F(148,100))
    p,_=run_driver([opening,ex,payment,breach,exit],capital=250);save(record_property,p)
    rows=[r for r in p['records'] if r.get('event')=='exit']
    rejected=next(r for r in rows if r['kind']=='PROPOSAL_BLOCKED' and r['side']=='SELL')
    assert rejected['proposal'].operands['funding_shortfall_cents']==1
    assert len([r for r in rows if r['kind']=='PROPOSAL_BLOCKED' and r['side']=='SELL'])==1
    assert not any(r['kind']=='FILL' and r['command'].name=='AAPL' for r in rows)
    assert p['records'][-1]['terminal_unresolved_positions'] and dict(p['final_state'].positions)['AAPL']==1


def test_stale_ex_claim_default_remains_sticky_after_actual_recovery_and_blackout(record_property):
    opening=simple_events()[0]
    ex=event('ex-debit','2024-01-06',kind='EX',observed=at('2024-01-05'),
        actions=(Action('debit','AMZN','CASH_DISTRIBUTION',F(100),'2024-01-06','2024-02-01','USD','INVENTED'),))
    offset=event('ex-credit','2024-01-07',kind='EX',observed=at('2024-01-05'),
        actions=(Action('credit','AAPL','CASH_DISTRIBUTION',F(100),'2024-01-07','2024-02-01','USD','INVENTED'),))
    blackout=event('blackout','2024-01-08',eligible=False)
    later=event('later','2024-01-09',instruction='TARGET',targets=(('AAPL',20),('AMZN',-20)))
    p,v=run_driver([opening,ex,offset,blackout,later]);save(record_property,p)
    ends=[r for r in p['records'] if r['kind']=='END']
    assert ends[1]['default_ever'] and ends[1]['reconciliation']['core']['equity_cents']<0
    assert ends[2]['reconciliation']['core']['equity_cents']>0 and ends[2]['default_ever']
    assert ends[3]['pending_flatten'] is not None
    assert any(r['kind']=='INSTRUCTION_BLOCKED' and r['event']=='later' for r in p['records'])
    assert p['records'][-1]['default_ever'] and not any(q for _,q in p['final_state'].positions)


def test_rejected_negative_hypothetical_never_latches_actual_default(record_property):
    p,v=run_driver([event('reject','2024-01-05',instruction='TARGET',targets=(('AAPL',1),('AMZN',-1)),flat=100001)])
    save(record_property,p);assert v['actual_fills']==0 and not p['records'][-1]['default_ever']
    blocked=next(r for r in p['records'] if r['kind']=='PROPOSAL_BLOCKED')
    assert blocked['proposal'].operands['post_fill_admission']['equity_cents']==-1
    assert p['final_state'].free_cents==100000


def test_terminal_claims_survive_positions_and_settle_postterminal_without_new_risk(record_property):
    seq=simple_events();seq[1]=replace(seq[1],actions=(replace(seq[1].actions[0],payment_date='2024-01-10'),))
    seq.append(event('postterminal','2024-01-10'))
    p,v=run_driver(seq);save(record_property,p)
    exit=next(r for r in p['records'] if r['kind']=='END' and r['event']=='exit')
    assert exit['pending_claims']==['div'] and not exit['overdue_ever']
    assert p['final_state'].claims[0].paid_at=='2024-01-10' and not p['records'][-1]['pending_claims']


def test_unsupported_action_is_explicit_and_blocks_dependent_entry(record_property):
    e=event('unsupported','2024-01-05',actions=(Action('split','AAPL','SPLIT',None,None,None,None,'INVENTED'),),
            instruction='TARGET',targets=(('AAPL',40),('AMZN',-40)))
    p,v=run_driver([e]);save(record_property,p)
    assert v['actual_fills']==0 and p['records'][-1]['unsupported']
    assert any(r['kind']=='UNSUPPORTED_ACTION' for r in p['records'])


def test_expired_locate_not_reused_and_prior_reductions_stay_actual(record_property):
    opening=simple_events()[0]
    reversed=event('reverse','2024-01-08',instruction='TARGET',targets=(('AAPL',-20),('AMZN',20)))
    reversed=replace(reversed,locates=opening.locates)
    p,v=run_driver([opening,reversed]);save(record_property,p)
    assert v['actual_fills']==4 and not any(q for _,q in p['final_state'].positions)
    assert any(r['kind']=='PAIR_CANCELLED' and r['event']=='reverse' for r in p['records'])


@pytest.mark.parametrize('axis',['fee','claim','default','locate_expiry','mark','orderfill'])
def test_saved_rehashed_semantic_tamper_rejected(axis):
    p,_=run_driver(simple_events());a=deepcopy(p)
    if axis=='fee':next(r for r in a['records'] if r['kind']=='FILL')['actual_fill']['commission_token']='0.02 USD'
    elif axis=='claim':
        r=next(r for r in a['records'] if r['kind']=='EXTERNAL' and r['transition'].kind=='EX_ENTITLEMENT')
        r['transition']=replace(r['transition'],operands={**r['transition'].operands,'rounded_cents':999})
    elif axis=='default':a['records'][-1]['default_ever']=True
    elif axis=='locate_expiry':next(r for r in a['records'] if r['kind']=='LOCATE_EXPIRED')['usage']['expired']=False
    elif axis=='mark':a['records'].remove(next(r for r in a['records'] if r['kind']=='MARK'))
    else:next(r for r in a['records'] if r['kind']=='FILL')['actual_fill']['order_id']='WRONG'
    with pytest.raises(Exception,match='SIGNED_SAVED'):
        verify_bytes(canonical(encode(a)),CTX)


def test_saved_private_immutable_replay_fresh_process_blocks_native_and_write_opens(tmp_path,record_property):
    import os,sys,subprocess,hashlib
    from dataclasses import asdict
    from polar.gym_store import GymStore
    from polar.signed_event_saved import publish_packet,verify_stored
    p,v=run_driver(simple_events());save(record_property,p)
    store=GymStore(tmp_path,64*1024**2);ref=publish_packet(store,p)
    before={str(f.relative_to(tmp_path)):(hashlib.sha256(f.read_bytes()).hexdigest(),f.stat().st_mtime_ns)
            for f in tmp_path.rglob('*') if f.is_file()}
    assert verify_stored(tmp_path,ref['id'],CTX)['actual_fills']==4
    assert publish_packet(store,p)==ref
    script=r'''
import sys,json,os,importlib.abc,builtins,io
class NoNative(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.startswith('nautilus_trader'):raise RuntimeError('NATIVE_IMPORT_FORBIDDEN')
sys.meta_path.insert(0,NoNative())
from polar.signed_event_driver import AccountContext
from polar.signed_event_saved import verify_stored
old=os.open
def readonly(path,flags,*args,**kw):
 if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_TRUNC):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
 return old(path,flags,*args,**kw)
os.open=readonly
def guard(fn):
 def wrapped(path,mode='r',*args,**kw):
  if any(c in mode for c in 'wa+x'):raise RuntimeError('WRITE_OPEN_FORBIDDEN')
  return fn(path,mode,*args,**kw)
 return wrapped
builtins.open=guard(builtins.open);io.open=guard(io.open)
d=json.loads(sys.argv[3]);d['names']=tuple(d['names'])
r=verify_stored(sys.argv[1],sys.argv[2],AccountContext(**d))
print(json.dumps({k:v for k,v in r.items() if k!='packet'}))
'''
    r=subprocess.run([sys.executable,'-c',script,str(tmp_path),ref['id'],json.dumps(asdict(CTX))],cwd=tmp_path,
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=30)
    assert r.returncode==0,r.stderr
    result=json.loads(r.stdout);assert result['source_reads']==result['native_calls']==result['writes']==0
    assert before=={str(f.relative_to(tmp_path)):(hashlib.sha256(f.read_bytes()).hexdigest(),f.stat().st_mtime_ns)
                   for f in tmp_path.rglob('*') if f.is_file()}


def test_stress_maintenance_topup_is160_not_initial150(record_property):
    e=replace(simple_events()[0],maintenance_short=F(6,10))
    p,_=run_driver([e]);save(record_property,p)
    assert dict(p['final_state'].escrow)['AMZN']==64000
    assert any(r['kind']=='EXTERNAL' and r['transition'].kind=='COLLATERAL_TOPUP' and
               r['transition'].operands['requested_cents']==4000 for r in p['records'])


@pytest.mark.parametrize('mutation',[lambda e:replace(e,decision_ns=e.at_ns),
    lambda e:replace(e,marks=e.marks[:1]),lambda e:replace(e,flat_fee_cents=True),
    lambda e:replace(e,execution_prices=(('AAPL',F(999)),)),
    lambda e:replace(e,locates=(replace(e.locates[0],account='OTHER'),))])
def test_causal_or_typed_or_locate_metadata_never_silently_submits(mutation):
    e=mutation(simple_events()[0])
    if e.locates and e.locates[0].account=='OTHER':
        p,v=run_driver([e]);assert v['actual_fills']==0
    else:
        with pytest.raises(Exception):run_driver([e])


def test_unknown_submit_preserves_failed_prefix_and_cannot_be_saved_as_completed(record_property):
    from polar.signed_event_saved import packet_bytes
    p,_=run_driver([simple_events()[0]],inject_unknown_submit=True);save(record_property,p)
    assert p['status']=='TECHNICAL_UNFINALIZED' and p['technical_halt']
    assert p['active_command'] is not None and p['pending'] is not None
    assert any(r['kind']=='SUBMIT_UNKNOWN_EFFECT' for r in p['bridge_events'])
    assert not any(r['kind']=='FILL' for r in p['records'])
    with pytest.raises(Exception,match='SIGNED_SAVED_CONTEXT_SCHEMA'):packet_bytes(p)


def test_late_actual_callback_is_preserved_by_bridge_not_dropped_at_driver_boundary(record_property):
    p,_=run_driver([simple_events()[0]],inject_late_callback=True);save(record_property,p)
    assert p['technical_halt'] and p['status']=='TECHNICAL_UNFINALIZED'
    assert len([r for r in p['records'] if r['kind']=='FILL'])==1
    assert any(r['kind']=='DUPLICATE_CALLBACK_REJECTED' and r['actual_fill'] for r in p['bridge_events'])
    assert p['actual_native_observation']['positions']['AMZN']==-40


def test_positive_cash_income_recognition_settlement_does_not_reset_exact_origins(record_property):
    rate=Rate('FREE_CASH_INTEREST',None,F(365,1000),'INVENTED_POSITIVE_CASH_RATE')
    p,_=run_driver([event('fri','2024-01-05',rates=(rate,)),event('mon','2024-01-08',rates=(rate,)),
                    event('tue','2024-01-09',rates=(rate,))]);save(record_property,p)
    stream=p['final_state'].accruals[0]
    assert stream.exact_cents==F(4003,10) and stream.recognized_cents==stream.settled_cents==400
    assert p['final_state'].free_cents==100400 and not p['final_state'].receivables_cents


def test_due_payment_with_positive_equity_headroom_blocks_new_pair_then_resolved_later_formation(record_property):
    opening=simple_events()[0]
    ex=event('due-ex','2024-01-06',kind='EX',observed=at('2024-01-05'),
        actions=(Action('due','AMZN','CASH_DISTRIBUTION',F(25,2),'2024-01-06','2024-01-06','USD','INVENTED_DUE'),))
    due=event('due-formation','2024-01-08',instruction='TARGET',targets=(('AAPL',41),('AMZN',-41)),price=F(5))
    exit=event('resolve','2024-01-09',instruction='EXIT',targets=(('AAPL',0),('AMZN',0)))
    later=event('later','2024-01-10',instruction='TARGET',targets=(('AAPL',1),('AMZN',-1)))
    p,_=run_driver([opening,ex,due,exit,later]);save(record_property,p)
    rows=[r for r in p['records'] if r.get('event')=='due-formation']
    assert any(r['kind']=='MODEL_OVERDUE_PAYMENT_EPISODE' for r in rows)
    assert not any(r['kind']=='SUBMIT' for r in rows)
    end=next(r for r in rows if r['kind']=='END')
    assert end['reconciliation']['core']['equity_cents']>0 and not end['default_ever']
    assert p['final_state'].claims[0].paid_at=='2024-01-09'
    assert dict(p['final_state'].positions)=={'AAPL':1,'AMZN':-1} and p['records'][-1]['overdue_ever']


def test_matching_pending_actual_native_execution_after_host_event_boundary_is_retained_unfinalized(record_property):
    p,_=run_driver([simple_events()[0]],native_latency_ns=1000000,expect_time_failure=True);save(record_property,p)
    assert p.get('status')=='POLICY_UNFINALIZED' and p['policy_time_failure'] and not p['technical_halt']
    assert 'OUT_OF_EVENT_EXECUTION' in p['reason']
    assert dict(p['core_state'].positions)['AMZN']==-40
    assert p['actual_native_observation']['positions']['AMZN']==-40


def test_eligible_execution_delayed_receive_is_not_late_execution_and_saved_clock_is_checked(record_property):
    p,v=run_driver([simple_events()[0]],receive_delay_ns=86400*10**9);save(record_property,p)
    fills=[r for r in p['records'] if r['kind']=='FILL']
    assert len(fills)==2
    assert all(r['native_clock']['execution_ns']<r['native_clock']['boundary'].end_ns<r['native_clock']['received_ns']
               and r['native_clock']['status']=='ELIGIBLE_EXECUTION' for r in fills)
    for axis in ('execution_ns','received_ns','native_init_ns'):
        bad=deepcopy(p);f=next(r for r in bad['records'] if r['kind']=='FILL')
        if axis=='execution_ns':f['actual_fill'][axis]=f['native_clock']['boundary'].end_ns
        elif axis=='received_ns':f['native_clock'][axis]=0
        else:f['actual_fill'][axis]=0
        with pytest.raises(Exception):verify_bytes(canonical(encode(bad)),CTX)


def test_invalid_native_submission_timestamp_has_zero_native_effects(record_property):
    p,_=run_driver([simple_events()[0]],invalid_submission_ns=0);save(record_property,p)
    assert 'SUBMISSION_OUTSIDE_EVENT_BOUNDARY' in p['reason']
    assert not any(r['kind']=='SUBMIT' for r in p['records'])
    assert p['core_state'].free_cents==100000 and not p['core_state'].positions
    assert not any(p['actual_native_observation']['positions'].values())
