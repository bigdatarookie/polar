# Captured single-symbol reference composition

The existing research-input-prepare CLI accepts conversion config /8 with profile
CAPTURED-SINGLE-SYMBOL-REFERENCE-COMPOSITION-V1. It combines qualified native v2
inputs with archived single-symbol daily bar responses. It performs no network
request or financial operation. It requires an existing pinned source definition
and compatible source disposition, and binds every component to that disposition.
It preserves the original definition, receipt, request and selected member pins
in source relations. The caller's source qualification remains distinct from a
public display grant or a scientific verdict.

Config fields are schema, profile_id, namespace, inputs, captures, qualification,
consumer_question, schedule and date_range. Each capture supplies symbol, plan,
receipt, raw, selected and source_definition pins. The archived plan must be an
Alpaca single-symbol daily SIP USD request with adjustment=all; the response must
be complete, match the symbol and have no continuation token. Selected NDJSON
has symbol, aggregation_label (the source timestamp's date) and
adjusted_reference_close_token. Tokens must equal original JSON close lexemes
and fit the existing positive six decimal scale without rounding.

The disposition has compatibility.per_source_basis, source_pins and status
COMPATIBLE_FOR_FROZEN_COHORT_VENDOR_REFERENCE_SEMANTICS_WITH_LIMITS. Relative
source pins resolve against its directory. All raw/selected/receipt/definition
and native-parent pins must occur in that immutable source set. Unknown clocks,
investor total return and other provider limitations are preserved; the adapter
does not create action/distribution credits or establish raw-share equivalence.
It maps the qualified common vendor-reference semantics into the existing v2
basis. It cannot compose heterogeneous unqualified bases.

Use python -m polar.cli research-input-prepare CONFIG, then
python -m polar.cli research-input-preflight MANIFEST_PIN. Set
POLAR_ARTIFACT_ROOT to the existing qualified private artifact namespace. Capture
CLI output privately: preparation/preflight receipts can include source grid
metadata. A resulting input is not a financial run. Annual fixed calendars use
the existing scheduled_fixed contract and must be bound independently to the
exact declared economic window.
