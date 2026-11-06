"""Controlled service/component fixtures only: no real DB, jobs or server."""
import copy
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.codec import digest
from polar.config import Settings
from polar.engine import calculate
from polar.models import Dataset, RunConfig
from polar.registry import NotFound
from polar.service import Service

SENTINEL = "PRIVATE_NOT_FOR_UI"


@pytest.fixture
def ui_service(tmp_path, raw_fixture, config):
    class ControlledRegistry:
        def __init__(self):
            self.data, self.runs = {}, {}

        def dataset(self, dataset_id):
            if dataset_id not in self.data:
                raise NotFound("DATASET_NOT_FOUND")
            return copy.deepcopy(self.data[dataset_id])

        def datasets(self, limit=10, offset=0):
            return [{"id":k} for k in sorted(self.data)[offset:offset+limit]]

        def get(self, run_id):
            if str(run_id) not in self.runs:
                raise NotFound("RUN_NOT_FOUND")
            return copy.deepcopy(self.runs[str(run_id)])

        def search(self, limit=10, offset=0, dataset_id=None):
            rows = [r for r in self.runs.values() if r["dataset_id"] == dataset_id]
            return sorted(rows, key=lambda r:(r["created_at"],r["id"]))[offset:offset+limit]

    service = Service(Settings("unused", tmp_path))
    service.registry = ControlledRegistry()

    def add(raw=raw_fixture, state="completed", report_status=None, revision="1"*40, cash_flat=False):
        data = Dataset.model_validate_json(raw)
        body = data.model_dump(mode="json")
        service.registry.data[data.dataset_id] = {"id":data.dataset_id,"body":body,
            "source_hash":hashlib.sha256(raw).hexdigest(),"content_hash":digest(body),
            "source_bytes":raw,"registered_at":datetime(2026,11,6,tzinfo=timezone.utc)}
        conf = config.model_copy(update={"dataset_id":data.dataset_id})
        if cash_flat or not data.sessions:
            conf = conf.model_copy(update={"strategy_version":"cash-flat-v1","orders":[]})
        rid, aid = uuid.uuid4(), uuid.uuid4()
        row = {"id":rid,"attempt_id":aid,"config":conf.model_dump(mode="json"),
               "dataset_id":data.dataset_id,"state":state,"created_at":datetime(2026,11,6,tzinfo=timezone.utc),
               "artifact_ref":None,"artifact_hash":None,"actor":SENTINEL,"attempts":[{"secret":SENTINEL}]}
        if state == "completed":
            report = calculate(data, conf)
            report["diagnostics"].append({"internal":SENTINEL})
            report["units"]["internal"] = SENTINEL
            report["coverage"]["internal"] = SENTINEL
            if report_status:
                report["status"] = report_status
            ref = service.artifacts.publish(rid, aid, report, {"secret":SENTINEL},
                                            {"code_revision":revision,"password":SENTINEL})
            row.update(artifact_ref=ref, artifact_hash=hashlib.sha256((tmp_path/ref/"manifest.json").read_bytes()).hexdigest())
        service.registry.runs[str(rid)] = row
        return row

    return service, add


