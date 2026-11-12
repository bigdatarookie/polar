# Scheduled reference policies without fitting

The existing ReferenceResearchService/Service research-config, research-preflight,
research-run and research-recompute entrypoints accept a closed scheduled profile.
They reuse the reference input reader, frozen decision quantities, native ledger,
common result publisher and immutable store. Legacy ridge/PPO/C profiles retain
their existing admission and output path. This first unit supports absolute
momentum sleeves, equal-weight scale controls, positive top momentum and cash.
The pure inverse-volatility helper is not yet an executable B profile: stress
cost propagation and saved uncertainty remain a separate delivery unit.

## Metadata interface

Use polar.scheduled-reference-seed/1 with namespace INVENTED or RETAINED,
absolute profile_path, protocol_path, input_path, calendar_path and timezone_path,
code_revision (40 hex), runtime_image_id (sha256 plus 64 hex), candidate_id and
experiment_id; execution_authority_path is optional during inert preparation.
research-config resolves refs with path/sha256/bytes, current code-binding and
artifact-root identity into polar.scheduled-reference-config/1. It does not fit,
predict or run a policy. See tests/scheduled_fixture.py for a complete invented
profile/calendar and src/polar/scheduled_policy.py for closed required fields.
A profile is bound to the exact protocol, input, calendar and timezone hashes;
no experiment or owner name source allowlist and no expression/plugin loader.
The calendar explicitly declares VALIDATION and/or FINAL, full NAV dates and
month-end decision/next-session reference-close joins. Profiles state all leg
IDs, labels, rules/scales, primary roles, K-to-D delay, point criteria, prose and
saved subperiods. Finite common-wire bounds are checked before an original.

Retained preparation validates the existing exact reference-source rights and
runtime versions. Preflight validates pinned metadata/schedule/bindings only: it does not
open numeric quote payloads, evaluate policy/features/weights or create an attempt.
Full quote/domain validation occurs after durable FIRST_START in the original
attempt; any failure is preserved without refund. A run requires a content-bound
polar.scheduled-reference-operation/1 authority: action ORIGINAL,
binding_sha256 of config excluding execution_authority_ref, allowed_fit_calls=0,
allowed_predict_calls=0, allowed_native_accounts equal legs times phases,
expected_prior_attempts=[], and pinned method_ref, candidate_ref and
qualification_ref. Method schema is polar.prospective-method-disposition/1 with
method_verdict PASS and matching protocol SHA/candidate. Reservation must be
RESERVED with matching candidate and registration. Qualification must be the
actual matching candidate CI PASS with applicable scheduled service selection;
independent applicable technical disposition remains an ordinary owner duty.
This schema is not a new permission issuer or scientific budget grant.

## Execution and output

The durable FIRST_START_CONSERVATIVE_DEBIT is persisted before loading retained
numeric source or evaluating the first signal. A family is stable across source
revisions for a protocol/input/namespace. Any prior attempt rejects another
original; failed/unfinalized attempts are preserved without refund or retry.
Each phase uses fresh capital. At D, only eligible formation prefixes determine
weights and desired whole quantities. Next-close execution can clip buys for
cash including fees, never resize targets using future quotes. Terminal exits
are planned once. Native/evaluator results and full saved diagnostics are
checkpointed by phase. Fit/predict/model counters are truthfully zero.

Semantic files are profile.json, calendar.json (including source schedule rows),
phases.json, diagnostics.json and bindings.json plus a hashed manifest. Public
records use polar.research-result/1, supplied roles/labels, synthetic vendor-
adjusted-reference basis, actual costs and NOT_REVIEWED until an external review.
Tail/month/recovery and subperiod metrics are descriptive saved-ledger outputs.
Full diagnostics remain immutable; the finite public wire carries selected
scalar metrics and explicit accounting/anchor/censoring limitations. No trained
model or forecast-MSE provenance is fabricated.

Stored reproduction verifies hashes, current code binding, saved evaluation and
saved-ledger diagnostics. It never loads source, evaluates policy, fits,
predicts, invokes native or writes. A success does not grant a new original.

## Public qualification

scripts/ci.sh --scenario scheduled-policy --reports EMPTY_DIRECTORY runs the
invented 400-date, four-symbol service through two phases and ten native
accounts, applicable pre-existing frozen literal allocation/fee controls,
common-wire publication/readback, zero-call stored reproduction and duplicate
rejection. Computation and owned cleanup are separate statuses. Ordinary Actions
runs this named scenario for candidates containing scheduled_service.py; a
missing entry/result fails. No private quote, frozen owner outcome or retained
scientific fit belongs in public CI. Author synthetic PASS is not independent
technical or financial acceptance. The first author failure at 03384fa is kept
outside Git in polar-v037-scheduled-A-author-20261111-01: publication exceeded
the common metric limit after native computation; the limit was preserved and
the projection made finite.

