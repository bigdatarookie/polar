# Pure signed raw-share account core

`polar.signed_account_core` provides pure, immutable account transitions for the
selected v043 signed-account seam. It is not a backtester, broker adapter, native
account configuration, strategy, Service admission, data reader or public result
schema. No files, clocks, provider, engine or storage are accessed. Inputs and
provenance are caller-supplied, not proof of a real market or funding facility.

## Representation

`State(free_cents, positions=(), escrow=(), claims=(), accruals=(), used_ids=())`
uses exact Python integers for signed free settled cash and signed whole shares;
per-name escrow amounts are nonnegative integer cents. Collections are immutable
tuples of unique names or typed frozen objects, not dictionaries retained from
callers. NAV = F + sum escrow + sum HALF_EVEN(q*raw_USD_price*100) + C - U.
There is no duplicate financing-principal debt: F<0 already records debit cash.
Restricted cash is included once, not collateral expense or an extra asset.
Receivables are NAV assets, not free purchasing power.

Prices, nominal distributions and rates accept only `Fraction` or exact integer
inputs, never binary floats/Decimal or implicit source lexemes. Prices are >0,
nominal/rate magnitudes >=0. `amount_cents` reuses the existing signed
`distribution_claims.half_even` primitive. Each marked position is rounded once.
`magnitude_target` floors absolute signed notional/price toward zero; it does not
floor a negative number away from zero. Scalar domains and duplicate/type checks
reject booleans and malformed inputs; no price or economic criterion is inferred.

`Transition` contains exact before/after immutable state, event ID, kind, copied
consumed operands and status. Applied IDs enter used_ids; duplicate IDs reject.
Rejected proposals return the identical original state and failed-test operands,
without consuming an executed-event ID. This is not a physical execution verdict.
The evidence contains Fractions/typed objects: it is a Python pure-core API,
not yet a qualified persisted JSON/private result wire or saved verifier.

## Proposed admission versus confirmed execution

`propose_fill(state, fill_id, name, side, quantity, price, fee_cents, *,
forced=False, located_cap=None, locate_provenance=None, funding_mode='NO_CREDIT',
funding_assumption=None, marks=None)` admits or blocks a proposed permitted fill.
Quantity denotes the supplied proposed quantity, not an automatically filled
request. No fill is manufactured. Fee is an explicitly supplied positive-
magnitude charge, zero for zero quantity. No fee schedule is chosen here.

- Long purchase decreases F by settled notional plus fee; sale increases F by
  notional minus fee. Every discretionary long increase needs full marks and
  F>=0, all per-name exact initial restrictions, and initial equity admission.
  C/U and charges remain in NAV. Positive F alone cannot override a payable.
- Short increase requires a located quantity cap/provenance, credits actual sale
  proceeds to that name's escrow, then transfers the minimum whole own cents to
  reach CEILING(1.5*post-fill marked short liability cents), not HE(half-fill
  proceeds). Fill and mark prices can differ. Existing excess escrow is not
  released. Every proposed risk increase checks full marked long assets +
  half marked short liability as a distinct exact initial equity requirement.
  A 113-cent liability requires 170 cents escrow (57 own cents at equal fill).
- Cover releases HE(escrow*actual proposed covered/short magnitude); full cover
  releases the remaining escrow exactly. Unfilled quantity releases nothing.
  No other name's escrow is touched. Default NO_CREDIT blocks a cash-insufficient
  cover atomically. Only forced cover plus explicit
  HYPOTHETICAL_MANDATORY_FUNDING and a nonempty assumption identity can admit a
  modeled debit. Status/evidence never promises broker credit or execution.
- Reversals crossing zero must be split by the caller into close/new-open events
  with separate IDs and an explicitly selected fee allocation. This atom does
  not invent that order-level rule. Missing required confirmed data or such an
  unsupported combined reversal raises an error; caller must preserve original
  input/error rather than claiming a reconciled financial result.

`record_confirmed_fill(state, fill_id, name, side, quantity, price, fee_cents,
marks, *, execution_provenance, located_cap=None, locate_provenance=None,
funding_mode='NO_CREDIT', funding_assumption=None)` is a distinct assertion path
for a supplied confirmed execution. It retains true quantity/cash/fees/positions
and adverse breaches, never hides an execution by rejecting admission. For an
underfunded confirmed short, proceeds enter escrow and own collateral transfer
is limited to actually available cash after fees. Missing locate, restriction,
equity or funding qualification is reported as breach. Confirmed cover can
produce signed debit; absent explicit prior funding qualification it is labeled
UNQUALIFIED_EXECUTION_FUNDING. No future credit/fill authority follows. Required
units/IDs/marks must still be valid; this is not a source authenticator.

