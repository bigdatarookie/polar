# A8 calendar outer hosting

`python -m polar.calendar_hosting CONFIG_FILE ADMISSION_FILE` joins the fixed
calendar `research-preflight` or `research-run` CLI to the existing bounded Linux
`process_budget.supervise` and immutable `HistoryStore`. It accepts no arbitrary
command, export path, new scheduler, financial grant or retry policy. The existing
calendar FIRST_START/family registry and scientific authority remain unchanged.
Retained ORIGINAL admission is explicitly unavailable until a trusted external
physical/aggregate guard interface exists. Direct retained Service calls also
fail closed. A caller-supplied PID/environment or CERTIFIED JSON is not proof.
Invented preflight stays metadata-only; source values stay after FIRST_START.

## Required explicit admission

`polar.calendar-host-admission/1` describes required finite inputs. The implemented
consumer is INVENTED only; RETAINED is refused before writer/child even when a
caller claims certification. A real trusted SRE interface is unavailable and
this adapter does not manufacture one. The example shape is executable in
`tests/test_calendar_hosting.py:fixture`; `hosting_binding` defines the guard pin.
Fields are closed: schema, action (`PREFLIGHT` or `ORIGINAL`), config_sha256,
artifact_root_identity (path/device/inode), actor_uid/gid, runtime_image_id,
limits, physical, export_bytes. Config is canonical-hash pinned, current-code
bound, and copied into an immutable hosting directory before launching. The
child receives that immutable config copy. There is no environment/PID capability
or self-issued guard handoff. The earlier PID check was rejected in review and
removed; the forged-envelope regression preserves that failure.

Every limit is a required positive integer: wall_seconds, cpu_seconds,
outer_wall_seconds, outer_cpu_seconds, cleanup_seconds, poll_seconds, rss_bytes,
store_growth_bytes, output_bytes, journal_bytes, receipt_bytes,
metadata_inflight_bytes, concurrent_growth_bytes, host_log_bytes,
docker_log_bytes. Output and receipts must fit the existing per-member bound.
Outer wall exceeds child wall plus cleanup and outer CPU covers child CPU.
These are caller-selected finite allowances, not defaults, measured peaks or a
new planning budget. The external guard must enforce the outer parent/collector
allowances; the local supervisor enforces the child tree's selected bounds.
RSS is sampled and does not replace a hard cgroup memory limit.

Physical metadata requires status CERTIFIED (INVENTED_TEST_ONLY only for invented
controls), measured_ns, valid_until_ns covering the complete outer allowance,
project_ceiling_bytes (at most the existing 64GiB policy), project_used_upper_bytes,
allocated_growth_upper_bytes, unknown_owners_included=true,
unique_backing_accounting=true, and guard_ref (path/sha256/bytes).
The new allocation must cover the sum of all selected growth/log/journal/receipt/
metadata/inflight/concurrent allowances and fit the supplied physical headroom.
Store/staging are counted together through existing used()/publication, not
charged twice. In this finite interface exports are explicitly disabled:
export_bytes must be integer zero. A later export or saved verification requires
its own explicit hosting/allocation; this interface does not grant either.

The guard ref is a `polar.calendar-host-guard/1` receipt with status
ACTIVE_ENFORCED (INVENTED_TEST_ONLY for controls), binding_sha256 of the whole
admission except the guard ref itself, root_identity, allocated_growth_upper_bytes,
valid_until_ns, guard_id, and exact coverage: parent, store, staging, supervision,
collector, host_logs, docker_logs, concurrent_writers, metadata_inflight.
For future retained use, actual runtime/root/actor/prior, finite cgroup CPU/RAM,
all-writer physical allocation, outer parent/collector limits and a trusted guard
issuer/interface remain required resources. Those interfaces are NOT implemented
or installed here. Strings, hashes, PID, cgroup equality and Docker rotation flags
do not authenticate aggregate guard custody. Both hosting prepare and direct
retained Service run fail closed while that interface is unavailable. Enabling
retained integration requires the actual guard resource and affected source
integration; this is not a financial admission or a scientific finding. Independent
metadata and research work continue.

## Bounded consumer and failure

For the invented consumer, the existing root lock encloses admission recheck and immutable config/admission
publication. Before launching, the adapter reserves selected receipt capacity
including collection; insufficient capacity rejects without a child. The child
gets an absolute logical store limit calculated from current usage plus selected
store growth. Other existing writers remain in the external guard's mandatory
coverage; the local lock is not a project-wide physical reservation.

Combined stdout/stderr and the resource journal are streamed with the existing
exact stored-byte caps and bounded non-detaching process-tree cleanup. Collection
reads only the capped console file, extracts a small status/semantic-ID summary,
and publishes one immutable bounded collection receipt. No full private export,
second collector copy, source reread, or regenerated financial finish is created.
Unexpectedly large process receipts degrade to a small FAILED_UNFINALIZED
collection instead of overrunning the selected receipt cap. Filesystem I/O errors
may leave only the immutable config/admission and completed witnesses/log prefix;
the wrapper does not delete or retry them. Parent I/O time and all external
writers require the supplied external guard; local logical limits are not a
physical peak guarantee.

On kill/quota/output/wall failure the result is FAILED_UNFINALIZED, refund=false,
automatic_retry=false, scientific frontier UNKNOWN_USE_DURABLE_CALENDAR_WITNESSES.
It preserves completed calendar witnesses/partials and the original conservative
debit, rather than declaring missing counters zero or manufacturing SUCCESS.
Existing failed original attempts cannot be restarted by a new hosting UUID.
The hosting directory is diagnostics, not a second scientific registry.

## Verification scope

Tests use invented metadata, an actual calendar CLI metadata preflight child, and
explicitly identified nonfinancial surrogate pressure children through the same
outer supervisor/store/collector path. They exercise fail-closed unknown/expired/
insufficient allocation, changed guard/config/actor, bounded output and wall
cleanup, store refusal with completed-record preservation, and immutable bounded
collection, plus rejection of a forged environment/parent-PID envelope.
No retained values, original scientific attempt, native financial
run, resource deletion, serving reconfiguration or physical admission is tested
or claimed. Existing calendar scientific tests remain separate technical controls.
