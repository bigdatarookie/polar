"""Invented actual pinned-engine component controls, no retained/Service run."""
from decimal import Decimal
from fractions import Fraction as F
import uuid
import json
from dataclasses import asdict, is_dataclass
import pytest

from polar.signed_account_core import State, recognize_distribution, pay_claim, accrue, settle_accrual, top_up
from polar.signed_native_bridge import TradingLot, settled_trade, native_types, SignedNativeBridge, BridgeError, cents, MarkIdentity, MarkEvent


def save_control(record_property, result):
    def encode(v):
        if is_dataclass(v):return asdict(v)
        if isinstance(v,F):return {'numerator':v.numerator,'denominator':v.denominator}
        raise TypeError(type(v).__name__)
    record_property('invented_native_component_control', json.dumps(result,sort_keys=True,default=encode))


def test_partial_basis_allocation_releases_remaining_cents_exactly():
    lot,pnl,cross = settled_trade(TradingLot(), 'SELL', 3, F('10.005000'))
    assert (lot,pnl,cross) == (TradingLot(-3,-3002),0,False)
    lot,pnl,cross = settled_trade(lot,'BUY',1,F('9.995000'))
    assert lot == TradingLot(-2,-2001) and pnl == 1
    lot,pnl,cross = settled_trade(lot,'BUY',2,F('9.995000'))
    assert lot == TradingLot() and pnl == 2 and not cross


