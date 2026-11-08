# Disposable synthetic API liveness environment

This helper prepares one explicitly selected local image and immutable candidate
source overlay. It does not prepare a DB, owner data, provider access, job,
browser, learner, simulation, or full QA environment. Its only supported scenario
is `synthetic-api-liveness/1`: `/livez` must return ALIVE and `/openapi.json` must
be observed and hashed. DB readiness is `NOT_APPLICABLE`, QA verdict is `NOT_RUN`.
Independent runtime qualification is separate from this source implementation.

Use Python 3.13 and an already available local Docker image with Python,
uvicorn and the candidate's service dependencies. Images declaring Docker volumes
are unsupported. Nothing is pulled, built, installed, or automatically repaired.
Docker must use a local Unix socket. Explicit image selection authorizes executing
that image and candidate in the disposable task resources; use trusted candidates.

Create this config outside Git, replacing all example pins with actual values:

```json
{
  "schema": "polar.qa-environment-config/1",
  "scenario": "synthetic-api-liveness/1",
  "repository": "/absolute/canonical/polar/repository",
  "commit": "FULL_40_HEX_COMMIT",
  "tree": "FULL_40_HEX_TREE",
  "image_id": "sha256:FULL_64_HEX_IMAGE_ID",
  "source_schema_sha256": "FULL_64_HEX_SCHEMA_SQL_SHA256",
  "fixture": {
    "schema": "polar.qa-liveness-input/1",
    "synthetic": true,
    "dataset": "EMPTY",
    "artifacts": "EMPTY"
  }
}
```

```sh
python3.13 scripts/polar_qa.py prepare /absolute/config.json --root /private/tmp/NEW-qa-task
python3.13 scripts/polar_qa.py cleanup --root /private/tmp/NEW-qa-task --operation UUID_FROM_RESULT --config-sha256 SHA_FROM_RESULT
```

The root must be new, canonical, absolute, outside Git, with an existing parent
and no symlink ancestors. An existing owned root can be reconciled only with the
identical config. An unrelated existing root is rejected without modification.
Keep the root private; config and resource files are custody records, not signed
attestations against a hostile local owner. The CLI returns JSON and exit 0 for
PREPARED/CLEANED, 1 for NOT_PREPARED/NOT_CLEANED. Unsupported scenarios return a
concrete gap. No raw Docker output, HTTP body or credential is printed.

The result schema `polar.qa-environment-result/1` binds operation, config hash,
root, full container/network IDs, endpoint, image/commit/tree, source manifest,
schema and synthetic fixture hashes, observed OpenAPI hash, and readiness scope.
Root files are strict JSON: `owner.json` (`polar.qa-environment-owner/1`),
`config.json` (`polar.qa-environment-config/1`), and `state.json`
(`polar.qa-environment-state/1`). Every completed result is retained in an exclusive result-UUID.json file,
including failed setup/cleanup results. State retains its reference, the latest result, attempt count,
phase, actual resource IDs, local daemon socket, host observation and next safe
reconciliation evidence. These describe one environment; they are not an agent
work queue or controller. Native OpenRig retains work ownership.

Prepare exports exact Git objects using accepted `scripts/polar-local.mjs`, seals
source, verifies the file set and schema hash, and creates an empty artifact
mount. One unique internal bridge network and one unprivileged read-only container
use operation/config/root/candidate/role labels. The API receives only candidate
source RO, empty artifacts RO, tmpfs `/tmp`, inert loopback DSN, explicit absent
secret paths, no Linux capabilities and no-new-privileges. The helper publishes an
ephemeral port on 127.0.0.1 only. The image is explicit and remains installed;
no owner stack, credential, shared volume or Docker socket is mounted. Actual
Docker/host isolation properties still require the independent runtime check.

Identical prepare revalidates exact IDs, labels, configuration, source and empty
scope. It starts its own stopped container if needed. Partial failures retain
resources and IDs. A failure after Docker create but before ID persistence can be
recovered by the exact intended unique name plus verified identity/properties;
no new parallel stack is created. A recorded resource replaced or missing blocks
prepare. A damaged incomplete source export is retained and returns a gap; it is
not silently deleted/rebuilt. Use a new root after explicit exact resource cleanup
if source preparation cannot be reconciled. A cleaned operation never recreates
resources. There is no background retry/watch or automatic setup cleanup.

