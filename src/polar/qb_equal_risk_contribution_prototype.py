"""Frozen four-asset equal risk contributions, exact certificates, invented tests.

Pure math only: no source, engine, model, store or result publication calls.
"""
from decimal import Decimal, DecimalException, localcontext, ROUND_HALF_EVEN
from fractions import Fraction
import math

PROTOCOL_ID = 'QB-EQUAL-RISK-CONTRIBUTION-20261118-V1'
SYMBOLS = ('BIL', 'SHY', 'TLT', 'VTI')
UNITS = 10**12
TOLERANCE = Fraction(1, 10**8)


class RiskBudgetError(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise RiskBudgetError(reason)


def pair(value):
    value = Fraction(value)
    return [value.numerator, value.denominator]


def matrix(value):
    require(isinstance(value, (list, tuple)) and len(value) == 4 and
            all(isinstance(row, (list, tuple)) and len(row) == 4 for row in value), 'FOUR_ASSET_MATRIX')
    result = []
    for row in value:
        converted = []
        for operand in row:
            require(type(operand) in (float, int, Fraction), 'COVARIANCE_OPERAND_TYPE')
            require(type(operand) is not float or math.isfinite(operand), 'NONFINITE_COVARIANCE')
            converted.append(Fraction(operand))
        result.append(converted)
    require(all(result[i][j] == result[j][i] for i in range(4) for j in range(4)), 'ASYMMETRIC_COVARIANCE')
    require(all(result[i][i] > 0 for i in range(4)), 'NONPOSITIVE_DIAGONAL')
    _ldl(result, strict=False)
    return result


def _ldl(value, *, strict):
    work = [list(row) for row in value]
    pivots = []
    for k in range(4):
        pivot = work[k][k]
        require(pivot > 0 if strict else pivot >= 0, 'NON_SPD_SHRINKAGE' if strict else 'NON_PSD_COVARIANCE')
        pivots.append(pivot)
        if pivot == 0:
            require(all(work[k][j] == 0 for j in range(k+1, 4)), 'NON_PSD_COVARIANCE')
            continue
        for i in range(k+1, 4):
            for j in range(k+1, 4):
                work[i][j] -= work[i][k] * work[k][j] / pivot
    return pivots


def quadratic(weights, covariance):
    return sum((weights[i] * covariance[i][j] * weights[j]
                for i in range(4) for j in range(4)), Fraction())


def contribution_certificate(weights, covariance):
    total = quadratic(weights, covariance)
    require(total > 0 and all(w > 0 for w in weights) and sum(weights) == 1, 'WEIGHT_DOMAIN')
    contributions = [weights[i] * sum((covariance[i][j] * weights[j] for j in range(4)), Fraction())
                     for i in range(4)]
    errors = [abs(4*x/total-1) for x in contributions]
    return total, contributions, errors


def _normalize(values):
    exact = [Fraction(x) for x in values]
    total = sum(exact)
    require(total > 0 and all(x > 0 for x in exact), 'POSITIVE_ITERATE_DOMAIN')
    return [x/total for x in exact]


def _scale(variance, target, units=UNITS):
    require(variance > 0 and 0 < target <= variance and type(units) is int and units > 0, 'RISK_SCALE_DOMAIN')
    lo, hi, evaluations = 0, units+1, 0
    while hi-lo > 1:
        mid = (lo+hi)//2
        evaluations += 1
        if variance * Fraction(mid, units)**2 <= target:
            lo = mid
        else:
            hi = mid
    selected = variance * Fraction(lo, units)**2
    next_variance = variance * Fraction(lo+1, units)**2 if lo < units else None
    require(selected <= target and (next_variance is None or next_variance > target), 'RISK_SCALE_CERTIFICATE')
    return lo, selected, next_variance, evaluations


def equal_risk_targets(sample_covariance):
    actual = {'coordinate_sweeps': 0, 'coordinate_update_attempts': 0,
              'coordinate_updates': 0, 'exact_budget_checks': 0,
              'risk_scale_evaluations': 0}
    try:
        return _solve(sample_covariance, actual)
    except (RiskBudgetError, DecimalException, OverflowError) as error:
        failure = RiskBudgetError(str(error) if isinstance(error, RiskBudgetError) else 'DECIMAL_ARITHMETIC_INVALID')
        failure.events = {'status': 'INVALID', 'actual_counts': dict(actual)}
        raise failure from None


def _solve(sample_covariance, actual):
    original = matrix(sample_covariance)
    covariance = [[original[i][j] if i == j else original[i][j]/2 for j in range(4)] for i in range(4)]
    pivots = _ldl(covariance, strict=True)
    with localcontext() as ctx:
        ctx.prec = 80
        ctx.rounding = ROUND_HALF_EVEN
        decimal = lambda x: Decimal(x.numerator)/Decimal(x.denominator)
        c = [[decimal(x) for x in row] for row in covariance]
        x = [1/c[i][i].sqrt() for i in range(4)]
        inverse = _normalize(x)
        while True:
            before = tuple(x)
            for i in range(4):
                actual['coordinate_update_attempts'] += 1
                diagonal = c[i][i]
                cross = sum((c[i][j]*x[j] for j in range(4) if j != i), Decimal())
                root = (cross*cross+4*diagonal).sqrt()
                x[i] = 2/(cross+root) if cross >= 0 else (root-cross)/(2*diagonal)
                require(x[i].is_finite() and x[i] > 0, 'NONFINITE_COORDINATE')
                actual['coordinate_updates'] += 1
            actual['coordinate_sweeps'] += 1
            weights = _normalize(x)
            variance, contributions, errors = contribution_certificate(weights, covariance)
            actual['exact_budget_checks'] += 1
            if max(errors) <= TOLERANCE:
                break
            require(tuple(x) != before, 'DECIMAL_STALL_WITHOUT_EXACT_CERTIFICATE')
    raw = {'ERC': weights, 'INV': inverse, 'EW': [Fraction(1, 4)]*4}
    annual_variances = {k: 252*quadratic(w, covariance) for k, w in raw.items()}
    target = min(Fraction(1, 100), *annual_variances.values())
    targets, scales = {}, {}
    for leg, w in raw.items():
        index, selected, next_variance, count = _scale(annual_variances[leg], target)
        actual['risk_scale_evaluations'] += count
        scale = Fraction(index, UNITS)
        targets[leg] = {symbol: pair(scale*weight) for symbol, weight in zip(SYMBOLS, w)}
        scales[leg] = {'index': index, 'units': UNITS, 'cash': pair(1-scale),
                       'annual_raw_variance': pair(annual_variances[leg]),
                       'annual_selected_variance': pair(selected),
                       'annual_next_grid_variance': pair(next_variance) if next_variance is not None else None}
    return {'schema': 'polar.equal-risk-contribution-prototype/1', 'protocol_id': PROTOCOL_ID,
            'status': 'EXACT_RISK_BUDGET_AND_COMMON_GRID_CERTIFIED',
            'raw_weights': {k: {s: pair(w) for s, w in zip(SYMBOLS, v)} for k, v in raw.items()},
            'weights': targets,
            'certificate': {'sample_covariance': [[pair(v) for v in row] for row in original],
                            'shrunk_covariance': [[pair(v) for v in row] for row in covariance],
                            'shrunk_ldl_pivots': [pair(v) for v in pivots],
                            'erc_variance': pair(variance),
                            'erc_contributions': [pair(v) for v in contributions],
                            'erc_relative_budget_errors': [pair(v) for v in errors],
                            'relative_budget_tolerance': pair(TOLERANCE),
                            'annual_common_target_variance': pair(target), 'scales': scales},
            'actual_counts': dict(actual)}
