"""HTTP/component evidence with invented data and retained metadata doubles, no PG."""
import copy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.config import Settings
from polar.history_bundle import BASES, HistoryError, canonical
from polar.service import Service

REVISION = "histrev-"+"1"*64
DATASET = "invented-history"
PREFIX = f"/v1/history/datasets/{DATASET}/revisions/{REVISION}"


class Retained:
    def __init__(self, root, count=7):
        self.store = SimpleNamespace(root=root)
        self.failure = None
        self.rows = [{"session_date": (date(2024,1,2)+timedelta(days=i)).isoformat(),
            "open":"1.2300", "high":"1.25", "low":"1.20", "close":"1.2300", "adjusted_close":"8e-1",
            "volume":"0", "event_at":None, "published_at":None, "historical_available_at":None,
            "source_row_index":i, "source_snapshot_id":"raw-"+"4"*64, "raw_object_sha256":"5"*64}
            for i in range(count)]
        asset = {"instrument_id":"hist-us-0001", "source_symbol":"AAPL.US", "display_symbol":"AAPL",
            "mapping_status":"DECLARED_CURRENT_ONLY", "currency":"USD", "row_count":count,
            "raw_rows":count, "quarantined_rows":0, "duplicate_rows":0, "quarantine_reason_counts":{},
            "chart_fitness":"READY_WITH_LIMITS" if count else "NOT_READY", "calendar_status":"UNVERIFIED",
            "first_date":self.rows[0]["session_date"] if count else None,
            "last_date":self.rows[-1]["session_date"] if count else None, "expected_sessions":None}
        self.summary = {"schema_version":"polar.history-revision/1", "dataset_id":DATASET,
            "dataset_revision":REVISION, "import_receipt_id":"2"*64, "manifest_sha256":"3"*64,
            "basis":dict(BASES), "instruments":[asset, {**asset,"instrument_id":"hist-us-0002", "row_count":0,
                "first_date":None,"last_date":None,"chart_fitness":"NOT_READY","raw_rows":2,
                "quarantined_rows":2,"duplicate_rows":2,"quarantine_reason_counts":{"DUPLICATE_ASSET_DATE":2}}],
            "row_count":count, "registered_at":datetime(2026,11,7,tzinfo=timezone.utc),
            "fitness":{"rights_status":"ADMITTED","structural_status":"QUARANTINED",
                "chart_fitness":"READY_WITH_LIMITS" if count else "NOT_READY",
                "retrospective_analysis_fitness":"NOT_ASSESSED","causal_PIT_fitness":"INSUFFICIENT_EVIDENCE",
                "financial_evaluation":"NOT_RUN"}, "runtime_qualification":"NOT_RUN"}

    def check(self):
        if self.failure: raise self.failure

    def catalog(self, limit, cursor=None):
        self.check()
        if cursor is not None: raise HistoryError("HISTORY_INVALID_CURSOR")
        return {"schema_version":"polar.history-catalog/1", "catalog_snapshot":1,"next_cursor":None,
                "items":[self.revision(DATASET, REVISION)] if self.rows else []}

    def revision(self, dataset, revision):
        self.check()
        if (dataset,revision) != (DATASET,REVISION): raise HistoryError("HISTORY_REVISION_NOT_FOUND")
        return copy.deepcopy(self.summary)

    def load_revision(self, dataset, revision):
        return self.revision(dataset, revision), SimpleNamespace(files={
            "bars/hist-us-0001.ndjson":b"".join(canonical(r)+b"\n" for r in self.rows),
            "bars/hist-us-0002.ndjson":b""})


@pytest.fixture
def api(tmp_path):
    retained = Retained(tmp_path)
    service = Service(Settings("unused",tmp_path))
    service.history_registry = retained
    service.registry.check = lambda:None
    return TestClient(create_app(service)), retained


def params(**overrides):
    return {"instrument_id":"hist-us-0001", "start":"2024-01-04", "end":"2024-01-08",
            "warmup_sessions":"2","limit":"2", **overrides}


