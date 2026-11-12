"""Raw-share cash reinvestment adapter inside the existing native runner.

One real Nautilus engine/account per leg, same exact-cent money/fees and bounded
worker. Receivables never enter spendable cash before internal settlement.
"""
from dataclasses import asdict
from fractions import Fraction
import json
import uuid

from .ci_research import require, INITIAL_CENTS, fee_cents, maximum_buy
from .distribution_claims import Action, State, Phase, transition, record, restore, Evidence, verify, valuation
from .gym_contract import canonical, sha
from .obs158_math import cent_round_micro
from .raw_action_input import instant
from .raw_claim_native import settlement_module
from .research_native_money import native_types

LEGS = ('PAYMENT_CASH_REINVEST','RETAIN_CASH','ANNUAL_CASH_REINVEST','CASH')


def compact_state(value):
    value = json.loads(canonical(value))
    return {**value, 'claims':[{**c, 'action':c['action']['event_id']} for c in value['claims']]}


def expand_state(value, actions):
    return {**value, 'claims':[{**c, 'action':actions[c['action']]} for c in value['claims']]}


def compact_evidence(e):
    e = asdict(e) if type(e) is Evidence else e
    return {'operation':e['operation'], 'before':compact_state(json.loads(e['before_json'])),
            'inputs':json.loads(e['inputs_json']), 'after':compact_state(json.loads(e['after_json']))}


def replay_event(e, actions):
    before = expand_state(e['before'], actions); after = expand_state(e['after'], actions)
    # Pure transition verification only; no policy/engine/source reconstruction.
    evidence = Evidence(e['operation'], canonical(before).decode().rstrip('\n'),
        canonical(e['inputs']).decode().rstrip('\n'), canonical(after).decode().rstrip('\n'))
    verify(evidence)
    return evidence


def terminal_check(state, expected_events):
    marks = {s:0 for s,q in state.holdings}
    result = valuation(state, marks, terminal=True)
    due = [c for c in state.claims if c.action.availability_date <= state.session_date]
    complete = len(state.claims) == expected_events and all(c.paid_at is not None for c in due)
    require(complete, 'RAW_DUE_LIFECYCLE_INCOMPLETE')
    require(not any(q for s,q in state.holdings) and result['receivable_cents'] == 0,
            'RAW_TERMINAL_NONZERO_ASSET')
    return {**result, 'due_event_lifecycle_complete':complete,
        'remaining_raw_quantities':dict(state.holdings), 'unpaid_positive_claim_cents':result['receivable_cents'],
        'pending_claim_record_count':result['outstanding_count'], 'strict_component_flag':result['cash_only_terminal']}


