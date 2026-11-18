# Frozen priced reserve on the scheduled reference path

Profile `polar.scheduled-reference-profile/15` uses the existing scheduled seed/config, `ReferenceResearchService.preflight/run/recompute`, native reference accounts, result contract and immutable semantic store. It statically calls the unchanged author module `polar.qb_priced_reserve_prototype`; the closed adapter checks its exact SHA. There is no caller-selected plugin or new service.

Use protocol ID `QB-RISK-MATCHED-PRICED-RESERVE-20261118-V1`, symbols `["BIL","VTI"]`, and policy `{kind: RISK_MATCHED_PRICED_RESERVE, lookback: 60, annual_cap: "0.10", weight_units: 1000000, prototype_sha256: <PROTOTYPE_SHA256 from polar.scheduled_priced_reserve>}`. Legs, in order, have IDs and rules `SWEPT`, `CASH_TARGET`, `BIL_ONLY`, scale `[1,1]` and descriptive labels. Primary strategy is SWEPT; benchmark is CASH_TARGET. The six ordered criterion specifications are exported as `SPECS`; supply unique IDs and descriptions plus `left_id: SWEPT`. BASE costs are 100 cents plus 10bps, COST_STRESS 200 cents plus 20bps. Uncertainty is `PAIRED_CIRCULAR_SAVED_RETURNS`, block63, replicates1000, seed37004. Existing profile hashes, public descriptions, limitations and bounded optional subperiods remain required.

Supply the existing monthly `polar.scheduled-policy-calendar/1` with FINAL only, pinned New York TZif bytes, and a compatible accepted reference input. Formation uses the existing causal 60-interval binary64 sample covariance, annualized by multiplying each operand by252. The original selector preserves these operands as exact rationals. Its fully funded BIL/VTI choice maximizes VTI on the fixed grid under the cash control's forecast variance. An infeasible mixture uses exactly the cash control allocation; zero VTI forecast variance explicitly leaves both in unremunerated cash. Valid singular geometry is allowed; invalid geometry is typed invalid, with no covariance repair. Formation is next New York midnight plus one second, execution at the declared next reference close; terminal EXIT overrides targets.

Build the normal scheduled seed/config against the exact accepted loaded revision and actual runtime image. Ordinary retained execution leaves `execution_authority_ref` null and creates the existing automatic offline intent after current code/runtime/input checks. Explicit legacy artifacts remain strict; supplied invalid artifacts never fall back. FIRST_START and the existing protocol/input/namespace original family remain nonresetting. Source preparation, rights, hosting and scientific predicates remain independently applicable; this profile does not qualify those predicates.

One plan is formed after FIRST_START and reused for independent BASE/stress native accounts. Own-account cash clipping, fees, whole units, drift and terminal liquidation use the existing engine. All six criteria apply to both actual cost scenarios. Any failed criterion takes precedence over unavailable comparisons. BIL-only contributes a terminal opportunity hurdle, not matched-risk SR/drawdown/volatility comparisons. The paired saved-return bootstrap compares only SWEPT with CASH_TARGET and remains descriptive conditional evidence.

Private phase plans retain original covariance operands, exact targets/weights/variance certificates and actual operation counts. The private finish record retains completed native accounts and original work counts; the profile15 run response contains status/attempt/semantic/result locators and financial acceptance only. Source/CI success does not constitute scientific acceptance.

Recompute reads the existing immutable bundle, including hash-bound saved TZif bytes, with no source/config references required. Arithmetic certificate verification checks PSD, the cash cap and adjacent maximality inequality, analytic minimum witnesses, selected/next-grid inequalities, explicit fallback, cash balances, clocks, instructions and the common stress plan. It does not reload prices, estimate covariance, invoke the author selector/search or execute native accounts. Returned estimator/rule/risk-search/native/write counts are zero for reproduction; original counts remain private and distinct. Saved NAV bootstrap arithmetic is recomputed from saved returns.

`tests/test_scheduled_priced_reserve.py` contains an invented input/profile composition and actual service tests. No real dataset, private period, numerical result or financial claim is included here. Quant owns the exact candidate composition, author checks, actual frozen experiment and subsequent native Validator submission.

The existing CLI surface is unchanged. Keep real outputs private:

```sh
polar research-config /absolute/private/scheduled-seed.json > /absolute/private/config.json
polar research-preflight /absolute/private/config.json > /absolute/private/preflight.json
polar research-run /absolute/private/config.json > /absolute/private/run.json
polar research-recompute scheduled-reference-experiment-<manifest-sha256> > /absolute/private/reproduction.json
```

The profile15 API response avoids original operation counts. Existing private phase/finish artifacts retain them; never infer original zero work from reproduction's zero estimator/search/native/write counts.
