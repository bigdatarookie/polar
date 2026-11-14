# Event-native component and consumed witnesses

This is the source/invented bridge for the calendar-only five-path/six-clause
consumer, not the original prediction six-path question. It reuses the existing
Nautilus1.231 engine, `research_native_money` cent cash account, reference allocator,
fee/affordability primitives, immutable publisher and accepted pure controller.
It introduces no alternative backtester, market loader, Service profile, evaluator,
public report or scientific execution authority. All supplied reference prices are
synthetic vendor-adjusted reference-unit marks, never raw physical shares or a
price-scale100 substitution. The existing dictionary-based native profiles are
unchanged.

## Typed API

`polar.event_native.EventPlan` is an in-process component plan, not a new external
source/config loader. Fields are account_scope, input_id, calendar_id, protocol_id,
source, nav_closes, daily_decisions, events and required_anchors. An actual operation
must separately bind its own account scope and qualified source/clock identities;
receiving strings/prices is not proof of source rights, PIT or scientific authority.

`ReferenceClose(symbol,date,close_ns,available_ns,price_micro,source_id,role)` binds
an exact positive six-decimal reference price and its explicit eligibility clock.
Unknown availability remains ineligible. Roles are NAV, VTI_WARMUP_CANDIDATE and
BIL_UNUSED_WARMUP_CONTEXT. Source rows form one ordered BIL/VTI rectangle. Native
quotes/NAV/state/trades use only nav_closes; no warmup/context performance is emitted.
The actual question's916source dates/716NAV dates are distinct; the component also
accepts bounded invented frames for technical controls. It does not admit a smaller
retained study or change the frozen scientific window.

`DecisionPoint(D,Q)` supplies strictly future Q; `EventInstruction(Request,Q)` uses
the accepted controller's source event/expiry/reentry/clock-pin contract. This
adapter consumes already selected clocks, not a new calendar/availability model.
Required anchors must exist on the supplied NAV close grid; missing required prices
fail rather than being reconstructed or complete-case dropped. Events whose later
protection/reentry lies beyond the terminal grid remain explicitly censored and
cannot create a fictional completion. No old clock-only job is rerun here.

`simulate_event_component(plan,diagnostics=None)` runs the five genuine controls
CALENDAR_PROTECTION, FULL_VTI, STATIC_50, SMA200 and FULL_BIL under BASE(100c+10bps)
and FRESH_2X(200c+20bps), each in its own actual native account. It returns private
component evidence, not a financial result. `ci_research_native.simulate` dispatches
this exact typed plan to the component; old dictionary plans retain their existing
path. `_simulate_account` is an internal bounded technical-control seam; its optional
fill-model injection is used only to demonstrate native failure preservation.

`sma_vti_category(rows,D)` uses exactly the latest200 supplied completed eligible
VTI closes with known-by<=D and close<D. It returns NORMAL(VTI1) only when
200*last-sum>0, otherwise BIL1, including equality. It records all200 exact prices,
clocks and source IDs. The initial prefix includes Jan2 if eligible plus199 earlier;
200 pre-NAV rows cannot become a201-point signal. Missing prefix is UNAVAILABLE,
not defensive, stale or shortened. Native SMA emits TARGET initially/on valid
category change, unchanged HOLD; control completeness remains false after any
required unavailable observation. No dummy quarter sleeves are used.

## Causal native phases

All times are exact integer nanoseconds. The supplied Q remains canonical nominal
close time; the actual native callback timestamps and sequence numbers are recorded
separately. The following sub-close phases are reserved and checked for collisions:

| Phase | Actual time | Evidence |
| --- | --- | --- |
| Both native close quotes | Q and Q+1 | Exact cached price/timestamp/source correspondence |
| Pretrade mark and controller route barrier | Q+100 | Actual native cash/positions/rounded marks/NAV/fees |
| A decision whose canonical D equals Q | Q+150 | After the already-admissible route barrier, before fills |
| Lexical sells | Q+200, Q+201 | Separate alias callbacks after prior fill completion |
| Lexical buys | Q+300, Q+301 | Actual remaining cash and fee-aware clipping |
| Final route receipt | Q+400 | Closed symbol/order/fill census consumed by controller |
| Post-routing NAV | Q+1000 | Actual native cash/quantities and source-bound close marks |

Ordinary D callbacks use their supplied D. For D==Q the adapter processes the old
route barrier first, then the same-time observation for a later permissible Q. It
records canonical D and actual callback time separately; it does not borrow that
close's price or any fill as a D-state operand. Actual D sizing uses native cash and
held units with eligible earlier marks. Targets use the existing exact formula
floor(weight*V_cents*10000/P_micro). A future close can cap affordability, never
increase that frozen absolute target. Coalesced identical protection keeps the
original D/cash/marks/targets/sizing ID, with explicit replacement provenance; HOLD
never resizes or retries. New genuine desired transitions size at their own D.

