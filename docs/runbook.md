# Local fixture runbook

SRE operates the reviewed exact candidate. Preserve owner checkout `test.txt`
deletion and untracked `AGENTS.md`. Do not reset/start Docker Desktop or replace
the owner's runtime as part of source checks. Resolve that operation explicitly
at candidate freeze; inspect existing containers/volumes and port 18080 before
any service startup. Never stop another project to free a port.

## Configuration and startup

Use the assigned implementation worktree. Set the following in the invoking
shell or an ignored task environment file; `.env.example` contains no secrets:

```sh
export POLAR_CODE_REVISION="$(git rev-parse HEAD)"
export POLAR_IMAGE_TAG="fixture-$POLAR_CODE_REVISION"
export POLAR_DB_PASSWORD_PATH=/private/tmp/polar-bootstrap-secrets/db_password
export POLAR_EVALUATOR_INPUT=/private/tmp/polar-selected-evaluator-input
export POLAR_NETWORK=polar_fixture_service
export POLAR_API_NETWORK=polar_fixture_api
```

Create the password file outside the repository, mode 0600, using a generated
local password without putting its value in argv, Git or logs. This file is
mounted as a Compose secret; image layers contain no password. The DB's local
role is not a remotely exposed account. Changing a password file does not rotate
an already initialized PostgreSQL volume's password automatically.

Refuse preexisting `polar_fixture_*` volumes/networks unless labels and provenance
show they belong to this task. Inspect the rendered configuration before startup.
`POLAR_DB_VOLUME`, `POLAR_ARTIFACT_VOLUME`, `POLAR_EVALUATION_VOLUME`,
`POLAR_NETWORK`, `POLAR_API_NETWORK` and `POLAR_API_PORT` allow explicit task-owned
resources. Choose fresh task-owned names for both networks; preserve existing
resources and diagnostic networks.

