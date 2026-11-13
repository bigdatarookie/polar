# Immutable claim-calendar validation scale

This repairs repeated pure validation work. It does not establish the exclusive
cause of a historical retained timeout, authorize another operation, or change
any timeout, claim, quantity, cost, lifecycle or terminal rule.

The existing native300s guard covers an entire four-account bounded_native(plan)
call. It is not a fresh300s allowance for each account. Existing NATIVE_RUN_ENTERED
is emitted before engine.run/end and final tape checks; ACCOUNT_COMPLETED follows
those checks. A last CASH entry without completion does not distinguish slow prior
accounts, engine processing, Python claim validation, final checks or another stall.
The allowed original B7 E1 diagnostic has no per-account elapsed times or worker
stack and no exported full phase/tape/semantic result. Exact historical cause stays
UNKNOWN; old INVALID/SPENT/partial/no-result accounting is unchanged.

Source inspection found valuation -> State.__post_init__ -> Claim.__post_init__ ->
Action.__post_init__ repeatedly parses every reference date and checks sortedness
for every already immutable claim. An invented43-claim/2728-date state, valued8times,
performed939128 date validations before this repair. The cache stores only successful
pure date-domain/sorted-unique validation for at most32 strict-string tuples.
Every call still checks tuple shape/length/element types before cache access, and
per-event ex/payment/token/source/amount checks remain. No price/amount/claim/state,
valuation or execution result is cached. Tuple/string immutability makes the fact
stable; eviction only causes ordinary revalidation. Invalid non-string elements
use the original error-order path and are never hashed into the cache. Invalid
calendar validation is not cached.

After the repair the same invented8-valuation probe performed696 date validations,
with identical cash-only values. Single local shared-runtime observations were
0.359209s before and0.047421125s after, not a broad speed/SLO or retained causal
claim. The large invented native phase completed all4accounts/2728NAV each/43actions
under the unchanged300s guard in65.460197112s in the first author run. Its CASH
account retained all43 zero-quantity recognitions/payments, zero trades/balance
updates and unchanged cash-only NAV. These are synthetic controls, not original
retained portfolios or a replacement of historical partial evidence.

Existing component money/rounding/phase/restore/split negatives and native transfer/
raw service controls remain applicable; the new regression also checks typed invalid
calendars, duplicate/reversed/missing-ex/unmapped-pay dates after cache priming. No
ordinary ledger or private evidence fields/bytes are changed. Guard/worker/admission,
result publication, family/root/counters/budgets and all original source inputs are
untouched. Any future financial operation requires its own actual selected scope,
applicable qualification, coherent runtime/custody and admission. The already spent
B7 family remains at2starts; this optimization creates no third-start path, refund,
reset, new family, larger wall limit or automatic original/stored invocation.
