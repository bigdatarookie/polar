# Offline dataset inspection

Run `polar inspect-dataset FILE` before registration. This reads at most 1 MiB
plus one size-check byte and emits one JSON object, without loading service
settings, secrets or a database connection. It does not write the input or
register a dataset. The existing service verbs retain their configuration path.

`polar.data_quality.inspect_dataset(raw_bytes: bytes) -> dict` is the reusable
pure operation. Inputs over 1 MiB fail before parsing. Existing `Dataset` schema
validation remains authoritative; there are no repairs or new accepted formats.
Failures raise `InspectionError` with `INVALID_INPUT_TYPE`, `INPUT_TOO_LARGE` or
`INVALID_DATASET`. CLI failures exit 1 with sanitized JSON on stderr; unreadable
files use `INPUT_READ_ERROR`. Input values and paths are never echoed in these
diagnostics.

The return schema is `polar.dataset-quality/1`:

- `dataset_id` and `content_hash` use the validated model's canonical JSON, exactly
  as registration does. `source_sha256` hashes the exact input bytes. Formatting
  changes affect only source identity; semantic content changes affect canonical
  identity. Decimal price strings are validated and canonicalized by the existing
  model, never converted to binary floats.
- `dataset_schema_version`, `synthetic`, `timing_model`, `price_basis` and
  `market_profile` describe the validated input. No source rows are returned.
- `counts` includes expected sessions, present bars, observed bars, settlement-only
  bars and missing price sessions. Missing includes both absent and explicitly
  MISSING bars. Settlement-only bars are neither observed nor missing. For this
  one-instrument schema, observed + settlement-only + missing = expected sessions.
- `actions_by_kind` contains zero-inclusive counts for the three supported kinds.
  `features` counts distinct feature IDs; `feature_revisions` counts distinct
  (feature ID, source revision) records, whose uniqueness the schema validates.
- `observed_fraction` is observed/expected, a decimal string rounded with fixed
  precision 28, or null when expected is zero. Settlement is excluded from the
  numerator but retained in the session denominator. `missing_fraction` uses
  missing/expected with the same precision and denominator rule. Six declared
  sessions with no bars therefore yield fractions `"0"` and `"1"`, respectively.
- `status` is `NO_DATA` when the bar tape is empty, otherwise `INSPECTED`. Sessions
  without bars still contribute missing counts; a wholly empty tape/calendar has
  zero counts and a null fraction. `INSPECTED` means schema validation and counting
  completed, without asserting data completeness or financial acceptance.
- `source_qualification` is always `SYNTHETIC_ONLY`; `investment_evaluation` is
  always `NOT_RUN`. This operation establishes neither historical availability
  nor investment performance.

JSON output is bounded by six times the 1 MiB input limit plus 4 KiB, including
Unicode escaping: market metadata comes from bounded input, and collection rows
are replaced with scalar counts.
Identical bytes yield identical results. There are no wall-clock fields or mutable
acceptance decisions. Independent exact-commit review owns acceptance.

## Persisted inspection

After registration, `GET /v1/datasets/ID` and `polar dataset ID` use the same
`Service.dataset` operation. The detail object contains `id`, `content_hash`,
`source_hash`, `registered_at` and `inspection` (the complete
`polar.dataset-quality/1` object described above). `registered_at` is the actual
PostgreSQL registration timestamp; it is separate from synthetic replay times.
API timestamps use ISO 8601; CLI timestamps parse as the same instant.

Detail always inspects retained original bytes, then verifies their SHA-256,
canonical hash and ID against the registered body/hash/ID. It returns no raw
source bytes or rows. Canonical-equivalent registration preserves the first
stored bytes, source hash and registration time; resubmission formatting does
not replace that identity. Inspection is read-only and does not modify the row
or grant acceptance. Stored quality is recomputed on read using the installed
inspection version; dataset records and schema version 1 are unchanged.

Missing IDs return HTTP 404 `DATASET_NOT_FOUND`. A binding mismatch or invalid
retained source returns HTTP 409 `DATASET_INTEGRITY_ERROR`, without partial
detail, validation messages or source values. The CLI exits 1 with
`{"status":"ERROR","code":"DATASET_NOT_FOUND"}` or
`{"status":"ERROR","code":"DATASET_INTEGRITY_ERROR"}` on stderr. Other dependency
failures keep the existing sanitized API/CLI behavior.

`polar datasets` and `polar runs` retain defaults limit 10/offset 0 and accept
`--limit` (1..10) and `--offset` (nonnegative), matching the API. `runs` also
accepts `--dataset-id`, matching the API's `dataset_id` filter. Dataset ordering
remains ID ascending; run ordering remains creation time then ID ascending.
Empty pages return `[]`; invalid CLI bounds exit 2 before loading settings,
while invalid API bounds return 422. There is no unbounded listing mode.

Component tests use controlled retained-row doubles for corruption; they never
corrupt a live database. The optional zero-job PostgreSQL integration test is
`tests/test_dataset_detail_postgres.py`. It requires an explicitly provisioned
empty database named `polar_test_*` through `POLAR_DATASET_TEST_DATABASE_URL`
and refuses a nonempty database. Running component checks does not establish
PostgreSQL, container recreation or preserved-report/attempt-history proof;
independent runtime qualification must record those effects separately.
