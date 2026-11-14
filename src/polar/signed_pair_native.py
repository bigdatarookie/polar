"""Fixed two-name native host; source/policy remains in the paired producer.

Native orders/callbacks/positions and the accepted exact account are reused.
The event factory is invoked at its actual host clock, after all prior callbacks.
"""
from decimal import Decimal
from fractions import Fraction as F
import uuid
from .signed_account_core import State,amount_cents
from .signed_event_driver import PairEvent,RoutingBoundary,SignedEventDriver
from .signed_event_saved import verify_packet
from .signed_native_bridge import SignedNativeBridge,native_types,require
from .signed_execution_terms import OrderFees


def run_pair_timeline(context,times,event_factory,*,capital_cents=10000000,on_completed=None,invented_partial_order=False):
    require(type(invented_partial_order) is bool and (not invented_partial_order or context.account.startswith('INVENTED')),'PAIR_PARTIAL_CONTROL_INVENTED_ONLY')
    require(type(times) is tuple and times and all(type(t) is int and t>=0 for t in times) and
            all(a+10000<b for a,b in zip(times,times[1:])),'PAIR_NATIVE_TIMELINE')
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FeeModel,FillModel
    from nautilus_trader.config import BacktestEngineConfig,LoggingConfig,StrategyConfig,RiskEngineConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.identifiers import Venue,InstrumentId,Symbol,ClientId,ClientOrderId
    from nautilus_trader.model.data import QuoteTick,CustomData,DataType
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.objects import Price,Quantity
    from nautilus_trader.model.enums import AccountType,OmsType,OrderSide,TimeInForce,PositionSide
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.accounting.factory import AccountFactory
    types=native_types();venue=Venue('FIXEDPAIR'+uuid.uuid4().hex.upper());ids={n:InstrumentId(Symbol(n),venue) for n in context.names}
    class Boundary(Data):
        def __init__(self,t):self.t=t
        @property
        def ts_event(self):return self.t
        @property
        def ts_init(self):return self.t
    def px(value):
        amount=value*10**8;require(amount.denominator==1,'PAIR_NATIVE_EXECUTION_PRECISION')
        return Price.from_str(f'{amount.numerator//10**8}.{amount.numerator%10**8:08d}')
    class ExecutionEquity(types['equity_type']):
        def notional_value(self,quantity,price,use_quote_for_inverse=False,target_currency=None,conversion_price=None):
            require(not self.is_inverse and conversion_price is None and target_currency in (None,USD) and
                    self.quote_currency==USD,'PAIR_NATIVE_NOTIONAL_PROFILE')
            q=F(quantity.as_decimal());p=F(price.as_decimal())
            require(q.denominator==1 and q>=0 and (p*10**8).denominator==1 and p>0,'PAIR_NATIVE_NOTIONAL_PRECISION')
            return types['money_from_cents'](amount_cents(q.numerator,p))
    class Thin(FillModel):
        def get_orderbook_for_fill_simulation(self,instrument,order,best_bid,best_ask):
            from nautilus_trader.model.book import OrderBook
            from nautilus_trader.model.data import BookOrder
            from nautilus_trader.model.enums import BookType
            book=OrderBook(instrument_id=instrument.id,book_type=BookType.L2_MBP)
            book.add(BookOrder(OrderSide.BUY,best_bid,Quantity.from_int(1),1),0,0)
            book.add(BookOrder(OrderSide.SELL,best_ask,Quantity.from_int(1),2),0,0)
            return book
    class Fee(FeeModel):
        def __init__(self):super().__init__();self.books={}
        def get_commission(self,order,fill_qty,fill_px,instrument):
            e=strategy.driver.event
            tracker=self.books.setdefault(e.id,OrderFees(e.flat_fee_cents,e.fee_bps))
            amount=tracker.fill(str(order.client_order_id),int(F(fill_qty.as_decimal())),F(fill_px.as_decimal()))
            return types['money_from_cents'](amount['total_cents'])
    engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),run_analysis=False,
        risk_engine=RiskEngineConfig(bypass=False,max_order_submit_rate='100/00:00:01')))
    class Host(Strategy):
        def __init__(self):
            super().__init__(StrategyConfig(strategy_id='FIXED_PAIR',order_id_tag='001',log_events=False,log_commands=False))
            self.driver=None;self.current=None;self.observations=[]
        def positions(self):
            q={n:0 for n in context.names}
            for p in self.cache.positions_open():
                q[p.instrument_id.symbol.value]+=int(F(p.quantity.as_decimal()))*(-1 if p.side==PositionSide.SHORT else 1)
            return q
        def on_start(self):
            bridge=SignedNativeBridge(State(capital_cents),ids,self.submit_order,self.positions,
                lambda:engine.portfolio.account(venue),initial_cents=capital_cents,continue_economic_events=True)
            self.driver=SignedEventDriver(context,bridge)
            for index,t in enumerate(times):
                self.clock.set_time_alert_ns('begin-'+str(index),t+100,lambda _,i=index:self.begin(i))
                for k in range(1,25):self.clock.set_time_alert_ns('pump-'+str(index)+'-'+str(k),t+100+k*100,lambda _:self.pump())
            for iid in ids.values():self.subscribe_quote_ticks(iid)
        def begin(self,index):
            # Source-side quote ticks for this slot are installed by the outer
            # streaming loop before time advances to the actual begin callback.
            e=self.current
            require(e.at_ns==times[index] and type(e) is PairEvent,'PAIR_NATIVE_EVENT_SLOT')
            self.driver.begin_event(e,RoutingBoundary(e.id,e.at_ns,e.at_ns+10000))
        def pump(self):
            if self.driver.event is None or self.driver.bridge.pending:return
            command=self.driver.next_order()
            if command is None:
                record=self.driver.history[-1]
                self.observations.append(record)
                if on_completed is not None:on_completed(self.driver,record)
                return
            order=self.order_factory.market(instrument_id=ids[command.name],
                order_side=OrderSide.BUY if command.side=='BUY' else OrderSide.SELL,
                quantity=Quantity.from_int(command.quantity),time_in_force=TimeInForce.IOC if invented_partial_order else TimeInForce.GTC,
                client_order_id=ClientOrderId(command.intent_id))
            self.driver.submit(order,native_ns=self.clock.timestamp_ns())
        def on_order_filled(self,fill):
            self.driver.on_fill(fill,received_ns=self.clock.timestamp_ns())
            p=self.driver.bridge.pending
            if p['filled']==p['quantity']:self.driver.on_terminal(str(fill.client_order_id),'FILLED')
        def on_order_canceled(self,e):self.driver.on_terminal(str(e.client_order_id),'CANCELLED')
        def on_order_expired(self,e):self.driver.on_terminal(str(e.client_order_id),'EXPIRED')
        def on_order_rejected(self,e):self.driver.on_terminal(str(e.client_order_id),'REJECTED')
        def on_order_denied(self,e):self.driver.on_terminal(str(e.client_order_id),'DENIED')
    try:
        engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.MARGIN,
            starting_balances=[types['money_from_cents'](capital_cents)],base_currency=USD,default_leverage=Decimal(1),
            fee_model=Fee(),fill_model=Thin() if invented_partial_order else FillModel(prob_slippage=0.),bar_execution=False,trade_execution=False,
            allow_cash_borrowing=False,use_random_ids=False)
        AccountFactory.register_account_type(venue.value,types['account_type'])
        for n,iid in ids.items():engine.add_instrument(ExecutionEquity(iid,Symbol(n),USD,8,Price.from_str('0.00000001'),Quantity.from_int(1),0,0))
        strategy=Host();engine.add_strategy(strategy)
        # Start with only a clock boundary. Future source quotes are not in the
        # native cache when a causal D factory captures its actual account.
        engine.add_data([CustomData(DataType(Boundary),Boundary(times[0]-1))],client_id=ClientId('PAIR'))
        engine.run(end=times[0]-1,streaming=True)
        for index,t in enumerate(times):
            e=event_factory(index,strategy.driver)
            require(type(e) is PairEvent and e.at_ns==t,'PAIR_NATIVE_FACTORY_CLOCK')
            strategy.current=e;ticks=[]
            for i,n in enumerate(context.names):
                quote=next((v for v in e.side_quotes if v.name==n),None)
                bid=quote.bid if quote else dict(e.marks)[n];ask=quote.ask if quote else dict(e.marks)[n]
                ticks.append(QuoteTick(ids[n],px(bid),px(ask),Quantity.from_int(1000000000),Quantity.from_int(1000000000),t+i,t+i))
            engine.add_data(ticks)
            engine.add_data([CustomData(DataType(Boundary),Boundary(t+10000))],client_id=ClientId('PAIR'))
            engine.run(end=t+10000,streaming=True)
            require(strategy.driver.event is None and not strategy.driver.bridge.pending,'PAIR_NATIVE_UNFINISHED_SLOT')
        engine.end();packet=strategy.driver.packet();verified=verify_packet(packet,context)
        return {'packet':packet,'verification':verified,'completed':strategy.observations}
    except Exception as exc:
        if 'strategy' in locals() and strategy.driver is not None:
            exc.pair_partial=strategy.driver.failure_evidence(exc)
            exc.pair_native_entry={'native_account_id':str(strategy.driver.bridge._account().id),'actual_entry_observed':True}
        raise
    finally:engine.dispose()