def simulate(plan, diagnostics=None):
    from nautilus_trader.accounting.factory import AccountFactory
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FeeModel, FillModel, LatencyModel
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.data import QuoteTick, CustomData, DataType
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue, ClientId
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide

    require(plan['profile']['kind'] == 'RAW_ACTION_REINVEST', 'RAW_NATIVE_PLAN')
    types = native_types(); cost = plan['cost_profile']; fee_cents(0,1,cost_profile=cost)
    instrument = plan['instrument']; days = plan['dates']; prices = plan['prices']
    actions = [Action(**{**a,'reference_dates':tuple(a['reference_dates'])}) for a in plan['actions']]
    rows = {r['date']:r for r in plan['schedule']}
    class Boundary(Data):
        def __init__(self, ns): self.ns = ns
        @property
        def ts_event(self): return self.ns
        @property
        def ts_init(self): return self.ns
    class Fee(FeeModel):
        def get_commission(self, order, fill_qty, fill_px, instrument):
            q = Fraction(fill_qty.as_decimal()); p = Fraction(fill_px.as_decimal())*1000000
            require(q.denominator == p.denominator == 1, 'RAW_NATIVE_FILL_PRECISION')
            return types['money_from_cents'](fee_cents(q.numerator,p.numerator,cost_profile=cost))
    results = []
    for leg in LEGS:
        venue = Venue('RAWCLAIM'+uuid.uuid4().hex.upper()); iid = InstrumentId(Symbol(instrument),venue)
        engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),run_analysis=False))
        module = settlement_module()
        class Adapter(Strategy):
            def __init__(self):
                super().__init__(StrategyConfig(strategy_id=leg,order_id_tag='001',log_events=False,log_commands=False))
                self.held = 0; self.expected_cash = INITIAL_CENTS; self.pending = None; self.inflight = {}
                self.book = State(days[0],Phase.PRE_SESSION,INITIAL_CENTS,((instrument,0),))
                self.trace = []; self.intents = []; self.orders = []; self.fills = []; self.nav = []
                self.flat = self.bps = 0
            def cash(self):
                v = Fraction(engine.portfolio.account(venue).balance_total(USD).as_decimal())*100
                require(v.denominator == 1 and v >= 0, 'RAW_NATIVE_CASH'); return v.numerator
            def reconcile(self):
                require(not self.inflight and self.cash() == self.expected_cash, 'RAW_NATIVE_CASH_PENDING')
                actual = sum(int(p.quantity.as_decimal()) for p in self.cache.positions_open())
                require(all(Fraction(p.quantity.as_decimal()).denominator == 1 and
                    p.instrument_id == iid and p.is_long for p in self.cache.positions_open()) and
                    actual == self.held, 'RAW_NATIVE_HOLDINGS')
            def pure(self, op, inputs):
                self.book,e = transition(op,self.book,inputs); self.trace.append(compact_evidence(e))
            def on_start(self):
                self.subscribe_quote_ticks(iid)
                for day in days:
                    row=rows[day]; op=instant(row['reference_open_utc']); cl=instant(row['reference_close_utc'])
                    self.clock.set_time_alert_ns('ex-'+day,op-1,lambda e,d=day:self.pre_session(d))
                    self.clock.set_time_alert_ns('pay-'+day,cl+10,lambda e,d=day:self.payments(d))
                    self.clock.set_time_alert_ns('sell-'+day,cl+100,lambda e,d=day:self.route(d,'SELL'))
                    self.clock.set_time_alert_ns('buy-'+day,cl+200,lambda e,d=day:self.route(d,'BUY'))
                    self.clock.set_time_alert_ns('nav-'+day,cl+1000,lambda e,d=day:self.sample(d))
                for event in plan['events']:
                    self.clock.set_time_alert_ns('decision-'+event['formation'],event['decision_ns'],
                        lambda e,d=event:self.decide(d))
            def pre_session(self, day):
                self.reconcile()
                require(self.book.available_cash_cents == self.cash() and dict(self.book.holdings)[instrument] == self.held,
                        'RAW_PRIOR_HOLDER_SNAPSHOT')
                for action in actions:
                    if action.ex_date == day:
                        self.pure('recognize',{'action':asdict(action),'session_date':day,'phase':'PRE_SESSION'})
            def payments(self, day):
                self.reconcile(); mark={instrument:cent_round_micro(self.held*prices[day]['close_micro'])}
                for claim in tuple(self.book.claims):
                    if claim.action.availability_date == day:
                        self.book = module.settle(self.book,claim.action.event_id,day,mark,
                            expected_ns=instant(rows[day]['reference_close_utc'])+10)
                        receipt=module.receipts[-1]
                        receipt['claim_evidence']=compact_evidence(receipt['claim_evidence'])
                        self.trace.append(receipt['claim_evidence'])
                        self.expected_cash=self.book.available_cash_cents
                self.reconcile()
            def decide(self, event):
                self.reconcile(); require(self.book.available_cash_cents == self.expected_cash,'RAW_DECISION_CASH')
                kind = 'EXIT' if event['terminal'] else 'TARGET' if leg != 'CASH' and (
                    event['initial'] or leg == LEGS[0] and event['payment'] or
                    leg == LEGS[2] and event['annual']) else 'HOLD'
                p=prices[event['formation']]['close_micro']
                target=0 if kind == 'EXIT' else self.held+self.expected_cash*10000//p if kind == 'TARGET' else self.held
                require(0 <= target <= 1000000000,'RAW_TARGET_DOMAIN')
                self.pending={'execution_date':event['execution_date'],'target':target,'kind':kind}
                self.intents.append({**event,'kind':kind,'target':target,'decision_cash_cents':self.expected_cash,
                    'decision_holdings':self.held,'eligible_price_micro':p})
            def route(self, day, side):
                self.reconcile()
                if self.pending is None or self.pending['execution_date'] != day:return
                target=self.pending['target']; desired=max(self.held-target,0) if side=='SELL' else max(target-self.held,0)
                if desired == 0:return
                p=prices[day]['close_micro']; q=desired if side=='SELL' else maximum_buy(desired,p,self.expected_cash,cost_profile=cost)
                logical=f'{leg}/{day}/{side}/{instrument}'
                record={'id':logical,'symbol':instrument,'side':side,'at_ns':self.clock.timestamp_ns(),
                    'intended_quantity':desired,'routed_quantity':q,'reason':'FEE_AWARE_CASH_CAP' if q<desired else None}
                self.orders.append(record)
                if q == 0:return
                fee=fee_cents(q,p,cost_profile=cost); settled=cent_round_micro(q*p)
                require(self.expected_cash+(settled-fee if side=='SELL' else -settled-fee)>=0,'RAW_SELL_FEE_SHORTFALL')
                order=self.order_factory.market(iid,OrderSide.SELL if side=='SELL' else OrderSide.BUY,Quantity.from_int(q))
                self.inflight[str(order.client_order_id)]={**record,'q':q,'price_micro':p,'fee_cents':fee,'settled_cents':settled}
                self.submit_order(order)
            def on_order_filled(self,event):
                r=self.inflight.pop(str(event.client_order_id),None)
                require(r is not None and Fraction(event.last_qty.as_decimal()) == r['q'] and
                    Fraction(event.last_px.as_decimal())*1000000 == r['price_micro'] and
                    Fraction(event.commission.as_decimal())*100 == r['fee_cents'] and event.ts_event == r['at_ns'],
                    'RAW_NATIVE_FILL_BINDING')
                sign=1 if r['side']=='BUY' else -1
                self.held+=sign*r['q'];self.expected_cash-=sign*r['settled_cents']+r['fee_cents']
                self.flat+=cost['flat_cents'];self.bps+=r['fee_cents']-cost['flat_cents']
                self.fills.append({**r,'cash_after_cents':self.expected_cash,'exact_notional_micro':r['q']*r['price_micro'],
                    'settlement_epsilon_micro':r['settled_cents']*10000-r['q']*r['price_micro']})
            def sample(self, day):
                self.reconcile()
                if (self.book.available_cash_cents != self.expected_cash or dict(self.book.holdings)[instrument] != self.held or
                    self.book.session_date == day or day == days[-1]):
                    self.pure('settled_snapshot',{'session_date':day,'holdings':[[instrument,self.held]],
                        'available_cash_cents':self.expected_cash})
                mark=cent_round_micro(self.held*prices[day]['close_micro'])
                v=valuation(self.book,{instrument:mark},terminal=day==days[-1]);require(v['nav_cents']>0,'RAW_NONPOSITIVE_NAV')
                if day in (days[0],days[-1]):require(self.held==0,'RAW_BOUNDARY_POSITION')
                self.nav.append({'date':day,'nominal_ns':instant(rows[day]['reference_close_utc']),
                    'sample_ns':self.clock.timestamp_ns(),'cash_cents':self.expected_cash,
                    'exposure_cents':mark,'position_cents':{instrument:mark},'positions':{instrument:self.held},
                    'receivable_cents':v['receivable_cents'],'pending_claim_count':v['outstanding_count'],
                    'nav_cents':v['nav_cents'],'flat_cents':self.flat,'bps_cents':self.bps})
            def on_order_denied(self,event):require(False,'RAW_NATIVE_ORDER_DENIED')
            def on_order_rejected(self,event):require(False,'RAW_NATIVE_ORDER_REJECTED')
            def on_order_canceled(self,event):require(False,'RAW_NATIVE_ORDER_CANCELED')
        adapter=None
        try:
            engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.CASH,
                starting_balances=[types['money_from_cents'](INITIAL_CENTS)],base_currency=USD,
                fee_model=Fee(),fill_model=FillModel(prob_fill_on_limit=1.,prob_slippage=0.,random_seed=0),
                latency_model=LatencyModel(base_latency_nanos=0,insert_latency_nanos=0,
                    update_latency_nanos=0,cancel_latency_nanos=0),modules=[module],bar_execution=False,trade_execution=False,
                allow_cash_borrowing=False,use_random_ids=False)
            AccountFactory.register_account_type(venue.value,types['account_type'])
            engine.add_instrument(types['equity_type'](iid,Symbol(instrument),USD,6,Price.from_str('0.000001'),Quantity.from_int(1),0,0))
            adapter=Adapter();engine.add_strategy(adapter)
            ticks=[]
            for day in days:
                micro=prices[day]['close_micro'];p=Price.from_str(f'{micro//1000000}.{micro%1000000:06d}')
                require(Fraction(p.as_decimal())*1000000==micro,'RAW_PRICE_NATIVE_ROUNDTRIP')
                ns=instant(rows[day]['reference_close_utc'])
                ticks.append(QuoteTick(iid,p,p,Quantity.from_int(1000000000),Quantity.from_int(1000000000),ns,ns))
            engine.add_data(ticks)
            start=instant(rows[days[0]]['reference_open_utc'])-2;end=instant(rows[days[-1]]['reference_close_utc'])+1000
            engine.add_data([CustomData(DataType(Boundary),Boundary(start)),CustomData(DataType(Boundary),Boundary(end))],client_id=ClientId('CI-CONTROL'))
            if diagnostics:diagnostics({'phase':'NATIVE_RUN_ENTERED','id':leg})
            engine.run(end=end,streaming=True);engine.end()
            require(len(adapter.nav)==len(days) and not adapter.inflight,'RAW_NATIVE_INCOMPLETE')
            terminal=terminal_check(adapter.book,len(actions))
            tape={'id':leg,'nav':adapter.nav,'intents':adapter.intents,'orders':adapter.orders,'fills':adapter.fills,
                'claim_events':adapter.trace,'settlements':module.receipts,'final_claim_state':compact_state(record(adapter.book)),
                'terminal':terminal,'component_counts':{'recognize':len(actions),'pay':len(module.receipts),
                    'native_positive_balance_updates':sum(r['native_balance_updates'] for r in module.receipts)}}
            results.append(tape)
            if diagnostics:diagnostics({'phase':'ACCOUNT_COMPLETED','id':leg,'nav_points':len(days),'fills':len(adapter.fills)})
        except BaseException:
            if diagnostics:diagnostics({'phase':'ACCOUNT_PARTIAL','id':leg,'partial':
                {'nav':adapter.nav,'fills':adapter.fills,'claim_events':adapter.trace} if adapter else None})
            raise
        finally:engine.dispose()
    return {'schema':'polar.raw-action-native-simulation/1','legs':results,'cost_profile':cost,
        'engine':'nautilus_trader-1.231.0','quote_basis':'RAW_UNADJUSTED_CAPTURED_ACTION_MODEL',
        'quantity_unit':'WHOLE_RAW_SHARE_DECLARED_SOURCE_IDENTITY'}
