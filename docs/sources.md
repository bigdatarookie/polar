# Source bindings

The requirements package remains authoritative and is not reproduced here.
All eight entries of its `MANIFEST.sha256` verified on 2026-11-06.

| Source | SHA-256 | Use |
| --- | --- | --- |
| `/Users/garry/Documents/git/openrig-exp/trading-prototype-v1/MANIFEST.sha256` | `1bbe0f997fbf133e5a9fe10966ee64ddfcffb183eedf828d8dc6ecbed82c29b9` | Current package binding; read PLATFORM architecture/records/operations/PR, TEAM independence, MEMORY records/budgets |
| `/Users/garry/.openrig/shared-docs/rigs/polar-rig/state/data/fixture-v1/fixture.json` | `a6dd88480836e262c565f1ba4dfd5a056e7bbfd1688787dd2a343a82bf0bba14` | Frozen artificial six-session data; generated test input, no vendor rows |
| Same directory, `generate.py` | `2f08c2e15568d8c37a9f7d18d128bdd95f8ab5816e84190dadd3842ef4e2c460` | Literal synthetic test generator retained under tests/fixtures; output hash checked |
| `/Users/garry/.openrig/shared-docs/rigs/polar-rig/state/quant/validator/bootstrap-v1/fixture-protocol-v2.md` | `3c124b8371cd4852e1cd98a78fa1d673fc87965e78d71ccfeafbf1f9f0ed1e53` | Frozen financial formulas, order phases and tolerances; not implementation acceptance |
| Same protocol directory, `canonical-binding-update-v1.md` | `a5509827b74da8a494af1815cf9cef7a25ae2d6405b5626f22478583e702d8d1` | Validator receipt reconciling the older manifest hash in frozen protocol v2 with current TEAM model/effort guidance |
| `/Users/garry/.openrig/shared-docs/rigs/polar-rig/state/platform/sre-bootstrap-profile-20261106.md` | `92c4744830cc82f8ca0a8da730bba8eae01d266746fb1b34d4c6c8087a6d329e` | Reduced runtime envelope and recovery advice, not runtime proof |

Dataset IDs are SHA-256 of the validated canonical JSON form, prefixed `ds-`.
The original uploaded UTF-8 bytes, their separate SHA-256 and actual import time
are retained in PostgreSQL and saved with each result. Those bytes have artificial
2024 replay ingestion fields; actual import time is never backdated. Exact input
source hash and normalized content identity have different purposes.

Dependency selection checked against official sources on 2026-11-06:

- [Python release/support status](https://www.python.org/downloads/): use supported 3.13; container pin 3.13.18, author environment 3.13.15.
- [PostgreSQL supported versions](https://www.postgresql.org/support/versioning/): 17.11 supported.
- [FastAPI releases](https://fastapi.tiangolo.com/release-notes/): 0.162.0.
- [Psycopg installation and compatibility](https://www.psycopg.org/psycopg3/docs/basic/install.html): 3.3.8 binary distribution, PostgreSQL and Python compatibility.
- [PyArrow installation](https://arrow.apache.org/docs/python/install.html) and [package metadata](https://pypi.org/pypi/pyarrow/json): 26.0.1.
- [uv lock/sync behavior](https://docs.astral.sh/uv/concepts/projects/sync/): `uv.lock`, frozen sync and hashed export.

Direct package versions were checked through their publisher's PyPI metadata;
`uv.lock` fixes transitives and hashes, `requirements.lock` is its non-dev hashed
Docker export. Official Docker Hub registry manifests resolved image pins for
`python:3.13.18-slim-bookworm` and `postgres:17.11-alpine` on 2026-11-06.
Registry existence is not a successful build or compatibility test.
