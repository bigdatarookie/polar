# Polar fixture platform

A local, deterministic synthetic accounting service: versioned input → PostgreSQL
job → leased worker → cash/fills/NAV and metrics → immutable report → API/CLI.
It has no UI, broker connection, campaign runner, arbitrary strategy execution or
financial acceptance field. This bootstrap qualifies infrastructure only.

The canonical read-only requirements package is
`/Users/garry/Documents/git/openrig-exp/trading-prototype-v1` (SPEC v0.4).
See [source provenance](docs/sources.md), [API/CLI and operations](docs/runbook.md),
and [qualification limits](docs/qualification.md). Assignment is
`qitem-20261106111851-80c852ada6e7b9eb`, scope `POL.0.4.0.1`.

```sh
uv sync --locked --python 3.13
uv run --locked pytest -q
uv run --locked python scripts/fixture.py /private/tmp/polar-fixture-inputs
```

The generator writes only synthetic fixture data outside Git. Local tests do not
qualify PostgreSQL or Compose. The PostgreSQL effect test requires a separately
provisioned, fresh empty database named `polar_test_*` and
`POLAR_TEST_DATABASE_URL`; it refuses an existing schema and never resets one.

`compose.yaml` has explicit project name `polar`, loopback API port 18080, no DB
host port, persistent named volumes, rotated logs, pinned image digests and
resource caps. SRE starts the reviewed exact commit after resolving the stopped
owner Docker runtime. No Docker reset, system installation or deployment is
implied by these files.
