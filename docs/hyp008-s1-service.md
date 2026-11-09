# S1 immutable Service, unit 3

This namespace composes the fixed S1 source/mask, numeric and family components.
Its engineering qualification uses invented inputs. It grants no real source
conversion, scientific start or financial acceptance. Earlier component verdicts
retain their exact source/runtime scope.

`Service.s1(operation, value)` and the installed `polar` CLI share the same facade:

```
polar hyp008-s1-prepare config.json
polar hyp008-s1-seal seal-request.json
polar hyp008-s1-run seal.json
polar hyp008-s1-attempt UUID
polar hyp008-s1-report s1-HASH
polar hyp008-s1-verify-stored s1-HASH
```

There is no public root, authorize, reset, registration-creation or grant option.
CLI dispatch precedes PostgreSQL/legacy service initialization. These operations
do not migrate a database, start jobs or acquire data. Unconfigured deployment
returns NOT_BOUND and CLI exit 1. Schema/domain failures fail closed.

## Trusted deployment

The fixed service profile `/run/polar/s1-deployment.json` is provisioned by the
deployment owner outside experiment/request directories, mounted read-only by the
accepted config3 observed launcher. Its exact closed shape is:

```
{
  "schema": "polar.hyp008-s1-deployment/1",
  "binding": "StoreBinding object, not this explanatory string",
  "runtime_root": "/polar-artifacts",
  "root_identity": [0, 0],
  "authority_directory": "/run/polar/s1-authorities",
  "locators": {},
  "defaults_directory": "/run/polar/s1-defaults",
  "storage_limit": 68719476736
}
```

The illustrative zero identity is **not executable provisioning**: replace it
with the trusted **host** device/inode. `binding.canonical_root` is the normalized
host artifact directory, not its container alias. The service checks this host
identity against automatic `preparation.retained_binding.artifact_root`, and the
exact writable bind to `/polar-artifacts` in the same-container mount observation.
Host/container inode values are never equated. A local stat separately guards
replacement within the current process. The stable runtime-plan profile digest
contains the host identity, host coordinate, runtime alias and external authority
directory; a copied marker/new root cannot reuse the old seal/plan. In-process
trusted deployments may instead use a local root/inode, for isolated component
tests. Neither constructor nor config3 is a hostile-host Python sandbox.

`locators` maps content digest to each primary input/default/code/interpretation
file, and declared source coordinate to its separately mounted exact bytes.
Paths confer no authority. Ref `{sha256,bytes}` is always checked before decode.
The profile, source closure, pinned default files, existing automatic preparation
receipt and external authority directory must be readable by UID10001. The
persistent artifact mount must be writable; keep the launch output separate.
Use the accepted launcher lifecycle/cleanup and its automatic same-container
image/source/mount receipt, not a hand-written preparation substitute.

Before sealing, the trusted deployment owner stages immutable qualification,
registration, execution-assignment and runtime-plan records with
`S1Store.raw_object(exact_bytes)`/`object(value)`. This does **not** authorize them.
The service checks exact code candidate/full source map against the build, QA
verdict/proof references, prepared/registration assignment and runtime plan.
The plan keys are schema, candidate, image_id, source_build_ref, launcher_refs and
store_profile_ref. Source projection keys are schema, candidate and files;
files use the build's full `/app/src/polar/...` byte/hash map. Qualification keys
are schema, code_ref, build_ref, verdicts and proof_refs. Assignment keys are
schema, prepared_ref, registration_ref, native_qitem and scope. Exact schemas and
field checks are in `hyp008_s1_schema.json` and `hyp008_s1_service.py`.

Only a later independently authorized deployment owner may provision the exact
`<seal_id>.json` Authority in the fixed external authority directory. Seal creation
never writes it. Authority binds the seal, registration, stable store binding,
family and execution assignment. Real authority is absent in this engineering
slice. Invented qualification uses disjoint bindings and roots.

## Source closure and admission

Prepare reads JSON numeric tokens opaquely; it does no Fraction/Decimal/float
conversion of source operands. It checks content/delivery/references, complete
row ordering, original census fields, metadata components and every numeric
pointer against allowlisted exact source bytes. Original roster lines use
one-based raw-line hashes including existing newline, not canonical re-encoding.
Null unavailable A parents never dereference nonexistent numeric children.
Bounds protect finite memory/decoder work: 10000 census rows, 32MiB/file,
256KiB/line, 512MiB per source-graph pass, depth64. A rejected input requires a
specific corrected binding; no silent truncation or subset admission.

Iempty publishes NOT_STARTED/NO_ISSUE_COMPARISON lineage without any family
charge or execution seal. Nonempty run without the external exact authority is
NOT_BOUND before source reread/runtime/numeric work. With authority, actual
image/platform/full loaded-source/default checks and fresh opaque closure/masks
must match before the durable family start. Payload conversion/moments occur
only after that irreversible family reservation.

The fixed family ledger is shared across config/seal/UUID changes in the trusted
store. A root lock serializes admission. Fsynced family start precedes attempt
link publication, and TREE/LINEAR/HISTORICAL_PASS INTENT precedes each wrapper
operation. Intent is conservatively charged even if an inner call was not reached.
Trusted boundary/completion hooks persist separate actual-call evidence; completed
model/proof/history hashes must match returned artifacts. Unknown is not zero or
retry authority. No stage/family refund, automatic resume or alternate model is
provided. Crashes/write failures may leave UNFINALIZED records and an already
consumed family. Operation cleanup is a separately bound physical receipt;
the report does not infer it from numerical success.

## Stored output and verification

The exact semantic members are config.json, source.json, masks.json,
transform.json, representations.json, tree.json, linear.json, history.json,
forecasts.json, evaluation.json, family.json and limitations.json. COMMON
config/source/masks/family/limitations are always present on published outcomes;
COMPLETE requires all twelve. Missing optional artifacts carry explicit
NOT_RUN/UNAVAILABLE/ARTIFACT_NOT_RETURNED status, reason and null reference.
No failed family receives a qualified score. Partial numeric records and stage
charges remain in the physical attempt even if publication fails.

`hyp008_s1_semantic.SHAPES`, `MASK_FIELDS`, `_nested` and the frozen envelope
schema define the closed producer fields and ordered joins. Training IDs, frozen
I/P, history windows, source refs, exact rounding records, transform, scalar tree
parameters **and** parameter provenance, serialized model/iterations/leaf/split
structure, full linear request/proof/solver evidence, forecasts and row/aggregate
losses are semantic bytes. Leaf counts are observed, not forced to two; the
conditional additive-screen interpretation retains its source/default limits.

Canonical JSON is sorted compact UTF8 with final LF, no nonfinite numbers.
`manifest.json` contains schema, ordered-name file map of `{sha256,bytes}`, and
experiment_id. Its acyclic identity is `s1-` plus SHA256 of the canonical
schema/file-map core, excluding experiment_id; manifest is not its own member.
UUIDs/clocks/actual image/resources/stage counters/cleanup are physical attempt
records, not numerical identity operands. Publication links the immutable
manifest to an exact terminal record, and report checks both.

`verify-stored` rechecks file/canonical/member/ID/source/mask/projection bindings,
the **full** stored exact certificate result and the common-P evaluation using
stored target/forecast bits. It performs no source payload conversion, transform
recomputation, fit, LP, historical statistic, prediction or new admission. Stored
verification does not prove independent runtime replay or financial validity.

Author component controls use invented source fixtures, source/runtime/model
doubles and supplied exact certificates. They do not establish actual native
Service execution. The final source composition/image/config and new integrated
qualification harness need normal independent review before invocation; prior
Unit2 runtime evidence remains component-only.
