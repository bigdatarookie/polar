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
