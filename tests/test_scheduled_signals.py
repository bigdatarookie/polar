"""Invented literal controls for the pure scheduled target functions."""
from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR, localcontext
from fractions import Fraction
import json

import pytest

from polar.gym_contract import context
from polar.scheduled_signals import inverse_vol_targets, trend_targets


def trend_fixture():
    symbols = ['AAA', 'BBB', 'CCC', 'DDD']
    rows = [{s: 1000000 for s in symbols} for _ in range(5)]
    rows[3] = {'AAA': 1100000, 'BBB': 1000000, 'CCC': 900000, 'DDD': 1100000}
    rows[4] = {'AAA': 1, 'BBB': 990000000, 'CCC': 1, 'DDD': 1}
    return rows, symbols


def test_absolute_sleeves_do_not_reallocate_inactive_cash_and_ties_use_order():
    rows, symbols = trend_fixture()
    original = deepcopy(rows)
    result = trend_targets(rows, symbols, lookback=4, skip=1)
    assert result['weights']['SLEEVES'] == {
        'AAA': Fraction(1, 4), 'BBB': Fraction(0), 'CCC': Fraction(0), 'DDD': Fraction(1, 4)}
    assert result['weights']['MOMENTUM'] == {
        'AAA': Fraction(1), 'BBB': Fraction(0), 'CCC': Fraction(0), 'DDD': Fraction(0)}
    assert result['diagnostics']['sleeve_cash_weight'] == {'numerator': '1', 'denominator': '2'}
    assert result['diagnostics']['momenta'] == {
        'AAA': {'numerator': '1', 'denominator': '10'},
        'BBB': {'numerator': '0', 'denominator': '1'},
        'CCC': {'numerator': '-1', 'denominator': '10'},
        'DDD': {'numerator': '1', 'denominator': '10'}}
    assert result['diagnostics']['endpoint_offsets'] == {'left': -4, 'right': -1}
    assert rows == original


def test_trend_uses_exact_sign_not_binary64_and_prefix_excludes_future():
    # Decimal ratio rounds to 1 in binary64, but the exact sign is positive.
    huge = 10**30
    rows = [{'AAA': huge, 'BBB': huge}, {'AAA': huge + 1, 'BBB': huge},
            {'AAA': 5, 'BBB': 10}]
    expected = trend_targets(rows, ['AAA', 'BBB'], lookback=2, skip=1)
    assert float(huge + 1) / float(huge) - 1 == 0
    assert expected['weights']['SLEEVES'] == {'AAA': Fraction(1, 2), 'BBB': Fraction(0)}
    extended = rows + [{'AAA': 10**40, 'BBB': 1}]
    assert trend_targets(extended[:3], ['AAA', 'BBB'], lookback=2, skip=1) == expected
    changed_skipped = deepcopy(rows)
    changed_skipped[-1] = {'AAA': 10**40, 'BBB': 1}
    assert trend_targets(changed_skipped, ['AAA', 'BBB'], lookback=2, skip=1) == expected


def test_nonpositive_absolute_momentum_is_cash_and_symbol_order_is_explicit():
    rows = [{'ZZZ': 10, 'AAA': 10}, {'ZZZ': 9, 'AAA': 10}]
    result = trend_targets(rows, ['ZZZ', 'AAA'], lookback=1, skip=0)
    assert not any(result['weights']['SLEEVES'].values())
    assert not any(result['weights']['MOMENTUM'].values())
    assert result['diagnostics']['momentum_selected_symbol'] is None
    rows[-1] = {'ZZZ': 11, 'AAA': 11}
    result = trend_targets(rows, ['ZZZ', 'AAA'], lookback=1, skip=0)
    assert result['weights']['MOMENTUM'] == {'ZZZ': Fraction(1), 'AAA': Fraction(0)}


@pytest.mark.parametrize('lookback,skip', [(0, 0), (10001, 0), (2, -1), (2, 2), (True, 0), (2, False)])
def test_invalid_trend_endpoints_reject(lookback, skip):
    with pytest.raises(ValueError):
        trend_targets([{'AAA': 1}] * 5, ['AAA'], lookback=lookback, skip=skip)


@pytest.mark.parametrize('bad', [0, -1, True, 1.0, None, '10'])
def test_required_price_domain_fails_without_fill_or_cash_substitution(bad):
    rows, symbols = trend_fixture()
    rows[1]['BBB'] = bad  # Required prefix, even though not a momentum endpoint.
    with pytest.raises(ValueError, match='SCHEDULED_PRICE_DOMAIN'):
        trend_targets(rows, symbols, lookback=4, skip=1)


def test_missing_symbol_and_insufficient_history_reject():
    rows, symbols = trend_fixture()
    with pytest.raises(ValueError, match='SCHEDULED_INSUFFICIENT_HISTORY'):
        trend_targets(rows[:3], symbols, lookback=4, skip=1)
    del rows[2]['CCC']
    with pytest.raises(ValueError, match='SCHEDULED_PRICE_SYMBOLS'):
        trend_targets(rows, symbols, lookback=4, skip=1)


