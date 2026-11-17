# Native component reference selection

The existing research-input-prepare command accepts conversion config /9 with
profile NATIVE-COMPONENT-REFERENCE-INPUT-V1. It selects explicit symbol subsets
from qualified native v2 reference inputs, clips a caller-declared calendar range
and composes the exact rectangular union. It adds no loader, financial model,
provider request or source admission service. Existing /3, /5 and /6 contracts
remain unchanged.

The config fields match the existing composition interface: schema, profile_id,
namespace, inputs, purpose, schedule and date_range. Each input is an input_ref
pin and a sorted, nonempty symbols list. Purpose schema
polar.reference-input-composition-purpose/3 binds those exact inputs, symbols,
schedule, date_range, consumer_protocol, source_acceptance, rights_source_refs,
rights and source_qualifications. Each qualification entry pairs the exact
input_ref and selected symbols with the original qualification pin. The owning
source consumer supplies this purpose under its existing source-use authority;
the materializer does not infer a new grant from the existence of JSON evidence.
Source-specific qualification schemas may predate the generated native manifest.
They are hash-verified and preserved, without inventing a replacement verdict.

All selected native parents must use the existing all-adjusted synthetic
reference-unit basis, no additional action credits and the same qualified private
rights scope (or positive invented namespace markers). Source-specific semantic
fitness remains the source owner's decision; a shared ticker or basis label is
not scientific evidence. Existing PIT, distribution, vintage and investor-total-
return limits remain in the original pinned source decisions and provenance.

Each complete parent is validated by the existing native reader, so the caller
must already be entitled to read each declared parent input. This is not a
selection-before-protected-access authorization boundary. Duplicate parent pins,
overlapping symbols, missing selected symbols/dates, incompatible basis/rights,
changed pins and different complete session rows fail before publication. Existing
component, symbol and byte limits remain unchanged. Output quote lines are
byte-identical to the selected upstream lines; source pointers and unknown clocks
survive, including existing captured single-symbol pointers. Original source
relations and per-component qualification pins remain addressable in provenance.

Use python -m polar.cli research-input-prepare CONFIG and
python -m polar.cli research-input-preflight MANIFEST_PIN. Set POLAR_ARTIFACT_ROOT
to the qualified private artifact namespace. Capture private CLI receipts without
printing source grids. A causal prefix extends only the source schedule; the
consumer must preserve its evaluation geometry and explicitly rebase source row
ordinals when needed. Materialization performs no policy or financial execution.
