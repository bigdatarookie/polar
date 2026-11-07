"""Series API bounds/invariance using invented rows, no PostgreSQL/runtime/provider."""
import copy
from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.config import Settings
from polar.history_bundle import BASES,canonical,sha,HistoryError
from polar.history_calendar import reference_calendar
from polar.service import Service

DATASET="invented-series"
REVISION="histrev-"+"1"*64
PREFIX=f"/v1/history/datasets/{DATASET}/revisions/{REVISION}/series"


class Retained:
    def __init__(self,root):
        self.store=SimpleNamespace(root=root)
        self.dates=[(date(2024,1,2)+timedelta(days=i)).isoformat() for i in range(8)]
        self.sources={name:[{"session_date":s,"close":str(v),"adjusted_close":str(v*2)}
            for s,v in zip(self.dates,values)] for name,values in
            (("a",[1,1,4,10,10,10,10,10]),("b",[10]*8))}
        self.summary={"dataset_id":DATASET,"dataset_revision":REVISION,"import_receipt_id":"2"*64,
            "manifest_sha256":"3"*64,"basis":BASES,"fitness":{"financial_evaluation":"NOT_RUN",
            "causal_PIT_fitness":"INSUFFICIENT_EVIDENCE"},"instruments":[self.asset(k) for k in self.sources]}
    def asset(self,k):
        return {"instrument_id":k,"currency":"USD","first_date":self.dates[0],"last_date":self.dates[-1],
            "calendar_status":"UNVERIFIED","row_count":8,"quarantined_rows":0,"duplicate_rows":0,
            "quarantine_reason_counts":{},"chart_fitness":"READY_WITH_LIMITS"}
    def load_revision(self,dataset,revision):
        if (dataset,revision)!=(DATASET,REVISION):raise HistoryError("HISTORY_REVISION_NOT_FOUND")
        return copy.deepcopy(self.summary),SimpleNamespace(files={"bars/"+k+".ndjson":b"".join(canonical(r)+b"\n" for r in v)
                                                               for k,v in self.sources.items()})


@pytest.fixture
def api(tmp_path,monkeypatch):
    retained=Retained(tmp_path)
    key=tmp_path/"test.key";key.write_bytes(bytes(range(32)))
    service=Service(Settings("unused",tmp_path,history_cursor_key_file=key))
    service.history_registry=retained
    service.registry.check=lambda:None
    def invented_reference(*args):
        return retained.dates,{"status":"QUALIFIED_REFERENCE_DATES_ONLY","calendar_sha256":"4"*64,
            "binding_sha256":"5"*64,"scope":"INVENTED_TEST_REFERENCE"}
    monkeypatch.setattr("polar.history_series.reference_calendar",invented_reference)
    return TestClient(create_app(service)),retained


def params(**overrides):
    return {"instrument_id":"a","benchmark_instrument_id":"b","start":"2024-01-04","end":"2024-01-09",
            "sma_period":"3","ema_period":"3","bb_period":"2","rsi_period":"2",**overrides}


def get(client,**overrides):
    response=client.get(PREFIX,params=params(**overrides))
    assert response.status_code==200,response.text
    return response.json()


def test_page_and_window_invariance_full_prefix(api):
    client,_=api
    full=get(client,start="2024-01-02",end="2024-01-10")
    rows=[];query=params(limit="1",warmup_sessions="1")
    while True:
        response=client.get(PREFIX,params=query);assert response.status_code==200
        page=response.json();assert page["row_count"]<=1 and len(response.content)<=1024**2
        rows.extend(page["rows"])
        if page["next_cursor"] is None:break
        query["cursor"]=page["next_cursor"]
    expected=[r for r in full["rows"] if "2024-01-03"<=r["session_date"]<"2024-01-09"]
    assert [{k:v for k,v in r.items() if k!="row_role"} for r in rows] == [
        {k:v for k,v in r.items() if k!="row_role"} for r in expected]
    narrow=get(client,start="2024-01-05",end="2024-01-06")
    assert narrow["rows"][0]["values"]["ema"]=="6"
    assert narrow["reference_metadata"]["anchor_session"]=="2024-01-02"
    assert narrow["reference_metadata"]["asset_anchor"]=="1"
    assert narrow["parameters"]["bb_deviation"]=="2"
    assert full["coverage"]["original_calendar_status"]=="UNVERIFIED"


