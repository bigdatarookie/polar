"""Frozen paired saved-return bootstrap; no source, policy, native, or store calls."""
from collections import Counter
from decimal import Decimal, DecimalException, localcontext
from fractions import Fraction
from hashlib import sha256
import json
from math import gcd
import random
import re

from .gym_contract import context, decimal_fraction

SAMPLES = 1000
BLOCK_LENGTH = 63
SEED = 37001
BIT_LIMIT = 1000000
STATISTICS = ('sr_delta', 'growth_delta', 'drawdown_delta')


class _InvalidStatistic(ValueError):
    pass


def _bounded(value, limit=BIT_LIMIT):
    value = Fraction(value)
    if value.numerator.bit_length() > limit or value.denominator.bit_length() > limit:
        raise _InvalidStatistic('INTEGER_BOUND')
    return value


def _integer(value):
    if type(value) is int:
        if value.bit_length() > BIT_LIMIT:
            raise _InvalidStatistic('INTEGER_BOUND')
        return value
    if type(value) is not str or re.fullmatch(r'-?(?:0|[1-9][0-9]*)', value) is None:
        raise _InvalidStatistic('INVALID_RATIONAL_ENCODING')
    # Decimal->int is exact and avoids changing Python's global int-string guard.
    if len(value.lstrip('-')) > BIT_LIMIT*30103//100000+2:
        raise _InvalidStatistic('INTEGER_BOUND')
    result = int(Decimal(value))
    if result.bit_length() > BIT_LIMIT:
        raise _InvalidStatistic('INTEGER_BOUND')
    return result


def _return(value):
    if isinstance(value, Fraction):
        result = _bounded(value)
    elif type(value) is int:
        result = _bounded(value)
    elif isinstance(value, dict) and 'numerator' in value and 'denominator' in value:
        denominator = _integer(value['denominator'])
        if denominator <= 0:
            raise _InvalidStatistic('INVALID_RATIONAL_DENOMINATOR')
        result = _bounded(Fraction(_integer(value['numerator']), denominator))
    else:
        raise _InvalidStatistic('MISSING_OR_INVALID_EXACT_RETURN')
    if result <= -1:
        raise _InvalidStatistic('NONPOSITIVE_GROSS_RETURN')
    return result


def _vector(leg):
    """Keep a failed vector's original size; never drop an offending observation."""
    raw = leg.get('returns')
    if raw is not None:
        if not isinstance(raw, list):
            return [], 0, 'MISSING_SAVED_RETURN_VECTOR'
        n = len(raw)
        try:
            return [_return(r) for r in raw], n, None
        except (_InvalidStatistic, DecimalException, ArithmeticError) as exc:
            return [], n, str(exc) if isinstance(exc, _InvalidStatistic) else 'EXACT_RETURN_CONVERSION_FAILED'
    nav = leg.get('nav')
    if not isinstance(nav, list) or not nav:
        return [], 0, 'MISSING_SAVED_NAV_OR_RETURN_VECTOR'
    n = len(nav)-1
    if any(not isinstance(r, dict) or type(r.get('nav_cents')) is not int for r in nav):
        return [], n, 'MISSING_OR_INVALID_SAVED_NAV'
    values = [r['nav_cents'] for r in nav]
    if any(v <= 0 for v in values):
        return [], n, 'NONPOSITIVE_SAVED_NAV'
    try:
        return [_return(Fraction(b, a)-1) for a, b in zip(values, values[1:])], n, None
    except _InvalidStatistic as exc:
        return [], n, str(exc)


def _indices(n, rng):
    indices = []
    while len(indices) < n:
        start = rng.randrange(n)
        indices.extend((start+i) % n for i in range(BLOCK_LENGTH))
    return indices[:n]


def _canonical_indices(indices):
    return (json.dumps(indices, separators=(',', ':'))+'\n').encode()


