# OBS158 shared preflight, conversion and account-math boundary

This is Part A of the fixed `OBS158_PRICE_LEDGER_20190830_20200831_V1`
implementation. It does not implement or authorize a strategy/native run.
The old three-name Gym profile and spent families remain separate.

`load_obs158_inputs(config)` accepts `polar.obs158-input-config/1` with
`public_ref` and `metric_ref` (`path`, `sha256`, optional `bytes`). It binds
public packet716fd279, its four immutable members, metric binding5ec3128a,
qualification630c2ea0 and source revisionrawpv-d362. The qualification directory
is not the raw directory: exact normalized manifest/member identities come from
the pinned inspection's absolute-path source map. The reader checks the transitive
source hashes, normalized members, raw array tokens and reused corpus-line join.
Inputs are frozen byte tuples, not mutable admitted dictionaries. Actual file paths
and physical receipts remain outside numerical result identities.

`preflight_obs158(inputs, converted=None)` is the shared callable for DE and the
immediate runner. It checks the fixed158x253 unique grid, exact aliases/lexical
routing order, unchanged raw basis, positive OHLC/whole nonnegative volume,
lossless4dp opens/6dp closes, preserved null source clocks and two-session
estimatedK, aggregation dates,960zero-volume flags and42excluded source statuses.
It does not silently repair/drop an alias, date, duplicate or invalid source row.
Graph-hash checks and semantic source-pointer assertions are distinct.

`convert_obs158(inputs)` returns `polar.obs158-converted/1` with separately named
`executor_quotes`, `private_close_marks`, `eligible_bars`, `unit_events`,
`barriers`, `sample_grid`, `decisions` and `route_slots`. Only delayed eligible
bars belong in a strategy's observation channel. Source tokens are preserved;
integer micro-USD prices are separate exact representations. All158quotes at Q
precede QUOTES_COMPLETE atQ+1ns; routing slots startQ+100ns for sells andQ+1000ns
for buys in lexical order, with acknowledgment required before the next order.
All158private close marks share C in fixed order; MARKS_COMPLETE isC+1ns and
sampling remainsC+100ns. Actual native ordering/ack equivalence is NOT RUN.

There are13instructions, including the outside-window final instruction retained
as NOT_EXECUTED_OUTSIDE_PROFILE. All253samples/252intervals remain, with three
initial cash-only closes, no compulsory liquidation and final report knowledge
at the frozen delayedK. Split events are forward-only/exactly-once model events;
dividends are excluded and other factor1 units are an unverified assumption.

`obs158_math` supplies pure exact integer/rational primitives:

- `microprice`: lossless literal decimal to micro-USD; no float or rounding.
- `cent_round_micro`: signed HALF_EVEN after quantity multiplication.
- `settled_fill`: greatest affordable intended/depth-capped whole buy quantity,
  sell holdings/fee checks, no zero-order fee, exact and settled notionals,
  epsilon, side-signed cash residual and explicit unrouted reasons.
- `marked_account`: separate cent rounding for each physical position; zero
  holdings need no mark, required missing held marks fail explicitly.
- `snapshot_targets`: exact floor of own snapshotV/(158*rawclose).
- `forward_unit`: exact physical/native forward-unit and cent-position identity.

Prospective literal tests are source only, NOT RUN by the author. The source
assignment grants no component/native/model/strategy/evaluator/retained operation.
Independent QA assigns finite affected controls before invocation, including the
158quote/mark barriers, K/D/Q leakage, raw6dp/cent ties, source joins, split-once
units and complete output behavior. No private oracle was consulted.

The report always returns `runner_execution_allowed: false` in Part A.
Native cent/unit equivalence, independent controls, full runner output schema and
actual runtime binding are explicit NOT_RUN required checks. Part B must implement
those boundaries using the qualified Nautilus seam or return a precise unsupported
function/version/use. It must not infer native Money equivalence, copy old profile
constants or create a second simulator. The final evaluator/file/field/order/ID
projection is still unimplemented and must freeze before comparisons.

Financial scope stays INSUFFICIENT_EVIDENCE with
PRICE_ONLY_PARTIAL_ACTION_EXECUTION_MODEL. Structural/math/source/native/runtime/
reproduction evidence remain distinct. This is not a full PIT, action, currency,
identity, actual execution, capacity, total-return or original-HYP result.
