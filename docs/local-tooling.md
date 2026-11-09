# Local verification launcher

Version1.3 adds `docker CONFIG NEW_PRIVATE_DIR` and `docker-cleanup CONFIG PRIVATE_DIR` for the [runtime-observed launch boundary](observed-launch.md). Existing browser and export behavior is unchanged; Docker preparation, scenario and independent QA verdicts remain separate.

`scripts/polar-local.mjs` is one versioned Node CLI and importable lifecycle for local Polar verification. It uses installed tools, no package download, personal browser connection, project CPU/RAM quota, or compute-slot gate. Coordinate actual shared state conflicts with their owner. Tool receipts are observations, not global enforcement or product/financial acceptance.

## Qualify and reuse

Use the installed Node24 binary. Defaults target the qualified macOS installation: cached Playwright1.65.0-alpha-2026-10-30 and Google Chrome. Other installations can supply absolute `POLAR_PLAYWRIGHT_MODULE` and `POLAR_BROWSER_EXECUTABLE` paths. Playwright uses its default CommonJS import; no bundled Chromium download is needed.

```
node scripts/polar-local.mjs doctor polar-db-1
node scripts/polar-local.mjs smoke /private/tmp/polar-my-new-smoke
```

Doctor validates strict Docker RFC3339 nanoseconds with integer arithmetic, current package/browser metadata, actual project-owned target identity and portable BusyBox timeout success/expiry. Running target probes execute only `true` and bounded `sleep`; stopped targets are explicitly NOT_RUN. Docker CLI calls have host-side deadlines. It does not read database rows/secrets or stop services. Host availability uses load, memory_pressure and filesystem observations; macOS freeMemory alone excludes reclaimable memory.

Reuse a qualified version and environment fingerprint. Requalify after launcher/parser changes, Node/Playwright/browser changes, Docker target image/runtime changes, or a relevant failed operation. Fingerprint covers the entry module and browser file metadata, not all transitive package bytes; record the actual browser version from smoke. Retain failed receipts alongside corrections. This CLI does not install software or adjudicate permission.

## Reuse page actions

```
import {withPage} from '/absolute/path/scripts/polar-local.mjs';
const result = await withPage('/private/tmp/polar-new-journey',
  'http://127.0.0.1:18981/', async (page, {out, signal}) => {
    signal.throwIfAborted();
    await page.getByRole('button', {name: 'Inspect'}).click();
    await page.screenshot({path: out + '/selected.png'});
  }, {actionTimeoutMs: 120000});
if (result.status !== 'PASS') process.exitCode = 1;
```

Or `node scripts/polar-local.mjs journey NEW_PRIVATE_DIR LOOPBACK_URL ACTIONS.mjs`, where the trusted module default-exports that callback. The trusted callback owns assertions, optional evidence and cancellation of its work; launcher owns browser lifecycle. Module import is trusted code and is outside the cooperative callback timer. Only file/loopback starting URLs are accepted; this is not a network sandbox and page subrequests are not filtered. Product callers retain responsibility for provider/private-use constraints.

One fresh task-owned profile, one persistent context and one page are created. Default smoke clicks its local fixture button and captures a screenshot. `actionTimeoutMs` (1–600seconds) is a cooperative cancellation timer, **not a hard wall bound or callback termination**. On expiry the launcher aborts the supplied `signal`, requests browser-context close to interrupt Playwright operations, and waits for the callback promise to settle. A callback that ignores cancellation can exceed the timer; one that never settles prevents `withPage` from returning. Arbitrary JavaScript, filesystem writes, external work and spawned children are not forcibly stopped. This API is not suitable when hard execution containment is required; do not substitute an external timer race around it and call that containment.

Callbacks must await/join all their work before settling, honor `signal` for non-browser work, and cancel/join their own timers or subprocesses. Detached work after callback settlement violates this trusted interface contract; the launcher cannot detect or contain it. Before settlement, `action-state.json` explicitly records RUNNING or CANCELLATION_REQUESTED_WAITING_FOR_CALLBACK, with hardTermination:false. No final result.json, profile deletion or lifecycle return happens while the callback promise remains pending. After it settles, an exceeded timer remains FAIL even if the callback subsequently succeeds. The final receipt records actionContract, callbackHardTermination:false, actionDeadlineExceeded and actionSettled. It is evidence of joined callback settlement, not proof all arbitrary side effects terminated. Browser close is observed for up to8seconds. Finally closes the context, checks sampled browser descendants, and deletes only the exact profile when no observed survivors remain. FAIL preserves partial evidence. It never kills broad processes or touches personal profiles. A process that resists close remains a named owned survivor for diagnosis; the tool does not claim all children were observed.250ms samples may miss short children; RSS is sampled tree peak and CPU is Node-only. Abrupt host kill/power loss is outside finally cleanup. No connection to owner browser/CDP.

