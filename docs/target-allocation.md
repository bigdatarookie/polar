# Pure target allocation

`polar.allocation.allocate(snapshot, *, max_names)` computes whole-share target
quantities from caller-supplied marks. It reads no market data, wall clock, files,
database or service settings. It adds no CLI/API, orders, strategy, risk controller
or runtime integration. Its result is labeled `ZERO_COST_ALLOCATION_ARITHMETIC`
with `financial_verdict="NOT_RUN"`.

```python
from datetime import datetime, timezone
from decimal import Decimal as D
from polar.allocation import Mark, Position, Snapshot, Target, allocate

at = datetime(2026, 11, 6, 19, tzinfo=timezone.utc)
result = allocate(Snapshot(
    cash=D("100"), currency="USD", as_of=at,
    positions=(Position("A", 2), Position("C", 4)),
    targets=(Target("A", D("0.5")), Target("B", D("0.4"))),
    marks=(Mark("A", D("30"), "USD", at),
           Mark("B", D("70"), "USD", at), Mark("C", D("5"), "USD", at)),
), max_names=3)
# marked_nav=180; sorted desired A=3/B=1/C=0; deltas +1/+1/-4;
# allocated_value=160; residual_cash=20; total_target_weight=0.9.
```

`Position`, `Target`, `Mark`, `Snapshot`, `AllocationRow` and `Allocation` are
frozen dataclasses. Snapshot collections must be tuples; result rows are a tuple
ordered by stable instrument ID. No input coercion or mutation occurs. Dataclass
construction itself does not validate; `allocate` validates before calculation.
The result carries currency/as_of, marked NAV, total target weight, allocated
value, residual cash, and rows containing instrument_id/current_quantity/
target_weight/mark/desired_quantity/delta. Money is in declared currency, marks
in currency/share, quantities and deltas in whole shares, weights dimensionless.

For each held/targeted name:

- NAV = cash + sum(current quantity × mark).
- Desired quantity = floor(NAV × target weight / mark); absent targets use zero.
- Delta = desired quantity − current quantity; absent holdings use zero.
- Allocated value = sum(desired quantity × mark); residual cash = NAV − allocated.

Weights sum to at most one without renormalization. Residual cash includes both
unallocated weight and whole-share rounding. Nonnegative inputs imply residual
cash is nonnegative. All-cash/empty targets exit existing holdings at supplied
marks for this arithmetic; zero NAV returns zero desired quantities/residual.
Zero quantity/weight rows still require marks. No quantities are netted away.

The caller must supply `max_names`, an actual integer in 1..1000. Each collection
and their union obey this bound. IDs match ASCII
`[A-Za-z0-9][A-Za-z0-9._:-]{0,63}` with no stripping or ticker inference; duplicates
within each collection reject. Marks must cover exactly the union of position
and target IDs: missing and unused marks reject. Overlap across collections
identifies the same instrument.

Cash/marks/weights must be `Decimal`, finite, absolute value at most 10^12,
exponent at least −12, and rendered decimal length at most 40, matching existing
decimal input limits. Cash and weights are nonnegative; marks strictly positive.
Holdings must be actual Python integers in 0..10^12; bool/float/Decimal holdings
reject. Desired quantities and derived monetary totals may exceed the input
bounds and are never clipped. Bounded products/sums use a private precision-100
context with rounding/inexact traps; Decimal integer quotient implements the
nonnegative floor directly. Caller context/flags remain unchanged. Extreme
positive exponents on numerical zeros are handled internally as exact zero;
the caller's Decimal representation remains unchanged.

Currency is one explicit uppercase ASCII three-letter code; every mark must
match. Every timestamp must be UTC-aware with zero offset; mark as_of must equal
snapshot as_of exactly. Both earlier and later mark times reject. This records
the caller's single snapshot assertion; it does not establish freshness,
historical availability, FX conversion or live executability.

Invalid inputs raise `AllocationError` with `.code` and `str(error)` equal to a
stable code, without caller values: `INVALID_NAME_LIMIT`, `INVALID_SNAPSHOT`,
`INVALID_CURRENCY`, `UTC_REQUIRED`, `DECIMAL_REQUIRED`, `DECIMAL_OUT_OF_BOUNDS`,
`NEGATIVE_CASH`, `IMMUTABLE_TUPLE_REQUIRED`, `NAME_LIMIT`, `INVALID_ROW_TYPE`,
`INVALID_INSTRUMENT_ID`, `DUPLICATE_POSITION`, `DUPLICATE_TARGET`, `DUPLICATE_MARK`,
`MISSING_MARK`, `UNEXPECTED_MARK`, `INVALID_POSITION_QUANTITY`, `NEGATIVE_WEIGHT`,
`NONPOSITIVE_MARK`, `CURRENCY_MISMATCH`, `MARK_SNAPSHOT_MISMATCH`,
`WEIGHT_SUM_EXCEEDS_ONE` or `ARITHMETIC_BOUND`. With several invalid fields,
the first validation failure is reported; error precedence is not an interface
guarantee. No invalid input is repaired.

This is zero-cost target arithmetic. Fees, spreads, sale/buy sequencing, fills,
liquidity, actual affordability, FX, risk scaling and empirical/financial verdicts
belong to later separately qualified components. Accepted engine/config/schema/
API/CLI/service behavior remains unchanged. QA System is N/A for this isolated
pure function; independent code/formula review and Lead acceptance still apply.
