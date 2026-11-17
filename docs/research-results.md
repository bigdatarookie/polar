# Saved research result API v1

The public producer wire is `polar.research-result/1`, closed by `src/polar/research_result_schema.json`. The normative generated schema is executable `ResearchResult` in `src/polar/research_results.py`. No source payload, local path, arbitrary extra field, financial calculation or synthetic replacement is exposed by the read API. Independent assessment records use `src/polar/research_review_schema.json` and bind the exact saved result ID/content hash.

`polar research-publish RESULT.json` publishes canonical result bytes atomically in the existing artifact root under `research-results/research-<sha256>/result.json`. Duplicate identical publication returns the same identity; changed content yields a new identity. Import is a local trusted producer operation, not an HTTP write endpoint. `polar research-review REVIEW.json` records an external assessment, with distinct nonauthor ID; this records the supplied review, it does not authenticate a reviewer's identity or manufacture independent acceptance. Every source/method/run must already have its applicable authority. No run is performed by publishing or reading.

`GET /v1/research/results?limit=10&offset=0` returns `{schema_version:"polar.research-catalog/1", items:[{result_id,content_sha256,question,bindings,basis,evidence_level,assessment}],limit,offset,total,next_offset}`. Limit1..10; offset0..4096. Ordering is stable lexicographic content ID, not run chronology. Empty catalog is `items:[]`, never a demo fallback. Each member is verified on read. `GET /v1/research/results/{result_id}` returns `{schema_version:"polar.research-detail/1",result_id,content_sha256,record:<ResearchResult>,assessment}`. Invalid ID422, unknown404, content/hash/schema/unsafe-path conflict409, unavailable storage503. Error bodies contain stable codes only. The existing Service/CLI/API share operations and artifact root; no DB migration or research execution is needed for read/publication.

`record.grid` is the ordered complete UTC nominal NAV sample grid (RFC3339 endingZ). `record.series` has one STRATEGY, exactly identified BENCHMARK and optional CONTROL legs. Each leg's `values` and `ledger` arrays match every grid index; values are decimal strings or explicit null/status/reason. No row is dropped or forward-filled. `primary_benchmark_id` selects the paired benchmark; extra cash/full-exposure controls remain visible and identified. Values have `status` OK/UNAVAILABLE/INVALID/NOT_APPLICABLE/NOT_RUN: OK requires nonnull value+null reason; other statuses require null+reason. Zero is a value, not missing. NAV unit USD. Ledger preserves cash/exposure/cumulative flat and bps fees, integer positions and supplied net-return status on the same grid. Initial net-return is NOT_APPLICABLE/INITIAL_POINT. Final source-close is never required or inferred from cash-only NAV.

`record.metrics` identifies each metric and unit with exact per-leg value records. `comparisons` gives producer-computed differences and their explicit leg/metric IDs. `criteria` gives preregistered point-condition MET/NOT_MET/UNAVAILABLE and `point_interpretation` describes the result. These are point descriptions, not independent financial verdicts or significance. The frontend plots supplied NAV and formats display precision only (e.g. Sharpe2dec); it computes no returns/CAGR/differences/fees or unavailable substitutions. Full decimal tokens remain available in details.

`costs` separates CHARGED_FEES, MODELED_SPREAD, MODELED_SLIPPAGE and UNMODELED items with per-leg value/status and descriptions. `basis` preserves PRICE_ONLY/TOTAL_RETURN, NET/GROSS_SAME_TAPE, timezone/frequency/currency/cash/RF assumptions. `limitations` is coded text+scope and must remain readable next to results; bulky provenance/ledger details can be on-demand outside the main chart. `bindings` pins protocol/data/code/evaluator/runtime and producer/candidate/experiment IDs. `provenance` contains safe IDs/hash/role only. Do not expose original private file paths.

`assessment={technical,product,financial,reviews}` defaults all dimensions to NOT_REVIEWED. Later immutable `polar.research-review/1` sidecars carry TECHNICAL/PRODUCT PASS/FAIL/HOLD or FINANCIAL SUPPORTED_WITH_LIMITS/NOT_SUPPORTED/INDETERMINATE plus exact subject hash, scope description, reviewer ID, UTC time and public reference hash. Assessment is the latest timestamp/hash ordered record per scope; all reviews stay visible. A producer may not record its own assessment. Source/author/native/CI/serving/financial evidence remain distinct. The service records external assertions and checks binding, not institutional authentication.

The fixed two CI8h profiles are selected independently and before results by research owners. This wire does not establish original HYP claims or approve a retained trial. Public CI uses invented fixtures only; private real source data is never committed or uploaded.

