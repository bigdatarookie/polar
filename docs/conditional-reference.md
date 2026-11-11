# Exact adjacent conditional reference

This offline data operation produces `RETROSPECTIVE_CONDITIONAL_PREPARATION_REFERENCE` from the owner's exact 253-close descriptor. It is neither a funded portfolio nor a decision-admissible reference. It uses unit multiplier 1, common cash 0 and the explicit local no-other-entitlement assumption. Those declarations do not certify issue identity, currency, share scale, vintage, fallback behavior or absence of events.

The input/output model predicate supports exactly two issue-unit labels: `ASSUMED_USD_PER_ASSUMED_POST_SEPARATION_COMMON_SHARE` (existing Alcoa convention) and `ASSUMED_USD_PER_ASSUMED_AAOI_PARENT_COMMON_SHARE` (AAOI parent-common convention). Both require the same complete four-field model, with string holder multiplier `1`, string common cash `0` and `OWNER_EXPLICIT_NONE_FOR_LOCAL_PREPARATION`. Unknown labels, extra fields or changed assumptions remain unsupported. The report preserves the exact supplied supported model; AAOI is never relabelled as Alcoa. Issue/source-use qualification and contrary revision/event evidence remain the owner's responsibility; label compatibility does not establish source identity or complete event coverage. The original AAOI `UNSUPPORTED_OWNER_MODEL` pre-publication failure remains preserved; this correction authorizes no private retry by the author and changes no arithmetic, K, invalidation, publication or CLI behavior.

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
