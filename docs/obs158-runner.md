# Fixed OBS158 price-ledger runner

This is the Part B source contract for the frozen 158-alias, 253-close profile.
It extends the existing shared checker/converter and HistoryStore publisher.
It does not implement a general backtester, loader, scheduler or agent tracker.
The independent one-name cent-control PASS on `1b01c47` qualifies only that
component. Full Part B source, native barriers/unit handling, evaluation,
publication and retained execution need their own applicable evidence.

## Interfaces and source scope

`obs158_data.load_obs158_inputs`, `preflight_obs158` and `convert_obs158` are
unchanged accepted Part A interfaces. Their report continues to say
`runner_execution_allowed=false`; Part A alone never grants a strategy run.
`Obs158Service` checks the complete observed source/image/config binding,
selected control-reference identities and explicit scoped authorization, then
uses the same data checker. This is deterministic preparation, not an automated
independent-review or financial verdict. OpenRig remains the authority for real
assignments, independent admission, scientific limits and later operation.

`Service` exposes `obs158_preflight(config)`, `obs158_run(config)`,
`obs158_replay(config, experiment_id)`, `obs158_attempt(attempt_id)` and
`obs158_report(experiment_id)`. The matching installed commands are
`polar obs158-preflight FILE`, `obs158-run FILE`, `obs158-replay FILE ID`,
`obs158-attempt ID` and `obs158-report ID`. `polar obs158-code` returns current
eligible source-file bytes/hashes without loading a dataset or native engine.
All other standalone `obs158-*` commands require `--artifact-root PATH` for the
existing private job root; they use the same Obs158Service directly without
reading DB credentials or connecting to PostgreSQL. The storage allocation is
explicit (`--storage-bytes`, at most the existing 64 GiB policy), not a claim to
account for every other project artifact root. Service methods use the normal
configured artifact root. Root changes cannot reuse a bound authorization.
Existing Gym, history, worker and research interfaces retain their namespaces.
No HTTP, UI or queue-operation surface is added here.

`simulate_obs158(converted, aliases)` consumes only shared-preflight admitted
converted channels and the exact lexical roster. `evaluate_obs158(simulation,
converted, aliases)` consumes the two account tapes and complete fixed grid.
These are implementation seams, not authorization bypasses or free retained
preparation calls. Calling retained preflight reads actual source artifacts and
requires its own applicable operation scope. This source delivery invokes none.

## Exact input and runtime binding

The closed configuration is `polar.obs158-run-config/1` in
`src/polar/obs158_output_schema.json`. It binds source class, input config, complete
current source map, commit/tree, immutable local image ID, frozen composition
reference, engineering control-reference binding, execution authorization and
the literal `/polar-launch/preparation.json` path. There is no default run grant.

Retained input uses the unchanged Part A config. Invented qualification uses
`polar.obs158-invented-input-config/1` with the exact public/metric packet and an
immutable fixture reference. The fixture supplies only `rows` and `context` under
`polar.obs158-invented-input/1`; it cannot replace the frozen roster/calendar/
timezone/public profile. The same 39,974-cell checker, zero-volume count and
conversion apply. Invented outputs are separately labelled and namespaced.
For isolated invented fixtures, explicit `calendar_ref` and `timezone_ref` may
relocate metadata to a task-owned mounted directory, but their exact hashes and
sizes must equal the frozen protocol. No calendar, timezone or profile changes
are admitted. Retained inputs keep the accepted original graph/pointer loader.

The currently qualified config2 launcher mounts six small immutable references
and a task output directory. It does not mount a whole retained archive or a
persistent service root. An invented wrapper can materialize its precommitted
synthetic fixture and identical public metadata under `/polar-output` before the
service call. A later retained operation requires an explicitly assigned,
independently reviewed compatible data/artifact mount binding; config2 alone
does not supply that function. No private data is baked into an image here and
no transport tool is replaced by this implementation.

Before native import the observed config2 launcher receipt must match the actual
Linux/arm64 image, configured/actual UID10001, complete current source map,
source-build receipt and input config bytes. Source overlays are unsupported.
The established composition proof and all its runtime files/package versions are
checked through the existing Gym runtime verifier. A spawned native child checks
current source hashes again before importing the engine. A source/code/runtime
reference mismatch fails closed. These checks verify the selected bytes; a caller
reference is not a substitute for actual independent review or source fitness.

`Dockerfile.obs158` reuses the qualified local dependency image. Its isolated
build context needs the existing SHA5d7f composition proof copied byte-for-byte as
`obs158-composition-proof.json`; the recipe verifies it and packages it read-only
at `/app/runtime/obs158-composition-proof.json`. This metadata is 1,525,809 bytes,
so it cannot be one of config2's 1 MiB mounted references. Packaging it avoids a
launcher change or an unqualified reduced proof. It is outside application source
and contains no dataset or credentials. No dependency/compiler reinstall or new
runtime-qualification claim is implied by source-image assembly.

`polar.obs158-controls-binding/1` binds the exact public/metric, source-map,
output-contract and composition hashes, with bounded reference files for all
four named engineering check categories. These references identify the selected
controls/evidence; they do not execute an oracle or copy OpenRig task status.
Actual qualification remains with the independent owners. In particular, the
scoped old cent control cannot be labelled full 158-name qualification.