def identical_returns():
    return [{'AAA': p, 'BBB': p} for p in [100000000, 100100000, 100000000]]


def test_inverse_vol_identical_return_literal_weights_and_shared_risk():
    # Identical return columns imply equal sigmas and raw risks for any sum1
    # vector. Forecast risk is below 10%, so scale is exactly one for all legs.
    result = inverse_vol_targets(identical_returns(), ['AAA', 'BBB'], window=2)
    assert result['weights'] == {
        'INVERSE_VOL': {'AAA': Fraction(1, 2), 'BBB': Fraction(1, 2)},
        'EQUAL_WEIGHT': {'AAA': Fraction(1, 2), 'BBB': Fraction(1, 2)},
        'MOMENTUM': {'AAA': Fraction(1), 'BBB': Fraction(0)}}
    diagnostics = result['diagnostics']
    assert diagnostics['momentum_selected_symbol'] == 'AAA'
    assert diagnostics['raw_proportions_binary64']['INVERSE_VOL'] == {'AAA': '0.5', 'BBB': '0.5'}
    assert set(diagnostics['scales_binary64'].values()) == {'1.0'}
    assert diagnostics['post_round_risk_spread_binary64'] == '0.0'
    assert len(set(diagnostics['post_round_annual_risk_binary64'].values())) == 1
    assert float(diagnostics['common_tau_binary64']) < .10
    json.dumps(diagnostics, allow_nan=False)


def test_inverse_vol_momentum_has_no_positive_filter():
    rows = [{'ZZZ': p, 'AAA': p} for p in [100000000, 100100000, 99000000]]
    result = inverse_vol_targets(rows, ['ZZZ', 'AAA'], window=2, annual_cap=10.0)
    assert result['weights']['MOMENTUM'] == {'ZZZ': Fraction(1), 'AAA': Fraction(0)}
    assert all(float(x) < 0 for x in result['diagnostics']['momenta_binary64'].values())


def test_binary64_conversion_starts_from_original_exact_price_value_once():
    micro = 100000000000000100
    exact_float = float('100000000000.0001')
    assert exact_float != float(micro) / 1000000
    rows = [{'AAA': p, 'BBB': p} for p in [micro, micro + 1000000000000, micro - 1000000000000]]
    result = inverse_vol_targets(rows, ['AAA', 'BBB'], window=2)
    assert result['diagnostics']['price_binary64'][0] == [repr(exact_float), repr(exact_float)]


def test_heterogeneous_risk_matching_floors_without_reallocation_and_is_causal():
    symbols = ['AAA', 'BBB', 'CCC', 'DDD']
    rows = [{s: (j + 1) * 100000000 + ((i * (j + 2)) % 11) * (j + 1) * 130000 - i * 1700
             for j, s in enumerate(symbols)} for i in range(61)]
    original = deepcopy(rows)
    result = inverse_vol_targets(rows, symbols)
    diagnostics = result['diagnostics']
    for name, targets in result['weights'].items():
        assert sum(targets.values()) <= 1
        assert all(x >= 0 for x in targets.values())
        for symbol, weight in targets.items():
            before = diagnostics['scaled_pre_round_binary64'][name][symbol]
            with localcontext(context()):
                expected = Decimal(before).quantize(Decimal('1e-12'), rounding=ROUND_FLOOR)
            assert weight == Fraction(expected)
            assert Decimal(before) - expected >= 0
            assert Decimal(before) - expected < Decimal('1e-12')
    assert float(diagnostics['common_tau_binary64']) <= .10
    assert float(diagnostics['post_round_risk_spread_binary64']) <= 1e-8
    assert rows == original
    extended = rows + [{s: 1 for s in symbols}]
    assert inverse_vol_targets(extended[:61], symbols) == result


def test_zero_variance_or_zero_portfolio_risk_has_no_epsilon_repair():
    rows = identical_returns()
    for row in rows:
        row['BBB'] = 100000000
    with pytest.raises(ValueError, match='SCHEDULED_NONPOSITIVE_VARIANCE'):
        inverse_vol_targets(rows, ['AAA', 'BBB'], window=2)
    # Equal and opposite centered returns have valid marginal variance, but
    # exact zero equal-weight forecast risk; this must fail, not be repaired.
    rows = [{'AAA': a, 'BBB': b} for a, b in [
        (100000000, 100000000), (110000000, 90000000), (99000000, 99000000)]]
    with pytest.raises(ValueError, match='SCHEDULED_NONPOSITIVE_RISK'):
        inverse_vol_targets(rows, ['AAA', 'BBB'], window=2)


@pytest.mark.parametrize('cap', [0, -1, float('nan'), float('inf'), True, '0.1'])
def test_invalid_forecast_risk_cap_rejects(cap):
    with pytest.raises(ValueError, match='SCHEDULED_ANNUAL_RISK_CAP'):
        inverse_vol_targets(identical_returns(), ['AAA', 'BBB'], window=2, annual_cap=cap)
