"""Pure descriptive diagnostics over an already-saved exact-cent NAV ledger.

No source, model, policy, native execution, persistence, or point-screen decision.
"""
from datetime import date
from decimal import Decimal, DecimalException, localcontext
from fractions import Fraction

from .gym_contract import context, decimal_fraction, decimal_string, GymError


def _unavailable(reason, **extra):
    return {'value': None, 'status': 'UNAVAILABLE', 'reason': reason, **extra}


def _metric(value):
    try:
        with localcontext(context()):
            value = decimal_fraction(Fraction(value))
            return {'value': decimal_string(value), 'status': 'OK', 'reason': None}
    except (DecimalException, GymError, ArithmeticError):
        return _unavailable('NUMERICAL_OUTPUT_UNAVAILABLE')


def _decimal_metric(value):
    try:
        return {'value': decimal_string(value), 'status': 'OK', 'reason': None}
    except (DecimalException, GymError, ArithmeticError):
        return _unavailable('NUMERICAL_OUTPUT_UNAVAILABLE')


def _nav(tape):
    rows = tape.get('nav') if isinstance(tape, dict) else None
    if not isinstance(rows, list) or not rows:
        return None, 'MISSING_NAV_SERIES'
    required = {'date', 'nominal_ns', 'nav_cents'}
    if any(not isinstance(r, dict) or not required <= r.keys() for r in rows):
        return None, 'MISSING_REQUIRED_NAV_FIELDS'
    for row in rows:
        if type(row['nav_cents']) is not int or row['nav_cents'] <= 0:
            raise ValueError('SCHEDULED_DIAGNOSTIC_NAV_DOMAIN')
        if type(row['nominal_ns']) is not int or type(row['date']) is not str:
            raise ValueError('SCHEDULED_DIAGNOSTIC_NAV_CHRONOLOGY')
        try:
            valid = date.fromisoformat(row['date']).isoformat() == row['date']
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('SCHEDULED_DIAGNOSTIC_NAV_CHRONOLOGY')
    if any(a['date'] >= b['date'] or a['nominal_ns'] >= b['nominal_ns'] for a, b in zip(rows, rows[1:])):
        raise ValueError('SCHEDULED_DIAGNOSTIC_NAV_CHRONOLOGY')
    return rows, None


def _returns(nav):
    return [Fraction(b['nav_cents'], a['nav_cents']) - 1 for a, b in zip(nav, nav[1:])]


def _daily_tail(nav):
    returns = _returns(nav)
    n = len(returns)
    if not n:
        return _unavailable('INSUFFICIENT_RETURN_INTERVALS', n=0, k=0)
    ordered = sorted(enumerate(returns), key=lambda item: (item[1], item[0]))
    k = (n + 19) // 20
    tail_mean = sum((r for _, r in ordered[:k]), Fraction()) / k
    worst_index, worst = ordered[0]
    return {'status': 'OK', 'reason': None, 'n': n, 'k': k,
            'nominal_tail_fraction': '0.05', 'actual_tail_fraction': _metric(Fraction(k, n)),
            'lower_return_threshold': _metric(ordered[k-1][1]),
            'lower_tail_mean_return': _metric(tail_mean),
            'expected_shortfall_loss': _metric(-tail_mean),
            'sign_convention': 'RETURN_SIGNED; ES_LOSS_IS_NEGATIVE_OF_LOWER_TAIL_MEAN_NO_CLAMP',
            'worst_day': {'date': nav[worst_index+1]['date'], 'return': _metric(worst)},
            'tie_rule': 'EARLIEST_ORIGINAL_RETURN_DATE',
            'claim': 'FINITE_EMPIRICAL_SAVED_NET_RETURNS_NOT_POPULATION_TAIL_GUARANTEE'}


def _worst_horizon(nav, horizon):
    n = len(nav)-1
    if n < horizon:
        return _unavailable('INSUFFICIENT_RETURN_INTERVALS', horizon=horizon, intervals=n, windows=0)
    candidates = [(Fraction(nav[i+horizon]['nav_cents'], nav[i]['nav_cents'])-1, i)
                  for i in range(len(nav)-horizon)]
    value, start = min(candidates, key=lambda item: (item[0], item[1]))
    return {'status': 'OK', 'reason': None, 'horizon': horizon, 'windows': len(candidates),
            'start_date': nav[start]['date'], 'end_date': nav[start+horizon]['date'],
            'net_return': _metric(value), 'tie_rule': 'EARLIEST_START_DATE'}