`top_up(state, event_id, name, requested_cents)` moves at most max(F,0) to that
short name's escrow and reports unmet requested cents. It is NAV-neutral. It does
not create a new asset, debit facility, automatic transfer response or liquidation.

## Distribution claims and cumulative accrual

`recognize_distribution(state, event_id, name, nominal_usd, ex_date,
payment_date, source_ref, currency='USD')` snapshots supplied pre-entitlement
holdings. Long creates receivable C; short creates modeled nominal manufactured
payable U, rounded once per event/name/account with rational residual. Caller
binds event order, exact source action/calendar and actual ex-entitlement state.
Missing/non-USD terms reject, not zero substitution. Sale/cover preserves a claim.
No withholding, split/fractional/cash-in-lieu or loan-contract rule is inferred.
Splits and such missing rules remain explicitly unsupported outside this API.

`pay_claim(state, event_id, claim_id, at_date, *, funding_mode='NO_CREDIT',
funding_assumption=None)` clears the existing cent claim exactly, no earlier
than its supplied payment date. A cash-insufficient payable returns
SETTLEMENT_BLOCKED_INSUFFICIENT_FREE_CASH, unchanged state/unpaid obligation,
with no partial payment or escrow raid. Explicit hypothetical mandatory funding
with identity can settle to negative F, preserving shortfall and negative-F delta.
Payment is NAV-neutral; it is not a second expense/income. Terminal flat holdings
can coexist with unsettled claims; no writeoff or extended runoff is generated.

`accrue(state, event_id, component, start_base_cents, annual_rate,
elapsed_seconds, provenance, *, stream_id, base_kind)` accepts caller-bound
previous-event base and exact civil seconds/(365*86400), not a day scheduler.
BORROW uses MARKED_SHORT_NOTIONAL; DEBIT_INTEREST uses NEGATIVE_FREE_CASH;
REBATE uses DECLARED_REBATE_BASE; FREE_CASH_INTEREST uses POSITIVE_FREE_CASH.
Cash bases must match the supplied state's cash domain. Caller must bind the
appropriate prior event state, interval and source/scenario identity; this core
does not authenticate nonoverlap, a historical rate or borrower terms. Short
rebate is not silently based on escrow. Expense streams add U; income streams
add C. Component direction supplies the sign; negative-rate conventions reject.

Each `Accrual` retains stable stream ID/component/base-kind/provenance, cumulative
exact cents, cumulative HE recognized cents and cumulative settled cents.
Recognition delta is new rounded cumulative minus previous rounded cumulative.
Rate changes may continue within a bound stream; contract/type/base identity
changes require a new stream, never a silent reset. Components/streams do not
net rounding residuals. `settle_accrual(state, event_id, stream_id, ...)` uses the
same explicit NO_CREDIT/hypothetical funding contract as claim payment and never
resets the cumulative exact or recognized origin. Income recognition raises NAV;
settlement only moves C to F. Expense recognition lowers NAV; settlement only
moves U to paid cash.

## Mark/default boundary

`mark(state, prices)` returns exact equity/deficit, separate rational per-name
initial/maintenance restriction requirements/excess, full-long+half-short initial
equity admission, .25*long+.30*short maintenance equity, and cash shortfall.
Requirements are tests and are never subtracted from NAV. E<=0 is a valid DEFAULT
state with deficit max(-E,0), retained cash/positions/obligations and failed
survival. Positive-NAV log/CAGR/Sharpe/exposure ratios are INAPPLICABLE, not clipped
or computed. Dollar equity/deficit stays available. No automatic liquidation or
financial verdict is produced.

## Qualification scope

Owner base28020110, append-only opening/settlement correctionfee54dd6 and
transition/income clarification control this atom. Existing Validator32 literals
were read as prior evidence, not replayed or claimed as implementation tests;
new invented implementation controls test the actual selected core. Official
scripts/ci.sh also runs its separate invented native baseline/runtime/Node checks;
these are technical controls, not a retained strategy/native scenario. Independent
review/current exact CI/normal integration remain necessary before adoption.
Native signed execution correspondence, strategy scheduling, full action input,
funding scenario limits, private save/replay wire and financial methodology are
separate concrete seams. This API grants no retained run, publication or UI action.
