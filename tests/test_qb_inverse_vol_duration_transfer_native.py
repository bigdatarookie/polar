"""Actual candidate profile through native accounts on invented operands only."""
import hashlib
import json
from pathlib import Path
from zoneinfo import TZPATH

import pytest

from polar.qb_inverse_vol_duration_transfer import profile
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from reference_fixture import write
from scheduled_fixture import inverse_fixture
from test_scheduled_service import snapshot


def candidate_fixture(tmp_path, monkeypatch):
    store, old, _, calendar = inverse_fixture(tmp_path, monkeypatch)
    manifest = json.loads(Path(old["input_ref"]["path"]).read_bytes())
    # The existing public fixture supplies only invented observations. Project
    # its four invented instruments to the candidate's declared aliases;
    # this neither reads nor relabels a retained instrument or source payload.
    aliases = {"AAA": "BIL", "BBB": "SHY", "CCC": "VTI", "DDD": "TLT"}
    with Path(manifest["quotes"]["path"]).open() as stream:
        rows = [json.loads(line) for line in stream]
    selected = [{**row, "symbol": aliases[row["symbol"]]}
                for row in rows if row["symbol"] in aliases]
    quotes = tmp_path / "invented-qb-quotes.ndjson"
    quotes.write_bytes(b"".join((json.dumps(row, sort_keys=True) + "\n").encode()
                               for row in selected))
    manifest.update(symbols=sorted(aliases.values()), rows=len(selected),
                    quotes={"path": str(quotes), "bytes": quotes.stat().st_size,
                            "sha256": hashlib.sha256(quotes.read_bytes()).hexdigest()})
    source = write(tmp_path / "invented-qb-source.json", manifest)
    protocol = write(tmp_path / "invented-qb-protocol.json", {
        "schema": "polar.invented-scheduled-protocol/1", "classification": "INVENTED",
        "purpose": "Exact candidate profile integration, no retained scientific result"})
    timezone = next((Path(root) / "America/New_York" for root in TZPATH
                     if (Path(root) / "America/New_York").is_file()), None)
    if timezone is None:
        from importlib.resources import files
        raw = files("tzdata").joinpath("zoneinfo/America/New_York").read_bytes()
    else:
        raw = timezone.read_bytes()
    tz = tmp_path / "candidate-NewYork"
    tz.write_bytes(raw)
    tzref = {"path": str(tz), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    candidate = profile(protocol_sha256=protocol["sha256"], input_sha256=source["sha256"],
                        calendar_sha256=old["calendar_ref"]["sha256"],
                        timezone_sha256=tzref["sha256"])
    pp = write(tmp_path / "invented-qb-profile.json", candidate)
    cfg = {**old, "profile_ref": pp, "protocol_ref": protocol, "input_ref": source,
           "timezone_ref": tzref, "candidate_id": "INVENTED-QB-INVERSE-VOL-DURATION-TRANSFER",
           "experiment_id": "INVENTED-QB-INVERSE-VOL-DURATION-TRANSFER-ORIGINAL"}
    assert cfg["namespace"] == "INVENTED"
    assert manifest["rights"] == "INVENTED_PUBLIC_TEST"
    return store, cfg, candidate


def test_exact_candidate_native_scenarios_wire_and_saved_only_reproduction(tmp_path, monkeypatch):
    store, cfg, candidate = candidate_fixture(tmp_path, monkeypatch)
    service = ReferenceResearchService(store, 128 * 1024**2)
    ready = service.preflight(cfg)
    assert ready["expected_native_accounts"] == 6
    assert ready["scientific_starts"] == 0
    assert not list(store.rglob("start.json"))
    result = service.run(cfg)
    assert result["status"] == "SUCCESS" and result["native_accounts"] == 6
    assert result["fit_calls"] == result["predict_calls"] == result["model_calls"] == 0
    assert set(result["results"]) == {"FINAL", "FINAL_COST_STRESS"}
    semantic = store / "reference-research-experiments" / result["semantic_id"]
    phases = json.loads((semantic / "phases.json").read_bytes())
    assert phases["FINAL"]["plan"]["decisions"] == phases["FINAL_COST_STRESS"]["plan"]["decisions"]
    assert (semantic / "uncertainty.json").is_file()
    for phase, scenario in zip(("FINAL", "FINAL_COST_STRESS"), candidate["cost_scenarios"]):
        saved = phases[phase]
        assert saved["simulation"]["cost_profile"] == scenario["cost_profile"]
        assert saved["plan"]["cost_profile"] == scenario["cost_profile"]
        assert saved["plan"]["signals"]
        assert {leg["id"] for leg in saved["simulation"]["legs"]} == {
            "INVVOL", "EW", "MOM"}
        for leg in saved["simulation"]["legs"]:
            assert all(q == 0 for q in leg["nav"][-1]["positions"].values())
        record = ResearchResults(store, 128 * 1024**2).read(result["results"][phase]["result_id"])
        assert len(record["record"]["series"]) == 3
        assert len(record["record"]["criteria"]) == len(candidate["criteria"])
        assert [series["id"] for series in record["record"]["series"]
                if series["role"] == "STRATEGY"] == ["INVVOL"]
        assert record["record"]["primary_benchmark_id"] == "EW"
        assert record["assessment"]["financial"] == "NOT_REVIEWED"
    before = snapshot(store)
    import polar.scheduled_service as module

    def forbidden(*args, **kwargs):
        raise AssertionError("STORED_REPRODUCTION_EXECUTED_SOURCE_POLICY_OR_NATIVE")

    for name in ("load_reference", "plan_phase", "bounded_native"):
        monkeypatch.setattr(module, name, forbidden)
    reproduced = service.recompute(result["semantic_id"])
    assert reproduced["status"] == "REPRODUCED"
    assert reproduced["native_calls"] == reproduced["store_writes"] == 0
    assert snapshot(store) == before
    with pytest.raises(ValueError, match="SCHEDULED_ORIGINAL_ALREADY_RECORDED"):
        service.run(cfg)
