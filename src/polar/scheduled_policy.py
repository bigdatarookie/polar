"""Closed scheduled target mechanisms on the existing reference ledger, without fits."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
import re

from .ci_research import INITIAL_CENTS, require
from .ci_research_evaluation import evaluate_legs, metric
from .gym_contract import context, decimal_string, canonical
from .reference_ridge_plan import nanoseconds
from .scheduled_signals import trend_targets, inverse_vol_targets

PROFILE_SCHEMA = 'polar.scheduled-reference-profile/1'
CONDITIONS = {
    'SR_DELTA_GE': {'right_id', 'threshold'},
    'TERMINAL_GE': {'right_id'}, 'TERMINAL_GT': {'right_id'},
    'POSITIVE_GROWTH': set(), 'DRAWDOWN_LE': {'right_id'},
    'VOL_RATIO_BETWEEN': {'right_id', 'lower', 'upper'},
}


def profile_value(p):
    fields = {'schema', 'protocol_id', 'protocol_sha256', 'input_sha256', 'calendar_sha256', 'timezone_sha256', 'symbols', 'policy', 'legs',
              'primary_strategy', 'primary_benchmark', 'decision_delay_seconds', 'criteria',
              'question_label', 'question_summary', 'clock_description', 'partition_description',
              'additional_limitations', 'subperiods'}
    version2 = type(p) is dict and p.get('schema') == 'polar.scheduled-reference-profile/2'
    require(type(p) is dict and set(p) == fields | ({'cost_scenarios', 'uncertainty'} if version2 else set()) and
            p['schema'] in (PROFILE_SCHEMA, 'polar.scheduled-reference-profile/2'), 'SCHEDULED_PROFILE_SCHEMA')
    for key in ('protocol_sha256', 'input_sha256', 'calendar_sha256', 'timezone_sha256'):
        require(type(p[key]) is str and re.fullmatch('[a-f0-9]{64}', p[key]), 'SCHEDULED_PROFILE_HASH')
    require(type(p['protocol_id']) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}', p['protocol_id']), 'SCHEDULED_PROTOCOL_ID')
    for key in ('question_label', 'question_summary', 'clock_description', 'partition_description'):
        require(type(p[key]) is str and 0 < len(p[key]) <= 1000, 'SCHEDULED_PUBLIC_TEXT')
    require(type(p['additional_limitations']) is list and len(p['additional_limitations']) <= 16, 'SCHEDULED_LIMITATIONS')
    for pair in p['additional_limitations']:
        require(type(pair) is list and len(pair) == 2 and all(type(v) is str and 0 < len(v) <= 1000 for v in pair), 'SCHEDULED_LIMITATION')
    symbols = p['symbols']
    require(type(symbols) is list and 1 <= len(symbols) <= 64 and symbols == sorted(set(symbols)), 'SCHEDULED_SYMBOLS')
    policy = p['policy']
    if version2:
        require(type(policy) is dict and set(policy) == {'kind', 'lookback', 'annual_cap'} and
                policy['kind'] == 'COMMON_RISK_INVERSE_VOLATILITY' and policy['lookback'] == 60 and
                policy['annual_cap'] == '0.10', 'SCHEDULED_POLICY')
        require(p['cost_scenarios'] == [{'id':'BASE', 'cost_profile':{'flat_cents':100,'bps':10}},
                                      {'id':'COST_STRESS', 'cost_profile':{'flat_cents':200,'bps':20}}],
                'SCHEDULED_COST_SCENARIOS')
        require(p['uncertainty'] == {'kind':'PAIRED_CIRCULAR_SAVED_RETURNS', 'block':63, 'replicates':1000, 'seed':37001},
                'SCHEDULED_UNCERTAINTY_PROFILE')
    else:
        require(type(policy) is dict and set(policy) == {'kind', 'lookback', 'skip'} and
                policy['kind'] == 'ABSOLUTE_MOMENTUM_SLEEVES' and
                type(policy['lookback']) is int and type(policy['skip']) is int and
                0 <= policy['skip'] < policy['lookback'] <= 4096, 'SCHEDULED_POLICY')
    require(type(p['decision_delay_seconds']) is int and 1 <= p['decision_delay_seconds'] <= 3600, 'SCHEDULED_DECISION_DELAY')
    legs = p['legs']
    require(type(legs) is list and 2 <= len(legs) <= 5 and
            len({x['id'] for x in legs}) == len(legs), 'SCHEDULED_LEGS')
    ids = {x['id'] for x in legs}
    if version2:
        require(len(legs) == 3 and {x['rule'] for x in legs} == {'INVERSE_VOL','MOMENTUM','EQUAL_WEIGHT'} and
                all(x['scale'] == [1,1] for x in legs), 'SCHEDULED_COMMON_RISK_LEGS')
    require(p['primary_strategy'] in ids and p['primary_benchmark'] in ids and
            p['primary_strategy'] != p['primary_benchmark'], 'SCHEDULED_PRIMARY_ROLES')
    for leg in legs:
        require(set(leg) == {'id', 'label', 'rule', 'scale'} and
                leg['rule'] in (('INVERSE_VOL', 'MOMENTUM', 'EQUAL_WEIGHT') if version2 else ('SLEEVES', 'MOMENTUM', 'EQUAL_WEIGHT', 'CASH')), 'SCHEDULED_LEG')
        require(type(leg['id']) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}', leg['id']) and
                type(leg['label']) is str and 0 < len(leg['label']) <= 128, 'SCHEDULED_LEG_ID_LABEL')
        require(type(leg['scale']) is list and len(leg['scale']) == 2 and
                all(type(v) is int for v in leg['scale']) and leg['scale'][1] > 0 and
                0 <= Fraction(*leg['scale']) <= 1, 'SCHEDULED_WEIGHT_SCALE')
    require(type(p['criteria']) is list and 1 <= len(p['criteria']) <= 20 and
            len({c['id'] for c in p['criteria']}) == len(p['criteria']), 'SCHEDULED_CRITERIA')
    for c in p['criteria']:
        require(c['kind'] in CONDITIONS and set(c) == {'id', 'description', 'kind', 'left_id'} | CONDITIONS[c['kind']], 'SCHEDULED_CRITERION_SCHEMA')
        require(c['left_id'] in ids and ('right_id' not in c or c['right_id'] in ids and c['right_id'] != c['left_id']), 'SCHEDULED_CRITERION_LEGS')
        for key in ('threshold', 'lower', 'upper'):
            if key in c:
                require(type(c[key]) is str and len(c[key]) <= 64 and Decimal(c[key]).is_finite(), 'SCHEDULED_CRITERION_NUMBER')
    require(type(p['subperiods']) is list and len(p['subperiods']) <= 8, 'SCHEDULED_SUBPERIODS')
    for pair in p['subperiods']:
        require(type(pair) is list and len(pair) == 2 and date.fromisoformat(pair[0]) <= date.fromisoformat(pair[1]), 'SCHEDULED_SUBPERIOD')
    # Reuse the current common wire's finite bounds; never spend an original on
    # a profile whose public projection cannot fit it.
    require(29 + 4*len(p['subperiods']) + (3 if version2 else 0) <= 40 and
            12 + len(p['additional_limitations']) + len(legs)*(1+len(p['subperiods'])) + (3 if version2 else 0) <= 30,
            'SCHEDULED_PUBLIC_WIRE_BOUND')
    return p


def calendar_value(calendar, schedule, phases=None):
    """Validate date-only geometry before any policy signal is evaluated."""
    require(calendar.get('schema') == 'polar.scheduled-policy-calendar/1', 'SCHEDULED_CALENDAR_SCHEMA')
    rows = {r['date']: r for r in schedule}; days = list(rows)
    require(len(days) == len(schedule) and days == sorted(set(days)), 'SCHEDULED_SOURCE_DATES')
    grids = calendar['phases']
    require(type(grids) is dict and set(grids) <= {'VALIDATION', 'FINAL'} and 'FINAL' in grids, 'SCHEDULED_PHASES')
    for phase, g in grids.items():
        require(g['initial'] in rows and g['terminal'] in rows and g['initial'] < g['terminal'], 'SCHEDULED_BOUNDARIES')
        selected = [d for d in days if g['initial'] <= d <= g['terminal']]
        require(g['nav_dates'] == selected and g['nav_points'] == len(selected) and
                g['return_count'] == len(selected)-1, 'SCHEDULED_GRID')
        expected = [(d, rows[d]['next_reference_date']) for d in selected[:-1]
                    if rows[d]['month_end_in_reference_range'] is True and
                    rows[d]['next_reference_date'] is not None and rows[d]['next_reference_date'] < g['terminal']]
        require([(r['signal_date'], r['execution_date']) for r in g['decisions']] == expected and
                g['decision_count'] == len(expected), 'SCHEDULED_DECISION_GRID')
        for d in g['decisions']:
            require(d['signal_index'] == days.index(d['signal_date']) and
                    d['execution_reference_close_utc'] == rows[d['execution_date']]['reference_close_utc'], 'SCHEDULED_DECISION_JOIN')
    return grids


def plan_phase(market, profile, grid, tz):
    """Called only after durable FIRST_START; source prefix is the signal firewall."""
    profile_value(profile)
    symbols = market['symbols']; require(symbols == profile['symbols'], 'SCHEDULED_MARKET_SYMBOLS')
    days = market['dates']; rows = {r['date']: r for r in market['schedule']}
    close = lambda d: nanoseconds(datetime.fromisoformat(rows[d]['reference_close_utc']))
    nav = [{'date': d, 'nominal_ns': close(d), 'sample_ns': close(d)+1000,
            'initial': i == 0, 'terminal': d == grid['terminal']} for i, d in enumerate(grid['nav_dates'])]
    decisions = []; signals = []
    for event in grid['decisions']:
        day, entry = event['signal_date'], event['execution_date']; index = days.index(day)
        known = datetime.combine(date.fromisoformat(day)+timedelta(days=1), time(), tzinfo=tz)
        decision = known+timedelta(seconds=profile['decision_delay_seconds'])
        require(nanoseconds(known) < nanoseconds(decision) < close(entry), 'SCHEDULED_CLOCK')
        lookback = profile['policy']['lookback']
        require(index >= lookback, 'SCHEDULED_SIGNAL_HISTORY')
        prefix = [market['prices_micro'][d] for d in days[index-lookback:index+1]]
        common_risk = profile['policy']['kind'] == 'COMMON_RISK_INVERSE_VOLATILITY'
        signal = (inverse_vol_targets(prefix, symbols, window=lookback, annual_cap=float(profile['policy']['annual_cap'])) if common_risk else
                  trend_targets(prefix, symbols, lookback=lookback, skip=profile['policy']['skip']))
        instructions = {}
        for leg in profile['legs']:
            if leg['rule'] == 'CASH':
                instructions[leg['id']] = {'kind': 'HOLD'}
                continue
            weights = ({s: Fraction(1, len(symbols)) for s in symbols} if leg['rule'] == 'EQUAL_WEIGHT' and not common_risk
                       else signal['weights'][leg['rule']])
            scale = Fraction(*leg['scale'])
            instructions[leg['id']] = {'kind': 'TARGET',
                'weights': {s: [(weights[s]*scale).numerator, (weights[s]*scale).denominator] for s in symbols},
                'signal': signal['diagnostics']}
        decisions.append({'day': entry, 'formation': day, 'known_ns': nanoseconds(known),
                          'decision_ns': nanoseconds(decision), 'open_ns': close(entry),
                          'kind': 'REFERENCE', 'instructions': instructions})
        signals.append({'formation': day, 'execution': entry, **signal['diagnostics']})
    terminal = grid['terminal']; previous = days[days.index(terminal)-1]
    known = datetime.combine(date.fromisoformat(previous)+timedelta(days=1), time(), tzinfo=tz)
    decision = known+timedelta(seconds=profile['decision_delay_seconds'])
    require(nanoseconds(known) < nanoseconds(decision) < close(terminal), 'SCHEDULED_TERMINAL_CLOCK')
    decisions.append({'day': terminal, 'formation': previous, 'known_ns': nanoseconds(known),
                      'decision_ns': nanoseconds(decision), 'open_ns': close(terminal), 'kind': 'REFERENCE',
                      'instructions': {leg['id']: {'kind': 'EXIT'} for leg in profile['legs']}})
    return {'profile': {'kind': 'REFERENCE_TARGETS', 'legs': [x['id'] for x in profile['legs']], 'end': terminal},
            'symbols': symbols, 'prices': {d: {s: {'close_micro': market['prices_micro'][d][s]} for s in symbols} for d in days},
            'grid': nav, 'decisions': decisions, 'signals': signals,
            'quote_basis': 'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT', 'clock_policy': 'PINNED_REFERENCE_EARLY_CLOSE'}


def evaluate_policy(simulation, profile, phase):
    require(phase in ('VALIDATION', 'FINAL'), 'SCHEDULED_EVALUATION_PHASE')
    legs, exact = evaluate_legs(simulation); by_id = {x['id']: x for x in legs}
    require(set(by_id) == {x['id'] for x in profile['legs']}, 'SCHEDULED_EVALUATION_LEGS')
    conditions = []
    for c in profile['criteria'] if phase == 'FINAL' else []:
        a = c['left_id']; b = c.get('right_id'); kind = c['kind']; passed = None
        with localcontext(context()):
            if kind == 'SR_DELTA_GE':
                av = by_id[a]['metrics']['sharpe_252_rf0']['value']; bv = by_id[b]['metrics']['sharpe_252_rf0']['value']
                if av is not None and bv is not None: passed = Decimal(av)-Decimal(bv) >= Decimal(c['threshold'])
            elif kind == 'TERMINAL_GE': passed = exact[a]['terminal'] >= exact[b]['terminal']
            elif kind == 'TERMINAL_GT': passed = exact[a]['terminal'] > exact[b]['terminal']
            elif kind == 'POSITIVE_GROWTH': passed = exact[a]['terminal'] > INITIAL_CENTS
            elif kind == 'DRAWDOWN_LE': passed = exact[a]['max_drawdown'] <= exact[b]['max_drawdown']
            elif kind == 'VOL_RATIO_BETWEEN':
                av = by_id[a]['metrics']['annual_vol_252']['value']; bv = by_id[b]['metrics']['annual_vol_252']['value']
                if av is not None and bv is not None and Decimal(bv) > 0:
                    passed = Decimal(c['lower']) <= Decimal(av)/Decimal(bv) <= Decimal(c['upper'])
        conditions.append({'id': c['id'], 'description': c['description'],
                           'status': 'UNAVAILABLE' if passed is None else 'MET' if passed else 'NOT_MET',
                           'reason': 'REQUIRED_METRIC_UNAVAILABLE' if passed is None else None})
    comparisons = []
    a = profile['primary_strategy']
    for b in (x['id'] for x in profile['legs'] if x['id'] != a):
        for key in ('terminal_nav_usd', 'net_cagr_act36525', 'sharpe_252_rf0', 'max_drawdown', 'total_cost_usd'):
            av = by_id[a]['metrics'][key]['value']; bv = by_id[b]['metrics'][key]['value']
            with localcontext(context()): delta = decimal_string(Decimal(av)-Decimal(bv)) if av is not None and bv is not None else None
            comparisons.append({'metric_id': key, 'left_id': a, 'right_id': b,
                                'result': metric(delta, None if delta is not None else 'PAIRED_METRIC_UNAVAILABLE')})
    outcome = ('DIAGNOSTIC_PHASE_NO_POINT_SCREEN' if phase != 'FINAL' else
               'INDETERMINATE' if any(c['status'] == 'UNAVAILABLE' for c in conditions) else
               'SUPPORTIVE_ON_THIS_LIMITED_SCREEN' if all(c['status'] == 'MET' for c in conditions) else
               'NOT_SUPPORTIVE_ON_THIS_LIMITED_SCREEN')
    return {'schema': 'polar.scheduled-reference-evaluation/1', 'phase': phase, 'legs': legs,
            'comparisons': comparisons, 'criteria': conditions, 'point_interpretation': outcome,
            'financial_acceptance': 'NOT_REVIEWED', 'exposure_denominator': len(simulation['legs'][0]['nav'])-1}
