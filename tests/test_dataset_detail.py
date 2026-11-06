"""Component API/CLI checks. Retained rows are doubles, not PostgreSQL proof."""
import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.cli import main
from polar.codec import digest
from polar.config import Settings
from polar.data_quality import inspect_dataset
from polar.registry import NotFound
from polar.service import DatasetIntegrityError, Service


@pytest.fixture
def retained_service(tmp_path, data, raw_fixture):
    s = Service(Settings("unused", tmp_path))
    row = {"id":data.dataset_id, "body":data.model_dump(mode="json"),
           "content_hash":digest(data.model_dump(mode="json")),
           "source_hash":hashlib.sha256(raw_fixture).hexdigest(),
           "source_bytes":raw_fixture,
           "registered_at":datetime(2026, 11, 6, tzinfo=timezone.utc)}

    class RetainedRegistry:
        def dataset(self, dataset_id):
            if dataset_id != data.dataset_id:
                raise NotFound("DATASET_NOT_FOUND")
            return copy.deepcopy(row)

    s.registry = RetainedRegistry()
    return s, row


def test_shared_detail_api_cli(retained_service, raw_fixture, monkeypatch, capsys):
    s, row = retained_service
    monkeypatch.setattr("polar.service.Service", lambda settings: s)
    monkeypatch.setattr(Settings, "load", lambda: None)
    response = TestClient(create_app(s)).get("/v1/datasets/" + row["id"])
    assert response.status_code == 200
    detail = response.json()
    assert set(detail) == {"id", "content_hash", "source_hash", "registered_at", "inspection"}
    assert detail["inspection"] == inspect_dataset(raw_fixture)
    assert datetime.fromisoformat(detail["registered_at"]) == row["registered_at"]
    assert detail["inspection"]["investment_evaluation"] == "NOT_RUN"
    main(["dataset", row["id"]])
    cli = json.loads(capsys.readouterr().out)
    assert datetime.fromisoformat(cli.pop("registered_at")) == row["registered_at"]
    detail.pop("registered_at")
    assert cli == detail


@pytest.mark.parametrize("field", ["id", "content_hash", "source_hash", "body", "source_bytes"])
def test_corrupt_binding_fails_closed(retained_service, field, monkeypatch, capsys):
    s, row = retained_service
    dataset_id = row["id"]
    before = copy.deepcopy(row)
    row[field] = {"secret":"NEVER_ECHO_THIS"} if field == "body" else (
        b'{"secret":"NEVER_ECHO_THIS"}' if field == "source_bytes" else "NEVER_ECHO_THIS")
    corrupt = copy.deepcopy(row)
    with pytest.raises(DatasetIntegrityError, match="^DATASET_INTEGRITY_ERROR$"):
        s.dataset(dataset_id)
    response = TestClient(create_app(s)).get("/v1/datasets/" + dataset_id)
    assert response.status_code == 409
    assert response.json() == {"code":"DATASET_INTEGRITY_ERROR"}
    monkeypatch.setattr("polar.service.Service", lambda settings: s)
    monkeypatch.setattr(Settings, "load", lambda: None)
    with pytest.raises(SystemExit) as exc:
        main(["dataset", dataset_id])
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err) == {"status":"ERROR", "code":"DATASET_INTEGRITY_ERROR"}
    assert row == corrupt and row != before  # reads do not repair or mutate the row


def test_missing_detail_api_cli(retained_service, monkeypatch, capsys):
    s, _ = retained_service
    assert TestClient(create_app(s)).get("/v1/datasets/missing").json() == {"code":"DATASET_NOT_FOUND"}
    assert TestClient(create_app(s)).get("/v1/datasets/missing").status_code == 404
    monkeypatch.setattr("polar.service.Service", lambda settings: s)
    monkeypatch.setattr(Settings, "load", lambda: None)
    with pytest.raises(SystemExit) as exc:
        main(["dataset", "missing"])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().err)["code"] == "DATASET_NOT_FOUND"


def test_valid_replacement_source_still_rejects_canonical_disagreement(retained_service, raw_fixture):
    s, row = retained_service
    changed = json.loads(raw_fixture)
    changed["dataset_name"] = "different valid source"
    row["source_bytes"] = json.dumps(changed).encode()
    row["source_hash"] = hashlib.sha256(row["source_bytes"]).hexdigest()
    with pytest.raises(DatasetIntegrityError):
        s.dataset(row["id"])


def test_formatting_variant_keeps_retained_identity(retained_service, raw_fixture):
    s, row = retained_service
    original = s.dataset(row["id"])
    # A valid differently formatted retained source still binds to the same body.
    row["source_bytes"] = json.dumps(json.loads(raw_fixture), indent=3).encode()
    row["source_hash"] = hashlib.sha256(row["source_bytes"]).hexdigest()
    other = s.dataset(row["id"])
    assert original["id"] == other["id"]
    assert original["source_hash"] != other["source_hash"]
    assert other["inspection"] == inspect_dataset(row["source_bytes"])


@pytest.mark.parametrize("command", ["datasets", "runs"])
@pytest.mark.parametrize("option,value", [("--limit","0"),("--limit","11"),("--offset","-1")])
def test_cli_bounds_before_settings(command, option, value, monkeypatch):
    def forbidden():
        pytest.fail("invalid pagination must fail before settings/dependencies")
    monkeypatch.setattr(Settings, "load", forbidden)
    with pytest.raises(SystemExit) as exc:
        main([command, option, value])
    assert exc.value.code == 2


def test_list_parameter_parity(retained_service, monkeypatch, capsys):
    s, _ = retained_service
    calls = []
    def datasets(limit=10, offset=0):
        calls.append(("datasets", limit, offset))
        return []
    def runs(limit=10, offset=0, dataset_id=None):
        calls.append(("runs", limit, offset, dataset_id))
        return []
    s.registry.datasets, s.registry.search = datasets, runs
    monkeypatch.setattr("polar.service.Service", lambda settings: s)
    monkeypatch.setattr(Settings, "load", lambda: None)
    client = TestClient(create_app(s))
    for command in ("datasets", "runs"):
        main([command])
        client.get("/v1/" + command)
        assert calls[-1] == calls[-2]
        flags = ["--limit", "1", "--offset", "2"]
        query = "?limit=1&offset=2"
        if command == "runs":
            flags += ["--dataset-id", "ds-filter"]
            query += "&dataset_id=ds-filter"
        main([command] + flags)
        client.get("/v1/" + command + query)
        assert calls[-1] == calls[-2]
        for query in ("?limit=0", "?limit=11", "?offset=-1"):
            assert client.get("/v1/" + command + query).status_code == 422
    assert all(json.loads(line) == [] for line in capsys.readouterr().out.splitlines())
