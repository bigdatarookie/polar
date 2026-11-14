"""Invented metadata/barrier controls; no engine, source or economic execution."""
from dataclasses import replace
from fractions import Fraction
import json
import pytest
from polar.scheduled_event_controller import (
    Context, State, Request, Observation as O, PositionMark, Anchor, RouteReceipt, TerminalOrder, SymbolEvaluation,
    ControllerError, advance_controller as advance, accept_route_receipt as accept,
    normalize_event_calendar, request_from_event, validate_anchor, ns,
)
from polar.scheduled_fixed import event_clock_metadata

C = Context('invented-account', 'calendar', 'base', 'input-pin', 'calendar-pin', 'protocol-pin')


def start(mode='CALENDAR'):
    s = State(C, mode=mode)
    return advance(s, O('INIT', 1, 2)).state if mode == 'CALENDAR' else s


def request(key='a', d=3, expiry=10, rd=11, rq=12):
    return Request(key, d, expiry, rd, rq, 'invented-clock-pin')


def anchor(p):
    return Anchor(C, p.generation, p.q_ns, p.q_ns, p.q_ns, 1, 2, 3, 10000,
                  (PositionMark('BIL', 0, Fraction(10), 0, 'bil-close-pin'),
                   PositionMark('VTI', 0, Fraction(20), 0, 'vti-close-pin')),
                  10000, 0, 0, 'invented-anchor')


def receipt(s, outcome='ZERO_DELTA_NO_ORDER'):
    p = s.awaiting
    positive = outcome != 'ZERO_DELTA_NO_ORDER'
    evaluations = []
    for name, delta in (('BIL', 1 if positive else 0), ('VTI', -1 if positive else 0)):
        orders = ()
        if positive:
            filled = outcome == 'FILLED' or (outcome == 'PARTIAL' and name == 'BIL')
            status = 'FILLED' if filled else 'REJECTED' if outcome == 'PARTIAL' else outcome
            orders = (TerminalOrder(name+'-order', 'BUY' if delta > 0 else 'SELL', 1, int(filled), status, (name+'-fill',) if filled else ()),)
        evaluations.append(SymbolEvaluation(name, delta, int(positive), None, 'consumed-sizing-proof', orders))
    return RouteReceipt(C, p.intent_id, p.generation, p.q_ns, p.q_ns, anchor(p), outcome,
                        (('BIL', 1 if positive else 0), ('VTI', -1 if positive else 0)),
                        ('consumed-sizing-proof',), 2*int(positive),
                        2 if outcome == 'FILLED' else 1 if outcome == 'PARTIAL' else 0,
                        2 if outcome == 'FILLED' else 1 if outcome == 'PARTIAL' else 0, tuple(evaluations))



def routed(s):
    return advance(s, O('ROUTE_Q', s.pending.q_ns)).state


def settled(s, outcome='ZERO_DELTA_NO_ORDER'):
    s = routed(s)
    return accept(s, receipt(s, outcome))


def reduced():
    s = settled(start())
    return advance(s, O('REDUCED', 3, 4, request())).state


def test_initial_target_is_not_commit_or_execution_then_explicit_zero_delta_commits():
    s = start()
    assert s.desired == 'NORMAL' and s.committed is None and s.execution_outcome == 'NOT_RUN'
    s = routed(s)
    assert s.committed is None and s.awaiting is not None
    s = accept(s, receipt(s))
    assert s.committed == 'NORMAL' and not s.conservative_reduced and s.execution_authority is False


def test_same_reduced_overlap_extends_expiry_preserves_original_d_q_and_single_pending():
    s = reduced(); original = s.pending
    r = request('b', 3, 15, 16, 17)
    d = advance(s, O('REDUCED', 3, 9, r))
    assert d.action == 'HOLD' and d.state.pending.decision_ns == original.decision_ns
    assert d.state.pending.q_ns == original.q_ns and d.state.pending.expiry_ns == 15
    assert d.state.pending.event_ids == ('a', 'b') and d.state.pending.intent_id != original.intent_id
    assert d.state.committed == 'NORMAL'


