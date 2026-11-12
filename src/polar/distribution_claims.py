"""Pure modeled raw-share claims; no source, policy, native, storage or service calls.

Caller certifies the bound calendar/issue/source and actual pre-session holdings.
Phases validate declared ordering, never prove a real market or native ordering.
"""
from dataclasses import dataclass, asdict, replace
from datetime import date
from enum import IntEnum
from fractions import Fraction
import re


class ClaimError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise ClaimError(reason)


def day(value):
    require(type(value) is str and len(value) == 10, 'CLAIM_DATE')
    try:
        require(date.fromisoformat(value).isoformat() == value, 'CLAIM_DATE')
    except ValueError:
        raise ClaimError('CLAIM_DATE') from None
    return value


def integer(value, maximum=10**60):
    require(type(value) is int and 0 <= value <= maximum, 'CLAIM_INTEGER_DOMAIN')
    return value


def token(value, maximum=256):
    require(type(value) is str and 0 < len(value) <= maximum and value.isprintable(), 'CLAIM_TOKEN')
    return value


def nominal(value):
    # No Decimal context and no six-decimal price constraint. Bound lexeme size,
    # not economic precision, so adversarial rationals cannot allocate unbounded integers.
    require(type(value) is str and len(value) <= 512 and
            re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value), 'CLAIM_NOMINAL_TOKEN')
    return Fraction(value)


def half_even(value):
    q, r = divmod(value.numerator, value.denominator)
    return q + int(2*r > value.denominator or 2*r == value.denominator and q % 2 == 1)


class Phase(IntEnum):
    PRE_SESSION = 0
    PRE_DECISION_CLOSE = 1
    CLOSE_SETTLED = 2


@dataclass(frozen=True)
class Action:
    event_id: str
    instrument: str
    source_ref: str
    raw_pointer: str
    ex_date: str
    payment_date: str
    amount_token: str
    reference_dates: tuple[str, ...]
    currency: str = 'USD'
    basis: str = 'RAW_USD_PER_CONTEMPORANEOUS_SHARE'

    def __post_init__(self):
        for v in (self.event_id, self.instrument, self.source_ref): token(v)
        token(self.raw_pointer, 2048)
        day(self.ex_date); day(self.payment_date); nominal(self.amount_token)
        require(self.currency == 'USD' and self.basis == 'RAW_USD_PER_CONTEMPORANEOUS_SHARE', 'CLAIM_BASIS_CURRENCY')
        require(self.payment_date >= self.ex_date, 'CLAIM_PAY_BEFORE_EX')
        require(type(self.reference_dates) is tuple and 1 <= len(self.reference_dates) <= 10000, 'CLAIM_CALENDAR')
        for d in self.reference_dates: day(d)
        require(tuple(sorted(set(self.reference_dates))) == self.reference_dates and
                self.ex_date in self.reference_dates, 'CLAIM_CALENDAR')
        require(any(d > self.payment_date for d in self.reference_dates), 'CLAIM_AVAILABILITY_UNMAPPED')

    @property
    def availability_date(self):
        return next(d for d in self.reference_dates if d > self.payment_date)


@dataclass(frozen=True)
class Claim:
    action: Action
    entitled_quantity: int
    cents: int
    residue: tuple[int, int]
    paid_at: str | None = None

    def __post_init__(self):
        require(type(self.action) is Action, 'CLAIM_ACTION_TYPE')
        self.action.__post_init__()
        integer(self.entitled_quantity, 10**24); integer(self.cents)
        exact = self.entitled_quantity * nominal(self.action.amount_token) * 100
        expected = half_even(exact)
        residue = exact - expected
        require(self.cents == expected and type(self.residue) is tuple and
                all(type(x) is int for x in self.residue) and
                self.residue == (residue.numerator, residue.denominator), 'CLAIM_AMOUNT_EVIDENCE')
        require(self.paid_at is None or self.paid_at == self.action.availability_date, 'CLAIM_PAYMENT_EVIDENCE')

    @property
    def status(self):
        return 'PAID' if self.paid_at is not None else 'RECEIVABLE'