@pytest.mark.parametrize('change',[{"ema_period":"4"},{"basis":"ADJUSTED_CLOSE"},{"start":"2024-01-05"},
    {"reference_family":"PROVIDER_ADJUSTED_CLOSE_INDEX"},{"instrument_id":"b"},{"limit":"3"},
    {"benchmark_instrument_id":"a"},{"warmup_sessions":"1"}])
def test_cursor_binds_every_numeric_projection_input(api,change):
    client,_=api
    page=get(client,limit="2")
    response=client.get(PREFIX,params=params(limit="2",cursor=page["next_cursor"],**change)) if "limit" not in change else client.get(
        PREFIX,params=params(cursor=page["next_cursor"],**change))
    assert response.status_code==422


def test_missing_leg_resets_indicators_but_reference_recovers_same_anchor(api):
    client,retained=api
    del retained.sources["a"][2]
    page=get(client,start="2024-01-02",end="2024-01-10")
    gap=page["rows"][2]
    assert gap["values"]["asset_reference"] is gap["values"]["benchmark_reference"] is None
    assert gap["statuses"]["ema"]["reason"]=="GAP"
    assert page["rows"][3]["values"]["asset_reference"]=="1E+3"
    assert page["rows"][3]["values"]["ema"] is None
    assert page["coverage"]["missing_expected_sessions"]==1
    assert page["rows"][5]["values"]["ema"]=="1E+1"


def test_omission_disabled_unresolved_and_empty(api,monkeypatch):
    client,_=api
    query=params();[query.pop(k) for k in ("sma_period","ema_period","bb_period","rsi_period")]
    page=client.get(PREFIX,params=query).json()
    assert page["rows"][0]["statuses"]["ema"]["status"]=="DISABLED"
    monkeypatch.setattr("polar.history_series.reference_calendar",lambda *args:(None,{"status":"UNRESOLVED_GAPS"}))
    page=get(client)
    assert page["rows"][0]["statuses"]["sma"]["reason"]=="UNRESOLVED_GAPS"
    assert page["coverage"]["expected_sessions"] is None
    assert get(client,start="2025-01-01",end="2025-01-02")["data_status"]=="EMPTY_WINDOW"


@pytest.mark.parametrize('change',[{"sma_period":"1"},{"ema_period":"03"},{"bb_deviation":"NaN"},
    {"bb_deviation":"1e-19"},{"bb_deviation":"10.0001"},{"rsi_period":"501"},{"limit":"1001"},
    {"warmup_sessions":"2501"},{"basis":"raw"}])
def test_invalid_numeric_queries(api,change):
    client,_=api
    assert client.get(PREFIX,params=params(**change)).status_code==422


def test_reference_family_not_raw_substitution(api):
    client,retained=api
    retained.sources["a"][3]["adjusted_close"]="100"
    raw=get(client,start="2024-01-05",end="2024-01-06")
    adjusted=get(client,start="2024-01-05",end="2024-01-06",reference_family="PROVIDER_ADJUSTED_CLOSE_INDEX")
    assert raw["rows"][0]["values"]["asset_reference"]=="1E+3"
    assert adjusted["rows"][0]["values"]["asset_reference"]=="5E+3"
    assert raw["rows"][0]["values"]["ema"]==adjusted["rows"][0]["values"]["ema"]


def test_duplicate_and_unknown_asset_fail(api):
    client,retained=api
    assert client.get(PREFIX,params=params(instrument_id="absent")).status_code==404
    retained.sources["a"].append(retained.sources["a"][0])
    assert client.get(PREFIX,params=params()).status_code==409


