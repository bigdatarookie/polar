"""One supplied signed research account: event algebra and serial native gate.

No policy, source loader, trial admission, clock inference or broker authority.
The hosting native Strategy calls next_order/submit, then actual callbacks.
"""
from dataclasses import dataclass, asdict
from copy import deepcopy
from fractions import Fraction
from datetime import datetime, timezone

from .signed_account_core import (State, mark, amount_cents, rational, integer,
    recognize_distribution, pay_claim, accrue, settle_accrual, top_up, propose_fill)
from .signed_native_bridge import MarkEvent, MarkIdentity, require, whole
from .distribution_claims import half_even, day, token

NS = 10**9
PHASES = ('FORCED_COVERS', 'FORCED_SALES', 'FORCED_RETRY', 'PAYMENT',
          'ORD_COVERS', 'ORD_SALES', 'ORD_RETRY', 'NEW_SHORT', 'NEW_LONG', 'FINAL')


@dataclass(frozen=True)
class AccountContext:
    account: str
    path: str
    config: str
    source: str
    names: tuple[str, ...]

    def __post_init__(self):
        for v in (self.account, self.path, self.config, self.source): token(v)
        require(type(self.names) is tuple and len(self.names) == 2 and
                tuple(sorted(set(self.names))) == self.names, 'DRIVER_TWO_NAMES')
        for v in self.names: token(v)


@dataclass(frozen=True)
class Rate:
    component: str
    name: str | None
    annual_rate: Fraction
    provenance: str

    def __post_init__(self):
        rational(self.annual_rate); token(self.provenance)
        require(self.component in ('BORROW', 'DEBIT_INTEREST', 'FREE_CASH_INTEREST'), 'DRIVER_RATE_COMPONENT')
        require((self.name is not None) == (self.component == 'BORROW'), 'DRIVER_RATE_NAME')
        if self.name is not None: token(self.name)


@dataclass(frozen=True)
class Action:
    id: str
    name: str
    kind: str
    nominal_usd: Fraction | None
    ex_date: str | None
    payment_date: str | None
    currency: str | None
    source_ref: str
    historical_known_ns: int | None = None


@dataclass(frozen=True)
class Locate:
    id: str
    path: str
    account: str
    formation: str
    issuer: str
    side: str
    execution_event: str
    cap: int
    success: bool
    provenance: str

    def __post_init__(self):
        for v in (self.id, self.path, self.account, self.formation, self.issuer,
                  self.side, self.execution_event, self.provenance): token(v)
        integer(self.cap); require(self.side == 'SHORT' and type(self.success) is bool, 'DRIVER_LOCATE')


@dataclass(frozen=True)
class Event:
    id: str
    at_ns: int
    kind: str                         # EX, CLOSE, OBSERVATION
    marks: tuple[tuple[str, Fraction], ...]
    mark_event: MarkEvent
    instruction: str = 'HOLD'        # predeclared TARGET, EXIT, HOLD
    formation: str | None = None
    decision_ns: int | None = None
    targets: tuple[tuple[str, int], ...] = ()
    execution_prices: tuple[tuple[str, Fraction], ...] = ()
    locates: tuple[Locate, ...] = ()
    actions: tuple[Action, ...] = ()
    rates: tuple[Rate, ...] = ()       # rates effective AFTER this event
    recalled: tuple[str, ...] = ()
    latency_ns: int = 60 * NS
    maintenance_short: Fraction = Fraction(3, 10)
    buffer: Fraction = Fraction(1, 10)
    flat_fee_cents: int = 100
    fee_bps: int = 10
    terminal: bool = False


@dataclass(frozen=True)
class OrderRequest:
    intent_id: str
    event_id: str
    phase: str
    name: str
    side: str
    quantity: int
    price: Fraction
    fee_cents: int
    forced: bool
    locate_id: str | None
    located_cap: int | None


def fee_for(event, quantity, price):
    return event.flat_fee_cents + half_even(Fraction(quantity) * price * 100 * event.fee_bps / 10000)


