"""Narrow Nautilus1.231.0 Cython adapter. No generic strategy imports."""
from decimal import Decimal
from fractions import Fraction
from .gym_contract import (GymError, SYMBOLS, STRATEGIES, exact_string, fraction)
from .gym_strategy import intents


def simulate(converted):
    import importlib.metadata
    if importlib.metadata.version('nautilus_trader')!='1.231.0': raise GymError('ENGINE_VERSION_MISMATCH')
    # Import lazily: non-native preflight/evaluation remain usable without the native stack.
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FixedFeeModel,FillModel,LatencyModel
    from nautilus_trader.config import BacktestEngineConfig,LoggingConfig,PortfolioConfig,StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.identifiers import InstrumentId,Symbol,Venue,ClientId
    from nautilus_trader.model.instruments import Equity
    from nautilus_trader.model.objects import Price,Quantity,Money
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import QuoteTick,MarkPriceUpdate,CustomData,DataType,Bar
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.enums import AccountType,OmsType,OrderSide,TimeInForce

    class Boundary(Data):
        """Control-only final boundary; contains no market price or source bar."""
        def __init__(self, ns): self.ns=ns
        @property
        def ts_event(self): return self.ns
        @property
        def ts_init(self): return self.ns

    venue=Venue('XGYM');ids={s:InstrumentId.from_str(s+'.XGYM') for s in SYMBOLS}
    output=[]
    for strategy_id in STRATEGIES:
        # New engine AND all new fee/fill/latency/account state for every physical run.
        engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),
                  portfolio=PortfolioConfig(use_mark_prices=True,bar_updates=False),run_analysis=False))
        class Adapter(Strategy):
            def __init__(self):
                super().__init__(StrategyConfig(strategy_id=strategy_id,order_id_tag='001',log_events=False,log_commands=False))
                self.held={s:0 for s in SYMBOLS};self.marks={};self.opens={};self.pending=[]
                self.observations=[];self.intent_rows=[];self.orders=[];self.fills=[];self.nav=[]
                self.outstanding={};self.failed=None
            def cash(self): return Fraction(engine.portfolio.account(venue).balances_total()[USD].as_decimal())
            def alert(self,name,ns,callback):
                self.clock.set_time_alert_ns(name,ns,callback)
            def on_start(self):
                for iid in ids.values(): self.subscribe_quote_ticks(iid)
                for i,grid in enumerate(converted['nav_grid']):
                    self.alert('nav-'+str(i),grid['sample_ns'],lambda e,g=grid:self.sample(e,g))
                groups={}
                for event in converted['events']:
                    if event['kind']=='ELIGIBLE_BAR':groups.setdefault((event['date'],event['known_by_ns']),[]).append(event)
                for i,((day,k),bars) in enumerate(sorted(groups.items())):
                    self.alert('obs-'+str(i),k,lambda e,b=bars:self.observe(e,b))
                for i,decision in enumerate(converted['decisions']):
                    self.alert('decision-'+str(i),decision['decision_ns'],lambda e,d=decision:self.decide(e,d))
                    for j,s in enumerate(SYMBOLS):
                        self.alert(f'sell-{i}-{j}',decision['open_ns']+100+j,lambda e,s=s,d=decision:self.route(e,s,'SELL',d))
                        self.alert(f'buy-{i}-{j}',decision['open_ns']+200+j,lambda e,s=s,d=decision:self.route(e,s,'BUY',d))
            def on_quote_tick(self,tick):
                symbol=tick.instrument_id.symbol.value
                self.opens[symbol]=(tick.ts_event,Fraction(tick.ask_price.as_decimal()))
            def observe(self,event,bars):
                if len(bars)!=3: raise GymError('OBSERVATION_GRID')
                day=bars[0]['date'];n=next(r for r in self.nav if r['date']==day)
                self.observations.append({'date':day,'known_by_ns':event.ts_event,'nav':n['nav'],
                    'closes':{b['symbol']:b['ohlcv']['c'] for b in bars},
                    'bars':[{k:b[k] for k in ('symbol','date','ts_event','ts_init','known_by_ns','ohlcv')} for b in bars]})
            def decide(self,event,decision):
                if strategy_id==STRATEGIES[0] and decision['order_date']==converted['nav_grid'][-2]['date']: self.pending=[];return
                observation=next(o for o in self.observations if o['date']==decision['observation_date'])
                if observation['known_by_ns']>=event.ts_event: raise GymError('FUTURE_OBSERVATION')
                self.pending=intents(strategy_id,observation,self.held,event.ts_event,decision['order_date'],decision['terminal'])
                self.intent_rows.extend(self.pending)
            def route(self,event,symbol,side,decision):
                if self.outstanding: raise GymError('UNACKNOWLEDGED_PREVIOUS_ORDER')
                intent=next((r for r in self.pending if r['symbol']==symbol and r['order_date']==decision['order_date']),None)
                if intent is None: return
                intended=intent['sell_quantity' if side=='SELL' else 'buy_quantity']
                if intended==0: return
                if set(self.opens)!=set(SYMBOLS) or any(t!=decision['open_ns']+i for i,s in enumerate(SYMBOLS) for t in [self.opens[s][0]]):
                    raise GymError('OPEN_PHASE_INCOMPLETE')
                price=self.opens[symbol][1];before=self.cash()
                qty=min(intended,self.held[symbol]) if side=='SELL' else min(intended,max(0,int((before-1)//price)))
                logical=f'{strategy_id}/{decision["order_date"]}/{side}/{symbol}'
                row={'order_id':logical,'symbol':symbol,'side':side,'route_ns':event.ts_event,
                     'intended_quantity':intended,'routed_quantity':qty,'unrouted_quantity':intended-qty,
                     'reason':'NOT_ROUTED_CASH_CAP' if qty<intended else None,'cash_before':exact_string(before)}
                self.orders.append(row)
                if qty==0:return
                if qty>1000000: raise GymError('QUOTE_SIZE_EXCEEDED')
                order=self.order_factory.market(instrument_id=ids[symbol],order_side=OrderSide.SELL if side=='SELL' else OrderSide.BUY,
                       quantity=Quantity.from_int(qty),time_in_force=TimeInForce.GTC)
                self.outstanding[str(order.client_order_id)]=(row,price,before)
                self.submit_order(order)
            def on_order_filled(self,event):
                key=str(event.client_order_id)
                if key not in self.outstanding: raise GymError('UNEXPECTED_FILL')
                order,price,before=self.outstanding.pop(key);qty=int(event.last_qty.as_decimal())
                fee=Fraction(event.commission.as_decimal());actual=Fraction(event.last_px.as_decimal())
                if qty!=order['routed_quantity'] or fee!=1 or actual!=price or event.ts_event!=order['route_ns']:
                    raise GymError('NATIVE_FILL_PROFILE_MISMATCH')
                signed=qty if order['side']=='BUY' else -qty
                self.held[order['symbol']]+=signed
                expected=before-signed*price-fee
                # Account callbacks can be queued after this handler; verify actual cash before next route/NAV.
                self.fills.append({'order_id':order['order_id'],'symbol':order['symbol'],'side':order['side'],
                                   'ts_event':event.ts_event,'ts_init':event.ts_init,'quantity':qty,
                                   'price':exact_string(actual),'fee':exact_string(fee),'cash_after':exact_string(expected)})
            def sample(self,event,grid):
                if self.outstanding: raise GymError('PENDING_FILL_AT_NAV')
                for r in converted['events']:
                    if r['kind']=='MODELED_CLOSE_MARK' and r['date']==grid['date']:self.marks[r['symbol']]=r['price']
                cash=self.cash();exposure=sum((self.held[s]*fraction(self.marks[s]) for s in SYMBOLS if self.held[s]),Fraction())
                native_positions={s:0 for s in SYMBOLS}
                for position in self.cache.positions_open():
                    native_positions[position.instrument_id.symbol.value]+=int(position.quantity.as_decimal())
                if native_positions!=self.held: raise GymError('NATIVE_POSITION_MISMATCH')
                native=engine.portfolio.net_exposures(venue).get(USD)
                native_exposure=Fraction(native.as_decimal()) if native is not None else Fraction()
                # Native Money rounds USD exposure to cents; exact supplied close prices and whole lots here are cents.
                if native_exposure!=exposure or cash<0: raise GymError('NATIVE_ACCOUNTING_MISMATCH')
                if grid['cash_only'] and any(self.held.values()):raise GymError('TERMINAL_POSITION_NOT_ZERO')
                if self.fills and cash!=fraction(self.fills[-1]['cash_after']):raise GymError('NATIVE_CASH_MISMATCH')
                self.nav.append({'date':grid['date'],'nominal_ns':grid['nominal_ns'],'sample_ns':event.ts_event,
                                 'cash':exact_string(cash),'positions':dict(self.held),
                                 'marks':{s:(None if grid['cash_only'] else self.marks.get(s)) for s in SYMBOLS},
                                 'nav':exact_string(cash+exposure),'native_exposure':exact_string(native_exposure)})
            def on_order_rejected(self,event): raise GymError('NATIVE_ORDER_REJECTED')
            def on_order_denied(self,event): raise GymError('NATIVE_ORDER_DENIED')
        try:
            engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.CASH,
                starting_balances=[Money.from_str('100000.00 USD')],base_currency=USD,
                fee_model=FixedFeeModel(Money.from_str('1.00 USD'),charge_commission_once=True),
                fill_model=FillModel(prob_fill_on_limit=1.,prob_slippage=0.,random_seed=0),
                latency_model=LatencyModel(base_latency_nanos=0,insert_latency_nanos=0,update_latency_nanos=0,cancel_latency_nanos=0),
                bar_execution=False,trade_execution=False,allow_cash_borrowing=False,use_random_ids=False)
            for s in SYMBOLS:
                engine.add_instrument(Equity(ids[s],Symbol(s),USD,4,Price.from_str('0.0001'),Quantity.from_int(1),0,0))
            adapter=Adapter();engine.add_strategy(adapter)
            quotes=[];marks=[]
            for row in converted['events']:
                ns=row['ts_init'];iid=ids[row['symbol']]
                if row['kind']=='MODELED_OPEN':
                    p=Price.from_str(format(Decimal(row['price']),'.4f'))
                    if Fraction(p.as_decimal())!=fraction(row['price']):raise GymError('NATIVE_PRICE_PRECISION_LOSS')
                    quotes.append(QuoteTick(iid,p,p,Quantity.from_int(1000000),Quantity.from_int(1000000),ns,ns))
                elif row['kind']=='ELIGIBLE_BAR':
                    fields={'type':'Bar','bar_type':str(iid)+'-1-DAY-LAST-EXTERNAL',
                            'open':format(Decimal(row['ohlcv']['o']),'.4f'),
                            'high':format(Decimal(row['ohlcv']['h']),'.4f'),
                            'low':format(Decimal(row['ohlcv']['l']),'.4f'),
                            'close':format(Decimal(row['ohlcv']['c']),'.4f'),
                            'volume':row['ohlcv']['v'],'ts_event':row['ts_event'],'ts_init':row['ts_init']}
                    # Verify precise native representation, but NEVER add full bars to matching engine.
                    native_bar=Bar.from_dict(fields);back=Bar.to_dict(native_bar)
                    if any(fraction(back[k])!=fraction(row['ohlcv'][v]) for k,v in
                           (('open','o'),('high','h'),('low','l'),('close','c'),('volume','v'))) or back['ts_event']!=row['ts_event'] or back['ts_init']!=row['ts_init']:
                        raise GymError('NATIVE_BAR_ROUND_TRIP')
                elif row['kind']=='MODELED_CLOSE_MARK':
                    p=Price.from_str(format(Decimal(row['price']),'.4f'))
                    marks.append(MarkPriceUpdate(iid,p,ns,ns))
            engine.add_data(quotes);engine.add_data(marks)
            end=converted['nav_grid'][-1]['sample_ns']
            engine.add_data([CustomData(DataType(Boundary),Boundary(end))],client_id=ClientId('GYM-CONTROL'))
            engine.run()
            if len(adapter.nav)!=7 or len(adapter.observations)!=6 or adapter.outstanding: raise GymError('INCOMPLETE_NATIVE_RUN')
            output.append({'strategy_id':strategy_id,'observations':adapter.observations,'intents':adapter.intent_rows,
                           'orders':adapter.orders,'fills':adapter.fills,'nav':adapter.nav})
        finally: engine.dispose()
    return {'schema':'polar.gym-simulation/1','engine':'nautilus_trader/1.231.0',
            'strategies':output,'limitations':['TRUSTED_PYTHON_NOT_SECURITY_SANDBOX','MODELED_CLOCKS_QUOTES_ACTIONS_SETTLEMENT']}
