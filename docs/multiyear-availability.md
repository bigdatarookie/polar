# Retained multiyear availability input

The existing HYP003 availability writer accepts a normalized
polar.multiyear-source-content/1 bundle directly. It does not fabricate a RAW
source-plan/parent ledger, recapture source or change the bundle. Existing generic
HYP003 preparation still rejects this adapter. Existing RAW/collection paths,
population/reference grid, state meanings and financial nonclaims remain.

Use the same availability-config/1 input fields: directory, manifest,
manifest_sha256 and links_ref. The hash-bound links JSON must have schema
polar.hyp003-multiyear-source-record-links/1 and links containing exactly:
population_record_id, source_symbol, source_manifest_sha256. The last field must
match the exact supplied multiyear manifest hash. Each selected literal alias
must resolve to exactly one supplied population record, equal that record's
literal_symbol, with no duplicate links. This establishes source-record evidence
only; it does not infer an economic identity or merge same-ticker records.

The safe reader verifies declared normalized members, byte lengths and hashes.
source-profiles.json preserves each request's exact parameters, request_ordinal,
chunk_index, expected dates and inclusive provider civil-date interval. Profiles
and body references must match each row's ordinal/chunk/alias/body hash. Each row
is associated once with its actual request profile; same-alias chunks do not
multiply observations. Transport state stays UNKNOWN and profile binding
DECLARED_NOT_VERIFIED. Canonical/source-plan job IDs remain null; producer quality
coverage labels are retained separately and are not RAW producer-job proof.

The legacy top-level source_array/body SHA/zero-based ordinal become a consumer
source_reference without rewriting source bytes. The array marker is interpreted
literally (bars. plus the whole alias, including punctuation). Body bytes outside
the normalized bundle are not read or reconstructed, so a valid declared pointer
is REFERENCED_ONLY, not VERIFIED_EXACT_BODY_POSITION. Original metadata is also
preserved in source_metadata: request/chunk/aggregation/quality reasons/mapping/
economic-ID/causal-K and original pointer declarations. Null observed clocks stay
null; all observations, including outside-grid dates, are retained. Price/volume
tokens are not floated, scaled or copied into availability cells.

The wire-definition/2 describes this additive source format and metadata; content
schema remains source-availability-content/1 with a new code/source-bound immutable
revision. A prior supported-input index is never overwritten or relabelled. DE
builds a new index from exact supported and newly qualified source revisions,
then owns consumer/source coverage assessment. Presence of a row, calendar date,
request or manifest is not coverage, known-by, action or financial acceptance.
