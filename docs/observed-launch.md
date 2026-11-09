# Runtime-observed Docker launch

`node scripts/polar-local.mjs docker CONFIG NEW_PRIVATE_DIR` creates one local task container, observes engine identity before scenarios, publishes one immutable preparation receipt, and starts that **same full container ID** only when the comparison succeeds. There is no image pull, build, provider, database or shared-service operation. It uses a network-disabled, read-only container, an explicit configured user and dropped capabilities. No compute-slot or approval token is introduced.

This first interface runs a declared interpreter on a hash-bound harness. Its exact argument vector is:

```
ENTRYPOINT HARNESS_PATH INPUT_PATH EXPECTATIONS_PATH CONFIG_PATH /polar-output
```

The six referenced files are copied to sealed task-private staging after byte/hash verification, then individually mounted read-only at their declared paths. `/polar-output` is the only writable scenario mount; it is0777 inside the container to support the configured user, behind the0700 private host output root. Do not place credentials in these nonsecret binding files or commands. The caller's original files are not modified. Each file is bounded to1MiB; output and captured command metadata are bounded. These are invocation bounds, not project resource quotas. Scenario code is trusted/reviewed task code; Docker daemon administrators and hostile concurrent owners are outside this isolation claim.

## Configuration

Strict schema `polar.observed-launch-config/1`:

```json
{
  "schema": "polar.observed-launch-config/1",
  "launch_id": "<fresh UUIDv4>",
  "candidate": {"commit": "<40hex>", "tree": "<40hex>"},
  "image_id": "sha256:<64hex expected local engine image ID>",
  "runtime_image_id": "sha256:<64hex local image requested for creation>",
  "platform": "linux/arm64",
  "user": "10001",
  "entrypoint": "/usr/local/bin/python3",
  "environment": {"PYTHONDONTWRITEBYTECODE": "1"},
  "refs": {
    "source_build": {"path": "/absolute/build.json", "sha256": "<64hex>"},
    "harness": {"path": "/absolute/check.py", "sha256": "<64hex>"},
    "input": {"path": "/absolute/input.json", "sha256": "<64hex>"},
    "expectations": {"path": "/absolute/expectations.json", "sha256": "<64hex>"},
    "config": {"path": "/absolute/scenario.json", "sha256": "<64hex>"},
    "review": {"path": "/absolute/existing-review.md", "sha256": "<64hex>"}
  },
  "build_fields": {"commit": ["commit"], "tree": ["tree"], "image_id": ["image_id"]},
  "scenario_timeout_ms": 30000
}
```

Expected and requested image IDs have separate meanings: creating image A while expecting B must produce a truthful mismatch receipt, never change the expected ID to A. Tags and registry manifest digests are unsupported identity types; resolve a local immutable expected ID explicitly before invocation. `build_fields` names bounded key paths in the referenced JSON composition/build receipt; those values must equal expected commit/tree/image. Byte hashes and these fields are verified. Schema /1 does **not** inspect packaged source or reconstruct compiler provenance. Existing independent review/composition evidence remains responsible for that claim. Source overlays are unsupported and never implicitly mounted; unrecognized configuration fields fail closed. Use existing exact source export separately where applicable, without claiming the image ID proves its contents.

`review` is an existing applicable independent non-author review reference, checked by exact bytes/hash. The launcher records it; it does not interpret arbitrary Markdown, authenticate reviewers, adjudicate scientific fitness or create another approval system. Task/QA custody must establish review applicability before product scenarios. A rejected or materially changed executable harness must receive independent review of the correction first. Tool author smoke uses only invented synthetic commands and is not tool acceptance.

All paths must be absolute canonical regular files with no symlink aliases, control characters or comma mount syntax. The six reference paths must be distinct. Output parent must already be canonical/private; a new output root is created0700. Never point this command at an owner environment. Empty/missing/ambiguous bindings fail before scenario execution.

## Observation and receipts

`preparation.json` is canonical, fsynced and published by no-clobber hard link before `docker start --attach FULL_ID`. It records producer file hash, launch/config/root identity, expected candidate/image/reference bindings, engine identity, actual container `.Image`, referenced image OS/architecture, configured user, effective entrypoint/command, safe environment, creation/observation/comparison/publication times, ownership and preparation state. Configured user is not an observed process UID: `process_uid` remains null. Expected-image comparison uses `.Image`, never `.Config.Image` or a revision environment variable.

Only `TZ`, `LANG`, `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED` and `POLAR_CODE_REVISION` may be configured, with bounded nonsecret formats. Only those declared keys are extracted from engine environment. Other values/names are omitted; unexpected effective command/environment values are redacted rather than persisted or hashed. DSNs, tokens, cookies, source/config bodies and full engine inspect output are never receipt fields. Scenario stdout/stderr contents are not retained by the launcher, only their byte counts. Trusted scenario artifacts stay in the private output directory.