Sells and buys use distinct per-alias native phases, as the existing adapter does.
Submitting both aliases inside one callback would reuse pre-fill cash and lose the
pre-order witness ordering. Every callback requires prior native completion before
reading cash/holdings for the next order. One effective intent per leg/Q is issued;
stable IDs bind caller account scope, leg/cost/input/calendar/protocol, generation,
original D/Q and cause. Actual native account/instrument IDs and fill IDs are also
saved, and joined to the logical context rather than inferred from ticker names.

FULL_VTI/FULL_BIL initialize then HOLD; STATIC_50 initializes half/half and targets
month-end, not daily drift. Its half vector uses the shared REDUCED destination
label as a control target, not an event protection request or a financial duration
verdict. No evaluator applies the calendar strategy's duration clause to controls
here. Terminal EXIT cancels outstanding future intent and liquidates through real
native fills or genuine zero-delta evaluation. It never marks a hypothetical
liquidation or completed reentry merely from a label.

## Actual anchors and route outcomes

Every supplied NAV close has a captured mark, including all required planned
anchors and HOLD/no-order closes. The mark is read after both actual native quote
updates and before any route/fee. The raw mark captures actual native cash and
reconciled long holdings, exact native prices/source IDs, cent position
values/NAV and cumulative actual flat/bps fees. The later actual route barrier is
linked to that already captured monetary snapshot; no D-NAV/posttrade NAV/fee-addback
reconstruction is used. Accepted Anchor validation consumes the emitted object.

Accepted RouteReceipt/SymbolEvaluation/TerminalOrder are built from both symbols'
actual evaluated deltas, original sizing references, routed/clipped quantities,
terminal native order IDs and unique fill IDs. Counters close to those records;
filled/native/side/account/instrument/price/fee joins are explicit. Omitted symbols
are not aggregate FILLED. A genuine all-zero desired delta can commit
ZERO_DELTA_NO_ORDER only with captured consumed sizing. A nonzero target whose
executable quantity is zero stays NO_FILL/unconfirmed; later HOLD cannot upgrade it.
Successful target commit never claims achieved exact half exposure after lot/fees.

Native denial, rejection, cancellation, unexpected fill, partial or mismatch keeps
the existing abort/unfinalized contract. EventNativeFailure retains the actual
callback and an actual native partial cash/position observation separately from
the controller's last reconciled expected prefix. It does not erase a physical
partial fill or emit a successful receipt for it. Partial evidence cannot be
published as a completed witness packet. This component establishes no scientific
partial-path admission, refund, retry or native-guard increase.

## Source-absent private witness packet

`verify_saved_event_witnesses(account)` inspects saved source/clock/identity/floor,
affordability/maximality, fee/settlement, closed terminal census and actual executed
cash/holding/NAV tape. It checks original per-fill quantities and costs; it does not
reroute a fee counterfactual, invoke native, reconstruct source or evaluate utility.
SMA200 inputs/formula, exact saved NAV dates/grid, actual account/instrument joins,
required anchors, leg/cost/generation and no missing receipt are checked explicitly.
It is internal arithmetic/correspondence proof, not independent authenticity of an
arbitrarily supplied self-consistent native trace.

`event_native_witness.witness_bytes`, `verify_witness_bytes`, `publish_witnesses`
and `verify_stored_witnesses` use the existing canonical JSON/SHA/immutable publisher.
Only the closed component dataclasses, exact normalized Fractions, tuples and plain
JSON scalar structures decode; no pickle, executable imports or source lookup.
Expected external Context is mandatory when reading saved bytes. The private
content-addressed event-component-witnesses directory contains exactly a manifest
and witnesses.json. Publication uses a caller-owned existing GymStore lock/publisher
without research begin/budget/attempt/record APIs. Verification opens only saved
members, validates their hashes/lengths and performs no write/native/Service call.
This is a component packet, not the future full study semantic/replay/result schema.

Remaining selected seams are the saved six-clause cluster/ES/fees/duration/full-cycle
utility evaluator, complete five-leg report/limitations correspondence, and closed
Service/preflight/profile/source/current-method/runtime/operation integration.
The accepted source view and controller metadata checks do not authorize a retained
financial invocation. Any later scientific use still needs its actual prospective
custody, source rights/clock qualifications, root/prior/resource/authority and
original independent financial judgment. No public UI/Orders/serving change occurs.
