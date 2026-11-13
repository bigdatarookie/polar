# Closed B10 common nominal equity portfolio

Profile `polar.scheduled-reference-profile/13` admits only BIL/SHY/VTI and four
legs: VTI_BIL (2/3 BIL, 1/3 VTI), VTI_SHY (2/3 SHY, 1/3 VTI), VTI_FULL and
CASH. The existing fixed annual calendar, exact rational floor, sell-before-buy
NEXT_CLOSE native ledger and immutable store execute fresh BASE100c+10bps and
COST_STRESS200c+20bps accounts (eight total). No new engine or estimator.
Equal nominal VTI weights are not matched executed equity units/exposure/risk;
own-account fees, drift and whole-unit cash clipping remain part of the model.

Five closed criteria: terminal wealth retains at least9/10 VTI_SHY; canonical
D50 strategy RF0Sharpe>=0; exact whole-account drawdown<=9/10 comparator;
annual volatility<=comparator multiply9 then divide10 in fresh D50; positive
terminal growth. Structural invalidity precedes scalars. In a valid phase,
known NOT_MET wins over another required UNAVAILABLE. Comparator Sharpe/CAGR
are report-only. Zero multiplicative risk boundaries need no ratio division.
All eighteen scalar metrics remain in saved evaluation and ordinary result for
every leg/cost. BASE has existing extra diagnostics; STRESS extra diagnostics
are explicitly NOT_REQUESTED. No eras in either phase, no bootstrap or adoption
claim. Preflight wire bounds remain honest (BASE29 metrics, STRESS18, at most30
limitations); no artifact scalar is dropped to meet the display wire.

Existing `reference_input.prepare_input` config/5 uses profile
`SELECTED-COMPOSED-ALL-ADJUSTED-REFERENCE-INPUT-V1` and the same config3 keys:
schema, profile_id, namespace, inputs, purpose, schedule, date_range. Exactly two
input entries contain `{input_ref: original_manifest_pin, symbols: selection}`:
`[VTI]` from an existing converter/2 selected projection and `[BIL,SHY]` from an
existing composer/1 projection with exactly those two symbols. Purpose schema
`polar.reference-input-composition-purpose/2` repeats exact input entries and
union symbols, schedule, date_range, consumer_protocol, source_acceptance,
rights_source_refs, rights. The protocol reference pins the owner metadata JSON
wrapper; no fabricated collection/job or source capture is introduced.

Existing source reader revalidates each original immutable input; only selected
original quote lines enter the output. GLD/IEF are excluded from economic quotes,
records and membership. Original inputs/source-relations references and member,
job/parent/capture graphs remain provenance, not extra strategy symbols. Selected
lines retain original source pointers, exact tokens and null historical clocks.
Output is existing synthetic-reference-source-input/2, composer/2; separate
captures/vintages remain explicit. Namespace/selection/calendar/rights admission
precedes numeric reads, including positive invented provenance rejection in
RETAINED. Config3 and original B9 behavior remain unchanged.

The existing scale1 call-site witness schema and saved verifier bind D cash,
holdings, eligible prices, own centNAV and exact floors plus pre-order cash,
fees, maximal clipping, zero routes, order/fill IDs and all consumed scalar
ledger operands. Existing source-absent read-only recompute checks both phases
without source, policy, native calls or store writes; it is saved numeric work,
not an independent financial confirmation. Direct `verify_saved` remains the
profile10-only convenience API; scheduled recompute is the profile13 graph path.
Actual input/profile/calendar/runtime/root/actor/prior/method/card/operative
allocation stay separately bound by existing owners. Source/invented delivery
performs no retained conversion, financial call, serving change or publication.
