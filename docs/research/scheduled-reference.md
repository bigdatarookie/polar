# Scheduled reference policies without fitting

The existing ReferenceResearchService/Service research-config, research-preflight,
research-run and research-recompute entrypoints accept a closed scheduled profile.
They reuse the reference input reader, frozen decision quantities, native ledger,
common result publisher and immutable store. Legacy ridge/PPO/C profiles retain
their existing admission and output path. This first unit supports absolute
momentum sleeves, equal-weight scale controls, positive top momentum and cash.
The pure inverse-volatility helper is not yet an executable B profile: stress
cost propagation and saved uncertainty remain a separate delivery unit.

## Metadata interface

Use polar.scheduled-reference-seed/1 with namespace INVENTED or RETAINED,
absolute profile_path, protocol_path, input_path, calendar_path and timezone_path,
code_revision (40 hex), runtime_image_id (sha256 plus 64 hex), candidate_id and
experiment_id; execution_authority_path is optional during inert preparation.
research-config resolves refs with path/sha256/bytes, current code-binding and
artifact-root identity into polar.scheduled-reference-config/1. It does not fit,
predict or run a policy. See tests/scheduled_fixture.py for a complete invented
profile/calendar and src/polar/scheduled_policy.py for closed required fields.
A profile is bound to the exact protocol, input, calendar and timezone hashes;
no experiment or owner name source allowlist and no expression/plugin loader.
The calendar explicitly declares VALIDATION and/or FINAL, full NAV dates and
month-end decision/next-session reference-close joins. Profiles state all leg
IDs, labels, rules/scales, primary roles, K-to-D delay, point criteria, prose and
saved subperiods. Finite common-wire bounds are checked before an original.

Retained preparation validates the existing exact reference-source rights and
runtime versions. Preflight reads and validates source but evaluates no policy,
features or weights and creates no attempt. A run requires a content-bound
polar.scheduled-reference-operation/1 authority: action ORIGINAL,
binding_sha256 of config excluding execution_authority_ref, allowed_fit_calls=0,
allowed_predict_calls=0, allowed_native_accounts equal legs times phases,
expected_prior_attempts=[], and pinned method_ref, candidate_ref and
qualification_ref. Method schema is polar.prospective-method-disposition/1 with
method_verdict PASS and matching protocol SHA/candidate. Reservation must be
RESERVED with matching candidate and registration. Qualification must be the
actual matching candidate CI PASS with applicable scheduled service selection;
independent applicable technical disposition remains an ordinary owner duty.
This schema is not a new permission issuer or scientific budget grant.

## Execution and output

The durable FIRST_START_CONSERVATIVE_DEBIT is persisted before loading retained
numeric source or evaluating the first signal. A family is stable across source
revisions for a protocol/input/namespace. Any prior attempt rejects another
original; failed/unfinalized attempts are preserved without refund or retry.
Each phase uses fresh capital. At D, only eligible formation prefixes determine
weights and desired whole quantities. Next-close execution can clip buys for
cash including fees, never resize targets using future quotes. Terminal exits
are planned once. Native/evaluator results and full saved diagnostics are
checkpointed by phase. Fit/predict/model counters are truthfully zero.

Semantic files are profile.json, calendar.json (including source schedule rows),
phases.json, diagnostics.json and bindings.json plus a hashed manifest. Public
records use polar.research-result/1, supplied roles/labels, synthetic vendor-
adjusted-reference basis, actual costs and NOT_REVIEWED until an external review.
Tail/month/recovery and subperiod metrics are descriptive saved-ledger outputs.
Full diagnostics remain immutable; the finite public wire carries selected
scalar metrics and explicit accounting/anchor/censoring limitations. No trained
model or forecast-MSE provenance is fabricated.

Stored reproduction verifies hashes, current code binding, saved evaluation and
saved-ledger diagnostics. It never loads source, evaluates policy, fits,
predicts, invokes native or writes. A success does not grant a new original.

## Public qualification

scripts/ci.sh --scenario scheduled-policy --reports EMPTY_DIRECTORY runs the
invented 400-date, four-symbol service through two phases and ten native
accounts, applicable pre-existing frozen literal allocation/fee controls,
common-wire publication/readback, zero-call stored reproduction and duplicate
rejection. Computation and owned cleanup are separate statuses. Ordinary Actions
runs this named scenario for candidates containing scheduled_service.py; a
missing entry/result fails. No private quote, frozen owner outcome or retained
scientific fit belongs in public CI. Author synthetic PASS is not independent
technical or financial acceptance. The first author failure at 03384fa is kept
outside Git in polar-v037-scheduled-A-author-20261111-01: publication exceeded
the common metric limit after native computation; the limit was preserved and
the projection made finite.
