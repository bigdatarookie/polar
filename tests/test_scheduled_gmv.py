"""Invented literal exact-GMV/certificate controls; no market operands."""
from copy import deepcopy
from fractions import Fraction
import json
import math
import unittest
from unittest.mock import patch

from polar import scheduled_gmv as gmv


def diagonal():
    return [[float((i+1)**2) if i == j else 0.0 for j in range(4)] for i in range(4)]


def decoded(values):
    return [Fraction(int(v['numerator']), int(v['denominator'])) for v in values]


def encoded(n, d=1):
    return {'numerator': str(n), 'denominator': str(d)}


class ExactShrunkGMV(unittest.TestCase):
    def test_diagonal_closed_form_and_all_fifteen_systems(self):
        covariance = diagonal()
        before = deepcopy(covariance)
        result = gmv.solve(covariance)
        self.assertEqual(covariance, before)
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['actual_counts'], {'spd_certifications': 1,
                         'portfolio_optimizations': 1, 'support_linear_system_attempts': 15})
        self.assertEqual(decoded(result['weights']), [Fraction(v, 205) for v in (144, 36, 16, 9)])
        self.assertEqual(result['selected_support_mask'], 15)
        self.assertEqual(result['accepted_support_masks'], [15])
        self.assertEqual([s['mask'] for s in result['supports']], list(range(1, 16)))
        full = result['supports'][-1]
        self.assertEqual(decoded(full['x']), [Fraction(1), Fraction(1, 4), Fraction(1, 9), Fraction(1, 16)])
        self.assertEqual(full['normalizer'], encoded(205, 144))
        self.assertEqual(full['objective'], encoded(144, 205))
        # A singleton satisfies its active equation but violates omitted-asset KKT.
        self.assertEqual(result['supports'][0]['reasons'], ['INACTIVE_KKT'])
        self.assertEqual(gmv.verify(json.loads(json.dumps(result)))['status'], 'OK')

    def test_boundary_zero_active_weight_and_least_valid_mask(self):
        # S=(Q+diagQ)/2 has top-left [[1,1],[1,2]]. Its inverse*1 is [1,0].
        covariance = [[1.0, 2.0, 0.0, 0.0], [2.0, 2.0, 0.0, 0.0],
                      [0.0, 0.0, 4.0, 0.0], [0.0, 0.0, 0.0, 8.0]]
        result = gmv.solve(covariance)
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(decoded(result['weights']), [Fraction(8, 11), 0, Fraction(2, 11), Fraction(1, 11)])
        self.assertEqual(result['accepted_support_masks'], [13, 15])
        self.assertEqual(result['selected_support_mask'], 13)
        full = result['supports'][-1]
        self.assertEqual(full['zero_active_indices'], [1])
        self.assertEqual(full['status'], 'ACCEPTED')
        self.assertTrue(full['checks']['weights_nonnegative'])
        self.assertEqual(full['objective'], encoded(8, 11))
        self.assertEqual(gmv.verify(result)['status'], 'OK')

    def test_negative_unconstrained_weight_rejected_without_clipping(self):
        # S top-left [[1,1.5],[1.5,4]], inverse*1=[10/7,-2/7].
        covariance = [[1.0, 3.0, 0.0, 0.0], [3.0, 4.0, 0.0, 0.0],
                      [0.0, 0.0, 4.0, 0.0], [0.0, 0.0, 0.0, 8.0]]
        result = gmv.solve(covariance)
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['accepted_support_masks'], [13])
        full = result['supports'][-1]
        self.assertEqual(decoded(full['x'])[:2], [Fraction(10, 7), Fraction(-2, 7)])
        self.assertEqual(full['status'], 'REJECTED')
        self.assertEqual(full['reasons'], ['WEIGHTS_NONNEGATIVE'])
        self.assertLess(decoded(full['weights'])[1], 0)
        self.assertEqual(decoded(result['weights']), [Fraction(8, 11), 0, Fraction(2, 11), Fraction(1, 11)])
        self.assertEqual(gmv.verify(result)['status'], 'OK')

    def test_nonpositive_ldl_pivot_preserves_partial_and_no_support_attempt(self):
        covariance = [[1.0, 4.0, 0.0, 0.0], [4.0, 1.0, 0.0, 0.0],
                      [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
        result = gmv.solve(covariance)
        self.assertEqual((result['status'], result['reason']), ('INVALID', 'LDL_NONPOSITIVE_PIVOT'))
        self.assertEqual(decoded(result['ldl']['pivots']), [1, -3])
        self.assertEqual(result['actual_counts'], {'spd_certifications': 1,
                         'portfolio_optimizations': 0, 'support_linear_system_attempts': 0})
        self.assertEqual(result['supports'], [])
        self.assertNotIn('weights', result)

    def test_natural_support_pivot_nonpositive_is_failure_not_row_swap(self):
        record = {}
        with self.assertRaisesRegex(gmv.GMVError, 'SUPPORT_NONPOSITIVE_PIVOT'):
            gmv._gauss_jordan([[Fraction(0), Fraction(1)], [Fraction(1), Fraction(0)]],
                              [0, 1], gmv._Arithmetic(), record)
        self.assertEqual(record['pivots'], [encoded(0)])

    def test_float_dyadics_and_exact_shrinkage_not_decimal_reconstruction(self):
        covariance = diagonal()
        covariance[0][0] = 0.1
        covariance[0][1] = covariance[1][0] = 0.125
        result = gmv.solve(covariance)
        self.assertEqual(result['status'], 'OK')
        self.assertEqual(result['covariance_repr'][0][0], '0.1')
        self.assertEqual(result['covariance_q'][0][0], encoded(3602879701896397, 36028797018963968))
        self.assertEqual(result['shrunk_s'][0][1], encoded(1, 16))
        self.assertEqual(gmv.verify(result)['status'], 'OK')

    def test_shape_nonfinite_diagonal_and_asymmetry_rejected_before_solve(self):
        fixtures = [([[1.0]], 'COVARIANCE_SHAPE'), (None, 'COVARIANCE_SHAPE')]
        for key, value, reason in [(0, math.inf, 'COVARIANCE_NOT_FINITE_BINARY64'),
                                   (0, math.nan, 'COVARIANCE_NOT_FINITE_BINARY64'),
                                   (0, 0.0, 'COVARIANCE_DIAGONAL_NOT_POSITIVE'),
                                   (0, -1.0, 'COVARIANCE_DIAGONAL_NOT_POSITIVE'),
                                   (0, 1, 'COVARIANCE_NOT_FINITE_BINARY64')]:
            covariance = diagonal()
            covariance[key][key] = value
            fixtures.append((covariance, reason))
        covariance = diagonal()
        covariance[0][1], covariance[1][0] = 0.25, math.nextafter(0.25, 1.0)
        fixtures.append((covariance, 'COVARIANCE_NOT_EXACTLY_SYMMETRIC'))
        for covariance, reason in fixtures:
            with self.subTest(reason=reason):
                result = gmv.solve(covariance)
                self.assertEqual((result['status'], result['reason']), ('INVALID', reason))
                self.assertEqual(sum(result['actual_counts'].values()), 0)

    def test_numeric_guard_reports_failure_without_alternative_optimizer(self):
        # This small injected guard tests the exact production comparison branch.
        with patch.object(gmv, 'BIT_LIMIT', 8):
            covariance = diagonal()
            covariance[0][0] = 256.0
            result = gmv.solve(covariance)
        self.assertEqual(result['reason'], 'NUMERIC_BOUND')
        self.assertEqual(result['bit_limit'], 8)
        self.assertEqual(result['guard']['maximum_numerator_bits'], 9)
        self.assertEqual(result['actual_counts']['support_linear_system_attempts'], 0)
        self.assertNotIn('weights', result)

    def test_verifier_never_invokes_optimization_factorization_or_solver(self):
        result = gmv.solve(diagonal())
        with patch.object(gmv, 'solve', side_effect=AssertionError('optimizer forbidden')), \
             patch.object(gmv, '_ldl', side_effect=AssertionError('factorization forbidden')), \
             patch.object(gmv, '_gauss_jordan', side_effect=AssertionError('solver forbidden')):
            checked = gmv.verify(result)
        self.assertEqual(checked['status'], 'OK')
        self.assertEqual((checked['portfolio_optimizations'], checked['linear_system_solves'], checked['checked_supports']),
                         (0, 0, 15))

    def test_certificate_tamper_cannot_relabel_wrong_x_kkt_or_weights(self):
        original = gmv.solve(diagonal())
        edits = [lambda r: r['supports'][-1]['x'].__setitem__(0, encoded(2)),
                 lambda r: r['supports'][0]['checks'].__setitem__('inactive_kkt', True),
                 lambda r: r['weights'].__setitem__(0, encoded(1)),
                 lambda r: r['supports'][-1]['pivots'].__setitem__(0, encoded(2)),
                 lambda r: r['ldl']['pivots'].__setitem__(0, encoded(-1)),
                 lambda r: r['shrunk_s'][0].__setitem__(0, encoded(2)),
                 lambda r: r.__setitem__('selected_support_mask', 1),
                 lambda r: r['actual_counts'].__setitem__('support_linear_system_attempts', 14),
                 lambda r: r['supports'].pop()]
        for edit in edits:
            changed = deepcopy(original)
            edit(changed)
            self.assertEqual(gmv.verify(changed)['status'], 'INVALID')
        self.assertEqual(gmv.verify(original)['status'], 'OK')

    def test_noncanonical_or_invalid_rationals_and_malformed_certificate(self):
        for value in [encoded(2, 2), encoded(1, 0), {'numerator': 1, 'denominator': '1'}]:
            with self.assertRaises(gmv.GMVError):
                gmv._decode(value, gmv._Arithmetic())
        for value in [None, {}, {'schema': gmv.SCHEMA, 'status': 'INVALID', 'reason': 'OLD_FAIL'}]:
            self.assertEqual(gmv.verify(value)['status'], 'INVALID')


if __name__ == '__main__':
    unittest.main()
