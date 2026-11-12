"""Independent saved-output arithmetic; no producer, evaluator, or native imports.

Extracted from Validator's check_metrics.py and saved-ledger audits (v033/v037).
These functions verify already saved observations, never generate a strategy.
"""
from datetime import datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction
import re

CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999)
YEAR_NS = 31557600 * 10**9


def utc_ns(value):
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?Z", value)
    if not match:
        raise ValueError("UTC_NANOSECOND_TOKEN")
    delta = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S") - datetime(1970, 1, 1)
    return (delta.days * 86400 + delta.seconds) * 10**9 + int((match[2] or "").ljust(9, "0"))


def decimal_token(value):
    if value is None:
        return None
    with localcontext(CONTEXT):
        number = (Decimal(value.numerator) / Decimal(value.denominator)
                  if isinstance(value, Fraction) else +Decimal(value))
        if not number.is_finite():
            raise ValueError("NONFINITE_NUMBER")
        token = format(number, "f")
        return "0" if number == 0 else token.rstrip("0").rstrip(".") if "." in token else token


def round_micro_to_cents(value):
    """Exact half-even settlement, independently expressed as integer division."""
    quotient, remainder = divmod(value, 10000)
    return quotient + int(remainder > 5000 or remainder == 5000 and quotient % 2 == 1)


def fee_cents(quantity, price_micro, flat=100, bps=10):
    return 0 if quantity == 0 else flat + (quantity * price_micro * bps + 10**8 - 1) // 10**8


def affordable(desired, price_micro, cash_cents, flat=100, bps=10):
    low, high = 0, desired
    while low < high:
        middle = (low + high + 1) // 2
        debit = round_micro_to_cents(middle * price_micro) + fee_cents(middle, price_micro, flat, bps)
        if debit <= cash_cents:
            low = middle
        else:
            high = middle - 1
    return low


def statistics(points, elapsed_ns):
    if len(points) < 3 or any(type(v) is not int or v <= 0 for v in points) or elapsed_ns <= 0:
        raise ValueError("INSUFFICIENT_POSITIVE_NAV_OR_TIME")
    returns = [Fraction(right, left) - 1 for left, right in zip(points, points[1:])]
    mean = sum(returns, Fraction(0)) / len(returns)
    variance = sum(((r - mean)**2 for r in returns), Fraction(0)) / (len(returns) - 1)
    peak, drawdown = points[0], Fraction(0)
    for point in points:
        peak = max(peak, point)
        drawdown = max(drawdown, 1 - Fraction(point, peak))
    with localcontext(CONTEXT):
        project = lambda x: Decimal(x.numerator) / Decimal(x.denominator)
        root252 = Decimal(252).sqrt()
        sd = project(variance).sqrt()
        volatility = root252 * sd
        sharpe = (root252 * project(mean)) / sd if variance else None
        ratio = project(Fraction(points[-1], points[0]))
        years = project(Fraction(elapsed_ns, YEAR_NS))
        cagr = (ratio.ln() / years).exp() - 1
    return {"returns": returns, "mean": mean, "variance": variance,
            "volatility": volatility, "sharpe": sharpe, "cagr": cagr, "drawdown": drawdown}


def metrics(nav, fills, flat=100):
    points = [r["nav_cents"] for r in nav]
    stat = statistics(points, nav[-1]["nominal_ns"] - nav[0]["nominal_ns"])
    fees = sum(f["fee_cents"] for f in fills)
    gross = sum((Fraction(f["exact_notional_micro"], 10**6) for f in fills), Fraction(0))
    intervals = len(nav) - 1
    expected = {
        "terminal_nav_usd": Fraction(points[-1], 100),
        "net_total_return": Fraction(points[-1], points[0]) - 1,
        "net_cagr_act36525": stat["cagr"], "daily_mean_return": stat["mean"],
        "daily_sample_variance": stat["variance"], "annual_vol_252": stat["volatility"],
        "sharpe_252_rf0": stat["sharpe"], "max_drawdown": stat["drawdown"],
        "flat_fee_usd": Fraction(len(fills) * flat, 100),
        "bps_cost_usd": Fraction(fees - len(fills) * flat, 100),
        "total_cost_usd": Fraction(fees, 100), "gross_exact_notional_usd": gross,
        "gross_settled_notional_usd": Fraction(sum(f["settled_cents"] for f in fills), 100),
        "gross_notional_over_initial": gross / Fraction(points[0], 100),
        "positive_fill_count": Fraction(len(fills)),
        "mean_close_exposure": sum((Fraction(r["exposure_cents"], r["nav_cents"]) for r in nav[1:]), Fraction(0)) / intervals,
        "invested_session_fraction": Fraction(sum(any(r["positions"].values()) for r in nav[1:]), intervals),
        "max_close_concentration": max((Fraction(v, r["nav_cents"]) for r in nav for v in r["position_cents"].values()), default=Fraction(0)),
    }
    return expected, stat["returns"]


def criterion(spec, left, right, initial_cents):
    """Only literal arithmetic predicates; no search or scientific interpretation."""
    kind = spec["kind"]
    if kind == "SR_DELTA_GE":
        if left["sharpe_252_rf0"] is None or right["sharpe_252_rf0"] is None:
            return None
        with localcontext(CONTEXT):
            return (Decimal(decimal_token(left["sharpe_252_rf0"])) - Decimal(decimal_token(right["sharpe_252_rf0"]))
                    >= Decimal(spec["threshold"]))
    if kind == "TERMINAL_GE":
        return left["terminal_nav_usd"] >= right["terminal_nav_usd"]
    if kind == "POSITIVE_GROWTH":
        return left["terminal_nav_usd"] > Fraction(initial_cents, 100)
    if kind in ("DRAWDOWN_LE", "DRAWDOWN_SCALED_LE"):
        factor = Fraction(*spec["factor"]) if kind == "DRAWDOWN_SCALED_LE" else Fraction(1)
        return left["max_drawdown"] <= factor * right["max_drawdown"]
    raise NotImplementedError(kind)
