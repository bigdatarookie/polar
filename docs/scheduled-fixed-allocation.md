# Fixed annual rational reference allocations

`polar.scheduled-reference-profile/5` extends the existing no-fit scheduled service.
It uses policy `FIXED_ANNUAL_RATIONAL_WEIGHTS` and closed leg fields
`id,label,rule,weights`. A `FIXED_WEIGHTS` leg supplies exact nonnegative integer
numerator/denominator pairs for every sorted source symbol, sum at most one;
`CASH` supplies zero weights and remains HOLD until the common terminal EXIT.
No weight rounding, signal estimator, optimizer, fit or model is introduced.
The shared ledger floors only the final exact quantity, retains cent costs and
sell-before-buy ordering, and clips execution buys without raising frozen targets.

The pinned `polar.prospective-fixed-allocation-calendar/1` carries parent_schedule,
dates, initial_date, terminal_date, nav_points, returns, annual_targets,
terminal_EXIT and clock_scope. The service checks the full declared reference-date
grid, first-day formation plus each preceding year's last reference session,
next-session execution, next UTC midnight K, D exactly sixty seconds later,
reference execution close, and terminal EXIT overriding other instructions.
There is no warmup estimator or monthly replacement calendar. Source symbols,
manifest, schedule, profile, protocol, runtime and authority remain bound by the
existing service. Preflight remains metadata-only; source quotes are read only
after FIRST_START_CONSERVATIVE_DEBIT. Missing source pins are not executable.

`polar.fixed-allocation-saved-diagnostics/1` versions the frozen diagnostic recipe.
Drawdown ties retain earliest equal high and first maximum trough. A zero drawdown
uses the initial peak/trough/recovery with zero durations; unrecovered episodes
retain null recovery and both peak-to-terminal and trough-to-terminal censoring.
Postinitial holdings exposure uses exact saved quantity times close_micro divided
by 10000 times cent NAV, including terminal, with earliest-date/lexical-symbol
maximum ties. The first saved segment may start at initial cash; later segments
carry the preceding actual close and subtract its cumulative costs/fills. No reset
or extra liquidation occurs. Existing profile diagnostics are unchanged.

Run and stored-only recomputation reuse the existing CLI, native engine, evaluator,
immutable manifest and common saved-result wire. Reproduction uses saved plan
quotes and saved ledger only, with no input source, policy, estimator, model,
native or store-write call. Tests use invented inputs; technical qualification
is separate from retained capture, source rights, financial and adoption judgment.

## Fixed annual BASE and cost stress

Profile `polar.scheduled-reference-profile/8` reuses exactly profile/5's fixed
rational policy, annual calendar, UTC K/D60, earliest-equal-peak diagnostics and
terminal EXIT. Its only extra required field is `cost_scenarios`, exactly
`[{"id":"BASE","cost_profile":{"flat_cents":100,"bps":10}},
{"id":"COST_STRESS","cost_profile":{"flat_cents":200,"bps":20}}]`.
It forbids an uncertainty/bootstrap field. Both scenario phases are FINAL-only,
share the same saved constant-weight decisions, and execute fresh independent
native accounts with the actual scenario cost profile and fee-aware clipping.
There is no posthoc fee subtraction or additional signal/estimator/optimization.
Five legs give ten native accounts; zero score/rank/estimator/optimizer/ML/bootstrap
calls. Explicit zero counters describe this fixed policy, not retained acceptance.

BASE gets the declared carried subperiods; stress has empty subperiod arrays and
NOT_REQUESTED diagnostics. Both get independent five-clause point evaluations
and public immutable result IDs. No uncertainty.json is generated or admitted;
robustness/adoption remain insufficient regardless of point-screen outcomes.
Stored reproduction requires both phases, exact scenario/plan/simulation cost
bindings and identical shared decisions, then rechecks saved metrics/diagnostics
without input source, policy, native or writes. This is a scoped saved-output
reproduction, not a new scientific run or an independent financial verdict.

Profile/8 retained authority also binds allowed_score_calls, allowed_rank_calls,
allowed_estimator_calls, allowed_optimizer_calls and allowed_bootstrap_samples
all exactly0. The existing source/runtime/method/reservation/root/CI/native bounds
remain required. Its extra point-screen limitation consumes one common-wire
limitation slot; choose compact accurate public text within existing bounds.