@dataclass(frozen=True)
class Split:
    instrument: str
    session_date: str
    numerator: int
    denominator: int
    quantity_before: int
    quantity_after: int

    def __post_init__(self):
        token(self.instrument); day(self.session_date)
        for v in (self.numerator, self.denominator, self.quantity_before, self.quantity_after): integer(v, 10**24)
        require(self.numerator > 0 and self.denominator > 0 and
                self.quantity_before*self.numerator == self.quantity_after*self.denominator, 'CLAIM_SPLIT_EVIDENCE')


@dataclass(frozen=True)
class State:
    session_date: str
    phase: Phase
    available_cash_cents: int
    holdings: tuple[tuple[str, int], ...]
    claims: tuple[Claim, ...] = ()
    splits: tuple[Split, ...] = ()

    def __post_init__(self):
        day(self.session_date); integer(self.available_cash_cents)
        require(type(self.phase) is Phase, 'CLAIM_PHASE')
        require(type(self.holdings) is tuple and len(self.holdings) <= 256, 'CLAIM_HOLDINGS')
        for row in self.holdings:
            require(type(row) is tuple and len(row) == 2, 'CLAIM_HOLDINGS')
            token(row[0]); integer(row[1], 10**24)
        require(tuple(sorted(self.holdings)) == self.holdings and
                len(dict(self.holdings)) == len(self.holdings), 'CLAIM_HOLDINGS')
        require(type(self.claims) is tuple and len(self.claims) <= 10000, 'CLAIM_EVENTS')
        for c in self.claims:
            require(type(c) is Claim, 'CLAIM_STATE_TYPE'); c.__post_init__()
            require(c.action.instrument in dict(self.holdings) and c.action.ex_date <= self.session_date and
                    (c.paid_at is None or c.paid_at <= self.session_date), 'CLAIM_STATE_CLOCK_IDENTITY')
            require(c.paid_at != self.session_date or self.phase >= Phase.PRE_DECISION_CLOSE,
                    'CLAIM_STATE_PAYMENT_PHASE')
        require(len({c.action.event_id for c in self.claims}) == len(self.claims), 'CLAIM_DUPLICATE_EVENT')
        require(type(self.splits) is tuple and len(self.splits) <= 10000, 'CLAIM_SPLIT_HISTORY')
        for s in self.splits:
            require(type(s) is Split, 'CLAIM_SPLIT_HISTORY'); s.__post_init__()
            require(s.instrument in dict(self.holdings) and s.session_date <= self.session_date, 'CLAIM_SPLIT_HISTORY')
            require(not any(c.action.instrument == s.instrument and c.action.ex_date == s.session_date for c in self.claims),
                    'CLAIM_SPLIT_EX_AMBIGUOUS')
        require(len({(s.instrument, s.session_date) for s in self.splits}) == len(self.splits), 'CLAIM_DUPLICATE_SPLIT')


def clock(state, session_date, phase):
    state.__post_init__(); day(session_date)
    require(type(phase) is Phase and (session_date, phase) >= (state.session_date, state.phase), 'CLAIM_ORDER')


def recognize(state, action, session_date, phase=Phase.PRE_SESSION):
    clock(state, session_date, phase)
    require(type(action) is Action, 'CLAIM_ACTION_TYPE'); action.__post_init__()
    require(phase == Phase.PRE_SESSION and session_date == action.ex_date, 'CLAIM_ENTITLEMENT_PHASE')
    require(action.event_id not in {c.action.event_id for c in state.claims}, 'CLAIM_DUPLICATE_EVENT')
    require(action.instrument in dict(state.holdings), 'CLAIM_INSTRUMENT')
    require(not any(s.instrument == action.instrument and s.session_date == session_date for s in state.splits),
            'CLAIM_SPLIT_EX_AMBIGUOUS')
    quantity = dict(state.holdings)[action.instrument]
    exact = quantity * nominal(action.amount_token) * 100
    cents = half_even(exact); residue = exact - cents
    claim = Claim(action, quantity, cents, (residue.numerator, residue.denominator))
    # Record even a zero-holder event so later holdings cannot gain it retroactively.
    return replace(state, session_date=session_date, phase=phase, claims=state.claims+(claim,))


