"""Pure calendar-controller metadata. No source IO, pricing, routing or authority.

All times are exact integer UTC nanoseconds. Callers supply accepted clock metadata,
not inferred release availability. A TARGET is an instruction, never a fill.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from fractions import Fraction
from hashlib import sha256
import json


class ControllerError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise ControllerError(reason)


def integer(v):
    return type(v) is int


def ident(v):
    return isinstance(v, str) and bool(v.strip())


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def ns(value):
    """Accepted clock ISO timestamps are at most microsecond precision; no float."""
    if value is None:
        return None
    require(isinstance(value, str), 'TIMESTAMP_TYPE')
    import re
    require(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value) is not None,
            'TIMESTAMP_PRECISION_OR_ZONE')
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
        delta = d - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return (delta.days * 86400 + delta.seconds) * 10**9 + delta.microseconds * 1000
    except ValueError as exc:
        raise ControllerError('TIMESTAMP_INVALID') from exc


@dataclass(frozen=True)
class Context:
    account_id: str
    leg_id: str
    cost_id: str
    input_id: str
    calendar_id: str
    protocol_id: str

    def __post_init__(self):
        require(all(ident(v) for v in vars(self).values()), 'CONTEXT_IDENTITY')


@dataclass(frozen=True)
class CalendarEvent:
    event_id: str
    cancelled: bool
    anchor_ns: int | None
    decision_ns: int | None
    candidate_ns: int | None
    expiry_ns: int | None
    reentry_decision_ns: int | None
    reentry_candidate_ns: int | None
    clock_status: str
    clock_pin: str | None
    clock_json: str | None
    provenance: str
    reasons: tuple[str, ...]
    censored: bool


@dataclass(frozen=True)
class Calendar:
    events: tuple[CalendarEvent, ...]
    clusters: tuple[tuple[str, ...], ...]
    unclustered: tuple[str, ...]
    execution_authority: bool = False


def normalize_event_calendar(metadata, clock_rows, nav_role_grid):
    """Preserve every supplied source ID, including cancellations/missing/censors.

    metadata rows: event_id, cancelled, provenance. clock_rows are *outputs* from
    scheduled_fixed.event_clock_metadata; their eligibility is retained verbatim.
    nav_role_grid is a strictly ordered nonempty tuple of exact close timestamps.
    Clusters are inclusive planned-prior-close through r2, never execution Q.
    """
    require(isinstance(metadata, (list, tuple)) and isinstance(clock_rows, (list, tuple)), 'CALENDAR_TYPE')
    require(isinstance(nav_role_grid, (tuple, list)) and len(nav_role_grid) > 0 and
            all(integer(t) for t in nav_role_grid) and
            all(a < b for a, b in zip(nav_role_grid, nav_role_grid[1:])), 'NAV_ROLE_GRID')
    clocks = {}
    for r in clock_rows:
        require(isinstance(r, dict) and r.get('schema') == 'polar.event-clock-projection/1' and
                r.get('purpose') == 'CALENDAR_ONLY' and r.get('execution_authority') is False and
                ident(r.get('event_id')) and r['event_id'] not in clocks, 'CLOCK_IDENTITY_OR_PURPOSE')
        clocks[r['event_id']] = r
    events, ids = [], set()
    for row in metadata:
        require(isinstance(row, dict) and set(row) == {'event_id', 'cancelled', 'provenance'} and
                ident(row['event_id']) and type(row['cancelled']) is bool and ident(row['provenance']) and
                row['event_id'] not in ids, 'SOURCE_EVENT_IDENTITY')
        key = row['event_id']; ids.add(key)
        r = clocks.get(key)
        if row['cancelled']:
            require(r is None, 'CANCELLED_HAS_PROTECTION_CLOCK')
            events.append(CalendarEvent(key, True, None, None, None, None, None, None,
                                        'CANCELLED', None, None, row['provenance'], (), False))
            continue
        if r is None:
            events.append(CalendarEvent(key, False, None, None, None, None, None, None,
                                        'UNAVAILABLE', None, None, row['provenance'], ('CLOCK_MISSING',), True))
            continue
        prior = r.get('prior_reference_date')
        # The role grid supplies actual saved close timestamps, including the
        # prior planned close even when no decision-eligible quote exists there.
        # Never replace this anchor with the older sizing quote or delayed Q.
        candidates = [t for t in nav_role_grid if
                      datetime.fromtimestamp(t // 10**9, timezone.utc).date().isoformat() == prior]
        require(len(candidates) <= 1, 'AMBIGUOUS_PRIOR_CLOSE')
        anchor = candidates[0] if candidates else None
        d, q, end, rd, rq = (ns(r.get(k)) for k in ('decision_at', 'execution_candidate_at', 'expiry_at',
                                                  'reentry_decision_at', 'reentry_candidate_at'))
        require(d is None or q is None or d < q, 'DECISION_NOT_BEFORE_Q')
        require(rd is None or rq is None or rd < rq, 'REENTRY_NOT_BEFORE_Q')
        require(anchor is None or end is None or anchor <= end, 'EVENT_INTERVAL')
        reasons = tuple(r.get('unavailable_reasons', []) + r.get('ineligibility_reasons', []))
        if anchor is None:
            reasons += ('PLANNED_ANCHOR_MISSING',)
        censored = end is None or end > nav_role_grid[-1] or anchor is None or anchor < nav_role_grid[0]
        events.append(CalendarEvent(key, False, anchor, d, q, end, rd, rq, r['status'], digest(r), json.dumps(r, sort_keys=True, separators=(',', ':')),
                                    row['provenance'], reasons, censored))
    require(set(clocks) <= ids, 'CLOCK_WITHOUT_SOURCE_EVENT')
    intervals = sorted((e.anchor_ns, e.expiry_ns, e.event_id) for e in events
                       if not e.cancelled and e.anchor_ns is not None and e.expiry_ns is not None)
    clusters, current, right = [], [], None
    for start, end, key in intervals:
        if right is not None and start > right:
            clusters.append(tuple(sorted(current))); current = []
        current.append(key); right = max(right, end) if current[:-1] else end
    if current:
        clusters.append(tuple(sorted(current)))
    missing = tuple(e.event_id for e in events if not e.cancelled and
                    (e.anchor_ns is None or e.expiry_ns is None))
    return Calendar(tuple(events), tuple(clusters), missing)


@dataclass(frozen=True)
class Request:
    event_id: str
    decision_ns: int
    expiry_ns: int
    reentry_decision_ns: int
    reentry_candidate_ns: int
    clock_pin: str

    def __post_init__(self):
        require(ident(self.event_id) and ident(self.clock_pin) and
                all(integer(x) for x in (self.decision_ns, self.expiry_ns, self.reentry_decision_ns,
                                         self.reentry_candidate_ns)) and
                self.decision_ns <= self.expiry_ns < self.reentry_decision_ns < self.reentry_candidate_ns,
                'REQUEST_CHRONOLOGY')


def request_from_event(event):
    """Eligibility gate on retained clock evidence, not an execution grant.

    A separately selected modeled assumption must already be represented by an
    accepted clock projection. UNKNOWN/null K cannot silently create a request.
    """
    require(isinstance(event, CalendarEvent) and not event.cancelled and
            event.clock_status in {'OBSERVED_METADATA_ELIGIBLE', 'CONDITIONALLY_MODELED'} and
            event.clock_pin is not None, 'EVENT_INELIGIBLE_CLOCK')
    return Request(event.event_id, event.decision_ns, event.expiry_ns,
                   event.reentry_decision_ns, event.reentry_candidate_ns, event.clock_pin)


@dataclass(frozen=True)
class Intent:
    intent_id: str
    generation: int
    destination: str
    decision_ns: int
    q_ns: int
    cause: str
    event_ids: tuple[str, ...]
    expiry_ns: int | None
    # Fractions are exact target instructions only, not physical holdings.
    vti_weight: Fraction
    bil_weight: Fraction


def intent(context, generation, destination, d, q, cause, requests):
    require(integer(d) and integer(q) and d < q, 'STRICT_FUTURE_Q_REQUIRED')
    members = tuple(sorted(r.event_id for r in requests))
    expiry = max((r.expiry_ns for r in requests), default=None)
    require(destination in {'NORMAL', 'REDUCED', 'BIL', 'EXIT'}, 'DESTINATION')
    vti = {'NORMAL': Fraction(1), 'REDUCED': Fraction(1, 2), 'BIL': Fraction(0), 'EXIT': Fraction(0)}[destination]
    bil = Fraction(0) if destination == 'EXIT' else 1 - vti
    key = digest([vars(context), generation, destination, d, q, cause, members])
    return Intent(key, generation, destination, d, q, cause, members, expiry, vti, bil)


@dataclass(frozen=True)
class State:
    context: Context
    mode: str = 'CALENDAR'
    asof_ns: int = -1
    desired: str | None = None
    pending: Intent | None = None
    awaiting: Intent | None = None
    generation: int = 0
    requests: tuple[Request, ...] = ()
    seen_event_ids: tuple[str, ...] = ()
    committed: str | None = None
    execution_outcome: str = 'NOT_RUN'
    conservative_reduced: bool | None = False
    duration_evidence_complete: bool = True
    terminal: bool = False
    last_barrier_ns: int | None = None
    execution_authority: bool = False

    def __post_init__(self):
        require(isinstance(self.context, Context) and self.mode in {'CALENDAR', 'SMA'} and
                self.execution_authority is False, 'STATE_CONTEXT_OR_MODE')


@dataclass(frozen=True)
class Observation:
    kind: str
    at_ns: int
    q_ns: int | None = None
    request: Request | None = None
    category: str | None = None


@dataclass(frozen=True)
class Decision:
    state: State
    action: str
    reason: str
    cancelled_intent_ids: tuple[str, ...] = ()
    execution_authority: bool = False


def advance_controller(s, observation):
    """Advance one causal barrier. At D==Q, ROUTE_Q must be processed first.

    INIT/SMA/REDUCED decisions change the desired latch now. EXPIRY merely queues
    NORMAL; only ROUTE_Q changes the reentry latch. No repeated-category retries.
    """
    require(isinstance(s, State) and isinstance(observation, Observation), 'CONTROLLER_TYPES')
    o = observation
    require(integer(o.at_ns) and o.at_ns >= s.asof_ns, 'NONMONOTONIC_OBSERVATION')
    require(o.kind in {'INIT', 'REDUCED', 'EXPIRY', 'SMA', 'ROUTE_Q', 'EXIT'}, 'OBSERVATION_KIND')
    require(s.pending is None or o.at_ns < s.pending.q_ns or o.kind in {'ROUTE_Q', 'EXIT'},
            'PROCESS_Q_BARRIER_BEFORE_EQUAL_OR_LATER_OBSERVATION')
    s = replace(s, asof_ns=o.at_ns)
    if s.terminal and o.kind != 'ROUTE_Q':
        return Decision(s, 'HOLD', 'TERMINAL_ALREADY_SELECTED')
    if o.kind == 'ROUTE_Q':
        p = s.pending
        require(p is not None and p.q_ns == o.at_ns and s.awaiting is None, 'Q_OR_UNFINALIZED_PRIOR_ROUTE')
        s = replace(s, pending=None, last_barrier_ns=o.at_ns)
        if p.destination == 'REDUCED' and (p.expiry_ns is None or p.q_ns > p.expiry_ns):
            return Decision(s, 'SKIP', 'OBSOLETE_Q_AFTER_EXPIRY', (p.intent_id,))
        if p.cause == 'REENTRY':
            require(not any(r.decision_ns < p.q_ns <= r.expiry_ns for r in s.requests), 'ACTIVE_REDUCTION_AT_REENTRY')
            s = replace(s, desired='NORMAL')
        return Decision(replace(s, awaiting=p, execution_outcome='AWAITING_RECEIPT'), 'ROUTE_INTENT', p.cause)
    if o.kind == 'EXIT':
        p = intent(s.context, s.generation + 1, 'EXIT', o.at_ns, o.q_ns, 'TERMINAL', ())
        old = (s.pending.intent_id,) if s.pending else ()
        # terminal-selected still needs a later valid routing barrier/receipt.
        return Decision(replace(s, pending=p, generation=p.generation, desired='EXIT', requests=(), terminal=True),
                        'EXIT', 'TERMINAL_OVERRIDES', old)
    if o.kind == 'INIT':
        require(s.desired is None and s.mode == 'CALENDAR', 'INITIALIZATION')
        p = intent(s.context, s.generation + 1, 'NORMAL', o.at_ns, o.q_ns, 'INITIAL', ())
        return Decision(replace(s, pending=p, generation=p.generation, desired='NORMAL'), 'TARGET', 'INITIAL_NORMAL')
    if o.kind == 'SMA':
        require(s.mode == 'SMA' and o.category in {'NORMAL', 'BIL', 'UNAVAILABLE'}, 'SMA_CATEGORY')
        if o.category == 'UNAVAILABLE':
            return Decision(s, 'HOLD', 'SMA_CONTROL_UNAVAILABLE')
        if s.desired == o.category:
            return Decision(s, 'HOLD', 'SMA_UNCHANGED_NO_RETRY')
        p = intent(s.context, s.generation + 1, o.category, o.at_ns, o.q_ns, 'SMA_CHANGE', ())
        old = (s.pending.intent_id,) if s.pending else ()
        return Decision(replace(s, desired=o.category, pending=p, generation=p.generation), 'TARGET', 'SMA_CHANGE', old)
    require(s.mode == 'CALENDAR' and s.desired is not None, 'CALENDAR_NOT_INITIALIZED')
    if o.kind == 'REDUCED':
        r = o.request
        require(isinstance(r, Request) and r.decision_ns == o.at_ns, 'REQUEST_DECISION')
        require(r.event_id not in s.seen_event_ids, 'DUPLICATE_OR_EXPIRED_EVENT')
        active = tuple(x for x in s.requests if x.expiry_ns >= o.at_ns) + (r,)
        generation = s.generation + 1
        p = s.pending
        old = (p.intent_id,) if p and p.cause == 'REENTRY' else ()
        if s.desired == 'REDUCED':
            if p and p.destination == 'REDUCED':
                old = (p.intent_id,)
                # Preserve the original D/Q sizing decision; update only the
                # causal active-set version and expiry, never retry failed routing.
                p = intent(s.context, generation, 'REDUCED', p.decision_ns, p.q_ns, p.cause, active)
            elif p and p.cause == 'REENTRY':
                p = None
            return Decision(replace(s, requests=active, generation=generation, pending=p,
                                    seen_event_ids=s.seen_event_ids + (r.event_id,)), 'HOLD', 'OVERLAP_NO_REBALANCE', old)
        require(o.q_ns is not None, 'PROTECTION_Q_MISSING')
        p = intent(s.context, generation, 'REDUCED', o.at_ns, o.q_ns, 'PROTECTION', active)
        old = (s.pending.intent_id,) if s.pending else ()
        return Decision(replace(s, requests=active, generation=generation, desired='REDUCED', pending=p,
                                seen_event_ids=s.seen_event_ids + (r.event_id,)), 'TARGET', 'NEW_REDUCTION', old)
    # EXPIRY removes only ended requests. Reentry uses the final actual expiry's
    # explicit supplied midnight/Q clock, never synthesizes a market close.
    require(o.kind == 'EXPIRY', 'UNSUPPORTED_OBSERVATION')
    active = tuple(r for r in s.requests if r.expiry_ns >= o.at_ns)
    if active:
        return Decision(replace(s, requests=active), 'HOLD', 'REDUCTION_STILL_ACTIVE')
    if s.pending and s.pending.cause == 'REENTRY':
        return Decision(s, 'HOLD', 'REENTRY_ALREADY_QUEUED')
    if s.desired != 'REDUCED' or not s.requests:
        return Decision(s, 'HOLD', 'NO_REENTRY_REQUIRED')
    last = max(s.requests, key=lambda r: (r.expiry_ns, r.event_id))
    require(o.at_ns == last.reentry_decision_ns, 'REENTRY_CLOCK_MISMATCH')
    p = intent(s.context, s.generation + 1, 'NORMAL', o.at_ns, last.reentry_candidate_ns, 'REENTRY', ())
    old = (s.pending.intent_id,) if s.pending else ()
    return Decision(replace(s, requests=(), pending=p, generation=p.generation), 'TARGET', 'QUEUED_REENTRY_LATCH_UNCHANGED', old)


@dataclass(frozen=True)
class PositionMark:
    symbol: str
    quantity: int
    close: Fraction
    rounded_value_cents: int
    source_id: str


@dataclass(frozen=True)
class Anchor:
    context: Context
    generation: int
    q_ns: int
    mark_ns: int
    route_barrier_ns: int
    quote_barrier_sequence: int
    mark_sequence: int
    first_route_sequence: int
    cash_cents: int
    positions: tuple[PositionMark, ...]
    nav_cents: int
    cumulative_flat_cents: int
    cumulative_bps_cents: int
    anchor_id: str


def validate_anchor(anchor, context, generation, q_ns):
    """Validate supplied fields/identity/barriers only, not prices or native truth.

    On HOLD, caller uses the required planned anchor generation and a subsequent
    route barrier even if it has no orders. This never changes controller state.
    """
    a = anchor
    require(isinstance(a, Anchor) and a.context == context and a.generation == generation and a.q_ns == q_ns,
            'ANCHOR_IDENTITY')
    require(all(integer(x) for x in (a.generation, a.q_ns, a.mark_ns, a.route_barrier_ns, a.quote_barrier_sequence,
                                    a.mark_sequence, a.first_route_sequence, a.cash_cents, a.nav_cents,
                                    a.cumulative_flat_cents, a.cumulative_bps_cents)) and
            a.q_ns <= a.mark_ns <= a.route_barrier_ns and 0 <= a.quote_barrier_sequence < a.mark_sequence < a.first_route_sequence and
            a.cumulative_flat_cents >= 0 and a.cumulative_bps_cents >= 0 and ident(a.anchor_id), 'ANCHOR_BARRIER_OR_TYPE')
    require(isinstance(a.positions, tuple) and len(a.positions) == 2 and
            {p.symbol for p in a.positions if isinstance(p, PositionMark)} == {'BIL', 'VTI'}, 'ANCHOR_POSITION_CENSUS')
    require(all(integer(p.quantity) and isinstance(p.close, Fraction) and p.close > 0 and
                integer(p.rounded_value_cents) and ident(p.source_id) for p in a.positions), 'ANCHOR_OPERAND_TYPES')
    return 'SUPPLIED_ANCHOR_STRUCTURE_VALID_NOT_NATIVE_VERIFIED'


@dataclass(frozen=True)
class RouteReceipt:
    context: Context
    intent_id: str
    generation: int
    q_ns: int
    finalized_ns: int
    anchor: Anchor
    outcome: str
    desired_deltas: tuple[tuple[str, int], ...]
    sizing_evidence_ids: tuple[str, ...]
    order_count: int
    filled_order_count: int
    fill_count: int


def accept_route_receipt(s, receipt):
    r = receipt; p = s.awaiting
    require(isinstance(r, RouteReceipt) and p is not None and r.context == s.context and
            r.intent_id == p.intent_id and integer(r.generation) and r.generation == p.generation and
            r.q_ns == p.q_ns and integer(r.finalized_ns) and r.finalized_ns >= r.q_ns and
            r.finalized_ns >= s.asof_ns, 'RECEIPT_CAUSAL_IDENTITY')
    validate_anchor(r.anchor, s.context, p.generation, p.q_ns)
    require(r.anchor.route_barrier_ns <= r.finalized_ns, 'RECEIPT_BEFORE_ROUTE_BARRIER')
    require(r.outcome in {'FILLED', 'ZERO_DELTA_NO_ORDER', 'PARTIAL', 'REJECTED', 'CANCELLED', 'NO_FILL', 'UNKNOWN', 'INVALID'},
            'RECEIPT_OUTCOME')
    require(all(integer(n) and n >= 0 for n in (r.order_count, r.filled_order_count, r.fill_count)) and
            r.filled_order_count <= r.order_count and r.fill_count >= r.filled_order_count, 'ROUTING_COUNTERS')
    require(isinstance(r.desired_deltas, tuple) and len(r.desired_deltas) == 2 and
            {x[0] for x in r.desired_deltas if isinstance(x, tuple) and len(x) == 2} == {'BIL', 'VTI'} and
            all(integer(x[1]) for x in r.desired_deltas), 'DELTA_CENSUS')
    require(isinstance(r.sizing_evidence_ids, tuple) and all(ident(x) for x in r.sizing_evidence_ids), 'SIZING_REFERENCES')
    if r.outcome in {'NO_FILL', 'REJECTED'}:
        require(r.fill_count == r.filled_order_count == 0, 'NO_FILL_COUNTER_CONTRADICTION')
    if r.outcome == 'PARTIAL':
        require(r.fill_count > 0 and r.filled_order_count < r.order_count, 'PARTIAL_COUNTER_CONTRADICTION')
    zero = all(x[1] == 0 for x in r.desired_deltas)
    success = r.outcome in {'FILLED', 'ZERO_DELTA_NO_ORDER'}
    if r.outcome == 'ZERO_DELTA_NO_ORDER':
        require(zero and r.order_count == r.fill_count == r.filled_order_count == 0 and
                bool(r.sizing_evidence_ids), 'ZERO_DELTA_REQUIRES_CONSUMED_PROOF')
    elif r.outcome == 'FILLED':
        require(not zero and r.order_count > 0 and r.filled_order_count == r.order_count and
                bool(r.sizing_evidence_ids), 'FILLED_REQUIRES_COMPLETE_ROUTING')
    conservative = s.conservative_reduced
    if r.outcome in {'UNKNOWN', 'INVALID'}:
        conservative = None
    elif success:
        conservative = p.destination == 'REDUCED'
    elif p.destination == 'REDUCED' or s.committed == 'REDUCED' or s.conservative_reduced:
        conservative = True
    return replace(s, awaiting=None, asof_ns=r.finalized_ns,
                   committed=p.destination if success else s.committed,
                   execution_outcome=r.outcome, conservative_reduced=conservative,
                   duration_evidence_complete=s.duration_evidence_complete and r.outcome not in {'UNKNOWN', 'INVALID'})