DB, worker and migration use only the private internal service network. API also
joins its own normal bridge for host port publishing, while its published binding
remains 127.0.0.1 only. This API bridge permits outbound connectivity; the API is
not internal-only. Evaluator and artifact helpers retain network_mode:none.
See Docker's [internal network documentation](https://docs.docker.com/compose/how-tos/networking/#internal-networks)
and [loopback port publishing](https://docs.docker.com/engine/network/port-publishing/).
Validate actual host HTTP reachability after startup; successful Compose parsing
or an in-container health check does not prove the host path.

```sh
docker compose -p polar config --quiet
docker compose -p polar build api
docker compose -p polar up -d --wait db
docker compose -p polar run --rm --no-deps migrate
docker compose -p polar up -d api worker
curl --fail http://127.0.0.1:18080/livez
curl --fail http://127.0.0.1:18080/readyz
```

Run migration once under its PostgreSQL advisory transaction lock, never from all
workers at startup. Schema 1 is additive bootstrap; an incompatible existing
schema is a blocker. This migration is not a general major-version upgrade or a
destructive rollback. Preserve the previous commit/image/schema and data before
an update; app rollback does not undo a schema change.

## Strategy → saved report

Generate the artificial fixture and fixed accounting tape outside the repo:

```sh
uv run --locked python scripts/fixture.py /private/tmp/polar-fixture-inputs
curl --fail -H 'Content-Type: application/json' --data-binary @/private/tmp/polar-fixture-inputs/fixture.json http://127.0.0.1:18080/v1/datasets
curl --fail -H 'Content-Type: application/json' -H 'Idempotency-Key: fixture-base-v1' --data-binary @/private/tmp/polar-fixture-inputs/config.json http://127.0.0.1:18080/v1/runs
```

Use the returned run UUID below. Query until terminal state with a bounded timeout
of at most 60s, rather than submitting a second run on an uncertain response:

```sh
curl --fail http://127.0.0.1:18080/v1/runs/RUN_UUID
curl --fail http://127.0.0.1:18080/v1/runs/RUN_UUID/report
docker compose -p polar exec -T api python -m polar.cli report RUN_UUID
curl --fail http://127.0.0.1:18080/v1/runs/RUN_UUID/evidence
```

The API and CLI both call `Service`/`Registry`; the CLI above reads the same DB
and artifact volume as the API. No re-computation occurs when reading a report.
The exact fixed protocol ID/hash is part of every config. Synthetic base NAVs are
1000, 1039, 1031, 1032, 1026, 1014 USD. This is arithmetic qualification, not alpha.
Repeating `fixture-base-v1` with the same payload returns the same logical run;
changed payload returns HTTP409. Do not change keys to bypass a quota.

Additional versioned operations:

| Purpose | API | CLI |
| --- | --- | --- |
| Dataset discovery, max 10/page | GET `/v1/datasets?limit=10&offset=0` | `datasets --limit 10 --offset 0` |
| Register original fixture bytes | POST `/v1/datasets` | `register FILE` (file accessible inside invocation) |
| Inspect retained dataset and source binding | GET `/v1/datasets/ID` | `dataset ID` |
| Feature as-of/revision | GET `/v1/datasets/ID/features/marker?decision_at=2024-01-03T21%3A00%3A02Z` | API currently; no separate CLI selector |
| Search run metadata | GET `/v1/runs?limit=10&offset=0&dataset_id=ID` | `runs --limit 10 --offset 0 --dataset-id ID` |
| Submit/status | POST `/v1/runs`; GET `/v1/runs/UUID` | `submit FILE --key KEY`; `status UUID` |
| Cancel | POST `/v1/runs/UUID/cancel` | `cancel UUID` |
| Report/evidence | GET `/v1/runs/UUID/report` or `/evidence` | `report UUID`; `evidence UUID` |
| Descriptive comparison | GET `/v1/compare?left=UUID&right=UUID` | `compare LEFT RIGHT` |

For a host CLI, set `POLAR_DATABASE_URL` through a protected environment only when
an isolated reachable PostgreSQL endpoint already exists. Default Compose DB has
no published port; use the container CLI. Never print the DSN. API uses local
loopback trust only; actor/qitem refs are attribution, not remote authentication.
There are no browser/CORS/UI or remote access claims.

## Lease, retry and publication

PostgreSQL serializes admission/claim. Only one run can be running. A job has a
15s lease with heartbeats; an expired worker attempt is retained as `lost` and
can be retried once with a new attempt UUID. A second loss fails terminally.
Deterministic invalid data is stored as an `INVALID` report, with null affected
metrics, without an infrastructure retry. Terminal records are immutable.

The supervised child includes calculation and artifact writes. It reserves 20s
of the 60s job envelope for bounded DB calls/finalization. Cancellation stops the
child; queued cancellation is immediate. Late output cannot finalize against
another attempt or an expired lease. Cancellation/lease races can retain orphaned
attempt directories; these are never exposed as complete reports or deleted
automatically. Partial directories are not final manifests. PostgreSQL completion
is the visibility boundary, after atomic publication, file/directory fsync and
manifest hashing. APIs verify both DB manifest binding and required file hashes.

At most 20 logical fixture jobs, one retry each; restarting services does not reset
admission. Lost/killed attempts reserve a full 60 CPU-seconds. Successful attempts
record child plus parent process CPU time. The fixed job/time ceilings bound
fixture computation conservatively; host CPU deltas, recovery CPU and overhead
must still be measured by SRE against the 60 CPU-minute mission envelope.

## Persistence and isolated recovery

At a quiescent boundary recreate only task API/worker containers, retain named
volumes, then read the original report through both surfaces without calculation.
Never use `down -v`, volume prune, or owner environment reset.

The following helpers are deliberately not run by source development. They check
task container/volume ownership and refuse active jobs or ambiguous resources:

```sh
python3 scripts/ops.py backup /private/tmp/polar-backup-UNIQUE
python3 scripts/ops.py restore /private/tmp/polar-backup-UNIQUE --suffix UNIQUE123
```

Backup stops API admission, requires no queued/running job, stops worker, creates
a DB logical dump and artifact tar with checksums. It leaves API/worker stopped.
It contains dataset versions, actual import times, configs, attempts, artifact
manifests, environment and native qitem/scope references. Budget includes backups.

Restore verifies checksums and **refuses existing restore-volume names**. It stops
only the named task services, keeps all source volumes, creates separately named
DB/artifact volumes, internal service network and API bridge, imports
metadata/artifacts, and starts only API
on 127.0.0.1:18081. No worker recomputation is allowed to mask a broken restore.
Normal task containers may be recreated against these explicitly selected fresh
volumes; source volumes remain intact. The generated restore resource map includes
POLAR_API_NETWORK as polar_restore_SUFFIX_api alongside its separate service
network, so restored API does not reuse the source bridge. Record that resource map.
Recheck port 18081 before running. Verify the original report/manifest through
API/CLI and compare bytes/hash to pre-backup evidence. Import success alone is
not restore acceptance. Preserve source and backup; no automatic cleanup exists.

## Evaluator and limits

Select one completed immutable run/attempt directory as
`POLAR_EVALUATOR_INPUT`; copy/mount only that directory read-only. Stop worker,
then use `python3 scripts/ops.py evaluate`. The helper refuses a running worker or
other helper; evaluator has no network, DB secret, Docker socket, holdout or
host-wide mount, and exclusive output creation preserves previous evaluations.
It checks artifact integrity only. It cannot issue the independent financial
verdict. Shared host/harness access means `BLINDING_NOT_ENFORCED`.

DB/API/worker caps total 2 CPU and 2304 MiB (768 MiB margin within 3 GiB). Evaluator
replaces worker. Helpers run serially with worker/evaluator stopped. Logs rotate
at 2×5MiB/service; tempfs is 64MiB/service; PID caps are 100. Inspect actual
HostConfig/cgroups and monitor task usage before claiming enforcement. Direct
Compose commands can bypass helper serialization; there is no hard host-wide
aggregate scheduler. Named volumes have no demonstrated hard disk boundary.
Admission checks DB+artifact size; SRE accounts for backups/logs/scratch and stops
before 4 GiB retained + 1 GiB scratch/logs. Report
`STORAGE_HARD_QUOTA_NOT_ENFORCED` until real enforcement is demonstrated.

## Read-only runtime inventory and custody

Run `python3 scripts/ops.py inventory --help` from the assigned checkout. Inventory
only reads Compose/Docker metadata and a bounded `BEGIN READ ONLY` PostgreSQL
projection; it never builds, starts, stops, migrates, restores, submits a job or
reads a secret file. No Docker or host installation is implied. It requires the
existing Docker CLI/Compose and selected task runtime. Run serially within the
Lead's assigned computation and environment-custody window.

Before inspection, obtain the current candidate, app image/revision, environment
owner and resource/backup handles through the native handoff. The selected host
tooling commit may differ from the accepted app image; do not rebuild the app to
make them equal. Preserve owner checkout changes and other QA's environment.

Use the existing configuration variables above and in `.env.example`, especially
`POLAR_DB_VOLUME`, `POLAR_ARTIFACT_VOLUME`, `POLAR_NETWORK`, `POLAR_API_NETWORK`,
`POLAR_API_PORT`, `POLAR_DB_PASSWORD_PATH`, `POLAR_EVALUATOR_INPUT`,
`POLAR_CODE_REVISION` and `POLAR_IMAGE_TAG`. Select the **existing** task resources,
secret-file path and observed app revision/tag from that handoff. Compose defaults
are not runtime discovery. For a restored environment, use its retained resource
map rather than silently selecting `polar_fixture_*`. Never regenerate the DB
password or print a DSN/environment. Inventory reads the rendered configuration
but emits only the allowlisted resource names/caps, not service environments.

With those ordinary Compose variables set, invoke directly, without a private
bootstrap wrapper (replace the uppercase values with the assigned exact hashes):

```sh
python3 scripts/ops.py inventory \
  --expected-app-revision APP_COMMIT_40_HEX \
  --expected-image-id sha256:APP_IMAGE_64_HEX \
  --output /private/tmp/polar-inventory-UNIQUE.json
```

The parent directory must exist; the absolute output must be a NEW file outside
Git, including other repositories. Existing files and symlinks are refused. The
file is created exclusively with mode0600 and bounded to64KiB; the command prints
only a fixed receipt/error code. No credential values, raw inspect/env, dataset
bodies, reports, logs or dumps are written. Commands have an8-second timeout and
2MiB captured-response limit, at most12 selected containers and exactly the three
core service projections. Inputs from labels are validated as hashes/revisions;
unknown labels/environment fields and subprocess error bodies are discarded.

Manifest `polar.runtime-inventory/1` separates:

- `selected_tooling`: actual Git commit/tree, operations-file hash and whether its
  bytes match that commit. Uncommitted tooling is explicitly distinguishable.
- `desired`: selected Compose-file hash, resource names and declared caps.
- `observed`: actual container/image IDs, validated revision labels, per-service
  Compose config hashes, states, mounts/networks, loopback port and Docker
  HostConfig caps; database schema version/checksum and bounded aggregate counts.
- `checks`: equality of declared/observed caps/maps and optional expected app
  revision/image. These comparisons do not compare the app with the tooling SHA.
- `limits`: hard storage `NOT_ENFORCED`, `BLINDING_NOT_ENFORCED`, incomplete global
  accounting and `NOT_RUN` kernel-cap/running-source-byte verification.

Successful collection is not a PASS verdict. Missing services or schema probes
remain `UNKNOWN`/`NOT_RUN`; do not substitute desired configuration. Failed app
revision/image/cap equality is retained as false. Wrong project/root/resource
ownership, duplicate core services or mismatched mounts/networks/loopback refuse
collection with a sanitized fixed error. A revision label or config hash alone
is not running-code proof, hard resource enforcement or acceptance. Inspection
is a timestamped observation, not an atomic snapshot across Docker and DB; a
candidate-scoped owner must exclude concurrent runtime changes.

To bind an existing backup handle, add `--backup-directory /absolute/backup-dir`.
Only the existing `backup-manifest.json` format is read: its file hash and
allowlisted declared dump/tar hashes are recorded. Inventory never opens or
copies dump/artifact bodies, verifies their content hashes, runs a restore or
claims that the backup includes later registrations. `file_verification` and
`restore_effect` stay `NOT_RUN`; `current_state_coverage` stays `UNKNOWN`. Keep
raw backup files protected outside Git and shared evidence. Backup/restore and
evaluator commands retain the operations and ownership checks documented above;
this flag is not authorization to execute them.

Custody handoff: send the manifest path/hash, tooling SHA, observed app image and
revision, owner/window, resource names and protected backup location through the
native queue. Explicitly state gaps, allowed operations and remaining manual
budget; never send secret contents or an environment dump. A receiver can use
these documented ordinary Compose variables and existing read-only CLI/API
operations to fetch one retained dataset identity and original report:

```sh
# Use the manifest's observed loopback port and the assigned retained IDs.
curl --fail http://127.0.0.1:PORT/v1/datasets/DATASET_ID
docker compose -p polar exec -T api python -m polar.cli dataset DATASET_ID
curl --fail http://127.0.0.1:PORT/v1/runs/RUN_UUID/report
docker compose -p polar exec -T api python -m polar.cli report RUN_UUID
```

Compare dataset canonical/source hashes and actual registration timestamp, then
report/manifest hashes and attempt history against the handed-over before-state.
Fetch report/evidence/status without recomputation; no new logical job is needed.
Reports contain financial rows: inspect locally, preserve only safe identity/hash
projections in shared proof. QA System independently records consumer effects;
author inventory does not accept itself. With one shared stack, serialize
conflicting restarts, migration, restore and revision changes between QA seats;
QA2 can prepare or run separately assigned independent work. Do not duplicate
full stacks or expand quotas automatically. A recreation requires separate Lead
authorization, original before-state and retained volumes; inventory never does it.

## Retained workspace UI

Open `/ui/` on the existing API origin for the selected read-only workspace. See
[retained-ui.md](retained-ui.md) for projection, status, controls and qualification
limits. GET-only selection/refresh creates no datasets or jobs. Image/browser
qualification requires a separately authorized candidate-scoped runtime slot.
