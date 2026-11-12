# Selected-purpose lossless reference input

The existing `python -m polar.cli research-input-prepare CONFIG.json` admits
`polar.reference-input-conversion-config/2` with exactly schema, profile_id,
namespace (RETAINED or INVENTED), binding, purpose, schedule and date_range.
Use profile_id `SELECTED-ALL-ADJUSTED-REFERENCE-INPUT-V1`.
Refs are ordinary absolute path/SHA256[/bytes] metadata pins; original paths and
bytes stay intact. date_range has start/end/count. Only the existing converter
and immutable reference-input store are used; there is no source/provider call,
new loader, feature, return, estimator, portfolio or model operation.

Purpose schema `polar.selected-reference-source-purpose/1` has exactly:

- source_collection: exact original collection ref, source_plan_id: its composite ID
- source_config: original selected importer config ref (contains original scope/selection)
- acquisition_order: ordered owner targets; portfolio_symbol_order: sorted same set
- schedule: original parent schedule ref; date_grid: exact consumer calendar ref
  with dates and parent_schedule; date_range: exact start/end/count
- consumer_protocol and source_acceptance: existing owner metadata refs
- rights_source_refs: nonempty existing rights evidence refs; rights: output scope

RETAINED rights must literally be
`SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION`.
This binds the declared private/noncommercial/nonredistribution scope, certifies
no entitlement facts and grants no rights or scientific fitness. INVENTED requires
INVENTED_PUBLIC_TEST and positive deterministic invented provenance on both the
binding and source collection; it cannot relabel retained rows as public.

Binding schema `polar.selected-source-consumer-metadata-binding/1` has exactly
schema/source_collection/source_plan_id/portfolio_symbol_order/records/rights/provenance.
RETAINED provenance is exactly:
`{"kind":"OWNER_SELECTED_SOURCE_ONLY","historical_K":"UNKNOWN","asof":"MAPPING_ONLY_NOT_VINTAGE","economic_identity_admission":"NOT_ISSUED"}`.
INVENTED provenance is exactly `{"kind":"DETERMINISTIC_INVENTED_FIXTURE"}`.

Records are the existing converter segment/parent metadata for every selected
alias, sorted by literal_alias. Use selected_for_purpose=true; do not emit the
C-specific eligible_for_C field. Each source_plan_job_id/request must match the
original selected importer metadata. source_records/source_record_ids stay empty:
source-only target identity is not population, FIGI or economic admission.
canonical_job_id, request, segments and other factual source metadata are retained.
The actual collection/partition/body/line/hash/ordinal/parent joins are checked by
the existing converter before any immutable publication. Calendar dates must equal
the declared purpose grid exactly. No missing/extra target/date, adjustment/feed/
request/window mismatch, silent rounding, scaling or extra action credit is admitted.

Output is the existing synthetic-reference-source-input/2: original token c,
padded6dp reference quote at scale1, original pointers and null/unknown clocks.
The scheduled service accepts this validated input version without reclassifying
basis or eligibility. Frozen C54 pins/grid and legacy invented contracts/output
identities remain unchanged. Existing `research-input-preflight` is structural,
not a financial or source-to-experiment admission. Run only through the existing
DE owner after ordinary affected technical qualification/integration.

The output schedule is a derived clipping of the immutable parent: original
calendar pins are not replaced by its new byte hash. When a version2 input's
projected schedule hash differs, scheduled preparation verifies its original
parent pin and exact deterministic clipping (all metadata/clocks preserved,
next-date/month-boundary fields recomputed only at the declared boundary).
A rehashed changed clock/date cannot satisfy the frozen parent calendar. This
check reads calendar metadata only, never quotes or policy values.
