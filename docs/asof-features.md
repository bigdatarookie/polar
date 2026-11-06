# Offline as-of feature view

`polar asof-features FILE --decision-at 2024-01-02T11:00:00Z` reads a bounded
synthetic envelope and prints one JSON view. No registration, settings/secret
loading, service construction, database or network access occurs on this path.
The only file operation is a read of at most 1 MiB plus one size-check byte.

The pure operation is `polar.feature_view.asof_features(raw_bytes: bytes,
decision_at: str) -> dict`. The cutoff must parse as a timezone-aware ISO datetime
with zero UTC offset; output normalizes it to UTC `Z`. Existing Feature and
Provenance validators govern record decimal strings, UTC and provenance order.

Input example (the selected value is the observed decimal string zero):

```json
{
  "schema_version": "polar.synthetic-feature-view-input/1",
  "synthetic": true,
  "timing_model": "synthetic_replay",
  "features": [{
    "instrument_id": "A",
    "feature_id": "f",
    "value": "0",
    "event_time": "2024-01-01T21:00:00Z",
    "effective_time": "2024-01-01T21:00:00Z",
    "published_at": "2024-01-02T10:00:00Z",
    "available_at": "2024-01-02T10:00:00Z",
    "ingested_at": "2024-01-02T10:00:00Z",
    "source_revision": "opaque-r1"
  }]
}
```

Limits: 1 MiB input, <=1000 records, nonempty instrument/feature/revision IDs
of <=64 characters, no extra fields. Existing finite Decimal-string bounds
apply. Multiple instruments are allowed only in this standalone envelope.
No implicit truncation, imputation or formula fitting is performed.

Selection is per `(instrument_id, feature_id, event_time, effective_time)`.
All five clocks must be <= cutoff; equality is eligible. For each observation,
choose the unique eligible maximum of publication/availability/ingestion.
Duplicate observation+revision is rejected regardless of eligibility. Equal
winning clocks are ambiguous and reject the whole request. Equal lower clocks
may both be superseded by a later unique winner. Revision spelling never chooses
the winner. Event/effect times remain part of observation identity.

Result schema `polar.asof-feature-view/1` includes:

- `decision_at`, exact `source_sha256` and `canonical_input_hash`. Canonical input
  identity hashes the validated envelope with its feature records sorted by
  canonical record bytes. It is invariant to record order/JSON formatting; it
  includes excluded revisions and excludes the separate cutoff argument.
- `selected`: full normalized Feature-shaped records, sorted by observation key.
  Decimal values remain strings. `diagnostics`: one observation-key/revision entry
  per supplied record, sorted by observation key and revision spelling; reasons
  are `SELECTED`, `SUPERSEDED` or `NOT_AVAILABLE_AT_DECISION`. Diagnostic sorting
  uses spelling only for presentation, never for revision priority.
- `status`: `NO_DATA` for an empty envelope; `NO_ELIGIBLE_FEATURES` for a nonempty
  envelope with no eligible record; otherwise `SELECTED`. These are distinct from
  a selected value of `"0"`. Both output lists are empty only for no input records;
  excluded records remain audited when no selection is possible.
- `synthetic=true`, `timing_model=synthetic_replay`,
  `source_qualification=SYNTHETIC_ONLY`, `investment_evaluation=NOT_RUN`.

Same canonical input and cutoff yield identical selected records, diagnostics
and canonical input hash; source-byte hash may differ. Output has at most 1000
selected records and 1000 diagnostics; all string fields are bounded. No raw
payload appears in failure diagnostics. Public `FeatureViewError.code` values
are `INVALID_INPUT_TYPE`, `INPUT_TOO_LARGE`, `INVALID_DECISION_AT`,
`INVALID_FEATURE_INPUT`, `DUPLICATE_REVISION` and `AMBIGUOUS_REVISION`.
The CLI exits 1 with `{"status":"ERROR","code":"..."}` on stderr and no view
on failure; unreadable files use `INPUT_READ_ERROR`.

This is a synthetic mechanics/audit view, not historical data qualification,
an action-event API or a financial verdict. The runtime Dataset schema and
`temporal.eligible_feature` retain their existing contracts and are not replaced.
