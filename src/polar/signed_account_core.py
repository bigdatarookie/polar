"""Pure signed raw-share research accounting; no engine, source or Service calls.

Every operation returns immutable state plus consumed transition evidence.
Scheduling, price selection and actual broker credit/locate are outside this core.
"""
from dataclasses import dataclass, replace
from copy import deepcopy
from fractions import Fraction

from .distribution_claims import half_even, day, token


class SignedAccountError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise SignedAccountError(reason)


def integer(value, *, signed=False):
    require(type(value) is int and abs(value) <= 10**30 and (signed or value >= 0), 'SIGNED_INTEGER')
    return value


def rational(value, *, positive=False):
    require(type(value) in (Fraction, int) and type(value) is not bool, 'SIGNED_RATIONAL')
    value = Fraction(value)
    require(abs(value.numerator) <= 10**60 and value.denominator <= 10**30
            and (value > 0 if positive else value >= 0), 'SIGNED_RATIONAL')
    return value


def amount_cents(shares, price):
    """Exact signed multiplication then existing HALF_EVEN primitive, once."""
    integer(shares, signed=True); price = rational(price, positive=True)
    return half_even(shares * price * 100)


def magnitude_target(notional_usd, price):
    require(type(notional_usd) in (Fraction, int), 'SIGNED_RATIONAL')
    price = rational(price, positive=True)
    size = abs(Fraction(notional_usd)) / price
    q = size.numerator // size.denominator
    return integer(-q if notional_usd < 0 else q, signed=True)


@dataclass(frozen=True)
class Claim:
    id: str
    name: str
    kind: str
    exact_cents: Fraction
    cents: int
    ex_date: str
    payment_date: str
    source_ref: str
    paid_at: str | None = None

    def __post_init__(self):
        token(self.id); token(self.name); token(self.source_ref)
        require(self.kind in ('RECEIVABLE', 'PAYABLE'), 'SIGNED_CLAIM_KIND')
        rational(self.exact_cents); integer(self.cents)
        require(self.cents == half_even(self.exact_cents), 'SIGNED_CLAIM_ROUNDING')
        day(self.ex_date); day(self.payment_date)
        require(self.payment_date >= self.ex_date, 'SIGNED_CLAIM_DATE')
        if self.paid_at is not None:
            day(self.paid_at)
            require(self.paid_at >= self.payment_date, 'SIGNED_CLAIM_DATE')


@dataclass(frozen=True)
class Accrual:
    component: str
    stream_id: str
    base_kind: str
    provenance: str
    exact_cents: Fraction = Fraction(0)
    recognized_cents: int = 0
    settled_cents: int = 0

    def __post_init__(self):
        require(self.component in ('BORROW', 'DEBIT_INTEREST', 'REBATE', 'FREE_CASH_INTEREST'), 'SIGNED_COMPONENT')
        token(self.stream_id); token(self.provenance)
        expected={'BORROW':'MARKED_SHORT_NOTIONAL','DEBIT_INTEREST':'NEGATIVE_FREE_CASH',
                  'REBATE':'DECLARED_REBATE_BASE','FREE_CASH_INTEREST':'POSITIVE_FREE_CASH'}
        require(self.base_kind == expected[self.component], 'SIGNED_ACCRUAL_BASE_KIND')
        rational(self.exact_cents); integer(self.recognized_cents); integer(self.settled_cents)
        require(self.recognized_cents == half_even(self.exact_cents)
                and self.settled_cents <= self.recognized_cents, 'SIGNED_ACCRUAL_RECONCILIATION')

    @property
    def is_income(self):
        return self.component in ('REBATE', 'FREE_CASH_INTEREST')