def pay(state, event_id, session_date, phase=Phase.PRE_DECISION_CLOSE):
    clock(state, session_date, phase)
    require(phase == Phase.PRE_DECISION_CLOSE, 'CLAIM_PAYMENT_PHASE')
    matches = [c for c in state.claims if c.action.event_id == event_id]
    require(len(matches) == 1, 'CLAIM_UNKNOWN_EVENT'); c = matches[0]
    require(c.paid_at is None, 'CLAIM_DOUBLE_PAYMENT')
    require(session_date == c.action.availability_date, 'CLAIM_PAYMENT_AVAILABILITY')
    claims = tuple(replace(x, paid_at=session_date) if x is c else x for x in state.claims)
    return replace(state, session_date=session_date, phase=phase,
                   available_cash_cents=state.available_cash_cents+c.cents, claims=claims)


def settled_snapshot(state, session_date, holdings, available_cash_cents):
    """Accept caller-reconciled post-close native state; does not execute any trade.

    Cash/quantity provenance and all actual fills/fees remain caller responsibility.
    Claim objects survive buys/sells unchanged. This input is not a native audit.
    """
    clock(state, session_date, Phase.CLOSE_SETTLED)
    require(type(holdings) is tuple and {x[0] for x in holdings} == set(dict(state.holdings)), 'CLAIM_INSTRUMENT')
    return replace(state, session_date=session_date, phase=Phase.CLOSE_SETTLED,
                   holdings=holdings, available_cash_cents=available_cash_cents)


def split(state, instrument, numerator, denominator, session_date, *, same_day_ex):
    """Transform whole raw units; caller must apply reciprocal quote unit separately."""
    clock(state, session_date, Phase.PRE_SESSION)
    integer(numerator, 10**24); integer(denominator, 10**24)
    require(numerator > 0 and denominator > 0, 'CLAIM_SPLIT_RATIO')
    require(type(same_day_ex) is bool and not same_day_ex and
            not any(c.action.instrument == instrument and c.action.ex_date == session_date for c in state.claims),
            'CLAIM_SPLIT_EX_AMBIGUOUS')
    require(instrument in dict(state.holdings), 'CLAIM_INSTRUMENT')
    require(not any(s.instrument == instrument and s.session_date == session_date for s in state.splits), 'CLAIM_DUPLICATE_SPLIT')
    q = Fraction(dict(state.holdings)[instrument]*numerator, denominator)
    require(q.denominator == 1, 'CLAIM_FRACTIONAL_SPLIT_UNSUPPORTED')
    holdings = tuple((s, q.numerator if s == instrument else n) for s, n in state.holdings)
    evidence = Split(instrument, session_date, numerator, denominator, dict(state.holdings)[instrument], q.numerator)
    return replace(state, session_date=session_date, phase=Phase.PRE_SESSION, holdings=holdings,
                   splits=state.splits+(evidence,))


def valuation(state, position_marks_cents, *, terminal=False):
    """Accept caller-bound raw cent marks, not quotes or adjusted prices."""
    state.__post_init__()
    require(type(position_marks_cents) is dict and set(position_marks_cents) == set(dict(state.holdings)), 'CLAIM_MARK_IDENTITIES')
    for s, cents in position_marks_cents.items():
        integer(cents)
        require(dict(state.holdings)[s] != 0 or cents == 0, 'CLAIM_FLAT_MARK')
    outstanding = [c for c in state.claims if c.paid_at is None]
    amount = sum(c.cents for c in outstanding)
    require(type(terminal) is bool, 'CLAIM_TERMINAL_FLAG')
    return {'nav_cents': state.available_cash_cents+sum(position_marks_cents.values())+amount,
            'available_cash_cents': state.available_cash_cents, 'receivable_cents': amount,
            'outstanding_count': len(outstanding),
            'claim_status': 'TERMINAL_OUTSTANDING' if terminal and outstanding else 'OPEN' if outstanding else 'SETTLED',
            'cash_only_terminal': terminal and not outstanding and not any(dict(state.holdings).values())}


