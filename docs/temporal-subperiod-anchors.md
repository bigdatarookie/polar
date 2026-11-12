# Temporal subperiod NAV anchors

Future profile/6 diagnostics interpret each subperiod pair as a saved NAV anchor
and inclusive final mark. The first return is the next saved reference mark after
the anchor. The adapter calls the existing return-date evaluator with that date,
so its preceding-close holdings and cumulative fee/fill subtraction use exactly
the requested anchor. Shared boundary fills belong to the earlier segment once.
No calendar-day increment, reset, sizing, reexecution or extra liquidation occurs.
Missing anchor/end and zero-return/final-anchor ranges remain explicit UNAVAILABLE;
no fake zero metric or silently shifted anchor is supplied.

Private diagnostics are versioned `polar.temporal-saved-diagnostics/2`, record the
requested anchor and actual first return, and retain the latest-equal-high temporal
drawdown convention. Stress with no configured subperiods remains empty. The
shared generic evaluator still accepts inclusive first-return dates; profiles1–4
and the separately versioned fixed-allocation profile5 keep their old behavior.

This is a prospective source correction. Original B3 artifacts, records, profile,
semantic IDs, trial counters and historical diagnostic fields are immutable.
Their old source export remains the reproduction context. Do not apply this
adapter to recalculate or overwrite the original B3 eras. The existing independent
assessment exposes the BASE first-era absence/second-era anchor mismatch and the
absence of STRESS eras separately from its full-phase verdict. No new scientific
run, producer/native/recompute or changed economic method is authorized here.
