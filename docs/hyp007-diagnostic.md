# HYP007 diagnostic service contract v1

Implementation contract, frozen before dependent synthetic tests. Scientific authority is
owner protocol `60dbc42dacb9c75bf6c84be807787c1e909749fba262626e1b4529c34268717d`.
This is a distinct operation, not a revision of the existing descriptive experiment.
No real label, fit or experiment is authorized by this implementation assignment.

Service methods and installed CLI commands correspond one to one:

| Service | CLI argument |
|---|---|
| hyp007_diagnostic_prepare(config) | hyp007-diagnostic-prepare CONFIG.json |
| hyp007_diagnostic_run(sealed_manifest) | hyp007-diagnostic-run SEALED.json |
| hyp007_diagnostic_attempt(attempt_id) | hyp007-diagnostic-attempt UUID |
| hyp007_diagnostic_report(experiment_id) | hyp007-diagnostic-report hyp007-HEX |

All inputs are strict objects with unknown fields rejected. Config has schema
`polar.hyp007-config/1`, source_root (absolute existing directory), raw_manifest,
action_manifest, calendar and tzdata (relative safe paths below source_root), and
qualification_objects (nonempty map of safe relative path to SHA256). Raw/action
manifest, calendar and timezone hashes are protocol constants. Object bytes and source
decimal tokens are retained without normalization into the legacy history schema.
Prepare returns schema `polar.hyp007-prepare/1`, status PREPARED_STRUCTURAL_ONLY,
config, inventory, roster, structural, definitions and prepare_id (hash of the other
fields). Structural records bind domains, clock/role support and packet dependencies;
no labels/targets or final finite train/evaluation counts are calculated by prepare.

Run accepts schema `polar.hyp007-seal/1`, prepared (the exact prepare response),
sealed_at (UTC microseconds), bindings, and seal_id (SHA256 of all other fields).
bindings requires protocol, source_projection, accepted_tree, build, learner_defaults,
qa, execution_assignment and resource_policy. Each is an exact hash-bound object;
unbound/null/missing values return NOT_BOUND before any data arithmetic. The exact
source projection, build inventory/defaults and QA proof bytes must be verified locally.
Execution assignment is a separately retained native authorization record, not implied
by this PR or a nonempty caller string. Real execution is disabled until that binding.

Errors use `polar.hyp007-error/1`, status ERROR, code (stable uppercase token),
with no raw exception/payload/path/credentials. CLI errors exit1, NOT_BOUND exits2.
Attempt/report reads verify all hashes and exact file sets before returning metadata.
No HTTP mutation, automatic retry, worker lease or source refetch is introduced.

Artifacts live under separate `hyp007-preparations`, `hyp007-families`,
`hyp007-attempts`, `hyp007-experiments` namespaces. Every publication is no-clobber,
fsynced, hash-bound and size bounded. Family is fixed by the protocol lineage, never
by job/config/seed. Family started/slot-start/slot-finish/receipt records are append
only. A started slot consumes its ordinal before a fit; unfinalized family fails
closed. Exactly 2022,2023,2024 × ridge6,ridge21,tree, at most9 real fits. A later
manifest cannot reset consumed accounting. Report cannot claim completion without
the complete roster, panel, masks, all score predictions, models/transforms, losses,
resource receipt, input/code/build/defaults/qualification DAG and all9 successful slots.
Unexpected numerical failure aborts rather than removing an opportunity.

Output manifest `polar.hyp007-manifest/1` lists the exhaustive filenames and SHA256/
byte lengths; experiment identity hashes the immutable seal plus source projection.
Required files: seal.json, inputs.json, roster.ndjson, panel.ndjson, masks.ndjson,
predictions.ndjson, losses.ndjson, transforms.json, models.json, report.json,
resources.json, fit-slots.json. Native model text is embedded in models.json with
its own SHA256; no unlisted model side files are admitted.
Attempt start and finish are separate physical records, never semantic identity inputs.
Partial/failed records remain readable and are never promoted by publication alone.

Numerics are binary64, single native thread, explicit finite checks; conditional
raw-close C versus ex-open target wealth are separate. All raw/index/event ancestors,
modeled K and physical receipt clocks remain distinct. All source/value/model artifacts
remain private outside Git. Resource supervision covers the entire subprocess tree,
600 CPU/900 wall seconds including construction and serialization; no fit retry.

Prospective author synthetic plan: invented inputs only; finite deadline20 minutes
per affected invocation. At most TWO native tree fits total (one no-split constant,
one nonconstant), SIX ridge SVD fits total, no real fits. Failure/restart/resource
tests use injected synthetic learners and consume zero native fits. SRE's separate
build smoke allows ONE native constant tree fit and one synthetic SVD. Independent
QA declares its own finite invented-data fit count before execution. Replay uses
persisted models without retraining. Arithmetic, masks, DST/K equality, missing/zero,
role/collision/terminal behavior and tamper/interrupt tests precede real execution.

Bindings use exact `{path,sha256}` objects pointing to retained bounded files.
Protocol is the normative Markdown bytes. source_projection is the exact map from
service/CLI/safe-store/process-budget/HYP007 module filename to actual SHA256.
accepted_tree has schema polar.hyp007-accepted-source/1, commit and tree (40hex).
build is SRE's polar.hyp007-numeric-build/3 with exact installed runtime_files,
runtime_packages, learner_defaults_sha256 and source/native/backend provenance.
learner_defaults is the prefit complete explicit/sklearn/native/default/alias/cast map.
qa has schema polar.hyp007-qualification/1, source_projection_sha256, build_sha256,
verdicts `{code:PASS,system:PASS,numeric:PASS}` and at least3 proof_objects (binding
refs). execution_assignment has schema polar.hyp007-execution-assignment/1,
native_qitem, operation HYP007_SOURCE_COHORT_PREDICTOR_V1_1,
source_projection_sha256 and scope ONE_REAL_FAMILY_NINE_FITS. resource_policy is
exactly cpu_seconds600, wall_seconds900, logical_opportunity_limit100000, real_fit_limit9.
Those are inputs, not assertions of current acceptance. Before executing, the later
operator must provision artifacts/hyp007-authorizations/SEAL_ID.json with schema
polar.hyp007-local-authorization/1, seal_id, execution_assignment_sha256,
accepted_commit, accepted_tree. This post-seal local authorization is outside the
seal digest, so there is no self-reference. No implementation command creates it.

The owner evidence-clock map691495df and definitione10a38e6 are required qualification
inputs. Cash unit checks qualify reconstruction at S, not historical publication;
required dated split/terminal assertions contribute max two-session K. All referenced
static check/report objects are verified by exact bytes. No real source IDs live in Git.
