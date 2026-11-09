# Resumable metadata import v1

One ordinary-code loader in existing private Polar artifact storage. The first
adapter is anonymous OpenFIGI `/v3/mapping`: literal TICKER, US, unlisted=true,
no common-stock filter. It is not an OHLCV adapter or a scientific acceptance.
Route evidence: DR policy4e8032ce5268d9838b027d3ec9c7287c4702a2cc75b5f618b6caad9a279ba4db.
Actual provider execution is separate from implementation/fixture qualification.

The installed `polar` CLI and `Service.import_*` methods use the same operations:

| CLI | Input / effect |
|---|---|
| import-plan FILE | Strict config; offline plan and cache reconciliation |
| import-cache-import FILE [--fixture] | Offline validated ancestry/sample/roster migration |
| import-status PLAN | Pending/success/retryable/permanent states and cumulative counts |
| import-result PLAN JOB | All response versions/candidates/source refs; selects none |
| import-attempt-path PLAN UUID | Inert exact terminal/consumer paths for existing SRE wake |
| import-attempts PLAN | Discover retained attempts/markers after missed wake; not object validation |
| import-execute / import-resume PLAN | Explicit --fixture FILE or --network, optional --attempt-id UUID |
| import-control PLAN pause/resume/stop | Atomic cooperative control; never discards an in-flight result |
| import-terminal PLAN UUID --manifest-sha256 HASH | Full retained terminal/object verification |
| import-consume PLAN UUID --manifest-sha256 HASH --assessment FILE | Validate, then idempotent consumption receipt |

Network execution requires a prebound attempt UUID, exact source projection,
POLAR_CODE_REVISION and POLAR_IMPORT_BUILD_ID. It never reads a key or creates an
account. Default operations are offline. Provider and invented-fixture namespaces
are separate, even for identical request IDs, so fixtures cannot poison real cache.
No custom watch, scheduler, database, Markdown state or agent task tracker is added.
Provider execution additionally requires --scope-file pointing to the immutable
remaining-only e094936f record. Fresh uncached jobs must be a subset of that scope;
using an empty/wrong artifact root cannot refetch the8190completed jobs. This file
is a scope bound, not an execution authorization by itself.

## Typed input/state and identities

JSON inputs reject duplicate/unknown fields. Config `polar.import-config/1` has
adapter=`openfigi-ticker-us-unlisted/1`, mode=`fixture|provider`, requests (unique
list of exact four-field request objects), policy (exact fixed dictionary in
import_contract.POLICY), route_evidence={path:absolute file,sha256:64hex}.
Maximum100000 logical jobs. Policy160POSTs/4appearances/900original wall seconds,
45seconds/request,10jobs/request,3second starts,25requests/60seconds,
initialunknownquota60seconds, backoff2..30 plus0..1jitter, 429maxreset/retry-after
plus1second (missing/malformed headers conservatively60seconds),2MiBresponse and
32MiBnewbody limits. Mandated waits are never reduced to squeeze a retry into budget.
An operation may end partial rather than consume its worst-case body-byte reserve.
No old project CPU/RAM pool is used. All attempts/source history are retained.

Job ID is SHA256(canonical polar.import-job-key/1,adapter,anonymous profile,
endpoint,exact individual request), independent of partition/path/plan ID. Canonical
key JSON has no newline; inherited producer wire is compact sorted JSON PLUS
newline, and its actual original SHA is retained separately. Source/config/projection
versions are bound in plan and physical attempt. Counter/limiter/budget scope is
provider/profile, so renaming a plan does not reset it. This initial prospective
cutover counts new appearances separately; inherited exact attempts remain null,
with known receipt minima preserved. A later budget revision requires a separately
versioned prospective cutover; no reset command exists.

Migration `polar.import-migration/1` has roots (explicit allowlist of
{root:absolute directory,manifest:relative safe path,sha256}),
current_manifest_sha256 and ancestry_objects ({root,path,sha256} list). Each manifest
member is byte/hash verified; parent source pins must resolve to a manifest or
explicit ancestry object. The initial sample uses its parent root and singular
receipt/request files. Roster captures use plural receipt/request-body envelopes.
Every accepted result must match original request position and entire response
array length. Never infer a position from ticker text. Malformed historical bodies
remain raw failed evidence, without invented per-job assignments. Multiple captured
response versions and provenance aliases are retained, never latest/first selected.
The full dated relation ledger and older projection remain separately pinned
ancestry, not overwritten by transport deduplication or current classification.