## Common forecast-risk and true cost stress (profile/2)

The version2 closed profile supports COMMON_RISK_INVERSE_VOLATILITY with60
returns and annual_cap string0.10, exactly three named INVERSE_VOL/EQUAL_WEIGHT/
MOMENTUM legs at scale1, one FINAL calendar and a one-second K-to-D delay.
Monthly weights use the same eligible61-close prefix, binary64 conversion and
ordered covariance recipe; exactD50 floor12decimal weights and post-round
risk-spread checks remain explicit in saved signals. The same signal/weight/time
plan is executed in two fresh three-account scenarios, BASE100cent+10bps and
COST_STRESS200cent+20bps. Each account recomputes frozenD desired quantities
from its own marked centNAV and clips buys including its actual fees. Fees are
native commissions and ledger charges, not a subtraction from another tape.
The default cost path and legacy record descriptions remain unchanged.

Two immutable public records distinguish FINAL(BASE) and FINAL_COST_STRESS.
They retain supplied leg IDs, actual scalar cost descriptions and all configured
point predicates. The protocol's positive initial-wealth condition is explicit,
as are each benchmark's wealth, Sharpe, drawdown and realized-volatility ratio
conditions. BASE-only fixed subperiods and saved-return uncertainty remain
separate from point criteria and from financial acceptance.

uncertainty.json in the semantic artifact contains fixed seed37001 paired
circular63-block/1000-draw analysis of BASE exact saved returns, all shared-index
hashes, every component/draw status and reasons, counts and central95 empirical
order bounds. Full exact cumulative wealth, drawdown and rational moments use
freshD50 scalar projection, with the frozen integer bit bound; missing/undefined
statistics are not dropped or redrawn. Partial valid intervals are descriptive
subsets only. A positive conditional robustness description requires all1000
valid for every component versus both controls, all base/stress point screens
MET and both lower Sharpe-delta bounds positive. It never grants adoption or
calibrated market confidence. Stored reproduction recalculates only saved
analysis and evaluation, without policy/source/native/model calls or writes.

## Daily exact SMA200 gate (profile/3)

The closed `polar.scheduled-reference-profile/3` supports only
`{"kind":"DAILY_SMA_GATED_QUARTERS","window":200}` with four sorted symbols,
one SMA_SLEEVES leg, full and half equal-weight monthly controls, and cash.
It uses `polar.daily-gate-policy-calendar/1`: every nonterminal formation date
has exactly its next eligible execution date, with a separate terminal exit.
For each symbol the last 200 eligible integer-microprice closes include the
formation close. A gate is active exactly when `200*last > sum`; equality is
inactive, fewer observations invalidates, and each active weight is exactly
one quarter with no redistribution.

The complete daily observed boolean vector is retained independently of fills
and affordability. First observation, any change from the previous observed
vector, or formation month-end emits one coalesced portfolio-wide TARGET;
otherwise HOLD performs no sizing or rebalancing. The monthly controls TARGET
only on the bound month-end formations. Terminal EXIT overrides every leg.
Saved plans retain vectors, previous observations, triggers and per-leg
TARGET/HOLD/EXIT counts. The public record carries bounded gate counts and actual
positive submitted-order counts, without pretending that targets equal fills.
`DRAWDOWN_SCALED_LE` compares exact drawdown fractions; the frozen A2 profile
uses factor `[4,5]`, not a rounded decimal comparison. This profile performs no
fit, prediction, uncertainty bootstrap or learned-state operation.

Use the existing CLI and artifact-root configuration; no new runner is needed:

```sh
python -m polar.cli research-config /absolute/sma-seed.json
python -m polar.cli research-preflight /absolute/sma-config.json
python -m polar.cli research-run /absolute/sma-config.json
python -m polar.cli research-recompute scheduled-reference-experiment-SEMANTIC_HASH
```

Save `research-config`'s returned object as the config file. Existing applicable
retained method/candidate/technical bindings and original-operation authority
still apply; a public invented author check grants no retained run or financial
acceptance. Run selected invented SMA/policy/service tests using the shared
`scripts/ci.sh --test ... --reports EMPTY_DIRECTORY` path. Immutable records,
stored-only verification and legacy profile/1 and profile/2 remain unchanged.
