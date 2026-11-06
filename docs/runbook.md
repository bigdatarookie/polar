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
```

Create the password file outside the repository, mode 0600, using a generated
local password without putting its value in argv, Git or logs. This file is
mounted as a Compose secret; image layers contain no password. The DB's local
role is not a remotely exposed account. Changing a password file does not rotate
an already initialized PostgreSQL volume's password automatically.

Refuse preexisting `polar_fixture_*` volumes/networks unless labels and provenance
show they belong to this task. Inspect the rendered configuration before startup.
`POLAR_DB_VOLUME`, `POLAR_ARTIFACT_VOLUME`, `POLAR_EVALUATION_VOLUME`,
`POLAR_NETWORK` and `POLAR_API_PORT` allow explicit task-owned resources.

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
| Dataset discovery, max 10/page | GET `/v1/datasets?limit=10&offset=0` | `datasets` |
| Register original fixture bytes | POST `/v1/datasets` | `register FILE` (file accessible inside invocation) |
| Feature as-of/revision | GET `/v1/datasets/ID/features/marker?decision_at=2024-01-03T21%3A00%3A02Z` | API currently; no separate CLI selector |
| Search run metadata | GET `/v1/runs?limit=10&offset=0&dataset_id=ID` | `runs` |
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
DB/artifact volumes and network, imports metadata/artifacts, and starts only API
on 127.0.0.1:18081. No worker recomputation is allowed to mask a broken restore.
Normal task containers may be recreated against these explicitly selected fresh
volumes; source volumes remain intact. Record the generated restore resource map.
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