@pytest.mark.parametrize('outcome', ['NO_FILL', 'PARTIAL', 'REJECTED', 'CANCELLED'])
def test_failed_attempt_same_category_is_hold_not_retry(outcome):
    s = settled(reduced(), outcome)
    d = advance(s, O('REDUCED', 5, 6, request('b', 5, 15, 16, 17)))
    assert d.action == 'HOLD' and d.state.pending is None and d.state.desired == 'REDUCED'
    assert d.state.committed == 'NORMAL' and d.state.conservative_reduced is True


def test_reentry_queued_does_not_flip_latch_and_new_pre_q_reduction_cancels_without_roundtrip():
    s = settled(reduced())
    s = advance(s, O('EXPIRY', 11)).state
    reentry = s.pending
    assert s.desired == 'REDUCED' and reentry.destination == 'NORMAL'
    d = advance(s, O('REDUCED', 11, 13, request('b', 11, 20, 21, 22)))
    assert d.action == 'HOLD' and d.cancelled_intent_ids == (reentry.intent_id,)
    assert d.state.pending is None and d.state.desired == 'REDUCED'
    assert advance(d.state, O('EXPIRY', 21)).state.pending.q_ns == 22


def test_equal_q_requires_barrier_first_then_partial_normal_keeps_conservative_budget():
    s = advance(settled(reduced()), O('EXPIRY', 11)).state
    r = request('b', 12, 20, 21, 22)
    with pytest.raises(ControllerError, match='PROCESS_Q_BARRIER'):
        advance(s, O('REDUCED', 12, 13, r))
    s = routed(s)
    assert s.desired == 'NORMAL' and s.committed == 'REDUCED' and s.conservative_reduced
    s = accept(s, receipt(s, 'PARTIAL'))
    assert s.desired == 'NORMAL' and s.committed == 'REDUCED' and s.conservative_reduced
    d = advance(s, O('REDUCED', 12, 13, r))
    assert d.action == 'TARGET' and d.state.pending.q_ns == 13


def test_reentry_success_clears_conservative_state_but_unknown_duration_is_unavailable():
    s = advance(settled(reduced(), 'NO_FILL'), O('EXPIRY', 11)).state
    s = settled(s)
    assert s.desired == s.committed == 'NORMAL' and not s.conservative_reduced
    s = routed(advance(s, O('REDUCED', 13, 14, request('b', 13, 20, 21, 22))).state)
    s = accept(s, receipt(s, 'UNKNOWN'))
    assert s.conservative_reduced is None and s.committed == 'NORMAL'
    s = advance(s, O('REDUCED', 15, 16, request('c', 15, 20, 21, 22))).state
    assert s.conservative_reduced is None and s.pending is None and not s.duration_evidence_complete
    s = settled(advance(s, O('EXPIRY', 21)).state)
    assert s.committed == 'NORMAL' and not s.conservative_reduced and not s.duration_evidence_complete


def test_obsolete_q_no_commit_and_no_expired_event_reopening():
    s = advance(settled(start()), O('REDUCED', 3, 13, request())).state
    d = advance(s, O('ROUTE_Q', 13))
    assert d.action == 'SKIP' and d.state.committed == 'NORMAL' and d.state.awaiting is None
    with pytest.raises(ControllerError, match='DUPLICATE_OR_EXPIRED'):
        advance(d.state, O('REDUCED', 14, 15, request('a', 14, 20, 21, 22)))


def test_terminal_overrides_pending_but_needs_real_receipt_not_synthetic_cashout():
    s = reduced(); old = s.pending
    d = advance(s, O('EXIT', 3, 4))
    assert d.action == 'EXIT' and d.cancelled_intent_ids == (old.intent_id,)
    assert d.state.committed == 'NORMAL' and d.state.pending.destination == 'EXIT'
    s = settled(d.state)
    assert s.committed == 'EXIT' and s.terminal and not s.conservative_reduced
    assert advance(s, O('REDUCED', 5, 6, request('b', 5))).reason == 'TERMINAL_ALREADY_SELECTED'


