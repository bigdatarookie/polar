"""Closed FOMC geometry and saved algebra for Quant's frozen calendar policy.

No source IO/native calls on import. Geometry consumes dates only. Economic
operands enter only in the explicitly called post-FIRST_START plan/evaluator.
"""
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction as F
from pathlib import Path
import hashlib

from .ci_research import INITIAL_CENTS, require
from .gym_contract import canonical, sha
from .event_native import (EventPlan, FomcEventPlan, ReferenceClose, DecisionPoint,
                           eligible_closes, sma_vti_category, LEGS, COSTS)
from .event_study import (tail_loss, interval, clause, drawdown_exact, safe_statistics,
                          safe_diagnostics, diagnostics_tape)

QUESTION = 'FOMC-CALENDAR-ONLY-REFERENCE-01'
AUTHOR_REVISION = '69ec8999c89cc926be6dba0ab225e31f60eac03b'
POLICY_SHA = '34881097ad5d48d144ee14ceb5bd45fe8b3272a982f40da47a527c259f93cfff'
CONTRACT_SHA = '328eb8c606320c8c77933290bae0663d1bd537f6586dd4905d84606871db51db'
PROPOSAL_SHA = 'ba7ec7f0b051a001082d5ca75be21482fe372a3e726090489b2bcfa1fe96d5e0'
INDEX_SHA = '09d3e5b9b4a123555290c454def9dbec3afb6ca669ed46ca7cf1b4023875c7dc'
PHASES = {'VALIDATION': ('2021-01-04', '2022-12-30'),
          'FINAL': ('2023-01-03', '2026-11-06')}
MAPPING = {'CALENDAR_PROTECTION': 'CALENDAR_HALF', 'FULL_VTI': 'FULL_VTI',
           'STATIC_50': 'MONTHLY_FIXED_HALF', 'SMA200': 'SMA200', 'FULL_BIL': 'FULL_BIL'}


def author_policy():
    from research_candidates.quant_a_fomc_calendar import policy
    root = Path(__file__).resolve().parents[2]
    for name, expected in [('policy.py', POLICY_SHA), ('author_contract.json', CONTRACT_SHA)]:
        path = root/'research_candidates/quant_a_fomc_calendar'/name
        require(not path.is_symlink() and path.resolve() == path and
                hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'FOMC_AUTHOR_BLOB')
    require(Path(policy.__file__).resolve() == root/'research_candidates/quant_a_fomc_calendar/policy.py',
            'FOMC_STATIC_AUTHOR_IMPORT')
    return policy


def ns(t):
    delta = t.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days*86400 + delta.seconds)*10**9 + delta.microseconds*1000


def stamp(t):
    return t.astimezone(timezone.utc).isoformat()