def _elapsed(nav, left, right):
    return _metric(Fraction(nav[right]['nominal_ns']-nav[left]['nominal_ns'], 10**9))


def _drawdown(nav, *, latest_equal_peak=False):
    peak = nav[0]['nav_cents']; peak_index = 0
    depth = Fraction(); trough = 0; episode_peak = 0; underwater = 0
    for i, row in enumerate(nav):
        value = row['nav_cents']
        if value > peak or latest_equal_peak and value == peak:
            peak, peak_index = value, i
        drawdown = 1-Fraction(value, peak)
        if i and drawdown > 0:
            underwater += 1
        if drawdown > depth:  # Strict update keeps the first maximum-depth trough.
            depth, trough, episode_peak = drawdown, i, peak_index
    n = len(nav)-1
    common = {'maximum_depth': _metric(depth), 'postinitial_intervals': n,
              'underwater_intervals': underwater,
              'time_underwater_fraction': _metric(Fraction(underwater, n)) if n else _unavailable('INSUFFICIENT_RETURN_INTERVALS')}
    if depth == 0:
        return {**common, 'status': 'NO_DRAWDOWN', 'reason': None,
                'peak': None, 'trough': None, 'recovery': None,
                'recovery_status': 'NOT_APPLICABLE', 'peak_to_trough_intervals': None,
                'peak_to_trough_seconds': None, 'peak_to_recovery_intervals': None,
                'trough_to_recovery_intervals': None, 'peak_to_recovery_seconds': None,
                'censored_peak_to_terminal_intervals': None, 'censored_peak_to_terminal_seconds': None}
    target = nav[episode_peak]['nav_cents']
    recovered = next((i for i in range(trough+1, len(nav)) if nav[i]['nav_cents'] >= target), None)
    point = lambda i: {'date': nav[i]['date'], 'nav_cents': str(nav[i]['nav_cents'])}
    return {**common, 'status': 'RECOVERED' if recovered is not None else 'UNRECOVERED_BY_TERMINAL', 'reason': None,
            'peak': point(episode_peak), 'trough': point(trough),
            'recovery': point(recovered) if recovered is not None else None,
            'recovery_status': 'RECOVERED' if recovered is not None else 'UNRECOVERED_BY_TERMINAL',
            'peak_to_trough_intervals': trough-episode_peak,
            'peak_to_trough_seconds': _elapsed(nav, episode_peak, trough),
            'peak_to_recovery_intervals': recovered-episode_peak if recovered is not None else None,
            'trough_to_recovery_intervals': recovered-trough if recovered is not None else None,
            'peak_to_recovery_seconds': _elapsed(nav, episode_peak, recovered) if recovered is not None else None,
            'censored_peak_to_terminal_intervals': len(nav)-1-episode_peak if recovered is None else None,
            'censored_peak_to_terminal_seconds': _elapsed(nav, episode_peak, len(nav)-1) if recovered is None else None}


def _exposure(nav):
    sampled = nav[1:]
    if not sampled:
        return _unavailable('INSUFFICIENT_RETURN_INTERVALS', intervals=0)
    required = ('cash_cents', 'position_cents', 'positions')
    # Means exclude the anchor; maximum concentration includes its carried holdings.
    missing = sum(not all(k in r for k in required) for r in nav)
    if missing:
        return _unavailable('MISSING_EXPOSURE_ACCOUNTING_FIELDS', intervals=len(sampled), missing_rows=missing)
    symbols = set(sampled[0]['position_cents']) if isinstance(sampled[0]['position_cents'], dict) else None
    for r in nav:
        valid = (symbols is not None and isinstance(r['position_cents'], dict) and isinstance(r['positions'], dict)
                 and set(r['position_cents']) == symbols == set(r['positions'])
                 and type(r['cash_cents']) is int and r['cash_cents'] >= 0
                 and all(type(v) is int and v >= 0 for v in r['position_cents'].values())
                 and all(type(v) is int and v >= 0 for v in r['positions'].values())
                 and r['cash_cents']+sum(r['position_cents'].values()) == r['nav_cents'])
        if not valid:
            return _unavailable('INVALID_EXPOSURE_ACCOUNTING_FIELDS', intervals=len(sampled))
    n = len(sampled)
    means = {s: sum((Fraction(r['position_cents'][s], r['nav_cents']) for r in sampled), Fraction())/n
             for s in sorted(symbols)}
    maximum = max((Fraction(amount, r['nav_cents']) for r in nav for amount in r['position_cents'].values()), default=Fraction())
    cash = sum((Fraction(r['cash_cents'], r['nav_cents']) for r in sampled), Fraction())/n
    return {'status': 'OK', 'reason': None, 'intervals': n,
            'mean_asset_fractions': {s: _metric(v) for s, v in means.items()},
            'mean_cash_fraction': _metric(cash), 'mean_gross_exposure_fraction': _metric(sum(means.values(), Fraction())),
            'maximum_single_asset_fraction': _metric(maximum),
            'invested_close_fraction': _metric(Fraction(sum(any(r['positions'].values()) for r in sampled), n))}


