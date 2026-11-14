# Event clock metadata, clock1.1

`polar.scheduled_fixed.event_clock_metadata(value)` is one pure callable. It reads
only its supplied dictionary and the runtime IANA timezone database. It does not
read files, fetch sources, calculate prices/weights/returns, invoke an engine or
change legacy annual `calendar_value`, `plan_phase`, profiles or Service dispatch.

Input schema `polar.event-clock-metadata/1` has exactly:

- `event_id`, `reference_period`: nonempty strings identifying independent event
  and reference period, not an inferred release/outcome identity.
- `release_at`: aware ISO timestamp (explicit offset or Z), `release_zone`: IANA
  zone for interpreting the planned release date. Original planned time is not
  evidence that an actual release happened.
- `calendar_availability`, `event_observation_availability`: independent objects
  `{known_by, basis, provenance}`. `basis` is OBSERVED, MODELED or UNKNOWN. UNKNOWN
  requires null known_by; other bases require an aware timestamp. Provenance is
  a nonempty supplied reference/description. Assertions are caller-supplied
  metadata, not independently verified source qualifications.
- `reference_provenance`: `{basis, provenance}` with the same basis enum. MODELED
  reference sessions are not observed primary-venue fills.
- `sessions`: at most 10000 ordered unique `{date, open_at, close_at}` records.
  Both timestamps are aware, open precedes close, and both local dates in
  release_zone equal date. No weekday/calendar extension is generated.
- `quotes`: at most 10000 unique `{close_at, availability}` records; close_at must
  match a supplied reference close. No quote values are accepted. An empty list
  represents absent metadata, not an observed absence of market quotes.

Unknown fields/naive or invalid timestamps/malformed metadata raise the existing
require error `EVENT_CLOCK_INVALID_METADATA`. JSON-like values are expected.

Output schema `polar.event-clock-projection/1` exposes event/reference identity,
release/timezone, prior session, cutoff, decision, execution candidate, latest
completed temporal candidate and its availability, separately qualified quote,
r1/r2/expiry, reentry decision/candidate, all independent availability and
reference provenance, quote-level eligibility reasons and chronology warnings.
Input is unchanged; output provenance objects are independent copies.

Clock rules:

1. Last supplied reference session date strictly before the local planned release
   date; cutoff 14:00 America/New_York on that date, with the installed timezone
   database (DST-aware); D = cutoff +60 seconds.
2. Candidate execution is first supplied close strictly after D, not equal. A
   prior close already elapsed is flagged. Candidate after planned release is
   flagged UNPROTECTED_EARLY_EXECUTION_UNAVAILABLE; neither cutoff nor D moves.
3. Latest temporal candidate is latest supplied session close strictly before D.
   Quote availability is inspected only among supplied quote metadata. The
   qualified quote is latest supplied close <D whose supported close<=K<=D.
   This can be older than the temporal candidate. Null K, future K and unfinished
   quotes remain explicitly ineligible. There is no quote-age cap: prediction
   feed staleness policy belongs elsewhere. No claim of searching complete
   source history follows from a one-candidate input.
4. r1/r2 are first two supplied closes >=planned release. Expiry is r2. Reentry D
   is 00:01 UTC next civil UTC date after r2; reentry candidate first close >D.
   Missing predecessor, completed close, execution, r1/r2 or reentry close yields
   UNAVAILABLE with partial chronology retained; no stale fill or extension.
5. Calendar and event observation K must separately be known <=cutoff. Their
   absence does not become quote K or release time. Quote K eligibility is <=D.

Status precedence: missing required chronology -> UNAVAILABLE; otherwise unknown
reference basis or missing/late calendar/event K or no qualified quote ->
NOT_EXECUTABLE. With full metadata eligibility, any modeled constituent produces
CONDITIONALLY_MODELED; all observed constituents produce
OBSERVED_METADATA_ELIGIBLE. The latter is metadata algebra only, not source,
rights, physical fill, PIT or financial acceptance. Every output has
`execution_authority: false` and explicit supplied-metadata-only scope. Late
execution warning is separate from availability status; downstream policy must
preserve the unprotected gap rather than pretending protection preceded release.

No weights, event policy/SMA, probability proxy, ES/utility, six-leg profile,
grouped report, signed account, public wire/Orders/UI or scientific grant is
introduced here. The source pending January2024 BLS sidecar normalizes to Feb12
19:00Z cutoff /19:01Z D /21:00Z candidate, Feb9 21:00Z temporal quote with null K,
Feb13/14 release closes and Feb15 00:01Z/21:00Z reentry; status remains
NOT_EXECUTABLE. Actual sidecar application is recorded separately from invented
unit controls and is not a historical source-use qualification.
