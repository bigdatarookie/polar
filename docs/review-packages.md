# Legacy local package compatibility

The standard author, independent QA and Actions path is [scripts/ci.sh](ci.md).
Migrated technical checks use its official locked environment and exact Git checkout;
local package generation, nested assignment/review bindings and post-handoff hash
matching are no longer prerequisites.

The commands below are retained for recorded PR32/PR37 legacy consumers and
historical recovery. They must not be added back as an admission step for the
migrated path. The module still has explicit CLI/test consumers, so it has not been
deleted blindly. Preserve old packages and failures; retire remaining calls only
when their actual consumer has moved to the standard path.

For an existing legacy consumer, the local metadata commands are:

```sh
node scripts/polar-local.mjs package /absolute/SPEC.json /absolute/new-package
node scripts/polar-local.mjs package-check /absolute/new-package
```

These commands do not import the candidate or start Docker. The caller's existing native assignment owns execution authority. A file called review is not proof of applicable independent review: the package reports `NOT_ASSESSED`. Authors may debug their isolated invented scenario under their technical mandate; final independent acceptance remains with QA. This command accepts only the `INVENTED` classification and grants no retained-data, scientific-trial, provider, credential or financial authority.

The spec is JSON with `schema: "polar.review-package-spec/1"`, `protocol: "pr32"` or `"pr37"`, native `task`, `owner`, `input_classification: "INVENTED"`, immutable candidate `repo`, and pinned references shaped `{ "path": "/canonical/absolute/path", "sha256": "..." }`. Paths must resolve without symlinks. Required shared refs are `build_ref`, `config_template`, and `refs.tool`, `refs.observer`, `refs.harness`, `refs.review`. `refs.tool` pins the existing local launcher; `refs.observer` pins the exact adapter module, including a versioned filename. The generator module itself is also pinned. No adapter is selected by a guessed filename.

For PR32 provide `assignment_template`, `runner_binding_template`, `code_projection_ref`, and `refs.runner`. The generator derives commit/tree/image from the build, refreshes config/build/projection/tool/observer/harness/review refs, writes the assignment, derives its digest into config, and then derives all runner pointers and digests. Capability refs use exactly `path`, `record_token`, `sha256`; observed-launch refs use `path`, `sha256`. The existing corrected runner still takes exactly one `RUNNER-BINDING.json` argv. No second scientific runner is generated. If `full_package_map_ref` is supplied for PR32, it must exactly equal the build receipt’s full `source_files` map; a subset is rejected in the SOURCE phase with a retained bounded map diff before Git export or operation output creation.

For PR37 the config template is the existing observed-launch config. Provide `full_package_map_ref` and the caller's exact `refs.input`, `refs.expectations`, `refs.config`, and (for the corrected adapter) `refs.package_map`. Candidate run-config identity must agree with the build. The complete package namespace is checked against immutable Git objects; the eligible `.py/.json/.sql` projection must exactly equal the build's code map. PR32 additionally keeps its separate executable code projection; full package, eligible code, and executable projection counts need not be equal.

Do not hand-edit generated SHA chains. The immutable package includes canonical config/assignment/binding/runner metadata, maps, a fresh sealed Git-derived source namespace, a manifest, and `PACKAGE.json`. An old writable export is never repaired by deleting inconvenient files. Existing failed families, roots, charges and history remain separate; optional `previous_failure` records ancestry. Omit `invocation_id`, `output_root`, and `anchor` for repeatable author preparation with fresh automatically derived identities. Supplying an explicit identity binds that particular finite unit; existing paths are rejected. Never reset a scientific family to rerun it.

## Existing execution and cleanup

For an observed-launch package, use the same launcher verbs with explicit package selection:

```sh
node scripts/polar-local.mjs docker --package /absolute/new-package
node scripts/polar-local.mjs docker-cleanup --package /absolute/new-package
```

The selected, hash-checked adapter retains its existing prepare/start/finally-cleanup behavior and exact full-ID/image/label checks. PR32 uses its existing bound Python runner and Service path. Package generation does not launch either path. Candidate/fixture references are rechecked before use. Cleanup only needs the original package/config/adapter binding, so candidate-source corruption does not prevent exact-owned recovery. Unknown cleanup is not success; preserve evidence and use the named recovery owner. Parent termination cannot guarantee that JavaScript finally executes; long or interruptible operations still need appropriate existing recovery custody, without a new controller or per-attempt permission gate.

To retain failure streams in a synthetic author operation, explicitly opt in on the spec:

```json
"diagnostics_capture": { "mode": "INVENTED_PRIVATE", "max_bytes": 65536 }
```

This narrowly captures the adapter's existing exact owned `docker start --attach` result before its cleanup. It writes host-private bounded stdout, stderr (including emitted traceback), and phase/exit/signal/timeout/truncation metadata. The synchronous capture hook issues no command itself and is restored on return or exception. Ordinary calls and packages without this explicit policy keep counts-only behavior. Do not opt sensitive/private scientific inputs or oracle material into this author capture path. Do not publish private stream bodies in shared reports; return statuses and exact local evidence paths. Publication failure stays explicit and cannot yield an execution PASS.

A preparation mismatch retains safe expected/observed maps and missing/extra/changed identities in its failed private package directory. It does not erase the only diagnostic to clean up source staging. No source bodies, environment strings or oracle values are placed in the shared map diff.