def event_date(at_ns):
    require(type(at_ns) is int and at_ns >= 0, 'DRIVER_TIME')
    return datetime.fromtimestamp(at_ns // NS, timezone.utc).date().isoformat()


def maintenance(state,marks,event):
    report=mark(state,marks);L=sum(max(v,0) for v in report['position_marks_cents'].values())
    S=-sum(min(v,0) for v in report['position_marks_cents'].values())
    deficits={}
    for name,value in report['position_marks_cents'].items():
        if value<0:
            exact=(1+event.maintenance_short)*abs(value)
            required=-(-exact.numerator//exact.denominator)
            deficits[name]=max(0,required-dict(state.escrow).get(name,0))
    M=Fraction(L,4)+event.maintenance_short*S;E=report['equity_cents']
    return {'report':report,'restriction_deficits_cents':deficits,'equity_requirement_cents':M,
            'buffer_ratio':None if E<=0 else (E-M)/E,
            'passes':E>0 and not any(deficits.values()) and E-M>=event.buffer*E}


def validate_event(event, context):
    require(type(event) is Event and type(event.mark_event) is MarkEvent, 'DRIVER_EVENT_TYPE')
    token(event.id); event_date(event.at_ns)
    require(event.kind in ('EX', 'CLOSE', 'OBSERVATION') and event.instruction in ('TARGET', 'EXIT', 'HOLD')
            and type(event.terminal) is bool, 'DRIVER_EVENT_KIND')
    require(event.mark_event.at_ns == event.at_ns and type(event.marks) is tuple and
            len(event.marks) == len(context.names) and set(dict(event.marks)) == set(context.names), 'DRIVER_MARK_CENSUS')
    for n,p in event.marks: rational(p, positive=True)
    require(type(event.execution_prices) is tuple and len(dict(event.execution_prices)) == len(event.execution_prices)
            and set(dict(event.execution_prices)) <= set(context.names), 'DRIVER_EXECUTION_CENSUS')
    for n,p in event.execution_prices: rational(p, positive=True)
    require(all(p==dict(event.marks)[n] for n,p in event.execution_prices),'DRIVER_EXECUTION_REFERENCE_MARK_JOIN')
    require(event.kind == 'CLOSE' or not event.execution_prices, 'DRIVER_NO_MIDNIGHT_EXECUTION')
    require(type(event.latency_ns) is int and event.latency_ns >= 0 and
            type(event.flat_fee_cents) is int and event.flat_fee_cents >= 0 and
            type(event.fee_bps) is int and 0 <= event.fee_bps <= 10000, 'DRIVER_EXECUTION_PARAMETERS')
    rational(event.maintenance_short); rational(event.buffer)
    require(event.buffer < 1 and event.maintenance_short >= Fraction(3,10), 'DRIVER_RISK_PARAMETERS')
    require(type(event.targets) is tuple and len(dict(event.targets)) == len(event.targets), 'DRIVER_TARGET_CENSUS')
    if event.instruction != 'HOLD':
        token(event.formation)
        require(event.kind == 'CLOSE' and type(event.decision_ns) is int and
                0 <= event.decision_ns < event.at_ns and event.decision_ns + event.latency_ns <= event.at_ns,
                'DRIVER_CAUSAL_INSTRUCTION')
        require(set(dict(event.targets)) == set(context.names), 'DRIVER_TARGET_CENSUS')
        for _,q in event.targets: integer(q, signed=True)
        require(event.instruction != 'EXIT' or all(q == 0 for _,q in event.targets), 'DRIVER_EXIT_TARGET')
        require(sum(q > 0 for _,q in event.targets) <= 1 and sum(q < 0 for _,q in event.targets) <= 1,
                'DRIVER_SIGNED_PAIR_TARGET')
    else:
        require(not event.targets and event.formation is None and event.decision_ns is None, 'DRIVER_HOLD_HAS_NO_TARGET')
    require(type(event.rates) is tuple and all(type(v) is Rate for v in event.rates) and
            len({(v.component,v.name) for v in event.rates}) == len(event.rates), 'DRIVER_RATE_CENSUS')
    require(all(r.name is None or r.name in context.names for r in event.rates), 'DRIVER_RATE_NAME')
    require(type(event.locates) is tuple and all(type(v) is Locate for v in event.locates) and
            len({v.id for v in event.locates}) == len(event.locates), 'DRIVER_LOCATE_CENSUS')
    require(type(event.actions) is tuple and all(type(v) is Action for v in event.actions) and
            len({v.id for v in event.actions}) == len(event.actions), 'DRIVER_ACTION_CENSUS')
    require(type(event.recalled) is tuple and set(event.recalled) <= set(context.names), 'DRIVER_RECALL_NAMES')


class SignedEventDriver:
    """Finite per-event state machine, hosting native callbacks are authoritative.

    next_order returns at most one command; submit is the sole native bridge
    gate. A caller must complete/cancel that order before asking for the next.
    No native order is fabricated by the saved verifier.
    """
    def __init__(self, context, bridge):
        require(type(context) is AccountContext and set(bridge.instruments) == set(context.names) and
                bridge.continue_economic_events and not bridge.events, 'DRIVER_BRIDGE_BINDING')
        self.context=context; self.bridge=bridge; self.initial=bridge.state
        self.records=[]; self.event=None; self.previous=None; self.previous_marks=None
        self.current_marks=None; self.phase_index=0; self.tasks=[]; self.command=None
        self.flatten=None; self.default_ever=False; self.overdue_ever=False
        self.unsupported=False; self.terminal=False; self.history=[]
        self.borrow={n:0 for n in context.names}; self.locate_usage={}; self.formations=set()
        self._seen=set(); self._blocked={}; self._new_short_cents=0; self._active_locate=None
        self._ordinary_allowed=False; self._event_bridge_start=0; self._fill_cursor=0
        self._last_flatten_ns=-1

    def _record(self, kind, **values):
        self.records.append({'sequence':len(self.records),'kind':kind, **deepcopy(values)})

    def _external(self, transition, marks):
        before=self.bridge.state
        reconciliation=self.bridge.apply_external(transition,marks)
        self._record('EXTERNAL',event=self.event.id,transition=transition,reconciliation=reconciliation)
        self.default_ever |= self.bridge.model_survival_failed
        require(transition.before == before, 'DRIVER_EXTERNAL_BEFORE')

    def begin_event(self, event):
        validate_event(event,self.context)
        require(self.event is None and not self.bridge.pending and not self.bridge.halted,
                'DRIVER_EVENT_SERIAL_BARRIER')
        require(event.id not in self._seen and (self.previous is None or event.at_ns > self.previous.at_ns),
                'DRIVER_EVENT_ORDER')
        require(not self.terminal or event.instruction == 'HOLD', 'DRIVER_POSTTERMINAL_RISK')
        self._seen.add(event.id); self.event=event; self._event_bridge_start=len(self.bridge.events)
        self.current_marks=dict(event.marks); self._new_short_cents=0; self._active_locate=None
        self._blocked={}; self.tasks=[]; self.command=None; self.phase_index=0
        self._record('BEGIN',event=event,before=self.bridge.state,previous_event=None if self.previous is None else self.previous.id)
        if event.kind=='EX' and self.previous is not None:
            require(self.current_marks==self.previous_marks,'DRIVER_EX_DOES_NOT_INVENT_NEW_PRICE')
        # Exact elapsed calendar seconds, using saved PREVIOUS bases/rates only.
        if self.previous is not None:
            require((event.at_ns-self.previous.at_ns)%NS == 0,'DRIVER_SUBSECOND_ACCRUAL')
            seconds=(event.at_ns-self.previous.at_ns)//NS
            base_state=self.bridge.state
            for rate in self.previous.rates:
                if rate.component=='BORROW':
                    q=dict(base_state.positions).get(rate.name,0)
                    base=abs(amount_cents(min(q,0),self.previous_marks[rate.name]));kind='MARKED_SHORT_NOTIONAL'
                elif rate.component=='DEBIT_INTEREST':base=max(-base_state.free_cents,0);kind='NEGATIVE_FREE_CASH'
                else:base=max(base_state.free_cents,0);kind='POSITIVE_FREE_CASH'
                stream=self.context.account+':'+rate.component+':'+(rate.name or 'CASH')
                self._external(accrue(self.bridge.state,event.id+':accrue:'+stream,rate.component,base,
                    rate.annual_rate,seconds,rate.provenance,stream_id=stream,base_kind=kind),self.previous_marks)
        for action in sorted(event.actions,key=lambda a:(a.name,a.id)):
            token(action.id);token(action.source_ref)
            try:
                require(action.kind=='CASH_DISTRIBUTION' and action.name in self.context.names and
                        action.currency=='USD' and action.ex_date is not None and action.payment_date is not None,
                        'UNSUPPORTED_ACTION_IDENTITY_CURRENCY_OR_TYPE')
                day(action.ex_date);day(action.payment_date);rational(action.nominal_usd)
                require(action.payment_date>=action.ex_date and event.kind=='EX' and
                        event.at_ns%(86400*NS)==0 and action.ex_date==event_date(event.at_ns), 'UNSUPPORTED_ACTION_CLOCK')
                require(action.historical_known_ns is None or type(action.historical_known_ns) is int and
                        0<=action.historical_known_ns<=event.at_ns,'UNSUPPORTED_ACTION_K')
            except ValueError as exc:
                self.unsupported=True; self._record('UNSUPPORTED_ACTION',event=event.id,action=action,reason=str(exc));continue
            self._external(recognize_distribution(self.bridge.state,action.id,action.name,action.nominal_usd,
                action.ex_date,action.payment_date,action.source_ref,currency=action.currency),self.current_marks)
        if event.actions:
            self._record('VALUATION_LIMITATION',event=event.id,
                status='PRE_EX_CUM_MARK_WITH_NEW_CLAIM',claims=[c.id for c in self.bridge.state.claims if c.paid_at is None],
                marks=event.mark_event,model_equity_cents=mark(self.bridge.state,self.current_marks)['equity_cents'])
        reconciliation=self.bridge.observe_current_book(self.current_marks,event.mark_event)
        self.default_ever |= self.bridge.model_survival_failed
        self._record('MARK',event=event.id,mark_event=event.mark_event,marks=self.current_marks,
                     state=self.bridge.state,reconciliation=reconciliation)
        for name,needed in sorted(maintenance(self.bridge.state,self.current_marks,event)['restriction_deficits_cents'].items()):
            if needed:self._external(top_up(self.bridge.state,event.id+':topup:'+name,name,needed),self.current_marks)
        risk=maintenance(self.bridge.state,self.current_marks,event);report=risk['report']
        requirement=risk['equity_requirement_cents']
        reasons=[]
        if report['equity_cents']<=0:reasons.append('ECONOMIC_NAV_DEFAULT')
        if any(risk['restriction_deficits_cents'].values()):reasons.append('RESTRICTION_SHORTFALL')
        if report['equity_cents']-requirement<event.buffer*report['equity_cents']:reasons.append('EQUITY_BUFFER_BREACH')
        if event.recalled:reasons.append('RECALL')
        if self.bridge.economic_execution_breach:reasons.append('RECONCILED_EXECUTION_BREACH')
        if reasons and self.flatten is None:
            self.flatten={'observed_ns':event.at_ns,'eligible_after_ns':event.at_ns+event.latency_ns,
                          'event':event.id,'reasons':reasons}
            self._record('FLATTEN_QUEUED',event=event.id,flatten=self.flatten,report=report,requirement=requirement)
        if event.instruction!='HOLD':
            require(event.formation not in self.formations,'DRIVER_REUSED_FORMATION')
            self.formations.add(event.formation)
        self._forced_now=bool(self.flatten is not None and event.kind=='CLOSE' and
            event.at_ns>self.flatten['observed_ns'] and event.at_ns>=self.flatten['eligible_after_ns'])
        self._ordinary_allowed=(event.kind=='CLOSE' and event.instruction!='HOLD' and not self.unsupported and
            (event.instruction=='EXIT' or not self.default_ever and self.flatten is None and
             event.decision_ns>self._last_flatten_ns))
        # A causally predeclared EXIT is an eligible full flatten too. Its due
        # payment checkpoint follows the cover/sale/retry, never precedes EXIT.
        if self._ordinary_allowed and event.instruction=='EXIT':self._forced_now=True
        if event.instruction!='HOLD' and not self._ordinary_allowed:
            self._record('INSTRUCTION_BLOCKED',event=event.id,instruction=event.instruction,
                         default_ever=self.default_ever,pending_flatten=self.flatten,unsupported=self.unsupported)

    def _deltas(self,forced):
        targets={n:0 for n in self.context.names} if forced else dict(self.event.targets)
        positions=dict(self.bridge.state.positions);out=[]
        for n in self.context.names:
            q=positions.get(n,0);target=targets[n]
            if q<0 and target>q:out.append((n,'BUY',min(-q,target-q)))
            if q>0 and target<q:out.append((n,'SELL',min(q,q-target)))
        return out

    def _tasks_for(self,phase):
        if phase.startswith('FORCED'):
            if not self._forced_now:return []
            forced=True
        else:
            if not self._ordinary_allowed:return []
            if self.event.instruction=='EXIT':return []  # already consumed by full-flatten phases
            forced=self.event.instruction=='EXIT'
        if phase.endswith('RETRY'):
            return [(n,'BUY',min(q,-dict(self.bridge.state.positions).get(n,0)),forced)
                    for n,q in sorted(self._blocked.get(phase.split('_')[0],{}).items())
                    if dict(self.bridge.state.positions).get(n,0)<0]
        if phase.endswith('COVERS') or phase.endswith('SALES'):
            return [(n,s,q,forced) for n,s,q in self._deltas(phase.startswith('FORCED'))
                    if s==('BUY' if phase.endswith('COVERS') else 'SELL')]
        return []

    def _payment(self):
        if self.event.kind!='CLOSE':return
        date=event_date(self.event.at_ns)
        for claim in sorted(self.bridge.state.claims,key=lambda c:(c.payment_date,c.name,c.id)):
            if claim.paid_at is None and claim.payment_date<=date:
                t=pay_claim(self.bridge.state,self.event.id+':pay:'+claim.id,claim.id,date)
                self._external(t,self.current_marks)
                if t.status!='APPLIED':self._overdue('CLAIM',claim.id,claim.cents)
        for stream in sorted(self.bridge.state.accruals,key=lambda a:a.stream_id):
            if stream.recognized_cents>stream.settled_cents:
                t=settle_accrual(self.bridge.state,self.event.id+':settle:'+stream.stream_id,stream.stream_id)
                self._external(t,self.current_marks)
                if t.status!='APPLIED':self._overdue('ACCRUAL',stream.stream_id,stream.recognized_cents-stream.settled_cents)

    def _overdue(self,kind,identity,cents):
        self.overdue_ever=True
        self._record('MODEL_OVERDUE_PAYMENT_EPISODE',event=self.event.id,at_ns=self.event.at_ns,
                     obligation_kind=kind,identity=identity,requested_cents=cents,
                     scope='MODEL_FUNDING_FAILURE_NOT_LEGAL_BROKER_DEFAULT')

    def _new_risk(self,phase):
        if not self._ordinary_allowed or self.event.instruction!='TARGET' or self.flatten is not None or self.default_ever:
            return []
        targets=dict(self.event.targets);positions=dict(self.bridge.state.positions)
        if any(positions.get(n,0)*targets[n]<0 for n in self.context.names):
            self._record('PAIR_CANCELLED',event=self.event.id,reason='UNFINISHED_REVERSAL_REDUCTION');return []
        shorts=[(n,abs(t)-abs(min(positions.get(n,0),0))) for n,t in targets.items() if t<0]
        if phase=='NEW_SHORT':
            if not shorts or shorts[0][1]<=0:
                self._record('PAIR_CANCELLED',event=self.event.id,reason='NO_ADDED_SHORT_LOCATE_AND_MATCHING_NOTIONAL');return []
            n,q=shorts[0]
            candidates=[v for v in self.event.locates if (v.path,v.account,v.formation,v.issuer,v.side,v.execution_event)==
                (self.context.path,self.context.account,self.event.formation,n,'SHORT',self.event.id)]
            valid=(len(candidates)==1 and candidates[0].success and candidates[0].cap>=q and
                   candidates[0].id not in self.locate_usage and n in dict(self.event.execution_prices))
            if not valid:
                self._record('PAIR_CANCELLED',event=self.event.id,reason='MISSING_FAILED_EXPIRED_OR_REUSED_LOCATE',
                             frozen_short_quantity=q,candidates=candidates);return []
            v=candidates[0];self._active_locate=v
            self.locate_usage[v.id]={'token':v,'reserved':q,'filled':0,'expired':False,'orders':[]}
            self._record('LOCATE_RESERVED',event=self.event.id,token=v,frozen_short_quantity=q)
            return [(n,'SELL',q,False)]
        if self._active_locate is None or not self._new_short_cents:return []
        out=[]
        for n,t in sorted(targets.items()):
            if t>0:
                q=max(0,t-max(positions.get(n,0),0));px=dict(self.event.execution_prices).get(n)
                if px is not None:q=min(q,int(Fraction(self._new_short_cents,100)/px))
                out.append((n,'BUY',q,False))
        return out

    def next_order(self):
        require(self.event is not None and not self.bridge.pending and not self.bridge.halted, 'DRIVER_ORDER_BARRIER')
        require(self.command is None,'DRIVER_UNCONSUMED_COMMAND')
        while self.phase_index<len(PHASES):
            phase=PHASES[self.phase_index]
            if not hasattr(self,'_entered') or self._entered!=phase:
                self._entered=phase
                self._record('PHASE',event=self.event.id,phase=phase)
                if phase=='PAYMENT':
                    if self._forced_now and not any(q for _,q in self.bridge.state.positions):
                        self._last_flatten_ns=self.event.at_ns;self.flatten=None
                        self.bridge.economic_execution_breach=False
                        self._record('FLATTEN_COMPLETED',event=self.event.id,at_ns=self.event.at_ns)
                    self._payment()
                self.tasks=self._new_risk(phase) if phase.startswith('NEW_') else self._tasks_for(phase) if phase!='FINAL' else []
            while self.tasks:
                n,side,q,forced=self.tasks.pop(0)
                if q<=0:continue
                price=dict(self.event.execution_prices).get(n)
                if price is None:
                    self._record('EXECUTION_UNAVAILABLE',event=self.event.id,phase=phase,name=n,quantity=q);continue
                locate=self._active_locate if phase=='NEW_SHORT' else None
                # Pure proposals for clipping never install state or latch actual default.
                frozen=q
                def preview(qty):
                    p=propose_fill(self.bridge.state,'preview:'+self.event.id+':'+phase+':'+n,n,side,qty,price,
                        fee_for(self.event,qty,price),marks=self.current_marks,forced=forced,
                        located_cap=None if locate is None else locate.cap,
                        locate_provenance=None if locate is None else locate.provenance)
                    if phase.startswith('NEW_') and p.status=='ADMITTED_PROPOSAL_NOT_EXECUTION':
                        from dataclasses import replace
                        hypothetical=p.after
                        for name,need in sorted(maintenance(hypothetical,self.current_marks,self.event)['restriction_deficits_cents'].items()):
                            if need:hypothetical=top_up(hypothetical,'preview-topup:'+self.event.id+':'+name,name,need).after
                        if not maintenance(hypothetical,self.current_marks,self.event)['passes']:
                            p=replace(p,status='REJECTED_DISCRETIONARY_MAINTENANCE')
                    return p
                proposal=preview(q)
                if proposal.status!='ADMITTED_PROPOSAL_NOT_EXECUTION' and phase.startswith('NEW_'):
                    # Finite integer search, source-independent. This is valid for
                    # same-side risk additions at positive fixed execution/mark/fee.
                    lo,hi=0,q
                    while lo<hi:
                        mid=(lo+hi+1)//2
                        if preview(mid).status=='ADMITTED_PROPOSAL_NOT_EXECUTION':lo=mid
                        else:hi=mid-1
                    q=lo
                    if q:proposal=preview(q)
                if q==0 or proposal.status!='ADMITTED_PROPOSAL_NOT_EXECUTION':
                    self._record('PROPOSAL_BLOCKED',event=self.event.id,phase=phase,name=n,side=side,
                                 frozen_quantity=frozen,proposal=proposal)
                    if side=='BUY' and dict(self.bridge.state.positions).get(n,0)<0 and not phase.endswith('RETRY'):
                        self._blocked.setdefault(phase.split('_')[0],{})[n]=q
                    continue
                intent=self.event.id+':'+phase+':'+n
                self.command=OrderRequest(intent,self.event.id,phase,n,side,q,price,fee_for(self.event,q,price),forced,
                    None if locate is None else locate.id,None if locate is None else locate.cap)
                self._record('ORDER_COMMAND',event=self.event.id,command=self.command,frozen_quantity=frozen,
                             actual_prestate=self.bridge.state,proposal=proposal)
                return self.command
            self.phase_index+=1
        self._finish_event();return None

    def submit(self,order):
        c=self.command
        require(c is not None and self.event is not None,'DRIVER_NO_COMMAND')
        # Exact order identity/type is checked by the accepted bridge. Also bind
        # the command's side/quantity; no caller-supplied oversized native order.
        from nautilus_trader.model.enums import OrderSide
        require(str(order.instrument_id)==str(self.bridge.instruments[c.name]) and whole(order.quantity)==c.quantity and
            order.side==(OrderSide.BUY if c.side=='BUY' else OrderSide.SELL),'DRIVER_NATIVE_COMMAND_BINDING')
        self._record('SUBMIT',event=self.event.id,command=c,order_id=str(order.client_order_id))
        if c.locate_id is not None:self.locate_usage[c.locate_id]['orders'].append(str(order.client_order_id))
        self.bridge.propose_and_submit(c.intent_id,order,c.price,c.fee_cents,self.current_marks,
            mark_event=MarkEvent(c.intent_id+':admission-mark',self.event.at_ns,self.event.mark_event.identities),
            located_cap=c.located_cap,locate_provenance=None if c.locate_id is None else self._active_locate.provenance,
            forced=c.forced)
        # command stays attached until actual terminal callback, including partials.

    def on_fill(self,fill):
        if self.command is None:
            # An unsolicited/late actual callback must reach the accepted
            # bridge's raw-execution error custody before the host is halted.
            self.bridge.record_fill(fill,self.current_marks or self.previous_marks)
            require(False,'DRIVER_UNEXPECTED_FILL_COMMAND')
        c=self.command;before=self.bridge.state
        result=self.bridge.record_fill(fill,self.current_marks)
        q=result.operands['actual_quantity'];old=dict(before.positions).get(c.name,0)
        if c.side=='SELL' and old<=0:
            require(c.locate_id is not None,'DRIVER_ACTUAL_SHORT_WITHOUT_LOCATE')
            use=self.locate_usage[c.locate_id];use['filled']+=q
            require(not use['expired'] and use['filled']<=use['reserved'],'DRIVER_LOCATE_CONSUMPTION')
            self.borrow[c.name]+=q;self._new_short_cents+=result.operands['settled_notional_cents']
        elif c.side=='BUY' and old<0:self.borrow[c.name]-=q
        self.default_ever |= self.bridge.model_survival_failed
        self._record('FILL',event=self.event.id,command=c,order_id=str(fill.client_order_id),trade_id=str(fill.trade_id),
                     actual_fill=deepcopy(next(v['actual_fill'] for v in reversed(self.bridge.events)
                                              if v['kind']=='CONFIRMED_NATIVE_FILL')),
                     transition=result,borrow=dict(self.borrow),locate_usage=deepcopy(self.locate_usage),
                     reconciliation=self.bridge.reconcile(self.current_marks))
        return result

    def on_terminal(self,order_id,status):
        require(self.command is not None,'DRIVER_UNEXPECTED_TERMINAL')
        self.bridge.record_terminal(order_id,status)
        self._record('TERMINAL_ORDER',event=self.event.id,command=self.command,order_id=order_id,status=status)
        self.command=None
        # A stress160% requirement is distinct from core150% initial escrow.
        # No asynchronous topup while fills of this order remain outstanding.
        for name,need in sorted(maintenance(self.bridge.state,self.current_marks,self.event)['restriction_deficits_cents'].items()):
            if need:self._external(top_up(self.bridge.state,self.event.id+':post-order-topup:'+order_id+':'+name,name,need),self.current_marks)

    def _finish_event(self):
        require(not self.bridge.pending and self.command is None,'DRIVER_FINAL_PENDING')
        for v in self.event.locates:
            if v.id in self.locate_usage and self.locate_usage[v.id]['token'].execution_event==self.event.id:
                self.locate_usage[v.id]['expired']=True
                self._record('LOCATE_EXPIRED',event=self.event.id,token=v,usage=self.locate_usage[v.id])
        require(all(self.borrow[n]==max(-dict(self.bridge.state.positions).get(n,0),0) for n in self.context.names),
                'DRIVER_BORROW_POSITION_JOIN')
        self.terminal |= self.event.terminal
        result={'event':self.event.id,'state':self.bridge.state,'default_ever':self.default_ever,
                'overdue_ever':self.overdue_ever,'unsupported':self.unsupported,'pending_flatten':deepcopy(self.flatten),
                'borrow':dict(self.borrow),'locate_usage':deepcopy(self.locate_usage),
                'terminal_unresolved_positions':bool(self.terminal and any(q for _,q in self.bridge.state.positions)),
                'pending_claims':[c.id for c in self.bridge.state.claims if c.paid_at is None],
                'reconciliation':self.bridge.reconcile(self.current_marks),
                'bridge_events':deepcopy(self.bridge.events[self._event_bridge_start:])}
        self._record('END',**result);self.history.append(deepcopy(result))
        self.previous=self.event;self.previous_marks=self.current_marks;self.event=None;self._entered=None

    def packet(self):
        require(self.event is None and not self.bridge.pending,'DRIVER_PACKET_INCOMPLETE_EVENT')
        return {'schema':'polar.private-signed-events/1','context':self.context,'initial_state':self.initial,
                'native_instruments':{n:str(i) for n,i in self.bridge.instruments.items()},
                'native_account_id':str(self.bridge._account().id),
                'records':deepcopy(self.records),'final_state':self.bridge.state,
                'native_submission_count':self.bridge.native_submission_count,
                'execution_authority':False,'scope':'SUPPLIED_SINGLE_PATH_COMPONENT_NOT_FINANCIAL_ACCEPTANCE'}

    def failure_evidence(self,error):
        """Retain a technical prefix/unknown effect; never relabel it completed.

        The completed-packet verifier intentionally refuses this shape. A host
        must archive these bytes before disposing its owned native account.
        """
        try:
            observed={'positions':deepcopy(self.bridge._positions()),
                'native_account':self.bridge._account().exact_marked_trading_equity(
                    {str(i):self.current_marks[n] for n,i in self.bridge.instruments.items()}),
                'scope':'OBSERVED_PARTIAL_NOT_RECONCILED_OR_COMPLETED'}
        except Exception as observation_error:
            observed={'status':'UNAVAILABLE','reason':str(observation_error)}
        return {'schema':'polar.private-signed-event-partial/1','status':'TECHNICAL_UNFINALIZED',
            'context':self.context,'initial_state':self.initial,'records':deepcopy(self.records),
            'active_event':self.event,'active_command':self.command,'core_state':self.bridge.state,
            'native_instruments':{n:str(i) for n,i in self.bridge.instruments.items()},
            'bridge_events':deepcopy(self.bridge.events),'pending':deepcopy(self.bridge.pending),
            'technical_halt':self.bridge.halted,'error_type':type(error).__name__,'reason':str(error),
            'actual_native_observation':observed,
            'execution_authority':False}
