# VTI/BIL monthly no-trade band

Pure author policy for VTI-BIL-NO-TRADE-BAND-01. Compare a fixed closed40/60 no-trade region around a half allocation against monthly half, initial-half buy-and-hold, full VTI and full BIL under identical native cost/reference conventions. Each cost account supplies its own actual formation mark, including residual cash and prior paid fees; an instruction is never an executed fill.

`protocol.md` and `author_contract.json` freeze method/limits before outcomes. `policy.py` has no source IO, financial account, order sizing or execution. The native caller must qualify source rights/identity/geometry, exact current account/mark lineage, metadata flags and next eligible execution close. Closed-band equality holds; terminal EXIT overrides startup/rebalance.

Source-free checks cover strict boundary behavior, cash dilution, control/start/end precedence, exact nonnegative-domain failure, frame/known-by chronology and account-frame mismatch. They do not certify actual native callback/readiness, data, financing, performance or UI. Code has not run on real source values and financial execution is NOT RUN.

Use the existing qualified Python3.13 environment for author checks. Preserve exposed-horizon/source-PIT/adjustment and prior experiment history; no claimed pristine holdout or old source/runtime-admission transfer.