Wire v1.1 clarification before results: decimal tokens permit up to4096 fractional digits and256 integer digits, preserving Decimal50 significant precision with leading fractional zeros rather than forcing50decimalplaces. Timezone permits UTC or a named Area/Location; public grid is always UTC. Financial reviews additionally require evidence_status (NOT_RUN/INVALID/INSUFFICIENT_EVIDENCE/ASSESSED_WITH_LIMITS) and reason; nonfinancial scopes use NOT_APPLICABLE. Assessment.financial_evidence preserves this distinct status with default NOT_RUN/INDEPENDENT_REVIEW_NOT_RECORDED. Commission attribution is displayed once: flat and10bps components are both debited inside nativecommission; modeledspread/slippage labels describe the specified scenario and do not imply an additional charge. No economic definition or result value changed.

Publication privacy boundary: only explicitly sanitized public result/review documents may be passed to these trusted local CLI operations. All free-text values are scanned before publication and on read; physical absolute Unix paths, file URIs and Windows drive paths are rejected with a stable error. This is not a general credential/PII detector and is not authority to publish private source payloads in prose. Producers remain responsible for public-safe text. The read API is intended for the existing private local service, never a public deployment.


The shared result wire accepts1..31 limitation objects, preserving each supplied
code/text/scope. This is an additive bounded report-capacity extension; existing
result bytes/content IDs and defaults are unchanged. It does not relax40metrics,
30provenance entries, closed-field/text safety or8MiB total result limits. No
limitation truncation or implicit financial verdict is performed. Scheduled
profile10 can use31; other existing scheduled profiles retain their30 admission
bound. Actual publication/serving or retained scientific use is separate from
source/schema qualification.

## Descriptive readers and native decisions

`polar.research-description/1` is an additional strict record family in the same
content-addressed result store, catalog, detail and delivery interfaces. It has
owner-sanitized observations and explicit `NOT_APPLICABLE` portfolio applicability,
without manufactured NAV, ledgers, investor metrics or orders. Historical Git,
engine, candidate and experiment bindings may be null. Actual file hashes remain
in provenance. A content-derived data revision identifies the exact composite
inputs; it is not a registered dataset alias. The JSON schema is
`src/polar/research_description_schema.json`.

Readers accept both families. Publication of descriptions defaults disabled;
`POLAR_DESCRIPTIVE_WRITER_ENABLED=1` enables it only after the deployment owner has
qualified and loaded API, delivery worker and accepted web dualreaders. The
worker consumes this same switch. Native proof publication separately defaults disabled; enable
`POLAR_NATIVE_REVIEW_WRITER_ENABLED=1` only after the same reader/replay qualification.
The disabled-writer dualreader composition is
the rollback floor after either descriptive or native-proof publication. Preserve
subsequent results, review directories, claims and outbox; do not restore a DB
backup over those operations. Original result/1 canonical bytes and IDs are stable.

The external `research-review` entry preserves existing assessments and labels
unknown provenance `LEGACY_EXTERNAL_UNKNOWN`. Its scope summaries remain external
facts; `assessment.native_review` contains only verified native decisions and
otherwise stays `NOT_REVIEWED`. A claimed reviewer or role cannot populate it.
A new request containing only `decision_ref: qitem-ID#terminalTransitionID`
resolves through the actual inherited `rig` adapter, never caller identity fields.

The assigned current Polar Validator's native terminal resolution must be JSON
`polar.native-research-decision/1`, binding exact result ID/content, complete
bindings, actual author/coauthor sessions, actual claimed generation, and six
review fields: scope, verdict, scope_description, reference, evidence_status,
reason. The tool verifies native role/custody, actual transport claim and close,
current generation and re-read custody, and excludes authors/coauthors. The
Validator attests authorship and exact subject from its actual independent
assessment; historic prose alone is insufficient. Reviewer alias/time are derived
from native metadata. Missing typed scope remains unreviewed, without a science
rerun. Scientific verdict and code acceptance are separate.

Proof is committed by hash in a new immutable review reference and stored beside
its review.json in the existing review directory. External calls cannot mint this
reserved reference. Identical external replay preserves already verified proof.
The original worker cannot replay these directories, even though it can read
review.json; retain the qualified replay-capable floor. Native adapter dependency
loss preserves delivery leases rather than recording a scientific rejection.
Native delivery must run through an actual tool-bound consumer; a container with
no inherited rig adapter is not evidence of native review consumption.

Only owner-authorized metadata may enter the ordinary result wire. Protected
licensed/derived numerical fields require the current owner and same private
purpose to be verified per request by the server. They stay withheld while that
predicate is unavailable. Loopback, UID and file mode are not owner authentication.
Metadata-only display does not complete the full protected-numerical user journey.
