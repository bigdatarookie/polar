"""Typed event-only adapter to the existing Nautilus/reference-cent engine.

No source IO, Service admission, evaluator or execution authority on import.
"""
from dataclasses import dataclass, asdict, replace
from fractions import Fraction
from hashlib import sha256
import json
from datetime import date, datetime, timezone

from .ci_research import INITIAL_CENTS, require, fee_cents, maximum_buy
from .research_allocation import desired_targets, nav_cents
from .obs158_math import cent_round_micro
from .scheduled_event_controller import (
    Context, State, Observation, Request, Intent, Anchor, PositionMark,
    RouteReceipt, SymbolEvaluation, TerminalOrder, advance_controller,
    accept_route_receipt, validate_anchor, validate_symbol_census,
)

SYMBOLS = ('BIL', 'VTI')
LEGS = ('CALENDAR_PROTECTION', 'FULL_VTI', 'STATIC_50', 'SMA200', 'FULL_BIL')
COSTS = (('BASE', {'flat_cents':100,'bps':10}), ('FRESH_2X', {'flat_cents':200,'bps':20}))


def key(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class ReferenceClose:
    symbol: str
    date: str
    close_ns: int
    available_ns: int | None
    price_micro: int
    source_id: str
    role: str


@dataclass(frozen=True)
class DecisionPoint:
    decision_ns: int
    q_ns: int


@dataclass(frozen=True)
class EventInstruction:
    request: Request
    q_ns: int


@dataclass(frozen=True)
class EventPlan:
    account_scope: str
    input_id: str
    calendar_id: str
    protocol_id: str
    source: tuple[ReferenceClose, ...]
    nav_closes: tuple[int, ...]
    daily_decisions: tuple[DecisionPoint, ...]
    events: tuple[EventInstruction, ...]
    required_anchors: tuple[int, ...]


def eligible_closes(rows, decision_ns, symbol):
    require(type(decision_ns) is int and type(rows) is tuple and symbol in SYMBOLS, 'EVENT_ELIGIBILITY_TYPE')
    require(all(type(r) is ReferenceClose and r.symbol in SYMBOLS and type(r.close_ns) is int and
                type(r.price_micro) is int and r.price_micro>0 and type(r.source_id) is str and r.source_id and
                r.role in ('NAV','VTI_WARMUP_CANDIDATE','BIL_UNUSED_WARMUP_CONTEXT') and
                (r.role!='VTI_WARMUP_CANDIDATE' or r.symbol=='VTI') and
                (r.role!='BIL_UNUSED_WARMUP_CONTEXT' or r.symbol=='BIL') and
                (r.available_ns is None or type(r.available_ns) is int and r.available_ns>=r.close_ns)
                for r in rows),'EVENT_ELIGIBILITY_ROWS')
    selected=tuple(r for r in rows if r.symbol==symbol)
    require(all(a.close_ns<b.close_ns for a,b in zip(selected,selected[1:])) and
            len({r.source_id for r in selected})==len(selected),'EVENT_ELIGIBILITY_ORDER')
    return tuple(r for r in rows if r.symbol == symbol and r.close_ns < decision_ns and
                 r.available_ns is not None and r.close_ns <= r.available_ns <= decision_ns)


def sma_vti_category(rows, decision_ns):
    """Exactly200 latest supplied eligible VTI closes, never201 or shortened."""
    quotes = eligible_closes(rows, decision_ns, 'VTI')
    if len(quotes) < 200:
        return {'category':'UNAVAILABLE','reason':'ELIGIBLE_PREFIX_LT200','eligible_count':len(quotes),
                'decision_ns':decision_ns,'execution_authority':False}
    window = quotes[-200:]
    total = sum(r.price_micro for r in window); margin = 200*window[-1].price_micro-total
    return {'category':'NORMAL' if margin > 0 else 'BIL','decision_ns':decision_ns,'window':200,
            'sum_micro':total,'last_micro':window[-1].price_micro,'margin_micro':margin,
            'eligible_count':len(quotes),'selector':'LATEST200_SUPPLIED_ELIGIBLE',
            'prices_micro':tuple(r.price_micro for r in window),'source_ids':tuple(r.source_id for r in window),'close_ns':tuple(r.close_ns for r in window),
            'available_ns':tuple(r.available_ns for r in window),'execution_authority':False}


def validate_plan(plan):
    require(type(plan) is EventPlan and all(type(v) is str and v for v in
            (plan.account_scope,plan.input_id,plan.calendar_id,plan.protocol_id)), 'EVENT_PLAN_IDENTITY')
    require(type(plan.source) is tuple and plan.source and all(type(r) is ReferenceClose for r in plan.source), 'EVENT_SOURCE_ROWS')
    dates = {}; source_ids = set()
    for r in plan.source:
        require(r.symbol in SYMBOLS and type(r.close_ns) is int and r.close_ns>=0 and type(r.price_micro) is int and
                r.price_micro > 0 and type(r.source_id) is str and r.source_id and r.source_id not in source_ids and
                (r.available_ns is None or type(r.available_ns) is int and r.available_ns >= r.close_ns), 'EVENT_QUOTE_TYPE')
        require(date.fromisoformat(r.date).isoformat() == r.date and
                datetime.fromtimestamp(r.close_ns//10**9,timezone.utc).date().isoformat()==r.date, 'EVENT_SOURCE_DATE')
        require(r.role in ('NAV','VTI_WARMUP_CANDIDATE','BIL_UNUSED_WARMUP_CONTEXT') and
                (r.role != 'VTI_WARMUP_CANDIDATE' or r.symbol == 'VTI') and
                (r.role != 'BIL_UNUSED_WARMUP_CONTEXT' or r.symbol == 'BIL'), 'EVENT_ROLE')
        require((r.symbol,r.close_ns) not in dates, 'EVENT_DUPLICATE_QUOTE')
        dates[r.symbol,r.close_ns]=r;source_ids.add(r.source_id)
    per_symbol = {s:tuple(r.close_ns for r in plan.source if r.symbol==s) for s in SYMBOLS}
    require(per_symbol['BIL'] == per_symbol['VTI'] and all(a<b for a,b in zip(per_symbol['BIL'],per_symbol['BIL'][1:])),
            'EVENT_SOURCE_RECTANGLE_ORDER')
    require(type(plan.nav_closes) is tuple and len(plan.nav_closes)>=3 and
            all(type(t) is int for t in plan.nav_closes) and
            all(b-a>10000 for a,b in zip(plan.nav_closes,plan.nav_closes[1:])), 'EVENT_NAV_GRID')
    require(all(tuple(r.close_ns for r in plan.source if r.symbol==s and r.role=='NAV')==plan.nav_closes for s in SYMBOLS),
            'EVENT_NAV_ROLE_CORRESPONDENCE')
    require(all(r.role=='NAV' or r.close_ns<plan.nav_closes[0] for r in plan.source), 'WARMUP_AFTER_NAV_START')
    require(type(plan.daily_decisions) is tuple and len(plan.daily_decisions)==len(plan.nav_closes)-1 and
            all(type(d) is DecisionPoint and type(d.decision_ns) is int and type(d.q_ns) is int and
                plan.nav_closes[0]<=d.decision_ns<d.q_ns for d in plan.daily_decisions) and
            tuple(d.q_ns for d in plan.daily_decisions)==plan.nav_closes[1:] and
            all(a.decision_ns<b.decision_ns for a,b in zip(plan.daily_decisions,plan.daily_decisions[1:])), 'EVENT_DAILY_GRID')
    require(type(plan.events) is tuple and all(type(e) is EventInstruction and type(e.request) is Request and
            type(e.q_ns) is int and e.request.decision_ns<e.q_ns and (e.q_ns in plan.nav_closes or e.q_ns>plan.nav_closes[-1]) and
            (e.request.reentry_candidate_ns in plan.nav_closes or e.request.reentry_candidate_ns>plan.nav_closes[-1]) and
            e.request.decision_ns>=plan.daily_decisions[0].decision_ns for e in plan.events), 'EVENT_REQUEST_GRID')
    require(len({e.request.event_id for e in plan.events})==len(plan.events), 'EVENT_DUPLICATE_MEMBER')
    require(type(plan.required_anchors) is tuple and len(set(plan.required_anchors))==len(plan.required_anchors) and
            set(plan.required_anchors)<=set(plan.nav_closes), 'EVENT_REQUIRED_ANCHORS')
    # Reserve native sub-close phases. Equal D/Q is explicitly handled at Q+150;
    # unrelated D inside another close's routing microphases is not admitted.
    ds=[d.decision_ns for d in plan.daily_decisions]+[e.request.decision_ns for e in plan.events]+[
        e.request.reentry_decision_ns for e in plan.events]
    require(all(not any(q<d<=q+1000 for q in plan.nav_closes) for d in ds), 'EVENT_PHASE_COLLISION')
    return dates


class EventNativeFailure(RuntimeError):
    def __init__(self, reason, evidence):
        super().__init__(reason);self.evidence=evidence


def simulate_event_component(plan, diagnostics=None):
    """Ten isolated native component accounts, not a financial/Service run grant."""
    validate_plan(plan)
    accounts=[]
    for cost_id,cost in COSTS:
        for leg in LEGS:
            accounts.append(_simulate_account(plan,leg,cost_id,cost,diagnostics=diagnostics))
    return {'schema':'polar.event-native-component/1','accounts':accounts,'legs':LEGS,
            'cost_ids':tuple(v[0] for v in COSTS),'execution_authority':False,
            'scope':'SUPPLIED_INPUT_NATIVE_COMPONENT_NOT_RETAINED_FINANCIAL_ASSESSMENT'}


def _simulate_account(plan, leg, cost_id, cost, *, diagnostics=None, fill_model=None):
    import uuid
    import importlib.metadata
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.backtest.models import FeeModel, FillModel, LatencyModel
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig, RiskEngineConfig
    from nautilus_trader.trading.strategy import Strategy
    from nautilus_trader.model.identifiers import Venue, InstrumentId, Symbol, ClientId, ClientOrderId
    from nautilus_trader.model.objects import Price, Quantity
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
    from nautilus_trader.model.data import QuoteTick, CustomData, DataType
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.accounting.factory import AccountFactory
    from .research_native_money import native_types
    require(importlib.metadata.version('nautilus_trader')=='1.231.0','ENGINE_VERSION')
    rows=validate_plan(plan);require(leg in LEGS and (cost_id,cost) in COSTS,'EVENT_LEG_COST')
    types=native_types();venue=Venue('EVENT'+uuid.uuid4().hex.upper())
    ids={s:InstrumentId(Symbol(s),venue) for s in SYMBOLS}
    context=Context(key([plan.account_scope,leg,cost_id,plan.input_id,plan.calendar_id,plan.protocol_id]),leg,cost_id,
                    plan.input_id,plan.calendar_id,plan.protocol_id)
    class Boundary(Data):
        def __init__(self,t):self.t=t
        @property
        def ts_event(self):return self.t
        @property
        def ts_init(self):return self.t
    class Fee(FeeModel):
        def get_commission(self,order,fill_qty,fill_px,instrument):
            q=Fraction(fill_qty.as_decimal());p=Fraction(fill_px.as_decimal())*10**6
            require(q.denominator==p.denominator==1,'EVENT_NATIVE_PRECISION')
            return types['money_from_cents'](fee_cents(q.numerator,p.numerator,cost_profile=cost))
    engine=BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True),
              risk_engine=RiskEngineConfig(bypass=False,max_order_submit_rate='20/00:00:01'),run_analysis=False))
    class Adapter(Strategy):
        def __init__(self):
            super().__init__(StrategyConfig(strategy_id=leg,order_id_tag='001',log_events=False,log_commands=False))
            self.controller=State(context,mode='SMA' if leg=='SMA200' else 'CALENDAR')
            self.held={s:0 for s in SYMBOLS};self.cash_expected=INITIAL_CENTS
            self.flat=0;self.bps=0;self.sequence=0;self.quote_sequences={}
            self.sizing={};self.outstanding={};self.active_route=None
            self.decisions=[];self.sma=[];self.anchors=[];self.receipts=[];self.orders=[];self.fills=[];self.nav=[];self.issued=[]
            self.raw_anchors={};self.current_anchors={};self.route_evaluations={};self.failures=[];self.fill_ids=set()
        def step(self):self.sequence+=1;return self.sequence
        def cash(self):
            c=Fraction(engine.portfolio.account(venue).balances_total()[USD].as_decimal())*100
            require(c.denominator==1 and c>=0,'EVENT_NATIVE_CASH');return c.numerator
        def reconcile(self):
            require(not self.outstanding and self.cash()==self.cash_expected,'EVENT_NATIVE_CASH_PENDING')
            actual={s:0 for s in SYMBOLS}
            for p in self.cache.positions_open():
                q=Fraction(p.quantity.as_decimal());require(q.denominator==1 and q>=0,'EVENT_NATIVE_POSITION')
                actual[p.instrument_id.symbol.value]+=q.numerator
            require(actual==self.held,'EVENT_NATIVE_POSITION_RESIDUAL')
        def on_quote_tick(self,tick):self.quote_sequences[tick.instrument_id.symbol.value]=self.step()
        def on_start(self):
            for iid in ids.values():self.subscribe_quote_ticks(iid)
            for q in plan.nav_closes:
                self.clock.set_time_alert_ns('anchor-'+str(q),q+100,lambda e,q=q:self.capture(e,q))
                for i,s in enumerate(SYMBOLS):
                    self.clock.set_time_alert_ns('sell-'+s+'-'+str(q),q+200+i,lambda e,q=q,s=s:self.route(e,q,'SELL',s))
                    self.clock.set_time_alert_ns('buy-'+s+'-'+str(q),q+300+i,lambda e,q=q,s=s:self.route(e,q,'BUY',s))
                self.clock.set_time_alert_ns('receipt-'+str(q),q+400,lambda e,q=q:self.finalize(e,q))
                self.clock.set_time_alert_ns('nav-'+str(q),q+1000,lambda e,q=q:self.sample(e,q))
            observations=[]
            for i,d in enumerate(plan.daily_decisions):observations.append((d.decision_ns,0,'DAILY',d,i))
            if leg=='CALENDAR_PROTECTION':
                for e in plan.events:
                    observations.append((e.request.decision_ns,1,'REDUCED',e,0))
                    observations.append((e.request.reentry_decision_ns,2,'EXPIRY',e,0))
            grouped={}
            for row in observations:grouped.setdefault(row[0],[]).append(row)
            for d,group in grouped.items():
                at=d+150 if d in plan.nav_closes else d
                self.clock.set_time_alert_ns('decide-'+str(d),at,lambda e,g=tuple(sorted(group,key=lambda x:(x[1],str(x[3])))):self.decide(e,g))
        def decision_prices(self,d):
            chosen={s:eligible_closes(plan.source,d,s) for s in SYMBOLS}
            require(all(chosen[s] for s in SYMBOLS),'EVENT_D_PRICE_UNAVAILABLE')
            selected={s:chosen[s][-1] for s in SYMBOLS}
            return {s:r.price_micro for s,r in selected.items()},selected
        def queue_control(self,d,q,destination,cause):
            generation=self.controller.generation+1
            weights={'NORMAL':(Fraction(1),Fraction(0)),'BIL':(Fraction(0),Fraction(1)),
                     'REDUCED':(Fraction(1,2),Fraction(1,2)),'EXIT':(Fraction(0),Fraction(0))}[destination]
            p=Intent(key([asdict(context),generation,d,q,cause]),generation,destination,d,q,cause,(),
                     plan.nav_closes[-1] if destination=='REDUCED' else None,*weights)
            old=self.controller.pending
            self.controller=replace(self.controller,asof_ns=d,desired=destination,pending=p,generation=generation,
                               terminal=destination=='EXIT')
            return {'action':'EXIT' if destination=='EXIT' else 'TARGET','reason':cause,'old':old}
        def decide(self,event,group):
            for d,_,kind,obj,index in group:
                if self.controller.terminal:continue
                old=self.controller.pending
                if kind=='DAILY':
                    q=obj.q_ns
                    if index==len(plan.daily_decisions)-1:
                        result=advance_controller(self.controller,Observation('EXIT',d,q));self.controller=result.state
                        action,reason=result.action,result.reason
                    elif leg=='CALENDAR_PROTECTION':
                        if index!=0:continue
                        result=advance_controller(self.controller,Observation('INIT',d,q));self.controller=result.state
                        action,reason=result.action,result.reason
                    elif leg=='SMA200':
                        signal=sma_vti_category(plan.source,d);self.sma.append(signal)
                        result=advance_controller(self.controller,Observation('SMA',d,q,category=signal['category']));self.controller=result.state
                        action,reason=result.action,result.reason
                    else:
                        month_end=(index+2<len(plan.nav_closes) and
                            rows['VTI',q].date[:7]!=rows['VTI',plan.nav_closes[index+2]].date[:7])
                        if index!=0 and not(leg=='STATIC_50' and month_end):continue
                        destination={'FULL_VTI':'NORMAL','FULL_BIL':'BIL','STATIC_50':'REDUCED'}[leg]
                        result=self.queue_control(d,q,destination,'CONTROL_INITIAL' if index==0 else 'STATIC_MONTH_END')
                        action,reason=result['action'],result['reason']
                elif kind=='REDUCED':
                    result=advance_controller(self.controller,Observation('REDUCED',d,obj.q_ns,obj.request));self.controller=result.state
                    action,reason=result.action,result.reason
                else:
                    result=advance_controller(self.controller,Observation('EXPIRY',d));self.controller=result.state
                    action,reason=result.action,result.reason
                p=self.controller.pending
                record={'decision_ns':d,'observed_native_ns':event.ts_event,'action':action,'reason':reason,
                        'desired':self.controller.desired,'pending_id':p.intent_id if p else None,'sequence':self.step(),
                        'cancelled_or_superseded_ids':(old.intent_id,) if old and (p is None or p.intent_id!=old.intent_id) else (),
                        'obsolete_pending_cancelled':bool(old and old.destination=='REDUCED' and old.expiry_ns is not None and old.q_ns>old.expiry_ns and (not p or p.intent_id!=old.intent_id))}
                self.decisions.append(record)
                if p and (old is None or p.intent_id!=old.intent_id):
                    if old and old.destination==p.destination and old.decision_ns==p.decision_ns and old.q_ns==p.q_ns and old.intent_id in self.sizing:
                        self.sizing[p.intent_id]={**self.sizing[old.intent_id],'coalesced_from':old.intent_id}
                    else:
                        self.reconcile();prices,selected=self.decision_prices(d);witness={}
                        if p.destination=='EXIT':targets={s:0 for s in SYMBOLS}
                        else:targets=desired_targets(self.cash(),self.held,prices,{'VTI':p.vti_weight,'BIL':p.bil_weight},witness=witness)
                        self.sizing[p.intent_id]={'id':key([context.account_id,p.intent_id,'sizing']),'intent_id':p.intent_id,
                            'decision_ns':p.decision_ns,'native_capture_ns':event.ts_event,'capture_sequence':record['sequence'],'cash_cents':self.cash(),
                            'holdings':dict(self.held),'prices_micro':prices,'source_rows':{s:asdict(v) for s,v in selected.items()},
                            'targets':targets,'weights':{'VTI':p.vti_weight,'BIL':p.bil_weight},'consumed':witness,
                            'terminal':p.destination=='EXIT','context':asdict(context)}
        def capture(self,event,q):
            self.reconcile();prices={s:rows[s,q].price_micro for s in SYMBOLS}
            for s in SYMBOLS:
                quote=self.cache.quote_tick(ids[s])
                require(quote is not None and quote.ts_event==q+SYMBOLS.index(s) and
                        Fraction(quote.bid_price.as_decimal())*10**6==prices[s], 'EVENT_ANCHOR_QUOTE_BINDING')
            nav,amounts=nav_cents(self.cash(),self.held,prices,allow_zero=True);seq=self.step()
            self.raw_anchors[q]={'context':context,'generation':self.controller.generation,'q_ns':q,'mark_ns':event.ts_event,
                'quote_barrier_sequence':max(self.quote_sequences.values()),'mark_sequence':seq,'cash_cents':self.cash(),
                'positions':tuple(PositionMark(s,self.held[s],Fraction(prices[s],10**6),amounts[s],rows[s,q].source_id) for s in SYMBOLS),
                'nav_cents':nav,'cumulative_flat_cents':self.flat,'cumulative_bps_cents':self.bps,
                'anchor_id':key([context.account_id,q,'anchor'])}
            if self.controller.pending and self.controller.pending.q_ns==q:
                result=advance_controller(self.controller,Observation('ROUTE_Q',q));self.controller=result.state
                self.decisions.append({'decision_ns':q,'observed_native_ns':event.ts_event,'action':result.action,
                                       'reason':result.reason,'sequence':self.step()})
                if self.controller.awaiting:
                    self.active_route=self.controller.awaiting;self.issued.append(self.active_route)
        def route(self,event,q,side,symbol):
            self.reconcile()
            if side=='SELL' and symbol==SYMBOLS[0]:
                raw=self.raw_anchors[q];a=Anchor(**raw,route_barrier_ns=event.ts_event,first_route_sequence=self.step())
                # Generation identifies the dispatched intent even if D==Q has
                # since queued a newer intent for a later Q.
                p=self.active_route
                if p:a=replace(a,generation=p.generation)
                validate_anchor(a,context,a.generation,q);self.current_anchors[q]=a;self.anchors.append(a)
                if p:
                    sizing=self.sizing[p.intent_id]
                    self.route_evaluations[q]={s:{'delta':sizing['targets'][s]-self.held[s],'orders':[],'routed':0,
                                                  'clipping':None,'sizing_id':sizing['id']} for s in SYMBOLS}
            p=self.active_route
            if not p or p.q_ns!=q:return
            for s in (symbol,):
                value=self.route_evaluations[q][s];delta=value['delta']
                if (side=='SELL' and delta>=0) or (side=='BUY' and delta<=0):continue
                desired=abs(delta);price=rows[s,q].price_micro;pre_cash=self.cash();pre_held=dict(self.held);clip={}
                quantity=desired if side=='SELL' else maximum_buy(desired,price,pre_cash,cost_profile=cost,witness=clip)
                if quantity<desired:value['clipping']='FUTURE_CLOSE_FEE_AWARE_CAP'
                value['routed']+=quantity
                route={'context':asdict(context),'intent_id':p.intent_id,'generation':p.generation,'q_ns':q,
                       'symbol':s,'side':side,'sequence':self.step(),'at_ns':event.ts_event,'price_micro':price,
                       'source_id':rows[s,q].source_id,'pre_cash_cents':pre_cash,'pre_holdings':pre_held,
                       'desired':desired,'routed_quantity':quantity,'clip_witness':clip,'fills':[],'status':'ZERO_EXECUTABLE' if not quantity else 'SUBMITTED'}
                self.orders.append(route)
                if not quantity:continue
                fee=fee_cents(quantity,price,cost_profile=cost);settled=cent_round_micro(quantity*price)
                require(pre_cash+(settled-fee if side=='SELL' else -settled-fee)>=0,'EVENT_SELL_FEE_SHORTFALL')
                oid=key([p.intent_id,s,side]);order=self.order_factory.market(instrument_id=ids[s],
                    order_side=OrderSide.SELL if side=='SELL' else OrderSide.BUY,quantity=Quantity.from_int(quantity),
                    time_in_force=TimeInForce.GTC,client_order_id=ClientOrderId(oid))
                require(oid not in self.outstanding and not any(v.get('order_id')==oid for v in self.orders[:-1]),'EVENT_DUPLICATE_ORDER')
                route['order_id']=oid;self.outstanding[oid]=route;value['orders'].append(route)
                self.submit_order(order)
        def on_order_filled(self,event):
            oid=str(event.client_order_id);r=self.outstanding.get(oid)
            actual={'order_id':oid,'fill_id':str(event.trade_id),'quantity':str(event.last_qty.as_decimal()),'price':str(event.last_px.as_decimal()),
                    'commission':str(event.commission.as_decimal()),'commission_currency':str(event.commission.currency),
                    'side':'BUY' if event.order_side==OrderSide.BUY else 'SELL','instrument_id':str(event.instrument_id),
                    'account_id':str(event.account_id),'at_ns':event.ts_event,'sequence':self.step()}
            self.fills.append(actual)
            require(actual['fill_id'] not in self.fill_ids,'EVENT_DUPLICATE_FILL');self.fill_ids.add(actual['fill_id'])
            require(r is not None and str(event.instrument_id)==str(ids[r['symbol']]) and
                    event.order_side==(OrderSide.BUY if r['side']=='BUY' else OrderSide.SELL),'EVENT_UNEXPECTED_FILL')
            q=Fraction(event.last_qty.as_decimal());p=Fraction(event.last_px.as_decimal())*10**6
            fee=Fraction(event.commission.as_decimal())*100
            require(q.denominator==p.denominator==fee.denominator==1,'EVENT_FILL_PRECISION')
            # Preserve the actual callback before refusing an unsupported partial.
            r['fills'].append(actual)
            matches=(q.numerator==r['routed_quantity'] and p.numerator==r['price_micro'] and
                     event.commission.currency==USD and fee.numerator==fee_cents(q.numerator,p.numerator,cost_profile=cost))
            if not matches:
                r['status']='PARTIAL_OR_MISMATCH_UNFINALIZED'
                self.failures.append({'kind':r['status'],'actual_fill':actual,'requested':r['routed_quantity']})
            require(matches,'EVENT_NATIVE_PARTIAL_OR_MISMATCH')
            settled=cent_round_micro(q.numerator*p.numerator);sign=1 if r['side']=='BUY' else -1
            self.held[r['symbol']]+=sign*q.numerator;self.cash_expected-=sign*settled+fee.numerator
            self.flat+=cost['flat_cents'];self.bps+=fee.numerator-cost['flat_cents'];r['status']='FILLED'
            r.update(actual_fee_cents=fee.numerator,actual_settled_cents=settled,post_cash_cents=self.cash_expected)
            self.outstanding.pop(oid)
        def refuse(self,event,kind):
            self.failures.append({'kind':kind,'order_id':str(event.client_order_id),'at_ns':event.ts_event})
            require(False,'EVENT_NATIVE_'+kind)
        def on_order_denied(self,event):self.refuse(event,'DENIED')
        def on_order_rejected(self,event):self.refuse(event,'REJECTED')
        def on_order_canceled(self,event):self.refuse(event,'CANCELLED')
        def finalize(self,event,q):
            self.reconcile();p=self.active_route
            if not p or p.q_ns!=q:return
            evaluations=[];order_count=fill_count=0
            for s in SYMBOLS:
                v=self.route_evaluations[q][s];orders=[]
                for r in v['orders']:
                    require(r['status']=='FILLED','EVENT_UNFINALIZED_ORDER')
                    ids_f=tuple(x['fill_id'] for x in r['fills']);order_count+=1;fill_count+=len(ids_f)
                    orders.append(TerminalOrder(r['order_id'],r['side'],r['routed_quantity'],r['routed_quantity'],'FILLED',ids_f))
                evaluations.append(SymbolEvaluation(s,v['delta'],v['routed'],v['clipping'],v['sizing_id'],tuple(orders)))
            zero=all(v.desired_delta==0 for v in evaluations)
            outcome='ZERO_DELTA_NO_ORDER' if zero else 'FILLED' if order_count else 'NO_FILL'
            receipt=RouteReceipt(context,p.intent_id,p.generation,q,event.ts_event,self.current_anchors[q],outcome,
                tuple((v.symbol,v.desired_delta) for v in evaluations),tuple(sorted({v.consumed_sizing_id for v in evaluations})),
                order_count,order_count,fill_count,tuple(evaluations))
            self.controller=accept_route_receipt(self.controller,receipt);self.receipts.append(receipt);self.active_route=None
        def sample(self,event,q):
            self.reconcile();prices={s:rows[s,q].price_micro for s in SYMBOLS};nav,amounts=nav_cents(self.cash(),self.held,prices,allow_zero=True)
            self.nav.append({'date':rows['VTI',q].date,'nominal_ns':q,'sample_ns':event.ts_event,'nav_cents':nav,
                'cash_cents':self.cash(),'positions':dict(self.held),'position_cents':amounts,'flat_cents':self.flat,
                'bps_cents':self.bps,'desired':self.controller.desired,'committed':self.controller.committed,
                'conservative_reduced':self.controller.conservative_reduced,'duration_evidence_complete':self.controller.duration_evidence_complete})
        def output(self):
            return {'context':context,'leg':leg,'cost_id':cost_id,'cost_profile':dict(cost),
                'native_account_id':str(engine.portfolio.account(venue).id),'native_instruments':{s:str(ids[s]) for s in SYMBOLS},
                'quote_basis':'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT','quantity_unit':'WHOLE_SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE','decisions':self.decisions,
                'sma':self.sma,'sizing':self.sizing,'anchors':self.anchors,'receipts':self.receipts,'orders':self.orders,
                'fills':self.fills,'nav':self.nav,'failures':self.failures,'state':self.controller,'required_anchors':plan.required_anchors,
                'issued_intents':self.issued,'nav_role_grid':plan.nav_closes,'nav_role_dates':tuple(rows['VTI',q].date for q in plan.nav_closes),
                'initial_cash_cents':INITIAL_CENTS,'status':'COMPLETE_NATIVE_TRACE' if all(r.outcome!='NO_FILL' for r in self.receipts) else 'COMPLETE_TRACE_WITH_UNCONFIRMED_TARGET',
                'sma_control_complete':all(v['category']!='UNAVAILABLE' for v in self.sma),
                'event_census':[{'event_id':e.request.event_id,'candidate_q':e.q_ns,'expiry_ns':e.request.expiry_ns,
                    'protection_censored':e.q_ns>plan.nav_closes[-1],'reentry_censored':e.request.reentry_candidate_ns>plan.nav_closes[-1]} for e in plan.events]}
    adapter=None
    try:
        engine.add_venue(venue=venue,oms_type=OmsType.NETTING,account_type=AccountType.CASH,
            starting_balances=[types['money_from_cents'](INITIAL_CENTS)],base_currency=USD,fee_model=Fee(),
            fill_model=fill_model or FillModel(prob_slippage=0.,random_seed=0),latency_model=LatencyModel(base_latency_nanos=0),
            bar_execution=False,trade_execution=False,allow_cash_borrowing=False,use_random_ids=False)
        AccountFactory.register_account_type(venue.value,types['account_type'])
        for s in SYMBOLS:engine.add_instrument(types['equity_type'](ids[s],Symbol(s),USD,6,Price.from_str('0.000001'),Quantity.from_int(1),0,0))
        adapter=Adapter();engine.add_strategy(adapter);ticks=[]
        for q in plan.nav_closes:
            for i,s in enumerate(SYMBOLS):
                p=rows[s,q].price_micro;px=Price.from_str(f'{p//10**6}.{p%10**6:06d}')
                ticks.append(QuoteTick(ids[s],px,px,Quantity.from_int(10**9),Quantity.from_int(10**9),q+i,q+i))
        engine.add_data(ticks);end=plan.nav_closes[-1]+1001
        engine.add_data([CustomData(DataType(Boundary),Boundary(plan.nav_closes[0]-1)),
                         CustomData(DataType(Boundary),Boundary(end))],client_id=ClientId('EVENT-COMPONENT'))
        if diagnostics:diagnostics({'phase':'NATIVE_RUN_ENTERED','leg':leg,'cost_id':cost_id})
        engine.run(end=end,streaming=True);engine.end();adapter.reconcile()
        require(len(adapter.nav)==len(plan.nav_closes) and not any(adapter.held.values()) and
                adapter.controller.awaiting is None and adapter.controller.pending is None,'EVENT_NATIVE_INCOMPLETE')
        result=adapter.output();verify_saved_event_witnesses(result)
        if diagnostics:diagnostics({'phase':'ACCOUNT_COMPLETED','leg':leg,'cost_id':cost_id,'nav_points':len(adapter.nav)})
        return result
    except BaseException as exc:
        evidence=adapter.output() if adapter else {'leg':leg,'cost_id':cost_id}
        evidence['status']='FAILED_UNFINALIZED'
        try:
            from nautilus_trader.model.enums import PositionSide
            physical={s:0 for s in SYMBOLS}
            if adapter:
                for pos in adapter.cache.positions_open():
                    amount=Fraction(pos.quantity.as_decimal());require(amount.denominator==1,'EVENT_PARTIAL_QUANTITY')
                    physical[pos.instrument_id.symbol.value]+=amount.numerator*(-1 if pos.side==PositionSide.SHORT else 1)
                evidence['actual_native_partial_observation']={'cash_cents':adapter.cash(),'positions':physical,
                    'controller_expected_cash_cents':adapter.cash_expected,'controller_expected_positions':dict(adapter.held),
                    'scope':'OBSERVED_PARTIAL_NOT_RECONCILED_OR_COMPLETED'}
        except Exception as observation_error:
            evidence['actual_native_partial_observation']={'status':'UNAVAILABLE','error':str(observation_error)}
        if diagnostics:diagnostics({'phase':'ACCOUNT_PARTIAL','leg':leg,'cost_id':cost_id,'error':str(exc),'evidence':evidence})
        raise EventNativeFailure(str(exc),evidence) from exc
    finally:engine.dispose()