@pytest.mark.parametrize('mutate,match', [
    (lambda r: replace(r, context=replace(C, account_id='other')), 'CAUSAL_IDENTITY'),
    (lambda r: replace(r, context=replace(C, cost_id='stress')), 'CAUSAL_IDENTITY'),
    (lambda r: replace(r, generation=r.generation+1), 'CAUSAL_IDENTITY'),
    (lambda r: replace(r, q_ns=r.q_ns+1), 'CAUSAL_IDENTITY'),
    (lambda r: replace(r, finalized_ns=r.q_ns-1), 'CAUSAL_IDENTITY'),
    (lambda r: replace(r, sizing_evidence_ids=()), 'SYMBOL_EVALUATION_BINDING'),
    (lambda r: replace(r, desired_deltas=(('VTI', 1), ('BIL', 0))), 'SYMBOL_EVALUATION_BINDING'),
    (lambda r: replace(r, order_count=1), 'SYMBOL_AGGREGATE_COUNTER_CENSUS'),
    (lambda r: replace(r, anchor=replace(r.anchor, first_route_sequence=2)), 'BARRIER'),
    (lambda r: replace(r, anchor=replace(r.anchor, generation=999)), 'ANCHOR_IDENTITY'),
    (lambda r: replace(r, anchor=replace(r.anchor, route_barrier_ns=r.q_ns+1)), 'BEFORE_ROUTE'),
    (lambda r: replace(r, anchor=replace(r.anchor, mark_ns=r.q_ns+1)), 'BARRIER'),
])
def test_malformed_receipts_fail_instead_of_committing(mutate, match):
    s = routed(reduced())
    with pytest.raises(ControllerError, match=match):
        accept(s, mutate(receipt(s)))
    assert s.committed == 'NORMAL' and s.awaiting is not None


def test_complete_positive_order_vs_nonzero_no_fill_and_no_receipt_for_hold():
    s = settled(reduced(), 'FILLED')
    assert s.committed == 'REDUCED' and s.conservative_reduced
    with pytest.raises(ControllerError, match='CAUSAL_IDENTITY'):
        accept(s, receipt(routed(reduced())))


def test_sma_initial_unchanged_failed_hold_category_change_and_unavailable():
    s = start('SMA')
    d = advance(s, O('SMA', 1, 2, category='UNAVAILABLE'))
    assert d.state.desired is None and d.state.pending is None
    s = advance(d.state, O('SMA', 1, 2, category='BIL')).state
    s = settled(s, 'NO_FILL')
    d = advance(s, O('SMA', 3, 4, category='BIL'))
    assert d.action == 'HOLD' and d.state.pending is None
    d = advance(d.state, O('SMA', 4, 5, category='NORMAL'))
    assert d.action == 'TARGET'
    d = advance(d.state, O('SMA', 4, 6, category='UNAVAILABLE'))
    assert d.state.pending.q_ns == 5 and d.state.desired == 'NORMAL'


def clock(key, day=12, end=14):
    # Existing accepted clock computes all chronology, never a price lookup.
    days = [f'2024-02-{d:02}' for d in range(8, 25)]
    value = {'schema': 'polar.event-clock-metadata/1', 'purpose': 'CALENDAR_ONLY',
             'event_id': key, 'reference_period': '2024-01', 'release_at': f'2024-02-{day+1:02}T13:30:00Z',
             'release_zone': 'America/New_York',
             'calendar_availability': {'known_by': None, 'basis': 'UNKNOWN', 'provenance': 'UNKNOWN_ORIGINAL_K'},
             'event_observation_availability': {'known_by': None, 'observation_at': None,
                                               'basis': 'NOT_APPLICABLE', 'provenance': 'CALENDAR_ONLY'},
             'reference_provenance': {'basis': 'MODELED', 'provenance': 'INVENTED_GRID'},
             'sessions': [{'date': d, 'open_at': d+'T14:30:00Z', 'close_at': d+'T21:00:00Z'} for d in days],
             'quotes': [{'close_at': days[0]+'T21:00:00Z', 'availability':
                         {'known_by': None, 'basis': 'UNKNOWN', 'provenance': 'UNKNOWN_QUOTE_K'}}]}
    return event_clock_metadata(value)