def _moment_table(vector):
    """Integer common-denominator acceleration, only where the bit guard is safe.

    Fractions and their moments are unchanged. If conservative size bounds cannot
    establish every literal centered-sum intermediate fits the frozen guard,
    fall back to that literal Fraction recipe instead of failing or clipping.
    """
    n = len(vector)
    denominator = 1
    for r in vector:
        denominator = denominator//gcd(denominator, r.denominator)*r.denominator
        if denominator.bit_length() > BIT_LIMIT//4:
            return None
    numerators = [r.numerator*(denominator//r.denominator) for r in vector]
    bound = max([denominator.bit_length()]+[abs(v).bit_length() for v in numerators])
    if 2*(bound+2*n.bit_length()+4) >= BIT_LIMIT:
        return None
    return denominator, numerators, [v*v for v in numerators]


def _sharpe(vector, indices, table, counts):
    n = len(indices)
    if n < 2:
        raise _InvalidStatistic('INSUFFICIENT_INTERVALS')
    if table is not None:
        denominator, numerators, squares = table
        total = sum(numerators[i]*count for i, count in counts.items())
        total_square = sum(squares[i]*count for i, count in counts.items())
        mean = _bounded(Fraction(total, n*denominator))
        variance = _bounded(Fraction(n*total_square-total*total, n*(n-1)*denominator*denominator))
    else:
        total = Fraction()
        for i in indices:
            total = _bounded(total+vector[i])
        mean = _bounded(total/n)
        centered = Fraction()
        for i in indices:
            delta = _bounded(vector[i]-mean)
            centered = _bounded(centered+_bounded(delta*delta))
        variance = _bounded(centered/(n-1))
    if variance == 0:
        raise _InvalidStatistic('ZERO_VARIANCE')
    if variance < 0:
        raise _InvalidStatistic('INVALID_VARIANCE')
    with localcontext(context()):
        sd = decimal_fraction(variance).sqrt()
        root252 = Decimal(252).sqrt()
        value = (root252*decimal_fraction(mean))/sd
        if not value.is_finite():
            raise _InvalidStatistic('NONFINITE_DECIMAL_STATISTIC')
        return value


def _path(vector, indices):
    wealth = peak = Fraction(1)
    maximum_dd = Fraction()
    for i in indices:
        wealth = _bounded(wealth*_bounded(1+vector[i]))
        if wealth <= 0:
            raise _InvalidStatistic('NONPOSITIVE_WEALTH_PATH')
        peak = max(peak, wealth)
        drawdown = _bounded(1-_bounded(wealth/peak))
        maximum_dd = max(maximum_dd, drawdown)
    return _bounded(wealth-1), maximum_dd


def _bad(reason):
    return {'value': None, 'status': 'INVALID_STATISTIC', 'reason': reason}


def _text(value):
    with localcontext(context()):
        value = decimal_fraction(value) if isinstance(value, Fraction) else value
        if not value.is_finite():
            raise _InvalidStatistic('NONFINITE_DECIMAL_STATISTIC')
        return '0' if value == 0 else format(value, 'f')


def _leg_statistics(vector, indices, table, counts, reason):
    if reason:
        return {k: (None, reason) for k in ('sr', 'growth', 'drawdown')}
    if len(indices) < 2:
        return {k: (None, 'INSUFFICIENT_INTERVALS') for k in ('sr', 'growth', 'drawdown')}
    out = {}
    try:
        out['sr'] = (_sharpe(vector, indices, table, counts), None)
    except (_InvalidStatistic, DecimalException, ArithmeticError) as exc:
        out['sr'] = (None, str(exc) if isinstance(exc, _InvalidStatistic) else 'DECIMAL_STATISTIC_EXCEPTION')
    try:
        growth, drawdown = _path(vector, indices)
        out.update(growth=(growth, None), drawdown=(drawdown, None))
    except (_InvalidStatistic, DecimalException, ArithmeticError) as exc:
        reason = str(exc) if isinstance(exc, _InvalidStatistic) else 'EXACT_PATH_STATISTIC_EXCEPTION'
        out.update(growth=(None, reason), drawdown=(None, reason))
    return out


def _difference(left, right):
    if left[1]:
        return None, _bad('STRATEGY_'+left[1])
    if right[1]:
        return None, _bad('BENCHMARK_'+right[1])
    try:
        with localcontext(context()):
            value = left[0]-right[0]
            if isinstance(value, Fraction):
                value = _bounded(value)
            return value, {'value': _text(value), 'status': 'OK', 'reason': None}
    except (_InvalidStatistic, DecimalException, ArithmeticError) as exc:
        return None, _bad(str(exc) if isinstance(exc, _InvalidStatistic) else 'DECIMAL_STATISTIC_EXCEPTION')


def _interval(values, invalid_reasons, samples):
    ordered = sorted(values)
    m = len(ordered)
    if not m:
        return {'status': 'UNAVAILABLE', 'reason': 'NO_VALID_REPLICATES', 'lower': None, 'upper': None,
                'valid_count': 0, 'invalid_count': samples, 'invalid_reason_counts': dict(sorted(invalid_reasons.items())),
                'lower_order_index': None, 'upper_order_index': None}
    lower, upper = (m-1)//40, (39*(m-1)+39)//40
    return {'status': 'OK' if m == samples else 'DESCRIPTIVE_VALID_SUBSET_ONLY',
            'reason': None if m == samples else 'INVALID_REPLICATES_RETAINED_NO_REDRAW',
            'lower': _text(ordered[lower]), 'upper': _text(ordered[upper]),
            'valid_count': m, 'invalid_count': samples-m, 'invalid_reason_counts': dict(sorted(invalid_reasons.items())),
            'lower_order_index': lower, 'upper_order_index': upper}


def bootstrap(simulation, primary_id, benchmark_ids, *, seed=SEED, recipe="LEGACY"):
    """Fixed1000 paired circular63 draws from ONLY the three saved BASE legs.

    Legs may have native positive integer-cent ``nav`` rows, or ``returns`` with
    exact numerator/denominator strings (Fraction values are also accepted for
    invented pure callers). Floats and mismatched/missing observations are never
    substituted or silently dropped. This function does not decide robustness.
    """
    if recipe not in ('LEGACY','TEMPORAL_DESCRIPTIVE') or type(seed) is not int or seed not in ((37003,) if recipe=='TEMPORAL_DESCRIPTIVE' else (37001,37002)):
        raise ValueError('BOOTSTRAP_SEED')
    legs = simulation.get('legs') if isinstance(simulation, dict) else None
    if (not isinstance(legs, list) or len(legs) != 3 or not isinstance(benchmark_ids, (list, tuple))
            or type(primary_id) is not str or len(benchmark_ids) != 2
            or any(type(b) is not str for b in benchmark_ids) or len(set([primary_id, *benchmark_ids])) != 3
            or any(not isinstance(leg, dict) or type(leg.get('id')) is not str for leg in legs)):
        raise ValueError('BOOTSTRAP_THREE_BASE_LEG_IDENTITIES')
    ids = [leg['id'] for leg in legs]
    if len(set(ids)) != 3 or set(ids) != {primary_id, *benchmark_ids}:
        raise ValueError('BOOTSTRAP_THREE_BASE_LEG_IDENTITIES')
    parsed = {leg['id']: _vector(leg) for leg in legs}
    n = parsed[primary_id][1]
    vectors, errors, tables = {}, {}, {}
    for leg_id in [primary_id, *benchmark_ids]:
        vector, count, reason = parsed[leg_id]
        if count != n:
            reason = 'RETURN_VECTOR_LENGTH_MISMATCH'
        vectors[leg_id], errors[leg_id] = vector, reason
        tables[leg_id] = _moment_table(vector) if not reason and n >= 2 else None
    valid = {b: {s: [] for s in STATISTICS} for b in benchmark_ids}
    reasons = {b: {s: Counter() for s in STATISTICS} for b in benchmark_ids}
    rng = random.Random(seed)
    sequence_hash = sha256()
    replicates = []
    keys = {'sr_delta': 'sr', 'growth_delta': 'growth', 'drawdown_delta': 'drawdown'}
    for draw in range(SAMPLES):
        indices = _indices(n, rng)
        index_bytes = _canonical_indices(indices)
        sequence_hash.update(index_bytes)
        counts = Counter(indices)
        stats = {leg_id: _leg_statistics(vectors[leg_id], indices, tables[leg_id], counts, errors[leg_id])
                 for leg_id in [primary_id, *benchmark_ids]}
        comparisons = []
        for benchmark in benchmark_ids:
            compared = {'benchmark_id': benchmark}
            for name, key in keys.items():
                value, record = _difference(stats[primary_id][key], stats[benchmark][key])
                compared[name] = record
                if record['status'] == 'OK':
                    valid[benchmark][name].append(value)
                else:
                    reasons[benchmark][name][record['reason']] += 1
            comparisons.append(compared)
        replicates.append({'draw': draw, 'indices_sha256': sha256(index_bytes).hexdigest(), 'comparisons': comparisons})
    comparisons = [{'benchmark_id': b, **{s: (_temporal_interval if recipe=='TEMPORAL_DESCRIPTIVE' else _interval)(valid[b][s], reasons[b][s], SAMPLES) for s in STATISTICS}}
                   for b in benchmark_ids]
    all_valid = all(c[s]['valid_count'] == SAMPLES for c in comparisons for s in STATISTICS)
    return {'schema': 'polar.scheduled-paired-bootstrap/1', 'status': 'COMPLETE' if all_valid else 'INSUFFICIENT',
            'reason': None if all_valid else 'REQUIRED_COMPONENT_REPLICATES_INVALID',
            'primary_id': primary_id, 'benchmark_ids': list(benchmark_ids), 'n': n,
            'samples': SAMPLES, 'block_length': BLOCK_LENGTH, 'seed': seed,
            'integer_bit_limit': BIT_LIMIT, 'index_sequence_sha256': sequence_hash.hexdigest(),
            'index_hash_encoding': 'EACH_ORDERED_INTEGER_INDEX_ARRAY_COMPACT_JSON_PLUS_LF_IN_DRAW_ORDER',
            'all_components_valid': all_valid, 'comparisons': comparisons, 'replicates': replicates,
            'growth_unit': 'CUMULATIVE_NET_WEALTH_RATIO_DIFFERENCE_FROM_W0_EXACT1_NOT_USD_OR_MEAN_RETURN',
            'drawdown_sign': 'STRATEGY_NONNEGATIVE_MAXDD_MINUS_BENCHMARK_NEGATIVE_IS_BETTER',
            'scope': 'DESCRIPTIVE_PAIRED_SAVED_NET_RETURNS_EXPOSED_ERA_NOT_INDEPENDENT_MARKET_ERAS_OR_FINANCIAL_ACCEPTANCE'}


def _temporal_interval(values, invalid_reasons, samples):
    ordered=sorted(values);m=len(ordered)
    result={'status':'COMPLETE_DESCRIPTIVE' if m==samples else 'PARTIAL_WITH_EXPLICIT_INVALID_COUNTS' if m else 'UNAVAILABLE',
        'reason':None if m==samples else 'INVALID_REPLICATES_RETAINED_NO_REDRAW' if m else 'NO_VALID_REPLICATES',
        'valid_count':m,'invalid_count':samples-m,'invalid_reason_counts':dict(sorted(invalid_reasons.items())),
        'quantile_rule':'EMPIRICAL_INVERSE_CDF_CEIL_P_M_MINUS_ONE'}
    for name,num,den in [('lower',1,40),('median',1,2),('upper',39,40)]:
        idx=(num*m+den-1)//den-1 if m else None
        result[name+'_order_index']=idx
        result[name]=_text(ordered[idx]) if m else None
        if m and isinstance(ordered[idx],Fraction):
            result[name+'_exact']={'numerator':format(Decimal(ordered[idx].numerator),'f'),'denominator':format(Decimal(ordered[idx].denominator),'f')}
    return result
