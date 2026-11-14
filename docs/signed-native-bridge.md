# Exact-cent signed native/core component

`polar.signed_native_bridge` reuses Nautilus1.231.0 and the accepted signed account
core. It is an execution/account boundary, not a strategy, scheduler, Service
profile, retained runner, public result format or broker-credit claim. No engine,
account or source is constructed on module import. `native_types()` returns the
pinned cent Equity/Money types and an `ExactCentMarginAccount` subclass to register
through the existing `AccountFactory` before native account creation.

## Two authorities, one exact reconciliation

Native actual orders, fill IDs, quantities, prices, positions and commissions are
execution authority. `signed_account_core` is research-policy admission and
physical F/R/C/U accounting authority. Native margin cash is realized trading PnL
less actual fees plus initial cash; it is never physical free cash F or escrow R.
The ordinary native equity instrument has zero margin requirements: keeping native
risk active is not sufficient research funding/locate admission.

The stock MarginAccount PnL path consumes f64 average prices and the native stock
Position/Portfolio valuation API is explicitly NOT_SUPPORTED as an exact-cent
oracle. An actual invented BUY1@10.000000 -> SELL1@10.005000 with two1c fees gives
stock native99999c versus core99998c from initial100000c. This is a demonstrated
stock-path mismatch, not a claim that every float error has that exclusive cause.
Neither prices, precision nor fees were changed to obtain the exact result.

The subclass consumes original native exact decimal fill tokens, whole quantities
and commissions. Each fill's notional is settled once with the accepted core's
HALF_EVEN cent primitive. Its signed remaining opening-principal basis is updated
from actual fills, not native avg_px_open. Partial close releases a proportional
HALF_EVEN share of remaining settled basis; full close releases the entire residual
basis exactly. Remaining unrealized cents are round(signed quantity*current exact
mark)-signed remaining basis. Thus exact trading equity equals native realized-PnL
cash plus exact unrealized cents; no fee/principal is credited twice. Basis
allocation only partitions realized/unrealized PnL and does not alter core cash
flows, prices or order fees. The caller must supply original source-bound marks.

`account.exact_marked_trading_equity({instrument_id:Fraction_price})` is the exact
adapter API; stock Position.unrealized_pnl/Portfolio marks are unsupported exact
alternatives. The actual native cash balance must independently equal initial+
account exact-realized-actual-commission cents. Native/account/core signed positions
must match. Stock native position quantities remain authoritative throughout.

## Bridge contract and serial gateway

Construct `SignedNativeBridge(flat_core_state, {source_name:native_instrument_id},
submit_order, native_positions_callable, exact_account_callable, initial_cents=...)`.
Only empty initial positions/claims/accruals/escrow and matching initial cash are
supported. `native_positions_callable` returns original source names and exact
signed whole quantities. The production integration must expose no alternate
submission path: this component supplies one gateway, not a claim that arbitrary
external Strategy code cannot bypass Python callbacks.

- `propose_and_submit(intent_id,native_order,exact_price,fee_cents,marks,...)` reads
  actual native order instrument/side/quantity/ID, invokes core `propose_fill` and
  records consumed admission operands. A rejected proposal submits0orders and
  installs no proposed state. A unique intent/order is consumed even on rejection;
  retry requires a separately meaningful caller decision, not implicit recycling.
  The sole submit call site saves pending state before possible synchronous native
  callbacks. Any unresolved order blocks every other submission across names, so
  pending proposals cannot double-spend cash/escrow/locate. This chooses serialization
  rather than speculative reservation accounting. A throwing submit is UNKNOWN
  effect, retained and halted; it is not evidence of no fill.
- `record_fill(actual_native_event,marks)` consumes order/trade IDs exactly once,
  installs only core `record_confirmed_fill` results, and reconciles actual native
  and core positions, PnL/fee cash and equity with exact zero residual. Partial fills
  update actual state and leave remaining order pending. No proposal.after becomes
  a physical fill. Duplicate callbacks are rejected/retained without a second fee
  or state mutation. Unexpected fill/unsupported crossing/raw input/error is saved
  as NON_RECONCILED_EXECUTION and halts further submissions, never erased or resized.
  A known actual economic breach remains a confirmed execution breach and halts;
  true fills do not disappear because research admission would have rejected them.
- `record_terminal(order_id,status)` finalizes FILLED/CANCELLED/REJECTED/DENIED/EXPIRED
  against the exact pending order. FILLED requires the full callback quantity census.
  Cancellation after partial fill releases only pending instructions; it never
  unwinds actual positions/fees. Closing to zero and opening the opposite side must
  be separate orders with separate genuine fees. Combined discretionary reversal
  remains core-rejected. The account can retain an unexpected physical crossing's
  trading data, but the bridge does not qualify it as reconciled execution.
- `apply_external(core_transition,marks)` accepts a supplied matching-before-state
  core collateral/claim/accrual recognition or settlement transition only when no
  order is pending. It accumulates the same-mark equity recognition delta exactly
  once as the external adjustment. Settlement and escrow moves are NAV-neutral;
  receivable/payable/income/expense recognition changes this adjustment. The adapter
  does not modify native cash or simulate native fees for these nonnative claims.
  Core cumulative exact/recognized/settled origins and NO_CREDIT/explicit identified
  hypothetical mandatory-funding semantics remain unchanged. Matching typed input
  is correspondence, not proof of source entitlement or actual broker funding.
- `reconcile(marks)` saves compact core operands, native trading cash/PnL/fees,
  external adjustment and residual. Core NAV must equal exact native trading equity
  plus that single cumulative external adjustment, with no tolerance. Any identity,
  position, cash or equity mismatch halts and retains the inputs/error. A sticky
  model-survival-failed flag remains after nonpositive model NAV; it is not observed
  fair-value insolvency and blocks later discretionary submissions. Explicit forced
  mandatory paths still use the core contract. No stop/liquidation or scheduler is
  fabricated here. Pre-ex stale cum marks/claim age/DNAV/targets remain a later
  scheduler/report witness duty; this component does not silently offset claims.

`events` is a component trace with exact Fraction operands, actual fill tokens and
reconciliation rows. It is not a qualified private replay/result wire format or
production HistoryStore. Later consumers must define bounded serialization and
manifest checks rather than treating Python objects as authenticated saved results.

## Qualification boundaries

Invented controls exercise the actual product subclass/gateway on pinned native
accounts: odd-cent/six-decimal long/short profit/loss, partial and full cover basis,
close-then-open both directions, fees once, actual one-unit partial fill followed
by cancellation, rejected funding/NO_CREDIT sale fee with no submit, pending serial
barrier, duplicate callback refusal, deliberate physical bypass/crossing retained
as nonreconciled, and external C/U recognition/payment/accrual/escrow/default.
Intentional fault injection bypasses the test gateway only to prove it preserves
unexpected actual fills; this is not an allowed production submission path.

No retained quote/action/rate/portfolio payload, provider call, research allocation,
48-account runner, Service/public publication, UI/serving change or full-strategy
readiness follows. Independent affected source/current CI review, normal integration
and accepted callable/runtime handback are still required before consumer adoption.
