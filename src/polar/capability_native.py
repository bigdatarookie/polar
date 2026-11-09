"""Fixed seven-account Nautilus adapter; no bars, learned models or legacy intents."""
from decimal import Decimal
from fractions import Fraction
import importlib.metadata
import platform
import sys
import time

from .capability_contract import (require, CapabilityError, SYMBOLS, ACCOUNTS, I, OPEN_DATES,
    CLOSE_DATES, ns, cents, money, rational, validate)
from .capability_profile import allocation, identity


def settlement_boundaries():
    """Price-free data barriers; no new quote, mark, sample or route timestamp."""
    return tuple(ns(day+'T14:30:00.000000Z')+1000*(route+1)+1
                 for day in OPEN_DATES for route in range(1,len(SYMBOLS)+1))


def failure_context(code,pending,awaiting,callback_kind,callback_ns):
    # Diagnostic only; never substitute a successful settlement or expected value.
    return {'schema':'polar.capability-adapter-failure-context/1','code':str(code)[:96],
        'pending_count':len(pending),'pending_ids':[str(key)[:128] for key in sorted(pending)[:16]],
        'awaiting_logical_id':None if awaiting is None else str(awaiting.get('logical_order_id','UNKNOWN'))[:128],
        'callback_kind':str(callback_kind)[:96],
        'callback_ns':None if callback_ns is None else str(callback_ns)[:32]}


