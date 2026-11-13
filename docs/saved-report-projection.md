# Manifest-checked report-only technical projection

`polar.saved_report_projection.project_saved_report(store_root, semantic_id,
 candidate_id=..., experiment_id=..., report_revision=..., runtime_image_id=...)`
reads the existing `reference-research-experiments/<semantic_id>/` layout. The
original raw manifest hash must equal its scheduled semantic ID. Exactly the five
original profile/bindings/calendar/phases/diagnostics members are hash/length
checked with existing bounded no-symlink readers; paths from those JSON objects
are never followed. This closed entrypoint handles profile10 FINAL report inputs.
No second store, scientific job, registry, source conversion or publication exists.

Two calendar forms are explicit. The earlier phases form supplies exactly FINAL
nav_dates/nav_points/return_count (with absent schema or the scheduled-policy schema)
and requires every leg's complete common timestamp vector/date/count. It does not
establish source-close provenance not represented in that form. A fixed-allocation
producer instead saves polar.prospective-fixed-allocation-calendar/1 with flat dates,
initial_date/terminal_date/nav_points/returns, annual_targets, terminal_EXIT,
parent_schedule, clock_scope and source_schedule_rows. No phases object is appended
to or required in that original form. Unknown schemas, mixed flat+phases forms or
unsupported redundant fields reject rather than selecting a convenient version.

The fixed form invokes only the existing pure fixed calendar metadata validator:
saved source rows bind selected dates, original boundaries, annual formation and
next-reference execution dates, modeled UTC K/+60s D and terminal EXIT override.
Every leg's exact nominal timestamps must equal those saved reference closes;
matching calendar dates alone is insufficient. Saved plan grid date/nominal/sample
and initial/terminal flags, event clocks and fixed instruction metadata must agree,
as must its declared mapping/unit and simulation unit. The fixed diagnostic schema
is required alongside supplied diagnostic values. No plan is rebuilt and no price
or source_prices_micro field is valued or traversed. Parent_schedule and clock_scope
annotations remain opaque, manifest-bound producer data; references are not followed
and descriptive prose is not a clock grant. Actual source identity/authenticity,
price/quantity/metric correctness and missing historical evidence remain outside
report admission. No original bytes or calculation bindings are rewritten.

The input store should be physically read-only and all quote/model/source files
absent in a separately scoped actual verification. This function itself opens no
write/lock files. Original calculation code/runtime/bindings/semantic identity are
preserved; current report code inventory and declared corrective revision/runtime
are separate. The function does not require old calculation code to equal repaired
report code, and never edits old bindings to pretend equality. Runtime/revision
arguments are declarations: independent source/package/container custody must bind
them, not infer authentication from this artifact. Original manifest authenticity
and old execution/accounting remain independent evidence responsibilities.

Supplied saved simulation/evaluation/diagnostics are projected by the accepted
public_config/public_reference/project_diagnostics/validate_result functions only.
Before composition, every simulation leg must carry the same exact ordered
integer timestamp grid, with strictly increasing timestamps and the calendar's
NAV dates/count. Every evaluation leg must contain exactly the calendar return
count. Conflicting or extra saved operands are rejected before a formatter can
discard them. Saved leg/phase identities must agree. Missing required saved
fields/diagnostic operands/eras produce INCOMPLETE_INPUT, not reconstruction;
malformed/hash/identity/type/schema conflicts produce INVALID_INPUT. Source-value
refs are not followed, policies/plans are not rebuilt, native simulation/evaluators/
diagnostic recomputation/quote valuation/Service.run/recompute/publication/registry
or artifact-root writes are not called. Explicit saved UNAVAILABLE states remain
supplied states; absent historical sizing/clipping witnesses are not recovered.
All31 limitation objects retain their original formatter code/scope/text semantics.
A wire-valid report is technical admission, not an independent economic verdict,
INVALID reversal, TESTED transition, new attempt or capacity release.

The return uses `polar.saved-report-projection/1` with REPORT_SCHEMA_VALID,
INCOMPLETE_INPUT or INVALID_INPUT and a deterministic separately content-bound
`saved-report-projection-...` identity. It includes original manifest/member pins,
original calculation identifiers, report-code inventory and explicit zero-call/
input-write accounting. These zeros describe this entrypoint's executed call graph,
not missing historical operands or an unobserved retained run. Physical RO/source
absence and actual returned counters must still be witnessed when an authorized
consumer invokes it. No retained A7 compatibility is claimed by invented controls.

`write_artifact(output, artifact, input_store_root=...)` writes one exclusive private
0600 file in an existing current-user-owned directory outside the entire protected
input store. It never overwrites an existing file or follows an output symlink.
A write/fsync failure leaves its exact task-owned partial for diagnosis, not a false
completed receipt. The adapter does not publish result IDs, mutate input/store or
reuse old success-only scientific stored eligibility.

CLI (only after actual source/runtime/custody and finite scope are separately bound):
`python -m polar.saved_report_projection --store-root RO_STORE --semantic-id ID
 --candidate-id ORIGINAL --experiment-id ORIGINAL --report-revision REPORT_SHA
 --runtime-image-id sha256:IMAGE --output TASK_OUTPUT.json`.
Exit0 means report/schema valid; exit2 means an incomplete/invalid technical artifact.
No execution or retained projection is allocated by source availability. Original
A7 INVALID/SPENT/stored-ineligible, all disclosed outcomes and missing55 sizing/20
clipping witnesses remain unchanged. The scientific owner chooses any actual saved
verification scope separately; this source/invented task performs none.
