# Author qualification and remaining checks

Author source environment: macOS arm64, existing uv 0.12.15, CPython 3.13.15,
locked Python dependencies. Container Python pin is 3.13.18; equivalence is NOT
RUN until the actual build/host check. Image digests are registry-resolved, not
observed running image identities. Exact commit and evidence are returned through
the native OpenRig handoff, not a product task tracker.

Author checks on the candidate source:

| Status | Evidence scope |
| --- | --- |
| PASS | 15 local pytest cases: real calculation/publication subprocess, frozen source hash, six cash/share/NAV values, next-open receipts, corporate actions, metric/null semantics, feature revisions/late ingestion, rejected and fractional orders, delayed fills/split-adjusted pending quantity, no-data/small sample/nonpositive NAV, repeatability, artifact atomicity/tampering/storage failure, API liveness/dependency readiness/body/schema limits |
| PASS | Compose v5.5.1 `config --quiet` and Python compilation |
| PASS | Locked dependency sync and hashed export; official image manifest resolution |
| NOT RUN | One real PostgreSQL API/worker integration case (requires fresh empty `polar_test_*` DB). It exercises original-byte import, idempotency/conflict, concurrent claims, stale fencing/retry, report persistence, cancellation, immutable records, quota and manifest binding. No SQLite substitute. |
| FAIL | Existing Docker daemon connectivity; Docker Desktop was stopped and is not started/reset by the author |
| NOT RUN | Container build/start/image compatibility, cgroups and aggregate resource enforcement, hard storage quota, actual lease/crash/cancellation timing, service recreation persistence, metadata+artifact restore and evaluator mount isolation |
| NOT RUN | Independent QA, exact-commit Validator implementation review, Lead E2E/code review/acceptance/merge, UI integration, real-data/campaign/prospective/live financial performance |

The test client currently emits Starlette's httpx deprecation warning; the locked
adapter works in the author tests. A future adapter migration needs a separate
compatibility check. It is not silently suppressed.

Financial scope is the frozen raw USD six-session accounting fixture plus cash
baseline. Rejected orders retain cash/positions and appear in report diagnostics.
No partial/fractional fills, leverage, shorting, arbitrary code, ticker changes,
multi-instrument portfolio, separated dividend ex/pay receivables, mergers or
cash-in-lieu are supported. Unsupported data/actions fail schema validation or
produce `INVALID`, never an apparently valid financial result. A missing held
mark is invalid; an explicitly absent flat mark reports incomplete coverage.
Empty observation tapes do not produce numerical performance evidence.

All metric formulas are in `metrics.py`, tied to protocol v2. No first-day return
is invented; sample standard deviation uses ddof=1, daily risk-free is zero,
annualizations are explicitly synthetic, drawdown is a positive loss fraction,
and tiny-sample evidence remains insufficient. Gross counterfactual removes fees
from the same executed decisions/quantities. A regression test rejects the
affordability boundary where removing fees could otherwise admit a net-rejected
trade; the defect was reproduced before repair. No tolerance was widened.

General research source connectors, financial campaign protocol approvals,
hypothesis index/search families, full market calendars, authentication for remote
access, licensed real data and external UI integration are outside this bootstrap.
The service stores only deterministic jobs/results, not OpenRig agent assignments
or mutable financial acceptance. The evaluator's PASS is artifact integrity only.

Context policy gap: exact model-token accounting/automatic <=12k project-token and
20%-window enforcement are unavailable. Canonical/assignment/skill retrieval was
bounded by topic but several outputs were truncated, and cumulative retrieved
project material likely exceeds the target. Compliance is not claimed; durable
continuation should load the assignment, this candidate and selected evidence.
