"""Frozen exact rule prototype; no accepted native route or financial execution.

Covariance order is BIL, VTI. Actual runtime/source integration belongs to the
existing scheduled engine; these functions read no source, model or store.
"""
from fractions import Fraction
import math

PROTOCOL_ID = "QB-RISK-MATCHED-PRICED-RESERVE-20261118-V1"
WEIGHT_UNITS = 1_000_000
ANNUAL_CAP = Fraction(1, 10)


class PricedReserveError(ValueError):
    pass


def _number(value):
    if type(value) is float:
        if not math.isfinite(value):
            raise PricedReserveError("NONFINITE_COVARIANCE")
        return Fraction.from_float(value)
    if type(value) is int or isinstance(value, Fraction):
        return Fraction(value)
    raise PricedReserveError("INEXACT_OR_INVALID_COVARIANCE_TYPE")


def _pair(value):
    return [value.numerator, value.denominator]


def _select(matrix, units=WEIGHT_UNITS):
    if type(units) is not int or units < 1:
        raise PricedReserveError("INVALID_GRID")
    if (not isinstance(matrix, (list, tuple)) or len(matrix) != 2
            or any(not isinstance(row, (list, tuple)) or len(row) != 2 for row in matrix)):
        raise PricedReserveError("COVARIANCE_SHAPE")
    q = [[_number(x) for x in row] for row in matrix]
    b, cov, v = q[0][0], q[0][1], q[1][1]
    if cov != q[1][0]:
        raise PricedReserveError("ASYMMETRIC_COVARIANCE")
    if b < 0 or v < 0 or b * v < cov * cov:
        raise PricedReserveError("NON_PSD_COVARIANCE")
    evaluations = 0

    def cash_risk(k):
        return v * Fraction(k, units) ** 2

    def swept_risk(k):
        nonlocal evaluations
        evaluations += 1
        x = Fraction(k, units)
        return v * x*x + b * (1-x)**2 + 2 * cov * x * (1-x)

    if v == 0:
        cash_k = swept_k = 0
        target = Fraction()
        mode = "ZERO_EQUITY_FORECAST_FALLBACK_CASH"
        minimum_k = minimum_risk = next_risk = None
        selected_risk = Fraction()
    else:
        lower, upper = 0, units + 1
        while lower + 1 < upper:
            middle = (lower + upper) // 2
            if cash_risk(middle) <= ANNUAL_CAP ** 2:
                lower = middle
            else:
                upper = middle
        cash_k = lower
        target = cash_risk(cash_k)
        assert target <= ANNUAL_CAP ** 2
        assert cash_k == units or cash_risk(cash_k + 1) > ANNUAL_CAP ** 2
        curvature = b + v - 2 * cov
        assert curvature >= 0
        vertex = (b - cov) * units / curvature if curvature else Fraction()
        floor = min(units, max(0, vertex.numerator // vertex.denominator))
        candidates = {floor, min(units, floor + 1)}
        values = {k: swept_risk(k) for k in candidates}
        minimum_k = min(values, key=lambda k: (values[k], -k))
        minimum_risk = values[minimum_k]
        if minimum_risk > target:
            swept_k = cash_k
            selected_risk = target
            next_risk = None
            mode = "RISK_INFEASIBLE_GRID_FALLBACK_CASH_TARGET"
        else:
            lower, upper = minimum_k, units + 1
            while lower + 1 < upper:
                middle = (lower + upper) // 2
                if swept_risk(middle) <= target:
                    lower = middle
                else:
                    upper = middle
            swept_k = lower
            selected_risk = swept_risk(swept_k)
            next_risk = swept_risk(swept_k + 1) if swept_k < units else None
            assert selected_risk <= target
            assert next_risk is None or next_risk > target
            mode = "PRICED_RESERVE_GRID_FEASIBLE"
    cash_equity = Fraction(cash_k, units)
    swept_equity = Fraction(swept_k, units)
    reserve = 1 - swept_equity if mode == "PRICED_RESERVE_GRID_FEASIBLE" else Fraction()
    swept_cash = 1 - reserve - swept_equity
    return {
        "schema": "polar.priced-reserve-rule-prototype/1",
        "protocol_id": PROTOCOL_ID,
        "status": mode,
        "weights": {
            "SWEPT": {"BIL": _pair(reserve), "VTI": _pair(swept_equity)},
            "CASH_TARGET": {"BIL": [0, 1], "VTI": _pair(cash_equity)},
            "BIL_ONLY": {"BIL": [1, 1], "VTI": [0, 1]},
        },
        "unremunerated_cash": {"SWEPT": _pair(swept_cash),
                                "CASH_TARGET": _pair(1-cash_equity), "BIL_ONLY": [0, 1]},
        "certificate": {
            "covariance": [[_pair(x) for x in row] for row in q],
            "weight_units": units, "annual_cap": _pair(ANNUAL_CAP),
            "cash_grid_index": cash_k, "swept_equity_grid_index": swept_k,
            "target_variance": _pair(target), "selected_variance": _pair(selected_risk),
            "grid_minimum_index": minimum_k,
            "grid_minimum_variance": _pair(minimum_risk) if minimum_risk is not None else None,
            "next_grid_variance": _pair(next_risk) if next_risk is not None else None,
            "priced_reserve_risk_evaluations": evaluations,
        },
    }


def reserve_targets(annualized_covariance):
    """Prototype of the fixed rule, with no source/config/native side effects."""
    return _select(annualized_covariance)
