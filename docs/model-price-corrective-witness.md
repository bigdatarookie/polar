# Profile10 same-choice correction and consumed evidence

`CORRECTIVE_MODEL_PRICE_E1` is a closed scheduled operation action for profile10,
not an alias for ORIGINAL or the profile11/raw-action corrections. Ordinary
ORIGINAL still rejects any prior start. Admission holds the existing store lock,
requires exactly the named sole failed original, and publishes a new conservative
debit before loading any source/model prices. A second caller or third start is
rejected. This component supplies a technical interface, not an execution grant.

The exact-field `polar.model-price-corrective-amendment/1` must have status
`BOUND_FOR_EXECUTION`. It binds action, family, candidate/experiment, prior ID,
seven `prior_members` (canonical five plus FINAL phase and diagnostics),
`prior_semantic_id`, all six `prior_semantic_members` (manifest plus five members),
`science_binding_sha256`, `current_binding_sha256`, `prior_audit_ref`, `custody_ref`,
`invariants_ref`, `applicability_ref`, `charge_history_ref`, `owner_id`,
`maximum_family_starts:2`, `allowed_native_accounts:5`, `prior_charged_work_ns`,
`allowed_e1_work_ns`, and `total_work_budget_ns`. Unknown fields/retry flags reject.
Hash/length pins contain exactly `sha256` and integer `bytes`. Stored paths derive
from family/prior/semantic IDs, never arbitrary paths supplied by the amendment.

Original status must be FAILED_UNFINALIZED/RESEARCH_INVALID_RESULT with five
completed native accounts, refund=false/automatic_retry=false and no published
results. Original method/card, full science/root/registration, and all source refs
remain bound. Only code, revision, runtime and execution-authority refs can differ
in the science projection. Prior phase/semantic economic bodies are integrity
checked and byte-joined without JSON value decoding during admission; saved
bindings and the normalized profile must match. Old files are never rewritten.
No missing old optional counters are inferred as zero.

The applicability ref must be a pinned Validator disposition for the same
candidate, registration, family, old attempt and semantic ID with
`APPLICABLE_SAME_FROZEN_CHOICE_E1_WITH_FULL_OUTCOME_EXPOSURE`, bounded scientific
PASS and no unmet predicates. Audit/custody/invariant/charge refs are integrity
pins under existing queue custody, not cryptographic owner authentication. Current
method/card/runtime/CI qualification and actor/root/mount authority remain required.

Work allowances have no built-in new grant or reused historical per-operation
budget. The operative owner must explicitly bind a positive conservative prior
charge and a total/remaining allowance consistent with the actual selected resource
scope, including original and technical-use history. The source checks integer
bounds and the old saved wall charge; source accounting does **not** implement
physical remaining-time termination. Actual physical guards, UID/resources,
registry/prior/root/actor, private output and any separately explicit new
SUCCESS-only stored use remain operational custody. Old INVALID/SPENT status,
old stored ineligibility, full outcome exposure and missing55 sizing/20 clipping
witnesses remain. New evidence is not pristine holdout, independent confirmation,
performance rescue or old witness backfill.

## Call sites and saved-only validation

Profile10 `bind_plan` opts into the existing native capture path and pins MODEL
mapping/source identities and formation clocks. At `desired_targets`, the actual
reconciled D cash/holdings/NAV, eligible MODEL prices, normalized exact rational
weights, lot1 and floor result are captured with decision/leg/date links. At each
SELL/BUY route, actual pre-order state, MODEL quote/time, target/delta, fee profile
and BUY affordability/maximality operands are captured before execution. Zero
routes retain explicit no-order reasons. CASH/HOLD and terminal EXIT do not invent
TARGET witnesses. Fill IDs join the exact routed order. Native coordinates,
execution quantities/fees/cash/marks and frozen policy are unchanged; source
prices and MODEL prices remain separately saved. Witnesses add metadata only.

`polar.model_price_consumed.verify(plan,simulation,profile,calendar)` is a pure
saved-array validator. It requires captured witnesses and checks all four aliases,
five legs, calendar/decision/formation clocks, exact floors, fill-linked cash and
holdings, fee affordability and maximality, SELL/BUY/zero/EXIT semantics, and native
marks. It never substitutes reconstructed state for missing captured operands.
`verify_saved(service,semantic_id)` is the manifest-checked source-absent read-only
entry point: it reads the six immutable semantic files, checks the current code
binding, profile10/calendar and every captured witness, and returns bounded status
and zero source/policy/native/store-write/financial-evaluation/publication counters.
It does not need the old graph or input/protocol/quote files and does not run a
financial evaluator, diagnostic recomputation, policy, native engine or publisher.
Old graphs without this witness schema remain unavailable, never upgraded.

The existing `ReferenceResearchService.recompute(semantic_id)` additionally checks
new-schema witnesses before its existing saved-output reproduction. It retains
legacy old-plan behavior; it cannot turn an old missing witness into new evidence.
The report-only adapter remains separate and losslessly preserves all31 limitation
objects. No second adapter, controller, tracker or public API is introduced.

Invented controls exercise single/concurrent additive debit, failure preservation,
seven-leaf/six-semantic integrity, changed-science/method/card/applicability/type
negatives, four-symbol MODEL floors and clipping, CASH/EXIT/zero routes, exact fill
links, identical native executed NAV/fills with capture on/off, and source-deleted
read-only witness validation. These are technical controls, not retained use or a
financial verdict. All previously exposed economic outcomes remain exposed.
