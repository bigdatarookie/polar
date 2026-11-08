# Pure lower empirical tenth

Import lower_empirical_tenth, EmpiricalTenthResult and EmpiricalTenthError from
polar.empirical_tenth. The function has no IO or external statistics dependency:

    lower_empirical_tenth(values, *, expected_count, max_rows)

values is an exact tuple of already represented built-in binary64 float or None
positions; whole values=None means no supplied window. expected_count and max_rows
are explicit positive built-in ints (bool/subclasses reject); there are no
scientific W or technical-limit defaults. Caller qualification of source/window,
consecutive grid, maturity/vintage and precision conversion remains separate.

The validation order is fixed:

1. Invalid max_rows raises INVALID_MAX_ROWS; then invalid expected_count raises
   INVALID_EXPECTED_COUNT; then wrong values shape raises IMMUTABLE_TUPLE_REQUIRED.
   Arbitrary iterables/generators/scalars are never consumed or converted.
2. expected_count or tuple length above max_rows raises CALL_DOMAIN_EXCEEDED.
   Within domain, None returns unavailable/WINDOW_NOT_SUPPLIED.
3. Tuple length above expected_count raises UNEXPECTED_EXTRA_OBSERVATIONS.
   The function never chooses a subset or the last W.
4. Any slot other than exact float or None raises BINARY64_REQUIRED, before
   numerical unavailability. Bool/int/Decimal/string/subclasses do not convert.
5. Collect ALL applicable COUNT_SHORT, EMPTY_WINDOW, MISSING_VALUE,
   NONFINITE_VALUE, deduplicated/ASCII sorted. Any returns WINDOW_UNAVAILABLE.
   Empty tuple has COUNT_SHORT plus EMPTY_WINDOW. Counts include missing slots;
   no hole/nonfinite is discarded to salvage a smaller effective n.
6. Only complete finite input defines the statistic. n=expected_count,
   k=(n+9)//10 using integers, ascending copy-sort, selected elementk-1. No alpha
   float multiplication, interpolation, averaging, epsilon or weighting.
   Selected zero is canonical positive0.0; other selected float bits are retained.

EmpiricalTenthResult is frozen, with status, q, selected_rank, supplied_count,
required_count, reasons. Status is STATISTIC_DEFINED or WINDOW_UNAVAILABLE.
Unavailable q/rank are None; whole-None supplied_count is None, otherwise the
actual tuple length is retained. Defined selected_rank is one-based, both counts
equal expected_count and reasons(). Errors expose only stable .code/str(code),
never malformed caller values. A supplied observed zero is distinct from absence.

Synthetic explanatory controls: (0.0,1.0) selects0.0/rank1; ten observations with
one-0.10 and nine0 select-0.10/rank1 (the lower endpoint); eleven ordered0..10 select
1.0/rank2. Constant/tied values do not invoke interpolation. Input order and
signed-zero order cannot change output bits; input tuple is never changed.
Ambient Decimal context does not participate in the float/integer implementation.

STATISTIC_DEFINED is a mechanical statistic, not a forecast, calibration/solver
certificate, exposure/cash target or financial fitness. No scientific W, source
grid, precision conversion, operational fallback or trial setting is adopted.
Existing reporting ES95, mapper, allocator, model, Gym, source and Service/CLI
paths are unchanged. Independent exact-candidate Code qualification is separate
from author synthetic checks; no assembled runtime/System/Validator loop is needed.