Cached result has job_id, exact request, kind (`CANDIDATES|WARNING_NO_MATCH`), full
response object, response_sha256, sources. Sources bind original manifest/body/wire
SHA, position and actual capture time, or new request/body records. No-match is
completed/reusable; it is not an absent security or permission to refetch it.
Cache commit `polar.import-cache-commit/1` is named by its content hash and verified
on every reconciliation. Unknown/corrupt cache raises a stable error, never success.

Per-job state has state=`pending|success|retryable_error|permanent_error`, kind,
retry_eligible, reason, post_cutover_appearances, historical_attempts_exact=null,
historical_attempts_known_minimum. State is derived from immutable request starts,
outcomes and accepted commits. Four started appearances consume the finite budget
even after crash or timeout. Generic positional batch errors never become fabricated
job errors. Legal singleton recovery goes behind independent queued jobs. Auth401/403
pauses only the provider/profile and is not cleared by ordinary soft resume; an
actual corrected access disposition belongs to the source/operations owner.

## Durable order, ownership and terminal meanings

Kernel flock grants one live scope executor; persisted start records include owner
PID, attempt UUID, source projection, environment, original deadline and physical
timestamps. Acquiring the released kernel lock permits reconciliation, not deleting
old attempts or resetting history. Atomic immutable raw body/response -> accepted
cache commit -> outcome/checkpoint. A committed response/result is recovered before
selecting pending jobs. Crash after acceptance or before checkpoint cannot cause
successful refetch. Checkpoint is a replaceable hash-wrapped projection, never the
authoritative cache or attempt counter. Pause/stop is a separate atomic channel.

Each attempt publishes immutable started.json, terminal-state.json and checkpoint
snapshot; content-manifest.json is published last and binds exact scope/attempt/
plan/start/end/status plus every referenced record/body/cache/plan/config object SHA
and byte length. Completed means every planned transport job has a verified cached
response, including no-match/conflicts; it does not certify economic identity/class/N.
Partial means some accepted jobs with remaining errors/unknowns/limits/pause. Failed
means no accepted jobs and no complete delivery. Interrupted means a caught interruption
with retained partial state; hard kill can leave no terminal marker and is explicitly
RUNNING_OR_INTERRUPTED_UNRECONCILED until owner/SRE reconciliation. No automatic
new capture follows a missing marker. Full terminal hashes are verified before receipt.

Terminal state reports each job state, candidate/no-match/conflict/error counts,
reused jobs, scope/new POSTs, bytes and unknown request outcomes. Request, throttle,
local processing times are separate; unobserved inter-pass time and ETA are null.
Fixture clock is explicitly SIMULATED_FIXTURE, never reported as real throughput.
Calendar qitem age is not measured labor. Source/fixture/runtime/provider/consumer/
scientific claims remain distinct.

Assessment JSON has consumer,outcome,next_action (nonempty bounded strings). The
consumer validates full terminal refs then writes attempts/UUID/consumer/receipt.json
with attempt ID, exact canonical content-manifest.json path/hash, worker start and
assessment. Identical duplicate is ALREADY_CONSUMED; conflicting/cross-attempt receipt
is an error. Native edge detection itself only matches text/basename and cannot
authenticate a receipt. SRE's existing deadline+2minute fallback independently
validates terminal/receipt or reconciles a missing marker; do not rearm old watches.
Receipt means this declared transport assessment occurred, not downstream strategy
or scientific acceptance. Installed reads support actual DE consumer follow-through.

## Prospective author fixture plan

Before dependent tests: no real provider operation, credentials, datasets/returns,
models or HYP007 fits. Bounded invented fixtures cover timeout/recovery,429andlongwait,
finite4appearance/160POST/deadline budgets, malformed-batch isolation/independent
continuation, authpause, durable response/result-before-checkpoint restart, no-match
and ancestor/sample migration, corrupt cache, exclusive executor, explicit control,
duplicate/cross-attempt receipt, missing marker and missed-wake discovery. At most
1000 simulated fixture POSTs total for author tests (virtual time), no actual POSTs;
maximum10minutes per affected test invocation. Retain failures and apply only
affected reruns. Independent QA declares its own fixtures on the exact frozen build,
with SRE operating the existing native wake cases. Real remaining-only526scope is
not executed until accepted mechanism/applicable QA and DE's fresh cache/scope binding.
