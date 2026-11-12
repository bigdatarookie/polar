"""Exact four-asset 50%-diagonal-shrunk GMV and saved-certificate checks.

No data, policy, model, native-engine, or store calls. ``solve`` accepts the
already-estimated symmetric binary64 covariance. ``verify`` only checks saved
arithmetic certificates; it never calls LDL or a linear-system solver.
"""
from decimal import Decimal
from fractions import Fraction
from itertools import permutations
import math
import re

BIT_LIMIT = 1000000
SCHEMA = 'polar.shrunk-gmv-certificate/1'


class GMVError(ValueError):
    pass


class _Arithmetic:
    def __init__(self):
        self.count = self.numerator_bits = self.denominator_bits = 0

    def bound(self, value):
        value = Fraction(value)
        n, d = abs(value.numerator).bit_length(), value.denominator.bit_length()
        self.count += 1
        self.numerator_bits = max(self.numerator_bits, n)
        self.denominator_bits = max(self.denominator_bits, d)
        if max(n, d) > BIT_LIMIT:
            raise GMVError('NUMERIC_BOUND')
        return value

    def add(self, x, y):
        return self.bound(x+y)

    def sub(self, x, y):
        return self.bound(x-y)

    def mul(self, x, y):
        return self.bound(x*y)

    def div(self, x, y):
        if y == 0:
            raise GMVError('ZERO_DIVISOR')
        return self.bound(x/y)

    def total(self, terms):
        value = self.bound(0)
        for term in terms:
            value = self.add(value, term)
        return value

    def snapshot(self):
        return {'checked_results': self.count,
                'maximum_numerator_bits': self.numerator_bits,
                'maximum_denominator_bits': self.denominator_bits}


def _integer_text(value):
    # Avoid CPython's global decimal-int-string digit setting for the frozen cap.
    return format(Decimal(value), 'f')


def _encode(value):
    return {'numerator': _integer_text(value.numerator),
            'denominator': _integer_text(value.denominator)}


