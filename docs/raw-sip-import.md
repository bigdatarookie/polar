# First-unit raw-SIP import

The `alpaca-raw-sip-first-unit/1` adapter extends `ImportService` and `ImportStore`.
The qualified OpenFIGI core remains a separate adapter. Raw bars never use its
metadata result kinds, retry rules, credentials or namespace.

The `polar.raw-sip-import-config/1` config contains `adapter`, `mode`
(`fixture` or `provider`), `unit_ref`, `reuse_ref`, and `seed_refs`. Each ref is
an absolute local `{path, sha256}` object. Provider mode accepts only the frozen
first-unit config digest `aded6413f66d7b2f2857de50df99cd75b6911325de34793bee9450dba58636ef`
and metadata reuse comparison `1d6c7fcb7362cac1186bab53583c28c1e23339dcedf1ac6bfcc64af606964b3a`.
Those private files and their job roster do not belong in Git.

Use the existing `polar import-plan`, `import-status`, `import-result`,
`import-execute`, `import-attempt-path`, `import-attempts`, `import-control`,
`import-terminal` and `import-consume` commands. Plan IDs start with `rawsip-`
or `rawsipfixture-`. No DB connection, new service or HTTP API is needed.
Planning reads supplied files and writes only local immutable loader records.

`import-execute` requires either an explicit `polar.raw-sip-fixture/1` fixture
or `--network` plus a separately bound operation scope. There is no network
fallback from fixture mode. The operation scope schema is
`polar.raw-sip-execution-authority/1`: `unit_sha256`, `source_projection`,
`python_sha256`, nonempty `binding_refs`, `attempt_id`, `credential_reference`
and `terminal_owner`. Operations must bind actual authorization, accepted source,
host/storage/rights and terminal-owner recovery in those refs. The application
checks their hashes; a schema-valid file does not confer authority.
This source task does not authorize a provider request.

The operation-only child reads `key_id`/`secret_key` at the authorized private
credential reference. Keys never enter command arguments, loader records,
responses or exception logs. Only the fixed Alpaca stock-bars HTTPS endpoint,
one-symbol raw/SIP/USD/1Day profile and a validated opaque pagination cursor are
accepted. Redirects and failures are retained without automatic retries.

The 20 jobs, 40 GETs (including pages/failures), two pages/job, 1 MiB/body,
40 MiB aggregate, 900 original seconds, one executor and one-second start spacing
are **internal first-unit choices**, not provider entitlements or user quotas.
Revising them requires an explicitly versioned finite aggregate binding under
the owning DE/DevOps assignment. New plans and attempts in this scope inherit
the stored deadline, charged request starts and bodies. This version does not
silently start a second unit or manufacture a fresh budget. It does not impose
these limits on unrelated future operations.

Each GET start is durable before transport. Exact body bytes are content addressed
before the response, result commit or checkpoint. A saved response can be replayed
without network; a start with no response is `UNKNOWN_IN_FLIGHT` and cannot be
implicitly reissued. Complete empty responses are `RAW_NO_ROWS`, not metadata
no-match, zero prices or delisting. Partial pages, repeated cursors, page exhaustion,
auth pauses, request failures and unreceived work remain explicit. Only complete
typed results are reusable. Conflicting body versions never get an automatic winner.

Legacy migration is explicit: each `polar.raw-sip-seed/1` has exact `request`,
`completeness: COMPLETE`, nonempty `provenance`, and ordered `pages` containing
`request_cursor` and `body_ref`. The adapter validates every body/hash, request
identity and complete cursor chain before admitting a cache result. Symbol/date
overlap is not exact request reuse. Partial or unknown legacy scopes are not
accepted as complete seeds. Existing retained legacy captures have no implicit
canonical raw-GET cache format. The metadata-only declared-profile comparison
found no exact first-unit matches; this is not a global cache-absence claim.

Attempts publish an immutable `content-manifest.json` last, using the existing
terminal validation and idempotent consumer receipt. The native wake scanner's
previous malformed-wrapper limitation is unchanged; the consumer/fallback must
validate the exact manifest, attempt path and hash before accepting a wake.
No exactly-once native-delivery claim is made.

The included partial source envelope uses `polar.partial-raw-pv-source-content/1`
with `bars.ndjson`, `parent-coverage-ledger.ndjson`, `source-plan.json`,
`coverage.json` and exact parseable raw-body members. All returned symbols, fields,
numeric tokens, body/array/row/page pointers and original job/population relations
are retained. Provider timestamp date labels are descriptive; they do not establish
exchange sessions or event clocks. Out-of-window rows remain visible. Historical
publication, availability and event clocks stay null; capture time never fills them.
Coverage denominators remain declared expected scope, not returned row counts.

Malformed/non-JSON bodies remain in the outer terminal capture graph, outside the
parseable partial-source members. A source-envelope size/storage failure leaves an
explicit source gap and the raw evidence, rather than refetching. The existing
32 MiB immutable-record limit applies to each normalized member; larger deliveries
need compatible partitioning/version changes. Structural admission by the offline
HYP003 consumer is separate from source-field, calendar, identity, actions,
economic, research or financial fitness. No feature, return or market calculation
is performed here.