Cleanup requires the exact operation and config hash, validates all observed
resources before deleting either, and rejects foreign network endpoints. It
removes only verified full container and network IDs; missing resources are
idempotent only after successful bounded Docker listing. A daemon/inspect failure
is not treated as absence. No prune, name-only removal, image/volume removal or
root/source/evidence deletion occurs. Keep receipts and failures for review.
The ownership lock serializes invocations of this helper; Docker administrative
changes by other actors remain an external race and must be coordinated.

Bounds: config 64KiB, state/individual command output/HTTP body 1MiB, CLI result
64KiB, accepted source-export total under 16MiB, up to 2000 exported files/4000
walk entries, command 30s, readiness 30s with 2s per HTTP request, invocation command/probe budget 180s plus up to 2s for probe-child cleanup.
Each HTTP probe has a separate reaped process and hard 5s bound (2s request
timeouts); slow streaming cannot hold the main invocation indefinitely.
One create per resource per invocation; same-config retries are caller invoked
and counted. Host load/CPU/disk availability is recorded. The shared 64GiB Polar
storage policy remains an operational obligation; the helper does not claim a
global storage attribution it cannot observe. It adds no fixed project CPU/RAM
quota. Source export has its own existing per-Git-command bounds. The helper disables
image healthchecks. Host Python version/executable hash is retained in state.

Command stdout now uses a bounded pipe drain, with at most1MiB retained and one
discarded overflow-detection byte. Excess triggers immediate owned process-group
termination and parent reaping; no unrestricted stdout temporary file is created.
The command deadline also covers descendants holding stdout after parent exit.

The exact image's complete Config.Env is merged with the fixed inert overrides
used by create_api. Its canonical map hash is persisted, without environment
values, and must match the container's complete effective environment before
adoption, start or cleanup. Missing/extra/altered/duplicate entries reject; a
container with correct labels/image/mounts but wrong environment is not adopted.
An older root lacking this hash requires exact local-image derivation first;
unavailable/conflicting image evidence fails closed. Failure receipts may update
custody evidence, but invalid recovered containers are never started/removed or
recorded as accepted resource IDs. Runtime/System qualification remains separate;
this source correction performs no Docker or deployment operation.


Before starting the API, the helper now atomically publishes and fsyncs an
exclusive preparation.json (polar.observed-preparation/1). It observes the full
actual API container ID, its .Image, the exact image's OS/architecture, configured
user, entrypoint/command and complete effective-environment hash. Expected fields
bind operation/config, candidate commit/tree, verified source manifest/schema,
synthetic input and observer source hash. Environment values are never retained.
Platform expectations come from inspection of the explicitly pinned image;
supported platforms are linux/arm64 and linux/amd64. This records configured
identity, not an observed process UID or independent source execution proof.

All comparisons and durable publication precede start of that same full ID.
Observation mismatch/unavailability or receipt publication failure leaves the
scenario NOT RUN. An already running container without a valid original
pre-start receipt is rejected. Repeated prepare revalidates source, resources,
receipt content and reference; it neither overwrites the receipt nor invents
pre-start evidence. A stopped container can restart only with its matching
original receipt. Receipt corruption, replacement or loss fails closed. A linked
receipt surviving an interrupted publication is revalidated and fsynced before
it can authorize start. The PREPARED result has observed_image_id from the actual
container and preparation {path, sha256}; it no longer labels the expected config
image_id as an observed result.

PR30 composition: the accepted polar-local export operation still produces this
caller's exact source overlay. Its observedLaunch CLI cannot adopt this existing
API container, mount the source overlay, or expose the bounded loopback liveness
route: it creates a separate network-disabled harness container. We therefore
adapt its create/observe/compare/atomic-no-clobber-publication/start boundary
inside this caller, using the same preparation schema with a distinct producer
polar.qa-environment-observation/1. No witness container is launched and no claim
is made that the PR30 CLI observed this API. This adapter is new source requiring
independent review; PR30's prior acceptance does not qualify it automatically.
The existing bounded stdout and full environment checks remain in place.
