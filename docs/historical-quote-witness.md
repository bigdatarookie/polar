# Single historical quote schema/access witness

This source-only interface supports one owner-selected one-second timestamp
interval at the [Alpaca single-symbol historical quotes endpoint](https://docs.alpaca.markets/us/reference/stockquotesingle-1).
It is not the bars adapter or a spread/cost estimator. Exact request/status/error,
raw body, lexical numeric tokens, field types/condition arrays and timestamp strings
are retained privately. Quote event timestamps are not receipt times or proof of
historical availability. Source units are uncalibrated; never compare them to
vendor-adjusted synthetic reference prices as a calibrated spread.

CLI uses the existing safe file and immutable HistoryStore publication primitives,
without a DB migration, worker/API/serving replacement, scheduler or retry loop:

```
python -m polar.import_quote_witness prepare SEED.json --artifact-root ABS_EXISTING_TASK_ROOT > CONFIG.json
python -m polar.import_quote_witness execute CONFIG.json --artifact-root ABS_EXISTING_TASK_ROOT
```

Seed exact fields: schema `polar.quote-witness-seed/1`, mode `RETAINED`, scope_ref,
code_revision (qualified40hex), runtime_image_id, qualification_ref, review_ref.
File references are absolute path/SHA256/bytes. scope_ref pins the existing
`polar.historical-quote-interface-gap/1` metadata, including exact owner-selection
ref, request and all36 date/symbol slots with only one PENDING_INTERFACE and
35NOT_REQUESTED. Owner-selection request and hard limits must match. Qualification
is the exact qualified source's full official CI PASS; review_ref pins the actual
independent affected GO. It is a JSON polar.quote-witness-technical-disposition/1
with exactly schema, disposition PASS, role INDEPENDENT_TECHNICAL_QA, independent
true, author_id platform-engineer@polar-rig, distinct qualified-seat reviewer_id,
candidate_sha, scope_sha256, qualification_sha256 and report_ref. Hashes must match
the seed's exact code candidate, selected scope and qualification file bytes;
report_ref pins the independent human-readable report. The same actual QA owner
emits this compatible binding after its normal review, not a new approval wave.
The record expresses reviewer identity/independence under existing custody; it is
not cryptographic authentication of arbitrary claimed identities. Malformed,
negative, self-review or different-subject bindings reject before preparation.
Prepare returns code/root binding; it performs no GET or
credential read. Actual retained execute additionally requires Linux/Python3.13.18,
exact POLAR_RUNTIME_IMAGE_ID, task bytecode prefix/writes disabled. SRE retains
actual private credential/runtime/root/capacity custody; this file does not grant
new source rights, account changes or science execution.

Fixed HTTPS host, one literal symbol, SIP/USD, mapping-asof, asc/limit10, one-second
window. Existing credential reference is used inside the subprocess only; no
credential changes, output, hashes or copies. Child has40s socket timeout, parent
45s wall bound and joined cleanup. One GET maximum, zero retries, no redirect or
pagination follow-up. Network failure/denied/empty is a useful terminal witness.
Any nonnull cursor is PARTIAL_NO_FOLLOWUP. Body capture never exceeds1MiB; reaching
that ceiling is conservatively completeness UNKNOWN, even if the true body may
end exactly there. No gap filling, IEX fallback, timestamp shift or36-slot expansion.

An immutable start precedes the possible GET. Family is owner-selection hash plus
exact request, stable across source/config changes; re-execution after any start
is rejected without a request. Interruption with no response stays UNKNOWN, never
an unspent retry. Raw response/status/error is published before optional parsing.
Finish retains all36 slots and null historical availability; actual GET count can
remain UNKNOWN without a response, distinct from the conservative one-attempt
debit. Existing saved A3 records, fees, financial judgment and spent scientific
allocations remain unchanged. This observation does not calibrate modeled USD1+
10bps or certify auction/depth/market coverage.

Author controls are invented/mocked only; INVENTED execute requires an explicitly
synthetic transport and cannot fall through to HttpTransport. No retained provider
or credential call is needed for source/CI qualification. Actual first use remains
with the existing DE/SRE consumer after ordinary independent QA and integration.
