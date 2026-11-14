# A8 resource enforcement correspondence

This is a source/invented infrastructure contract, not an A8 operation allocation.
The accepted calendar Service/profile/scientific choice remains unchanged. No
retained preflight, source input read, scientific attempt or serving action is
selected here.

## Existing writer and outer supervisor

GymStore inherits HistoryStore._publish. The complete transaction is now checked
against the caller's per-file limit BEFORE any staging directory or writer is
opened. The existing root logical-byte quota check precedes staging, and immutable
publication/readback/locking remain unchanged. A caller must hold the existing
root lock. This prevents a large serialized member being written first and rejected
only by readback. It does not bound pre-serialization RAM.

The existing process_budget.supervise callable can contain the entire ordinary
calendar research-run process and its non-detaching descendants. Select ALL of
cpu_seconds, wall_seconds, rss_limit_bytes, max_output_bytes, max_journal_bytes,
cleanup_seconds and poll explicitly. Do not rely on legacy defaults. Output and
journal have enforced stored-byte caps; sampled RSS is an observation/stop trigger,
not a hard memory allocation limit. The actual cgroup/outer guard and current
host load remain SRE bindings. The enclosing parent must not copy unlimited
console output into another log or omit Docker logs from its accounting.

The new invented supervised consumer publishes three 32-byte records under a
96-byte logical store limit, then attempts a fourth. It requires a nonzero exit,
HISTORY_STORAGE_LIMIT, all three completed records intact, zero unpublished
staging, bounded combined stdout/stderr and resource journal, and complete owned
process cleanup. No native or financial input is involved in that consumer.
Existing bounded-supervisor tests exercise output pressure and other stop paths.

## Required actual hosting join (not populated by this document)

Use the single existing serialized scientific slot. Before an actual START, SRE
must bind current source/runtime, actor, RW root identity, prior state, selected
finite stage/cumulative/cleanup allowances and actual memory/CPU constraints.
The original native guard may be explicitly lowered to the selected allowance;
it is not a fit guarantee. QuantA must select any new operative allowance while
retaining all prior containing preparation time; this document supplies none.

Include the maximum simultaneously existing store and staging, ONE export,
external supervisor log and journal, collector outputs, Docker stdout/log bound,
filesystem allocation/metadata margin and maximum in-flight write. The per-file
check and root logical quota are necessary but do not independently certify
physical allocation or the project-wide ceiling. Avoid double counting staging
already included by the root walk; include a separate export only once. Completed
immutable records and useful partials survive stops. No retry reconstructs them.

The caller must provide a conservative physical upper bound for every new writer
including collector/export/host logging, and join it to a current certified
project usage upper before admission. UNKNOWN is not zero or certified headroom.
Serialization RAM, filesystem allocation granularity and external writers cannot
be inferred from a logical store byte count or Docker log rotation setting.

## Primary storage instrument result

The primary policy is one total Polar storage ceiling of 64 GiB (68719476736
bytes), not a RAM limit or independent category budgets. Existing scoped metadata
shows a shared Docker.raw allocation of 99517075456 bytes on the same Data
filesystem. Counting that backing once avoids adding image/container/cache
logical categories again; adding it to whole Data filesystem usage double counts.
Its size exceeds the policy ceiling but it is shared, so it proves neither Polar
usage nor a Polar breach. Counting all backing cannot supply a below-ceiling safe
bound. Existing image union already deduplicated diffIDs; do not subtract it again.

The unresolved boundary is physical Polar-attributable allocation in shared Docker
backing plus outside binds/host roots, with shared extents and relocated-backing
completeness. Existing Operator ownership work and SRE current resource custody
remain the owners; no second ownership survey or UNKNOWN exclusion is selected.
A physical project upper/headroom is NOT_CERTIFIED. The new local write guard
removes a real enforcement defect without representing this global gap as solved.

## Consumed B11 log-envelope correction

SRE's accepted-interface configuration consumer found an additional concrete
admission gap: log_bytes and journal_bytes are per supervise invocation, but the
previous admission summed one pair only. The same shared guard continuation now
uses a single phase census for time/cleanup and log envelopes: ORIGINAL reserves
four supervisors (original work/collector plus prospective success-only saved
work/collector), while a separately admitted SAVED stage reserves two against
current remaining root space/headroom. Prior actual usage is already in used().
This is a conservative logical admission sum, not a physical/global certification.
The root check now requires operation_store_bytes + calls*(log_bytes+journal_bytes).
It does not double a separately accounted export or enclose external host writers.

The two fully rehashed invented metadata negatives supply only one log pair of
available global/root space; they must reject before debit or encoded input read.
An exact four-pair boundary remains admissible metadata only, and the two/four
phase-census assertions prevent log and cleanup multipliers drifting apart.
Accepted PR134 and original PR13549 source evidence remain immutable predecessors;
the corrected actual application tuple needs its affected current qualification.
