# Pure distribution claims (component only)

`polar.distribution_claims` is a pure immutable transition component, not a
price/action loader, native account, Service, strategy or retained financial run.
It imports no production/source/policy/native modules and reads/writes no files.
The existing same-day dividend engine, adjusted NO_ADDITIONAL action-credit
family and raw PRICE_ONLY family are unchanged. No common saved-result schema
or UI is extended by this component.

`Action` binds event/instrument/source/raw pointer, exact original nominal token,
USD/contemporaneous raw-share basis, source ex/payment civil dates and an explicit
ordered reference-date tuple. The modeled availability is derived as the first
reference close civil date strictly AFTER paymentDate. This is not observed
historical availability, declaration K or broker receipt. The caller must verify
actual source hash/identity/vintage, requested window, rights and reference close
clock. Tokens here preserve identifiers; they do not authenticate those claims.
Missing prior holdings/ex-grid or post-pay reference date rejects.

`State` contains declared date/phase, available integer-cent cash, a sorted tuple
of instrument/whole raw quantity and immutable event claims. `recognize` is only
PRE_SESSION on the ex date: the caller supplies already reconciled prior-holder
state. It snapshots quantity once (including zero, preventing retroactive
entitlement after an ex-close buy). Quantity times exact nominal token times100
is rational, rounded ONCE HALF_EVEN to cents; signed exact residue is retained.
No Decimal context or six-decimal price restriction is imposed on distributions.
`pay` at PRE_DECISION_CLOSE on the derived availability date moves the same cents
from claim to available cash exactly once. No external deposit, return or PnL is
booked. A sell after ex recognition does not extinguish the claim.

`settled_snapshot` accepts explicitly caller-reconciled post-close holdings and
cash without changing claims. It does not execute trades or validate costs,
affordability, cash provenance or native fills. Declared phase monotonicity is
checked; actual market/native event ordering and snapshot trust remain outside
the pure helper. Caller orchestration must process all due entitlements/payments
before decisions; a standalone state does not prove omitted actions absent.

`split` supports only exact positive whole-unit transformations. Caller must
apply reciprocal raw quote scaling and explicitly declare same-day ex presence.
An already recognized same-day ex claim or `same_day_ex=True` rejects because
contemporaneous-share basis/order is not qualified here. Fractional/CIL results
reject without flooring. Prior fixed nominal claims never multiply. This is not
a split-coverage claim, adjusted-to-raw inversion or qualified native position
mutation.

`valuation` accepts already identity-bound raw integer-cent position marks,
adds cash and nominal outstanding claims, and reports amount/count/status.
Terminal share liquidation leaves unpaid claims `TERMINAL_OUTSTANDING` and
cannot assert cash-only terminal. No writeoff, early payment, discounting,
withholding, reinvestment or tax model is introduced. A zero-holder recognized
event remains recorded until its modeled payment phase, including a zero-cent
transfer, so lifecycle evidence never silently disappears.

`record`/`restore` check JSON-safe typed state and arithmetic/clock consistency.
`transition` freezes pure operation inputs/before/after as immutable JSON strings
and returns `Evidence`; `verify` replays only the whitelisted pure operation.
Tampered cash change, amount/residue or payment clock is rejected against that
evidence. Consistent attacker-rewritten history is not authenticated by replay;
source/trusted initial state and native reconciliation are separate. Exact
nominal tokens are bounded to512 characters, dates to10000, holdings to256,
claims to10000, encoded transition evidence to16MiB, quantities to10^24, and
cent amounts to10^60 for finite exact-arithmetic inputs. These are component
input safety bounds, not scientific/test/CPU-share budgets.

Public entry points: frozen `Action`, `Claim`, `State`, `Evidence`; `Phase`;
`recognize`, `pay`, `settled_snapshot`, `split`, `valuation`, `record`, `restore`,
`transition`, `verify`. Instantiate `Action` with invented/bound metadata;
serialize it with `dataclasses.asdict` when passing transition inputs. Evidence
is component consistency only; later separately authorized raw/action loader,
cent-native account reconciliation, Service/store/versioned projection and
independent qualification are still required before any retained economic use.
