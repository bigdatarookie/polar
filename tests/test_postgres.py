"""Effect tests for an explicitly provisioned EMPTY, isolated PostgreSQL DB.

Never falls back to SQLite or resets a database. Costs three logical fixture jobs.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.config import Settings
from polar.registry import BudgetExceeded,Conflict,Registry
from polar.service import Service
from polar.worker import work_once


@pytest.mark.postgres
def test_postgres_api_worker_recovery(tmp_path,raw_fixture,data,config):
    dsn = os.environ.get("POLAR_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("NOT RUN: POLAR_TEST_DATABASE_URL requires fresh isolated PostgreSQL")
    settings = Settings(dsn,tmp_path,max_jobs=3,lease_seconds=5)
    reg = Registry(settings)
    with reg.connect() as db:
        name = db.execute("SELECT current_database() AS name").fetchone()["name"]
        assert name.startswith("polar_test_"), "Refusing a non-test database"
        tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
        assert not tables, "Refusing nonempty database; preserve prior evidence"
    reg.migrate()
    reg.migrate()  # controlled idempotent migration
    s = Service(settings)
    client = TestClient(create_app(s))
    assert client.get("/readyz").status_code == 200
    import json
    ds = client.post("/v1/datasets",content=raw_fixture,headers={"Content-Type":"application/json"})
    assert ds.status_code == 200 and ds.json()["id"] == data.dataset_id
    assert ds.json()["source_hash"] == "a6dd88480836e262c565f1ba4dfd5a056e7bbfd1688787dd2a343a82bf0bba14"
    body = config.model_dump(mode="json")
    first = client.post("/v1/runs",json=body,headers={"Idempotency-Key":"base"})
    assert first.status_code == 200
    run_id = uuid.UUID(first.json()["id"])
    again = client.post("/v1/runs",json=body,headers={"Idempotency-Key":"base"})
    assert again.json()["id"] == str(run_id)
    changed = {**body,"actor":"another-actor"}
    assert client.post("/v1/runs",json=changed,headers={"Idempotency-Key":"base"}).status_code == 409
    assert client.get(f"/v1/runs/{run_id}/report").status_code == 409
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _:reg.claim(),range(2)))
    assert sum(row is not None for row in claims) == 1
    old = next(row for row in claims if row)
    # Model a stopped worker by moving only this test run's lease into the past.
    with reg.connect() as db:
        db.execute("UPDATE runs SET lease_until=now()-interval '1 second' WHERE id=%s",(run_id,))
    assert not reg.finish(run_id,old["attempt_id"],"completed",0,"stale",artifact_hash="stale")
    completed = work_once(settings)
    assert completed["state"] == "completed" and completed["attempt"] == 2
    assert completed["attempts"][0]["state"] == "lost"
    report = client.get(f"/v1/runs/{run_id}/report")
    assert report.status_code == 200 and report.json()["nav"][-1]["nav"] == "1014"
    # New service instance reads persisted output; no calculation required.
    assert Service(settings).report(run_id) == report.json()
    assert client.get(f"/v1/runs/{run_id}/evidence").json()["run_id"] == str(run_id)
    with reg.connect() as db:
        with pytest.raises(psycopg.Error):
            db.execute("UPDATE datasets SET content_hash='tampered' WHERE id=%s",(data.dataset_id,))
    second = reg.submit("cancel-before-claim",config)
    assert reg.cancel(second["id"])["state"] == "canceled"
    assert reg.cancel(second["id"])["state"] == "canceled"  # terminal cancel is idempotent
    third = reg.submit("cancel-running",config)
    running = reg.claim()
    assert running["id"] == third["id"]
    reg.cancel(third["id"])
    assert not reg.heartbeat(third["id"],running["attempt_id"])
    assert reg.finish(third["id"],running["attempt_id"],"failed",0,error="TEST_CANCEL")
    assert reg.get(third["id"])["state"] == "canceled"
    with pytest.raises(BudgetExceeded):reg.submit("over-limit",config)
    # Report bytes changed while manifest changed too must still fail DB binding.
    manifest = s.artifacts.directory(completed["artifact_ref"])/"manifest.json"
    manifest.chmod(0o644)
    manifest.write_text("{}")
    assert client.get(f"/v1/runs/{run_id}/report").status_code == 503
    assert client.get(f"/v1/runs/{run_id}/evidence").status_code == 503
