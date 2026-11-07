# Local verification launcher

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
  'http://127.0.0.1:18981/', async (page, {out}) => {
    await page.getByRole('button', {name: 'Inspect'}).click();
    await page.screenshot({path: out + '/selected.png'});
  }, {actionTimeoutMs: 120000});
if (result.status !== 'PASS') process.exitCode = 1;
```

Or `node scripts/polar-local.mjs journey NEW_PRIVATE_DIR LOOPBACK_URL ACTIONS.mjs`, where the trusted module default-exports that callback. The callback owns assertions and optional evidence; launcher owns browser lifecycle. Module import is trusted code and is outside the callback deadline. Only file/loopback starting URLs are accepted; this is not a network sandbox and page subrequests are not filtered. Product callers retain responsibility for provider/private-use constraints.

One fresh task-owned profile, one persistent context and one page are created. Default smoke clicks its local fixture button and captures a screenshot. Callback execution has a sensible wall deadline (1–600seconds), close is bounded8seconds. Finally closes the context, checks sampled browser descendants, and deletes only the exact profile when no observed survivors remain. FAIL preserves partial evidence. It never kills broad processes or touches personal profiles. A process that resists close remains a named owned survivor for diagnosis; the tool does not claim all children were observed.250ms samples may miss short children; RSS is sampled tree peak and CPU is Node-only. Abrupt host kill/power loss is outside finally cleanup. No connection to owner browser/CDP.

Callers must use a new private output directory and keep raw payloads/screenshots outside Git. The parent should be private; module-produced files are caller-owned. `result.json` is0600 and includes actual version, host availability, browser version, action status, peak sampled RSS, known browser PIDs, survivors and profile deletion.

## Exact source export

```
node scripts/polar-local.mjs export REPO FULL_COMMIT FULL_TREE NEW_DIR
```

Exports regular tracked full `src/` and package/Compose metadata directly from Git objects. Verifies full tree and each Git blob, rejects symlinks/bytecode, emits per-file SHA256 manifest, seals files0444/directories0555.16MiB is a finite export operation bound, not a project storage quota. No checkout/index/branch write or untracked content. Keep export while a selected/rollback runtime mounts it. Host operation receipts and source exports are not secret storage.

## Qualification status

Author evidence is local-only under OpenRig state/platform/local-launcher. Initial11 timestamp cases and BusyBox1.37 success0/expiry143 passed. Actual Chrome156.0.8078.80 one-page smoke and action callback passed; observed survivors empty and explicit profile removed. These author checks do not self-accept this tooling. Independent QA-led PR review remains required; product UI/System/financial acceptance is separate.
