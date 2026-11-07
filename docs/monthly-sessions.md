# Supplied monthly session boundaries

`polar.monthly_sessions.monthly_session_boundaries(raw_bytes: bytes) -> dict`
plans calendar boundaries only. It does not schedule a strategy, choose a
feature-availability cutoff, invent business days, or certify executable fills.
No new CLI/API or Dataset version is introduced.

```python
import json
from polar.monthly_sessions import monthly_session_boundaries

raw = json.dumps({
    "schema_version": "polar.synthetic-calendar-input/1",
    "synthetic": True,
    "timing_model": "synthetic_replay",
    "calendar_id": "toy-calendar",
    "calendar_version": "v1",
    "venue_timezone": "America/New_York",
    "coverage_start": "2024-01-01",
    "coverage_end": "2024-02-02",
    "sessions": [
        {"session_id": "2024-01-31", "open_at": "2024-01-31T14:30:00Z",
         "close_at": "2024-01-31T18:00:00Z"},
        {"session_id": "2024-02-02", "open_at": "2024-02-02T14:30:00Z",
         "close_at": "2024-02-02T21:00:00Z"}
    ]
}).encode()
plan = monthly_session_boundaries(raw)
assert plan["months"][0]["candidate_next_open"] == "2024-02-02T14:30:00Z"
assert plan["months"][1]["status"] == "PARTIAL_MONTH"
```

Input schema `polar.synthetic-calendar-input/1` requires the fields above and
rejects extras. Source bytes must be <=1 MiB; session count <=2000; calendar ID
and version are nonempty strings <=64 characters. Coverage is inclusive canonical
`YYYY-MM-DD`, ordered, years 0001..9999. Existing Session validation supplies UTC
and open-before-close checks. Sessions must be strictly ordered without overlaps
or touching endpoints; IDs must be unique canonical dates matching **both**
venue-local open and close date and lie in coverage. The UTC calendar day alone
is insufficient. Early closes and DST use the supplied instants, not fixed UTC
market hours. No real exchange/session calendar is fetched or independently
validated; the caller's complete-calendar declaration is an input assumption.

Output schema `polar.monthly-session-boundaries/1` includes calendar ID/version,
timezone and normalized coverage, exact `source_sha256`, and
`canonical_input_hash` over the validated normalized envelope. JSON formatting
can change the byte hash while preserving the canonical hash and result rows.
Overall `status` is `PLANNED` for nonempty sessions or `NO_DATA` for a valid empty
session list. Zero-byte input is malformed and raises `INVALID_CALENDAR_INPUT`.

`months` contains **every** civil month intersecting coverage in order, including
empty and partial months. Each row includes `month`, `session_count`, `status`,
`last_session_id`, `observation_close`, `next_session_id`, `candidate_next_open`.

| Month status | Boundary fields |
|---|---|
| `PARTIAL_MONTH` | All four boundary fields null, regardless of supplied count |
| `NO_SESSIONS` | Fully covered civil month with zero sessions; all boundary fields null |
| `NO_NEXT_SESSION` | Complete nonempty month: last supplied ID/close present, next pair null |
| `BOUNDARY_FOUND` | Complete nonempty month: last supplied ID/close and exact following supplied ID/open present |

A month is complete only when coverage includes its first through last civil
date; the last observed session is not evidence of that completeness. Partial
coverage takes precedence over an empty count. Overall `NO_DATA` therefore
coexists with `NO_SESSIONS` or `PARTIAL_MONTH` rows. A following supplied session
may be across an empty month or in a partial month; it remains just the next
**supplied** event, with no inferred sessions in between. A last close is an
observation-event boundary and the next open is a candidate calendar event;
neither is a known feature-ready decision or a fill.

Output bounds follow validated dates: at most119,988 month rows; each row has
fixed fields and bounded IDs/timestamps. The helper does not silently shorten
long coverage declarations. Input limits are request safety limits, not empirical
history/sampling permissions. `calendar_qualification` is always `UNVERIFIED`
and `investment_evaluation` always `NOT_RUN`; no financial PASS exists here.

Failures raise `CalendarError` with a code only: `INVALID_INPUT_TYPE`,
`INPUT_TOO_LARGE`, `INVALID_CALENDAR_INPUT`, `TIMEZONE_UNAVAILABLE`,
`REVERSED_COVERAGE`, `DUPLICATE_SESSION`, `UNORDERED_OR_OVERLAPPING_SESSIONS`,
`SESSION_DATE_MISMATCH` or `SESSION_OUTSIDE_COVERAGE`. No input values are echoed.
Validation fails the whole request, never a partial plan. Stdlib IANA timezone
support is loaded at module import; the operation performs no file/network/clock
I/O and installs nothing if timezone support is absent. The system tzdata version
is not independently qualified by this synthetic helper. Existing Session,
Dataset max20, feature/temporal/allocation/engine/API/CLI/runtime contracts remain
unchanged.