def test_paged_warmup_window_lexical_values_and_identity(api):
    client, _ = api
    query, rows, pages = params(), [], []
    while True:
        response = client.get(PREFIX+"/bars", params=query)
        assert response.status_code == 200 and len(response.content) <= 1024**2
        page = response.json()
        assert page["dataset_revision"] == REVISION and page["import_receipt_id"] == "2"*64
        assert page["basis"]["volume_basis"] == "VENDOR_SPLIT_ADJUSTED"
        assert page["row_count"] <= 2 and page["coverage"]["expected_sessions"] is None
        assert page["coverage"]["observed_in_window"] == 4
        assert page["warmup"]["available"] == 2 and page["warmup"]["status"] == "UNRESOLVED"
        assert page["fitness"]["financial_evaluation"] == "NOT_RUN"
        rows.extend(page["rows"]); pages.append(page)
        if page["next_cursor"] is None: break
        query["cursor"] = page["next_cursor"]
    assert [p["window_complete"] for p in pages] == [False,False,True]
    assert len({p["request_identity"] for p in pages}) == 1
    assert [r["session_date"] for r in rows] == [f"2024-01-{d:02}" for d in range(2,8)]
    assert [r["row_role"] for r in rows] == ["WARMUP"]*2+["VISIBLE"]*4
    assert all((r["close"],r["volume"],r["adjusted_close"]) == ("1.2300","0","8e-1") for r in rows)
    assert all(r["event_at"] is None and r["publication_at"] is None for r in rows)


@pytest.mark.parametrize("change", [{"limit":"3"},{"warmup_sessions":"1"},{"start":"2024-01-05"},
    {"end":"2024-01-09"},{"instrument_id":"hist-us-0002"}])
def test_cursor_is_bound_to_full_request(api, change):
    client, _ = api
    cursor = client.get(PREFIX+"/bars",params=params()).json()["next_cursor"]
    result = client.get(PREFIX+"/bars",params=params(cursor=cursor,**change))
    assert result.status_code == 422 and result.json()["code"] == "HISTORY_INVALID_CURSOR"


@pytest.mark.parametrize("query", [{"limit":"0"},{"limit":"1001"},{"limit":"2.0"},{"limit":"+2"},
    {"limit":"02"},{"warmup_sessions":"2501"},{"warmup_sessions":"-1"},{"start":"2024-1-04"},
    {"start":"2024-02-30"},{"start":"2024-01-08"},{"end":"2100-01-01"},
    {"instrument_id":"../../bad"},{"cursor":"x"*2049},{"cursor":"../../bad"},{"projection":"anything"}])
def test_strict_queries_fail_safely(api, query):
    client, _ = api
    response = client.get(PREFIX+"/bars",params=params(**query))
    assert response.status_code == 422
    assert set(response.json()) == {"code"}


def test_unknown_and_repeated_query_keys(api):
    client, _ = api
    assert client.get(PREFIX+"/bars",params=[*params().items(),("limit","2")]).status_code == 422
    assert client.get(PREFIX,params={"unused":"bad"}).status_code == 422
    assert client.get("/v1/history/datasets",params={"limit":"1.0"}).status_code == 422
    assert client.get("/v1/history/readyz",params={"unused":"bad"}).status_code == 422


def test_empty_window_empty_asset_and_quarantine_limits(api):
    client, retained = api
    empty = client.get(PREFIX+"/bars",params=params(start="2025-01-01",end="2025-01-02",warmup_sessions="0")).json()
    assert empty["data_status"] == "EMPTY_WINDOW" and empty["rows"] == [] and empty["window_complete"]
    assert empty["next_cursor"] is None and empty["warmup"]["status"] == "NOT_REQUESTED"
    prior = client.get(PREFIX+"/bars",params=params(start="2025-01-01",end="2025-01-02",warmup_sessions="10")).json()
    assert prior["data_status"] == "EMPTY_WINDOW" and prior["warmup"]["status"] == "INSUFFICIENT_HISTORY"
    assert all(r["row_role"] == "WARMUP" for r in prior["rows"])
    none = client.get(PREFIX+"/bars",params=params(instrument_id="hist-us-0002")).json()
    assert none["rows"] == [] and none["fitness"]["chart_fitness"] == "NOT_READY"
    assert none["coverage"]["quarantined_rows"] == 2 and none["coverage"]["first_date"] is None
    retained.summary["instruments"][0]["quarantined_rows"] = 1
    partial = client.get(PREFIX+"/bars",params=params()).json()
    assert partial["data_status"] == "PARTIAL" and partial["row_count"] == 2


