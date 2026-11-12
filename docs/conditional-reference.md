# Exact adjacent conditional reference

This offline data operation produces `RETROSPECTIVE_CONDITIONAL_PREPARATION_REFERENCE` from the owner's exact 253-close descriptor. It is neither a funded portfolio nor a decision-admissible reference. It uses unit multiplier 1, common cash 0 and the explicit local no-other-entitlement assumption. Those declarations do not certify issue identity, currency, share scale, vintage, fallback behavior or absence of events.

The input/output model predicate supports exactly three issue-unit labels: `ASSUMED_USD_PER_ASSUMED_POST_SEPARATION_COMMON_SHARE` (existing Alcoa convention), `ASSUMED_USD_PER_ASSUMED_AAOI_PARENT_COMMON_SHARE` (AAOI parent-common convention) and `ASSUMED_USD_PER_ASSUMED_AAWW_PARENT_COMMON_SHARE` (AAWW parent-common convention). All require the same complete four-field model, with string holder multiplier `1`, string common cash `0` and `OWNER_EXPLICIT_NONE_FOR_LOCAL_PREPARATION`. Unknown labels, extra fields or changed assumptions remain unsupported. The report preserves the exact supplied supported model; one issue is never relabelled as another. Issue/source-use qualification and contrary revision/event evidence remain the owner's responsibility; label compatibility does not establish source identity or complete event coverage. AAWW cash0 includes the owner's explicit no-declared-but-unpaid-entitlement assumption; a source statement that dividends were never paid does not establish that assumption. Holder1 and no other entitlement likewise remain owner assumptions, and information/combined K remains UNBOUND.

The original AAOI `UNSUPPORTED_OWNER_MODEL` pre-publication failure remains preserved. The later AAWW gap was caught by comparing descriptor metadata with the closed supported models before private execution; no repeated failing private invocation was needed. Support for one issue does not automatically admit the next issue's label. These issue-label corrections change no arithmetic, K, invalidation, publication or CLI behavior and authorize no private operation by the author.

Run only after applicable independent technical qualification, using an existing private output directory outside Git:

```sh
PYTHONPATH=src python -m polar.conditional_reference \
  --descriptor /absolute/INPUT-DESCRIPTOR.json \
  --descriptor-sha256 DESCRIPTOR_SHA256 \
  --output-root /absolute/private-output
```

The descriptor schema is `polar.original-conditional-reference-input/1`, as supplied by DE's metadata interface. Its hash-bound `close_operands` NDJSON and `date_grid` JSON are the only source inputs opened. `date_grid.dates` must have 253 unique increasing ISO dates; operand rows must match exactly in original order. No dates/tokens are filled, sorted into place, rounded or dropped. Any missing, invalid, duplicate or reordered operand fails the invocation without publishing a report. Positive finite decimal tokens have a 256-character and exponent/adjusted magnitude bound inherited from `gym_contract.fraction`; unsupported oversized numbers fail explicitly, without float fallback or global integer-string settings.

Every row carries the original close token/hash/date, record/profile IDs, prior close-domain declaration, source manifest/member/previous pin/normalized ordinal/raw-line and raw-value hashes, provider pointer and raw clock. The builder verifies the bound operand bytes, token hashes, pointer shapes, stable source revision, chronology and decimal domain. It preserves the evidence; it does not reread or recertify original provider bodies. Normalized member ordinals and provider-array ordinals remain separate. Source-purpose/entitlement documents remain owner-provided evidence, not new historical availability proof.

The output `polar.original-conditional-reference-output/1` contains:

- All 253 original `closes`, with 252 `adjacent_gross_factors` in the same order. Each factor stores both complete endpoint rows, their close ordinals and reduced integer-string `gross_factor.numerator`/`denominator` for exact P[t]/P[t-1]. Decimal-to-Fraction conversion and rational division do not use Decimal context rounding.
- A separate factor `raw_clock.estimated_K`: maximum of the two aware endpoint raw estimates, with null observed historical K. If either estimate is missing, the factor estimate is null and labelled `UNBOUND_ENDPOINT_ESTIMATE_MISSING`. Original endpoint labels are retained. This maximum is only a raw-data estimate.
- Null entitlement-information K, owner-model-information K and combined-decision-use K, each explicitly `UNBOUND`, at rows/factors/report. No raw K is promoted to combined K and no later documentary evidence is backdated. `decision_admissibility` remains `NOT_ESTABLISHED_INFORMATION_K_UNBOUND`.
- Input references, four builder/helper code hashes, explicit verification depth, null economic N and financial `NOT_RUN`. No signal, rank, strategy, engine, provider, model or native execution is invoked.

