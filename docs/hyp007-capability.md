# Fixed HYP007 engineering capability

This is the selected HYP007_FIXED_SCORE_CAPABILITY_V1 implementation, separate
from the earlier diagnostic/nine-fit family and the 2019 Gym. Its only financial
label is INSUFFICIENT_EVIDENCE_ENGINEERING_CAPABILITY; original HYP007 adoption
remains NOT_ASSESSED. There is no HTTP route, scheduler, generic strategy plugin,
learner import, fit, prediction, transformation, source fetch or live trading.

Existing Service exposes hyp007_capability_prepare(config), run(sealed_config),
replay(sealed_config, packet_id), attempt(attempt_id) and report(packet_id), with
the hyp007_capability_ prefix on all five names. A caller must provide the full
closed polar.hyp007-capability-config/1 object. Unknown fields reject.
capability_service.CONFIG_FIELDS defines the closed field set.

## Configuration and preparation

The config binds schema/profile_id, mode (RETAINED or TECHNICAL_FIXTURE),
technical_case (null for retained), canonical family_root, immutable external
execution_authorization {assignment_id,sha256}, protocol_refs, input_refs,
auxiliary_refs, code, build_ref, runtime_refs, expected_image_id and launch.
All ordinary refs are {path,record_token,sha256}; semantic refs omit physical
paths. Record tokens are stable protocol identities, not content-dependent
attempt IDs.

protocol_refs has proposal_v1, disposition_v2, implementation_contract and
semantic_schema; exact accepted hashes are fixed in source. input_refs has
score_seal, score_manifest, capsule_manifest, capsule_readiness, raw_manifest,
actions_manifest, calendar and tzdata. auxiliary_refs enumerates the permitted
exact-byte lineage files, including the operand inventory, normalized/raw source
bodies, feature panel, prediction lines, fit receipts and inert model/transform
JSON. No filename suffix grants permission to open another file. Paths must be
canonical absolute ASCII paths; hashes are exact bytes. The fixed reader joins
witness/key/date/method identities and checks source lines and raw body ordinals;
it does not reconstruct scores, features, labels or economic identities.

code has accepted_commit, accepted_tree and source_projection. The projection
has schema polar.capability-source-projection/1 and files mapping the exact
SOURCE_FILES paths to SHA256. The schema's accepted_* field names are preserved
during invented candidate qualification; those candidate pins do not themselves
claim a production merge. build_ref is the exact source/image assembly receipt.
runtime_refs has packages_ref and api_lock_ref.

launch has tool_ref (accepted polar-local.mjs), observer_ref (its adjacent
polar-docker.mjs), harness_ref (scripts/polar_capability_worker.py), review_ref,
expectations_ref, source_build_ref (equal to build_ref) and build_fields.
build_fields contains commit/tree/image_id paths inside the assembly receipt,
using the qualified launcher's existing interface. Source code does not copy an
expected image into an observed field.

prepare is STATIC_ONLY on successful metadata admission. It verifies source,
protocol, build, reviewed launch refs and pre-provisioned family registration.
It does not open score/capsule numeric members, restore a float, rank, allocate,
construct native state, compute metrics, reserve starts or spawn a child.
An absent/unbound registration returns NOT_PREPARED; prepare never provisions it.

## Trusted registration and irreversible charges

The Service-owned anchor is /var/lib/polar/hyp007-capability-registry and cannot
be selected by a public caller. It must already exist, canonical/private, outside
the artifact root. Explicit administrative provisioning is separate from
prepare/run and requires prospective authority. This implementation has not
provisioned a retained family or execution assignment.

The anchor's immutable anchor.json has schema polar.capability-anchor/1 and its
path/device/inode descriptor. assignments/ID.json has schema
polar.capability-execution-assignment/1, family_id, mode, bindings (the entire
config except its authorization ref), qa_refs (hash-verified refs including the
launch review), granted_at_ns, input_classification (INVENTED or RETAINED) and
approved_input_hashes (all exact input/auxiliary hashes). These are externally
provisioned authority, not a caller approval string. Technical classification is
not inferred from a filename or allowed to relabel retained inputs.

The private administrative FamilyStore.provision operation creates a no-clobber
registration tombstone outside families/KEY, then a bound immutable header and
cache. Interrupted provisioning cannot silently retry from zero. Missing/moved
root or lost family storage requires reconciliation; it is never initialized by
run. Retained uses exactly one fixed family key regardless of input/config/code.

Append-only hash-chained START records precede dependent input validation;
ACCOUNT records precede each engine constructor, including failed constructors.
Seven accounts are charged in profile order. Original failure, interruption or
an unfinalized start prevents replay/replacement; only a successful original
permits its one replay. Resources and all failure records remain. The mutable
projection is a checked prefix cache, never the source of remaining budget.

Technical cases additionally share the pre-provisioned qualification directory,
with its own immutable polar.capability-qualification/1 header and checked
projection. Header fields are family_id, authorization_sha256 and ceilings:
6 starts,20 account constructions,600000000 CPU microseconds,
900000000000 wall nanoseconds and300000000000 native nanoseconds. Each case
root still has its two-start/fourteen-account ceiling. Cross-record crash windows
and lost projection/accounting fail closed. The fake storage cases in author
tests use isolated invented registry fixtures; their simulated counters are not
real native constructions or the retained registry.

## Execution and resource evidence

