"""Invented exact SMA200 controls; no real source or execution calls."""
from fractions import Fraction
import json

import pytest

from polar.scheduled_sma import sma_targets


SYMBOLS = ['ONE', 'THREE', 'TWO', 'ZERO']


def flat(count=200, price=1000000):
    return [{symbol: price for symbol in SYMBOLS} for _ in range(count)]


def test_flat_equality_inactive_and_cash_exact():
    result = sma_targets(flat(), SYMBOLS)
    assert result['weights'] == dict.fromkeys(SYMBOLS, Fraction(0))
    assert result['active'] == dict.fromkeys(SYMBOLS, False)
    assert result['diagnostics'] == {
        'window': 200, 'last_price_micro': dict.fromkeys(SYMBOLS, 1000000),
        'sum_price_micro': dict.fromkeys(SYMBOLS, 200000000),
        'margin_micro': dict.fromkeys(SYMBOLS, 0),
        'cash_residual': {'numerator': '1', 'denominator': '1'}}


def test_literal_one_microprice_above_below_mixed_quarters_and_current_included():
    prices = flat()
    prices[-1]['ONE'] = 1000001
    prices[-1]['THREE'] = 999999
    prices[-1]['TWO'] = 1000001
    result = sma_targets(prices, SYMBOLS)
    assert result['weights'] == {'ONE': Fraction(1, 4), 'THREE': Fraction(0),
                                 'TWO': Fraction(1, 4), 'ZERO': Fraction(0)}
    assert result['active'] == {'ONE': True, 'THREE': False, 'TWO': True, 'ZERO': False}
    assert result['diagnostics']['sum_price_micro'] == {
        'ONE': 200000001, 'THREE': 199999999, 'TWO': 200000001, 'ZERO': 200000000}
    assert result['diagnostics']['margin_micro'] == {'ONE': 199, 'THREE': -199, 'TWO': 199, 'ZERO': 0}
    assert result['diagnostics']['cash_residual'] == {'numerator': '1', 'denominator': '2'}
    json.dumps(result['diagnostics'], allow_nan=False)
    assert prices[-1]['ONE'] == 1000001


def test_all_active_has_no_cash_and_no_rescaling():
    prices = flat()
    prices[-1] = dict.fromkeys(SYMBOLS, 2000000)
    result = sma_targets(prices, SYMBOLS)
    assert result['weights'] == dict.fromkeys(SYMBOLS, Fraction(1, 4))
    assert result['diagnostics']['cash_residual'] == {'numerator': '0', 'denominator': '1'}


def test_only_last_200_and_no_external_future_or_mutation():
    prefix = flat()
    prefix[-1]['ONE'] += 1
    expected = sma_targets(prefix, SYMBOLS)
    assert sma_targets([{'unneeded_old_row': None}] + prefix, SYMBOLS) == expected
    # The caller passes the eligible prefix, never the later observations.
    later = prefix + [dict.fromkeys(SYMBOLS, 999999999)]
    assert sma_targets(later[:200], SYMBOLS) == expected
    prefix[-1]['ONE'] += 1
    assert expected['diagnostics']['last_price_micro']['ONE'] == 1000001


@pytest.mark.parametrize('count', [0, 1, 199])
def test_insufficient_history_never_cash_fallback(count):
    with pytest.raises(ValueError, match='SMA_HISTORY'):
        sma_targets(flat(count), SYMBOLS)


@pytest.mark.parametrize('symbols', [[], ['A', 'B', 'C'], ['A', 'B', 'C', 'C'],
    ['B', 'A', 'C', 'D'], ['A', 'B', 'C', ''], ['A', 'B', 'C', 1], 'ABCD', None])
def test_exact_four_sorted_unique_symbols(symbols):
    with pytest.raises(ValueError, match='SMA_SYMBOLS'):
        sma_targets(flat(), symbols)


@pytest.mark.parametrize('value', [True, False, 1.0, float('nan'), float('inf'), 0, -1, '1', None])
def test_invalid_required_integer_quote(value):
    prices = flat()
    prices[0]['ONE'] = value
    with pytest.raises(ValueError, match='SMA_QUOTE'):
        sma_targets(prices, SYMBOLS)


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'row_type', 'history_type'])
def test_shape_failures(mutation):
    prices = flat()
    if mutation == 'missing': del prices[0]['ONE']
    elif mutation == 'extra': prices[0]['EXTRA'] = 1
    elif mutation == 'row_type': prices[0] = list(prices[0].values())
    elif mutation == 'history_type': prices = tuple(prices)
    with pytest.raises(ValueError, match='SMA_HISTORY|SMA_QUOTE_SHAPE'):
        sma_targets(prices, SYMBOLS)
