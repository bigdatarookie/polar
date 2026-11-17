# Selected-span reference materialization

Use conversion schema polar.reference-input-conversion-config/10 for the explicit
FOMC source branch. The existing prepare_input dispatch calls
fomc_source.prepare_source_input(config, root, limit, queue=native_queue).
Platform owns that closed config schema, current native identity/admission,
static source contract and read-time authorization. No old drawdown admission,
CLI alias or generic plugin is used. The helper cannot qualify an actual source
or grant rights merely because a caller supplies a proof-shaped dictionary.

After checking the exact new scope before any value access, the source owner calls:

    selected_component_input.prepare_selected_components(
        spec, root, limit, source_binding=checked_native_binding)

The spec has schema polar.selected-component-materialization/1, namespace,
leaf_inputs, normalized_inputs, schedule, date_range, purpose_ref and
qualification_refs. Each leaf input has input_ref and symbol and must be a
singleton native v2 parent. Each normalized input has input_ref, binding_ref and
symbol; binding_ref is the existing selected-source-consumer-metadata-binding/1.
All metadata pins and the complete clipped session rows are validated before
price access. Purpose and original qualification pins are preserved, not reissued.
The closed consumer binds the whole spec and output namespace into its actual
source decision. An uploaded dictionary is not native identity evidence.

No mixed native parent quotes or original raw source bodies are opened. Original
normalized member bytes are read/hash-checked; only the selected record's spans
and requested date ordinals enter JSON decoding. The original pinned schedule
fixes the row/date map, so off-range selected-symbol rows also remain undecoded.
Singleton leaves use the same date-ordinal rule and never load_reference(parent).
Selected lexemes, raw pointers, member/line hashes, job/parent or capture graphs
and UNKNOWN availability are preserved. Original raw-body integrity is a pointer
hash/partition binding, not a new raw-body validation claim. Excluded values are
not semantically validated. Missing selected spans or altered metadata fail
before immutable publication. Existing component/symbol/member/byte bounds apply.

The output remains native synthetic-reference-source-input/2. Provenance records
converter polar.selected-component-materializer/1, spec, private_root,
source_native_binding, parent_schedule and exact selected integrity scope.
Platform must recognize that converter and run its new prepared_authorization
before protected member access in every preflight/read/run path; it must bind the
exact new source scope/code/runtime/current task and preserve custody rereads
before FIRST_START. Recognition of the old converter/7 is insufficient. This is
part of Platform's coherent FOMC integration, not a separate acceptance wave.
The helper returns PREPARED_SOURCE_ONLY, revision and immutable input_ref. It
performs no financial, policy, provider, source-native admission or model call.

Public invented checks forbid mixed parent quote/raw-body opens and excluded
asset/off-range row decoder calls. They verify selected-line lineage, existing
captured-leaf pointers, namespace/purpose/source graph/missing coverage failures,
publication absence on rejection and closed-owner config10 dispatch. Actual
retained materialization requires the separate new source/purpose/semantic fit;
this source-free implementation does not inspect retained values.
