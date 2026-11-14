# Pure calendar controller and supplied evidence contract

`polar.scheduled_event_controller` is a deterministic price-free companion of
`scheduled_fixed`. It does not read artifacts, submit orders, simulate portfolios,
calculate SMA or utility, publish results, or grant execution authority. Existing
profiles, engine dispatch, ledger, reader and public schemas are unchanged.

The selected consumer is the calendar-only five-path/six-clause question, not the
prediction six-path question. Prospective definitions are packet1b6c350e, dispatch
choicesc89f7e6a, and the queued-reentry barrier clarification3f0ca40a. This is the
first pure unit, not a runnable research profile or full-study acceptance.

## Closed Python callable contract

All time fields are integer UTC nanoseconds, excluding bool. `ns(ISO)` converts
accepted clock timestamps of at most six fractional digits exactly; unsupported
precision fails rather than truncating it. No native monetary values are inferred.
Frozen dataclasses are the in-process schema; no new Service/JSON dispatch exists.
`ControllerError` reports invalid supplied structure or causal ordering without
changing the input state. Consumers must retain errors/partial evidence, not label
an invalid call HOLD, no-fill, zero duration or successful execution.

- `normalize_event_calendar(metadata, clock_rows, nav_role_grid)` accepts source rows
  with exactly event_id, cancelled(bool), provenance; accepted
  `scheduled_fixed.event_clock_metadata` CALENDAR_ONLY output objects; and the
  strictly ordered nonempty saved close grid. Source IDs are unique. Extra clock
  IDs and clocks attached to cancelled members fail. It returns frozen `Calendar`
  with every `CalendarEvent`, canonical inclusive/touching/transitive cluster
  memberships, unclustered missing IDs and execution_authority=false. It preserves
  the complete canonical clock JSON and its SHA, including distinct calendar K,
  quote K, signal N/A, temporal candidate and modeled/observed/unknown provenance.
  A planned anchor is the actual supplied prior-date close in the role grid, never
  the older sizing quote, cutoff or delayed protection Q. Missing/censored events
  stay visible; no complete-case financial census is asserted.
- `request_from_event(event)` converts a noncancelled eligible/conditional accepted
  clock event into a typed `Request`. Null/unknown/future K or unavailable chronology
  cannot silently produce an eligible request. A selected modeled assumption must
  be explicitly supplied to the accepted clock upstream; this module never invents
  it. Content hashes identify supplied evidence, not authenticated source truth.
- `State(Context(...), mode='CALENDAR'|'SMA')` binds account, leg, cost, input,
  calendar and protocol identities. Initialize a separate state for each account.
- `advance_controller(state, Observation(...)) -> Decision` accepts INIT, REDUCED,
  EXPIRY, SMA, ROUTE_Q or EXIT. Returns a new state, TARGET/HOLD/EXIT/SKIP/ROUTE_INTENT,
  reason and any cancelled/superseded intent IDs. IDs bind context, generation,
  destination, original D/Q, cause and canonical active member IDs. Persist the
  returned decision sequence; current state alone is not the historical ledger.
- `validate_anchor(anchor, context, generation, q_ns)` validates the supplied
  common-Q identity, mark/route timestamps and quote<mark<route sequence barriers;
  cash, both BIL/VTI held quantities, exact Fraction close marks, rounded position
  cents, NAV and cumulative flat/bps cents, source and anchor IDs. On HOLD, call it
  separately for every required pretrade anchor using that barrier's generation.
  No routing or state commit is required. It returns only
  SUPPLIED_ANCHOR_STRUCTURE_VALID_NOT_NATIVE_VERIFIED. It cannot prove marks were
  captured, valuation is correct, quantities are affordable or native data is true.
- `accept_route_receipt(state, RouteReceipt(...)) -> State` validates exact issued
  intent/account/leg/cost/input/calendar/protocol/generation/Q identity, a finalized
  timestamp after the supplied route barrier, anchor, two-symbol delta census,
  explicit consumed-sizing evidence IDs and actual routing counters. An unresolved
  route must be finalized (possibly UNKNOWN/INVALID) before another dispatch.
  Only complete FILLED or explicit ZERO_DELTA_NO_ORDER commits. Missing or malformed
  evidence raises; it never backfills sizing, fills, anchors or observations.

## Causal state behavior

INIT queues NORMAL(fullVTI); a new eligible REDUCED observation queues halfVTI/halfBIL
only on NORMAL->REDUCED. Each request has an immutable source event ID, D, inclusive
r2 expiry and explicit reentry D/Q. Repeated/expired IDs fail, not reopen. Overlap
while desired REDUCED emits HOLD and extends the active expiry, even after failure
or drift. A still-queued identical protection is coalesced with original D/Q sizing
unchanged and a new active-set ID; the old ID is explicitly superseded. No duplicate
order or automatic failed-fill retry is authorized.

EXPIRY only removes expired requests. While any request remains active, HOLD. The
latest actual expiry supplies the bound midnight decision and strictly future Q;
queuing NORMAL reentry keeps desired REDUCED/pending destination NORMAL. New REDUCED
D<Q cancels reentry without a false NORMAL/REDUCED roundtrip. At a valid ROUTE_Q,
reentry flips desired NORMAL before its receipt. At equality D==Q, ROUTE_Q must be
processed first; same-time observations affect a later Q. A stale, cancelled or
obsolete protection Q>r2 cannot commit. Terminal EXIT cancels pending work and
requires its own later permissible routing/receipt, never a synthetic liquidation.

Desired latch, queued pending intent, issued awaiting receipt, committed target and
conservative reduced-duration status are separate fields. Partial/rejected/
nonzero-no-fill does not reset the latch or imply realized half exposure. A
successful zero-delta requires both deltas0, orders/fills0 and explicit consumed
sizing evidence. HOLD never upgrades a failed/unknown attempt. Failed NORMAL reentry
keeps prior conservative reduced status; successful NORMAL/EXIT clears current
reduced status. UNKNOWN/INVALID makes current duration unknown and permanently marks
`duration_evidence_complete=false`; later success cannot repair the missing history.
Actual exposure is deliberately not calculated or fabricated in this pure unit.

SMA mode accepts externally supplied NORMAL(VTI)/BIL category only: initial/change
TARGET, unchanged HOLD, UNAVAILABLE HOLD without category invention. No200-price
calculation or defensive fallback is supplied here. Static/monthly controls remain
unchanged outside this module.

## Next consumer seams

After ordinary affected source/CI/independent qualification and normal integration,
one separately routed metadata-only consumer may exercise the existing33/32 panel
and clock outputs. This author uses invented source-shaped rows only. Actual native
pretrade capture, single effective pending intent/IDs, fill/partial-path admission,
consumed sizing/fee/clipping witnesses, portfolio dispatch and the saved six-clause
ES/utility/duration evaluator remain separate selected work. No source, PIT,
financial, actual execution or full-study readiness follows from this unit.
