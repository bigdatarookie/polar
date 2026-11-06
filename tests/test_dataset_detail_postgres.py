"""Zero-job integration check, requiring a dedicated EMPTY test database.

Never reads runtime credentials implicitly; never drops or corrupts a database.
DevOps/QA own actual container recreation and retained-report proof separately.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.cli import main
from polar.config import Settings
from polar.models import Dataset
from polar.service import Service


@pytest.mark.postgres
def test_persisted_dataset_inspection(tmp_path, raw_fixture, data, monkeypatch, capsys):
    dsn = os.environ.get("POLAR_DATASET_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("NOT RUN: requires explicit empty isolated POLAR_DATASET_TEST_DATABASE_URL")
    settings = Settings(dsn, tmp_path)
    s = Service(settings)
    with s.registry.connect() as db:
        assert db.execute("SELECT current_database() AS name").fetchone()["name"].startswith("polar_test_")
        assert not db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall(), "Refusing nonempty database"
    s.registry.migrate()
    client = TestClient(create_app(s))
    before = datetime.now(timezone.utc)
    first = client.post("/v1/datasets", content=raw_fixture, headers={"Content-Type":"application/json"})
    assert first.status_code == 200
    variant = json.dumps(json.loads(raw_fixture), indent=3).encode()
    assert hashlib.sha256(variant).hexdigest() != first.json()["source_hash"]
    repeated = client.post("/v1/datasets", content=variant, headers={"Content-Type":"application/json"})
    assert repeated.json() == first.json()
    row = s.registry.dataset(data.dataset_id)
    assert row["source_bytes"] == raw_fixture
    detail = client.get("/v1/datasets/" + data.dataset_id).json()
    assert detail["source_hash"] == detail["inspection"]["source_sha256"] == first.json()["source_hash"]
    assert detail["id"] == detail["inspection"]["dataset_id"] == data.dataset_id
    assert before <= datetime.fromisoformat(detail["registered_at"]) <= datetime.now(timezone.utc)
    assert Service(settings).dataset(data.dataset_id) == s.dataset(data.dataset_id)
    monkeypatch.setattr(Settings, "load", lambda: settings)
    main(["dataset", data.dataset_id])
    cli = json.loads(capsys.readouterr().out)
    assert datetime.fromisoformat(cli.pop("registered_at")) == row["registered_at"]
    detail.pop("registered_at")
    assert cli == detail
    changed = json.loads(raw_fixture)
    changed["dataset_name"] = "second persisted dataset"
    second = Dataset.model_validate(changed)
    s.registry.register_dataset(changed, json.dumps(changed).encode())
    expected = sorted([data.dataset_id, second.dataset_id])
    for offset, dataset_id in enumerate(expected):
        response = client.get(f"/v1/datasets?limit=1&offset={offset}")
        assert [row["id"] for row in response.json()] == [dataset_id]
        main(["datasets", "--limit", "1", "--offset", str(offset)])
        assert json.loads(capsys.readouterr().out) == response.json()
    assert client.get("/v1/datasets?offset=2").json() == []
    assert client.get("/v1/datasets/missing").status_code == 404
    for command in ("datasets", "runs"):
        for query in ("limit=0", "limit=11", "offset=-1"):
            assert client.get(f"/v1/{command}?{query}").status_code == 422
    with s.registry.connect() as db:
        assert db.execute("SELECT count(*) AS n FROM runs").fetchone()["n"] == 0
