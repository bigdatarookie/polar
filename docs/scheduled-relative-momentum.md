# Exact-lag relative momentum on the scheduled reference service

Profile `polar.scheduled-reference-profile/7` uses the existing config/seed,
preflight, original, semantic store, result publisher and saved-only reproduction.
Use `python -m polar.cli`; no new engine, launcher or provider adapter.

The closed policy object is:

```json
{"kind":"RELATIVE_MOMENTUM_EXACT_LAGS","lookback":252,"skip":21,"full_symbol":"VTI","drawdown_peak":"LATEST_EQUAL_PEAK"}
```

Three sorted declared source aliases, four unique scale `[1,1]` legs with rules
`RELATIVE_MOMENTUM`, `EQUAL_WEIGHT`, `FULL`, `CASH`. Primary roles bind the first
two rules. Full context holds the configured full_symbol. Monthly calendar/1
continues to bind exact source schedule, all full civil month ends and warmup;
FINAL only. Timezone pin must contain UTC bytes; K is next UTC midnight, D+60s,
then next pinned reference close, including early closes. All event and terminal
K/D/close inequalities are checked from metadata during prepare, before both any
price read and FIRST_START. The planner repeats that complete check before its
first operand access. Terminal EXIT is separate.

Scores are exact Fraction(Pmicro[t-21],Pmicro[t-252])-1, not current close or
float/12dp scores. Descending exact rank, ascending literal-symbol ties, top1
even if negative. Exact thirds benchmark and cash zero targets are emitted for
all monthly events, including unchanged weights. Whole-unit sizing, future BUY
cash clipping, lexical sell-before-buy, fees and terminal liquidation reuse the
shared ledger. No HOLD shortcut for cash; no terminal buy.

Base cost100c+10bps and true stress200c+20bps execute eight independent accounts,
sharing one cached score/rank/target sequence. Policy must supply exactly the five
primary EW clauses: TERMINAL_GT, SR_DELTA_GE threshold0.10, DRAWDOWN_LE, VOL_LE,
POSITIVE_GROWTH. Vol has no lower ratio band. Original scores start only after
FIRST_START_CONSERVATIVE_DEBIT; preflight reads metadata/schedule only.

Authority/operation/1 requires `allowed_signal_counts`: score_calls354,
completed_scores354, operand_reads708, rank_calls118, completed_decisions118 for
the actual118-date study (invented controls have their own finite date count).
allowed_estimator_calls and allowed_optimizer_calls are0, native accounts8,
fit/predict0. Actual counters and partial invalid-signal diagnostics are saved on
failure without retry/refund; zero ML work does not mean zero scientific work.
Exact source input, protocol, calendar, timezone, runtime, independent technical
qualification, method disposition and sole reservation still bind normally.

Each saved witness pins input hash, formation/execution/index, both operand dates,
positive integer microprices, exact rational scores, rank/winner and cached leg
targets with a canonical SHA seal. Stored-only verification checks saved arithmetic
certificates, adjacent rank/tie relations, target projections, calendar/sample/K/D
joins and shared BASE/stress plan. It calls no score/ranking/target generator,
source reader, native, model or store writer. Rehashing a changed witness does not
bypass certificate validation; it is saved correspondence, not new source truth.

Uncertainty uses seed37004, three noncash saved BASE legs, paired circular63,
1000 draws and the versioned inverse-CDF ceil(p*m)-1 with median and explicit
invalid counts/no redraw. Robustness/adoption always remain INSUFFICIENT_EVIDENCE,
even if every point clause and bootstrap computation is valid. Legacy seed and
quantile recipes are unchanged.

Relative diagnostics/1 explicitly selects latest-equal-running-peak for every leg
and scenario; cash NO_DRAWDOWN has null dates. Inclusive FIRST_RETURN era arguments
retain preceding saved NAV anchors/cost ownership, not temporal profile6 anchor
semantics. Full BASE era diagnostics (up to3) remain saved at exact precision;
STRESS eras are NOT_REQUESTED. To fit the existing public wire, full-path metrics
plus bootstrap summaries stay scalar while each leg gets a compact era limitation
with requested dates, actual preceding anchor/interval/status, net return, SR, DD
and fees (10 significant display digits; exact saved values unchanged). No UI or
result-schema extension. Missing era boundaries remain explicit unavailable.
All prior profile semantics and immutable results remain unchanged.
