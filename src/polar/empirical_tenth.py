"""Pure lower empirical inverse-CDF at exact alpha1/10, not a forecast."""
from dataclasses import dataclass
import math


class EmpiricalTenthError(ValueError):
    """Stable code only, without caller values."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class EmpiricalTenthResult:
    status: str
    q: float | None
    selected_rank: int | None
    supplied_count: int | None
    required_count: int
    reasons: tuple[str, ...]


def lower_empirical_tenth(values, *, expected_count, max_rows) -> EmpiricalTenthResult:
    """Select the lower endpoint from a complete represented binary64 window.

    Fixed sequence: positive exact-int max_rows, then expected_count, then
    None/exact-tuple shape; count-domain bounds; whole-window absence;
    overfull tuple; strict slot types; all missing/short/nonfinite reasons;
    only then copy-sort and select rank(n+9)//10. Never coerce an iterable,
    salvage a smaller effective n, interpolate, weight or mutate input.
    """
    if type(max_rows) is not int or max_rows <= 0:
        raise EmpiricalTenthError('INVALID_MAX_ROWS')
    if type(expected_count) is not int or expected_count <= 0:
        raise EmpiricalTenthError('INVALID_EXPECTED_COUNT')
    if values is not None and type(values) is not tuple:
        raise EmpiricalTenthError('IMMUTABLE_TUPLE_REQUIRED')
    if expected_count > max_rows or values is not None and len(values) > max_rows:
        raise EmpiricalTenthError('CALL_DOMAIN_EXCEEDED')
    if values is None:
        return EmpiricalTenthResult('WINDOW_UNAVAILABLE', None, None, None,
                                    expected_count, ('WINDOW_NOT_SUPPLIED',))
    n = len(values)
    if n > expected_count:
        raise EmpiricalTenthError('UNEXPECTED_EXTRA_OBSERVATIONS')
    if any(value is not None and type(value) is not float for value in values):
        raise EmpiricalTenthError('BINARY64_REQUIRED')
    reasons = []
    if n < expected_count:
        reasons.append('COUNT_SHORT')
    if n == 0:
        reasons.append('EMPTY_WINDOW')
    if any(value is None for value in values):
        reasons.append('MISSING_VALUE')
    if any(value is not None and not math.isfinite(value) for value in values):
        reasons.append('NONFINITE_VALUE')
    if reasons:
        return EmpiricalTenthResult('WINDOW_UNAVAILABLE', None, None, n,
                                    expected_count, tuple(sorted(reasons)))
    k = (n+9)//10
    q = sorted(values)[k-1]
    return EmpiricalTenthResult('STATISTIC_DEFINED', 0.0 if q == 0.0 else q,
                                k, n, expected_count, ())
