"""Independent analytic and exhaustive invented oracles; no source or engine."""
from fractions import Fraction as F
import unittest
from unittest.mock import patch
from polar.qb_equal_risk_contribution_prototype import (
    SYMBOLS, RiskBudgetError, equal_risk_targets, quadratic, _scale,
)


def fractions(row):
    return [F(*row[s]) for s in SYMBOLS]


class Prototype(unittest.TestCase):
    def test_diagonal_analytic_inverse_sigma_budget(self):
        matrix = [[F((i+1)**2, 10000) if i == j else 0 for j in range(4)] for i in range(4)]
        result = equal_risk_targets(matrix)
        expected = [F(12,25), F(6,25), F(4,25), F(3,25)]
        for got, want in zip(fractions(result['raw_weights']['ERC']), expected):
            self.assertLess(abs(got-want), F(1,10**70))
        self.assertEqual(result['actual_counts']['coordinate_updates'], 4*result['actual_counts']['coordinate_sweeps'])

    def test_equal_diagonal_exchangeability_and_singular_psd(self):
        for off in (F(-1,3), F(1,5), F(1)):
            # Singular endpoints are valid before exact half-diagonal shrinkage.
            matrix = [[F(1,100) if i == j else off/100 for j in range(4)] for i in range(4)]
            result = equal_risk_targets(matrix)
            weights = fractions(result['raw_weights']['ERC'])
            for w in weights:
                self.assertLess(abs(w-F(1,4)), F(1,10**8))

    def test_general_gram_geometry_certificate_independently(self):
        vectors = [[1,0,-1,2], [0,2,1,-1], [1,1,3,0], [2,-1,0,1]]
        original = [[sum(a*b for a,b in zip(x,y)) for y in vectors] for x in vectors]
        result = equal_risk_targets(original)
        cov = [[F(original[i][j],1 if i==j else 2) for j in range(4)] for i in range(4)]
        weights = fractions(result['raw_weights']['ERC'])
        total = sum(weights[i]*cov[i][j]*weights[j] for i in range(4) for j in range(4))
        for i in range(4):
            share = weights[i]*sum(cov[i][j]*weights[j] for j in range(4))/total
            self.assertLessEqual(abs(4*share-1), F(1,10**8))
        for name in ('ERC','INV','EW'):
            row = fractions(result['weights'][name]);scale = result['certificate']['scales'][name]
            self.assertEqual(sum(row)+F(*scale['cash']), 1)
            self.assertLessEqual(252*quadratic(row,cov), F(*result['certificate']['annual_common_target_variance']))

    def test_small_grid_exhaustive_oracle(self):
        for units in (1,2,3,7,17):
            for variance in (F(1,100), F(3,7), F(2)):
                for divisor in (1,2,9):
                    target=variance/divisor
                    expected=max(k for k in range(units+1) if variance*F(k,units)**2<=target)
                    self.assertEqual(_scale(variance,target,units)[0], expected)

    def test_binary64_operands_preserved_and_invalid_rejected(self):
        matrix = [[0.01 if i==j else 0.0 for j in range(4)] for i in range(4)]
        value=equal_risk_targets(matrix)
        self.assertEqual(F(*value['certificate']['sample_covariance'][0][0]), F.from_float(0.01))
        for bad in (float('nan'), float('inf'), -1, 0, True, '0.01'):
            x=[row[:] for row in matrix];x[0][0]=bad
            with self.assertRaises(RiskBudgetError):equal_risk_targets(x)
        x=[row[:] for row in matrix];x[0][1]=0.1
        with self.assertRaises(RiskBudgetError):equal_risk_targets(x)
        x=[row[:] for row in matrix];x[0][1]=x[1][0]=1
        with self.assertRaises(RiskBudgetError):equal_risk_targets(x)

    def test_partial_work_failure_retains_actual_completed_counts(self):
        matrix = [[1 if i==j else 0 for j in range(4)] for i in range(4)]
        with patch('polar.qb_equal_risk_contribution_prototype.contribution_certificate',
                   side_effect=RiskBudgetError('INVENTED_CERTIFICATE_FAILURE')):
            with self.assertRaises(RiskBudgetError) as error:
                equal_risk_targets(matrix)
        counts=error.exception.events['actual_counts']
        self.assertEqual(counts['coordinate_sweeps'],1)
        self.assertEqual(counts['coordinate_update_attempts'],4)
        self.assertEqual(counts['coordinate_updates'],4)
        self.assertEqual(counts['exact_budget_checks'],0)


if __name__ == '__main__':
    unittest.main()
