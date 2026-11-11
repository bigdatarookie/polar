"""Literal invented controls for pure saved-ledger descriptions; no private data."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
import json
import unittest

from polar.scheduled_diagnostics import diagnose, evaluate_segment


DAY_NS = 86400 * 10**9


def tape(values, *, days=None):
    if days is None:
        days = [(date(2020, 1, 1)+timedelta(days=i)).isoformat() for i in range(len(values))]
    nav = []
    fills = []
    for i, (day, value) in enumerate(zip(days, values)):
        ns = (date.fromisoformat(day)-date(1970, 1, 1)).days*DAY_NS + 21*3600*10**9
        nav.append({'date': day, 'nominal_ns': ns, 'sample_ns': ns+1000,
                    'nav_cents': value, 'cash_cents': value, 'position_cents': {'AAA': 0},
                    'positions': {'AAA': 0}, 'flat_cents': 0, 'bps_cents': 0})
    return {'id': 'INVENTED_SAVED_LEDGER', 'nav': nav, 'fills': fills}


def schedule(days, end_dates=()):
    return [{'date': d, 'month_end_in_reference_range': True if d in end_dates else None,
             'reference_close_utc': d+'T21:00:00+00:00'} for d in days]


class SavedDiagnostics(unittest.TestCase):
    def test_tail_exact_signed_mean_ceil_count_and_earliest_tie(self):
        t = tape([10000, 9000, 8100]+[8100]*19)
        result = diagnose(t, [])['daily_tail']
        self.assertEqual((result['n'], result['k']), (21, 2))
        self.assertEqual(result['lower_return_threshold']['value'], '-0.1')
        self.assertEqual(result['lower_tail_mean_return']['value'], '-0.1')
        self.assertEqual(result['expected_shortfall_loss']['value'], '0.1')
        self.assertEqual(result['worst_day']['date'], '2020-01-02')
        self.assertEqual(result['worst_day']['return']['value'], '-0.1')
        # Positive lower-tail returns retain negative loss ES, never clamp to zero.
        positive = diagnose(tape([100, 110, 121]), [])['daily_tail']
        self.assertEqual(positive['lower_tail_mean_return']['value'], '0.1')
        self.assertEqual(positive['expected_shortfall_loss']['value'], '-0.1')

    def test_horizons_use_continuous_account_and_earliest_ties(self):
        result = diagnose(tape([10000]*65), [])['worst_horizons']
        for h in (1, 21, 63):
            self.assertEqual(result[str(h)]['windows'], 65-h)
            self.assertEqual(result[str(h)]['start_date'], '2020-01-01')
            self.assertEqual(result[str(h)]['net_return']['value'], '0')
        t = tape([10000]*63+[8000])
        worst = diagnose(t, [])['worst_horizons']['21']
        self.assertEqual(worst['start_date'], t['nav'][42]['date'])
        self.assertEqual(worst['end_date'], t['nav'][63]['date'])
        self.assertEqual(worst['net_return']['value'], '-0.2')
        short = diagnose(tape([10000, 9000]), [])['worst_horizons']['21']
        self.assertEqual(short['status'], 'UNAVAILABLE')
        self.assertEqual(short['reason'], 'INSUFFICIENT_RETURN_INTERVALS')
        self.assertIsNone(short['value'])

    def test_earliest_drawdown_trough_and_peak_then_first_recovery(self):
        t = tape([100, 120, 90, 120, 90, 120])
        result = diagnose(t, [])['drawdown']
        self.assertEqual(result['maximum_depth']['value'], '0.25')
        self.assertEqual(result['peak']['date'], '2020-01-02')
        self.assertEqual(result['trough']['date'], '2020-01-03')
        self.assertEqual(result['recovery']['date'], '2020-01-04')
        self.assertEqual(result['peak_to_trough_intervals'], 1)
        self.assertEqual(result['trough_to_recovery_intervals'], 1)
        self.assertEqual(result['peak_to_recovery_intervals'], 2)
        self.assertEqual(result['peak_to_trough_seconds']['value'], '86400')
        self.assertEqual(result['peak_to_recovery_seconds']['value'], '172800')
        self.assertEqual(result['time_underwater_fraction']['value'], '0.4')

    def test_unrecovered_is_censored_not_zero_duration(self):
        result = diagnose(tape([100, 120, 90, 95]), [])['drawdown']
        self.assertEqual(result['status'], 'UNRECOVERED_BY_TERMINAL')
        self.assertIsNone(result['recovery'])
        self.assertIsNone(result['trough_to_recovery_intervals'])
        self.assertEqual(result['censored_peak_to_terminal_intervals'], 2)
        self.assertEqual(result['censored_peak_to_terminal_seconds']['value'], '172800')

    def test_no_drawdown_has_no_fictitious_recovery(self):
        result = diagnose(tape([100, 100, 100]), [])['drawdown']
        self.assertEqual(result['status'], 'NO_DRAWDOWN')
        self.assertEqual(result['recovery_status'], 'NOT_APPLICABLE')
        self.assertEqual(result['maximum_depth']['value'], '0')
        for key in ('peak', 'trough', 'recovery', 'peak_to_recovery_intervals'):
            self.assertIsNone(result[key])

    def test_full_months_require_prior_close_and_bound_month_end(self):
        days = ['2022-12-30', '2023-01-03', '2023-01-31', '2023-02-01', '2023-02-28', '2023-03-01', '2023-03-06']
        t = tape([10000, 11000, 9000, 9900, 10800, 10000, 11000], days=days)
        result = diagnose(t, schedule(days, ['2022-12-30', '2023-01-31', '2023-02-28']))['calendar_months']
        self.assertEqual((result['complete_count'], result['partial_count']), (2, 1))
        self.assertEqual([m['month'] for m in result['months']], ['2023-01', '2023-02', '2023-03'])
        self.assertEqual(result['worst_full_month']['month'], '2023-01')
        self.assertEqual(result['worst_full_month']['net_return']['value'], '-0.1')
        self.assertEqual(result['months'][1]['net_return']['value'], '0.2')
        self.assertEqual(result['months'][2]['status'], 'PARTIAL')
        self.assertIn('ACTUAL_MONTH_END_NOT_BOUND', result['months'][2]['reason'])
        self.assertEqual(result['months'][2]['initial_date'], '2023-02-28')

    def test_month_without_preceding_close_is_not_silently_full(self):
        source_days = ['2022-12-30', '2023-01-03', '2023-01-31']
        t = tape([11000, 9000], days=source_days[1:])
        result = diagnose(t, schedule(source_days, ['2022-12-30', '2023-01-31']))['calendar_months']
        self.assertEqual(result['complete_count'], 0)
        self.assertEqual(result['worst_full_month']['status'], 'UNAVAILABLE')
        self.assertIn('PRECEDING_REFERENCE_CLOSE_MISSING', result['months'][0]['reason'])

    def test_exposure_uses_postinitial_own_nav_not_initial_capital(self):
        t = tape([10000, 10000, 20000])
        t['nav'][1].update(cash_cents=5000, positions={'AAA': 1}, position_cents={'AAA': 5000})
        t['nav'][2].update(cash_cents=5000, positions={'AAA': 2}, position_cents={'AAA': 15000})
        result = diagnose(t, [])['exposure']
        self.assertEqual(result['mean_asset_fractions']['AAA']['value'], '0.625')
        self.assertEqual(result['mean_cash_fraction']['value'], '0.375')
        self.assertEqual(result['maximum_single_asset_fraction']['value'], '0.75')
        self.assertEqual(result['invested_close_fraction']['value'], '1')

    def test_missing_exposure_accounting_is_explicit_not_zero(self):
        t = tape([10000, 11000, 10000])
        del t['nav'][1]['position_cents']
        result = diagnose(t, [])
        self.assertEqual(result['exposure']['status'], 'UNAVAILABLE')
        self.assertEqual(result['exposure']['missing_rows'], 1)
        self.assertEqual(result['daily_tail']['status'], 'OK')

    def test_max_concentration_keeps_subperiod_carried_anchor(self):
        t = tape([10000, 10000, 10000])
        t['nav'][0].update(cash_cents=0, positions={'AAA': 10}, position_cents={'AAA': 10000})
        result = diagnose(t, [])['exposure']
        self.assertEqual(result['mean_asset_fractions']['AAA']['value'], '0')
        self.assertEqual(result['maximum_single_asset_fraction']['value'], '1')

    def test_subperiod_preceding_anchor_cumulative_differences_and_carried_holdings(self):
        t = tape([10000, 12000, 15000, 18000, 20000])
        for i, row in enumerate(t['nav']):
            row.update(flat_cents=i*100, bps_cents=i*10,
                       cash_cents=row['nav_cents']//2, positions={'AAA': 1},
                       position_cents={'AAA': row['nav_cents']-row['nav_cents']//2})
            if i:
                t['fills'].append({'at_ns': row['nominal_ns']+500, 'q': 1,
                                   'exact_notional_micro': i*10000000, 'settled_cents': i*1000})
        before = deepcopy(t)
        result = evaluate_segment(t, '2020-01-03', '2020-01-04')
        self.assertEqual(result['initial_date'], '2020-01-02')
        self.assertEqual(result['intervals'], 2)
        self.assertEqual(result['metrics']['initial_nav_cents'], '12000')
        self.assertEqual(result['metrics']['net_total_return']['value'], '0.5')
        self.assertEqual(result['initial_holdings']['positions']['AAA'], '1')
        self.assertEqual(result['terminal_holdings']['positions']['AAA'], '1')
        self.assertEqual(result['costs']['flat_cents']['value'], '200')
        self.assertEqual(result['costs']['bps_cents']['value'], '20')
        self.assertEqual(result['costs']['total_fee_usd']['value'], '2.2')
        self.assertEqual(result['costs']['positive_fill_count']['value'], '2')
        self.assertEqual(result['costs']['gross_exact_notional_usd']['value'], '50')
        self.assertEqual(result['costs']['gross_settled_notional_usd']['value'], '50')
        self.assertEqual(result['costs']['normalization_initial_nav_cents'], '12000')
        self.assertEqual(Decimal(result['costs']['gross_notional_over_initial']['value']),
                         Decimal('0.41666666666666666666666666666666666666666666666667'))
        self.assertEqual(t, before)

    def test_missing_subperiod_boundary_or_accounting_never_fills(self):
        t = tape([10000, 12000, 15000])
        self.assertEqual(evaluate_segment(t, '2020-01-01', '2020-01-03')['reason'], 'PRECEDING_REFERENCE_CLOSE_MISSING')
        self.assertEqual(evaluate_segment(t, '2020-01-02', '2020-01-04')['reason'], 'SUBPERIOD_BOUNDARY_MISSING')
        del t['fills']
        result = evaluate_segment(t, '2020-01-02', '2020-01-03')
        self.assertEqual(result['costs']['positive_fill_count']['status'], 'UNAVAILABLE')
        self.assertEqual(result['costs']['positive_fill_count']['reason'], 'MISSING_SAVED_FILL_LEDGER')
        self.assertEqual(result['costs']['total_fee_usd']['value'], '0')

    def test_invalid_nav_rejected_and_missing_nav_explicit(self):
        for value in (0, -1, True, 1.0):
            t = tape([10000, value])
            with self.assertRaisesRegex(ValueError, 'NAV_DOMAIN'):
                diagnose(t, [])
        self.assertEqual(diagnose({'id': 'MISSING'}, [])['status'], 'UNAVAILABLE')
        t = tape([10000, 11000]); del t['nav'][1]['nav_cents']
        self.assertEqual(diagnose(t, [])['reason'], 'MISSING_REQUIRED_NAV_FIELDS')

    def test_output_is_deterministic_json_and_no_factor_claim(self):
        t = tape([10000, 11000, 10000])
        result = diagnose(t, schedule([r['date'] for r in t['nav']]), subperiods=[('2020-01-02', '2020-01-03')])
        raw = json.dumps(result, sort_keys=True, allow_nan=False)
        self.assertEqual(raw, json.dumps(diagnose(t, schedule([r['date'] for r in t['nav']]), subperiods=[('2020-01-02', '2020-01-03')]), sort_keys=True, allow_nan=False))
        self.assertEqual(result['factor_attribution']['status'], 'NOT_ESTIMATED')


if __name__ == '__main__':
    unittest.main()
