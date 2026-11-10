# All-adjusted reference input conversion

`research-input-prepare` converts an already captured, hash-pinned source collection into a versioned reference input. It performs no provider request, feature calculation, fit, prediction, native execution, scientific admission or database operation. The existing A/B `/1` reader and fixed service profiles remain unchanged. This does not make a C research runner executable.

Use the normal offline service CLI in the accepted locked environment:

```sh
python -m polar.cli research-input-prepare /absolute/conversion-config.json
python -m polar.cli research-input-preflight /absolute/returned-manifest-pin.json
```

`POLAR_ARTIFACT_ROOT` selects an existing private writable artifact store; no DB credential is opened. The returned `input_ref` is written as the second command's JSON argument file. Source paths must be mounted read-only at their pinned absolute paths. Only the designated artifact root is writable. DE owns the first private C transform after applicable independent source/invented qualification; the author must not run that transform or read retained bar payloads.

The config has exactly these fields:

```json
{
  "schema": "polar.reference-input-conversion-config/1",
  "profile_id": "V033-C-BROAD-REFERENCE-INPUT-V1",
  "binding": {"path": "/absolute/C-source-consumer-binding-v1/binding.json", "sha256": "<exact SHA256>"},
  "definition_packet": {"path": "/absolute/DEFINITION-PACKET-v1.1.json", "sha256": "<exact SHA256>"},
  "schedule": {"path": "/absolute/reference-schedule-v1.json", "sha256": "<exact SHA256>"},
  "date_range": {"start": "2016-01-04", "end": "2026-11-06", "count": 2728}
}
```

The C profile pins the existing metadata binding `ea17973d…`, prospective packet `36564b07…`, and parent schedule `67fcf8fd…`. It requires the frozen54 lexical aliases, all100 source relations and2728 dates, yielding147312 rows. It does not reselect a cohort or fill missing operands. The metadata binding's historical packet pointer remains preserved; the separately pinned v1.1 packet supplies the clarified modeled-clock contract. `INVENTED-ALL-ADJUSTED-REFERENCE-INPUT-V1` is a public fixture profile with its own fabricated source graph and expected symbols/dates; it does not admit private financial work.

The published `/2` manifest has truthful `VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE` basis and synthetic reference-unit semantics. Quotes are date-major then ASCII symbol order. Each source close lexeme is retained, exactly represented at scale1 in six decimal places; excess precision/nonpositive/nonfinite prices fail rather than round. Each quote retains its normalized member SHA, 1-based line, hash including newline, original raw-file/body/array/ordinal/job/request/page pointer and query/source alias correspondence. Original raw row tokens are checked through the existing import parser. No split/dividend credit or raw-share/total-return interpretation is added.

`source-relations.json` preserves all metadata/flags/exclusions, original parent relations and coverage metadata, including excluded aliases. Quotes reference parent relations by hash instead of duplicating whole listings on every row. Referenced partition/normalized/raw members are hash checked, and any selected missing/duplicate/conflicting operand is INVALID. This is a source projection, not a repeated provider acquisition or a substitute for the qualified import terminal graph audit.

The projected schedule filters the pinned parent rows and recomputes next-session/month-end fields only. UTC/NY/model/observed-null fields remain verbatim; C requires21 modeled early closes. It does not claim observed primary-venue or historical delivery clocks.

Publication reuses `HistoryStore` locking, staging and immutable conflict checks under `reference-inputs/<semantic revision>`. Repeating identical conversion reuses that publication; conflicting stored bytes fail. Quality reports actual quote bytes/counts. Each pinned member/output is bounded at256MiB and projected quote bytes are bounded cumulatively; this file cap is not an RSS guarantee. The author measured only the invented fixture; private full-cohort output size and peak remain NOT OBSERVED until DE's owned conversion. Preserve source rights: no private/raw/derived quote payload may be pushed to Git or public CI.

Qualification uses existing `scripts/ci.sh` with `tests/test_reference_input.py`, existing A service and B PPO service tests. Expected controls cover split partitions, precise lexemes, newline hashes, original row pointers, excluded relations, null clocks, date/month boundaries, missing/corrupt operands, immutable collisions and no-DB CLI. Existing method, financial protocols, service profile pins, candidate budgets and negative results are not changed.