def _calendar_months(nav, schedule_rows):
    if not isinstance(schedule_rows, list) or not schedule_rows or any(not isinstance(r, dict) or 'date' not in r for r in schedule_rows):
        return _unavailable('MISSING_SOURCE_REFERENCE_CALENDAR', complete_count=0, partial_count=0, months=[])
    dates = [r['date'] for r in schedule_rows]
    if any(type(d) is not str for d in dates) or dates != sorted(set(dates)):
        return _unavailable('INVALID_SOURCE_REFERENCE_CALENDAR', complete_count=0, partial_count=0, months=[])
    nav_by_date = {r['date']: i for i, r in enumerate(nav)}
    known_dates = set(dates)
    if any(r['date'] not in known_dates for r in nav):
        return _unavailable('SAVED_NAV_NOT_IN_SOURCE_CALENDAR', complete_count=0, partial_count=0, months=[])
    active_months = sorted({r['date'][:7] for r in nav[1:]})
    months = []
    for month in active_months:
        indices = [i for i, d in enumerate(dates) if d[:7] == month]
        visible = [i for i in range(1, len(nav)) if nav[i]['date'][:7] == month]
        reasons = []
        if not indices:
            reasons.append('MONTH_NOT_IN_SOURCE_CALENDAR')
        else:
            first, last = indices[0], indices[-1]
            if first == 0 or dates[first-1] not in nav_by_date:
                reasons.append('PRECEDING_REFERENCE_CLOSE_MISSING')
            if schedule_rows[last].get('month_end_in_reference_range') is not True:
                reasons.append('ACTUAL_MONTH_END_NOT_BOUND')
            if not all(dates[i] in nav_by_date for i in indices):
                reasons.append('INCOMPLETE_MONTH_NAV')
        if not reasons:
            anchor = nav_by_date[dates[first-1]]; end = nav_by_date[dates[last]]
            item = {'month': month, 'status': 'COMPLETE', 'reason': None, 'initial_date': nav[anchor]['date'],
                    'first_return_date': dates[first], 'end_date': dates[last], 'reference_intervals': len(indices),
                    'net_return': _metric(Fraction(nav[end]['nav_cents'], nav[anchor]['nav_cents'])-1)}
        else:
            anchor, end = visible[0]-1, visible[-1]
            item = {'month': month, 'status': 'PARTIAL', 'reason': '+'.join(reasons),
                    'initial_date': nav[anchor]['date'], 'first_return_date': nav[visible[0]]['date'],
                    'end_date': nav[end]['date'], 'reference_intervals': len(visible),
                    'net_return': _metric(Fraction(nav[end]['nav_cents'], nav[anchor]['nav_cents'])-1)}
        months.append(item)
    complete = [m for m in months if m['status'] == 'COMPLETE']
    if complete:
        # Compare exact endpoint ratios, never the projected Decimal strings.
        chosen = min(complete, key=lambda m: (Fraction(nav[nav_by_date[m['end_date']]]['nav_cents'], nav[nav_by_date[m['initial_date']]]['nav_cents'])-1, m['month']))
        worst = dict(chosen)
    else:
        worst = _unavailable('NO_COMPLETE_CALENDAR_MONTH', eligible_months=0)
    return {'status': 'OK', 'reason': None, 'complete_count': len(complete),
            'partial_count': len(months)-len(complete), 'months': months, 'worst_full_month': worst}


