# Saved research delivery

The existing PostgreSQL Registry holds delivery metadata; the existing worker
publishes only already-saved public projections through ResearchResults. This
path does not create a run, attempt, model, native account or optimizer call.
Existing producers continue their automatic preliminary result publication.

Submit to the owner-local API with POST /v1/research/deliveries:

    {"schema_version":"polar.research-delivery/1","kind":"RESULT",
     "display_scope":"OWNER_LOCAL","content_sha256":"<canonical-result-sha256>",
     "payload":{...canonical polar.research-result/1...}}

For an independent assessment use kind ASSESSMENT, the same result content hash,
and the exact polar.research-review/1 payload. Canonical bytes are sorted-key,
compact ASCII JSON with no trailing newline, exactly the existing result store
convention. The response is 202 with a deterministic delivery ID, state and
receipt, never the payload or lease token. GET /v1/research/deliveries/{id} reads
the receipt. The trusted local publisher remains responsible for lawful display
rights and sanitized content. OWNER_LOCAL is an explicit scope restriction, not
an entitlement certification. This endpoint is not an internet upload service.
No raw source objects, private operands, physical paths or executable commands
belong in this wire; existing strict result/review validation remains enforced.

Apply the additive migration using the existing Registry.migrate command before
updating the existing worker. API artifact mounts stay read-only; only the worker
needs the existing writable artifact store. The original schema/1 checksum and
financial runs/attempts are unchanged. No new database or delivery controller is
required. Missing/mismatched extension returns dependency failure, not success.

States are QUEUED, DELIVERING, WAITING_FOR_RESULT, DELIVERED and REJECTED. An
assessment arriving first waits for the exact subject. A wrong hash, malformed
record or self-review fails explicitly. A process loss after atomic publication
but before acknowledgement leaves a lease to reclaim; replay uses exactly the
same saved bytes and existing idempotent publication. A UUID fences stale
acknowledgements. Delivery retries are not financial attempts. Terminal rows are
immutable; repeating the identical request returns the same state. Dependency
failure retains the lease for bounded recovery by the existing worker lifecycle.
The worker still services legacy runs independently of delivery errors.

GET /v1/research/revision is a cheap discovery hint over immutable result/review
publication identities. It returns schema_version polar.research-revision/1,
revision (64 lowercase hex), result_count and assessment_count. Partial staging
is ignored and unsafe namespace entries fail. This hint is not a payload integrity
or acceptance verdict: catalog/detail still validate canonical bytes and all
bindings. A concurrent atomic rename may appear on the following poll.

The ordinary UI uses this revision hint for automatic result and assessment
refresh; existing detail assessments remain separate technical/product/financial
dimensions. A producer screen or delivery receipt cannot become independent QA
or financial PASS. Duplicate delivery must preserve existing negative judgments.

Queued, first/last started, delivered and finished timestamps measure delivery
latency. A result's calculation completion and a browser's committed refresh are
separate evidence clocks; report UNKNOWN when not actually observed. Do not infer
calculation-to-publication latency from queued-to-delivered latency.
