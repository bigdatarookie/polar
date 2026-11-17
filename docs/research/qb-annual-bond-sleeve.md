# Annual equity and short Treasury sleeve

`polar.qb_annual_bond_sleeve.profile` defines a fixed strategy configuration for
the existing scheduled profile/8 service. Its candidate combines equal equity
and short Treasury targets. The bill sleeve and unremunerated cash sleeve keep
the same equity target. A cash account supplies the accounting control.

The existing annual calendar supplies the initial and year-end formations,
modeled UTC availability, next-close execution and common terminal liquidation.
The existing native ledger executes each BASE and COST_STRESS account with its
own actual fees, frozen desired quantities and cash clipping. Every declared
terminal-wealth, drawdown and volatility comparison against both sleeve controls
must pass in both scenarios for the fixed descriptive point screen. Undefined
comparisons cannot count as passes. There is no parameter search, forecast,
bootstrap, causal fee attribution or financial acceptance in this definition.

The caller must provide actual immutable protocol, source, calendar and timezone
hashes. Retained data and private results stay outside Git. Execute only from a
pinned candidate using the accepted research CLI and qualified engine. A complete
tool-bound author backtest precedes a strategy PR; this definition alone proves
neither execution nor independent review.

This is a new annual cadence experiment on already exposed reference history.
Earlier monthly bond-sleeve negatives remain unchanged. Vendor-adjusted reference
units, unknown historical availability/revisions/PIT and private source rights
remain limitations. No investor total-return, independent replication, robustness
or actionable allocation claim follows from the point screen.