@dataclass(frozen=True)
class State:
    free_cents: int
    positions: tuple[tuple[str, int], ...] = ()
    escrow: tuple[tuple[str, int], ...] = ()
    claims: tuple[Claim, ...] = ()
    accruals: tuple[Accrual, ...] = ()
    used_ids: tuple[str, ...] = ()

    def __post_init__(self):
        integer(self.free_cents, signed=True)
        for pairs, signed in ((self.positions, True), (self.escrow, False)):
            require(type(pairs) is tuple and all(type(p) is tuple and len(p) == 2 for p in pairs), 'SIGNED_STATE')
            for name, number in pairs:
                token(name); integer(number, signed=signed)
            require(len(dict(pairs)) == len(pairs), 'SIGNED_STATE_DUPLICATE')
        positions, escrow = dict(self.positions), dict(self.escrow)
        require(all(positions.get(n, 0) < 0 or r == 0 for n, r in escrow.items()), 'SIGNED_ESCROW_WITHOUT_SHORT')
        require(type(self.claims) is tuple and all(type(c) is Claim for c in self.claims)
                and len({c.id for c in self.claims}) == len(self.claims), 'SIGNED_CLAIMS')
        require(type(self.accruals) is tuple and all(type(a) is Accrual for a in self.accruals)
                and len({a.stream_id for a in self.accruals}) == len(self.accruals), 'SIGNED_ACCRUALS')
        require(type(self.used_ids) is tuple, 'SIGNED_STATE')
        for key in self.used_ids: token(key)
        require(len(set(self.used_ids)) == len(self.used_ids), 'SIGNED_DUPLICATE_ID')
        require(all(c.id in self.used_ids for c in self.claims), 'SIGNED_CLAIM_ID_BINDING')

    @property
    def restricted_cents(self):
        return sum(r for _, r in self.escrow)

    @property
    def receivables_cents(self):
        return sum(c.cents for c in self.claims if c.kind == 'RECEIVABLE' and c.paid_at is None) + sum(
            a.recognized_cents - a.settled_cents for a in self.accruals if a.is_income)

    @property
    def payables_cents(self):
        return sum(c.cents for c in self.claims if c.kind == 'PAYABLE' and c.paid_at is None) + sum(
            a.recognized_cents - a.settled_cents for a in self.accruals if not a.is_income)


@dataclass(frozen=True)
class Transition:
    before: State
    after: State
    event_id: str
    kind: str
    operands: dict
    status: str = 'APPLIED'


def transition(state, event_id, kind, operands, **changes):
    require(type(state) is State, 'SIGNED_STATE')
    token(event_id); require(event_id not in state.used_ids, 'SIGNED_DUPLICATE_ID')
    after = replace(state, used_ids=state.used_ids + (event_id,), **changes)
    return Transition(state, after, event_id, kind, deepcopy(operands))


def _blocked(state, event_id, kind, operands, status):
    token(event_id); require(event_id not in state.used_ids, 'SIGNED_DUPLICATE_ID')
    return Transition(state, state, event_id, kind, deepcopy(operands), status)


def _funding(mode, identity):
    require(mode in ('NO_CREDIT', 'HYPOTHETICAL_MANDATORY_FUNDING'), 'SIGNED_FUNDING_MODE')
    if mode == 'HYPOTHETICAL_MANDATORY_FUNDING':
        token(identity)
    else:
        require(identity is None, 'SIGNED_FUNDING_IDENTITY_WITHOUT_MODE')


