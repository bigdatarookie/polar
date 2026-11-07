# Supplied label maturity at a fit cutoff

`polar.label_view.label_maturity_view(raw_bytes, fit_cutoff, *, limit)` is a pure
synthetic supplied-label operation. It does not compute returns, fit a model,
qualify target values or certify training admission. No CLI/API/service added.

```python
import json
from polar.label_view import label_maturity_view

raw = json.dumps({
    "schema_version": "polar.synthetic-label-input/1",
    "synthetic": True, "timing_model": "synthetic_replay",
    "labels": [{
        "instrument_id": "A", "label_id": "opening-return", "definition_version": "v1",
        "decision_at": "2024-01-02T21:00:00Z",
        "target_start_at": "2024-01-03T14:30:00Z",
        "target_end_at": "2024-01-10T14:30:00Z",
        "source_revision": "r1",
        "published_at": "2024-01-10T14:30:01Z",
        "available_at": "2024-01-10T14:30:01Z",
        "ingested_at": "2024-01-10T14:30:02Z",
        "value_unit": "fraction", "value": "0"
    }]
}).encode()
assert label_maturity_view(raw, "2024-01-10T14:30:01Z", limit=1)["status"] == "NO_MATURE_LABELS"
assert label_maturity_view(raw, "2024-01-10T14:30:02Z", limit=1)["selected"][0]["value"] == "0"
```

The input schema is `polar.synthetic-label-input/1`; output is
`polar.label-maturity-view/1`. Require explicit true synthetic marker, replay
timing and labels list. IDs/revision/unit are nonempty strings <=64 characters;
all six timestamps and cutoff are explicit `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` or
`+00:00` strings with up to six fractional digits (Python datetime precision).
Finer precision rejects rather than silently truncating into a cutoff boundary.
Enforce decision<=target start<target end and
publication<=availability<=ingestion. Decimal values use the existing finite,
bounded string validation; null, nonnumeric or float values are invalid.
`limit` is mandatory, strict integer 1..1000; excess records reject, never truncate.
Source input is <=1 MiB before parsing; no extra fields or implicit repairs.

Observation identity is exactly `(instrument_id, label_id, definition_version,
decision_at, target_start_at, target_end_at)`. `value_unit` stays supplied metadata,
not a grouping key or implicit conversion. Different units in revisions still
belong to the same observation; selected value/unit remain unqualified.

Mature iff `max(target_end_at, published_at, available_at, ingested_at) <= fit_cutoff`.
Equality is eligible. Choose the unique maximum **release** clock among mature
revisions, `max(published_at, available_at, ingested_at)`, which equals ingestion
under required order. Target end affects maturity but never revision ranking.
This avoids artificial ties when two different releases precede the same target
end. Revision spelling/input order never wins. A duplicate observation+revision
or equal winning mature release rejects the entire view. Lower tied releases
may be superseded by a later unique winner; immature ties do not select anything.

`selected` rows sort by the six-field observation tuple, dates chronologically;
diagnostics use the same tuple then lexical revision for display only. Every
diagnostic contains observation key, source_revision, reason and the full
normalized record, retaining excluded/superseded values and units. Reasons are
`SELECTED`, `SUPERSEDED`, `NOT_MATURE`. Empty labels gives `NO_DATA`; nonempty
without mature labels gives `NO_MATURE_LABELS`; otherwise `SELECTED`. Observed
`"0"` remains a value. No absent label is converted to a zero return.

`source_sha256` hashes original bytes. `canonical_input_hash` hashes existing
`codec.canonical` of the validated envelope in JSON mode with labels sorted by
canonical record bytes. Canonical JSON sorts object keys, uses compact separators,
allow_nan=False, default ensure_ascii=True and UTF-8. `request_hash` applies the
same digest to `{canonical_input_hash, fit_cutoff, limit}`, with normalized UTC
`Z` cutoff. Thus records and cutoff/limit are bound together; the separate source
hash witnesses formatting/order changes. Same canonical request gives the same
selected rows/diagnostics/hashes except exact-byte identity. At most 1000 selected
rows and 1000 diagnostics are returned, with bounded scalar fields.

Failures raise code-only `LabelViewError`: `INVALID_INPUT_TYPE`, `INPUT_TOO_LARGE`,
`INVALID_LIMIT`, `INVALID_FIT_CUTOFF`, `INVALID_LABEL_INPUT`, `RECORD_LIMIT_EXCEEDED`,
`DUPLICATE_REVISION`, `AMBIGUOUS_REVISION`. No raw input in errors or partial view.

Always `label_value_qualification=UNVERIFIED`, `training_eligibility=NOT_ASSESSED`,
`financial_verdict=NOT_RUN`. Supplied values are not validated economic outcomes.
This permits a target future at its original decision to mature at a later fit;
it does not prove original feature knowledge, formulas/actions/terminal handling,
universe/rights, purge/embargo, evaluation membership or effective sample size.
Supplied releases before target end are not a value-qualification claim; the end
still gates maturity. Actual clock evidence remains caller responsibility.
Existing feature/temporal/Dataset/RunConfig/engine/API/UI/schema contracts remain
unchanged. No file/network/wall-clock operation, new dependency or model fitting.
