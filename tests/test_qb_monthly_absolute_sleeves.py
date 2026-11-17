"""Exact candidate through the existing native engine on invented prices only."""
import hashlib
import json
from pathlib import Path

from polar.qb_monthly_absolute_sleeves import profile
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from reference_fixture import write
from scheduled_fixture import fixture
from test_scheduled_service import snapshot


def test_candidate_native_and_saved_only_reproduction(tmp_path, monkeypatch):
    store, old, _, _ = fixture(tmp_path, monkeypatch)
    manifest = json.loads(Path(old["input_ref"]["path"]).read_bytes())
    aliases = {"AAA": "BIL", "BBB": "SHY", "CCC": "VTI"}
    with Path(manifest["quotes"]["path"]).open() as stream:
        original = [json.loads(line) for line in stream]
    rows = [{**r, "symbol": aliases[r["symbol"]]} for r in original if r["symbol"] in aliases]
    quotes = tmp_path / "invented-trend-quotes.ndjson"
    quotes.write_bytes(b"".join((json.dumps(r, sort_keys=True) + "\n").encode() for r in rows))
    manifest.update(symbols=sorted(aliases.values()), rows=len(rows),
        quotes={"path": str(quotes), "sha256": hashlib.sha256(quotes.read_bytes()).hexdigest(),
                "bytes": quotes.stat().st_size})
    source = write(tmp_path / "invented-trend-source.json", manifest)
    protocol = write(tmp_path / "invented-trend-protocol.json", {"classification": "INVENTED"})
    p = profile(protocol_sha256=protocol["sha256"], input_sha256=source["sha256"],
                calendar_sha256=old["calendar_ref"]["sha256"], timezone_sha256=old["timezone_ref"]["sha256"])
    pp = write(tmp_path / "invented-trend-profile.json", p)
    cfg = {**old, "profile_ref": pp, "protocol_ref": protocol, "input_ref": source,
           "candidate_id": "INVENTED-QB-MONTHLY-TREND", "experiment_id": "INVENTED-QB-MONTHLY-TREND-ORIGINAL"}
    assert manifest["rights"] == "INVENTED_PUBLIC_TEST" and cfg["namespace"] == "INVENTED"
    service = ReferenceResearchService(store, 128 * 1024**2)
    assert service.preflight(cfg)["expected_native_accounts"] == 10
    assert not list(store.rglob("start.json"))
    result = service.run(cfg)
    assert result["status"] == "SUCCESS" and result["native_accounts"] == 10
    assert result["fit_calls"] == result["predict_calls"] == result["model_calls"] == 0
    for phase, publication in result["results"].items():
        detail = ResearchResults(store, 128 * 1024**2).read(publication["result_id"])
        assert {s["id"] for s in detail["record"]["series"]} == {"TREND", "EW", "EW_HALF", "MOM", "CASH"}
        assert [s["id"] for s in detail["record"]["series"] if s["role"] == "STRATEGY"] == ["TREND"]
        assert len(detail["record"]["criteria"]) == (len(p["criteria"]) if phase == "FINAL" else 0)
        assert detail["assessment"]["financial"] == "NOT_REVIEWED"
    before = snapshot(store)
    import polar.scheduled_service as module

    def forbidden(*args, **kwargs):
        raise AssertionError("STORED_REPRODUCTION_EXECUTED_SOURCE_POLICY_OR_NATIVE")

    for name in ("load_reference", "plan_phase", "bounded_native"):
        monkeypatch.setattr(module, name, forbidden)
    assert service.recompute(result["semantic_id"])["status"] == "REPRODUCED"
    assert snapshot(store) == before
