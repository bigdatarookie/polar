# Lossless selected-input composition

Use the existing `python -m polar.cli research-input-prepare CONFIG.json` with
`polar.reference-input-conversion-config/3`. Exactly these fields are admitted:
`schema`, `profile_id` (`COMPOSED-ALL-ADJUSTED-REFERENCE-INPUT-V1`), `namespace`
(`RETAINED` or `INVENTED`), `inputs`, `purpose`, `schedule`, `date_range`.

`inputs` is an ordered list of 2–16 original selected converter input/2 manifest
pins (absolute path/SHA256/optional bytes). Each component must originate from
selected converter/2, have a distinct source collection and disjoint aliases,
identical complete dates and schedule bytes, identical adjusted-reference basis,
unit, action-credit policy and rights. `schedule` pins the shared original parent
schedule; `date_range` is exactly start/end/count. No component is relabelled as
one capture. Retained projections are read and their quote lines copied verbatim,
then interleaved in date/sorted-symbol order. Original acquisition payloads are
never reopened or re-extracted. Prepare a single-alias component with the existing
selected converter/2 first; preserve its original source-purpose/collection pins.

`purpose` pins `polar.reference-input-composition-purpose/1` with exactly:
`schema`, `inputs` (same exact pins/order as config), `symbols` (sorted union),
`schedule`, `date_range` (same as config), `consumer_protocol`, `source_acceptance`,
`rights_source_refs` (1–16 pins), `rights` (existing private noncommercial
nonredistribution literal, or INVENTED_PUBLIC_TEST for invented fixtures).
The protocol/acceptance/rights refs are integrity-pinned owner metadata, not a
financial verdict or entitlement certification issued by this converter.

Output remains input/2 for the accepted reader and fixed annual profile/5.
`provenance.source_components` retains each input ref, original source collection,
symbols and original source-relations pin; source-relations retains original
records/jobs/parent relations/coverage. Conflicting graph keys fail closed rather
than being renamed. The composed revision is explicitly a composite identity,
not an original collection revision. `vintage_equivalence=NOT_ESTABLISHED`;
observed clocks, raw pointers, exact quote tokens and unknowns remain unchanged.
No scale change, rounding, rebase, dividend credit, provider call, feature, return,
fit, policy, portfolio/native operation or financial qualification occurs.

The shared criterion evaluator additionally supports `TERMINAL_SCALED_GE` and
`VOL_SCALED_LE`, each with a rational `factor: [numerator,denominator]` in [0,1].
Terminal wealth compares exact cent NAV, not return or CAGR. Volatility compares
canonical annual-volatility fields in a fresh D50 context as
`left <= (Decimal(numerator)/Decimal(denominator))*right`; no display rounding.
Legacy criterion definitions and fixed annual policy/5 remain unchanged.