def test_projection_uses_original_identity_and_exact_retained_report(ui_service):
    s, add = ui_service
    row = add()
    before = copy.deepcopy(s.registry.runs)
    client = TestClient(create_app(s))
    response = client.get(f"/v1/ui/runs/{row['id']}?dataset_id={row['dataset_id']}")
    assert response.status_code == 200
    result = response.json()
    assert SENTINEL not in response.text and 'artifact_ref' not in response.text
    assert result["dataset"]["source_sha256"] == s.registry.data[row["dataset_id"]]["source_hash"]
    assert result["calculation_revision"] == "1"*40
    assert result["report"]["nav"][-1]["nav"] == "1014"
    assert [f["quantity"] for f in result["report"]["fills"]] == ["4", "-2"]
    assert [f["fee"] for f in result["report"]["fills"]] == ["1", "1"]
    assert result["report"]["metrics"]["fees"]["value"] == "2"
    assert result["report"]["metrics"]["fees"]["evidence_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["report"]["financial_verdict"] == "NOT_RUN"
    assert result["evidence"]["manifest_sha256"] == row["artifact_hash"]
    assert result["evidence"]["run_id"] == str(row["id"])
    page = client.get(f"/v1/ui/datasets/{row['dataset_id']}/runs").json()
    assert page["items"][0]["metrics"] == result["report"]["metrics"]
    assert s.registry.runs == before
    assert client.get(f"/v1/ui/runs/{row['id']}?dataset_id=other").json() == {"code":"RUN_DATASET_MISMATCH"}


def test_actual_zero_metric_is_distinct_from_no_data(ui_service, raw_fixture):
    s, add = ui_service
    cash = add(cash_flat=True)
    view = s.ui_run(cash["id"])
    assert view["report"]["nav"][-1]["nav"] == "1000"
    assert view["report"]["metrics"]["total_return"]["value"] == "0"
    assert view["report"]["metrics"]["fees"]["value"] == "0"
    assert view["report"]["metrics"]["sharpe_252"]["value"] is None
    empty = json.loads(raw_fixture)
    empty.update(sessions=[],bars=[],features=[],actions=[])
    row = add(json.dumps(empty).encode())
    view = s.ui_run(row["id"])
    assert view["report_availability"] == "AVAILABLE"
    assert view["report"]["status"] == "NO_DATA"
    assert view["report"]["nav"] == []
    assert view["report"]["metrics"]["fees"]["value"] is None


@pytest.mark.parametrize("state", ["queued","running","failed","canceled"])
def test_noncomplete_job_never_requests_report(ui_service, state, monkeypatch):
    s, add = ui_service
    row = add(state=state)
    monkeypatch.setattr(s, "report", lambda _:pytest.fail("noncomplete must not read report"))
    result = s.ui_run(row["id"])
    assert result["run"]["state"] == state
    assert result["report_availability"] == "NOT_COMPLETE"
    assert result["report"] is result["evidence"] is None
    assert result["calculation_revision"] == "UNKNOWN"


def test_invalid_status_is_not_rewritten_as_success(ui_service):
    s, add = ui_service
    row = add(report_status="INVALID")
    assert s.ui_run(row["id"])["report"]["status"] == "INVALID"


@pytest.mark.parametrize("revision", [None,"UNRECORDED","main",SENTINEL,123])
def test_calculation_revision_never_inherits_api_revision(ui_service, revision, monkeypatch):
    s, add = ui_service
    row = add(revision=revision)
    monkeypatch.setenv("POLAR_CODE_REVISION", "a"*40)
    result = s.ui_run(row["id"])
    assert result["api_revision"] == "a"*40
    assert result["calculation_revision"] == "UNKNOWN"


@pytest.mark.parametrize("defect", ["dataset_source","manifest","report","environment","report_identity"])
def test_integrity_fails_closed_in_detail_and_catalog(ui_service, defect):
    s, add = ui_service
    row = add()
    if defect == "dataset_source":
        s.registry.data[row["dataset_id"]]["source_hash"] = SENTINEL
    elif defect == "report_identity":
        row["config"] = {**row["config"],"actor":"changed"}
    else:
        filename={"manifest":"manifest.json","report":"report.json","environment":"environment.json"}[defect]
        path=s.artifacts.directory(row["artifact_ref"])/filename
        path.chmod(0o644);path.write_text(SENTINEL)
    client=TestClient(create_app(s))
    for path in (f"/v1/ui/runs/{row['id']}", f"/v1/ui/datasets/{row['dataset_id']}/runs"):
        response=client.get(path)
        assert response.status_code in (409,503)
        assert set(response.json()) == {"code"} and SENTINEL not in response.text


def test_bounded_stable_pages_and_missing_ids(ui_service, raw_fixture):
    s, add=ui_service
    for i in range(3):
        raw=json.loads(raw_fixture);raw["dataset_name"]=f"retained dataset {i}";add(json.dumps(raw).encode(),state="queued")
    expected=sorted(s.registry.data)
    client=TestClient(create_app(s))
    for offset, dataset_id in enumerate(expected):
        page=client.get(f"/v1/ui/datasets?limit=1&offset={offset}").json()
        assert [d["dataset_id"] for d in page["items"]] == [dataset_id]
        assert client.get(f"/v1/ui/datasets/{dataset_id}").json() == page["items"][0]
    assert client.get('/v1/ui/datasets?offset=3').json()["items"] == []
    assert client.get('/v1/ui/datasets/missing/runs').status_code == 404
    assert client.get('/v1/ui/runs/'+str(uuid.uuid4())).status_code == 404
    for route in ('/v1/ui/datasets',f'/v1/ui/datasets/{expected[0]}/runs'):
        for bounds in ('limit=0','limit=11','offset=-1'):
            assert client.get(route+'?'+bounds).status_code == 422
    before=copy.deepcopy(s.registry.runs)
    assert client.post('/v1/ui/datasets').status_code == 405
    assert client.post('/v1/ui/runs/'+str(uuid.uuid4())).status_code == 405
    assert s.registry.runs == before


def test_local_ui_assets_only_and_api_routes_preserved(ui_service):
    s,_=ui_service
    client=TestClient(create_app(s))
    response=client.get('/ui/')
    assert response.status_code == 200
    assert 'id="refresh"' in response.text and 'id="runs-next"' in response.text
    assert client.get('/ui/fixture.json').status_code == 404
    assert client.get('/ui/../schema.sql').status_code == 404
    assert client.get('/v1/not-present').status_code == 404
    assert client.get('/livez').json() == {"status":"ALIVE"}
    assert client.get('/ui/assets/vendor/echarts-6.0.0.min.js').status_code == 200
    assert client.get('/ui/assets/bear/CREDITS.html').status_code == 200
    app=Path('src/polar/web/app.js').read_text()
    assert "fetch('fixture.json')" not in app and 'innerHTML' not in app
    assert 'Atlas' not in app and '$100,000' not in app