An external `polar.obs158-execution-authorization/1` binds the exact execution
bindings hash and canonical artifact root, permitted operations, finite job
limits, purpose/family and packet-start count. Purposes are
`FIXED_PAIR_AND_REPLAY` or `INVENTED_FIXED_PAIR`. Job limits explicitly include
total wall time, native wall time and at least five seconds of cleanup reserve;
they are per-job bounds, not lifetime/project CPU quotas. The outer assigned
launcher must bound the whole command, including possible filesystem failures.
Native process supervision alone does not promise to interrupt blocked host IO.

## Native channels, cash and units

Each strategy gets a new engine, account, fee/fill/latency models and a physical
issuer nonce, because Nautilus account-factory registrations are process-global.
Native symbols are ordinal internal identifiers; exact source aliases remain a
separate dictionary join. No economic security identity is inferred.
Each engine receives one streaming batch and an explicit end at the frozen last
sample. Pinned 1.231 swallows `AccountError` in non-streaming mode; streaming
preserves that exception for the private worker diagnostic. Explicit `end()`
flushes only through the same final boundary. This adds no second engine call,
future observation or terminal liquidation.

Only modeled opening quotes enter native matching; bar/trade matching are off.
All full OHLCV rows are losslessly round-tripped through the pinned 1.231 Bar
type, but zero full bars enter matching. All 158 actual cached open quotes must
be present with correct timestamps/prices before the quote barrier. All 158
actual cached mark updates must be present at C before the C+1 barrier; sampling
is C+100. Private marks may value the retrospective account, while the strategy
only receives the qualified snapshot and full-bar channel at its delayed K+1
barrier. A decision sizes from its own stored snapshot value/closes, never from
the current private mark or upcoming open. Outside-window instructions remain
visible without execution; buy-and-hold records later decisions as skipped.

Intents freeze whole-share targets at D. SELL slots are Q+100+i, BUY slots
Q+1000+i in lexical order. Each route requires the previous order acknowledged
and the actual native cash/holdings reconciled. The accepted `settled_fill`
primitive applies depth, holdings and fee-aware rounded cash caps. Zero routes
charge no fee. All remainders expire at that open; none are carried or retried.
Native fills, quantities, prices, commissions and timestamps must match the plan.
Expected cash after a fill is labelled separately from the cash actually
observed/reconciled at the next phase. Reconciliation is required for every fill.

Cash uses the qualified exact-cent account extension. Physical positions use
per-position HALF_EVEN, preserving exact marks and residuals. Stock native float
notional is not canonical account valuation. Known forward splits change the
physical/native unit factor exactly once before the final mark, preserving value
with raw source prices and an equivalent native mark. The fixed profile forbids
post-split trades. Dividends remain excluded; no terminal liquidation is added.

## Complete output and acyclic identity

The prospective closed file/record/order/numeric contract is
`obs158_output_schema.json`. Every emitted semantic field is hashed; the five
semantic files are `converted.json`, `preflight.json`, `source-context.json`,
`simulation.json` and `evaluation.json`. Coverage/excluded42 records and all960
zero-volume flags remain. Imported immutable source-row provenance is dataset
content, not an execution timestamp. Modeling clocks/barriers/acks also remain
semantic; they must not be dropped after a mismatch.

Canonical bytes are ASCII-escaped, sorted-key JSON with compact separators,
no floats/NaN/Infinity and one final LF. Arrays have their fixed declared order.
The manifest contains the protocol/code/runtime/schema/input-content bindings
and every complete file's SHA256/byte length. It contains no own hash or ID.
`experiment_id = "obs158-" + SHA256(canonical_manifest_bytes)`. Replay is a fresh
computation and must match the full manifest and all five files byte-for-byte.

Execution UUIDs, actual timestamps/PIDs, image/Git/container IDs, output roots,
authorization/reference paths and random native issuer IDs are physical attempt
records outside that semantic identity. Complete code and frozen runtime content
hashes remain semantic. No source-field, cost, status, diagnostic or modeled time
is excluded after seeing results. Scalar paired deltas subtract emitted
Decimal50 scalars under Decimal50; daily paired differences use exact fractions.

The fixed retained family is shared across code/build/authorization changes and
permits at most two admitted packet starts, including failures. The second is
only an exact replay of the first successful packet. A start is durably debited
before retained data loading/native work; it is never refunded. A full packet
contains two strategy engines. No automatic retry, third packet, alternate root
reset or reuse of the exhausted old Gym family is implemented. A killed command
can leave an UNFINALIZED start; that remains visible and consumes its start.

The native child writes a bounded private result instead of sending an unbounded
IPC payload. Timeouts terminate/kill only that owned child; failed/partial output
remains an attempt artifact. Worker errors retain a bounded traceback privately;
reports expose a safe code. Publication reuses immutable HistoryStore staging,
hash/readback, rename, fsync and root storage checks. Replay mismatches and all
failures remain recorded; successful processing is not a financial PASS.

## Validation status at source delivery

The existing Part A independent tests and exact single-name native-cent PASS
remain their scoped evidence. Full Part B source has only static parse/diff
checks by its author, with no imports, component executions, new native scenarios,
retained operand reads, model runs, DB/service mutation or provider access.
Independent source/numeric/native/process/publication controls and a compatible
new immutable image must precede applicable later operations. Source/schema
delivery itself grants zero computations or retained starts.
