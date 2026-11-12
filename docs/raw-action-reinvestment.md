# Raw-action private research branch

This is a separate, closed branch of `ReferenceResearchService`. It reuses the
existing immutable `HistoryStore`, conservative attempt debit, bounded native
worker, Nautilus1.231 and exact-cent money/fees. It does not reinterpret an
adjusted-reference family or publish to the common research result endpoint.
All examples/tests use invented operands. Code availability is not authority to
parse retained financial operands or run a candidate.

## Input and structural preflight

`polar.raw-action-input/1` has exactly these fields:

- `packet_ref`, `dates_ref`, `clocks_ref`, `quotes_ref`, `actions_ref`: existing
  absolute path/SHA256/byte-length pins; four data members must occur in the
  pinned `polar.private-raw-price-action-consumer-dataset/1` packet.
- `source_instrument`, `source_symbol`: the declared current identity.
- `event_dates`: metadata-only objects with `event_id`, `ex_date`,
  `payment_date`, `availability_date` (first reference civil date strictly
  later than paymentDate). IDs are unique; q0 events remain present.
- `split_records`: zero for this captured-event scope. Nonzero captured split
  input is rejected; no fractional/ambiguous split route is invented. The
  accepted pure component's existing whole-unit split API is unchanged.
- `rights`: `INVENTED_PUBLIC_TEST`, or
  `SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION`.
- `provenance`, `historical_K` (null), nonempty `limitations` strings.

Quote/action numeric payloads are not opened by preflight. Dates, clocks and
source packet metadata bind the complete grid and modeled instruction calendar.
Preflight validates every K=next-civil-UTC-midnight, D=K+60s and Q=next reference
close with K<D<Q, including terminal EXIT. Annual/payment overlaps coalesce by
date, with no amount or return selection. The pinned generated calendar must
equal `raw_action_input.calendar(...)`; it is metadata, not executable targets.

Inside the debited original only, `load` reads the existing quote and action
projections. Raw close/open lexemes must round-trip losslessly to integer micro
USD. No adjusted quote substitution, inversion or new provider retrieval occurs.
Actions use the exact string `original_fields_as_supplied.unadjustedValue`, not
an adjusted value or six-decimal rounded nominal. Content-bound event identity
uses the original source digest/JSON pointer/record digest recipe. Source
quality/pointer evidence is reused as pinned data, not certified anew by this
reader. Declared current issue, separate vintages, missing observed K, omitted
holder-event coverage and private demo rights remain limitations.

## Profile/config and local operations

`polar.raw-action-profile/1` has exactly `schema`, `protocol_id`,
`protocol_sha256`, `input_sha256`, `calendar_sha256`, `timezone_sha256`, `legs`,
`cost_scenarios`, `policy`, `capital_cents`. Policy is
`CLOSED_PAYMENT_RETAIN_ANNUAL_CASH_D60`, capital10000000 cents, legs in order:
PAYMENT_CASH_REINVEST, RETAIN_CASH, ANNUAL_CASH_REINVEST, CASH. BASE is100c+10bps;
STRESS is200c+20bps, with eight fresh accounts. The five frozen primary clauses
are terminal wealth11/10, nonworse sampled RF0 Sharpe, vol/DD6/5 and positive
growth. No mutable weights, estimator, bootstrap, model or parameter search.

`polar.raw-action-config/1` uses the existing scheduled config field set and
pin assembly: namespace, profile/protocol/input/calendar/timezone refs,
code inventory/revision, runtime image, candidate/experiment, execution
authority and actual artifact-root identity. `config_from_seed` accepts the
existing scheduled seed path names. It changes the schema, not any economic
operand. Exact retained runtime is Linux Python3.13.18/Nautilus1.231.0.

Local CLI (help is inert):

```text
python -m polar.raw_action_service config SEED.json --root ROOT
python -m polar.raw_action_service preflight CONFIG.json --root ROOT
python -m polar.raw_action_service run CONFIG.json --root ROOT
python -m polar.raw_action_service recompute SEMANTIC_ID --root ROOT
```

The same methods are dispatched by existing `ReferenceResearchService`.
The optional `--limit-bytes` is the existing artifact capacity bound (default
64GiB); it does not allocate scientific authority or create a new controller.

Retained authority uses existing `polar.scheduled-reference-operation/1`:
ORIGINAL, exact binding hash, eight native accounts, zero fit/predict/score/rank/
estimator/optimizer/bootstrap allowances, prior attempt history, compatible
method PASS, native reservation and exact-head qualifying CI. Additionally,
`independent_review_ref` pins a `polar.raw-action-technical-review/1` object:
`status=PASS`, `candidate_sha`, `protocol_sha256`, `input_sha256`, distinct
`reviewer`, and integrity-pinned `report_ref`. Reviewer identity is an assertion
under normal queue/review custody, not a cryptographic identity claim. The
independent final decision must cover raw input/native/Service/store/private
projection applicability; a pure component or method PASS is insufficient.

## Actual native event order

Each ex session snapshots reconciled prior native holdings before trading,
including q0. At the reference close, old holdings first own the market move;
due claims are then transferred once to native cash; previously formed close
orders execute with frozen desired quantities and only downward fee-aware BUY
clipping; final raw position marks plus remaining claims are sampled.

