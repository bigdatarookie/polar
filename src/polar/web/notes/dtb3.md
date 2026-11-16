# How material is the zero-carry assumption?

Research diagnostic: QB-CASH-CARRY-MATERIALITY-20261116-V1. Independent assessment: PASS for a current-vintage descriptive synthetic discount reference. Strategy profitability, investable cash earnings and historical point-in-time availability are UNKNOWN. Actual B11 execution: NOT RUN.

The question is whether the scale of quoted short-term Treasury discount yields makes zero carry a material modeling assumption. This diagnostic uses FRED DTB3 quotes and a constant USD 50,000 face-notional reference. It does not measure interest an investor earned or a tradable bill portfolio return.

| Saved quantity | Exact or displayed result |
| --- | --- |
| Reference horizon | 2022-12-30 inclusive to 2026-11-06 exclusive; 1,407 civil days |
| Weighted mean quoted annual discount yield | 157663/35175 percent; displayed 4.482246% |
| Synthetic discount-dollar reference | USD 157663/18; displayed USD 8,759.06 |
| Day-count/reference basis | 360-day annual discount basis on constant face notional |
| Joined quote age | 1–4 days; current vintage with modeled strict prior-date join |

The source quote scale makes zero discount-rate carry a material assumption for this synthetic reference. The dollar reference cannot be added to B11 performance: actual cash balances, bill purchase prices, maturity and rolling, funding, fees, taxes and changing positions are outside this calculation. The USD 1,000 comparison in the author calculation is only a flat illustrative reference, not B11's actual terminal-comparator wealth hurdle.

Method: exact file-backed queries materialized the complete daily reference and its summary. Independent review compared every saved row with a separate source/ASOF lookup and checked the rational totals. Complete daily data remain retained as artifacts; this report displays accepted summaries only. Strict prior-date joining does not establish observed publication-known-by timestamps. No strategy NAV, order, fill, annualized portfolio return or cash-earnings series exists for this diagnostic.

Source: [FRED DTB3](https://fred.stlouisfed.org/series/DTB3), Board of Governors H.15, current-vintage daily quoted discount yields. Source rights/fitness qualification is separate from the finite analytical assessment.

Next research step: assess the feasibility of an existing BIL cash-benchmark source/saved-result path under a prospectively separate question. B11's frozen zero-cash/RF0 control, criteria and attempt history stay unchanged.