def _integer(value):
    if (type(value) is not str or re.fullmatch(r'-?(?:0|[1-9][0-9]*)', value) is None
            or len(value.lstrip('-')) > BIT_LIMIT*30103//100000+2):
        raise GMVError('INVALID_RATIONAL_ENCODING')
    result = int(Decimal(value))
    if abs(result).bit_length() > BIT_LIMIT:
        raise GMVError('NUMERIC_BOUND')
    return result


def _decode(value, arithmetic):
    if not isinstance(value, dict) or set(value) != {'numerator', 'denominator'}:
        raise GMVError('INVALID_RATIONAL_ENCODING')
    n, d = _integer(value['numerator']), _integer(value['denominator'])
    if d <= 0:
        raise GMVError('INVALID_RATIONAL_DENOMINATOR')
    result = arithmetic.bound(Fraction(n, d))
    if _encode(result) != value:
        raise GMVError('NONCANONICAL_RATIONAL_ENCODING')
    return result


def _matrix(values, size=4):
    if (not isinstance(values, list) or len(values) != size
            or any(not isinstance(row, list) or len(row) != size for row in values)):
        raise GMVError('COVARIANCE_SHAPE')


def _covariance(values, arithmetic):
    _matrix(values)
    if any(type(value) is not float or not math.isfinite(value)
           for row in values for value in row):
        raise GMVError('COVARIANCE_NOT_FINITE_BINARY64')
    q = [[arithmetic.bound(Fraction.from_float(v)) for v in row] for row in values]
    if any(q[i][j] != q[j][i] for i in range(4) for j in range(4)):
        raise GMVError('COVARIANCE_NOT_EXACTLY_SYMMETRIC')
    if any(q[i][i] <= 0 for i in range(4)):
        raise GMVError('COVARIANCE_DIAGONAL_NOT_POSITIVE')
    return q


def _shrink(q, arithmetic):
    return [[q[i][j] if i == j else arithmetic.div(q[i][j], Fraction(2))
             for j in range(4)] for i in range(4)]


def _ldl(s, arithmetic, record):
    n = len(s)
    lower = [[arithmetic.bound(int(i == j)) for j in range(n)] for i in range(n)]
    diagonal = []
    record.update(unit_lower=[[_encode(x) for x in row] for row in lower], pivots=[])
    for j in range(n):
        subtotal = arithmetic.total(arithmetic.mul(arithmetic.mul(lower[j][k], lower[j][k]), diagonal[k])
                                    for k in range(j))
        pivot = arithmetic.sub(s[j][j], subtotal)
        diagonal.append(pivot)
        record['pivots'].append(_encode(pivot))
        if pivot <= 0:
            record['status'] = 'INVALID'
            raise GMVError('LDL_NONPOSITIVE_PIVOT')
        for i in range(j+1, n):
            subtotal = arithmetic.total(arithmetic.mul(arithmetic.mul(lower[i][k], lower[j][k]), diagonal[k])
                                        for k in range(j))
            lower[i][j] = arithmetic.div(arithmetic.sub(s[i][j], subtotal), pivot)
        record['unit_lower'] = [[_encode(x) for x in row] for row in lower]
    record['status'] = 'OK'


def _gauss_jordan(s, indices, arithmetic, record):
    n = len(indices)
    rows = [[s[i][j] for j in indices]+[arithmetic.bound(1)] for i in indices]
    record['pivots'] = []
    for j in range(n):
        pivot = rows[j][j]
        record['pivots'].append(_encode(pivot))
        if pivot <= 0:
            raise GMVError('SUPPORT_NONPOSITIVE_PIVOT')
        rows[j] = [arithmetic.div(v, pivot) for v in rows[j]]
        for i in range(n):
            if i == j:
                continue
            scale = rows[i][j]
            rows[i] = [arithmetic.sub(rows[i][k], arithmetic.mul(scale, rows[j][k]))
                       for k in range(n+1)]
    return [row[-1] for row in rows]


def _support_values(s, indices, x, arithmetic):
    a = arithmetic.total(x)
    if a <= 0:
        raise GMVError('SUPPORT_NONPOSITIVE_NORMALIZER')
    c = arithmetic.div(Fraction(1), a)
    w = [arithmetic.bound(0) for _ in range(4)]
    for i, v in zip(indices, x):
        w[i] = arithmetic.div(v, a)
    sw = [arithmetic.total(arithmetic.mul(s[i][j], w[j]) for j in range(4)) for i in range(4)]
    objective = arithmetic.total(arithmetic.mul(w[i], sw[i]) for i in range(4))
    checks = {'normalizer_positive': a > 0,
              'weights_nonnegative': all(v >= 0 for v in w),
              'sum_one': arithmetic.total(w) == 1,
              'active_stationarity': all(sw[i] == c for i in indices),
              'inactive_kkt': all(sw[i] >= c for i in range(4) if i not in indices),
              'objective_equals_c': objective == c}
    return a, c, w, sw, objective, checks


def _support_record(s, mask, arithmetic, record):
    indices = [i for i in range(4) if mask & (1 << i)]
    record.update(mask=mask, indices=indices, guard_before=arithmetic.snapshot(), status='IN_PROGRESS')
    x = _gauss_jordan(s, indices, arithmetic, record)
    a, c, w, sw, objective, checks = _support_values(s, indices, x, arithmetic)
    record.update(x=[_encode(v) for v in x], normalizer=_encode(a), c=_encode(c),
                  weights=[_encode(v) for v in w], sw=[_encode(v) for v in sw],
                  objective=_encode(objective), checks=checks,
                  reasons=[key.upper() for key, valid in checks.items() if not valid],
                  zero_active_indices=[i for i in indices if w[i] == 0],
                  status='ACCEPTED' if all(checks.values()) else 'REJECTED',
                  guard_after=arithmetic.snapshot())
    return w


def solve(covariance):
    """Return an OK certificate or explicit INVALID partial, never fallback weights.

    Only a four-by-four list of finite ``float`` values is admitted, since the
    caller owns the frozen binary64 estimation. Exact zero active weights are
    allowed. All15 supports are visited even after the first accepted support.
    """
    arithmetic = _Arithmetic()
    record = {'schema': SCHEMA, 'status': 'INVALID', 'reason': None,
              'bit_limit': BIT_LIMIT, 'supports': [], 'ldl': {},
              'actual_counts': {'spd_certifications': 0, 'portfolio_optimizations': 0,
                                'support_linear_system_attempts': 0}}
    try:
        q = _covariance(covariance, arithmetic)
        record['covariance_repr'] = [[repr(v) for v in row] for row in covariance]
        record['covariance_q'] = [[_encode(v) for v in row] for row in q]
        s = _shrink(q, arithmetic)
        record['shrunk_s'] = [[_encode(v) for v in row] for row in s]
        record['actual_counts']['spd_certifications'] += 1
        _ldl(s, arithmetic, record['ldl'])
        record['actual_counts']['portfolio_optimizations'] += 1
        accepted = []
        vector = None
        differing_vectors = False
        for mask in range(1, 16):
            support = {}
            record['supports'].append(support)
            record['actual_counts']['support_linear_system_attempts'] += 1
            w = _support_record(s, mask, arithmetic, support)
            if support['status'] == 'ACCEPTED':
                accepted.append(mask)
                if vector is not None and w != vector:
                    differing_vectors = True
                vector = w
        if not accepted:
            raise GMVError('NO_VALID_KKT_SUPPORT')
        if differing_vectors:
            raise GMVError('DIFFERING_KKT_WEIGHT_VECTORS')
        record.update(status='OK', weights=[_encode(v) for v in vector],
                      accepted_support_masks=accepted, selected_support_mask=accepted[0])
    except (GMVError, OverflowError, ValueError, ZeroDivisionError) as exc:
        record['reason'] = str(exc) if isinstance(exc, GMVError) else 'EXACT_ARITHMETIC_FAILURE'
        if record['supports'] and record['supports'][-1].get('status') == 'IN_PROGRESS':
            record['supports'][-1].update(status='INVALID', reason=record['reason'],
                                          guard_after=arithmetic.snapshot())
    record['guard'] = arithmetic.snapshot()
    return record


def _require(condition, reason):
    if not condition:
        raise GMVError(reason)


def _determinant(matrix, arithmetic):
    """Small saved-pivot identity check via permutation polynomial, not a solve."""
    n = len(matrix)
    terms = []
    for p in permutations(range(n)):
        term = arithmetic.bound(-1 if sum(p[i] > p[j] for i in range(n) for j in range(i+1, n)) % 2 else 1)
        for i in range(n):
            term = arithmetic.mul(term, matrix[i][p[i]])
        terms.append(term)
    return arithmetic.total(terms)


def _decode_vector(values, n, arithmetic):
    _require(isinstance(values, list) and len(values) == n, 'CERTIFICATE_VECTOR_SHAPE')
    return [_decode(v, arithmetic) for v in values]


def verify(certificate):
    """Check a successful saved certificate using identities only, with0solves.

    Checks Q/S correspondence, saved LDL reconstruction, every saved S_FF*x=1,
    positive natural-pivot determinant identities, all15 feasibility decisions,
    exact objective/KKT and identical full vectors. No input covariance/source,
    policy, optimization, LDL factorization, or Gauss-Jordan call is made.
    """
    arithmetic = _Arithmetic()
    answer = {'status': 'INVALID', 'reason': None, 'linear_system_solves': 0,
              'portfolio_optimizations': 0, 'checked_supports': 0}
    try:
        _require(isinstance(certificate, dict) and certificate.get('schema') == SCHEMA
                 and certificate.get('status') == 'OK' and certificate.get('reason') is None,
                 'CERTIFICATE_NOT_SUCCESSFUL')
        _require(certificate.get('bit_limit') == BIT_LIMIT, 'CERTIFICATE_BIT_LIMIT')
        _require(certificate.get('actual_counts') == {'spd_certifications': 1, 'portfolio_optimizations': 1,
                  'support_linear_system_attempts': 15}, 'CERTIFICATE_ACTUAL_COUNTS')
        strings = certificate['covariance_repr']
        _matrix(strings)
        _require(all(type(v) is str for row in strings for v in row), 'CERTIFICATE_COVARIANCE_REPR')
        floats = [[float(v) for v in row] for row in strings]
        _require([[repr(v) for v in row] for row in floats] == strings, 'CERTIFICATE_COVARIANCE_REPR')
        q = _covariance(floats, arithmetic)
        _require(certificate['covariance_q'] == [[_encode(v) for v in row] for row in q], 'CERTIFICATE_Q_MISMATCH')
        s = _shrink(q, arithmetic)
        _require(certificate['shrunk_s'] == [[_encode(v) for v in row] for row in s], 'CERTIFICATE_SHRINKAGE_MISMATCH')
        ldl = certificate['ldl']
        _require(ldl.get('status') == 'OK', 'CERTIFICATE_LDL_STATUS')
        _matrix(ldl['unit_lower'])
        lower = [[_decode(v, arithmetic) for v in row] for row in ldl['unit_lower']]
        diagonal = _decode_vector(ldl['pivots'], 4, arithmetic)
        _require(all(d > 0 for d in diagonal), 'CERTIFICATE_LDL_NONPOSITIVE_PIVOT')
        _require(all(lower[i][i] == 1 and all(lower[i][j] == 0 for j in range(i+1, 4)) for i in range(4)),
                 'CERTIFICATE_LDL_TRIANGLE')
        for i in range(4):
            for j in range(4):
                value = arithmetic.total(arithmetic.mul(arithmetic.mul(lower[i][k], lower[j][k]), diagonal[k])
                                         for k in range(4))
                _require(value == s[i][j], 'CERTIFICATE_LDL_RECONSTRUCTION')
        records = certificate['supports']
        _require(isinstance(records, list) and len(records) == 15, 'CERTIFICATE_SUPPORT_COUNT')
        accepted = []
        vector = None
        previous_guard = None
        for mask, record in enumerate(records, 1):
            indices = [i for i in range(4) if mask & (1 << i)]
            _require(record['mask'] == mask and record['indices'] == indices, 'CERTIFICATE_SUPPORT_ORDER')
            x = _decode_vector(record['x'], len(indices), arithmetic)
            pivots = _decode_vector(record['pivots'], len(indices), arithmetic)
            _require(all(v > 0 for v in pivots), 'CERTIFICATE_SUPPORT_NONPOSITIVE_PIVOT')
            previous = Fraction(1)
            for end, pivot in enumerate(pivots, 1):
                determinant = _determinant([[s[i][j] for j in indices[:end]] for i in indices[:end]], arithmetic)
                _require(determinant > 0 and arithmetic.div(determinant, previous) == pivot,
                         'CERTIFICATE_SUPPORT_PIVOT_IDENTITY')
                previous = determinant
            for i in indices:
                _require(arithmetic.total(arithmetic.mul(s[i][j], value) for j, value in zip(indices, x)) == 1,
                         'CERTIFICATE_LINEAR_IDENTITY')
            a, c, w, sw, objective, checks = _support_values(s, indices, x, arithmetic)
            for key, expected in [('normalizer', _encode(a)), ('c', _encode(c)),
                                  ('weights', [_encode(v) for v in w]), ('sw', [_encode(v) for v in sw]),
                                  ('objective', _encode(objective)), ('checks', checks),
                                  ('zero_active_indices', [i for i in indices if w[i] == 0]),
                                  ('reasons', [key.upper() for key, valid in checks.items() if not valid])]:
                _require(record[key] == expected, 'CERTIFICATE_SUPPORT_'+key.upper())
            valid = all(checks.values())
            _require(record['status'] == ('ACCEPTED' if valid else 'REJECTED'), 'CERTIFICATE_SUPPORT_DECISION')
            if valid:
                accepted.append(mask)
                _require(vector is None or vector == w, 'DIFFERING_KKT_WEIGHT_VECTORS')
                vector = w
            for key in ['guard_before', 'guard_after']:
                guard = record[key]
                _require(all(type(guard.get(k)) is int and guard[k] >= 0 for k in
                             ['checked_results', 'maximum_numerator_bits', 'maximum_denominator_bits'])
                         and max(guard['maximum_numerator_bits'], guard['maximum_denominator_bits']) <= BIT_LIMIT,
                         'CERTIFICATE_GUARD_RECORD')
            _require(all(record['guard_after'][key] >= record['guard_before'][key] for key in
                         ['checked_results', 'maximum_numerator_bits', 'maximum_denominator_bits']),
                     'CERTIFICATE_GUARD_ORDER')
            _require(previous_guard is None or record['guard_before'] == previous_guard,
                     'CERTIFICATE_GUARD_CONTINUITY')
            previous_guard = record['guard_after']
            answer['checked_supports'] += 1
        _require(bool(accepted), 'NO_VALID_KKT_SUPPORT')
        _require(certificate['accepted_support_masks'] == accepted and certificate['selected_support_mask'] == accepted[0],
                 'CERTIFICATE_SELECTED_SUPPORT')
        _require(certificate['weights'] == [_encode(v) for v in vector], 'CERTIFICATE_FINAL_WEIGHTS')
        _require(certificate['guard'] == previous_guard, 'CERTIFICATE_FINAL_GUARD')
        answer['status'] = 'OK'
    except (GMVError, KeyError, TypeError, ValueError, ArithmeticError) as exc:
        answer['reason'] = str(exc) if isinstance(exc, GMVError) else 'MALFORMED_CERTIFICATE'
    answer['verification_guard'] = arithmetic.snapshot()
    return answer