def test_sidecar_absent_corrupt_and_identity_binding(tmp_path,monkeypatch):
    retained=Retained(tmp_path);summary,bundle=retained.load_revision(DATASET,REVISION)
    assert reference_calendar(tmp_path/"missing",summary,bundle)[0] is None
    calendar={"sessions":retained.dates,"dates_only":True,"applicability":"COMMON_US_EQUITY_REFERENCE_NOT_PRIMARY_VENUE",
              "calendar":"INVENTED","calendar_version":"test","start":retained.dates[0],"end_inclusive":retained.dates[-1]}
    binding={"dataset_revision":REVISION,"manifest_sha256":"3"*64,"primary_import_receipt_id":"2"*64,
             "comparisons":[{"instrument_id":k,"bar_object_sha256":sha(bundle.files["bars/"+k+".ndjson"])} for k in ("a","b")]}
    raw,br=canonical(calendar),canonical(binding)
    (tmp_path/"calendar.json").write_bytes(raw);(tmp_path/"binding.json").write_bytes(br)
    monkeypatch.setattr("polar.history_calendar.CALENDAR_SHA256",sha(raw));monkeypatch.setattr("polar.history_calendar.BINDING_SHA256",sha(br))
    sessions,meta=reference_calendar(tmp_path,summary,bundle)
    assert sessions==retained.dates and meta["listing_PIT"]=="UNQUALIFIED"
    assert reference_calendar(tmp_path,{**summary,"import_receipt_id":"9"*64},bundle)[0] is None
    (tmp_path/"calendar.json").write_bytes(raw+b" ")
    with pytest.raises(HistoryError,match="HISTORY_CALENDAR_INTEGRITY_ERROR"):
        reference_calendar(tmp_path,summary,bundle)


def test_byte_cap_shrinks_page_without_loss_or_extra_warmup(api,monkeypatch):
    client,_=api
    original=client.get(PREFIX,params=params(limit="2"))
    assert original.status_code==200
    # Retain the entire shared metadata but allow exactly one point, not two.
    one=client.get(PREFIX,params=params(limit="1"))
    monkeypatch.setattr("polar.history_queries.MAX_RESPONSE_BYTES",len(one.content)+20)
    query=params(limit="8");rows=[]
    while True:
        response=client.get(PREFIX,params=query)
        assert response.status_code==200 and len(response.content)<=len(one.content)+20
        page=response.json();assert page["row_count"]==1
        rows.extend(page["rows"])
        if page["next_cursor"] is None:break
        query["cursor"]=page["next_cursor"]
    assert len(rows)==5 and len({r["session_date"] for r in rows})==5


def test_disabled_overlay_does_not_change_other_series(api):
    client,_=api
    original=get(client)
    query=params();query.pop("sma_period");query.pop("bb_period")
    reduced=client.get(PREFIX,params=query).json()
    assert [r["values"]["ema"] for r in original["rows"]]==[r["values"]["ema"] for r in reduced["rows"]]


def test_reference_no_overlap_and_empty_asset(api):
    client,retained=api
    retained.sources["b"]=[]
    page=get(client)
    assert page["reference_metadata"]["status"]=="NO_OVERLAP"
    assert all(r["values"]["asset_reference"] is None for r in page["rows"])
    retained.sources["a"]=[]
    assert get(client)["data_status"]=="EMPTY_WINDOW"


def test_calendar_configuration_default_and_explicit_path(tmp_path,monkeypatch):
    monkeypatch.setenv("POLAR_DATABASE_URL","unused")
    monkeypatch.setenv("POLAR_ARTIFACT_ROOT",str(tmp_path))
    monkeypatch.delenv("POLAR_HISTORY_CALENDAR_DIR",raising=False)
    settings=Settings.load()
    assert settings.history_calendar_dir is None
    assert Service(settings).history_calendar_dir==tmp_path/"history-calendar"
    monkeypatch.setenv("POLAR_HISTORY_CALENDAR_DIR",str(tmp_path/"bound-reference"))
    assert Service(Settings.load()).history_calendar_dir==tmp_path/"bound-reference"


def test_orphan_deviation_and_duplicate_query_rejected(api):
    client,_=api
    query=params(bb_deviation="2");query.pop("bb_period")
    assert client.get(PREFIX,params=query).status_code==422
    query=list(params().items())+[("ema_period","3")]
    assert client.get(PREFIX,params=query).status_code==422