def test_metadata_uses_planned_anchor_not_older_quote_and_retains_unknown_k():
    r = clock('a')
    grid = tuple(ns(f'2024-02-{d:02}T21:00:00Z') for d in range(8, 25))
    c = normalize_event_calendar([{'event_id': 'a', 'cancelled': False, 'provenance': 'SOURCE_ROW'}], [r], grid)
    e = c.events[0]
    assert e.anchor_ns == ns('2024-02-12T21:00:00Z')
    assert e.clock_status == 'NOT_EXECUTABLE' and c.execution_authority is False
    with pytest.raises(ControllerError, match='INELIGIBLE_CLOCK'):
        request_from_event(e)
    saved = json.loads(e.clock_json)
    assert saved['calendar_availability']['basis'] == 'UNKNOWN'
    assert saved['event_observation_availability']['basis'] == 'NOT_APPLICABLE'
    assert saved['latest_completed_candidate_availability']['known_by'] is None


def test_inclusive_touching_transitive_clusters_keep_cancelled_missing_and_censored():
    rows = [clock('a', 12), clock('b', 14), clock('c', 16), clock('late', 20)]
    metadata = [{'event_id': key, 'cancelled': key == 'cancelled', 'provenance': 'SOURCE_ROW'}
                for key in ('a', 'b', 'c', 'late', 'missing', 'cancelled')]
    grid = tuple(ns(f'2024-02-{d:02}T21:00:00Z') for d in range(8, 20))
    c = normalize_event_calendar(metadata, rows, grid)
    assert c.clusters == (('a', 'b', 'c'),)
    assert c.unclustered == ('late', 'missing')
    assert len(c.events) == 6 and c.events[-1].cancelled and c.events[-1].anchor_ns is None
    assert next(e for e in c.events if e.event_id == 'late').censored


def test_normalizer_duplicate_cancellation_and_clock_purpose_guards():
    meta = {'event_id': 'a', 'cancelled': False, 'provenance': 'SOURCE_ROW'}
    grid = (1, 2)
    with pytest.raises(ControllerError, match='SOURCE_EVENT_IDENTITY'):
        normalize_event_calendar([meta, meta], [], grid)
    with pytest.raises(ControllerError, match='CANCELLED_HAS'):
        normalize_event_calendar([{**meta, 'cancelled': True}], [clock('a')], grid)
    with pytest.raises(ControllerError, match='PURPOSE'):
        normalize_event_calendar([meta], [{**clock('a'), 'purpose': 'PRE_RELEASE_SIGNAL'}], grid)


def test_hold_anchors_are_independently_required_not_state_commits_and_strict_timestamp_precision():
    s = reduced(); a = anchor(s.pending)
    assert validate_anchor(a, C, s.pending.generation, 4).startswith('SUPPLIED_ANCHOR')
    assert s.committed == 'NORMAL'
    with pytest.raises(ControllerError, match='PRECISION'):
        ns('2024-01-01T00:00:00.123456789Z')
    assert ns('1970-01-01T00:00:00.000001Z') == 1000


def test_expiry_is_inclusive_and_identical_reentry_does_not_duplicate():
    s = settled(reduced())
    d = advance(s, O('EXPIRY', 10))
    assert d.reason == 'REDUCTION_STILL_ACTIVE' and d.state.pending is None
    s = advance(d.state, O('EXPIRY', 11)).state
    d = advance(s, O('EXPIRY', 11))
    assert d.reason == 'REENTRY_ALREADY_QUEUED' and d.state.pending == s.pending


def test_sma_pending_replacement_and_hold_anchor_identity():
    s = advance(start('SMA'), O('SMA', 1, 5, category='NORMAL')).state
    old = s.pending
    d = advance(s, O('SMA', 2, 5, category='BIL'))
    assert d.cancelled_intent_ids == (old.intent_id,) and d.state.pending.destination == 'BIL'
    a = anchor(d.state.pending)
    for bad in (replace(a, context=replace(C, leg_id='other')), replace(a, q_ns=6)):
        with pytest.raises(ControllerError, match='IDENTITY'):
            validate_anchor(bad, C, d.state.pending.generation, 5)


