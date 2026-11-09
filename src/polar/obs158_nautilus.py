"""Fixed OBS158 Nautilus adapter; private valuation never feeds decision sizing.

This module does not execute on import. Full-run qualification is separate from
the previously qualified single-instrument cent-account control.
"""
from fractions import Fraction
import uuid

from .obs158_data import PUBLIC_SHA, METRIC_SHA
from .obs158_math import require, microprice, marked_account, settled_fill, snapshot_targets
from .obs158_native_money import native_types, mark_native_position

STRATEGIES=('OBS158_EW_BH_V1','OBS158_EW_MONTHLY_V1')


def price_text(micro):
    require(type(micro) is int and micro>0,'NATIVE_PRICE_DOMAIN')
    return f'{micro//1000000}.{micro%1000000:06d}'


def grouped(rows,aliases):
    result={}
    for row in rows:
        day=result.setdefault(row['date'],{})
        require(row['alias'] in aliases and row['alias'] not in day,'CHANNEL_ALIAS_JOIN')
        day[row['alias']]=row
    require(all(set(day)==set(aliases) for day in result.values()),'INCOMPLETE_CHANNEL')
    return result


def simulate_obs158(converted,aliases):
    """One fixed pair, two fresh engines; no data loading, fitting or alternative strategy."""
    require(len(aliases)==158 and list(aliases)==sorted(set(aliases))
            and converted['schema']=='polar.obs158-converted/1'
            and converted['public_sha256']==PUBLIC_SHA and converted['metric_sha256']==METRIC_SHA,
            'FIXED_NATIVE_PROFILE')
    aliases=tuple(aliases)
    from nautilus_trader.accounting.factory import AccountFactory
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FixedFeeModel,FillModel,LatencyModel
    from nautilus_trader.config import BacktestEngineConfig,LoggingConfig,PortfolioConfig,StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.data import QuoteTick,MarkPriceUpdate,CustomData,DataType,Bar
    from nautilus_trader.model.identifiers import InstrumentId,Symbol,Venue,ClientId
    from nautilus_trader.model.objects import Price,Quantity
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import AccountType,OmsType,OrderSide,TimeInForce
    types=native_types()
    marks=grouped(converted['private_close_marks'],aliases)
    opens=grouped(converted['executor_quotes'],aliases)
    eligible=grouped(converted['eligible_bars'],aliases)
    grid=converted['sample_grid'];end=grid[-1]['sample_ns']
    require(len(grid)==253 and len(marks)==253 and len(eligible)==253,'FIXED_NATIVE_GRID')
    active=[d for d in converted['decisions'] if d['within_funded_window']]
    require(active and len({d['order_date'] for d in active})==len(active),'DUPLICATE_DECISION')
    require(set(opens)=={d['order_date'] for d in active},'OPEN_DECISION_JOIN')
    # Validate complete native OHLCV conversion, but never send full bars to matching.
    for i,alias in enumerate(aliases):
        iid=InstrumentId(Symbol(f'OBS158-{i:03d}'),Venue('OBS158CONVERSION'))
        for day in eligible.values():
            row=day[alias];raw=row['raw_ohlcv']
            fields={'type':'Bar','bar_type':str(iid)+'-1-DAY-LAST-EXTERNAL',
                    **{k:price_text(microprice(raw[v])) for k,v in
                       (('open','o'),('high','h'),('low','l'),('close','c'))},
                    'volume':raw['v'],'ts_event':row['ts_event'],'ts_init':row['ts_init']}
            back=Bar.to_dict(Bar.from_dict(fields))
            require(all(Fraction(back[k])==Fraction(raw[v]) for k,v in
                        (('open','o'),('high','h'),('low','l'),('close','c'),('volume','v')))
                    and back['ts_event']==row['ts_event'] and back['ts_init']==row['ts_init'],
                    'NATIVE_BAR_ROUND_TRIP')

    class Boundary(Data):
        def __init__(self,ns):self.ns=ns
        @property
        def ts_event(self):return self.ns
        @property
        def ts_init(self):return self.ns

    results=[];physical=[]
    for strategy_id in STRATEGIES:
        # AccountFactory issuer registrations are process-global and cannot be
        # registered twice. The nonce is physical only and never enters tapes/IDs.
        venue=Venue('OBS158'+uuid.uuid4().hex.upper())
        ids={a:InstrumentId(Symbol(f'OBS158-{i:03d}'),venue) for i,a in enumerate(aliases)}
        reverse={v:k for k,v in ids.items()}
        engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),
                 portfolio=PortfolioConfig(use_mark_prices=True,bar_updates=False),run_analysis=False))

        class Adapter(Strategy):
            def __init__(self):
                super().__init__(StrategyConfig(strategy_id=strategy_id,order_id_tag='001',
                                                log_events=False,log_commands=False))
                self.held={a:0 for a in aliases};self.factor={a:1 for a in aliases}
                self.expected_cash=10000000;self.outstanding={};self.pending={}
                self.samples=[];self.byday={};self.observations=[];self.observed={}
                self.intents=[];self.orders=[];self.fills=[];self.phases=[];self.actions=[]
                self.decisions=[];self.expiries=[];self.mark_day=None;self.quote_day=None
            def cash(self):
                value=Fraction(engine.portfolio.account(venue).balances_total()[USD].as_decimal())*100
                require(value.denominator==1 and value>=0,'NATIVE_CASH_DOMAIN')
                return value.numerator
            def reconcile(self,ns):
                require(not self.outstanding,'UNACKNOWLEDGED_PREVIOUS_ORDER')
                actual=self.cash();require(actual==self.expected_cash,'NATIVE_CASH_MISMATCH')
                if self.fills and self.fills[-1]['native_cash_after_cents'] is None:
                    fill=self.fills[-1]
                    require(ns>fill['ts_event'],'CASH_RECONCILIATION_PHASE')
                    fill['native_cash_after_cents']=str(actual);fill['cash_reconciled_at_ns']=ns
                return actual
            def native_quantities(self):
                quantities={a:0 for a in aliases}
                for position in self.cache.positions_open():
                    require(position.instrument_id in reverse,'UNEXPECTED_NATIVE_INSTRUMENT')
                    alias=reverse[position.instrument_id];value=Fraction(position.quantity.as_decimal())
                    require(value.denominator==1 and value>0 and quantities[alias]==0,
                            'NATIVE_POSITION_DOMAIN')
                    quantities[alias]=value.numerator
                require(all(quantities[a]*self.factor[a]==self.held[a] for a in aliases),
                        'NATIVE_PHYSICAL_POSITION_MISMATCH')
                return quantities
            def on_start(self):
                require(isinstance(engine.portfolio.account(venue),types['account_type']),
                        'NATIVE_ACCOUNT_TYPE')
                for iid in ids.values():self.subscribe_quote_ticks(iid)
                def alert(name,ns,fn):self.clock.set_time_alert_ns(name,ns,fn)
                for i,b in enumerate(converted['barriers']):
                    if b['ts_init']>end:continue
                    if b['channel']=='MARKS_COMPLETE':fn=lambda e,b=b:self.mark_barrier(e,b)
                    elif b['channel']=='QUOTES_COMPLETE':fn=lambda e,b=b:self.quote_barrier(e,b)
                    elif b['channel']=='ELIGIBLE_COMPLETE':fn=lambda e,b=b:self.observe(e,b)
                    else:raise ValueError('UNKNOWN_CHANNEL_BARRIER')
                    alert(f'phase-{i}',b['ts_init'],fn)
                for i,g in enumerate(grid):
                    alert(f'sample-{i}',g['sample_ns'],lambda e,g=g:self.sample(e,g))
                for i,u in enumerate(converted['unit_events']):
                    require(all(d['open_ns']<u['ts_init'] for d in active),
                            'POST_SPLIT_TRADE_NOT_SUPPORTED')
                    alert(f'unit-{i}',u['ts_init'],lambda e,u=u:self.apply_unit(e,u))
                for i,d in enumerate(active):
                    alert(f'decision-{i}',d['decision_ns'],lambda e,d=d:self.decide(e,d))
                    for j,a in enumerate(aliases):
                        for side,offset in (('SELL',100),('BUY',1000)):
                            alert(f'{i}-{side}-{j}',d['open_ns']+offset+j,
                                  lambda e,d=d,a=a,side=side:self.route(e,d,a,side))
                    alert(f'expire-{i}',d['open_ns']+2000,lambda e,d=d:self.expire(e,d))
            def mark_barrier(self,event,b):
                require(event.ts_event==b['ts_init'],'MARK_BARRIER_CLOCK')
                rows=marks[b['date']]
                for a in aliases:
                    update=self.cache.mark_price(ids[a]);r=rows[a]
                    require(update is not None and update.ts_event==r['ts_event']
                            and update.ts_init==r['ts_init']
                            and Fraction(update.value.as_decimal())*1000000
                                ==int(r['price_micro'])*self.factor[a],
                            'ALL_NATIVE_CLOSE_MARKS_REQUIRED')
                self.mark_day=b['date'];self.phases.append(dict(b,observed_ns=event.ts_event,
                                                               observed_aliases=158))
            def quote_barrier(self,event,b):
                require(event.ts_event==b['ts_init'],'QUOTE_BARRIER_CLOCK')
                for a,r in opens[b['date']].items():
                    tick=self.cache.quote_tick(ids[a])
                    require(tick is not None and tick.ts_event==r['ts_event']
                            and tick.ts_init==r['ts_init']
                            and Fraction(tick.bid_price.as_decimal())*1000000==int(r['price_micro'])
                            and Fraction(tick.ask_price.as_decimal())*1000000==int(r['price_micro']),
                            'ALL_NATIVE_OPEN_QUOTES_REQUIRED')
                self.quote_day=b['date'];self.phases.append(dict(b,observed_ns=event.ts_event,
                                                                observed_aliases=158))
            def sample(self,event,g):
                cash=self.reconcile(event.ts_event);native=self.native_quantities()
                require(self.mark_day==g['date'] and event.ts_event==g['sample_ns'],
                        'CLOSE_MARK_SAMPLE_BARRIER')
                raw={a:marks[g['date']][a]['raw_close'] for a in aliases}
                account=marked_account(cash,self.held,{a:microprice(raw[a]) for a in aliases},aliases)
                bridges=[]
                for i,a in enumerate(aliases):
                    bridge=mark_native_position(Quantity.from_int(native[a]),raw[a],self.factor[a])
                    expected=account['positions'][i]
                    require(bridge['position_cents']==expected['position_cents'],
                            'NATIVE_CENT_POSITION_BRIDGE')
                    bridges.append({'alias':a,**{k:v for k,v in bridge.items() if k!='native_money'}})
                require(not g['cash_only'] or not any(self.held.values()),'CASH_ONLY_WARMUP')
                row={**g,'cash_cents':str(cash),'positions':{a:str(self.held[a]) for a in aliases},
                     'marks':raw,'price_ledger_value_cents':account['price_ledger_value_cents'],
                     'position_ledger':account['positions'],'native_unit_bridges':bridges}
                self.samples.append(row);self.byday[g['date']]=row
            def observe(self,event,b):
                day=b['date'];rows=eligible[day]
                require(day in self.byday and day not in self.observed
                        and all(r['known_by_ns']+1==event.ts_event for r in rows.values()),
                        'DELAYED_OBSERVATION_BARRIER')
                snapshot={'date':day,'known_by_ns':next(iter(rows.values()))['known_by_ns'],
                          'delivered_ns':event.ts_event,
                          'price_ledger_value_cents':self.byday[day]['price_ledger_value_cents'],
                          'raw_closes':{a:rows[a]['raw_ohlcv']['c'] for a in aliases},
                          'bars':[rows[a] for a in aliases]}
                self.observed[day]=snapshot;self.observations.append(snapshot)
                self.phases.append(dict(b,observed_ns=event.ts_event,observed_aliases=158))
            def decide(self,event,d):
                self.reconcile(event.ts_event);self.native_quantities()
                if strategy_id==STRATEGIES[0] and d['order_date']!=active[0]['order_date']:
                    self.decisions.append({**d,'status':'SKIPPED_BUY_HOLD'});return
                observation=self.observed.get(d['snapshot_date'])
                require(observation is not None and observation['known_by_ns']<event.ts_event
                        and observation['delivered_ns']<event.ts_event==d['decision_ns'],
                        'FUTURE_OR_MISSING_STRATEGY_INFORMATION')
                targets=snapshot_targets(int(observation['price_ledger_value_cents']),
                         {a:microprice(observation['raw_closes'][a]) for a in aliases},aliases)
                pending={}
                for a in aliases:
                    row={'strategy_id':strategy_id,'alias':a,'snapshot_date':d['snapshot_date'],
                         'known_by_ns':observation['known_by_ns'],'decision_ns':event.ts_event,
                         'order_date':d['order_date'],'open_ns':d['open_ns'],
                         'snapshot_value_cents':observation['price_ledger_value_cents'],
                         'target_quantity':str(targets[a]),'held_at_decision':str(self.held[a]),
                         'sell_intended':str(max(0,self.held[a]-targets[a])),
                         'buy_intended':str(max(0,targets[a]-self.held[a]))}
                    self.intents.append(row);pending[a]=row
                self.pending[d['order_date']]=pending
                self.decisions.append({**d,'status':'INTENTS_FROZEN'})
            def route(self,event,d,a,side):
                cash=self.reconcile(event.ts_event);self.native_quantities()
                require(event.ts_event==d['open_ns']+(100 if side=='SELL' else 1000)+aliases.index(a),
                        'ROUTE_SLOT_CLOCK')
                pending=self.pending.get(d['order_date'])
                if pending is None:return
                require(self.quote_day==d['order_date'] and self.factor[a]==1,'OPEN_ROUTING_BARRIER')
                intent=pending[a];intended=int(intent['sell_intended' if side=='SELL' else 'buy_intended'])
                quote=opens[d['order_date']][a]
                plan=settled_fill(side,intended,self.held[a],cash,int(quote['price_micro']))
                logical=f'{strategy_id}/{d["order_date"]}/{side}/{aliases.index(a):03d}'
                row={'order_id':logical,'alias':a,'route_ns':event.ts_event,
                     'raw_open':quote['raw_open'],'cash_before_cents':str(cash),**plan}
                self.orders.append(row);qty=int(plan['filled_quantity'])
                if qty==0:return
                order=self.order_factory.market(instrument_id=ids[a],
                      order_side=OrderSide.BUY if side=='BUY' else OrderSide.SELL,
                      quantity=Quantity.from_int(qty),time_in_force=TimeInForce.GTC)
                self.outstanding[str(order.client_order_id)]=row
                self.submit_order(order)
            def on_order_filled(self,event):
                key=str(event.client_order_id);require(key in self.outstanding,'UNEXPECTED_NATIVE_FILL')
                order=self.outstanding.pop(key);a=order['alias'];qty=int(order['filled_quantity'])
                require(Fraction(event.last_qty.as_decimal())==qty
                        and Fraction(event.last_px.as_decimal())*1000000==microprice(order['raw_open'])
                        and Fraction(event.commission.as_decimal())==1
                        and event.ts_event==event.ts_init==order['route_ns'],
                        'NATIVE_FILL_PROFILE_MISMATCH')
                self.held[a]+=qty if order['side']=='BUY' else -qty
                self.expected_cash=int(order['cash_after_cents'])
                fill=dict(order,ts_event=event.ts_event,ts_init=event.ts_init,
                          native_cash_after_cents=None,cash_reconciled_at_ns=None)
                fill['expected_cash_after_cents']=fill.pop('cash_after_cents')
                self.fills.append(fill)
            def expire(self,event,d):
                self.reconcile(event.ts_event);self.native_quantities()
                require(event.ts_event==d['open_ns']+2000,'INTENT_EXPIRY_CLOCK')
                rows=[r for r in self.orders if r['raw_open'] is not None
                      and r['order_id'].split('/')[1]==d['order_date']]
                self.expiries.append({'order_date':d['order_date'],'at_ns':event.ts_event,
                         'unrouted_quantity':str(sum(int(r['unrouted_quantity']) for r in rows)),
                         'status':'EXPIRED_NO_RETRY'})
                self.pending.pop(d['order_date'],None)
            def apply_unit(self,event,u):
                self.reconcile(event.ts_event);native=self.native_quantities();a=u['alias']
                require(event.ts_event==u['ts_init'],'SPLIT_UNIT_CLOCK')
                require(a in self.factor and self.factor[a]==1,'SPLIT_ALREADY_APPLIED')
                factor=int(u['new_per_old'].split('/')[0]);require(factor in (4,5),'SPLIT_FACTOR')
                before=self.held[a];self.factor[a]=factor;self.held[a]=native[a]*factor
                self.actions.append({**u,'applied_ns':event.ts_event,'native_quantity':str(native[a]),
                                     'physical_before':str(before),'physical_after':str(self.held[a]),
                                     'cash_delta_cents':'0'})
            def on_order_rejected(self,event):raise ValueError('NATIVE_ORDER_REJECTED')
            def on_order_denied(self,event):raise ValueError('NATIVE_ORDER_DENIED')

        try:
            engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.CASH,
                starting_balances=[types['money_from_cents'](10000000)],base_currency=USD,
                fee_model=FixedFeeModel(types['money_from_cents'](100),charge_commission_once=True),
                fill_model=FillModel(prob_fill_on_limit=1.,prob_slippage=0.,random_seed=0),
                latency_model=LatencyModel(base_latency_nanos=0,insert_latency_nanos=0,
                                          update_latency_nanos=0,cancel_latency_nanos=0),
                bar_execution=False,trade_execution=False,allow_cash_borrowing=False,use_random_ids=False)
            AccountFactory.register_account_type(venue.value,types['account_type'])
            for a in aliases:
                engine.add_instrument(types['equity_type'](ids[a],ids[a].symbol,USD,6,
                    Price.from_str('0.000001'),Quantity.from_int(1),0,0))
            adapter=Adapter();engine.add_strategy(adapter)
            quotes=[];native_marks=[]
            for day in opens.values():
                for a,r in day.items():
                    p=Price.from_str(price_text(int(r['price_micro'])));ns=r['ts_init']
                    quotes.append(QuoteTick(ids[a],p,p,Quantity.from_int(1000000),
                                            Quantity.from_int(1000000),ns,ns))
            for day in marks.values():
                for a,r in day.items():
                    factors=[int(u['new_per_old'].split('/')[0]) for u in converted['unit_events']
                             if u['alias']==a and u['ts_init']<=r['ts_init']]
                    require(len(factors)<=1,'SPLIT_ALREADY_APPLIED');factor=factors[0] if factors else 1
                    p=Price.from_str(price_text(int(r['price_micro'])*factor));ns=r['ts_init']
                    native_marks.append(MarkPriceUpdate(ids[a],p,ns,ns))
            engine.add_data(quotes);engine.add_data(native_marks)
            engine.add_data([CustomData(DataType(Boundary),Boundary(end))],client_id=ClientId('OBS158-CONTROL'))
            # 1.231 swallows AccountError in non-streaming mode. One streaming
            # batch preserves the original exception; explicit end has the same
            # frozen final data boundary, with no later strategy information.
            engine.run(end=end,streaming=True)
            engine.end()
            require(len(adapter.samples)==253 and not adapter.outstanding and not adapter.pending
                    and len(adapter.actions)==len(converted['unit_events'])
                    and all(f['native_cash_after_cents']==f['expected_cash_after_cents'] for f in adapter.fills),
                    'INCOMPLETE_NATIVE_PACKET')
            expected_phases=[b for b in converted['barriers'] if b['ts_init']<=end]
            actual=[(r['channel'],r['date'],r['ts_init']) for r in adapter.phases]
            expected=[(r['channel'],r['date'],r['ts_init']) for r in expected_phases]
            require(sorted(actual)==sorted(expected),'INCOMPLETE_NATIVE_PHASES')
            results.append({'strategy_id':strategy_id,'samples':adapter.samples,
                'observations':adapter.observations,'decisions':adapter.decisions,
                'outside_instructions':[d for d in converted['decisions'] if not d['within_funded_window']],
                'intents':adapter.intents,'orders':adapter.orders,'fills':adapter.fills,
                'expiries':adapter.expiries,
                'unit_events':sorted(adapter.actions,key=lambda r:(r['applied_ns'],r['alias'])),
                'barriers':adapter.phases})
            physical.append({'strategy_id':strategy_id,'native_venue':venue.value})
        finally:engine.dispose()
    return {'schema':'polar.obs158-simulation/1','engine':'nautilus_trader/1.231.0',
            'strategies':results,'native_bar_round_trips':39974,'matching_full_bars':0,
            'engine_runs':2,'physical':physical,
            'scope':'PRICE_ONLY_PARTIAL_ACTION_EXECUTION_MODEL'}