def test_asset_pagination_and_cursor_types(api):
    client, _ = api
    first = client.get(PREFIX+"/assets",params={"limit":"1"}).json()
    last = client.get(PREFIX+"/assets",params={"limit":"1","cursor":first["next_cursor"]}).json()
    assert [first["items"][0]["instrument_id"],last["items"][0]["instrument_id"]] == ["hist-us-0001","hist-us-0002"]
    assert last["next_cursor"] is None
    assert last["items"][0]["chart_fitness"] == "NOT_READY"
    assert client.get(PREFIX+"/bars",params=params(cursor=first["next_cursor"])).status_code == 422
    assert client.get("/v1/history/datasets",params={"cursor":first["next_cursor"]}).status_code == 422
    catalog = client.get("/v1/history/datasets").json()
    assert catalog["catalog_snapshot"] == 1
    assert all("rows" not in item and "files" not in item for item in catalog["items"])


def test_byte_limited_pages_advance_without_dropping_rows(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr("polar.history_queries.MAX_RESPONSE_BYTES", 4000)
    query, rows = params(limit="1000"), []
    for _ in range(10):
        response = client.get(PREFIX+"/bars",params=query)
        assert response.status_code == 200 and len(response.content) <= 4000
        page = response.json(); rows.extend(page["rows"])
        if page["next_cursor"] is None: break
        query["cursor"] = page["next_cursor"]
    else: pytest.fail("cursor did not finish bounded window")
    assert len(rows) == 6 and len({r["session_date"] for r in rows}) == 6


def test_total_row_cap_includes_warmup(api):
    client, retained = api
    big = Retained(retained.store.root,count=3000)
    retained.rows, retained.summary = big.rows, big.summary
    query = params(start=big.rows[2500]["session_date"],end=big.rows[2503]["session_date"],
                   warmup_sessions="2500",limit="1000")
    counts, warmup = [], []
    while True:
        response = client.get(PREFIX+"/bars",params=query)
        assert response.status_code == 200 and len(response.content) <= 1024**2
        page=response.json(); counts.append(page["row_count"]); warmup.append(page["warmup"]["returned"])
        if not page["next_cursor"]: break
        query["cursor"]=page["next_cursor"]
    assert counts == [1000,1000,503] and sum(warmup) == 2500


@pytest.mark.parametrize("error,status", [(HistoryError("HISTORY_REVISION_NOT_FOUND"),404),
    (HistoryError("HISTORY_OBJECT_HASH"),409),(HistoryError("HISTORY_SCHEMA_MISSING"),503),
    (OSError("secret path /private/password"),503)])
def test_readiness_errors_and_legacy_health_are_separate(api, error, status):
    client, retained = api
    assert client.get("/v1/history/readyz").json()["chart_data_available"] is True
    retained.failure = error
    response = client.get("/v1/history/readyz")
    assert response.status_code == status and "password" not in response.text and "/private" not in response.text
    assert client.get("/readyz").status_code == 200
    result = client.get(PREFIX+"/bars",params=params())
    assert result.status_code == status and set(result.json()) == {"code"}


def test_unknown_revision_asset_and_empty_catalog(api):
    client, retained = api
    assert client.get(PREFIX+"/bars",params=params(instrument_id="unknown")).status_code == 404
    assert client.get(PREFIX.replace(REVISION,"histrev-"+"9"*64)).status_code == 404
    assert client.get(PREFIX.replace(REVISION,"latest")).status_code == 422
    retained.rows = []
    assert client.get("/v1/history/readyz").json()["chart_data_available"] is False
    assert client.get("/v1/history/datasets").json()["items"] == []


def test_storage_allocation_interface(monkeypatch):
    monkeypatch.setenv("POLAR_DATABASE_URL","unused")
    monkeypatch.delenv("POLAR_STORAGE_BYTES",raising=False)
    assert Settings.load().storage_bytes == 64*1024**3
    monkeypatch.setenv("POLAR_STORAGE_BYTES",str(16*1024**3))
    assert Settings.load().storage_bytes == 16*1024**3
    for invalid in ("0","-1","1.0",str(64*1024**3+1),"9"*100):
        monkeypatch.setenv("POLAR_STORAGE_BYTES",invalid)
        with pytest.raises(ValueError,match="INVALID_STORAGE_ALLOCATION"): Settings.load()


def test_history_unavailable_configuration_is_sanitized(monkeypatch):
    def unavailable(): raise ValueError("private configuration /secret/password")
    monkeypatch.setattr(Settings,"load",unavailable)
    client=TestClient(create_app())
    response=client.get("/v1/history/readyz")
    assert response.status_code == 503 and response.json() == {"code":"HISTORY_DEPENDENCY_UNAVAILABLE"}
    assert client.get("/livez").status_code == 200
