import json
import uuid

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.artifacts import ArtifactStore,ArtifactError,verify
from polar.config import Settings
from polar.engine import calculate
from polar.service import Service


def test_atomic_artifact_and_tamper(tmp_path,data,config):
    store = ArtifactStore(tmp_path)
    run_id,aid = uuid.uuid4(),uuid.uuid4()
    report = calculate(data,config)
    ref = store.publish(run_id,aid,report,{"config":config.model_dump(mode="json")},{"code_revision":"test"})
    assert store.report(ref) == report
    assert not list(tmp_path.rglob(".partial-*"))
    with pytest.raises(ArtifactError,match="IMMUTABLE"):
        store.publish(run_id,aid,report,{}, {})
    p = store.directory(ref)/"report.json"
    p.chmod(0o644)
    p.write_text("{}")
    with pytest.raises(ArtifactError,match="HASH"):
        store.report(ref)


def test_liveness_dependency_readiness_and_bounds(tmp_path,monkeypatch):
    s = Service(Settings("host=127.0.0.1 port=1 connect_timeout=1",tmp_path))
    client = TestClient(create_app(s))
    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 503
    assert client.get("/v1/runs?limit=11").status_code == 422
    response = client.post("/v1/runs",json={"password":"NEVER_ECHO_THIS"})
    assert response.status_code == 422 and "NEVER_ECHO_THIS" not in response.text
    assert client.post("/v1/runs",content="x"*(1024**2+1)).status_code == 413


def test_incomplete_publication_not_a_report(tmp_path,data,config):
    store = ArtifactStore(tmp_path,limit=1)
    with pytest.raises(ArtifactError,match="STORAGE"):
        store.publish(uuid.uuid4(),uuid.uuid4(),calculate(data,config),{}, {})
    assert not list(tmp_path.rglob("manifest.json"))
    assert not list(tmp_path.rglob(".partial-*"))
