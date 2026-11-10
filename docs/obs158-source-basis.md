# Exact retained OBS158 asof correspondence

The retained d362 normalized source declares the exact token
`2020-09-02_ENTITY_MAPPING_NOT_VINTAGE;FALLBACK_UNVERIFIED`. The request profile
uses the date `2020-09-02`, but these are different metadata operands. The
normalizer's qualifier preserves entity-mapping scope, absence of a historical
vintage claim, and unverified fallback. It is not evidence of point-in-time
identity, source vintage, verified fallback or ISO currency.

The OBS158 retained checker compares that entire declared token. It continues
to require raw adjustment, sip feed and USD_REQUEST_CONTRACT currency. It never
strips qualifiers/whitespace, accepts a date prefix or rewrites source rows.
The fixed public INVENTED fixture retains its original bare request token;
retained data cannot use that branch. All other data/preflight/runtime/authority,
native/metric/terminal/attempt-budget checks are unchanged.

The metadata-only correspondence is recorded by DE in
`obs158-basis-correspondence-v036-20261111/ASSESSMENT.json`. It attributes the
all-row basis observation to an existing pinned40665-row inspection, not a new
raw-row survey. The19:52 generic and20:33 diagnostic failures remain historical.
CONVERSION_BINDING was a downstream skipped comparison, not a separately
diagnosed conversion defect. This source fix does not claim that a future full
preflight, native run or financial result passes.

Affected tests use invented metadata dictionaries only: exact retained token,
changed date/unsupported qualifier, missing/changed other basis fields and the
unchanged public fixture token. No input loader, retained preflight, candidate,
native/original/replay or financial calculation is invoked by these tests.
Independent nonauthor affected review and actual qualified source/runtime/input/
authority binding precede the sole SRE operational continuation. No source
acquisition, price/cohort/date/exam change, automatic retry or budget reset is
authorized by this correction.