def _cumulative_fills(tape, row):
    fills = tape.get('fills')
    if not isinstance(fills, list):
        return None, 'MISSING_SAVED_FILL_LEDGER'
    cutoff = row.get('sample_ns')
    if type(cutoff) is not int:
        return None, 'MISSING_NAV_SAMPLE_CLOCK'
    totals = {'gross_exact_notional_micro': 0, 'gross_settled_notional_cents': 0, 'positive_fill_count': 0}
    for f in fills:
        if not isinstance(f, dict) or not all(type(f.get(k)) is int for k in ('at_ns', 'q', 'exact_notional_micro', 'settled_cents')):
            return None, 'MISSING_FILL_ACCOUNTING_FIELDS'
        if f['q'] <= 0 or f['exact_notional_micro'] < 0 or f['settled_cents'] < 0:
            return None, 'INVALID_FILL_ACCOUNTING_FIELDS'
        if f['at_ns'] <= cutoff:
            totals['gross_exact_notional_micro'] += f['exact_notional_micro']
            totals['gross_settled_notional_cents'] += f['settled_cents']
            totals['positive_fill_count'] += 1
    return totals, None


def _costs(tape, start, end):
    result = {'status': 'OK', 'reason': None, 'normalization_initial_nav_cents': str(start['nav_cents'])}
    for name in ('flat_cents', 'bps_cents'):
        if type(start.get(name)) is not int or type(end.get(name)) is not int:
            result[name] = _unavailable('MISSING_CUMULATIVE_FEE_FIELD')
        elif start[name] < 0 or end[name] < start[name]:
            result[name] = _unavailable('INVALID_CUMULATIVE_FEE_FIELD')
        else:
            result[name] = _metric(end[name]-start[name])
    if all(result[k]['status'] == 'OK' for k in ('flat_cents', 'bps_cents')):
        result['total_fee_usd'] = _metric(Fraction(end['flat_cents']-start['flat_cents']+end['bps_cents']-start['bps_cents'], 100))
    else:
        result['total_fee_usd'] = _unavailable('CUMULATIVE_FEES_UNAVAILABLE')
    a, ar = _cumulative_fills(tape, start); b, br = _cumulative_fills(tape, end)
    if ar or br:
        for name in ('gross_exact_notional_usd', 'gross_settled_notional_usd', 'positive_fill_count', 'gross_notional_over_initial'):
            result[name] = _unavailable(ar or br)
    else:
        gross = b['gross_exact_notional_micro']-a['gross_exact_notional_micro']
        result['gross_exact_notional_usd'] = _metric(Fraction(gross, 1000000))
        result['gross_settled_notional_usd'] = _metric(Fraction(b['gross_settled_notional_cents']-a['gross_settled_notional_cents'], 100))
        result['positive_fill_count'] = _metric(b['positive_fill_count']-a['positive_fill_count'])
        result['gross_notional_over_initial'] = _metric(Fraction(gross, start['nav_cents']*10000))
    if any(isinstance(v, dict) and v.get('status') == 'UNAVAILABLE' for v in result.values()):
        result['status'] = 'PARTIAL_UNAVAILABLE'; result['reason'] = 'SAVED_ACCOUNTING_FIELDS_UNAVAILABLE'
    return result


def _statistics(nav):
    returns = _returns(nav); n = len(returns)
    if not n:
        return _unavailable('INSUFFICIENT_RETURN_INTERVALS', n=0)
    mean = sum(returns, Fraction())/n
    variance = sum(((r-mean)**2 for r in returns), Fraction())/(n-1) if n >= 2 else None
    try:
        with localcontext(context()):
            root252 = Decimal(252).sqrt()
            sd = decimal_fraction(variance).sqrt() if variance is not None else None
            vol = _decimal_metric(root252*sd) if sd is not None else _unavailable('INSUFFICIENT_INTERVALS')
            sr = _decimal_metric((root252*decimal_fraction(mean))/sd) if sd else _unavailable('ZERO_VARIANCE' if sd == 0 else 'INSUFFICIENT_INTERVALS')
    except (DecimalException, GymError, ArithmeticError):
        vol = sr = _unavailable('NUMERICAL_STATISTIC_UNAVAILABLE')
    try:
        with localcontext(context()):
            years = decimal_fraction(Fraction(nav[-1]['nominal_ns']-nav[0]['nominal_ns'], 31557600*10**9))
            cagr = _decimal_metric((decimal_fraction(Fraction(nav[-1]['nav_cents'], nav[0]['nav_cents'])).ln()/years).exp()-1)
    except (DecimalException, GymError, ArithmeticError):
        cagr = _unavailable('NUMERICAL_STATISTIC_UNAVAILABLE')
    return {'status': 'OK', 'reason': None, 'n': n, 'initial_nav_cents': str(nav[0]['nav_cents']),
            'terminal_nav_cents': str(nav[-1]['nav_cents']),
            'terminal_nav_usd': _metric(Fraction(nav[-1]['nav_cents'], 100)),
            'net_total_return': _metric(Fraction(nav[-1]['nav_cents'], nav[0]['nav_cents'])-1),
            'net_cagr_act36525': cagr, 'daily_mean_return': _metric(mean),
            'daily_sample_variance': _metric(variance) if variance is not None else _unavailable('INSUFFICIENT_INTERVALS'),
            'annual_vol_252': vol, 'sharpe_252_rf0': sr,
            'max_drawdown': _drawdown(nav)['maximum_depth']}


