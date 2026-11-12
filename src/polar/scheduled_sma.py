"""Pure exact SMA200 gates on caller-supplied eligible close prefixes."""
from fractions import Fraction


def sma_targets(prices, symbols):
    """Return quarter sleeves; use only the last 200 supplied eligible closes.

    The caller owns eligibility and prefix selection. This function has no event,
    execution or source state and never substitutes cash for invalid observations.
    """
    if (type(symbols) not in (list, tuple) or len(symbols) != 4 or
            any(type(symbol) is not str or not symbol for symbol in symbols) or
            list(symbols) != sorted(set(symbols))):
        raise ValueError('SMA_SYMBOLS')
    if type(prices) is not list or len(prices) < 200:
        raise ValueError('SMA_HISTORY')
    window = prices[-200:]
    expected = set(symbols)
    for row in window:
        if type(row) is not dict or set(row) != expected:
            raise ValueError('SMA_QUOTE_SHAPE')
        if any(type(row[symbol]) is not int or row[symbol] <= 0 for symbol in symbols):
            raise ValueError('SMA_QUOTE')
    sums = {symbol: sum(row[symbol] for row in window) for symbol in symbols}
    last = {symbol: window[-1][symbol] for symbol in symbols}
    margins = {symbol: 200 * last[symbol] - sums[symbol] for symbol in symbols}
    active = {symbol: margins[symbol] > 0 for symbol in symbols}
    weights = {symbol: Fraction(1, 4) if active[symbol] else Fraction(0) for symbol in symbols}
    cash = Fraction(1) - sum(weights.values(), Fraction(0))
    return {'weights': weights, 'active': active,
            'diagnostics': {'window': 200, 'last_price_micro': last,
                            'sum_price_micro': sums, 'margin_micro': margins,
                            'cash_residual': {'numerator': str(cash.numerator),
                                              'denominator': str(cash.denominator)}}}
