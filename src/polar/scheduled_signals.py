"""Pure causal scheduled-policy targets from a supplied historical price prefix.

No source access, fitting, execution, or account accounting lives here.  Internal
weights are exact Fractions; diagnostic numbers are canonical strings.
"""
from decimal import Decimal, ROUND_FLOOR, localcontext
from fractions import Fraction
import math

from .gym_contract import context


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _history(prices, symbols, intervals):
    _require(type(symbols) is list and bool(symbols) and
             all(type(s) is str and bool(s) for s in symbols) and
             len(set(symbols)) == len(symbols), 'SCHEDULED_SYMBOLS')
    _require(type(intervals) is int and 1 <= intervals <= 10000,
             'SCHEDULED_LOOKBACK')
    _require(type(prices) is list and len(prices) >= intervals + 1,
             'SCHEDULED_INSUFFICIENT_HISTORY')
    rows = prices[-(intervals + 1):]
    for row in rows:
        _require(type(row) is dict and set(row) == set(symbols),
                 'SCHEDULED_PRICE_SYMBOLS')
        _require(all(type(row[s]) is int and row[s] > 0 for s in symbols),
                 'SCHEDULED_PRICE_DOMAIN')
    return rows


def _rational(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def trend_targets(prices, symbols, *, lookback=252, skip=21):
    """Fixed equal sleeves above zero absolute trend, plus relative-MOM control."""
    _require(type(skip) is int and type(lookback) is int and 0 <= skip < lookback,
             'SCHEDULED_MOMENTUM_ENDPOINTS')
    rows = _history(prices, symbols, lookback)
    left, right = rows[0], rows[-1 - skip]
    momenta = {s: Fraction(right[s], left[s]) - 1 for s in symbols}
    winner = max(symbols, key=lambda s: momenta[s])
    if momenta[winner] <= 0:
        winner = None
    sleeves = {s: Fraction(1, len(symbols)) if momenta[s] > 0 else Fraction()
               for s in symbols}
    momentum = {s: Fraction(int(s == winner)) for s in symbols}
    return {'weights': {'SLEEVES': sleeves, 'MOMENTUM': momentum},
            'diagnostics': {'kind': 'ABSOLUTE_MOMENTUM_SLEEVES',
                            'lookback_intervals': lookback, 'skip_intervals': skip,
                            'endpoint_offsets': {'left': -lookback, 'right': -skip},
                            'left_prices_micro': dict(left), 'right_prices_micro': dict(right),
                            'momenta': {s: _rational(momenta[s]) for s in symbols},
                            'momentum_selected_symbol': winner,
                            'sleeve_cash_weight': _rational(1 - sum(sleeves.values()))}}


def _micro_float(value):
    # Convert the exact price token once, rather than rounded float(micro)/1e6.
    try:
        token = f'{value // 1000000}.{value % 1000000:06d}'
        result = float(token)
    except (ValueError, OverflowError):
        raise ValueError('SCHEDULED_BINARY64_PRICE') from None
    _require(math.isfinite(result) and result > 0, 'SCHEDULED_BINARY64_PRICE')
    return result


def _risk(weights, covariance):
    try:
        variance = 252 * math.fsum(weights[i] * covariance[i][j] * weights[j]
                                   for i in range(len(weights))
                                   for j in range(len(weights)))
        _require(math.isfinite(variance) and variance > 0, 'SCHEDULED_NONPOSITIVE_RISK')
        result = math.sqrt(variance)
    except (OverflowError, ZeroDivisionError):
        raise ValueError('SCHEDULED_NONFINITE_RISK') from None
    _require(math.isfinite(result) and result > 0, 'SCHEDULED_NONPOSITIVE_RISK')
    return result


def inverse_vol_targets(prices, symbols, *, window=60, annual_cap=0.10):
    """Three monthly allocations at a shared causal covariance forecast risk."""
    _require(type(window) is int and window >= 2, 'SCHEDULED_COVARIANCE_WINDOW')
    try:
        valid_cap = type(annual_cap) in (float, int) and math.isfinite(annual_cap) and annual_cap > 0
    except OverflowError:
        valid_cap = False
    _require(valid_cap, 'SCHEDULED_ANNUAL_RISK_CAP')
    rows = _history(prices, symbols, window)
    converted = [[_micro_float(row[s]) for s in symbols] for row in rows]
    n = len(symbols)
    try:
        returns = [[converted[t][i] / converted[t-1][i] - 1
                    for i in range(n)] for t in range(1, len(converted))]
        _require(all(math.isfinite(v) for row in returns for v in row),
                 'SCHEDULED_NONFINITE_RETURN')
        means = [math.fsum(row[i] for row in returns) / window for i in range(n)]
        covariance = [[math.fsum((row[i] - means[i]) * (row[j] - means[j])
                                for row in returns) / (window - 1)
                       for j in range(n)] for i in range(n)]
        _require(all(math.isfinite(x) for row in covariance for x in row),
                 'SCHEDULED_NONFINITE_COVARIANCE')
        _require(all(covariance[i][i] > 0 for i in range(n)),
                 'SCHEDULED_NONPOSITIVE_VARIANCE')
        sigmas = [math.sqrt(covariance[i][i]) for i in range(n)]
        inverse = [1 / sigma for sigma in sigmas]
        inverse_sum = math.fsum(inverse)
        _require(math.isfinite(inverse_sum) and inverse_sum > 0,
                 'SCHEDULED_NONFINITE_INVERSE_VOL')
        momenta = [converted[-1][i] / converted[0][i] - 1 for i in range(n)]
        _require(all(math.isfinite(v) for v in momenta), 'SCHEDULED_NONFINITE_MOMENTUM')
        # max() preserves the explicit input order on exact binary64 ties.
        winner = max(range(n), key=lambda i: momenta[i])
        raw = {'INVERSE_VOL': [v / inverse_sum for v in inverse],
               'EQUAL_WEIGHT': [1 / n for _ in symbols],
               'MOMENTUM': [float(i == winner) for i in range(n)]}
        risks = {name: _risk(weights, covariance) for name, weights in raw.items()}
        tau = min(annual_cap, *risks.values())
        scales = {name: tau / risk for name, risk in risks.items()}
        _require(all(math.isfinite(v) and 0 < v <= 1 for v in scales.values()),
                 'SCHEDULED_RISK_SCALE')
        before = {name: [scales[name] * v for v in weights]
                  for name, weights in raw.items()}
        targets = {}
        projected = {}
        for name, weights in before.items():
            with localcontext(context()):
                tokens = [Decimal(repr(v)).quantize(Decimal('1e-12'), rounding=ROUND_FLOOR)
                          for v in weights]
            targets[name] = {s: Fraction(token) for s, token in zip(symbols, tokens)}
            _require(all(w >= 0 for w in targets[name].values()) and
                     sum(targets[name].values()) <= 1, 'SCHEDULED_TARGET_WEIGHT_DOMAIN')
            projected[name] = [float(v) for v in tokens]
        after_risks = {name: _risk(weights, covariance) for name, weights in projected.items()}
        spread = max(after_risks.values()) - min(after_risks.values())
        _require(math.isfinite(spread) and spread <= 1e-8,
                 'SCHEDULED_POSTROUND_RISK_SPREAD')
    except (OverflowError, ZeroDivisionError):
        raise ValueError('SCHEDULED_BINARY64_ARITHMETIC') from None
    return {'weights': targets,
            'diagnostics': {'kind': 'COMMON_RISK_INVERSE_VOLATILITY',
                            'window_returns': window, 'price_count': len(rows),
                            'price_binary64': [[repr(v) for v in row] for row in converted],
                            'means_binary64': {s: repr(v) for s, v in zip(symbols, means)},
                            'covariance_binary64': [[repr(v) for v in row] for row in covariance],
                            'sigma_binary64': {s: repr(v) for s, v in zip(symbols, sigmas)},
                            'momenta_binary64': {s: repr(v) for s, v in zip(symbols, momenta)},
                            'momentum_selected_symbol': symbols[winner],
                            'raw_proportions_binary64': {name: {s: repr(v) for s, v in zip(symbols, row)}
                                                        for name, row in raw.items()},
                            'raw_annual_risk_binary64': {k: repr(v) for k, v in risks.items()},
                            'annual_cap_binary64': repr(float(annual_cap)),
                            'common_tau_binary64': repr(tau),
                            'scales_binary64': {k: repr(v) for k, v in scales.items()},
                            'scaled_pre_round_binary64': {name: {s: repr(v) for s, v in zip(symbols, row)}
                                                        for name, row in before.items()},
                            'target_weights': {name: {s: _rational(v) for s, v in row.items()}
                                               for name, row in targets.items()},
                            'cash_weights': {name: _rational(1 - sum(row.values()))
                                             for name, row in targets.items()},
                            'post_round_annual_risk_binary64': {k: repr(v) for k, v in after_risks.items()},
                            'post_round_risk_spread_binary64': repr(spread)}}