def geometry(source_rows, schedule, phases, ny):
    """Preserve every index row; never inspect a price to select an episode."""
    days = [r['date'] for r in schedule]
    closes = [datetime.fromisoformat(r['reference_close_utc'].replace('Z', '+00:00')) for r in schedule]
    require(days == sorted(set(days)) and all(a < b for a, b in zip(closes, closes[1:])), 'FOMC_SCHEDULE')
    require(len({r['event_id'] for r in source_rows}) == len(source_rows), 'FOMC_EVENT_ID_CENSUS')
    records = []
    for row in source_rows:
        result = {'event_id': row['event_id'], 'source_clock_status': row['clock_status'],
                  'source_classification': row['regular_exception_cancel_reschedule_classification'],
                  'status': 'SOURCE_UNRESOLVED_NO_ACTION'}
        records.append(result)
        try:
            day = date.fromisoformat(row['statement_date'])
        except (ValueError, TypeError, KeyError):
            continue
        phase = next((p for p, (lo, hi) in phases.items() if lo <= day.isoformat() <= hi), None)
        result.update(phase=phase, statement_date=day.isoformat())
        if (row['regular_exception_cancel_reschedule_classification'] != 'REGULAR_SCHEDULED_POLICY_STATEMENT_ROW'
            or row.get('clock_basis') != 'MODEL_CLOCK_FROM_OFFICIAL_STANDING_SCHEDULE_CONVENTION'
            or not row.get('statement_url') or row.get('scheduled_clock') != '14:00'
            or row.get('scheduled_zone') != 'America/New_York' or phase is None):
            continue
        prior = [d for d in days if d < day.isoformat()]
        if not prior:
            result['status'] = 'PREVIOUS_REFERENCE_SESSION_UNAVAILABLE'
            continue
        cutoff = datetime.combine(date.fromisoformat(prior[-1]), time(15), tzinfo=ny)
        decision = cutoff + timedelta(seconds=60)
        statement = datetime.combine(day, time(14), tzinfo=ny)
        entry = next((q for q in closes if q > decision), None)
        labels = [q for q in closes if q >= statement]
        result.update(cutoff_ns=ns(cutoff), decision_ns=ns(decision), statement_ns=ns(statement),
                      entry_ns=ns(entry) if entry else None)
        if entry is None or entry >= statement:
            result['status'] = 'TIMING_INELIGIBLE_NO_ACTION'
            continue
        if len(labels) < 2:
            result['status'] = 'LABEL_HORIZON_UNAVAILABLE_NO_ACTION'
            continue
        label = labels[1]; rd = label + timedelta(seconds=60)
        rq = next((q for q in closes if q > rd), None)
        lo, hi = phases[phase]
        require(lo in days and hi in days, 'FOMC_COMPLETE_PHASE_GRID')
        initial, terminal = closes[days.index(lo)], closes[days.index(hi)]
        first = next((q for q in closes if q > initial + timedelta(seconds=60)), None)
        result.update(label_ns=ns(label), return_decision_ns=ns(rd), return_ns=ns(rq) if rq else None)
        if rq is None or first is None or entry < first or not initial < entry < label < rq < terminal:
            result['status'] = 'PHASE_BOUNDARY_INELIGIBLE_NO_ACTION'
            continue
        result['status'] = 'ELIGIBLE_MODEL_CLOCK_ONLY'
    clusters = {}
    for phase in phases:
        groups = []
        for row in sorted((r for r in records if r.get('phase') == phase and
                           r['status'] == 'ELIGIBLE_MODEL_CLOCK_ONLY'), key=lambda r: (r['entry_ns'], r['event_id'])):
            if groups and row['entry_ns'] <= groups[-1]['return_ns']:
                group = groups[-1]
                group['members'].append(row['event_id']); group['members'].sort()
                group['label_ns'] = max(group['label_ns'], row['label_ns'])
                group['return_ns'] = max(group['return_ns'], row['return_ns'])
                group['return_decision_ns'] = max(group['return_decision_ns'], row['return_decision_ns'])
            else:
                groups.append({'members': [row['event_id']], 'entry_ns': row['entry_ns'],
                               'decision_ns': row['decision_ns'], 'label_ns': row['label_ns'],
                               'return_decision_ns': row['return_decision_ns'], 'return_ns': row['return_ns']})
        for group in groups:
            group['id'] = '+'.join(group['members'])
        clusters[phase] = groups
    return {'schema': 'polar.fomc-calendar-geometry/1', 'records': records, 'clusters': clusters}


