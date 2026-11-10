# Fixed54 C reference-ridge profile

This extends the existing reference reader, ridge4 kernel, next-close native
ledger and saved-result API. It does not grant a retained C fit or financial
acceptance. A/B profiles and their immutable outputs remain separate.

The retained profile is `V033-C-RIDGE-BROADREF100-V1`. Its prospective protocol
is `2622392745f39bf3e8e42c5f46ab39e3fdd64777f2433f82336d823efe529d31`,
method binding `f4ad21fe2bfa4e6cb9dc53e8b6226126531b92c6ec11387f69dbe395b0fb157a`,
and prepared input `/2` manifest
`ebd040aec68824bdc4d5a62dceb886683daec7ea0f3c325dd1c48337648b5e3c`.
No private quote or source locator is committed here.

The owner date contract `fd3e31ac...` retains its parent schedule association
`67fcf8fd...`. The executable subset is independently pinned as `94c92b64...`.
Before numeric loading, the adapter derives cycle indices, next-close monthly
labels and phase grids from the pinned date metadata. It checks 2728 dates,
21 modeled early closes, 2484 training rows, VALIDATION504/FINAL967 NAV points,
24/47 monthly decisions, and 1242/2484 complete-label diagnostic rows. No date
or alias is dropped to make the counts fit. Native event clocks remain the
actual pinned reference clocks, with counterfactual K at next NY midnight and
D one minute later.

The same one fixed pooled ridge fit is reused for both fresh-capital phases.
The controls are momentum, `EW_ELIGIBLE_MONTHLY` (exact 1/54 targets), and cash.
Decision quantities are frozen before the future close; only affordability
clips buys. Same-close processing publishes all54 quotes, then ordered sells,
buys, fees, full marks and one daily NAV. Risk checks remain enabled; the
REFERENCE_TARGETS submission budget is max(20,2*aliases) per second, admitting
the at-most108 C submissions without changing A/B's20. The existing close
event slots are qualified for54 here, not an arbitrary256-alias promise.

C semantic bundles contain exactly `model.json`, `phases.json`,
`diagnostics.json`, `bindings.json`, `calendar.json`, and `coverage.json`, plus
the content-addressed manifest. All files are hash/byte checked during stored
reproduction. Reproduction computes from stored outputs only, with zero fit,
native calls or store writes. One original per profile/input family remains
enforced, including conservative failure history without automated refund.

Two `research-result/1` records carry the same model reference and the exact
C baseline identity. A bounded optional typed `source_coverage` field preserves
all100 aliases, eligibility/reason codes, completeness/common-bar flags,
action/timing/economic-mapping status and explicit uncomputed excluded outcomes.
Source request paths and private payloads stay outside the public wire. The
coverage artifact and normalized calendar are additionally content-referenced.
Absent coverage is omitted during canonicalization, preserving old A/B record
bytes and content IDs. The generated closed JSON schema includes this extension.
Full967-point/54-position public projections must fit the existing8MiB result
bound; there is no truncation fallback.

Labels disclose conditional source-alias selection, current-vintage vendor-all
adjustment, 55 completeness-only versus54 joint eligibility, action/timing/
mapping unknowns, economic N50 NOT_ESTABLISHED, exposed A history and financial
cohort sensitivity NOT_ASSESSED. No EODHD/four-survivor/EW4/raw-share/certified
total-return or adoption claim is substituted.

Use existing `reference-config`, `reference-preflight`, `reference-run` and
`reference-recompute` CLI interfaces documented in reference-runner.md. Retained
authority additionally binds the exact C method/candidate and exact candidate
CI result selecting `tests/test_reference_c_service.py` or the full `tests`.
An old A-only selector cannot qualify C. Runtime/source/root/attempt checks are
unchanged. Execution still requires the owning scientific assignment and
appropriate independently qualified actual source/runtime/config tuple.

Public invented qualification uses only generated source tokens and invented
all100 metadata: the `/2` reader, one fit/two phases, all54 native positions and
fees before NAV, exact cash-plus-full-mark reconciliation, terminal liquidation,
coverage/API roundtrip and immutable stored-only reproduction. It is technical
evidence, not a retained C outcome or independent financial verdict.
