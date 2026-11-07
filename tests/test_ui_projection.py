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

    def add(raw=raw_fixture, state="completed", report_status=None, revision="1"*40, cash_flat=False, config_change=None, input_change=None, report_change=None, artifact_run_id=None):
        data = Dataset.model_validate_json(raw)
        body = data.model_dump(mode="json")
        service.registry.data[data.dataset_id] = {"id":data.dataset_id,"body":body,
            "source_hash":hashlib.sha256(raw).hexdigest(),"content_hash":digest(body),
            "source_bytes":raw,"registered_at":datetime(2026,11,6,tzinfo=timezone.utc)}
        conf = config.model_copy(update={"dataset_id":data.dataset_id})
        if cash_flat or not data.sessions:
            conf = conf.model_copy(update={"strategy_version":"cash-flat-v1","orders":[]})
        if config_change:
            conf = RunConfig.model_validate({**conf.model_dump(mode="json"), **config_change})
        rid, aid = uuid.uuid4(), uuid.uuid4()
        row = {"id":rid,"attempt_id":aid,"config":conf.model_dump(mode="json"),
               "dataset_id":data.dataset_id,"state":state,"created_at":datetime(2026,11,6,tzinfo=timezone.utc),
               "artifact_ref":None,"artifact_hash":None,"actor":SENTINEL,"attempts":[{"secret":SENTINEL}]}
        if state == "completed":
            report = calculate(data, conf)
            if "diagnostics" in report:
                report["diagnostics"].append({"internal":SENTINEL})
            for key in ("units", "coverage"):
                if key in report:
                    report[key]["internal"] = SENTINEL
            if report_status:
                report["status"] = report_status
            if report_change:
                report_change(report)
            inputs = {"dataset":copy.deepcopy(body),"config":conf.model_dump(mode="json"),"secret":SENTINEL}
            if input_change:
                input_change(inputs)
            ref = service.artifacts.publish(artifact_run_id or rid, aid, report, inputs,
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


@pytest.mark.parametrize("condition,diagnostic", [("no_bars", "NO_DATA"), ("unknown_decision", "UNKNOWN_DECISION_SESSION")])
def test_genuine_engine_invalid_detail_and_catalog(ui_service, raw_fixture, condition, diagnostic):
    s, add = ui_service
    healthy = add(cash_flat=True)
    if condition == "no_bars":
        raw = json.loads(raw_fixture)
        raw["bars"] = []  # legal Dataset with declared sessions; accepted engine INVALID
        row = add(json.dumps(raw).encode(), cash_flat=True)
    else:
        row = add(config_change={"orders":[{"decision_session_id":"2099-01-01","quantity":"1"}]})
    actual = s.artifacts.report(row["artifact_ref"])
    assert actual["status"] == actual["financial_verdict"] == "INVALID"
    assert actual["diagnostic"] == diagnostic
    assert "config_hash" not in actual and "strategy_version" not in actual
    assert actual["nav"] == actual["fills"] == []
    before = copy.deepcopy(s.registry.runs)
    client = TestClient(create_app(s))
    detail = client.get(f"/v1/ui/runs/{row['id']}")
    assert detail.status_code == 200, detail.json()
    projected = detail.json()["report"]
    assert projected["status"] == projected["financial_verdict"] == "INVALID"
    assert projected["diagnostic"] == diagnostic
    assert projected["metrics"]["performance"] == actual["metrics"]["performance"]
    assert "config_hash" not in projected and "strategy_version" not in projected
    assert projected["nav"] == projected["fills"] == []
    assert "initial_cash" not in projected
    assert not any(m.get("value") is not None for m in projected["metrics"].values())
    catalog = client.get(f"/v1/ui/datasets/{row['dataset_id']}/runs")
    assert catalog.status_code == 200, catalog.json()
    item = next(i for i in catalog.json()["items"] if i["run"]["id"] == str(row["id"]))
    assert item["report_status"] == item["financial_verdict"] == "INVALID"
    assert item["diagnostic"] == diagnostic
    assert client.get(f"/v1/ui/runs/{healthy['id']}").status_code == 200
    if condition == "unknown_decision":
        assert len(catalog.json()["items"]) == 2  # invalid and healthy on SAME dataset/page
    assert s.registry.runs == before


@pytest.mark.parametrize("fault", ["input_config", "input_dataset", "missing_config", "missing_dataset", "null_config", "null_dataset",
    "row_config", "run", "attempt", "report_dataset", "report_protocol", "supplied_config_hash", "supplied_strategy"])
def test_genuine_invalid_still_rejects_wrong_identity(ui_service, fault):
    s, add = ui_service
    def inputs(body):
        if fault == "input_config": body["config"]["actor"] = "another-actor"
        if fault == "input_dataset": body["dataset"]["dataset_name"] = "another-dataset"
        if fault == "missing_config": body.pop("config")
        if fault == "missing_dataset": body.pop("dataset")
        if fault == "null_config": body["config"] = None
        if fault == "null_dataset": body["dataset"] = None
    def report(body):
        if fault == "report_dataset": body["dataset_id"] = "ds-" + "0"*64
        if fault == "report_protocol": body["protocol_version"] = "other-protocol"
        if fault == "supplied_config_hash": body["config_hash"] = None
        if fault == "supplied_strategy": body["strategy_version"] = "other-strategy"
    row = add(config_change={"orders":[{"decision_session_id":"2099-01-01","quantity":"1"}]}, input_change=inputs, report_change=report,
              artifact_run_id=uuid.uuid4() if fault == "run" else None)
    requested_id = row["id"]
    if fault == "row_config": row["config"]["actor"] = "another-actor"
    if fault == "attempt": row["attempt_id"] = uuid.uuid4()
    client = TestClient(create_app(s))
    for route in (f"/v1/ui/runs/{requested_id}",f"/v1/ui/datasets/{row['dataset_id']}/runs"):
        response = client.get(route)
        assert response.status_code == 409
        assert response.json() == {"code":"REPORT_IDENTITY_MISMATCH"}


@pytest.mark.parametrize("filename", ["inputs.json", "manifest.json", "report.json", "environment.json"])
def test_genuine_invalid_does_not_bypass_artifact_hashes(ui_service, filename):
    s, add = ui_service
    row = add(config_change={"orders":[{"decision_session_id":"2099-01-01","quantity":"1"}]})
    path = s.artifacts.directory(row["artifact_ref"]) / filename
    path.chmod(0o644)
    path.write_text(SENTINEL)
    client = TestClient(create_app(s))
    for route in (f"/v1/ui/runs/{row['id']}",f"/v1/ui/datasets/{row['dataset_id']}/runs"):
        response = client.get(route)
        assert response.status_code == 503
        assert response.json() == {"code":"DEPENDENCY_UNAVAILABLE"}


def test_genuine_invalid_unknown_diagnostic_is_not_echoed(ui_service):
    s, add = ui_service
    def change(report):
        report["diagnostic"] = SENTINEL
        report["metrics"]["performance"]["reason"] = SENTINEL
    row = add(config_change={"orders":[{"decision_session_id":"2099-01-01","quantity":"1"}]}, report_change=change)
    response = TestClient(create_app(s)).get(f"/v1/ui/runs/{row['id']}")
    assert response.status_code == 200
    assert SENTINEL not in response.text
    assert response.json()["report"]["diagnostic"] is None
    assert response.json()["report"]["metrics"]["performance"]["reason"] is None