Missing observation, engine error, source/reference mismatch or actual image/config mismatch yields `NOT_PREPARED`, a precise safe reason, and zero scenario starts. Available partial resource IDs are retained. Preparation failure is not a candidate scenario FAIL. No automatic retry changes an expected value or starts a scenario again. Invalid foreign/unowned output paths return a bounded failure without writing into them; an immutable receipt cannot safely be created there.

`result.json` references the single preparation receipt path/hash and records scenario start/finish, exit/timeout state and cleanup. It does not recopy observed identity. Preparation is not QA or financial PASS. Scenario output flooding/timeout becomes scenario FAIL; exact-owned cleanup still runs. Child CPU/RSS/global availability enforcement is not claimed. A bounded Docker CLI timeout alone does not prove a container stopped: cleanup records the actual owned removal, or `UNVERIFIED_RETAINED` / `UNKNOWN_CREATE_OUTCOME` when observation is unavailable.

## Reconciliation and cleanup

Repeating the same launch/config/root reads and verifies its immutable completed result without engine calls or another scenario. Changed config, reference bytes, root identity or conflicting existing receipt fails closed, preserving the original. Incomplete result state cannot automatically rerun a scenario. Launch binding includes the canonical output root, so identical launch UUIDs in different roots cannot adopt one another's resources.

```
node scripts/polar-local.mjs docker-cleanup ORIGINAL_CONFIG PRIVATE_DIR
```

Explicit cleanup checks the original config/root binding, exact resource IDs/name and both labels before removal. Original input/harness bytes need not remain available for cleanup; the original config and private ownership evidence must. Ambiguous create outcome is reconciled by exact unique name, full ID and matching binding labels; a different root/foreign binding is never removed. Every cleanup emits its own immutable receipt, retaining prior results. Already removed resources return `ALREADY_ABSENT`. No prune, broad process kill, shared project or volume cleanup occurs. Unverifiable cleanup returns failure and retains evidence for the owning operator. Source/reference staging and receipts are retained, not recursively deleted.

## Qualification

Author components cover ordering, identity mismatch, absent observation, immutable publication, redaction, changed refs, unknown create outcome and root-specific ownership/cleanup. Author real smoke is synthetic only. Independent Code/System must qualify the exact frozen revision against real engine observations, including correct match, deliberately wrong expected image with zero marker, inspection/publication failure, exact cleanup and no owner interference. Do not infer runtime acceptance from this documentation or component tests, and do not repeat unrelated browser/Gym/financial checks.

## Packaged source observation (launcher 2 / config 2)

Set the same configuration fields with schema `polar.observed-launch-config/2`. The hash-bound source_build JSON must additionally contain `source_files`, the complete map of eligible packaged files under `/app/src/polar`: absolute canonical path to exactly `{sha256, bytes}`. Eligible suffixes are `.py`, `.json`, `.sql`, including nested package resources. Limit 500 files, 1 MiB per file, 16 MiB total eligible bytes, and the existing 1 MiB build receipt bound. Keep large inherited dependency maps in separately hash-bound evidence rather than this receipt.

Before starting the same full container ID, the parent copies its packaged directory as a bounded (32 MiB) tar stream, hashes eligible regular files in memory without extraction, and rejects changed/missing/extra eligible files, duplicate/escaping paths, symlinks, hardlinks and other nonregular entries. A malformed archive fails closed. Reference mounts cannot overlap source, `/polar-launch`, or `/polar-output`; overlays remain unsupported. Source maps bind bytes, not source correctness or compiler provenance.

The immutable preparation receipt includes `source_binding.packaged_source_independently_observed=true`, `observed_container_id`, and `observed_files` equal to the build map. The identical receipt bytes are exposed read-only at `/polar-launch/preparation.json` before start. The dedicated mounted directory is 0555 and file 0444, independently of the host root 0700 and private receipt 0600. The launcher verifies exact copy hashes; it observes configured user, while the consumer still verifies its actual UID/import origin and visible files. Preparation never imports candidate code.

Legacy config /1 keeps its prior reference-only behavior. Source-boundary author tests use disposable shims; real-engine and consumer qualification belong to independent QA before adoption. No OBS158 native invocation is authorized by this interface change.

## Pre-start receipt mount observation (launcher 2.1)

Host chmod does not prove container-visible mode bits. For config /2, after
publishing the read-only visible candidate receipt, the parent reads a bounded
archive of `/polar-launch` from the same still-created full container ID. It does
not execute a process. The archive must contain exactly the directory and one
regular `preparation.json`, without links or extra entries. Directory mode0555,
file mode0444 and exact receipt-byte hash must match before the canonical host
preparation is published and before `docker start`.