def _holdings(row):
    fields = ('cash_cents', 'positions', 'position_cents')
    if not all(k in row for k in fields) or not isinstance(row['positions'], dict) or not isinstance(row['position_cents'], dict):
        return _unavailable('MISSING_SAVED_INITIAL_HOLDINGS')
    if (type(row['cash_cents']) is not int or row['cash_cents'] < 0
            or set(row['positions']) != set(row['position_cents'])
            or not all(type(v) is int and v >= 0 for v in row['positions'].values())
            or not all(type(v) is int and v >= 0 for v in row['position_cents'].values())
            or row['cash_cents']+sum(row['position_cents'].values()) != row['nav_cents']):
        return _unavailable('INVALID_SAVED_INITIAL_HOLDINGS')
    return {'status': 'OK', 'reason': None, 'cash_cents': str(row['cash_cents']),
            'positions': {s: str(v) for s, v in sorted(row['positions'].items())},
            'position_cents': {s: str(v) for s, v in sorted(row['position_cents'].items())}}


def evaluate_segment(tape, first, last):
    """Requested return dates inclusive; preserve the immediately preceding NAV."""
    nav, reason = _nav(tape)
    if reason:
        return _unavailable(reason, first_return_date=first, last_return_date=last)
    by_date = {r['date']: i for i, r in enumerate(nav)}
    if first not in by_date or last not in by_date or by_date[first] > by_date[last]:
        return _unavailable('SUBPERIOD_BOUNDARY_MISSING', first_return_date=first, last_return_date=last)
    begin, end = by_date[first], by_date[last]
    if begin == 0:
        return _unavailable('PRECEDING_REFERENCE_CLOSE_MISSING', first_return_date=first, last_return_date=last)
    selected = nav[begin-1:end+1]
    return {'status': 'OK', 'reason': None, 'first_return_date': first, 'last_return_date': last,
            'initial_date': selected[0]['date'], 'intervals': len(selected)-1,
            'initial_holdings': _holdings(selected[0]), 'terminal_holdings': _holdings(selected[-1]),
            'metrics': _statistics(selected), 'costs': _costs(tape, selected[0], selected[-1]),
            'exposure': _exposure(selected), 'drawdown': _drawdown(selected),
            'account_treatment': 'CARRIED_SAVED_HOLDINGS_NO_RESET_NO_EXTRA_LIQUIDATION'}


def diagnose(tape, schedule_rows, *, subperiods=()):
    """Return deterministic JSON-safe descriptions, never a point/financial verdict."""
    nav, reason = _nav(tape)
    if reason:
        return {'schema': 'polar.scheduled-saved-diagnostics/1', 'status': 'UNAVAILABLE', 'reason': reason,
                'daily_tail': _unavailable(reason), 'worst_horizons': {str(h): _unavailable(reason) for h in (1, 21, 63)},
                'calendar_months': _unavailable(reason), 'drawdown': _unavailable(reason),
                'exposure': _unavailable(reason), 'subperiods': [_unavailable(reason, first_return_date=a, last_return_date=b) for a, b in subperiods]}
    return {'schema': 'polar.scheduled-saved-diagnostics/1', 'status': 'OK', 'reason': None,
            'leg_id': tape.get('id'), 'saved_nav_points': len(nav), 'return_intervals': len(nav)-1,
            'daily_tail': _daily_tail(nav), 'worst_horizons': {str(h): _worst_horizon(nav, h) for h in (1, 21, 63)},
            'calendar_months': _calendar_months(nav, schedule_rows), 'drawdown': _drawdown(nav),
            'exposure': _exposure(nav), 'subperiods': [evaluate_segment(tape, a, b) for a, b in subperiods],
            'factor_attribution': {'status': 'NOT_ESTIMATED', 'reason': 'NO_QUALIFIED_ALIGNED_FACTOR_METHOD_FOR_THIS_COMPARISON'},
            'scope': 'DESCRIPTIVE_SAVED_NET_LEDGER_ONLY_NO_POLICY_MODEL_NATIVE_OR_SOURCE_CALL'}