def test_request_eligibility_from_accepted_conditional_clock_preserves_source_pin():
    r = clock('a')
    # Prospective modeled known-by assumptions are explicit and content-bound,
    # never an inference from null original clocks.
    from test_event_clock_metadata import fixture, availability
    v = fixture(); v['purpose'] = 'CALENDAR_ONLY'; v['event_id'] = 'a'
    v['event_observation_availability'] = {**availability(None, 'NOT_APPLICABLE'), 'observation_at': None}
    v['calendar_availability'] = availability('2024-02-01T00:00:00Z', 'MODELED')
    v['quotes'][0]['availability'] = availability('2024-02-10T00:00:00Z', 'MODELED')
    r = event_clock_metadata(v)
    assert r['status'] == 'CONDITIONALLY_MODELED'
    grid = tuple(ns(f'2024-02-{d:02}T21:00:00Z') for d in range(8, 25))
    e = normalize_event_calendar([{'event_id':'a','cancelled':False,'provenance':'INVENTED'}], [r], grid).events[0]
    q = request_from_event(e)
    assert q.event_id == 'a' and q.clock_pin == e.clock_pin and q.reentry_candidate_ns > q.expiry_ns


def test_original_two_delta_one_unattributed_order_cannot_commit():
    s = routed(reduced())
    r = replace(receipt(s, 'FILLED'), order_count=1, filled_order_count=1, fill_count=1, symbol_evaluations=())
    with pytest.raises(ControllerError, match='SYMBOL_ROUTING_CENSUS'):
        accept(s, r)


@pytest.mark.parametrize('mutant,reason', [
    (lambda r: r.symbol_evaluations[:1], 'SYMBOL_ROUTING_CENSUS'),
    (lambda r: (replace(r.symbol_evaluations[0], orders=(replace(r.symbol_evaluations[0].orders[0], side='SELL'),)), r.symbol_evaluations[1]), 'SYMBOL_TERMINAL_ORDER'),
    (lambda r: (replace(r.symbol_evaluations[0], routed_quantity=0, orders=()), r.symbol_evaluations[1]), 'CLIPPING_REASON'),
    (lambda r: (replace(r.symbol_evaluations[0], orders=()), r.symbol_evaluations[1]), 'QUANTITY_CENSUS'),
    (lambda r: (r.symbol_evaluations[0], replace(r.symbol_evaluations[1], consumed_sizing_id='missing')), 'EVALUATION_BINDING'),
    (lambda r: (r.symbol_evaluations[0], replace(r.symbol_evaluations[1], orders=(replace(r.symbol_evaluations[0].orders[0], side='SELL'),))), 'COUNTER_CENSUS'),
    (lambda r: (replace(r.symbol_evaluations[0], orders=(replace(r.symbol_evaluations[0].orders[0], status='PARTIAL'),)), r.symbol_evaluations[1]), 'PARTIAL_CONTRADICTION'),
])
def test_closed_symbol_terminal_census_mutants(mutant, reason):
    s = routed(reduced()); r = receipt(s, 'FILLED')
    with pytest.raises(ControllerError, match=reason):
        accept(s, replace(r, symbol_evaluations=mutant(r)))


def test_legitimate_explicit_clipping_not_omitted_symbol_and_all_zero_routed_not_success():
    s = routed(reduced()); r = receipt(s, 'FILLED')
    bil, vti = r.symbol_evaluations
    clipped = replace(bil, routed_quantity=0, clipping_reason='FUTURE_CLOSE_FEE_AWARE_CAP', orders=())
    r = replace(r, symbol_evaluations=(clipped, vti), order_count=1, filled_order_count=1, fill_count=1)
    assert accept(s, r).committed == 'REDUCED'
    both = (clipped, replace(vti, routed_quantity=0, clipping_reason='NO_EXECUTABLE_QUANTITY', orders=()))
    with pytest.raises(ControllerError, match='COMPLETE_ROUTING'):
        accept(s, replace(r, symbol_evaluations=both, order_count=0, filled_order_count=0, fill_count=0))