def engine_control(tape, *, exact=True, partial=False, external=False, duplicate=False, unexpected_cross=False, default=False, mark_recovery=False, proposal_fees=None):
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FeeModel, FillModel, LatencyModel
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig, RiskEngineConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue, ClientOrderId
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce, PositionSide, BookType
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.accounting.factory import AccountFactory
    from nautilus_trader.model.book import OrderBook
    from nautilus_trader.model.data import BookOrder
    from polar.signed_account_core import record_confirmed_fill, mark
    types = native_types(); venue=Venue('BRIDGE'+uuid.uuid4().hex.upper()); iid=InstrumentId(Symbol('X'),venue)
    engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),
                         risk_engine=RiskEngineConfig(bypass=False,max_order_submit_rate='50/00:00:01'),run_analysis=False))
    out={'fills':[],'snapshots':[],'terminals':[],'errors':[],'gate_failures':[],'native_account_type':None}
    class Fee(FeeModel):
        def get_commission(self,order,fill_qty,fill_px,instrument):return types['money_from_cents'](1)
    class Thin(FillModel):
        def get_orderbook_for_fill_simulation(self,instrument,order,best_bid,best_ask):
            book=OrderBook(instrument_id=instrument.id,book_type=BookType.L2_MBP)
            book.add(BookOrder(OrderSide.BUY,best_bid,Quantity.from_int(1),1),0,0)
            book.add(BookOrder(OrderSide.SELL,best_ask,Quantity.from_int(1),2),0,0)
            return book
    class Probe(Strategy):
        def __init__(self):
            super().__init__(StrategyConfig(strategy_id='BRIDGE',order_id_tag='001',log_events=False,log_commands=False))
            self.i=0;self.core=State(100000);self.px=F(tape[0][2]);self.bridge=None;self.current=None
        def positions(self):
            result=0
            for p in self.cache.positions_open(instrument_id=iid):
                q=F(p.quantity.as_decimal());assert q.denominator==1
                result += q.numerator*(-1 if p.side==PositionSide.SHORT else 1)
            return {'X':result}
        def on_start(self):
            self.subscribe_quote_ticks(iid)
            if exact:self.bridge=SignedNativeBridge(self.core,{'X':iid},self.submit_order,self.positions,
                lambda:engine.portfolio.account(venue),initial_cents=100000)
        def on_quote_tick(self,tick):
            self.px=F(tick.bid_price.as_decimal());self.i+=1
            if self.i%2:
                side,qty,_=tape[(self.i-1)//2]
                order=self.order_factory.market(instrument_id=iid,order_side=OrderSide.BUY if side=='BUY' else OrderSide.SELL,
                      quantity=Quantity.from_int(qty),time_in_force=TimeInForce.IOC if partial else TimeInForce.GTC,
                      client_order_id=ClientOrderId('intent-'+str(self.i)))
                self.current=order
                if exact and unexpected_cross and self.i == 3:
                    # Deliberate fault injection: a physical execution bypassed
                    # the research gate. It must be preserved, never erased.
                    self.submit_order(order)
                elif exact:
                    try:
                        self.bridge.propose_and_submit('intent-'+str(self.i),order,self.px,
                                                      1 if proposal_fees is None else proposal_fees[(self.i-1)//2],{'X':self.px},
                                                      mark_event=MarkEvent('valuation-'+str(self.i),tick.ts_event,
                                                        (MarkIdentity('X','quote-'+str(tick.ts_event),'INVENTED_X',tick.ts_event,tick.ts_event,'MODELED','INVENTED_CURRENT_QUOTE'),)),
                                                      located_cap=qty,locate_provenance='INVENTED_LOCATE')
                    except BridgeError as exc:
                        if not mark_recovery:raise
                        out['gate_failures'].append(str(exc))
                    # A pending admission cannot spend/locate the same resource.
                    if self.bridge.pending is not None:
                        try:self.bridge.propose_and_submit('double-spend',order,self.px,1,{'X':self.px},
                            mark_event=MarkEvent('valuation-double-'+str(self.i),tick.ts_event,
                              (MarkIdentity('X','quote-'+str(tick.ts_event),'INVENTED_X',tick.ts_event,tick.ts_event,'MODELED','INVENTED_CURRENT_QUOTE'),)))
                        except BridgeError as exc:out['gate_failures'].append(str(exc))
                else:self.submit_order(order)
            else:
                if mark_recovery and self.i==4:return  # no intervening standalone high-mark reconcile
                account=engine.portfolio.account(venue);out['native_account_type']=type(account).__name__
                if exact:
                    if self.bridge.pending is not None:self.cancel_order(self.current)
                    if external and len(out['snapshots'])==0:
                        b=self.bridge
                        b.apply_external(recognize_distribution(b.state,'claim','X',F('0.015'),'2024-01-02','2024-01-03','INVENTED'),{'X':self.px})
                        b.apply_external(pay_claim(b.state,'pay','claim','2024-01-03'),{'X':self.px})
                        if self.positions()['X']<0:
                            b.apply_external(top_up(b.state,'top','X',3),{'X':self.px})
                        b.apply_external(accrue(b.state,'borrow','BORROW',100,F(1,2),86400,'INVENTED',stream_id='b',base_kind='MARKED_SHORT_NOTIONAL'),{'X':self.px})
                        b.apply_external(settle_accrual(b.state,'settle','b'),{'X':self.px})
                    if default and len(out['snapshots'])==0:
                        b=self.bridge
                        b.apply_external(recognize_distribution(b.state,'default-claim','X',F(2000),'2024-01-02','2024-01-03','INVENTED_STALE_PRE_EX_CUM_MARK'),{'X':self.px})
                        blocked=pay_claim(b.state,'blocked-pay','default-claim','2024-01-03')
                        assert blocked.status=='SETTLEMENT_BLOCKED_INSUFFICIENT_FREE_CASH'
                        b.apply_external(blocked,{'X':self.px})
                        funded=pay_claim(b.state,'funded-pay','default-claim','2024-01-03',funding_mode='HYPOTHETICAL_MANDATORY_FUNDING',funding_assumption='INVENTED_EXPLICIT_MODEL_DEBIT')
                        b.apply_external(funded,{'X':self.px})
                    if not self.bridge.halted:out['snapshots'].append(self.bridge.reconcile({'X':self.px}))
                else:
                    un=sum(cents(p.unrealized_pnl(Price.from_str(str(self.px.numerator/self.px.denominator))))
                           for p in self.cache.positions_open(instrument_id=iid))
                    out['snapshots'].append({'native_equity':cents(account.balances_total()[USD])+un,
                                             'core_equity':mark(self.core,{'X':self.px})['equity_cents']})
        def on_order_filled(self,event):
            out['fills'].append({'order':str(event.client_order_id),'trade':str(event.trade_id),
                                 'q':int(F(event.last_qty.as_decimal())),'price':str(event.last_px),'fee':cents(event.commission)})
            if exact:
                try:
                    self.bridge.record_fill(event,{'X':self.px})
                    if self.bridge.pending['filled']==self.bridge.pending['quantity']:
                        self.bridge.record_terminal(str(event.client_order_id),'FILLED')
                    if duplicate:
                        with pytest.raises(BridgeError,match='DUPLICATE_CALLBACK'):
                            self.bridge.record_fill(event,{'X':self.px})
                except BridgeError as exc:
                    if not unexpected_cross:raise
                    out['errors'].append(str(exc))
            else:
                self.core=record_confirmed_fill(self.core,'fill-'+str(len(out['fills'])),'X',
                    'BUY' if event.order_side==OrderSide.BUY else 'SELL',int(F(event.last_qty.as_decimal())),
                    F(event.last_px.as_decimal()),cents(event.commission),{'X':self.px},
                    execution_provenance='INVENTED_ACTUAL_NATIVE',located_cap=100,locate_provenance='INVENTED').after
        def on_order_canceled(self,event):
            out['terminals'].append('CANCELLED')
            if exact:self.bridge.record_terminal(str(event.client_order_id),'CANCELLED')
        def on_order_expired(self,event):
            out['terminals'].append('EXPIRED')
            if exact:self.bridge.record_terminal(str(event.client_order_id),'EXPIRED')
        def on_order_rejected(self,event):
            out['terminals'].append('REJECTED')
            if exact:self.bridge.record_terminal(str(event.client_order_id),'REJECTED')
        def on_order_denied(self,event):
            out['terminals'].append('DENIED')
            if exact:self.bridge.record_terminal(str(event.client_order_id),'DENIED')
    try:
        engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.MARGIN,
                         starting_balances=[types['money_from_cents'](100000)],base_currency=USD,
                         default_leverage=Decimal(1),fee_model=Fee(),fill_model=Thin() if partial else FillModel(prob_slippage=0.),
                         latency_model=LatencyModel(base_latency_nanos=0),bar_execution=False,trade_execution=False,
                         allow_cash_borrowing=False,use_random_ids=False)
        if exact:AccountFactory.register_account_type(venue.value,types['account_type'])
        engine.add_instrument(types['equity_type'](iid,Symbol('X'),USD,6,Price.from_str('0.000001'),Quantity.from_int(1),0,0))
        strategy=Probe();engine.add_strategy(strategy)
        ticks=[]
        for i,(_,_,price) in enumerate(tape):
            for j in (0,1):
                t=1700000000000000000+(i*2+j)*10**9;px=Price.from_str(price)
                ticks.append(QuoteTick(iid,px,px,Quantity.from_int(1000000),Quantity.from_int(1000000),t,t))
        engine.add_data(ticks);engine.run();engine.end()
        if exact:
            out['events']=strategy.bridge.events;out['pending']=strategy.bridge.pending;out['halted']=strategy.bridge.halted
            out['state']=strategy.bridge.state;out['account_fills']=engine.portfolio.account(venue).exact_fills
            out['external_adjustment']=strategy.bridge.external_adjustment_cents
            out['native_positions']=strategy.positions();out['submissions']=strategy.bridge.native_submission_count
            out['survival_failed']=strategy.bridge.model_survival_failed
        return out
    finally:engine.dispose()


def test_stock_half_cent_oracle_is_observably_not_core_cent_economics(record_property):
    r=engine_control([('BUY',1,'10.000000'),('SELL',1,'10.005000')],exact=False)
    save_control(record_property,r)
    assert len(r['fills'])==2
    assert r['snapshots'][-1] == {'native_equity':99999,'core_equity':99998}


@pytest.mark.parametrize('tape',[
    [('BUY',1,'10.000000'),('SELL',1,'10.005000')],
    [('SELL',3,'10.005000'),('BUY',1,'9.995000'),('BUY',2,'9.995000')],
    [('BUY',3,'10.005001'),('SELL',1,'10.000001'),('SELL',2,'10.000001')],
    [('SELL',1,'10.000001'),('BUY',1,'10.005001'),('BUY',1,'10.005001'),('SELL',1,'10.000001')],
    [('BUY',1,'10.000001'),('SELL',1,'10.005001'),('SELL',1,'10.005001'),('BUY',1,'10.000001')],
])
def test_exact_native_account_core_fill_mark_fee_and_close_open_reconcile(tape, record_property):
    r=engine_control(tape)
    save_control(record_property,r)
    assert len(r['fills'])==len(tape) and not r['halted'] and r['pending'] is None
    assert r['native_account_type']=='ExactCentMarginAccount'
    assert all(s['residual_cents']==0 for s in r['snapshots'])
    assert sum(f['fee'] for f in r['fills'])==len(tape)
    assert all(s['native']['actual_fee_cents']==i+1 for i,s in enumerate(r['snapshots']))


def test_actual_claim_settlement_escrow_and_accrual_external_recognition_once(record_property):
    r=engine_control([('SELL',3,'10.005000'),('BUY',3,'10.005000')],external=True)
    save_control(record_property,r)
    assert not r['halted'] and all(s['residual_cents']==0 for s in r['snapshots'])
    assert r['external_adjustment']==-4 # HE(3*1.5)=4 payable, subcent borrow rounds0


def test_native_partial_fill_terminal_census_and_serial_barrier(record_property):
    r=engine_control([('SELL',3,'10.005000')],partial=True)
    save_control(record_property,r)
    assert len(r['fills'])==1 and r['fills'][0]['q']==1
    assert r['pending'] is None and not r['halted'] and r['terminals']
    assert dict(r['state'].positions)['X']==-1
    assert r['snapshots'][0]['residual_cents']==0


def test_core_funding_rejection_has_zero_native_submissions_fills_fees(record_property):
    r=engine_control([('SELL',1000000,'10.005000')])
    save_control(record_property,r)
    assert r['submissions']==0 and not r['fills'] and not r['account_fills']
    assert r['state']==State(100000) and next(e for e in r['events'] if e['kind']=='ADMISSION')['native_submissions']==0


def test_no_credit_sale_fee_cannot_mint_native_cash_or_submit(record_property):
    r=engine_control([('BUY',99999,'0.010000'),('SELL',1,'0.000001')])
    save_control(record_property,r)
    assert r['submissions']==1 and len(r['fills'])==1 and dict(r['state'].positions)['X']==99999
    admissions=[e for e in r['events'] if e['kind']=='ADMISSION']
    assert admissions[-1]['status']=='SETTLEMENT_BLOCKED_INSUFFICIENT_FREE_CASH'
    assert admissions[-1]['native_submissions']==0


def test_serial_pending_prevents_double_spend_or_locate(record_property):
    r=engine_control([('SELL',3,'10.005000')],partial=True)
    save_control(record_property,r)
    assert r['gate_failures']==['PENDING_SERIAL_BARRIER'] and r['submissions']==1


def test_duplicate_callback_never_installs_same_fill_or_fee_twice(record_property):
    r=engine_control([('BUY',1,'10.000001')],duplicate=True)
    save_control(record_property,r)
    assert r['halted'] and len(r['fills'])==1 and dict(r['state'].positions)['X']==1
    assert len([e for e in r['events'] if e['kind']=='CONFIRMED_NATIVE_FILL'])==1
    assert len([e for e in r['events'] if e['kind']=='DUPLICATE_CALLBACK_REJECTED'])==1


def test_unexpected_actual_crossing_retains_native_truth_and_halts_not_fake_no_fill(record_property):
    r=engine_control([('SELL',1,'10.000001'),('BUY',2,'10.005001')],unexpected_cross=True)
    save_control(record_property,r)
    assert r['halted'] and r['native_positions']['X']==1 and dict(r['state'].positions)['X']==-1
    assert r['account_fills'][-1]['unsupported_crossing'] is True and len(r['fills'])==2
    assert r['errors']==['UNEXPECTED_ACTUAL_FILL']
    assert any(e['kind']=='NON_RECONCILED_EXECUTION' and e['actual_fill']['quantity_token']=='2' for e in r['events'])


def test_default_explicit_funding_and_blocked_payment_never_double_recognize_or_hide_model_default(record_property):
    r=engine_control([('SELL',1,'10.000001')],default=True)
    save_control(record_property,r)
    assert r['survival_failed'] and not r['halted'] and r['state'].free_cents<0
    assert r['external_adjustment']==-200000
    assert r['snapshots'][-1]['core']['status']=='DEFAULT'
    assert r['snapshots'][-1]['residual_cents']==0


def test_reconciliation_type_or_position_failure_is_retained_and_halts():
    # No native invocation: isolated malformed callback contract control.
    b=SignedNativeBridge(State(100), {'X':'X.INVENTED'}, lambda o:None,
                         lambda:{'X':True}, lambda:None, initial_cents=100)
    with pytest.raises(BridgeError,match='NATIVE_POSITION_TYPES'):
        b.reconcile({'X':F(1)})
    assert b.halted and b.events[-1]['kind']=='NON_RECONCILED_ACCOUNT'


def test_current_mark_default_before_rejected_order_survives_recovery(record_property):
    r=engine_control([('SELL',1,'10.000000'),('SELL',1,'2000.000000'),('SELL',1,'10.000000')],mark_recovery=True)
    save_control(record_property,r)
    assert r['survival_failed'] is True
    assert r['submissions']==1 and len(r['fills'])==1 and dict(r['state'].positions)['X']==-1
    adverse=[e for e in r['events'] if e['kind']=='EXISTING_BOOK_MARK' and e['core']['equity_cents']<=0]
    assert adverse[0]['core']['equity_cents']==-99001 and adverse[0]['mark_age_ns']=={'X':0}
    assert adverse[0]['sticky_model_survival_failed'] and adverse[0]['source_identities'][0]['basis']=='MODELED'
    assert len([e for e in r['events'] if e['kind']=='STICKY_DEFAULT_ADMISSION_BLOCK'])==2


def test_rejected_hypothetical_postfill_insolvency_is_not_actual_default(record_property):
    # This fee is a supplied HYPOTHETICAL proposal operand only. The order
    # rejects before submit; actual later native commission remains exactly1c.
    r=engine_control([('BUY',1,'10.000000'),('BUY',1,'10.000000')],proposal_fees=[100001,1])
    save_control(record_property,r)
    first_mark=next(e for e in r['events'] if e['kind']=='EXISTING_BOOK_MARK')
    first_proposal=next(e for e in r['events'] if e['kind']=='ADMISSION')
    assert first_mark['core']['equity_cents']==100000 > 0
    assert first_proposal['operands']['post_fill_admission']['equity_cents']==-1 < 0
    assert first_proposal['status']!='ADMITTED_PROPOSAL_NOT_EXECUTION' and first_proposal['native_submissions']==0
    assert r['survival_failed'] is False and r['submissions']==1 and len(r['fills'])==1
    assert r['fills'][0]['fee']==1 and dict(r['state'].positions)['X']==1


def test_duplicate_mark_event_deduplicates_history_but_changed_or_future_metadata_rejects():
    from types import SimpleNamespace
    from dataclasses import replace
    from nautilus_trader.model.enums import OrderSide
    from nautilus_trader.model.objects import Quantity
    class Account:
        exact_lots={}
        def exact_marked_trading_equity(self,marks):
            return {'native_cash_cents':100,'exact_unrealized_cents':0,'exact_trading_equity_cents':100,
                    'exact_realized_cents':0,'actual_fee_cents':0}
    b=SignedNativeBridge(State(100),{'X':'X.INVENTED'},lambda o:None,lambda:{},lambda:Account(),initial_cents=100)
    event=MarkEvent('valuation',10,(MarkIdentity('X','source-event','source-pin',9,None,'UNKNOWN','ORIGINAL_K_UNKNOWN'),))
    def order(i):return SimpleNamespace(client_order_id='order'+str(i),instrument_id='X.INVENTED',side=OrderSide.BUY,quantity=Quantity.from_int(100000))
    for i in (1,2):
        result=b.propose_and_submit('intent'+str(i),order(i),F(10),1,{'X':F(10)},mark_event=event)
        assert result['native_submissions']==0
    assert len([e for e in b.events if e['kind']=='EXISTING_BOOK_MARK'])==1 and not b.model_survival_failed
    with pytest.raises(BridgeError,match='REUSED_WITH_CHANGED'):
        b.propose_and_submit('intent3',order(3),F(11),1,{'X':F(11)},mark_event=event)
    future=replace(event,valuation_id='future',identities=(replace(event.identities[0],observed_ns=11),))
    with pytest.raises(BridgeError,match='PROVENANCE_OR_FUTURE'):
        b.propose_and_submit('intent4',order(4),F(10),1,{'X':F(10)},mark_event=future)
    assert b.native_submission_count==0 and b.state==State(100)