Qualified contrary event/series/unit/revision evidence must be supplied with `--invalidations /absolute/invalidations.json --invalidations-sha256 SHA256`. This hash-bound JSON list has items `{reference_date, reason, evidence_ref: {path, sha256}}`. A date invalidates both adjacent factors touching that close; null date invalidates the whole series. Those entries retain endpoints, carry `INVALIDATED` and a null gross factor, never a substitute factor. No independent event search is claimed; omission of invalidations is not certification that no contrary evidence exists. Changed operands or invalidations produce a new content ID and preserve older artifacts; consumers must adopt the new invalidated report rather than continue using superseded factors.

Publication reuses `HistoryStore` locking, exact immutable comparison, atomic rename and fsync. The supplied existing output directory must be private (no group/other permissions), outside Git and free of symlink traversal. The two-file artifact is `conditional-references/conditionalref-SHA256/{report.json,manifest.json}`. The manifest binds report bytes/hash; the content ID hashes canonical report bytes. Exact repeats return the same ID without rewriting it; conflicting existing bytes fail. Both files are read back before success. Errors emit stable codes without operand values or private paths. Input and output snapshots have explicit 4 MiB bounds (the shared ref reader also has its own bound); the store cap is 64 MiB. No environment timestamp enters semantic output.

Author and independent qualification use invented fixtures only. DE retains first private construction and Quant retains source-use/consumer interpretation. A source or invented-test PASS does not imply private construction, information-time admissibility, economic N or financial acceptance.

## Version 2: typed owner-assumed model metadata

The existing `polar.original-conditional-reference-input/1` contract still admits
only its three exact legacy models. Unknown v1 labels remain unsupported; adding
v2 metadata to a v1 descriptor does not upgrade it.

A separate immutable `polar.original-conditional-reference-input/2` descriptor
supports the same single cash-zero/holder-one mechanism with explicit typed
semantics. `model_semantics` must be exactly:

```json
{"schema":"polar.conditional-owner-model-semantics/1","currency":"USD","quantity_unit":"OWNER_ASSUMED_PARENT_COMMON_SHARE"}
```

The model remains a closed four-field object: `holder_multiplier` is the string
`"1"`, `common_cash` is `"0"`, and `other_entitlements` is
`"OWNER_EXPLICIT_NONE_FOR_LOCAL_PREPARATION"`. Its `unit_currency` is now opaque
owner provenance: 1–256 printable characters, without controls or surrounding
whitespace. The supplied label is retained verbatim; the builder neither parses
an issuer nor infers a currency, class, or source fact from it. Other fields,
changed assumptions and other typed semantics are rejected.

V2 also requires `source_use_owner`, an absolute-path reference with exact
`sha256` and positive `bytes` bounded by the existing 4 MiB input limit. This is
the only additional document opened. It must have schema
`polar.quant-conditional-reference-owner-model/1`, the descriptor's `record_id`,
an exactly equal complete `owner_model`, and a two-date `interval` matching the
first and last fixed-grid dates. Its other metadata and evidence references are
not recursively opened. Descriptor/model admission, owner integrity and
consistency, and the grid endpoint check occur before close operands are read.
This establishes metadata consistency only, not source, action, identity or
vintage completeness.

The pure API remains `build(descriptor, rows, grid, invalidations=(), *,
owner=None)`; v2 requires the explicitly decoded owner argument and performs no
hidden reads. `construct` and the CLI have unchanged arguments. V2 reports use
`polar.original-conditional-reference-output/2`, retain the exact model and
`model_semantics`, and preserve the owner pin in `input_refs`. The two-file
immutable envelope is unchanged. Exact arithmetic, 253 closes/252 adjacent
factors, invalidations, raw estimated K, null UNBOUND information K,
`financial: NOT_RUN`, `economic_N: null`, publication readback and conflict
behavior remain the same. Existing immutable v1 outputs are not rewritten.
