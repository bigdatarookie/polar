# Owner-selected adjusted source import

The existing import-plan/execute/status/result/terminal/consume commands support
adapter `alpaca-all-adjusted-sip-selected/1` and config schema
`polar.selected-adjusted-sip-import-config/1`. This adds no loader, provider route,
account, automatic retry or financial operation. All tests use invented inputs.
The existing broad100 adapter, scope pin, request keys, cache namespace and stored
plans/receipts remain unchanged. A newly generated plan still binds its actual
source projection; old source-bound plans are not relabeled as new executable code.

Config has exactly schema, adapter, mode (`fixture` or `provider`), scope_ref
(absolute path plus SHA-256), and seed_refs. The selected scope has exactly:

- schema: `polar.selected-adjusted-sip-scope/1`
- targets: ordered unique literal aliases, not an original population/FIGI roster
- request_template: existing exact endpoint, all/SIP/USD/1Day/ascending/10000;
  symbols is `ONE_LITERAL_ALIAS_PER_JOB`; explicit valid UTC start/end and asof
- policy: exact `polar.import_adjusted_sip.selected_policy(len(targets))`
- selection_ref: absolute path/SHA-256 of the existing owner selection metadata

The owner selection is `polar.quant-selected-source-operation/1`, with matching
fixed_targets and request_profile. Its explicit limit spelling `10000` or integer
10000 is normalized only for typed HTTP configuration; source numbers are never
rounded. All other selected target/request dimensions match exactly. Source-only
IDs are emitted as selected-source-target hashes, population identity is null and
economic admission is NOT_ISSUED. A ticker is not certified economic continuity.

For the selected three-target operation, the finite policy is 3 jobs, at most 2
pages/job and 6 GETs, 1MiB/body, 6MiB response budget, 45s/request, 1s spacing,
400s wall including the existing materialization reserve, and 128MiB scope
storage including the 64MiB terminal reserve. These are declared operation
bounds derived from the existing profile, not new project quotas. Redirects and
automatic retries remain disabled. Rate limit, denial, schema failure, repeated
cursor, incomplete pagination and unknown in-flight requests retain their exact
outcomes. There is no fallback feed, date window, adjustment, key or alias.

The namespace is imports-adjustedsip-selected[-fixture]-v1/<scope SHA-256>.
Plan IDs are adjustedsipselected[fixture]-<scope SHA-256>-<plan SHA-256>, allowing
the same ordinary CLI to locate the exact declared scope without a new registry
or ticker allowlist. Changing the declaration creates a separate namespace;
restart of the same declaration reuses existing saved responses and budget.
Explicit seeds must match the complete request/cursor/body contract. Broad100
and raw cache keys are never silently adopted by the selected profile.

Use the ordinary entry point, for example:

    POLAR_DATABASE_URL=unused-file-only PYTHONPATH=/candidate/src python -m polar.cli import-plan /input/config.json
    POLAR_DATABASE_URL=unused-file-only PYTHONPATH=/candidate/src python -m polar.cli import-execute PLAN_ID --attempt-id UUID --network --scope-file /input/authority.json

These import methods use the existing file store, not a PostgreSQL connection;
the nonsecret unused-file-only setting avoids requiring a DB secret for this
file-only CLI path. POLAR_ARTIFACT_ROOT and POLAR_STORAGE_BYTES retain their
existing meaning. Fixture mode uses --fixture /input/invented-responses.json,
never --network. No credential access or provider invocation occurs on plan.

The existing execution authority binds selected scope hash, actual code projection,
Python binary hash, metadata binding refs, attempt ID, original credential reference
and terminal owner. Mount config, scope, selection_ref and authority/binding-ref
metadata at their exact paths read-only; only the existing private artifact store
is writable. Execution revalidates selected scope/owner bytes before any request
or credential resolution. The child remains the existing fixed-host HTTPS GET
executor; selected adapter dispatch preserves the declared asof literally.

Normalized rows preserve original numeric lexemes and pointers, request asof,
vendor-all-adjusted price and volume basis, unknown historical K, no established
investor total return and unresolved economic identity. Extra source precision is
retained even when a later consumer requires exact 6dp representability: that
consumer must reject or disclose incompatibility, never silently round/rebase.
A successful transport/terminal is not source-entitlement, coverage/calendar,
action-completeness, scientific fitness or financial acceptance. DE owns first
actual capture and private consumption under the original selected operation.