def propose_fill(state, fill_id, name, side, quantity, price, fee_cents, *, forced=False,
         located_cap=None, locate_provenance=None, funding_mode='NO_CREDIT',
         funding_assumption=None, marks=None):
    """Proposed permitted fill; blocked transitions do not pretend execution."""
    require(type(state) is State, 'SIGNED_STATE'); token(name)
    integer(quantity); integer(fee_cents); price = rational(price, positive=True)
    require(side in ('BUY', 'SELL') and type(forced) is bool, 'SIGNED_FILL')
    require(quantity > 0 or fee_cents == 0, 'SIGNED_ZERO_FILL_FEE')
    _funding(funding_mode, funding_assumption)
    q = dict(state.positions).get(name, 0); escrow = dict(state.escrow)
    free = state.free_cents; notional = amount_cents(quantity, price)
    release = own = 0; admission = None; failed = []
    kind = 'ZERO_FILL'
    positions = dict(state.positions); positions[name] = q + (quantity if side == 'BUY' else -quantity)
    if quantity:
        if side == 'BUY' and q < 0:
            require(quantity <= -q, 'SIGNED_REVERSAL_REQUIRES_SPLIT')
            kind = 'COVER'; old_escrow = escrow.get(name, 0)
            release = old_escrow if quantity == -q else half_even(Fraction(old_escrow * quantity, -q))
            escrow[name] = old_escrow - release
            free += release - notional - fee_cents
            if free < 0 and not (forced and funding_mode == 'HYPOTHETICAL_MANDATORY_FUNDING'):
                failed.append('SETTLEMENT_BLOCKED_INSUFFICIENT_FREE_CASH')
        elif side == 'SELL' and q <= 0:
            kind = 'SHORT_INCREASE'; integer(located_cap)
            require(quantity <= located_cap, 'SIGNED_LOCATE_CAP'); token(locate_provenance)
            require(not forced and funding_mode == 'NO_CREDIT', 'SIGNED_DISCRETIONARY_FUNDING_MODE')
            require(type(marks) is dict and name in marks, 'SIGNED_OPENING_MARKS_REQUIRED')
            liability = abs(amount_cents(positions[name], marks[name]))
            required = -(-(3 * liability) // 2)  # ceil exact 1.5 * marked cents
            credited = escrow.get(name, 0) + notional
            own = max(required - credited, 0)
            free -= own + fee_cents
            escrow[name] = credited + own
        elif side == 'BUY':
            kind = 'LONG_BUY'; free -= notional + fee_cents
            require(not forced and funding_mode == 'NO_CREDIT', 'SIGNED_DISCRETIONARY_FUNDING_MODE')
        else:
            kind = 'LONG_SALE'; require(quantity <= q, 'SIGNED_REVERSAL_REQUIRES_SPLIT')
            free += notional - fee_cents
    proposed = replace(state, free_cents=free, positions=tuple(sorted(positions.items())), escrow=tuple(sorted(escrow.items())))
    if kind in ('LONG_BUY', 'SHORT_INCREASE'):
        require(type(marks) is dict, 'SIGNED_OPENING_MARKS_REQUIRED')
        admission = mark(proposed, marks)
        if free < 0: failed.append('NEGATIVE_FREE_CASH')
        if admission['initial_equity_excess_cents'] < 0: failed.append('INITIAL_EQUITY_REQUIREMENT')
        if any(x['initial_excess_cents'] < 0 for x in admission['per_name_restriction'].values()):
            failed.append('INITIAL_PER_NAME_RESTRICTION')
    operands = {'name': name, 'side': side, 'proposed_permitted_fill_quantity': quantity,
        'price_usd': price, 'exact_notional_cents': quantity * price * 100,
        'settled_notional_cents': notional, 'rounding_residual_cents': Fraction(notional) - quantity * price * 100,
        'fee_cents': fee_cents, 'released_escrow_cents': release, 'own_collateral_cents': own,
        'located_cap': located_cap, 'locate_provenance': locate_provenance, 'post_fill_marks': marks,
        'post_fill_admission': admission, 'failed_tests': failed,
        'forced': forced, 'funding_mode': funding_mode, 'funding_assumption': funding_assumption,
        'funding_shortfall_cents': max(-free, 0),
        'negative_free_cash_delta_cents': max(-free, 0) - max(-state.free_cents, 0)}
    if failed:
        return _blocked(state, fill_id, kind, operands,
                        'SETTLEMENT_BLOCKED_INSUFFICIENT_FREE_CASH' if kind == 'COVER' else 'REJECTED_DISCRETIONARY_ADMISSION')
    return replace(transition(state, fill_id, kind, operands, free_cents=free,
        positions=tuple(sorted(positions.items())), escrow=tuple(sorted(escrow.items()))), status='ADMITTED_PROPOSAL_NOT_EXECUTION')


def top_up(state, event_id, name, requested_cents):
    token(name); integer(requested_cents)
    require(dict(state.positions).get(name, 0) < 0, 'SIGNED_TOPUP_WITHOUT_SHORT')
    moved = min(max(state.free_cents, 0), requested_cents)
    escrow = dict(state.escrow); escrow[name] = escrow.get(name, 0) + moved
    return transition(state, event_id, 'COLLATERAL_TOPUP', {'name': name, 'requested_cents': requested_cents,
        'transferred_cents': moved, 'residual_requirement_cents': requested_cents - moved},
        free_cents=state.free_cents - moved, escrow=tuple(sorted(escrow.items())))


def recognize_distribution(state, event_id, name, nominal_usd, ex_date, payment_date, source_ref, *, currency='USD'):
    token(name); nominal_usd = rational(nominal_usd)
    require(currency == 'USD', 'SIGNED_UNSUPPORTED_CURRENCY')
    q = dict(state.positions).get(name, 0)
    exact = abs(q) * nominal_usd * 100; cents = half_even(exact)
    claim = Claim(event_id, name, 'PAYABLE' if q < 0 else 'RECEIVABLE', exact, cents, ex_date, payment_date, source_ref)
    return transition(state, event_id, 'EX_ENTITLEMENT', {'name': name, 'pre_entitlement_shares': q,
        'nominal_usd_per_share': nominal_usd, 'exact_cents': exact, 'rounded_cents': cents,
        'residual_cents': Fraction(cents) - exact, 'source_ref': source_ref, 'currency': currency},
        claims=state.claims + (claim,))


def pay_claim(state, event_id, claim_id, at_date, *, funding_mode='NO_CREDIT', funding_assumption=None):
    day(at_date); _funding(funding_mode, funding_assumption)
    matches = [c for c in state.claims if c.id == claim_id]
    require(len(matches) == 1 and matches[0].paid_at is None, 'SIGNED_UNKNOWN_OR_PAID_CLAIM')
    claim = matches[0]; require(at_date >= claim.payment_date, 'SIGNED_PAYMENT_BEFORE_DUE')
    delta = claim.cents if claim.kind == 'RECEIVABLE' else -claim.cents
    if delta < 0 and state.free_cents + delta < 0 and funding_mode == 'NO_CREDIT':
        return _blocked(state, event_id, 'CLAIM_PAYMENT', {'claim_id': claim_id, 'requested_cents': claim.cents},
                        'SETTLEMENT_BLOCKED_INSUFFICIENT_FREE_CASH')
    return transition(state, event_id, 'CLAIM_PAYMENT', {'claim_id': claim_id, 'at_date': at_date,
        'funding_mode': funding_mode, 'funding_assumption': funding_assumption,
        'negative_free_cash_delta_cents': max(-(state.free_cents + delta), 0) - max(-state.free_cents, 0),
        'cash_delta_cents': delta, 'funding_shortfall_cents': max(-(state.free_cents + delta), 0)},
        free_cents=state.free_cents + delta,
        claims=tuple(replace(c, paid_at=at_date) if c.id == claim_id else c for c in state.claims))


def accrue(state, event_id, component, start_base_cents, annual_rate, elapsed_seconds, provenance, *, stream_id, base_kind):
    """Caller binds prior event's base and duration; no rate/date inference here."""
    integer(start_base_cents); integer(elapsed_seconds); annual_rate = rational(annual_rate); token(provenance)
    seed=Accrual(component,stream_id,base_kind,provenance)
    old = next((a for a in state.accruals if a.stream_id == stream_id), seed)
    require((old.component,old.base_kind,old.provenance)==(component,base_kind,provenance), 'SIGNED_STREAM_BINDING_CHANGE')
    if component=='DEBIT_INTEREST':require(start_base_cents==max(-state.free_cents,0),'SIGNED_CASH_BASE')
    if component=='FREE_CASH_INTEREST':require(start_base_cents==max(state.free_cents,0),'SIGNED_CASH_BASE')
    increment = Fraction(start_base_cents) * annual_rate * elapsed_seconds / (365 * 86400)
    exact = old.exact_cents + increment; rounded = half_even(exact)
    current = replace(old, exact_cents=exact, recognized_cents=rounded)
    accruals = tuple(sorted((a for a in state.accruals if a.stream_id != stream_id), key=lambda a: a.stream_id)) + (current,)
    return transition(state, event_id, 'ACCRUAL_RECOGNITION', {'component': component, 'stream_id': stream_id, 'base_kind': base_kind,
        'previous_event_start_base_cents': start_base_cents, 'annual_scenario_rate': annual_rate,
        'elapsed_civil_seconds': elapsed_seconds, 'year_seconds': 365 * 86400,
        'increment_exact_cents': increment, 'cumulative_exact_cents': exact,
        'recognition_delta_cents': rounded - old.recognized_cents,
        'cumulative_rounding_residual_cents': Fraction(rounded) - exact, 'provenance': provenance},
        accruals=accruals)


def settle_accrual(state, event_id, stream_id, *, funding_mode='NO_CREDIT', funding_assumption=None):
    _funding(funding_mode, funding_assumption)
    selected = next((a for a in state.accruals if a.stream_id == stream_id), None)
    require(selected is not None, 'SIGNED_UNKNOWN_ACCRUAL')
    amount = selected.recognized_cents - selected.settled_cents
    delta = amount if selected.is_income else -amount
    if delta < 0 and state.free_cents + delta < 0 and funding_mode == 'NO_CREDIT':
        return _blocked(state, event_id, 'ACCRUAL_SETTLEMENT', {'component': selected.component, 'stream_id': stream_id, 'requested_cents': amount},
                        'SETTLEMENT_BLOCKED_INSUFFICIENT_FREE_CASH')
    return transition(state, event_id, 'ACCRUAL_SETTLEMENT', {'component': selected.component, 'stream_id': stream_id,
        'funding_mode': funding_mode, 'funding_assumption': funding_assumption,
        'funding_shortfall_cents': max(-(state.free_cents + delta), 0),
        'negative_free_cash_delta_cents': max(-(state.free_cents + delta), 0) - max(-state.free_cents, 0),
        'settled_cents': amount, 'cash_delta_cents': delta}, free_cents=state.free_cents + delta,
        accruals=tuple(replace(a, settled_cents=a.recognized_cents) if a.stream_id == stream_id else a for a in state.accruals))


def mark(state, prices):
    """Signed equity and separate rational constraints; no metric evaluation."""
    require(type(prices) is dict, 'SIGNED_MARKS')
    marks = {}
    for name, q in state.positions:
        require(q == 0 or name in prices, 'SIGNED_MISSING_MARK')
        marks[name] = amount_cents(q, prices[name]) if q else 0
    long = sum(v for v in marks.values() if v > 0); short = -sum(v for v in marks.values() if v < 0)
    equity = state.free_cents + state.restricted_cents + sum(marks.values()) + state.receivables_cents - state.payables_cents
    restriction_initial = Fraction(3, 2) * short; restriction_maintenance = Fraction(13, 10) * short
    equity_requirement = Fraction(1, 4) * long + Fraction(3, 10) * short
    initial_equity = long + Fraction(1, 2) * short
    per_name = {name: {'initial_cents': Fraction(3, 2) * abs(v),
                       'initial_excess_cents': dict(state.escrow).get(name, 0) - Fraction(3, 2) * abs(v),
                       'maintenance_cents': Fraction(13, 10) * abs(v),
                       'maintenance_excess_cents': dict(state.escrow).get(name, 0) - Fraction(13, 10) * abs(v)}
                for name, v in marks.items() if v < 0}
    return {'equity_cents': equity, 'deficit_cents': max(-equity, 0),
        'status': 'DEFAULT' if equity <= 0 else 'POSITIVE_EQUITY', 'survival': equity > 0,
        'positive_nav_metrics': 'INAPPLICABLE' if equity <= 0 else 'DOMAIN_ELIGIBLE_NOT_COMPUTED',
        'metric_reason': 'NONPOSITIVE_NAV' if equity <= 0 else None, 'position_marks_cents': marks,
        'free_cents': state.free_cents, 'restricted_cents': state.restricted_cents,
        'receivables_cents': state.receivables_cents, 'payables_cents': state.payables_cents,
        'initial_restriction_cents': restriction_initial, 'maintenance_restriction_cents': restriction_maintenance,
        'initial_restriction_excess_cents': state.restricted_cents - restriction_initial,
        'maintenance_restriction_excess_cents': state.restricted_cents - restriction_maintenance,
        'per_name_restriction': per_name, 'initial_equity_requirement_cents': initial_equity,
        'initial_equity_excess_cents': equity - initial_equity,
        'equity_requirement_cents': equity_requirement, 'equity_excess_cents': equity - equity_requirement,
        'free_funding_shortfall_cents': max(-state.free_cents, 0)}


def record_confirmed_fill(state, fill_id, name, side, quantity, price, fee_cents, marks, *,
                          execution_provenance, located_cap=None, locate_provenance=None,
                          funding_mode='NO_CREDIT', funding_assumption=None):
    """Record supplied confirmed execution despite economic admission breaches.

    Missing/malformed required execution data is an error, not a reconstructed
    fill. Caller retains that immutable input/error; this core cannot archive it.
    """
    require(type(state) is State and type(marks) is dict, 'SIGNED_STATE')
    token(name); token(execution_provenance); integer(quantity); integer(fee_cents)
    price=rational(price,positive=True); _funding(funding_mode,funding_assumption)
    require(side in ('BUY','SELL') and (quantity>0 or fee_cents==0),'SIGNED_FILL')
    positions=dict(state.positions);escrow=dict(state.escrow);q=positions.get(name,0)
    free=state.free_cents;notional=amount_cents(quantity,price);release=own=0;breaches=[]
    if quantity and side=='BUY' and q<0:
        require(quantity<=-q,'SIGNED_REVERSAL_REQUIRES_SPLIT')
        held=escrow.get(name,0);release=held if quantity==-q else half_even(Fraction(held*quantity,-q))
        escrow[name]=held-release;free+=release-notional-fee_cents
    elif quantity and side=='SELL' and q<=0:
        if located_cap is not None:integer(located_cap)
        if locate_provenance is not None:token(locate_provenance)
        if located_cap is None or located_cap<quantity or locate_provenance is None:
            breaches.append('EXECUTED_SHORT_LOCATE_UNQUALIFIED')
        require(name in marks,'SIGNED_OPENING_MARKS_REQUIRED')
        liability=abs(amount_cents(q-quantity,marks[name]));required=-(-(3*liability)//2)
        credited=escrow.get(name,0)+notional
        own=min(max(required-credited,0),max(free-fee_cents,0))
        escrow[name]=credited+own;free-=own+fee_cents
    elif quantity and side=='BUY':
        free-=notional+fee_cents
    elif quantity:
        require(quantity<=q,'SIGNED_REVERSAL_REQUIRES_SPLIT');free+=notional-fee_cents
    positions[name]=q+(quantity if side=='BUY' else -quantity)
    proposed=replace(state,free_cents=free,positions=tuple(sorted(positions.items())),escrow=tuple(sorted(escrow.items())))
    report=mark(proposed,marks)
    if free<0:
        breaches.append('NEGATIVE_FREE_CASH')
        if funding_mode!='HYPOTHETICAL_MANDATORY_FUNDING':breaches.append('UNQUALIFIED_EXECUTION_FUNDING')
    if report['initial_equity_excess_cents']<0:breaches.append('INITIAL_EQUITY_REQUIREMENT')
    if any(v['initial_excess_cents']<0 for v in report['per_name_restriction'].values()):
        breaches.append('INITIAL_PER_NAME_RESTRICTION')
    if report['status']=='DEFAULT':breaches.append('ECONOMIC_DEFAULT')
    result=transition(state,fill_id,'CONFIRMED_EXECUTION',{'name':name,'side':side,'actual_quantity':quantity,
        'price_usd':price,'settled_notional_cents':notional,'exact_notional_cents':quantity*price*100,
        'rounding_residual_cents':Fraction(notional)-quantity*price*100,'fee_cents':fee_cents,
        'own_collateral_cents':own,'released_escrow_cents':release,'post_fill_marks':marks,
        'execution_provenance':execution_provenance,'located_cap':located_cap,'locate_provenance':locate_provenance,
        'funding_mode':funding_mode,'funding_assumption':funding_assumption,
        'funding_shortfall_cents':max(-free,0),'negative_free_cash_delta_cents':max(-free,0)-max(-state.free_cents,0),
        'post_fill_report':report,'breaches':breaches,'future_credit_or_fill_authority':False},
        free_cents=free,positions=tuple(sorted(positions.items())),escrow=tuple(sorted(escrow.items())))
    return replace(result,status='CONFIRMED_EXECUTION_BREACH' if breaches else 'CONFIRMED_EXECUTION_RECORDED')