def record(state):
    """JSON-safe evidence; validates purely, without source reads or storage writes."""
    state.__post_init__()
    return {'schema': 'polar.distribution-claim-state/1', **asdict(state), 'phase': state.phase.name}


def restore(value):
    require(type(value) is dict and set(value) == {'schema','session_date','phase','available_cash_cents','holdings','claims','splits'}
            and value['schema'] == 'polar.distribution-claim-state/1', 'CLAIM_RECORD_SCHEMA')
    try:
        require(type(value['claims']) in (list, tuple) and len(value['claims']) <= 10000 and
                type(value['splits']) in (list, tuple) and len(value['splits']) <= 10000, 'CLAIM_RECORD_SIZE')
        claims=[]
        for c in value['claims']:
            a = dict(c['action']); a['reference_dates'] = tuple(a['reference_dates'])
            claims.append(Claim(Action(**a), c['entitled_quantity'], c['cents'], tuple(c['residue']), c['paid_at']))
            require(set(c) == {'action','entitled_quantity','cents','residue','paid_at'}, 'CLAIM_RECORD_FIELDS')
        return State(value['session_date'], Phase[value['phase']], value['available_cash_cents'],
                     tuple(tuple(x) for x in value['holdings']), tuple(claims), tuple(Split(**s) for s in value['splits']))
    except (TypeError, KeyError, AttributeError):
        raise ClaimError('CLAIM_RECORD_FIELDS') from None


@dataclass(frozen=True)
class Evidence:
    operation: str
    before_json: str
    inputs_json: str
    after_json: str


def _json(value):
    import json
    text = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    require(len(text.encode()) <= 16*1024**2, 'CLAIM_RECORD_SIZE')
    return text


def _apply(operation, before, inputs):
    require(type(inputs) is dict, 'CLAIM_TRANSITION_INPUTS')
    inputs = dict(inputs)
    if operation == 'recognize':
        a = dict(inputs['action']); a['reference_dates'] = tuple(a['reference_dates'])
        inputs['action'] = Action(**a)
    if 'phase' in inputs: inputs['phase'] = Phase[inputs['phase']]
    if 'holdings' in inputs: inputs['holdings'] = tuple(tuple(x) for x in inputs['holdings'])
    functions = {'recognize': recognize, 'pay': pay, 'settled_snapshot': settled_snapshot, 'split': split}
    require(operation in functions, 'CLAIM_TRANSITION_OPERATION')
    return functions[operation](before, **inputs)


def transition(operation, before, inputs):
    """Return immutable state plus replayable pure evidence; inputs are frozen as JSON.

    A settled_snapshot remains a caller assertion even if its replay is consistent.
    Neither a valid hash nor this replay authenticates source data or native state.
    """
    frozen_inputs = _json(inputs)
    import json
    try:
        after = _apply(operation, before, json.loads(frozen_inputs))
    except (TypeError, KeyError, AttributeError):
        raise ClaimError('CLAIM_TRANSITION_INPUTS') from None
    return after, Evidence(operation, _json(record(before)), frozen_inputs, _json(record(after)))


def verify(evidence):
    """Recompute only pure transition consistency from supplied saved evidence."""
    import json
    require(type(evidence) is Evidence, 'CLAIM_EVIDENCE_TYPE')
    for text in (evidence.before_json, evidence.inputs_json, evidence.after_json):
        require(type(text) is str and len(text.encode()) <= 16*1024**2, 'CLAIM_RECORD_SIZE')
    try:
        before = restore(json.loads(evidence.before_json))
        after = restore(json.loads(evidence.after_json))
        computed, replay = transition(evidence.operation, before, json.loads(evidence.inputs_json))
        require(computed == after and replay == evidence, 'CLAIM_TRANSITION_MISMATCH')
        return after
    except (TypeError, KeyError, AttributeError, json.JSONDecodeError):
        raise ClaimError('CLAIM_EVIDENCE_FIELDS') from None
