"""Closed adapter for Quant A's unchanged statically packaged policy.

No caller module/path, source access, fitting or fills enter the policy. The
common scheduled service freezes this plan once after FIRST_START for both costs.
"""
from datetime import date, datetime, time, timedelta
from fractions import Fraction
from pathlib import Path
import hashlib

from research_candidates.quant_a_drawdown_gate import policy as author
from .ci_research import require
from .reference_ridge_plan import nanoseconds

SCHEMA = 'polar.scheduled-reference-profile/14'
SEMANTIC_CANDIDATE = '957447a203d7fca6c99b5854b47a51791954c438'
POLICY_SHA = '974bc78fea2d0495d213d361abf257a31ebd05f63b9197061a0a2c490a909a2c'
POLICY_PATH = 'research_candidates/quant_a_drawdown_gate/policy.py'
IDS = ['DRAWDOWN_GATE', 'FULL_VTI', 'FIXED_HALF', 'FULL_BIL']
COSTS = [{'id': 'BASE', 'cost_profile': {'flat_cents': 100, 'bps': 10}},
         {'id': 'COST_STRESS', 'cost_profile': {'flat_cents': 200, 'bps': 20}}]


def policy_binding():
    root = Path(__file__).resolve().parents[2]
    path = root/POLICY_PATH
    require(not path.is_symlink() and path.resolve() == path and
            Path(author.__file__).resolve() == path, 'DRAWDOWN_STATIC_IMPORT_BINDING')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    require(digest == POLICY_SHA, 'DRAWDOWN_POLICY_BLOB_MISMATCH')
    return {POLICY_PATH: digest}


def validate_profile(p):
    policy_binding()
    require(p['schema'] == SCHEMA and p['symbols'] == ['BIL', 'VTI'] and
            p['policy'] == {'kind': 'QUANT_A_DRAWDOWN_RECOVERY',
                            'semantic_candidate': SEMANTIC_CANDIDATE, 'policy_sha256': POLICY_SHA} and
            p['cost_scenarios'] == COSTS and p['decision_delay_seconds'] == 60,
            'DRAWDOWN_CLOSED_PROFILE')
    require([x['id'] for x in p['legs']] == IDS and
            [x['rule'] for x in p['legs']] == ['DRAWDOWN', 'FULL_VTI', 'MONTHLY_HALF', 'FULL_BIL'] and
            all(set(x) == {'id', 'label', 'rule', 'scale'} and x['scale'] == [1, 1] for x in p['legs']) and
            p['primary_strategy'] == IDS[0] and p['primary_benchmark'] == 'FIXED_HALF' and
            p['subperiods'] == [], 'DRAWDOWN_LEGS')
    require([{k: v for k, v in c.items() if k not in ('id', 'description')} for c in p['criteria']] == [
        {'kind': 'DRAWDOWN_LE', 'left_id': IDS[0], 'right_id': 'FIXED_HALF'},
        {'kind': 'TERMINAL_GE', 'left_id': IDS[0], 'right_id': 'FIXED_HALF'},
        {'kind': 'POSITIVE_GROWTH', 'left_id': IDS[0]}], 'DRAWDOWN_FROZEN_SCREEN')
    return p


def instruction(history, previous, formation):
    decision = author.target(history, previous, formation)
    value = {'kind': decision.kind}
    if decision.kind == 'TARGET':
        value['weights'] = {s: [w.numerator, w.denominator] for s, w in
                            [('VTI', decision.vti_weight), ('BIL', decision.bil_weight)]}
    signal = {'observed_risk_on': decision.observed_risk_on,
              'previous_observed_risk_on': previous, 'reason': decision.reason,
              'drawdown': None if decision.drawdown is None else
                          [decision.drawdown.numerator, decision.drawdown.denominator]}
    return value, signal, decision.observed_risk_on


def plan_phase(market, profile, grid, tz):
    validate_profile(profile)
    symbols = profile['symbols']
    require(market['symbols'] == symbols, 'DRAWDOWN_MARKET_SYMBOLS')
    days = market['dates']; rows = {r['date']: r for r in market['schedule']}
    close = lambda d: nanoseconds(datetime.fromisoformat(rows[d]['reference_close_utc'].replace('Z', '+00:00')))
    def event(day, entry, instructions):
        known = datetime.combine(date.fromisoformat(day)+timedelta(days=1), time(), tzinfo=tz)
        decision = known+timedelta(seconds=profile['decision_delay_seconds'])
        require(nanoseconds(known) < nanoseconds(decision) < close(entry), 'DRAWDOWN_CLOCK')
        return {'day': entry, 'formation': day, 'known_ns': nanoseconds(known),
                'decision_ns': nanoseconds(decision), 'open_ns': close(entry),
                'kind': 'REFERENCE', 'instructions': instructions}
    nav = [{'date': d, 'nominal_ns': close(d), 'sample_ns': close(d)+1000,
            'initial': i == 0, 'terminal': d == grid['terminal']}
           for i, d in enumerate(grid['nav_dates'])]
    decisions = []; signals = []; previous = None
    for i, e in enumerate(grid['decisions']):
        day, entry, index = e['signal_date'], e['execution_date'], e['signal_index']
        require(days[index] == day and entry == rows[day]['next_reference_date'] and
                day < entry < grid['terminal'], 'DRAWDOWN_FORMATION_GRID')
        # Each exact Fraction comes only from the eligible dated prefix. Never
        # hand later execution rows, floating prices or holdings to author code.
        history = [(date.fromisoformat(d), Fraction(market['prices_micro'][d]['VTI'], 1000000))
                   for d in days[max(0, index-author.WINDOW+1):index+1]]
        gate, signal, observed = instruction(history, previous, date.fromisoformat(day))
        first = i == 0; monthly = rows[day]['month_end_in_reference_range'] is True
        def fixed(weights, target):
            return {'kind': 'TARGET', 'weights': weights} if target else {'kind': 'HOLD'}
        instructions = {'DRAWDOWN_GATE': gate,
            'FULL_VTI': fixed({'BIL': [0, 1], 'VTI': [1, 1]}, first),
            'FIXED_HALF': fixed({'BIL': [1, 2], 'VTI': [1, 2]}, first or monthly),
            'FULL_BIL': fixed({'BIL': [1, 1], 'VTI': [0, 1]}, first)}
        decisions.append(event(day, entry, instructions))
        signals.append({'formation': day, 'execution': entry, **signal})
        previous = observed  # Unconditional observed state, independent of fills.
    terminal = grid['terminal']; before = days[days.index(terminal)-1]
    decisions.append(event(before, terminal, {i: {'kind': 'EXIT'} for i in IDS}))
    return {'profile': {'kind': 'REFERENCE_TARGETS', 'legs': IDS, 'end': terminal},
            'symbols': symbols, 'prices': {d: {s: {'close_micro': market['prices_micro'][d][s]}
                                            for s in symbols} for d in grid['nav_dates']},
            'grid': nav, 'decisions': decisions, 'signals': signals,
            'quote_basis': 'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',
            'clock_policy': 'PINNED_REFERENCE_EARLY_CLOSE'}