def verify_saved_event_witnesses(account):
    """Source-absent arithmetic/identity audit of supplied consumed witnesses.

    Does not reroute/rebuild a portfolio, read prices or invoke native/Service.
    Typed Python output is not a qualified external private wire/replay schema.
    """
    context=account['context'];require(type(context) is Context,'EVENT_SAVED_CONTEXT')
    require(account['state'].context==context and account['state'].terminal and account['state'].awaiting is None and
            account['state'].pending is None and not account['failures'],'EVENT_SAVED_FINAL_STATE')
    anchors={a.q_ns:a for a in account['anchors']};require(len(anchors)==len(account['anchors']),'EVENT_SAVED_DUPLICATE_ANCHOR')
    require(set(account['required_anchors'])<=set(anchors) and set(anchors)==set(account['nav_role_grid']),'EVENT_SAVED_ANCHOR_MISSING')
    require(account['sma_control_complete']==all(v['category']!='UNAVAILABLE' for v in account['sma']),'EVENT_SAVED_SMA_COMPLETENESS')
    for signal in account['sma']:
        if signal['category']=='UNAVAILABLE':
            require(signal['eligible_count']<200,'EVENT_SAVED_SMA_UNAVAILABLE');continue
        require(signal['category'] in {'NORMAL','BIL'} and signal['window']==200 and
                all(len(signal[k])==200 for k in ('prices_micro','source_ids','close_ns','available_ns')) and
                len(set(signal['source_ids']))==200 and all(type(p) is int and p>0 for p in signal['prices_micro']) and
                all(a<b for a,b in zip(signal['close_ns'],signal['close_ns'][1:])) and
                all(c<signal['decision_ns'] and c<=k<=signal['decision_ns'] for c,k in zip(signal['close_ns'],signal['available_ns'])),
                'EVENT_SAVED_SMA_PREFIX')
        total=sum(signal['prices_micro']);margin=200*signal['prices_micro'][-1]-total
        require((signal['sum_micro'],signal['last_micro'],signal['margin_micro'],signal['category'])==
                (total,signal['prices_micro'][-1],margin,'NORMAL' if margin>0 else 'BIL'),'EVENT_SAVED_SMA_FORMULA')
    def prefix(at_ns,sequence):
        cash=account['initial_cash_cents'];held={s:0 for s in SYMBOLS};flat=bps=0
        for f in sorted(account['fills'],key=lambda v:(v['at_ns'],v['sequence'])):
            if (f['at_ns'],f['sequence'])>=(at_ns,sequence):break
            s=next((n for n,iid in account['native_instruments'].items() if iid==f['instrument_id']),None)
            require(s in SYMBOLS,'EVENT_SAVED_FILL_INSTRUMENT')
            qty=Fraction(f['quantity']);price=Fraction(f['price'])*10**6;fee=Fraction(f['commission'])*100
            require(qty.denominator==price.denominator==fee.denominator==1,'EVENT_SAVED_FILL_PRECISION')
            sign=1 if f['side']=='BUY' else -1
            held[s]+=sign*qty.numerator;cash-=sign*cent_round_micro(qty.numerator*price.numerator)+fee.numerator
            flat+=account['cost_profile']['flat_cents'];bps+=fee.numerator-account['cost_profile']['flat_cents']
        return cash,held,flat,bps
    for a in anchors.values():
        validate_anchor(a,context,a.generation,a.q_ns)
        cash,held,flat,bps=prefix(a.mark_ns,a.mark_sequence)
        prices={v.symbol:int(v.close*10**6) for v in a.positions};value,amounts=nav_cents(cash,held,prices,allow_zero=True)
        require((a.cash_cents,{v.symbol:v.quantity for v in a.positions},
                 {v.symbol:v.rounded_value_cents for v in a.positions},a.nav_cents,
                 a.cumulative_flat_cents,a.cumulative_bps_cents)==(cash,held,amounts,value,flat,bps),
                'EVENT_SAVED_ANCHOR_EXECUTED_PREFIX')
    sizing_by_id={}
    for intent_id,w in account['sizing'].items():
        require(w['context']==asdict(context),'EVENT_SAVED_SIZING_CONTEXT')
        original_id=w['intent_id'];origin=account['sizing'].get(original_id)
        require(origin is not None and w['id']==key([context.account_id,original_id,'sizing']) and
                (intent_id==original_id or 'coalesced_from' in w and w['coalesced_from'] in account['sizing'] and
                 {k:v for k,v in w.items() if k!='coalesced_from'}==
                 {k:v for k,v in account['sizing'][w['coalesced_from']].items() if k!='coalesced_from'}),
                'EVENT_SAVED_SIZING_ORIGIN')
        expected_capture=w['decision_ns']+(150 if w['decision_ns'] in anchors else 0)
        require(w['native_capture_ns']==expected_capture and type(w['capture_sequence']) is int and
                any(d.get('pending_id')==original_id and d['decision_ns']==w['decision_ns'] and
                    d['observed_native_ns']==w['native_capture_ns'] and d['sequence']==w['capture_sequence']
                    for d in account['decisions']), 'EVENT_SAVED_SIZING_CAPTURE')
        if w['decision_ns'] in anchors:
            a=anchors[w['decision_ns']]
            require(a.mark_ns<w['native_capture_ns']<a.route_barrier_ns and
                    a.mark_sequence<w['capture_sequence']<a.first_route_sequence and
                    all(d['sequence']<w['capture_sequence'] for d in account['decisions']
                        if d['decision_ns']==w['decision_ns'] and d['action']=='ROUTE_INTENT'),
                    'EVENT_SAVED_SIZING_Q_BARRIER')
        cash,held,_,_=prefix(w['native_capture_ns'],w['capture_sequence'])
        require((w['cash_cents'],w['holdings'])==(cash,held),'EVENT_SAVED_SIZING_EXECUTED_PREFIX')
        require(all(r['close_ns']<w['decision_ns'] and r['available_ns'] is not None and
                    r['close_ns']<=r['available_ns']<=w['decision_ns'] and r['price_micro']==w['prices_micro'][s]
                    for s,r in w['source_rows'].items()),'EVENT_SAVED_SIZING_ELIGIBILITY')
        expected={s:0 for s in SYMBOLS} if w['terminal'] else desired_targets(w['cash_cents'],w['holdings'],w['prices_micro'],w['weights'])
        require(expected==w['targets'],'EVENT_SAVED_FLOOR_TARGETS')
        sizing_by_id[w['id']]=w
    issued={p.intent_id:p for p in account['issued_intents']}
    require(len(issued)==len(account['issued_intents']) and len({p.q_ns for p in issued.values()})==len(issued),
            'EVENT_SAVED_DUPLICATE_INTENT_Q')
    require({r.intent_id for r in account['receipts']}==set(issued) and len(account['receipts'])==len(issued),
            'EVENT_SAVED_RECEIPT_CENSUS')
    all_orders={o['order_id']:o for o in account['orders'] if o['routed_quantity']}
    receipt_by_intent={r.intent_id:r for r in account['receipts']}
    for receipt in account['receipts']:
        p=issued[receipt.intent_id]
        require(receipt.context==context and receipt.anchor==anchors.get(receipt.q_ns) and
                receipt.q_ns==p.q_ns and receipt.generation==p.generation and receipt.finalized_ns>=receipt.anchor.route_barrier_ns,
                'EVENT_SAVED_RECEIPT_BINDING')
        validate_anchor(receipt.anchor,context,receipt.generation,receipt.q_ns);validate_symbol_census(receipt)
        require(all(sid in sizing_by_id for sid in receipt.sizing_evidence_ids),'EVENT_SAVED_SIZING_MISSING')
        w=account['sizing'][receipt.intent_id]
        require(p.decision_ns==w['decision_ns'] and p.decision_ns<p.q_ns and
                w['weights']=={'VTI':p.vti_weight,'BIL':p.bil_weight},'EVENT_SAVED_INTENT_SIZING')
        require(receipt.outcome in {'FILLED','ZERO_DELTA_NO_ORDER','NO_FILL'},'EVENT_SAVED_OUTCOME')
        if receipt.outcome=='ZERO_DELTA_NO_ORDER':
            require(all(v==0 for _,v in receipt.desired_deltas) and receipt.order_count==receipt.fill_count==0,'EVENT_SAVED_ZERO_DELTA')
        elif receipt.outcome=='FILLED':
            require(receipt.order_count>0 and any(v!=0 for _,v in receipt.desired_deltas),'EVENT_SAVED_FILLED_CENSUS')
        else:
            require(receipt.order_count==receipt.fill_count==0 and any(v!=0 for _,v in receipt.desired_deltas),'EVENT_SAVED_NO_FILL')
        before={v.symbol:v.quantity for v in receipt.anchor.positions}
        require(dict(receipt.desired_deltas)=={s:w['targets'][s]-before[s] for s in SYMBOLS},'EVENT_SAVED_TARGET_DELTA')
        terminal_ids=[]
        for evaluation in receipt.symbol_evaluations:
            for terminal in evaluation.orders:
                r=all_orders.get(terminal.order_id)
                require(r is not None and r['intent_id']==receipt.intent_id and r['generation']==receipt.generation and
                        r['symbol']==evaluation.symbol and r['side']==terminal.side and r['status']=='FILLED' and
                        r['routed_quantity']==terminal.quantity==terminal.filled_quantity and
                        tuple(f['fill_id'] for f in r['fills'])==terminal.fill_ids,'EVENT_SAVED_TERMINAL_NATIVE_JOIN')
                terminal_ids.append(terminal.order_id)
        require(set(terminal_ids)=={o['order_id'] for o in account['orders'] if o['routed_quantity'] and
                                   o['intent_id']==receipt.intent_id},'EVENT_SAVED_TERMINAL_CENSUS')
    order_ids=set();fill_ids=set()
    for order in account['orders']:
        require(order['context']==asdict(context) and order['q_ns'] in anchors and
                anchors[order['q_ns']].first_route_sequence<order['sequence'] and
                anchors[order['q_ns']].mark_ns<order['at_ns'],'EVENT_SAVED_ROUTE_BARRIER')
        q=order['routed_quantity'];p=order['price_micro']
        clip={}
        expected=order['desired'] if order['side']=='SELL' else maximum_buy(order['desired'],p,order['pre_cash_cents'],cost_profile=account['cost_profile'],witness=clip)
        require(q==expected and order['clip_witness']==clip,'EVENT_SAVED_AFFORDABILITY')
        if q:
            require(order['order_id'] not in order_ids,'EVENT_SAVED_DUPLICATE_ORDER');order_ids.add(order['order_id'])
            require(order['actual_fee_cents']==fee_cents(q,p,cost_profile=account['cost_profile']) and
                    order['actual_settled_cents']==cent_round_micro(q*p),'EVENT_SAVED_FEE_SETTLEMENT')
            for fill in order['fills']:
                require(fill['fill_id'] not in fill_ids,'EVENT_SAVED_DUPLICATE_FILL');fill_ids.add(fill['fill_id'])
                receipt=receipt_by_intent.get(order['intent_id']);a=anchors[order['q_ns']]
                require(receipt is not None and fill['order_id']==order['order_id'] and
                        a.mark_ns<order['at_ns']<=fill['at_ns']<=receipt.finalized_ns<order['q_ns']+1000 and
                        a.first_route_sequence<order['sequence']<fill['sequence'] and
                        all(fill['sequence']<later['sequence'] for later in account['orders']
                            if later['q_ns']==order['q_ns'] and later['sequence']>order['sequence']),
                        'EVENT_SAVED_FILL_CAUSAL_ORDER_JOIN')
    actual_fills={f['fill_id']:f for f in account['fills']}
    require(len(actual_fills)==len(account['fills']) and set(actual_fills)==fill_ids,'EVENT_SAVED_ACTUAL_FILL_CENSUS')
    cash=account['initial_cash_cents'];held={s:0 for s in SYMBOLS};flat=bps=0
    pending=iter(sorted(account['orders'],key=lambda o:o['sequence']));next_order=next(pending,None)
    require(tuple(v['nominal_ns'] for v in account['nav'])==tuple(account['nav_role_grid']) and
            tuple(v['date'] for v in account['nav'])==tuple(account['nav_role_dates']) and
            all(datetime.fromtimestamp(v['nominal_ns']//10**9,timezone.utc).date().isoformat()==v['date'] and
                v['sample_ns']==v['nominal_ns']+1000 for v in account['nav']), 'EVENT_SAVED_NAV_ROLE_GRID')
    for nav in account['nav']:
        q=nav['nominal_ns'];a=anchors[q]
        while next_order is not None and next_order['q_ns']<=q:
            order=next_order
            require(order['pre_cash_cents']==cash and order['pre_holdings']==held,'EVENT_SAVED_PREORDER_STATE')
            qty=order['routed_quantity'];price=order['price_micro']
            if qty:
                require(len(order['fills'])==1,'EVENT_SAVED_UNSUPPORTED_PARTIAL')
                f=order['fills'][0];require(actual_fills[f['fill_id']]==f,'EVENT_SAVED_ACTUAL_FILL_JOIN')
                require(Fraction(f['quantity'])==qty and Fraction(f['price'])*10**6==price and
                        f['side']==order['side'] and f['commission_currency']=='USD' and
                        f['account_id']==account['native_account_id'] and f['instrument_id']==account['native_instruments'][order['symbol']] and
                        Fraction(f['commission'])*100==fee_cents(qty,price,cost_profile=account['cost_profile']), 'EVENT_SAVED_FILL_OPERANDS')
                fee=fee_cents(qty,price,cost_profile=account['cost_profile']);settled=cent_round_micro(qty*price)
                sign=1 if order['side']=='BUY' else -1;held[order['symbol']]+=sign*qty;cash-=sign*settled+fee
                flat+=account['cost_profile']['flat_cents'];bps+=fee-account['cost_profile']['flat_cents']
                require(cash==order['post_cash_cents'],'EVENT_SAVED_POSTORDER_CASH')
            next_order=next(pending,None)
        prices={v.symbol:int(v.close*10**6) for v in a.positions}
        value,amounts=nav_cents(cash,held,prices,allow_zero=True)
        require((nav['cash_cents'],nav['positions'],nav['position_cents'],nav['nav_cents'],nav['flat_cents'],nav['bps_cents'])==
                (cash,held,amounts,value,flat,bps),'EVENT_SAVED_NAV_LEDGER')
    require(next_order is None and not any(held.values()),'EVENT_SAVED_FINAL_TAPE')
    return {'status':'VERIFIED_SAVED_CONSUMED_EVENT_WITNESSES','market_source_reads':0,'native_calls':0,'Service_calls':0,
            'economic_criteria':'NOT_ASSESSED','execution_authority':False}
