# Vendor all-adjusted reference history import

The existing ImportService/ImportStore executor accepts the versioned adapter
`alpaca-all-adjusted-sip-broad100/1`. Generic `import-plan`, `import-status`,
`import-result`, `import-execute`, `import-resume`, terminal readback and consumer
commands remain the interface. This profile does not acquire data on import or
planning. Provider execution requires the bound operation and qualified source.

The closed planning config contains schema `polar.adjusted-sip-import-config/1`,
`adapter`, `mode` (`fixture` or `provider`), `scope_ref` (`path`, `sha256`) and
`seed_refs`. Provider mode accepts only the frozen broad100 scope SHA
`d123cb78e0e1e5e091bbc6de04e1693ebc08181775eb72ebe3434fd89d21c077`.
It retains the scope's literal alias order and every source-record relation.
Multiple listing records stay separate inside each literal request relation;
`population_record_id` at the request level is null, never an economic identity.

Requests use vendor adjustment `all`, SIP/USD/1Day, asof 2020-09-02,
2016-01-04 inclusive through 2026-11-07 exclusive, 10000 bars/page. The profile
admits 100 jobs, 200 GETs, two pages/job, 1 MiB/body, 200 MiB total bodies,
1800 seconds original wall, one-second start spacing, 45 seconds/request,
concurrency one and no retries or redirects. The scope reserves 2 GiB within
the existing shared artifact-store limit, with 64 MiB for terminal evidence.
Materialization reserves 120 seconds of the same original deadline. These are
internal finite bounds, not statements of provider API limits.

Plan IDs start `adjustedsip100-` (or `adjustedsip100fixture-`); storage lives in
`imports-adjustedsip100-v1/<scope hash>` (fixture namespace separately).
Canonical job identity includes the new adapter version and exact request,
including adjustment. Evidence schemas use `polar.adjusted-sip-*/1` and success
kinds `ADJUSTED_COMPLETE` / `ADJUSTED_NO_ROWS`. Only exact adjusted seeds with
schema `polar.adjusted-sip-seed/1` and a complete cursor chain can be reused.
Raw requests, raw caches and raw seeds are not equivalent. Existing raw job IDs,
store names, schemas and source fields retain their meaning. Old execution plans
still require their exact source projection; this change does not bypass that
check or reset old counters.

Source output is partitioned by encoded bytes using the existing materializer.
The collection schema is `polar.vendor-all-adjusted-source-collection/1` and each
part's manifest is `polar.vendor-all-adjusted-source-content/1`. Each row carries
`source_fields_exact_tokens`, `vendor_adjusted_open/high/low/close/volume`, exact
body/row/page provenance, and its full parent relation. Numeric lexemes are not
rounded. Price basis is `VENDOR_ALL_ADJUSTED_REFERENCE`; volume basis is
`VENDOR_RESPONSE_UNITS_ADJUSTMENT_ALL_NOT_RAW_SHARES`. As-of is alias mapping,
not a historical vintage. Observed historical availability and economic ID remain
null. Adjustment completeness, raw-share equivalence and investor total return
are not established. This schema must not be passed to a raw-price adapter.

The existing executor preserves durable request-before-GET and body-before-result
ordering, unknown-inflight charging, malformed/extra-symbol/cursor failures,
auth/rate-limit pauses, cumulative counters and original deadline on resume.
Terminal manifest publication remains last. Empty, error and unknown relations
remain represented; no coverage-based replacement or scientific admission occurs.
Author synthetic qualification and independent technical review precede the DE
provider operation; broad50 remains unmet until actual source-purpose checks.