`raw_claim_native` is a supported `SimulationModule`. Payment computes the
accepted pure `pay` transition, proves cash increase equals claim decrease and
zero NAV change, then uses `ExecutionClient.generate_account_state` through
`Portfolio.update_account`. The event info explicitly names internal
distribution-receivable settlement, its exact event/evidence identity and zero
external cash flow. The real native total/free/locked balances and account event
are reconciled; no cached-balance mutation, synthetic PnL, fee reversal,
external funding label or shadow spendable cash is used. Zero-cent transfers
still produce lifecycle evidence but no artificial native balance event.
The invented control proves an unfunded native order is denied before payment
and an actual native buy can fill after the same claim settles.

The current adapter uses the existing explicit zero native latency and timer
offsets: due settlement close+10ns, sell+100ns, buy+200ns, NAV sample+1000ns.
Logical offsets express modeled deterministic ordering, not venue observations.
Decisions remain next UTC midnight+60s and never use future Q to upsize.

Three invested legs must match actual first executed positions, cash, fees,
rounding and logical times within each cost (account IDs/wallclock excluded).
Terminal EXIT overrides pending buys, with no buy/sell roundtrip. Positive
outstanding claim/shares invalidates cash-only comparison. A due unpaid q0 is
instead a technical lifecycle defect. Strict pure `cash_only_terminal` and
pending-record count remain separate from nonzero economic assets; a generic
future q0 claim does not silently change the strict component flag. All B7 due
events must be processed, including zero holders.

## Immutable private output and saved verification

`raw-action-experiment-<manifest hash>` resides under the existing
`reference-research-experiments` namespace. Members are:

- profile, bindings, calendar, common native plan and source-evidence JSON;
- BASE/STRESS per-leg native tape JSON;
- BASE/STRESS private typed result JSON.

The manifest binds every member byte length and SHA256. Attempts use the
existing `scheduled-reference-attempts/<stable protocol/input/namespace family>`
lock/debit and per-phase artifacts. Failure/partial receipts and actual native
events are retained. A failed original is never automatically retried/refunded.
The operation owner separately enforces one original plus one SUCCESS-only
stored allocation, including no replay after an indeterminate collection error.

`polar.private-raw-action-result/1` is validated by the closed strict
`raw_action_result.PrivateResult` model. Its basis explicitly names raw marks
plus captured nominal receivables, modeled post-pay availability and uncertified
investor total return. Every ledger point has integer `cash_cents`,
`receivable_cents`, `exposure_cents`, `position_cents`, raw `positions`, fees and
`nav_cents`; NAV must equal cash+raw exposure+receivables. Source context, limits,
private rights and exact bindings travel with each result. Financial status
starts NOT_REVIEWED; descriptive point evaluation is not an independent verdict.
Adoption and robustness remain INSUFFICIENT_EVIDENCE.

No `ResearchResults.publish`, P1 POST, public API/UI rollout or old-schema record
is emitted. Result IDs are `private-raw-action-result-<hash>`, not public research
IDs. The existing common wire lacks receivables and this basis: normal common
publication is NOT_SUPPORTED by this package. Validator can audit the private
immutable graph and sign an exact-subject sidecar without exposing source data.

Recompute validates manifest/member/current-code bindings, pure claim transition
replay, settlement receipts, actual saved fill money, cash/position/claim NAV,
initial control, exact metrics/criteria and diagnostic/projection equality.
Actions are stored once in a shared pool; compact state refers to exact event
IDs, avoiding repeated embedded full source calendars. Replay reads the saved
graph only: no source paths/mounts, original policy, native/model calls or writes.
Pure consistency cannot authenticate a consistently rewritten graph or replace
independent source/runtime/native custody.

Diagnostics reuse exact saved-NAV arithmetic: signed lowest ceil(n/20) tail,
1/21/63 extrema with earliest endpoint ties, complete months/partial reasons,
earliest equal peak with censored recovery, raw/cash/claim exposure, and two
carried BASE eras at the last2020 NAV anchor. STRESS eras are NOT_REQUESTED.
No fee-only causal explanation or reset/re-execution of carried eras occurs.


## Raw-action content ID codec (future technical correction)

Event IDs are `eodhd-vti-div-` followed by SHA256 of UTF-8 JSON with exactly
`source_sha256`, `json_pointer`, and `record_sha256`: keys sorted, compact
comma/colon separators, ASCII escaping, and **no trailing newline**. This is
what the retained dataset producer specifies. The reader now uses a scoped
content-ID codec; global Gym operation/config/family canonicalization still
includes its newline and is unchanged. No alternate LF form is accepted.

Admission reports `RAW_CONTENT_SOURCE_REF`, `RAW_CONTENT_RAW_POINTER`, and
`RAW_CONTENT_EVENT_ID` separately. Source identity, pointer equality, and digest
equality all remain mandatory; errors do not print payload values. Invented
producer-shaped fixtures use their own serialization and a fixed digest vector.

This source correction cannot validate a retained record or establish the
exclusive cause of the original B7 failure. The exact original offending record
and conjunct remain UNKNOWN. Its charged FAILED_UNFINALIZED attempt, immutable
source/event IDs, and ineligible SUCCESS-only stored allocation are preserved.
No rerun, refund, new scientific family or financial result is authorized here.
