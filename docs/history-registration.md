# Private captured-history registration

This component verifies an already captured `polar.private-history-bundle/1` archive, publishes its immutable content and receipt, and records a small catalog in the existing PostgreSQL database. It does not fetch data, rebuild normalization, add HTTP routes, calculate indicators or run an experiment. Actual PostgreSQL migration/registration and runtime qualification require the assigned operator and independent system checks.

The first profile is the four EODHD public-demo symbols AAPL/AMZN/TSLA/VTI, for sole-owner private noncommercial use only. Source payloads and data-containing outputs stay outside Git/public delivery. Do not use this path for business, other-human access or redistribution. The verifier is deliberately bounded to the first captured profile (four mapped IDs, up to 5000 rows per asset, 20000 total, 4 MiB per file, 64 MiB per archive). It rejects quarantine, partial archives, unexpected files, duplicate JSON keys/dates, numeric-domain errors, token mismatches, invalid receipts, hash changes, path traversal and symlinks. The manifest digest is a required external trust pin, not a digest silently read from the archive itself.

Prices/volume remain exact original JSON numeric-token strings. OHLC is raw/unadjusted; adjusted close includes provider split/dividend adjustments; volume is split-adjusted shares. These are separate bases. Zero volume remains observed zero. Missing historical clocks stay null, calendar continuity remains unverified, identity mapping remains current-only. Structural/chart readiness with these limits does not imply causal/PIT, financial, original-hypothesis or Gym qualification.

The dataset revision hashes the captured canonical content. Actual acquisition/import clocks belong to separately hashed immutable receipts. Replaying the same content and receipt is idempotent. A new receipt for identical content is retained without replacing the first receipt or its catalog manifest identity. Source/config/mapping/normalized content changes produce a different revision. Publication stores content once under `history/<revision>` and operational evidence under `history-receipts/<receipt-id>`. A hashed publication inventory binds both, and catalog lookups verify it against PostgreSQL's retained hash. No caller-provided filesystem path is returned in catalog output.

Files are staged, quota-checked, fsynced and published before PostgreSQL references them. Publication failure cannot admit partial data; a later database failure can leave a complete unreferenced bundle, which a retry can verify and reuse. Only the current call's unpublished staging directory is removed automatically. Existing artifacts are never cleaned up. The root lock serializes history publishers; the PG advisory transaction lock serializes history metadata admission. Aggregate checks reserve one MiB for metadata and include existing filesystem and database sizes, but do not claim a globally enforced quota against unrelated writers.

Legacy `schema.sql`, its version-1 checksum, `Registry`, `ArtifactStore`, existing service/worker readiness and fixture/result routes are unchanged. The separate `history_schema.sql` extension has its own version/checksum and transactional locked initialization in the same database. Unknown/partial extension state is refused, never reset. Existing legacy metadata must already pass its checks.

Explicit operator commands (no automatic startup migration):

```sh
polar history-migrate
polar history-register /private/path/to/captured-bundle --manifest-sha256 EXTERNALLY_VERIFIED_SHA256
polar history-catalog --limit 50
polar history-revision DATASET_ID HISTREV_ID
```

Catalog pagination returns a sequence snapshot and opaque cursor; continue with the same limit via `--cursor`. Results stay under one MiB and 50 revisions per page. It returns summaries and pinned receipt/manifest identities, never bars. `runtime_qualification=NOT_RUN` explicitly separates registration from independent assembled-system qualification. CLI errors emit stable sanitized codes, not SQL, credentials, source bodies or local paths. No new readiness/HTTP route is part of this PR.

Invented-data component tests cover exact lexical numbers, hostile ambient Decimal settings, tampering, duplicates, partial/symlink archives, quotas, immutable replay, first receipt retention, and publication-before-database failure/retry. Database doubles are not PostgreSQL evidence. The real retained private archive must be independently bound by its external manifest hash; actual schema/trigger/legacy-worker compatibility and registration/restart recovery remain independent runtime checks.