After START, a supervised host child reads and validates admitted packet inputs,
restores the20 bit/hex/token-agreed scores and calls the public mapper once.
Its output contains only the fixed targets, score metadata and two opens/five
closes. No Jan4 close sizing input or Jan12 future HLCV reaches the engine.

The host composes the accepted PR30 observed launcher. It supplies six pinned
read-only files, a complete immutable application image, reviewed installed
harness and fresh output root. Both launcher module hashes are verified.
The immutable preparation receipt must independently match the actual same
container's image/platform/user/command/environment and exact reference graph.
Missing/mismatched observation is a spent Service failure before native accounts.

The worker requests each account through bounded output-directory IPC. The host
fsyncs its authoritative charge, then publishes a hash-bound read-only ack.
Only after that ack may a fresh Nautilus1.231.0 engine be constructed. This is
deterministic application IPC, not an agent work queue.

CPU admission uses a documented conservative capacity upper bound, not an
unsupported claim to exact final container CPU. Host logical CPUs bound all host
supervisor/descendant CPU over monotonic attempt wall; Docker info's observed
logical CPU count bounds all guest descendants during the owned launch interval.
The engine ID must match the launch receipt. The sum is charged without refunds,
with measured process CPU retained separately as a lower bound. This may stop
earlier than actual CPU exhaustion; it never enlarges the600CPU allowance.
Missing capacity or unverified cleanup makes resource evidence INCOMPLETE and
remaining budget unknown. resource-bound.json records this distinction. Attempt
wall includes preprocessing, native supervision and exact-owned cleanup; idle
days between attempts do not count. Native intervals include construction,
engine run and disposal, summed across all seven accounts.

Only the owned launcher process group can be terminated. Container cleanup is
delegated to the accepted launcher's exact-ID/label checks and must independently
report REMOVED/ALREADY_ABSENT. No prune, unrelated process signal or owner runtime
operation is implemented. CPU/wall/native ceilings are family cumulative; a
timeout/crash cannot be used to obtain a fresh start.

## Native and semantic boundaries

Each account starts with100000.00USD and fresh fee/fill/latency state. Native
prices are exact cents represented with4dp, whole quantities, USD1 actual
OrderFilled commission per nonzero filled order. No affordability resizing.
Entry and exit each call public allocate once for every account, including cash.
Sparse marks are exactly held union targets. Quote Q+0..3ns is distinct from
Snapshot Q+1000ns; nonzero routes are densely Q+2000..5000ns.

All actual native callbacks and order/fill/fee ID maps remain physical.
Native account cash is checked after the queued account callback settles, before
the next route/sample; event timestamps are retained, never shifted.
Seven samples retain all four quantities; zero holdings have the predeclared
null mark projection. Positive held marks and exact native exposure must agree.
The exact integer/rational evaluator replays the fixed filled tape and verifies
cash/positions, samples, fees, times and terminal liquidation.

The eight typed semantic files and external manifest are canonical, immutable,
and whole-graph verified before family SUCCESS. Packet ID is the manifest hash.
Replay reruns ranking/native stages and must publish identical semantic bytes;
attempt IDs, receipt bytes, resource times and native IDs remain physical.
The actually observed image digest remains semantic. report verifies physical
finish references as well as all semantic bytes; orphan semantic files are not
successful experiments.

## Qualification state

The first author attempt ran26 invented pure cases and6 fake registry cases:
27 passed,5 failed. Failure artifacts and the prospective source/expectation
binding are retained outside Git. The mismatches were joined account-intent
shape and the exact ORDER_FILLED_COMMISSION discriminator. Source and fixture
representation were corrected without changing the schema, financial
expectations or original failure record.

No corrected harness invocation is claimed here: independent non-author review
must precede its next invocation. No author native constructor, retained operand
read/execution, real family registration, provider or financial run occurred.
Full schema meta-validation and full native original/replay qualification remain
NOT RUN until their actual independent evidence. The local validator implements
the exact hash-pinned schema's keywords; it is not a general JSON Schema engine.

## Current v0.27 technical execution authority

TECHNICAL_FIXTURE assignments retain their exact invented-input hashes, review
references, registered roots/configuration, irreversible original/replay lifecycle,
seven-account packet order and immutable resource/charge history. The historical
qualification header and allocation counters remain intact, but their global
starts/accounts/CPU/wall/native pools no longer admit or reject technical checks.
A failed or unfinished family still cannot retry or overwrite its original; this
is record integrity, not a global fixture allowance. Retained-input family limits
and separate scientific authorization are unchanged.

Technical supervision keeps the existing 900-second individual operation hang
timeout, including reserved bounded owned cleanup. Historical technical wall usage
is recorded without subtracting it from a later operation's timeout. The launcher
keeps its individual <=300-second scenario timeout. Cumulative technical CPU and
native-interval usage are still recorded monotonically but do not impose a share
quota. Queue/review wait does not start either operation clock. Missing cleanup,
image/source mismatch, corrupted history or incomplete resource evidence still
prevents success; no unknown history is reset to zero.

The external QA qa_guard_v41 / guard-binding-v41 execution-share gate is obsolete
for technical admission. Its original source/results remain historical. The
corresponding system-runner-v41 caller contains Gate.begin/finish phase handshakes
and frozen capacity/share assumptions; it cannot simply be launched unchanged.
QA owns removing those obsolete handshakes and rebinding the exact corrected
candidate/image/config/fixture, preserving numerical comparison and cleanup
criteria, with nonauthor review of a materially changed native harness before
invocation. This source correction does not grant any native or retained run.