Callers must use a new private output directory and keep raw payloads/screenshots outside Git. The parent should be private; module-produced files are caller-owned. `result.json` is0600 and includes actual version, host availability, browser version, action status, peak sampled RSS, known browser PIDs, survivors and profile deletion.

## Exact source export

```
node scripts/polar-local.mjs export REPO FULL_COMMIT FULL_TREE NEW_DIR
```

Exports regular tracked full `src/` and package/Compose metadata directly from Git objects. Verifies full tree and each Git blob, rejects symlinks/bytecode, emits per-file SHA256 manifest, seals files0444/directories0555.16MiB is a finite export operation bound, not a project storage quota. No checkout/index/branch write or untracked content. Keep export while a selected/rollback runtime mounts it. Host operation receipts and source exports are not secret storage.

## Qualification status

Frozen predecessor fc71aae failed independent QA: a callback wrote after the timer-race result. That FAIL remains unchanged. Version1.2 changes the callback contract and receipt ordering; it does not claim hard process containment.

Author evidence is local-only under OpenRig state/platform/local-launcher. Initial11 timestamp cases and BusyBox1.37 success0/expiry143 passed. Actual Chrome156.0.8078.80 one-page smoke and action callback passed; observed survivors empty and explicit profile removed. These author checks do not self-accept this tooling. Independent QA-led PR review remains required; product UI/System/financial acceptance is separate.

### Observed-container cleanup and lifecycle metadata

The observed launcher reports REMOVED only after a successful bounded full-ID
absence query following removal. A successful rm command alone is insufficient.
If the object remains or the engine/identity observation fails, cleanup reports
UNVERIFIED_RETAINED with an exact container ID and recovery owner/action.
Unknown create outcomes retain the intended unique name for owned reconciliation.
The docker CLI returns nonzero for unverified cleanup even if the scenario itself
passed; the scenario fact is preserved separately.

Existing config1/2/3 accepts an optional lifecycle object with these exact fields:
project, task, attempt, owner, cleanup_owner, terminal, intended_lifetime_ms,
retention. Identifiers are bounded safe strings; terminal is TRANSIENT or
RETAINED_EXCEPTION. The intended lifetime is finite, at least the scenario command
timeout, and representable as a date. It is recovery metadata, not a new resource
quota, timer, automatic expiry/deletion or per-run approval. Receipts state an
intended_cleanup_by time. Callers must bind actual existing recovery custody before
launch when interruption could bypass the synchronous finally block.

Transient retention is null. An explicit retained exception requires retention
{reason, release_condition, expires_at}, with at least one nonnull release condition
or ISO UTC expiry. It always names owner and cleanup_owner. Cleanup reports
RETAINED_EXCEPTION, never REMOVED, and does not delete that resource automatically.
The named owner must reconcile and explicitly release it through the existing
exact-owned operational path when its condition is met; this helper does not
claim autonomous condition evaluation or expiry enforcement.

Explicit lifecycle metadata is hashed with the config/output binding and observed
in newly created container labels plus resources/preparation receipts. A marker
prevents silently dropping new metadata to downgrade cleanup to a legacy path.
Old configs and old two-label resources remain readable and recoverable without
requiring new lifecycle fields. New resources launched from old configs expose
derived metadata with LEGACY_CALLER_UNKNOWN rather than guessing an old task/owner;
the default intended recovery period is the scenario timeout plus90seconds.
Reading old receipts never rewrites them or claims modern attribution.

The separate QA environment already re-observes absence after deleting each owned
resource and is unchanged here. Its intentional partial-prepare retention/reuse
contract remains; operations must have a named bounded recovery owner instead of
indefinite unowned retention. No new controller, resource registry or scheduler is
introduced. Actual service, volumes and images are never cleanup targets here.
