# Pure supplied-fill accounting

`polar.supplied_fills.apply_supplied_fills(snapshot, fills, cutoff, *, max_names,
max_events)` applies explicitly supplied executed fills to cash and positions.
It performs no execution simulation, allocation integration, I/O, clock read,
service submission, corporate-action inference, FX, cost basis, NAV or performance.
The immutable result is labeled `SUPPLIED_FILL_ACCOUNTING`, financial verdict
`NOT_RUN`. Caller prices/fees are observations, not qualified broker executions.

```python
from datetime import datetime, timezone
from decimal import Decimal as D
from polar.supplied_fills import LedgerSnapshot, SuppliedFill, apply_supplied_fills

at = datetime(2026, 11, 7, 5, tzinfo=timezone.utc)
snapshot = LedgerSnapshot(D('100'), 'USD', at, (), ())
fills = (
    SuppliedFill('buy-A', 'A', 2, D('10'), D('1'), 'USD', at, at, 1),
    SuppliedFill('sell-A', 'A', -1, D('12'), D('1'), 'USD', at, at, 2),
    SuppliedFill('buy-B', 'B', 1, D('20'), D('0'), 'USD', at, at, 3),
)
result = apply_supplied_fills(snapshot, fills, at, max_names=2, max_events=3)
# Cash receipts:100 ->79 ->90 ->70; A1/B1; exact total fees2.
```

Snapshot positions use public frozen `polar.allocation.Position`. Snapshot/fill/
receipt/result records are frozen dataclasses; collections must be tuples.
`LedgerSnapshot` contains cash, currency, as_of, positions, applied_fill_ids.
Each receipt retains all supplied fill fields and cash_before/cash_after plus
position_before/position_after for that instrument. Final positions sort by ID,
including zero positions. Historical fill IDs retain their order and new IDs are
appended in supplied sequence; IDs are never truncated. Receipts and total fees
describe the new batch; the snapshot retains the complete bounded ID history.
Constructors do not
validate: the callable validates every external snapshot, including empty calls.

For each fill, cash_after = cash_before − quantity × price − fee, and
position_after = position_before + quantity. A negative cash or position at any
step aborts the entire batch with `LedgerError(code)` and no partial result or
mutation. No bad fill is skipped or sales reordered to fund earlier buys. Duplicate
fill IDs within history, batch or across them reject; replay is an error, not an
idempotent-success response. Empty batches produce no receipts and fees0.

Inputs match accepted allocation bounds: actual integer quantities/limits only
(no bool, float or Decimal coercion); initial position0..10^12, nonzero signed
fill quantity with absolute value<=10^12. Cash/price/fee are finite Decimal with
absolute value<=10^12, exponent>=−12 and rendered length<=40. Cash/fees must be
nonnegative and price positive. IDs match ASCII `[A-Za-z0-9][A-Za-z0-9._:-]{0,63}`,
no stripping. Currency is an explicit uppercase ASCII three-letter label matching
all fills, not external ISO/FX validation. Caller name/event limits are required
actual integers1..1000. Names cover initial positions plus new fill instruments;
events cover retained IDs plus new fills, not just this batch.

Sequence is a strictly increasing supplied integer0..10^12 within each batch,
with gaps allowed; it is not a global event identity across calls. Fill IDs
provide replay rejection across the retained history. Within a batch,
execution times are nondecreasing in that order. All timestamps must be UTC-aware
with zero offset. Inclusive constraints: initial as_of<=execution<=receipt<=cutoff
and cutoff>=initial as_of. Receipt times may be nonmonotonic across events; they
do not reorder economics. Final nonempty as_of=max(initial as_of, all receipts);
empty calls preserve initial as_of. Cutoff alone never advances state. This clock
means accounting after the supplied batch was received, not complete arrival,
settlement/funding finality, market availability or absence of unknown executions.
Later retroactive executions reject rather than being backfilled.

Bounded arithmetic uses a private precision100 context with rounding/inexact
traps; caller context/flags and inputs remain unchanged. Derived cash, positions
and total fees are exact and unclipped. These outputs can exceed external input
bounds: selling10^12 shares at10^12 with fee0 returns cash10^24. Resubmitting such
a snapshot rejects the same input cap, even with an empty batch. There is no
unconditional closure/infinite-history/capital-capacity promise. Numerical zero
may be represented canonically internally without mutating its source Decimal.

Stable errors: `INVALID_LIMIT`, `INVALID_SNAPSHOT`, `IMMUTABLE_TUPLE_REQUIRED`,
`INVALID_CURRENCY`, `UTC_REQUIRED`, `CUTOFF_BEFORE_SNAPSHOT`, `DECIMAL_REQUIRED`,
`DECIMAL_OUT_OF_BOUNDS`, `NEGATIVE_CASH`, `NAME_LIMIT`, `EVENT_LIMIT`,
`INVALID_POSITION`, `INVALID_ID`, `DUPLICATE_POSITION`, `INVALID_POSITION_QUANTITY`,
`DUPLICATE_FILL_ID`, `INVALID_FILL`, `INVALID_FILL_QUANTITY`, `NONPOSITIVE_PRICE`,
`NEGATIVE_FEE`, `CURRENCY_MISMATCH`, `INVALID_FILL_TIME`, `INVALID_SEQUENCE`,
`UNORDERED_FILLS`, `INSUFFICIENT_CASH`, `INSUFFICIENT_POSITION`, `ARITHMETIC_BOUND`.
Only the code appears in `.code`/`str(error)`; no payload/partial accounting. With
multiple invalid fields, diagnostic precedence is not a promised interface.

Accepted allocation/engine/RunConfig/API/UI/schema/jobs remain unchanged. QA System
is N/A while this component is pure and nonpersistent; independent Code/Validator
and a non-author Lead accounting witness own acceptance. Literal accounting is
not empirical execution quality, financial performance or investment evidence.
