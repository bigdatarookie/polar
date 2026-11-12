# Witnessed temporal inverse-volatility ingredient

`polar.scheduled_temporal.estimate_temporal(prices_micro, labels, *, kind,
source_ref=None)` is a pure single-instrument ingredient. `ROLLING_60` requires61
positive integer-microprice closes; `STATIC_CALIBRATION` requires1259. The caller
binds the fixed calibration interval, consecutive eligible reference-calendar
labels, instrument, source operand member IDs/pins and pre-test cutoffs. This
helper checks exact lengths, strictly ordered ISO dates and positive integer
values; it does not discover source rights, missing exchange sessions or clocks.
It performs no source reads, account execution, fits, optimization or publication.

After the caller's durable original start, each call converts exact padded6dp
price tokens directly to binary64, computes chronological simple returns and
`math.fsum` mean, chronological centered-square sum divided n-1, then
`math.sqrt(252.0*variance)`. Every stage must be finite; zero/nonpositive variance
is INVALID, never cash/full exposure fallback. Raw exposure is
`min(1.0,0.10/sigma)`. The binary64 result becomes an exact
`Fraction.from_float`; floor at10^12 gives the final rational weight and residual
cash, with no Decimal-repr quantizer or renormalization.

The return is `{'weight': Fraction, 'witness': JSON-safe dictionary}`. Witnesses
retain the provided source metadata/labels, operand hash, represented prices,
returns, reduction scalars, variance/sigma/raw exposure, exact binary fraction,
floored target/cash and a canonical-LF SHA256. `actual_counts` records one
estimator call, calibration/rolling category and successful completion. A
`TemporalEstimationError` retains `.witness` and `.events`, including partial
stages/counters. A complete study's one calibration plus47 rolling calls means48
estimator calls, not ML training or optimization. The root Service owns that
budget, first-start persistence, cache-once BASE/stress reuse and immutable
success/failure evidence; this ingredient never grants an original or retry.

`verify_temporal_witness(witness)` verifies saved envelope/hash, fixed definition,
counts, date/vector domains, scalar algebraic links and exact raw-to-floor/cash
identities. It reports zero estimator/policy/source/native/write calls. It does
**not** recalculate prices-to-returns, either `fsum`, centered observations,
square root or exposure policy. The witnessed reductions remain attributed
original evidence: this integrity/identity validator does not independently
recertify a newly rehashed mean/variance/volatility calculation. Immutable store
hashes and independent invented qualification establish that original path;
relabeling estimator replay as saved verification would violate the interface.
The integration must bind witnesses and resulting saved TARGET instructions,
actual calibration/rolling counts and shared scenario plans without invoking
this estimator again.

Invented-only unit controls live in `tests/test_scheduled_temporal.py`. Official
qualification uses `scripts/ci.sh --test tests/test_scheduled_temporal.py
--reports EMPTY_DIRECTORY`. These controls do not use retained quotes or grant
technical independence, financial support, source certification or run authority.

## Shared service profile and operational boundary

`polar.scheduled-reference-profile/6` uses closed policy TEMPORAL_VOLATILITY,
lookback60, annual_cap0.10 and an exact calibration start/end pair resolving to
1259 consecutive existing source dates (1258 returns). One selected symbol may
reuse a full multiasset input manifest without a new projection; other profiles
retain exact symbol-list equality. The four generic leg rules are TEMPORAL_VOL,
STATIC_VOL, FULL and CASH, all scale1. Primary strategy is temporal, benchmark
static. The existing monthly calendar, next NY-midnight K/+1sec D, shared exact
reference allocator and terminal EXIT are reused.

The same plan is executed in fresh BASE100c+10bps and STRESS200c+20bps accounts.
One calibration and N monthly estimates are cached once, with no per-cost
re-estimation. The original finish and failure retain actual estimator counters;
invalid numerical estimates stop the started family with scientific_status
INVALID, no refund. Preflight is metadata/schedule-only with expected estimator
counts. Retained authority explicitly binds allowed_estimator_calls=N+1 and
allowed_optimizer_calls=0 alongside existing native-account/source/runtime/method
bindings. No source numeric read or estimator occurs before durable first start.

Stored-only reproduction verifies original witness envelopes, source operand
hashes, calibration/rolling date cutoffs and exact instruction weights; it never
calls the estimator or native service. Saved BASE-only bootstrap uses exactly
three non-cash legs, seed37003, paired circular63 blocks and1000 draws. Typed
TEMPORAL_DESCRIPTIVE quantiles use ceil(p*m)-1 for2.5/50/97.5%, retaining valid and
invalid counts without redraw. Original profiles retain their existing quantile
recipe. Even complete temporal resampling always has robustness
INSUFFICIENT_EVIDENCE. The temporal drawdown recipe binds the latest equal
running peak before the first maximum trough; legacy earliest-high behavior is
unchanged. Shared public metrics/limitations carry the frozen comparison and
estimation counts; no per-strategy renderer or financial verdict is introduced.
