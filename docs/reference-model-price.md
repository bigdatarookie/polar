# Explicit coarse100 model price

`polar.scheduled-reference-profile/10` reuses profile5's fixed annual rational
weights, calendar, exact-cent native account, evaluation and immutable store.
It adds one required typed field `model_price_mapping`; existing profile1–9
field sets and semantics remain unchanged. This is a changed lot1 model grid,
not a source correction, split, physical share or invariant coordinate relabel.

The mapping has exactly:

```json
{
  "schema": "polar.reference-model-price-mapping/1",
  "source_input_sha256": "<unchanged input manifest SHA256>",
  "multipliers": {"GLD": [1, 1], "IEF": [1, 1], "SHY": [100, 1], "VTI": [100, 1]},
  "lot_size": 1,
  "active_unit": "COARSE100_SYNTHETIC_REFERENCE_UNIT_NOT_PHYSICAL_SHARE"
}
```

Every source alias is explicit. Factors are integer pairs1/1 or100/1 only,
at least one coarse100, lot1; identity aliases must have zero weight in every
leg. Booleans, fractional factors, changed source hash, unbound symbols and an
implicit per-stage transformation are rejected. The selected A7 uses exactly
the four aliases/factors shown; invented tests use separate fictional aliases.
This is not a general transformation framework or permission to select factors.

Use existing scheduled seed/config/Service/CLI interfaces. The original input
and source quotes remain unchanged. Metadata/preflight binds profile, protocol,
input, calendar, timezone, code/runtime/root and declared mapping without
deriving prices. Retained `prepare(load_prices=True)` is rejected for this
profile: before an original use metadata-only `preflight`. After the durable
original debit, the unchanged source loader enforces reference_quote equals
original source_adjusted_close_token. Only then a separate model view applies
integer100 multiplication; original source prices and pointer evidence remain
separate. No source editing/reprojection/retrieval or new engine is involved.

All desired targets, execution quotes, affordability, exact notional fees,
native cent marks and exposure diagnostics use the same model view. Capital,
weights, clocks and fee rules are not rescaled. Fraction weights and integer
microprice multiplication stay exact; normal lot1/whole-unit floors, HALF_EVEN
cent settlement and downward fee-aware next-close clipping remain. Overflow or
native Price precision/range loss is rejected, never clamped or rounded. Actual
retained magnitudes remain uninspected until the properly debited original;
domain failure is charged INVALID/partial, not a free factor adjustment/retry.

Each native plan saves the typed mapping, original `source_prices_micro`, model
`prices` and explicit coarse quantity unit. These fields are covered by profile,
config, semantic-manifest and current code bindings. Stored reproduction checks
every saved source/model pair and mapping without reading source paths or
calling original policy/native/model code or writing the store. Source/model
correspondence is an arithmetic check over saved evidence, not a new source audit.

The existing common saved-result schema is retained because its wealth remains
synthetic-reference-model USD NAV, not a receivable or physical-share ledger.
Projection wording distinguishes original vendor-adjusted source evidence from
declared coarse model prices, adds mapping provenance/limitations and labels
return/CAGR as coarse model-unit outcomes. Executed price_micro is the model
price; quantity_unit identifies the coarse unit, and price_unit remains USD per
synthetic reference unit. No raw OHLC overlay is compatible. Original records,
source tokens and profile5 outputs are unchanged. P1/result-reader compatibility
does not by itself certify a new retained result or any financial conclusion.

This code adds no scale1 rerun, multiplier/lot/capital/cost/weight search,
stress/bootstrap or matched-initial-state guard. The owner must bind the exact
prospective protocol/card/current method and independently qualified current
profile/runtime to a new fixed original and SUCCESS-only stored allocation.
General denomination robustness/adoption remains insufficient even if the one
selected point screen survives. No provider, UI or serving rollout belongs to
this author change.


## Lossless metadata admission and report capacity

Profile10 adds one `DECLARED_MODEL_PRICE_DENOMINATION` limitation. Metadata
preflight counts it alongside twelve base limitations, declared extras and each
leg's risk/subperiod descriptions. The common executable and JSON wire now admit
up to31 limitation objects. A five-leg/two-subperiod profile with three extras
uses31 and passes this report bound; four extras need32 and reject before any
attempt debit, price/model load or native call. Metrics remain bounded40,
provenance30, text1000; legacy scheduled profiles retain their30-item preflight
bound. No missing explanation or era is dropped/grouped/truncated to fit.

Invented scalar projection, immutable publication/restart/API controls preserve
all31 code/scope/text identities and every other supplied field. Schema parity,
30/31 acceptance,32 rejection, closed fields/public-text checks and legacy
preflight controls cover this additive report capacity. This accommodates the
unchanged scientific mapping/weights/capital/lot/costs/calendar/criteria/eras;
it does not establish actual retained compatibility or create a scientific run.

Historical PR107 correctly added the missing denomination item to preflight's
count under the then-current30 wire, so31 rejected early. That result and its
red controls remain preserved; undoing the count would reintroduce late failure.
This later lossless capacity change keeps the count and strict oversized guard.
Original A7 remains INVALID/FAILED_UNFINALIZED, original spent and stored
ineligible. Its exact original failed field/exclusive cause is not established
by invented tests; missing historical consumed sizing/clip witnesses remain
UNAVAILABLE. No retained payload read, saved-result reconstruction/republication,
authority/budget/root change, retry/refund/reset, serving or financial verdict is
part of this source change. A separately allocated lawful corrective use, if any,
remains the scientific owner's decision with full history/exposure preserved.
