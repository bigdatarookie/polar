"""Independent enumerative oracle on invented PSD operands only."""
from fractions import Fraction as F
from itertools import product
import unittest

from polar.qb_priced_reserve_prototype import (
    ANNUAL_CAP, PricedReserveError, _select, reserve_targets,
)


def ratio(pair):
    return F(*pair)


class PricedReserveTests(unittest.TestCase):
    def test_zero_risk_bill_keeps_cash_target_equity_and_invests_residual(self):
        x = reserve_targets([[F(0), F(0)], [F(0), F(1, 25)]])
        self.assertEqual(x['weights']['CASH_TARGET']['VTI'], [1, 2])
        self.assertEqual(x['weights']['SWEPT'], {'BIL': [1, 2], 'VTI': [1, 2]})
        self.assertEqual(x['unremunerated_cash']['SWEPT'], [0, 1])
        self.assertEqual(ratio(x['certificate']['selected_variance']), F(1, 100))

    def test_singular_negative_covariance_valid_and_maximal_root(self):
        x = reserve_targets([[F(1, 25), F(-1, 25)], [F(-1, 25), F(1, 25)]])
        self.assertEqual(x['weights']['CASH_TARGET']['VTI'], [1, 2])
        self.assertEqual(x['weights']['SWEPT']['VTI'], [3, 4])
        self.assertEqual(x['weights']['SWEPT']['BIL'], [1, 4])
        self.assertGreater(ratio(x['certificate']['next_grid_variance']), F(1, 100))

    def test_infeasible_reserve_risk_has_explicit_cash_fallback(self):
        x = reserve_targets([[F(9, 100), F(3, 100)], [F(3, 100), F(1, 25)]])
        self.assertEqual(x['status'], 'RISK_INFEASIBLE_GRID_FALLBACK_CASH_TARGET')
        self.assertEqual(x['weights']['SWEPT'], x['weights']['CASH_TARGET'])
        self.assertEqual(x['unremunerated_cash']['SWEPT'], [1, 2])
        self.assertGreater(ratio(x['certificate']['grid_minimum_variance']), ratio(x['certificate']['target_variance']))

    def test_zero_equity_forecast_is_not_inferred_carry(self):
        x = reserve_targets([[F(1, 100), F(0)], [F(0), F(0)]])
        self.assertEqual(x['status'], 'ZERO_EQUITY_FORECAST_FALLBACK_CASH')
        self.assertEqual(x['weights']['SWEPT'], {'BIL': [0, 1], 'VTI': [0, 1]})
        self.assertEqual(x['unremunerated_cash']['SWEPT'], [1, 1])
        self.assertEqual(x['weights']['BIL_ONLY']['BIL'], [1, 1])

    def test_cap_not_binding_all_equity_is_valid(self):
        x = reserve_targets([[F(1, 1000), F(0)], [F(0), F(1, 400)]])
        self.assertEqual(x['weights']['SWEPT']['VTI'], [1, 1])
        self.assertEqual(x['weights']['SWEPT']['BIL'], [0, 1])

    def test_exact_binary64_operands_preserved(self):
        x = reserve_targets([[0.0001, 0.0], [0.0, 0.04]])
        self.assertEqual(ratio(x['certificate']['covariance'][0][0]), F.from_float(0.0001))
        self.assertEqual(ratio(x['certificate']['covariance'][1][1]), F.from_float(0.04))

    def test_nonfinite_nonsymmetric_nonpsd_and_types_fail(self):
        for matrix in [[[float('nan'), 0.], [0., .1]], [[.1, .02], [.03, .1]],
                       [[1, 2], [2, 1]], [[-1, 0], [0, 1]], [[True, 0], [0, 1]], [["0.1", 0], [0, 1]], [[1]]]:
            with self.subTest(matrix=matrix), self.assertRaises(PricedReserveError):
                reserve_targets(matrix)

    def test_small_grid_against_independent_full_enumeration(self):
        units = 17
        for b1, b2, v1, v2 in product((F(-1, 5), F(0), F(1, 5)), repeat=4):
            b, v, cov = b1*b1+b2*b2, v1*v1+v2*v2, b1*v1+b2*v2
            x = _select([[b, cov], [cov, v]], units)
            cash_k = max(k for k in range(units+1) if v*F(k, units)**2 <= ANNUAL_CAP**2) if v else 0
            target = v * F(cash_k, units)**2
            allowed = [k for k in range(units+1)
                       if v*F(k, units)**2+b*(1-F(k, units))**2+2*cov*F(k, units)*(1-F(k, units)) <= target] if v else []
            swept_k = max(allowed) if allowed else cash_k
            self.assertEqual(x['certificate']['cash_grid_index'], cash_k)
            self.assertEqual(x['certificate']['swept_equity_grid_index'], swept_k)
            self.assertEqual(ratio(x['certificate']['target_variance']), target)
            self.assertEqual(x['status']=='PRICED_RESERVE_GRID_FEASIBLE', bool(allowed))
            for leg in x['weights']:
                self.assertEqual(sum((ratio(z) for z in x['weights'][leg].values()), F())
                                 +ratio(x['unremunerated_cash'][leg]), 1)


if __name__ == '__main__':
    unittest.main()
