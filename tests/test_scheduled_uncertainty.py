"""Invented saved-return controls for fixed paired circular-block analysis."""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import json
import unittest

from polar.scheduled_uncertainty import (BIT_LIMIT, SAMPLES, _InvalidStatistic,
                                        _bounded, _indices, _interval, bootstrap)


def rational(r):
    return {'numerator': str(r.numerator), 'denominator': str(r.denominator)}


def simulation(strategy, ew=None, mom=None):
    ew = strategy if ew is None else ew
    mom = strategy if mom is None else mom
    return {'legs': [{'id': name, 'returns': [rational(Fraction(r)) for r in vector]}
                     for name, vector in [('STRATEGY', strategy), ('EW', ew), ('MOM', mom)]]}


def comparison(result, benchmark):
    return next(x for x in result['comparisons'] if x['benchmark_id'] == benchmark)


class SavedBootstrap(unittest.TestCase):
    def test_paired_equal_vectors_have_exact_zero_differences_every_draw(self):
        source = simulation([Fraction(1, 10), Fraction(-1, 20), Fraction(1, 50), Fraction(-1, 100)])
        before = deepcopy(source)
        result = bootstrap(source, 'STRATEGY', ['EW', 'MOM'])
        self.assertEqual(source, before)
        self.assertEqual((result['samples'], result['block_length'], result['seed']), (1000, 63, 37001))
        self.assertTrue(result['all_components_valid'])
        self.assertEqual(len(result['replicates']), 1000)
        for draw in result['replicates']:
            for c in draw['comparisons']:
                for name in ('sr_delta', 'growth_delta', 'drawdown_delta'):
                    self.assertEqual(c[name], {'value': '0', 'status': 'OK', 'reason': None})
        for c in result['comparisons']:
            for name in ('sr_delta', 'growth_delta', 'drawdown_delta'):
                self.assertEqual((c[name]['lower'], c[name]['upper']), ('0', '0'))
                self.assertEqual((c[name]['valid_count'], c[name]['invalid_count']), (1000, 0))
                self.assertEqual((c[name]['lower_order_index'], c[name]['upper_order_index']), (24, 975))

    def test_growth_is_cumulative_wealth_ratio_and_dd_sign_is_strategy_minus_control(self):
        # All means are zero; cumulative wealths are .75, .9375, .99, not zero.
        result = bootstrap(simulation([Fraction(1, 2), Fraction(-1, 2)],
                                      [Fraction(1, 4), Fraction(-1, 4)],
                                      [Fraction(1, 10), Fraction(-1, 10)]), 'STRATEGY', ['EW', 'MOM'])
        ew, mom = comparison(result, 'EW'), comparison(result, 'MOM')
        self.assertEqual((ew['growth_delta']['lower'], ew['growth_delta']['upper']), ('-0.1875', '-0.1875'))
        self.assertEqual((mom['growth_delta']['lower'], mom['growth_delta']['upper']), ('-0.24', '-0.24'))
        self.assertEqual((ew['drawdown_delta']['lower'], mom['drawdown_delta']['lower']), ('0.25', '0.4'))
        self.assertEqual(ew['sr_delta']['lower'], '0')
        self.assertTrue(result['all_components_valid'])

    def test_nonzero_sharpe_difference_uses_written_fresh_d50_order(self):
        # Literal moments: strategy mean .5, sample variance .5; control .25,1.125.
        result = bootstrap(simulation([Fraction(1), Fraction(0)],
                                      [Fraction(1), Fraction(-1, 2)]), 'STRATEGY', ['EW', 'MOM'])
        expected = '7.4833147735478827711674974646330986035120396155571'
        self.assertEqual(comparison(result, 'EW')['sr_delta']['lower'], expected)
        self.assertEqual(comparison(result, 'EW')['sr_delta']['upper'], expected)

    def test_circular_blocks_wrap_and_truncate_without_extra_rng_draws(self):
        class Starts:
            def __init__(self):
                self.calls = []
                self.values = iter([68, 5])

            def randrange(self, n):
                self.calls.append(n)
                return next(self.values)

        rng = Starts()
        indices = _indices(70, rng)
        self.assertEqual(indices[:5], [68, 69, 0, 1, 2])
        self.assertEqual(indices[:63], list(range(68, 70))+list(range(61)))
        self.assertEqual(indices[63:], list(range(5, 12)))
        self.assertEqual(rng.calls, [70, 70])
        self.assertEqual(len(indices), 70)

    def test_cash_sharpe_invalid_keeps_growth_dd_and_all_draws(self):
        active = [Fraction(1, 10), Fraction(-1, 10)]
        result = bootstrap(simulation(active, [0, 0], active), 'STRATEGY', ['EW', 'MOM'])
        ew = comparison(result, 'EW')
        self.assertEqual(ew['sr_delta']['status'], 'UNAVAILABLE')
        self.assertEqual((ew['sr_delta']['valid_count'], ew['sr_delta']['invalid_count']), (0, 1000))
        self.assertEqual(ew['sr_delta']['invalid_reason_counts'], {'BENCHMARK_ZERO_VARIANCE': 1000})
        self.assertIsNone(ew['sr_delta']['lower'])
        self.assertEqual((ew['growth_delta']['valid_count'], ew['drawdown_delta']['valid_count']), (1000, 1000))
        self.assertEqual(ew['growth_delta']['lower'], '-0.01')
        self.assertEqual(result['status'], 'INSUFFICIENT')
        self.assertFalse(result['all_components_valid'])
        self.assertEqual(len(result['replicates']), SAMPLES)
        for d in result['replicates']:
            self.assertEqual(d['comparisons'][0]['sr_delta']['status'], 'INVALID_STATISTIC')

    def test_empirical_indices_and_partial_valid_subset_are_explicit(self):
        interval = _interval([Decimal(i) for i in range(41)], Counter({'ZERO_VARIANCE': 959}), 1000)
        self.assertEqual((interval['lower_order_index'], interval['upper_order_index']), (1, 39))
        self.assertEqual((interval['lower'], interval['upper']), ('1', '39'))
        self.assertEqual((interval['valid_count'], interval['invalid_count']), (41, 959))
        self.assertEqual(interval['status'], 'DESCRIPTIVE_VALID_SUBSET_ONLY')
        self.assertEqual(interval['invalid_reason_counts'], {'ZERO_VARIANCE': 959})
        empty = _interval([], Counter({'INTEGER_BOUND': 1000}), 1000)
        self.assertEqual(empty['status'], 'UNAVAILABLE')
        self.assertIsNone(empty['lower_order_index'])
        self.assertIsNone(empty['upper'])

    def test_missing_observation_is_not_dropped_or_replaced(self):
        source = simulation([Fraction(1, 10), Fraction(-1, 10)])
        source['legs'][1]['returns'][1] = None
        result = bootstrap(source, 'STRATEGY', ['EW', 'MOM'])
        ew = comparison(result, 'EW')
        for name in ('sr_delta', 'growth_delta', 'drawdown_delta'):
            self.assertEqual((ew[name]['valid_count'], ew[name]['invalid_count']), (0, 1000))
            self.assertEqual(ew[name]['invalid_reason_counts'], {'BENCHMARK_MISSING_OR_INVALID_EXACT_RETURN': 1000})
        self.assertEqual(comparison(result, 'MOM')['growth_delta']['valid_count'], 1000)
        self.assertEqual(result['n'], 2)

    def test_fixed_size_vectors_cannot_silently_use_common_prefix(self):
        result = bootstrap(simulation([Fraction(1, 10), Fraction(-1, 10)], [Fraction(1, 10)]), 'STRATEGY', ['EW', 'MOM'])
        self.assertEqual(comparison(result, 'EW')['growth_delta']['invalid_reason_counts'],
                         {'BENCHMARK_RETURN_VECTOR_LENGTH_MISMATCH': 1000})
        self.assertEqual(result['n'], 2)

    def test_integer_bound_and_nonpositive_path_are_explicit(self):
        with self.assertRaisesRegex(_InvalidStatistic, 'INTEGER_BOUND'):
            _bounded(Fraction(256), limit=8)
        vector = [Fraction(1, 1 << (BIT_LIMIT+1)), Fraction(1, 10)]
        source = {'legs': [{'id': 'STRATEGY', 'returns': vector},
                           {'id': 'EW', 'returns': [Fraction(1, 10), Fraction(-1, 10)]},
                           {'id': 'MOM', 'returns': [Fraction(1, 10), Fraction(-1, 10)]}]}
        result = bootstrap(source, 'STRATEGY', ['EW', 'MOM'])
        self.assertEqual(comparison(result, 'EW')['growth_delta']['invalid_reason_counts'], {'STRATEGY_INTEGER_BOUND': 1000})
        source = simulation([Fraction(1, 10), Fraction(-1)])
        result = bootstrap(source, 'STRATEGY', ['EW', 'MOM'])
        self.assertEqual(comparison(result, 'EW')['sr_delta']['invalid_reason_counts'], {'STRATEGY_NONPOSITIVE_GROSS_RETURN': 1000})

    def test_native_nav_and_rational_saved_vectors_are_identical_and_repeatable(self):
        vector = [Fraction(1, 10), Fraction(-1, 20), Fraction(1, 50)]
        a = bootstrap(simulation(vector), 'STRATEGY', ['EW', 'MOM'])
        native = {'legs': [{'id': name, 'nav': [{'nav_cents': v} for v in (10000, 11000, 10450, 10659)]}
                           for name in ('STRATEGY', 'EW', 'MOM')]}
        b = bootstrap(native, 'STRATEGY', ['EW', 'MOM'])
        self.assertEqual(a, b)
        self.assertEqual(a, bootstrap(simulation(vector), 'STRATEGY', ['EW', 'MOM']))
        self.assertEqual(len(a['index_sequence_sha256']), 64)
        self.assertNotEqual(a['replicates'][0]['indices_sha256'], a['replicates'][1]['indices_sha256'])
        json.dumps(a, sort_keys=True, allow_nan=False)

    def test_public_api_rejects_wrong_base_leg_set(self):
        source = simulation([Fraction(1, 10), Fraction(-1, 10)])
        source['legs'].append({'id': 'STRESS_NOT_BASE', 'returns': [0, 0]})
        with self.assertRaisesRegex(ValueError, 'THREE_BASE_LEG_IDENTITIES'):
            bootstrap(source, 'STRATEGY', ['EW', 'MOM'])


if __name__ == '__main__':
    unittest.main()
