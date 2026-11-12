# Independent saved-output verifier

`python -m polar.saved_verifier` checks saved output without importing the
producer, evaluator, policy, learner or native engine. It does not submit an
experiment, call an allocated reproduction, publish a review or write the input
store. Validator retains the separate scientific and financial conclusion.

The first profile is `scheduled-reference-flat100-bps10/1`: saved whole reference
units, positive exact micro-unit prices, half-even cent settlement, flat100cent
plus ceiling-cent10bps per positive fill, sell-before-buy and fee-aware clipping,
frozen desired quantities, mandatory terminal cash, next New York civil-midnight
K/plus60second D/next reference close execution and close+1000ns samples. The
externally pinned packet declares initial capital; the toy uses1000cents and
the retained protocol uses its own bound capital. No universal scientific
capital choice is made by the checker.

## Command and packet

Use the accepted Python runtime and qualified checker source. Keep licensed
saved outputs and the actual packet local; Actions contains invented inputs only.

```sh
python -m polar.saved_verifier --packet /private/checker-packet.json \
  --packet-sha256 EXPECTED_PACKET_SHA256 > /private/checker-report.json
```

The optional external packet pin checks exact packet bytes. Supply it for an
attributable consumer run; the report always identifies the actual packet hash.
The packet is metadata pointing to existing saved files, not a new registry or
copy of the scientific dataset:

```json
{
  "schema": "polar.saved-verifier-packet/1",
  "profile": "scheduled-reference-flat100-bps10/1",
  "root": "/private/existing-saved-export",
  "initial_capital_cents": 1000,
  "semantic_id": "scheduled-reference-experiment-<manifest-sha256>",
  "expected_bindings": {
    "code_revision": "<producer-commit>",
    "runtime_image_id": "sha256:<producer-runtime>",
    "protocol_sha256": "<frozen-protocol-hash>",
    "input_sha256": "<input-manifest-hash>",
    "candidate_id": "<candidate>",
    "experiment_id": "<experiment>",
    "profile_sha256": "<saved-profile-hash>",
    "calendar_sha256": "<saved-calendar-hash>"
  },
  "manifest": {"path": "semantic/manifest.json", "sha256": "<hash>", "bytes": 1},
  "graph": {"path": "CONTENT-GRAPH.json", "sha256": "<hash>", "bytes": 1},
  "publications": [
    {"phase": "FINAL", "path": "public-FINAL/result.json",
     "sha256": "<hash>", "bytes": 1, "result_id": "research-<same-hash>"}
  ]
}
```

Replace placeholders and lengths with actual frozen metadata. Every saved phase
must have exactly one publication. Both manifest IDs and all semantic and graph
members are hash/length checked through bounded no-follow regular-file reads.
The existing producer32MiB member envelope is reused; this is an input-format
bound, not a new CPU/RAM/financial-attempt quota. No external `input_ref` price
file, executable model or original source body is followed: checking uses saved
plans, prices, instructions, fills, marks, metrics and public records only.

Expected protocol/input/code/runtime/candidate/experiment/profile/calendar pins
must match the saved bindings and publications. A metadata/runtime identity match
is not reexecution or independent proof that an engine physically ran.

## Report and scope

The compact `polar.saved-verifier-report/1` contains subject/bindings,
profile, actual checker module hashes/version, packet hash, grouped checks,
addressed discrepancies and explicit unsupported properties. The grouped counts
are observations, not test or scientific budgets. Details are bounded to the
first20 addresses per group; failure totals retain the full count.

`covered_verdict` describes this profile's implemented checks. `overall_verdict`
stays `UNKNOWN` on a covered pass because signal construction, source fitness,
historical availability, tail/bootstrap diagnostics and adoption are outside the
profile. Missing graph/native-cash evidence or unsupported profile/cost semantics
also remain `UNKNOWN`, never silent numerical PASS. `financial_verdict` is always
`NOT_ASSESSED`. A failed check returns process exit1; covered PASS/UNKNOWN returns0
so callers must inspect the report rather than interpret exit0 as acceptance.

Covered arithmetic includes cash/positions and all NAV marks, intended/routed
orders versus fills, exact fees/settlement/residuals, native-cash correspondence
where saved, terminal liquidation, Fraction returns/moments/drawdown and the
declared fresh-Decimal50 volatility/Sharpe/log-div-exp CAGR recipe. Constant cash
has defined zero volatility and unavailable Sharpe with `ZERO_VARIANCE`.

Public grid, series roles, values, ledgers, costs, metrics and comparisons bind
back to that saved computation. Supported literal criterion arithmetic includes
Sharpe delta thresholds, exact terminal wealth ordering, positive growth and
ordinary or rational-factor-scaled maximum drawdown. In particular4/5 is applied
to exact drawdown, not rounded display or ordinary drawdown<=benchmark. Predicate
arithmetic does not establish scientific suitability or adoption; an unknown
predicate is reported unsupported. Diagnostics beyond these base metrics are not
recomputed. There is no SMA feature, solver/certificate or bootstrap checker in
this first profile.

## Independence and acceptance

Arithmetic was extracted from the existing independent Validator saved audits
and stable pure-function contribution. The production modules depend only on
stdlib and their independent math helper. Public test controls include literal
half-even ties, zero orders, the fee-clipped desired8/routed7/terminal-sale ledger,
exact moments, flat cash and near-threshold predicates. The complete toy's
NAV1000/899/1059 and fees101/102 are fixed public expectations. The separate
reference arithmetic in tests is Validator's pure public contribution, not an
import of the candidate math or producer evaluator.

Semantic fee/NAV/clock/terminal mutants regenerate their fixture manifests and
publications consistently, so they must fail arithmetic rather than only a hash.
Wrong expected binding and raw-byte tampering exercise identity separately.
Symlinks/traversal, non-integer positions and unsupported profiles are explicit.

An available nonauthor QA owns the final exact-source/ordinary-CI technical
decision. Real use is then a separate read-only Validator invocation on a
permitted saved subject. Validator consumes compact exceptions and material
witnesses and issues its own conclusion without repeating the old full manual
audit. Fixture success or merge alone does not complete P2. Record metadata-ready,
qualified-checker-ready, actual start/finish, report-ready and independent
conclusion separately; retain pre-readiness wait. Cumulative token coverage and
time saved remain UNKNOWN unless reliably observed, with no old scientific run
repeated for benchmarking.