The final immutable `result.json` retains `prestart_receipt_mount`: observed
container ID/time, directory and file modes separately, file bytes/hash, and
individual directory-mode/file-mode/content matches. This observation is kept
outside the receipt whose hash it measures, avoiding a self-reference. A mismatch
publishes canonical NOT_PREPARED and starts no scenario, with distinct
PREPARATION_DIRECTORY_MODE_MISMATCH, PREPARATION_FILE_MODE_MISMATCH or
PREPARATION_MOUNT_CONTENT_MISMATCH. Copy/archive/file-set failures also fail closed.
Cleanup remains exact-owned. A visible candidate copy created during a failed
preparation is retained evidence, not independent launch authorization; the
canonical preparation and final result remain authoritative.

This records stopped-container archive metadata. It does not establish why an
earlier process saw different modes, or replace applicable runtime consumer
stat/readability checks. The original610fd3d System mode FAIL remains unchanged;
whether its directory or file differed and the reason remain unlocalized.
The mode contract and frozen consumer expectations have not been relaxed. A new
real-container invocation requires its separately recorded execution continuation
after independent review of changed source/harness. No runtime or native PASS is
implied by this source correction or its prospective component fixtures.

## Mount-root initialization correction (launcher 2.2)

The later 2de4679 qualification observed directory0700, file0444 and matching
receipt bytes in the stopped-container archive. The guard returned
NOT_PREPARED/PREPARATION_DIRECTORY_MODE_MISMATCH without starting the consumer.
That FAIL is retained; process-visible stat/readability remained NOT RUN.

The earlier source created the bind root0700 before container creation and only
changed it to0555 after receipt publication. The corrected source explicitly sets
0555 before `docker create`, including under a restrictive caller umask. For
atomic publication it temporarily enables host-owner write (0755) inside the
private0700 output root while the container is still created, then restores0555
in a `finally` block. File0444, the stopped-container archive checks and the
independent UID10001 consumer requirements are unchanged.

Docker29.8.0 source archives a temporary mounted container filesystem view;
it does not execute the consumer's stat/readability checks. The source ordering
and observed initial mode support this bounded correction, but the mechanism
which retained0700 despite later host chmod is UNVERIFIED. Neither a Docker
Desktop projection defect nor successful runtime correction is asserted.
Prospective fake-engine coverage retains the bind-root mode observed at create
instead of supplying a constant0555, and checks restrictive umask and failed
publication restoration. These fixtures are not a substitute for the separately
authorized actual consumer qualification after independent review.
# Retained files and persistent artifact output (config3)

`polar.observed-launch-config/3` extends the same observed launch/cleanup path.
Config1/config2 retain their fields and behavior. Config3 additionally requires:

```json
{
  "retained": {
    "read_only": [
      {"path":"/absolute/source/file","target":"/original/container/file","sha256":"64_HEX_SHA256","bytes":123}
    ],
    "artifact_root": {"path":"/private/task/artifacts","device":"DEVICE_NUMBER","inode":"INODE_NUMBER"}
  }
}
```

The caller creates and reconciles the persistent root once, under a private
caller-owned parent. Record device/inode from `stat(...,{bigint:true})`; the root
must be a caller-owned real directory writable by the configured unprivileged
container user (the current portable check requires the other-write bit).
The launcher never creates, chmods, resets or deletes that root or its ledger.
The separate physical launch output must not overlap it. Runner authorization
and the operational owner remain responsible for the same scientific family,
original ledger and retained-start limit across physical launches and repairs.
This tool adds no counter store or experiment policy.

Selected input files are streamed in 64-KiB chunks into private, sealed per-launch
staging, checked against exact byte count/SHA256, then mounted individually RO at
their original absolute targets. No host directory/home/credential-store mount
is added. The caller must supply only its authorized private read set. An exact
existing six-ref alias reuses that already verified mount; conflicting aliases,
duplicate/overlapping targets and application/entrypoint/preparation/output
overlays fail closed. The bounds are 512 files, 256 MiB per file and 1 GiB total
per invocation; these are streaming/path-complexity bounds, not a new task storage
entitlement. The shared host storage policy still applies to staging plus output.

`/polar-artifacts` is the sole additional RW target. The existing harness argument
contract is unchanged: pass this root and the declared finite storage size to the
existing runner/CLI through its reviewed config. No new environment variables,
network access, engine or command dispatcher are introduced. The automatic
pre-start receipt includes original file references/hashes, persistent-root
identity and the exact effective bind-mount graph observed from the same stopped
container. Image, packaged source and readable preparation-receipt checks remain.
The root identity and staged bytes are rechecked before start. An unexpected
mount/direction/identity or changed content prevents scenario start. Cleanup still
removes only the observed owned container and keeps all host artifacts/inputs.

Independent qualification should use invented files and a stdlib writer across
two physical launches to observe RO inputs, UID/readability, persistent writes,
automatic binding and exact cleanup. No retained data or native engine is needed
to qualify this mount seam. Source tests are not that actual Docker proof.