def one_account(account, target_rows, observations, *, charge, raw_callback):
    require(account in ACCOUNTS and importlib.metadata.version('nautilus_trader')=='1.231.0',
            'NATIVE_ACCOUNT_FAILURE')
    require(sys.version_info[:2]==(3,13) and platform.system()=='Linux'
            and platform.machine()=='aarch64','NATIVE_ACCOUNT_FAILURE')
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FixedFeeModel, FillModel, LatencyModel
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, PortfolioConfig, StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue, ClientId
    from nautilus_trader.model.instruments import Equity
    from nautilus_trader.model.objects import Price, Quantity, Money
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import QuoteTick, MarkPriceUpdate, CustomData, DataType
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce

    class Boundary(Data):
        def __init__(self,timestamp):self.timestamp=timestamp
        @property
        def ts_event(self):return self.timestamp
        @property
        def ts_init(self):return self.timestamp

    venue=Venue('XCAP');ids={s:InstrumentId.from_str(s+'.XCAP') for s in SYMBOLS}
    opens={day:[r for r in observations if r['kind']=='OPEN' and r['day']==day] for day in OPEN_DATES}
    closes={day:[r for r in observations if r['kind']=='CLOSE' and r['day']==day] for day in CLOSE_DATES}
    require(len(observations)==28 and all(len(rows)==4 and [r['source_symbol'] for r in rows]==list(SYMBOLS)
            for rows in list(opens.values())+list(closes.values())),'INPUT_INTEGRITY')
    end=ns(OPEN_DATES[1]+'T14:30:00.000000Z')+10000
    engine=None;adapter=None
    charge(account)  # Host fsynced charge acknowledgement BEFORE constructor.
    started=time.monotonic_ns()
    try:
        engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),
            portfolio=PortfolioConfig(use_mark_prices=True,bar_updates=False),run_analysis=False))
        class Adapter(Strategy):
            def __init__(self):
                super().__init__(StrategyConfig(strategy_id='CAPABILITY',order_id_tag='001',
                                                log_events=False,log_commands=False))
                self.held={s:0 for s in SYMBOLS};self.quotes={};self.events=[];self.samples=[]
                self.allocations=[];self.pending={};self.awaiting_balance=None
                self.callback_kind='constructed';self.callback_ns=None
                self.expected_cash=10000000;self.native_ids={};self.fill_ids={};self.fee_ids={};self.used_logical=set();self.failed=None
            def guard(self,condition,code):
                if not condition:
                    self.failed=code
                    context=failure_context(code,self.pending,self.awaiting_balance,self.callback_kind,self.callback_ns)
                    try:raw_callback({'callback':'adapter_failure_context','context':context})
                    except Exception:pass  # Preserve the original guard if diagnostic publication also fails.
                require(condition,code)
            def context(self,kind,event):
                self.callback_kind=kind;self.callback_ns=event.ts_event
            def cash(self):
                value=Fraction(engine.portfolio.account(venue).balances_total()[USD].as_decimal())*100
                self.guard(value.denominator==1 and value>=0,'NATIVE_FILL_MISMATCH')
                return value.numerator
            def alert(self,name,timestamp,callback):
                self.clock.set_time_alert_ns(name,timestamp,callback)
            def on_start(self):
                for iid in ids.values():self.subscribe_quote_ticks(iid)
                self.alert('initial',ns(I)+10000,lambda e:self.sample(e,0,None))
                for phase,day in zip(('entry','exit'),OPEN_DATES):
                    Q=ns(day+'T14:30:00.000000Z')
                    self.alert(phase+'-snapshot',Q+1000,lambda e,p=phase,q=Q,d=day:self.snapshot(e,p,q,d))
                for index,day in enumerate(CLOSE_DATES,1):
                    self.alert('close-'+day,ns(day+'T21:00:00.000000Z')+10000,
                               lambda e,i=index,d=day:self.sample(e,i,d))
                self.alert('terminal',end,lambda e:self.sample(e,6,None))
            def on_quote_tick(self,event):
                self.context('on_quote_tick',event)
                symbol=event.instrument_id.symbol.value
                self.guard(symbol in SYMBOLS,'MAPPING_MISMATCH')
                self.quotes[symbol]=event
            def positions(self):
                actual={s:0 for s in SYMBOLS}
                for p in self.cache.positions_open():
                    self.guard(p.instrument_id in ids.values(),'UNEXPECTED_ACCOUNT_STATE')
                    qty=Fraction(p.signed_qty)
                    self.guard(qty.denominator==1 and qty>=0,'UNEXPECTED_ACCOUNT_STATE')
                    actual[p.instrument_id.symbol.value]+=qty.numerator
                self.guard(actual==self.held,'UNEXPECTED_ACCOUNT_STATE')
                return actual
            def settled(self):
                self.guard(not self.pending and self.awaiting_balance is None,'PENDING_ORDER')
                self.guard(self.cash()==self.expected_cash,'NATIVE_FILL_MISMATCH')
                self.positions()
            def snapshot(self,event,phase,Q,day):
                self.context('snapshot-'+phase,event)
                self.settled()
                rows=opens[day]
                self.guard(set(self.quotes)==set(SYMBOLS) and all(
                    self.quotes[s].ts_event==Q+i and self.quotes[s].ts_init==Q+i
                    and Fraction(self.quotes[s].ask_price.as_decimal())==Fraction(cents(rows[i]['price']),100)
                    and self.quotes[s].bid_price==self.quotes[s].ask_price
                    for i,s in enumerate(SYMBOLS)),'QUOTE_PHASE_MISMATCH')
                quotes={r['source_symbol']:{k:v for k,v in r.items()
                    if k not in ('kind','day')} for r in rows}
                result,orders=allocation(account,phase,Q,self.cash(),self.held,quotes,target_rows)
                self.allocations.append(result)
                for route,order in enumerate(orders,1):
                    self.alert(phase+'-'+str(route),Q+1000*(route+1),
                        lambda e,o=order,p=phase,r=route:self.route(e,o,p,r))
            def route(self,event,intent,phase,route):
                self.context('route-'+phase+'-'+str(route),event)
                self.settled()
                symbol=intent['source_symbol'];qty=intent['quantity'];price=cents(intent['price'],positive=True)
                self.guard(type(qty) is int and 0<qty<=1000000,'QUOTE_QUANTITY_EXCEEDED')
                before=self.cash();held=self.held[symbol]
                self.guard((before>=qty*price+100 if phase=='entry'
                    else held>=qty and before+qty*price>=100),'FEE_INFEASIBLE')
                logical=account+'/'+phase+'/'+str(route)
                self.guard(logical not in self.used_logical,'ORDER_SEQUENCE_MISMATCH')
                order=self.order_factory.market(instrument_id=ids[symbol],
                    order_side=OrderSide.BUY if phase=='entry' else OrderSide.SELL,
                    quantity=Quantity.from_int(qty),time_in_force=TimeInForce.GTC)
                key=str(order.client_order_id)
                self.guard(key not in self.native_ids,'ORDER_SEQUENCE_MISMATCH')
                self.native_ids[key]=logical;self.used_logical.add(logical)
                self.pending[key]={'logical_order_id':logical,'phase':phase,'route_sequence':route,
                    **identity(symbol),'side':intent['side'],'logical_route_ns':str(event.ts_event),
                    'quantity':qty,'price_reference':intent['price'],'cash_before':money(before),
                    'held_before':held}
                self.submit_order(order)
            def raw(self,event,callback):
                self.context(callback,event)
                raw_callback({'callback':callback,'event_type':type(event).__name__,
                              'event':type(event).to_dict(event)})
            def on_order_submitted(self,event):
                self.raw(event,'on_order_submitted')
                key=str(event.client_order_id)
                self.guard(key in self.pending,'NATIVE_FILL_MISMATCH')
                row=self.pending[key]
                self.guard(event.ts_event==int(row['logical_route_ns'])
                    and event.ts_init==int(row['logical_route_ns']),'NATIVE_FILL_MISMATCH')
                self.events.append({'kind':'ORDER_SUBMITTED','sequence':len(self.events),**row,
                    'native_event_ns':str(event.ts_event),'native_init_ns':str(event.ts_init)})
            def on_order_filled(self,event):
                self.raw(event,'on_order_filled')
                key=str(event.client_order_id)
                self.guard(key in self.pending and self.awaiting_balance is None,'NATIVE_FILL_MISMATCH')
                order=self.pending.pop(key);quantity=Fraction(event.last_qty.as_decimal())
                native_fill=str(event.trade_id);native_fee=str(event.id)
                self.guard(native_fill not in self.fill_ids and native_fee not in self.fee_ids,
                           'NATIVE_FILL_MISMATCH')
                self.fill_ids[native_fill]=order['logical_order_id']+'/fill/1'
                self.fee_ids[native_fee]=order['logical_order_id']+'/fee'
                price=Fraction(event.last_px.as_decimal())*100;fee=Fraction(event.commission.as_decimal())*100
                self.guard(quantity==order['quantity'] and price==cents(order['price_reference'])
                    and fee==100 and event.commission.currency==USD
                    and event.ts_event==int(order['logical_route_ns'])
                    and event.ts_init==int(order['logical_route_ns']),'NATIVE_FILL_MISMATCH')
                signed=order['quantity']*(1 if order['side']=='BUY' else -1)
                symbol=order['source_symbol'];self.held[symbol]+=signed
                self.expected_cash=cents(order['cash_before'])-signed*price.numerator-100
                self.awaiting_balance={k:v for k,v in order.items() if k not in
                                       ('cash_before','held_before','price_reference')}
                self.awaiting_balance.update(kind='ORDER_FILLED',
                    native_event_ns=str(event.ts_event),native_init_ns=str(event.ts_init),
                    logical_fill_id=order['logical_order_id']+'/fill/1',fill_price=money(price.numerator),
                    held_after=self.held[symbol],fee_receipt={'logical_fee_id':order['logical_order_id']+'/fee',
                        'amount':money(fee.numerator),'currency':'USD','native_receipt_kind':'ORDER_FILLED_COMMISSION'})
                self.alert('settle-'+order['logical_order_id'],event.ts_event+1,self.balance)
            def balance(self,event):
                self.context('balance',event)
                self.guard(self.awaiting_balance is not None,'NATIVE_FILL_MISMATCH')
                cash=self.cash();self.guard(cash==self.expected_cash,'NATIVE_FILL_MISMATCH')
                self.positions()
                self.events.append({**self.awaiting_balance,'sequence':len(self.events),'cash_after':money(cash)})
                self.awaiting_balance=None
            def on_order_event(self,event):
                self.raw(event,'on_order_event')
                self.guard(type(event).__name__ not in ('OrderRejected','OrderDenied','OrderCanceled',
                    'OrderExpired','OrderCancelRejected','OrderModifyRejected'),'NATIVE_ACCOUNT_FAILURE')
            def on_event(self,event):
                self.raw(event,'on_event')
            def sample(self,event,index,day):
                self.context('sample-'+str(index),event)
                self.settled();positions=[];exposure=0
                mark_rows={} if day is None else {r['source_symbol']:r for r in closes[day]}
                for symbol in SYMBOLS:
                    qty=self.held[symbol];mark=mark_rows.get(symbol) if qty else None
                    self.guard(not qty or mark is not None,'MISSING_HELD_MARK')
                    if mark:exposure+=qty*cents(mark['price'],positive=True)
                    positions.append({**identity(symbol),'quantity':qty,
                        'mark':mark['price'] if mark else None,
                        'mark_event_ns':mark['quote_event_ns'] if mark else None,
                        'mark_source':mark['source'] if mark else None,
                        'mark_requirement':'ADMITTED_HELD_MARK' if qty else 'NOT_REQUIRED_ZERO_QUANTITY'})
                native=engine.portfolio.net_exposures(venue).get(USD)
                native_cents=Fraction(native.as_decimal())*100 if native is not None else Fraction()
                self.guard(native_cents==exposure,'METRIC_MISMATCH')
                cash=self.cash();nav=cash+exposure
                self.guard(nav>0 and (index!=6 or not any(self.held.values())),'INVALID_NAV')
                nominal=ns(I) if index==0 else (end-10000 if index==6 else ns(day+'T21:00:00.000000Z'))
                row={'logical_sample_id':account+'/'+str(index),'sample_index':index,
                    'role':'INITIAL' if index==0 else ('TERMINAL' if index==6 else 'CLOSE'),
                    'effective_nominal_ns':str(nominal),'native_sample_ns':str(event.ts_event),
                    'cash':money(cash),'positions':positions,'native_exposure_usd':money(exposure),
                    'nav':money(nav),'nav_exact_usd':rational(Fraction(nav,100)),
                    'outstanding_order_count':0,'claims_count':0}
                validate(row,'sample');self.samples.append(row)
        engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.CASH,
            starting_balances=[Money.from_str('100000.00 USD')],base_currency=USD,
            fee_model=FixedFeeModel(Money.from_str('1.00 USD'),charge_commission_once=True),
            fill_model=FillModel(prob_fill_on_limit=1.,prob_slippage=0.,random_seed=0),
            latency_model=LatencyModel(base_latency_nanos=0,insert_latency_nanos=0,
                                      update_latency_nanos=0,cancel_latency_nanos=0),
            bar_execution=False,trade_execution=False,allow_cash_borrowing=False,use_random_ids=False)
        for symbol in SYMBOLS:
            engine.add_instrument(Equity(ids[symbol],Symbol(symbol),USD,4,Price.from_str('0.0001'),
                                         Quantity.from_int(1),0,0))
        adapter=Adapter();engine.add_strategy(adapter)
        quotes=[];marks=[]
        for row in observations:
            symbol=row['source_symbol'];timestamp=int(row['quote_event_ns'])
            price=Price.from_str(row['price']+'00')
            require(Fraction(price.as_decimal())==Fraction(cents(row['price']),100),'NATIVE_REPRESENTATION')
            if row['kind']=='OPEN':
                quotes.append(QuoteTick(ids[symbol],price,price,Quantity.from_int(1000000),
                                         Quantity.from_int(1000000),timestamp,timestamp))
            else:
                marks.append(MarkPriceUpdate(ids[symbol],price,timestamp,timestamp))
        engine.add_data(quotes);engine.add_data(marks)
        # Force venue settlement and capture of fill-created +1ns balance alerts
        # before a later route/terminal can already be popped from the timer queue.
        # These are price-free control data, not extra economic observations.
        control_times=sorted({ns(I),end,*settlement_boundaries()})
        engine.add_data([CustomData(DataType(Boundary),Boundary(timestamp)) for timestamp in control_times],
                        client_id=ClientId('CAP-CONTROL'))
        engine.run()
        require(adapter.failed is None and len(adapter.samples)==7 and len(adapter.allocations)==2
                and not adapter.pending and adapter.awaiting_balance is None,'NATIVE_ACCOUNT_FAILURE')
        for event in adapter.events:validate(event,'event')
        return {'account_id':account,'allocations':adapter.allocations,'events':adapter.events,
                'samples':adapter.samples,'native_id_map':{
                    'orders':adapter.native_ids,'fills':adapter.fill_ids,'fees':adapter.fee_ids}}
    finally:
        try:
            if engine is not None:engine.dispose()
        finally:
            raw_callback({'callback':'native_interval','account_id':account,
                          'elapsed_ns':time.monotonic_ns()-started})
