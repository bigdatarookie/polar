# Retained VTI/BIL source view

This is one closed config6 branch in existing
`polar.reference_input.prepare_input(config, root, limit)` and
`Service.research_input_prepare(config)`. It projects an already accepted v2
composer2 source input. It does not refetch/re-adjust prices, recreate an
importer collection, run finance or change `load_reference` or config3/5.

## Closed metadata contract

Config schema `polar.reference-input-conversion-config/6` has exactly:

- `profile_id`: `CALENDAR-VTI-BIL-SOURCE-VIEW-V1`;
- `namespace`: INVENTED or RETAINED (never promote a positive fixture);
- `input_ref`: genuine parent manifest pin `{path,sha256,bytes?}`;
- `purpose`: immutable JSON purpose pin;
- `schedule`: original pinned XNYS reference schedule, not a fixed-allocation
  calendar or a date list; existing schedule_binding_matches binds its projection
  to the parent manifest schedule;
- `date_range`: `{start:'2023-03-16',end:'2026-11-06',count:916}`.

The parent must be `polar.synthetic-reference-source-input/2`, symbols exactly
BIL,SHY,VTI, composer/2 with selected-composition profile and matching semantic
config5 namespace/date-range/quote/schedule/relation pins. All-adjusted reference
basis, synthetic-unit/no-additional-action policy and original rights remain
unchanged. The full parent rectangle is validated by the existing reader; only
then are original selected NDJSON lines copied. No retained parent/value pointer
is followed in authoring or independent source review: actual construction is
the existing DE source consumer's later qualified use.

Purpose schema `polar.reference-input-selected-view-purpose/1` has exactly:

- `input_ref`, `symbols:['BIL','VTI']`, `schedule`, `date_range`, identical to the
  config (typed canonical correspondence);
- `roles`: `{nav_dates, warmup_dates, warmup_symbol:'VTI',context_symbol:'BIL'}`.
  Both date lists are explicit sorted unique strings. NAV has716 dates beginning
  2024-01-02/ending2026-11-06. Warmup has200 dates beginning2023-03-16/ending
  2023-12-29. Their prefix/suffix concatenation must equal the exact selected
  pinned reference schedule. No weekday/calendar synthesis, gaps, duplicates,
  overlapping roles, future warmup or extra source dates are admitted;
- `consumer_protocol`: pin to existing
  `polar.captured-reference-protocol-binding/1` wrapper `{schema,protocol,packet}`;
  protocol may be Markdown, packet is JSON. This binds a source consumer purpose,
  not a claim of a frozen runnable scientific protocol;
- `source_acceptance`, `event_panel`, `date_association`: JSON metadata pins.
  Their exact bytes/hashes are bound; the converter does not reinterpret panel
  members, planned versus actual releases, cancellations or known-by. Actual
  selected panel33/32planned/1cancelled and date association remain DE/owner
  evidence, not inferred market outcomes or tested probabilities;
- `rights_source_refs`:1..16 original rights metadata pins, and `rights`: exact
  retained sole-owner private/noncommercial restriction (or INVENTED_PUBLIC_TEST
  for an explicit fixture).

These metadata/namespace/basis/roles/pin checks precede numeric reads and output
publication. Rehashed malformed metadata cannot silently relax source namespace,
include SHY, repurpose warmup as NAV or claim historical eligibility. Hash equality
is content correspondence, not an independent authenticity/rights grant.

## Output and unchanged reader

The ordinary immutable source-input/2 manifest declares916dates x2aliases=1832
quote records. Quotes preserve original source lexemes, units, row pointers and
published/available clocks byte-for-byte. No rescaling, rounding, source-plan
replacement, action credit or modeled K is generated. The schedule uses existing
`project_schedule`, retaining original session metadata while adjusting only its
subset boundary links. Parent input/purpose/schedule/relation/component and
source-member identities are retained in provenance. Original source graph and
bytes remain untouched; any unselected source/component metadata is provenance,
not an economic SHY quote row.

`date-roles.json` is separately content-bound by manifest provenance/semantic:
NAV716 dates xBIL,VTI=1432 rows; WARMUP_CANDIDATE200 VTI rows;
UNUSED_WARMUP_CONTEXT200 BIL rows. Sum1832, with no warmup/context performance or
trade/state/NAV meaning. The regular `load_reference` still requires a complete
rectangle and reads this view unchanged; roles do not authorize a sparse grid or
change the reader's return type. Source preparation returns input_ref, date_roles
pin, role_counts and source-only/not-assessed status. Repeating identical config
in the same owned root returns the same immutable artifact.

Actual future model must bind NAV/calendar/roles separately. This converter does
not calculate715returns, a signal or an initial position. Supplying200 prewindow
rows does not certify known-by or authorize201-observation SMA. At the eventual
initial Jan3 decision, last200completed eligible quotes may includeJan2 and omit
an earlier prewindow quote, according to the separately qualified policy/clock.
No source history beyond the selected rectangle becomes NAV automatically.

## Consumer custody

After source/independent affected qualification/current CI/normal integration,
return this callable/config and exact accepted source/runtime to the existing DE
lineage. DE freezes actual config/purpose using the actual parent5a9b, original
schedule and supplied explicit role dates, then constructs once in a new owned
root under its source-only mandate and verifies rows/tokens/pointers/roles before
QuantA consumes it. Source construction is not a financial trial or public
publication. Existing clock accepted804 and signed-core/R1 work remain separate;
no additional engine/Lead approval gate, generic loader/controller or source fetch
is introduced. Author tests use invented composer-shaped inputs only, including
extra parent dates outside the selected crop. Official CI's invented native
baseline remains separate technical evidence, not a retained strategy invocation.