def plan_phase(market, role_rows, calendar, phase, bounds, account_scope, input_id, protocol_id):
    """Invoke only the statically packaged author, once per phase before costs."""
    author = author_policy()
    rows = tuple(ReferenceClose(**{**r, 'price_micro': market['prices_micro'][r['date']][r['symbol']]})
                 for r in role_rows)
    nav = tuple(r.close_ns for r in rows if r.symbol == 'VTI' and r.role == 'NAV')
    require(nav and all(bounds[0] <= r.date <= bounds[1] for r in rows if r.role == 'NAV'), 'FOMC_PHASE_ROLES')
    dt = lambda n: datetime.fromtimestamp(n//10**9, timezone.utc)
    pairs = author.daily_decisions(tuple(dt(n) for n in nav))
    daily = tuple(DecisionPoint(ns(d), ns(q)) for d, q in pairs)
    groups = calendar['clusters'][phase]
    episodes = tuple(author.Episode(g['id'], dt(g['entry_ns']), dt(g['label_ns']), dt(g['return_ns'])) for g in groups)
    instructions = []; signals = []
    def record(leg, d, q, decision):
        weights = None if decision.weights is None else {s: [w.numerator, w.denominator] for s, w in decision.weights}
        instructions.append({'leg': leg, 'decision_ns': d, 'q_ns': q, 'kind': decision.kind,
                             'weights': weights, 'reason': decision.reason, 'observed_state': decision.observed_state})
    for leg in ('FULL_VTI', 'STATIC_50', 'FULL_BIL'):
        for i, point in enumerate(daily):
            d, q = point.decision_ns, point.q_ns
            formation = dt(nav[i]).date()
            month_end = dt(nav[i+1]).date().month != formation.month
            record(leg, d, q, author.fixed_target(MAPPING[leg], first=i == 0,
                   month_end_formation=month_end, terminal=i == len(daily)-1))
    previous = None
    for i, point in enumerate(daily):
        if i == len(daily)-1:
            record('SMA200', point.decision_ns, point.q_ns, author.Instruction('EXIT', None, None, 'COMMON_TERMINAL'))
            continue
        eligible = eligible_closes(rows, point.decision_ns, 'VTI')
        values = tuple(author.Close(dt(r.close_ns), dt(r.available_ns), F(r.price_micro, 10**6)) for r in eligible)
        result = author.sma_target(values, dt(point.decision_ns), previous)
        record('SMA200', point.decision_ns, point.q_ns, result); previous = result.observed_state
        signals.append(sma_vti_category(rows, point.decision_ns))
    # INIT and calendar clocks remain distinct. Future entries cannot advance D.
    previous = None
    points = [(daily[0].decision_ns, daily[0].q_ns, ())]
    for group in groups:
        points += [(group['decision_ns'], group['entry_ns'], episodes),
                   (group['return_decision_ns'], group['return_ns'], episodes)]
    for d, q, selected in sorted(points, key=lambda x: (x[0], x[1])):
        result = author.calendar_target(dt(d), dt(q), selected, previous)
        record('CALENDAR_PROTECTION', d, q, result); previous = result.observed_state
    end = daily[-1]
    record('CALENDAR_PROTECTION', end.decision_ns, end.q_ns, author.Instruction('EXIT', None, None, 'COMMON_TERMINAL'))
    instructions.sort(key=lambda r: (r['leg'], r['decision_ns'], r['q_ns']))
    return FomcEventPlan(account_scope, input_id, sha(canonical(calendar)), protocol_id, rows, nav,
                         daily, (), nav, tuple(instructions), tuple(signals), POLICY_SHA)


def verify_account(account, geometry_value, phase, role_rows=None):
    from .event_native import verify_saved_event_witnesses, validate_fomc_steps
    verify_saved_event_witnesses(account)
    steps = account['fomc_steps']; validate_fomc_steps(steps, account['leg'], account['nav_role_grid'])
    require(account['fomc_policy_sha256'] == POLICY_SHA and
            account['fomc_steps_sha256'] == sha(canonical(steps)), 'FOMC_SAVED_PLAN_HASH')
    decisions = [r for r in account['decisions'] if r.get('fomc_instruction') is not None]
    require([r['fomc_instruction'] for r in decisions] == list(steps), 'FOMC_SAVED_AUTHORED_CENSUS')
    by_id = {p.intent_id: p for p in account['issued_intents']}
    for row in decisions:
        step = row['fomc_instruction']
        require(row['decision_ns'] == step['decision_ns'], 'FOMC_SAVED_DECISION_CLOCK')
        if row.get('pending_id') in by_id and step['kind'] != 'HOLD':
            intent = by_id[row['pending_id']]
            require((intent.decision_ns, intent.q_ns) == (step['decision_ns'], step['q_ns']), 'FOMC_SAVED_EXECUTION_CLOCK')
            weights = {'BIL': [intent.bil_weight.numerator, intent.bil_weight.denominator],
                       'VTI': [intent.vti_weight.numerator, intent.vti_weight.denominator]}
            require(step['kind'] == 'EXIT' and not intent.bil_weight and not intent.vti_weight or
                    step['kind'] == 'TARGET' and step['weights'] == weights, 'FOMC_SAVED_TARGET')
    if account['leg'] == 'CALENDAR_PROTECTION':
        allowed = {(g['decision_ns'], g['entry_ns']) for g in geometry_value['clusters'][phase]} | {
            (g['return_decision_ns'], g['return_ns']) for g in geometry_value['clusters'][phase]}
        allowed |= {(steps[0]['decision_ns'], account['nav_role_grid'][1]),
                    (account['nav_role_grid'][-2]+60*10**9, account['nav_role_grid'][-1])}
        require(all((s['decision_ns'], s['q_ns']) in allowed for s in steps), 'FOMC_SAVED_GEOMETRY_CLOCK')
    # Recheck saved instructions from frozen semantics, without invoking policy.
    grid = account['nav_role_grid']; dates = account['nav_role_dates']; expected = []
    def add(d, q, kind, weights, reason, observed=None):
        expected.append({'leg': account['leg'], 'decision_ns': d, 'q_ns': q, 'kind': kind,
                         'weights': weights, 'reason': reason, 'observed_state': observed})
    normal = {'BIL': [0, 1], 'VTI': [1, 1]}
    half = {'BIL': [1, 2], 'VTI': [1, 2]}
    bills = {'BIL': [1, 1], 'VTI': [0, 1]}
    if account['leg'] in ('FULL_VTI', 'FULL_BIL', 'STATIC_50'):
        weights = {'FULL_VTI': normal, 'FULL_BIL': bills, 'STATIC_50': half}[account['leg']]
        for i, (a, b) in enumerate(zip(grid, grid[1:])):
            terminal = i == len(grid)-2
            target = i == 0 or account['leg'] == 'STATIC_50' and dates[i][:7] != dates[i+1][:7]
            add(a+60*10**9, b, 'EXIT' if terminal else 'TARGET' if target else 'HOLD',
                None if terminal or not target else weights,
                'COMMON_TERMINAL' if terminal else 'INITIAL' if i == 0 else
                'MONTH_END_FORMATION' if target else 'NO_REBALANCE')
    elif account['leg'] == 'SMA200':
        require(len(account['sma']) == len(grid)-2, 'FOMC_SAVED_SMA_CENSUS')
        previous = None
        for i, signal in enumerate(account['sma']):
            d = grid[i]+60*10**9; q = grid[i+1]
            require(signal['decision_ns'] == d, 'FOMC_SAVED_SMA_CLOCK')
            if role_rows is not None:
                eligible = [r for r in role_rows if r['symbol'] == 'VTI' and r['close_ns'] < d and
                            r['available_ns'] is not None and r['available_ns'] <= d]
                require(signal['eligible_count'] == len(eligible), 'FOMC_SAVED_SMA_PREFIX_CENSUS')
                if signal['category'] != 'UNAVAILABLE':
                    require(tuple(signal['source_ids']) == tuple(r['source_id'] for r in eligible[-200:]),
                            'FOMC_SAVED_SMA_LATEST_PREFIX')
            if signal['category'] == 'UNAVAILABLE':
                add(d, q, 'HOLD', None, 'INSUFFICIENT_ELIGIBLE_PREFIX', previous)
            else:
                observed = signal['category'] == 'NORMAL'; target = previous is None or observed != previous
                add(d, q, 'TARGET' if target else 'HOLD', normal if observed and target else
                    bills if target else None, 'FIRST_OBSERVATION' if previous is None else
                    'STATE_CHANGE' if target else 'UNCHANGED_OBSERVED_STATE', observed)
                previous = observed
        add(grid[-2]+60*10**9, grid[-1], 'EXIT', None, 'COMMON_TERMINAL')
    else:
        previous = None
        groups = geometry_value['clusters'][phase]
        clocks = [(grid[0]+60*10**9, grid[1], False)]
        for g in groups:
            clocks += [(g['decision_ns'], g['entry_ns'], True), (g['return_decision_ns'], g['return_ns'], False)]
        for d, q, observed in sorted(clocks):
            target = previous is None or observed != previous
            add(d, q, 'TARGET' if target else 'HOLD', half if observed and target else normal if target else None,
                'FIRST_OBSERVATION' if previous is None else 'STATE_CHANGE' if target else 'UNCHANGED_OBSERVED_STATE', observed)
            previous = observed
        add(grid[-2]+60*10**9, grid[-1], 'EXIT', None, 'COMMON_TERMINAL')
    require(list(steps) == expected, 'FOMC_SAVED_FROZEN_INSTRUCTIONS')
    if role_rows is not None:
        require(tuple(r['date'] for r in role_rows if r['symbol'] == 'VTI' and r['role'] == 'NAV') == tuple(dates),
                'FOMC_SAVED_ROLE_GRID')
        for w in account['sizing'].values():
            for symbol, source in w['source_rows'].items():
                eligible = [r for r in role_rows if r['symbol'] == symbol and r['close_ns'] < w['decision_ns'] and
                            r['available_ns'] is not None and r['available_ns'] <= w['decision_ns']]
                require(eligible and {k: v for k, v in source.items() if k != 'price_micro'} == eligible[-1],
                        'FOMC_SAVED_LATEST_SIZING_SOURCE')
    return {'status': 'VERIFIED_FOMC_SAVED_ACCOUNT', 'source_reads': 0, 'native_calls': 0}


def material_fraction(nav):
    if len(nav) < 2 or any(r['nav_cents'] <= 0 for r in nav):
        return None
    return F(sum(4*r['position_cents']['VTI'] < 3*r['nav_cents'] for r in nav[:-1]), len(nav)-1)


def extra_fee_budget(strategy_nav, benchmark_nav):
    fee = lambda nav: nav[-1]['flat_cents']+nav[-1]['bps_cents']
    extra = max(0, fee(strategy_nav)-fee(benchmark_nav))
    days = (date.fromisoformat(strategy_nav[-1]['date'])-date.fromisoformat(strategy_nav[0]['date'])).days
    return extra, F(INITIAL_CENTS, 200)*F(days*4, 1461)


def evaluate_phase(accounts, calendar, phase, role_rows=None, account_scope=None):
    require(phase in ('VALIDATION', 'FINAL'), 'FOMC_PHASE')
    pairs = {(a['leg'], a['cost_id']): a for a in accounts}
    require(len(accounts) == len(pairs) == len(LEGS)*len(COSTS) and
            set(pairs) == {(leg, cost) for leg in LEGS for cost, _ in COSTS}, 'FOMC_ACCOUNT_CENSUS')
    for account in accounts:
        verify_account(account, calendar, phase, role_rows)
        if role_rows is not None:
            from .event_native import key
            input_id = role_rows[0]['source_id'].rsplit('/', 2)[0]
            require(account_scope is not None and account['context'].input_id == input_id and
                    account['context'].calendar_id == sha(canonical(calendar)) and
                    account['context'].protocol_id == QUESTION and
                    account['context'].leg_id == account['leg'] and account['context'].cost_id == account['cost_id'] and
                    account['context'].account_id == key([account_scope, account['leg'], account['cost_id'],
                        input_id, sha(canonical(calendar)), QUESTION]), 'FOMC_SAVED_EXTERNAL_CONTEXT')
            require(all(r['source_id'] == input_id+'/'+r['symbol']+'/'+r['date'] for r in role_rows),
                    'FOMC_SAVED_SOURCE_LOCATORS')
    for leg in LEGS:
        require(pairs[leg, 'BASE']['fomc_steps'] == pairs[leg, 'FRESH_2X']['fomc_steps'] and
                pairs[leg, 'BASE']['sma'] == pairs[leg, 'FRESH_2X']['sma'], 'FOMC_COST_SHARED_PHASE_PLAN')
    units = [{'id': g['id'], 'members': g['members'], 'anchor_ns': g['entry_ns'], 'r2_ns': g['label_ns']}
             for g in calendar['clusters'][phase]]
    details = {}; outputs = {}
    for pair, account in pairs.items():
        cluster_rows = [interval(account, u) for u in units]
        tail = tail_loss(cluster_rows, [u['id'] for u in units])
        if not units:
            tail.update(reason='UNAVAILABLE_NO_COMPLETE_CLUSTERS')
        risk_units = [{'id': g['id'], 'members': g['members'], 'anchor_ns': g['entry_ns'],
                       'r2_ns': g['return_ns']} for g in calendar['clusters'][phase]]
        risk_cycles = [interval(account, u) for u in risk_units]
        nav = account['nav']; valid = all(r['nav_cents'] > 0 for r in nav)
        details['/'.join(pair)] = {'clusters': cluster_rows, 'tail': tail, 'statistics': safe_statistics(nav),
            'actual_material_fraction': material_fraction(nav),
            'ordinary_ratios_valid': valid, 'all_phase_intervals': len(nav)-1,
            'risk_cycles_including_return_costs': risk_cycles,
            'return_lag_ns': {g['id']: g['return_ns']-g['label_ns'] for g in calendar['clusters'][phase]},
            'intended_calendar_fraction': F(sum(any(g['entry_ns'] <= r['nominal_ns'] < g['return_ns']
                for g in calendar['clusters'][phase]) for r in nav[:-1]), len(nav)-1),
            'desired_actual_mismatch_intervals': [r['nominal_ns'] for r in nav[:-1] if r['nav_cents'] > 0 and
                (r['desired'] == 'REDUCED') != (4*r['position_cents']['VTI'] < 3*r['nav_cents'])],
            'saved_diagnostics': safe_diagnostics(diagnostics_tape(account), [{'date': r['date']} for r in nav])}
    for cost, _ in COSTS:
        strategy = pairs['CALENDAR_PROTECTION', cost]; benchmark = pairs['FULL_VTI', cost]
        s = details['CALENDAR_PROTECTION/'+cost]; b = details['FULL_VTI/'+cost]
        st, bt = strategy['nav'][-1]['nav_cents'], benchmark['nav'][-1]['nav_cents']
        positive = s['ordinary_ratios_valid'] and b['ordinary_ratios_valid']
        ss, bs = s['tail']['value'], b['tail']['value']
        protection = clause('PROTECTION', None if ss is None or bs is None or bs == 0 else 5*ss <= 4*bs,
                            reason='UNAVAILABLE_BENCHMARK_ES_ZERO' if bs == 0 else
                            'UNAVAILABLE_EVENT_LOSS' if ss is None or bs is None else None)
        extra, allowance = extra_fee_budget(strategy['nav'], benchmark['nav'])
        material = s['actual_material_fraction']
        clauses = [protection, clause('WEALTH', 20*st >= 19*bt), clause('GROWTH', st > INITIAL_CENTS),
                   clause('DRAWDOWN', drawdown_exact(strategy['nav']) <= drawdown_exact(benchmark['nav'])),
                   clause('EXTRA_FEES', extra <= allowance, extra_cents=extra, allowance_cents=allowance),
                   clause('MATERIAL_TIME', None if material is None else material <= F(1, 4),
                          reason='UNAVAILABLE_NONPOSITIVE_NAV' if material is None else None)]
        if not positive:
            for c in clauses:
                if c['id'] in ('PROTECTION', 'WEALTH', 'GROWTH', 'DRAWDOWN', 'MATERIAL_TIME'):
                    c.update(status='UNAVAILABLE', reason='UNAVAILABLE_NONPOSITIVE_NAV')
        statuses = [c['status'] for c in clauses]
        screen = ('NOT_SUPPORTED' if 'NOT_MET' in statuses else 'INDETERMINATE' if 'UNAVAILABLE' in statuses
                  else 'CONDITIONAL_POINT_SCREEN_MET') if phase == 'FINAL' else 'DIAGNOSTIC_ONLY_NO_PREFERENCE_SCREEN'
        benign = [r['id'] for r in b['clusters'] if r['status'] == 'OK' and r['return'] >= 0]
        outputs[cost] = {'clauses': clauses, 'producer_screen': screen, 'false_alarm_cluster_ids': benign}
    return {'schema': 'polar.fomc-private-evaluation/1', 'phase': phase, 'accounts': details,
            'cost_results': outputs, 'financial_acceptance': 'NOT_REVIEWED',
            'source_reads': 0, 'native_calls': 0, 'writes': 0}
