"""Invented saved-result controls; never published as a real research answer."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.config import Settings
from polar.service import Service
from polar.research_results import ResearchResults, ResearchError, validate_result


def value(v="100000", status="OK", reason=None):
    return {"value": v, "status": status, "reason": reason}


def invented_result():
    legs = ["invented-strategy", "invented-benchmark"]
    return {
        "schema_version": "polar.research-result/1",
        "question": {"id": "invented-question", "label": "Invented persistence control", "summary": "Not a research result"},
        "bindings": {"protocol_id": "invented", "protocol_sha256": "1" * 64,
                     "data_revision": "invented", "data_sha256": "2" * 64,
                     "code_revision": "3" * 40, "evaluator_revision": "4" * 40,
                     "runtime_id": "sha256:" + "5" * 64, "producer_id": "invented-author",
                     "candidate_id": "invented-candidate", "experiment_id": "invented-experiment"},
        "basis": {"currency": "USD", "frequency": "DAILY", "timezone": "UTC",
                  "wealth_basis": "PRICE_ONLY", "cost_basis": "NET", "cash_basis": "Zero modeled credit",
                  "risk_free_basis": "Zero modeled reference"},
        "grid": ["2020-01-02T21:00:00Z", "2020-01-03T21:00:00Z"],
        "series": [{"id": leg, "label": leg, "role": role, "unit": "USD", "values": [value(), value(v)],
                    "ledger": [{"cash": "100000", "exposure": "0", "cumulative_flat_fees": "0",
                                "cumulative_bps_fees": "0", "positions": {},
                                "net_return": value(None, "NOT_APPLICABLE", "INITIAL_POINT")} for _ in range(2)]}
                   for leg, role, v in zip(legs, ["STRATEGY", "BENCHMARK"], ["99998", "100002"])],
        "primary_benchmark_id": legs[1],
        "metrics": [{"id": "final_nav", "label": "Final NAV", "unit": "USD",
                     "values": {legs[0]: value("99998"), legs[1]: value("100002")}}],
        "comparisons": [{"metric_id": "final_nav", "left_id": legs[0], "right_id": legs[1],
                         "unit": "USD", "result": value("-4"), "interpretation": "Invented negative difference"}],
        "costs": [{"id": "fees", "label": "Charged fees", "kind": "CHARGED_FEES", "unit": "USD",
                   "values": {leg: value("2") for leg in legs}, "description": "Invented test fee"}],
        "limitations": [{"code": "INVENTED", "text": "Synthetic fixture only", "scope": "Entire result"}],
        "provenance": [{"role": "semantic_manifest", "id": "invented-manifest", "sha256": "6" * 64}],
        "evidence_level": "INVENTED_CONTROL", "financial_claim": "No financial claim",
        "criteria": [], "point_interpretation": "Invented control only",
    }


def test_persist_restart_http_and_tamper(tmp_path):
    service = Service(Settings("unused", tmp_path))
    result = invented_result()
    publication = service.research_publish(result)
    rid = publication["result_id"]
    assert service.research_publish(result) == publication
    # Fresh service performs the same disk reads; no in-memory result cache.
    client = TestClient(create_app(Service(Settings("unused", tmp_path))))
    assert client.get("/v1/research/results").json()["items"][0]["result_id"] == rid
    detail = client.get("/v1/research/results/" + rid).json()
    assert detail["record"] == result
    assert detail["assessment"]["financial"] == "NOT_REVIEWED"
    assert client.get("/v1/research/results/not-an-id").status_code == 422
    assert client.get("/v1/research/results?limit=11").status_code == 422
    path = tmp_path / "research-results" / rid / "result.json"
    path.chmod(0o600)
    path.write_text("{}")
    response = client.get("/v1/research/results/" + rid)
    assert response.status_code == 409 and response.json()["code"] == "RESEARCH_CONTENT_MISMATCH"


@pytest.mark.parametrize("mutation", [
    lambda r: r["series"][0]["values"].pop(),
    lambda r: r["series"][0]["values"][0].update(value=None),
    lambda r: r["series"][0]["values"][0].update(value="NaN"),
    lambda r: r["metrics"][0]["values"].pop("invented-benchmark"),
    lambda r: r["grid"].reverse(),
    lambda r: r["provenance"][0].update(path="/private/not-public"),
    lambda r: r.update(financial_verdict="PASS"),
    lambda r: r["grid"].__setitem__(0, "2020-02-30T21:00:00Z"),
    lambda r: r["question"].update(summary="Evidence at /Users/private/file.json"),
    lambda r: r["limitations"][0].update(text="file:///private/input.json"),
    lambda r: r["limitations"][0].update(text="file:/private/input.json"),
    lambda r: r["costs"][0].update(description="C:\\private\\input.json"),
])
def test_closed_wire_fails_instead_of_synthesizing(mutation):
    result = invented_result()
    mutation(result)
    with pytest.raises(ResearchError, match="RESEARCH_INVALID_RESULT"):
        validate_result(result)


def test_explicit_missing_point_and_zero_kept_distinct():
    result = invented_result()
    result["series"][0]["values"][1] = value(None, "UNAVAILABLE", "MISSING_MARK")
    result["series"][1]["values"][1] = value("0")
    assert validate_result(result)["series"] == result["series"]


def test_review_exact_content_scope_and_no_self_acceptance(tmp_path):
    store = ResearchResults(tmp_path, 64 * 1024**3)
    p = store.publish(invented_result())
    review = {"schema_version": "polar.research-review/1", "result_id": p["result_id"],
              "content_sha256": p["content_sha256"], "reviewer_id": "invented-nonauthor",
              "scope": "FINANCIAL", "verdict": "NOT_SUPPORTED", "scope_description": "Invented control",
              "reference": {"role": "review", "id": "invented-review", "sha256": "7" * 64},
              "recorded_at": "2026-11-09T20:00:00Z", "evidence_status": "ASSESSED_WITH_LIMITS", "reason": None}
    store.review(review)
    assert store.read(p["result_id"])["assessment"]["financial"] == "NOT_SUPPORTED"
    bad = deepcopy(review)
    bad["content_sha256"] = "0" * 64
    with pytest.raises(ResearchError, match="REVIEW_BINDING"):
        store.review(bad)
    bad = deepcopy(review)
    bad["reviewer_id"] = "invented-author"
    with pytest.raises(ResearchError, match="REVIEW_BINDING"):
        store.review(bad)
    bad = deepcopy(review)
    bad["verdict"] = "PASS"
    with pytest.raises(ResearchError, match="INVALID_REVIEW"):
        store.review(bad)


def test_safe_publication_and_read_namespace(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "research-results").symlink_to(elsewhere)
    with pytest.raises(Exception):
        ResearchResults(root, 100000).publish(invented_result())


@pytest.mark.parametrize('count',[30,31])
def test_lossless_limitation_cardinality_http_and_strict_overflow(tmp_path,count):
    record=invented_result()
    record['limitations']=[{'code':f'INVENTED_LIMIT_{i}','scope':f'Invented scope {i}',
        'text':f'Exact invented limitation {i}: preserve every object.'} for i in range(count)]
    original=deepcopy(record)
    assert validate_result(record)==original
    service=Service(Settings('unused',tmp_path));pub=service.research_publish(record)
    client=TestClient(create_app(Service(Settings('unused',tmp_path))))
    response=client.get('/v1/research/results/'+pub['result_id'])
    assert response.status_code==200 and response.json()['record']==original
    assert service.research_publish(record)==pub  # Original content identity stable.
    overflow=deepcopy(record)
    overflow['limitations'] += [{'code':f'OVERFLOW_{i}','scope':'Invented','text':'Not truncated.'} for i in range(32-count)]
    with pytest.raises(ResearchError,match='RESEARCH_INVALID_RESULT'):validate_result(overflow)
    invalid=deepcopy(record);invalid['limitations'][-1]['arbitrary']='Not admitted'
    with pytest.raises(ResearchError,match='RESEARCH_INVALID_RESULT'):validate_result(invalid)
    invalid=deepcopy(record);invalid['limitations'][-1]['text']='file:///private/not-public'
    with pytest.raises(ResearchError,match='RESEARCH_INVALID_RESULT'):validate_result(invalid)
    # This capacity extension does not relax provenance or metric cardinality.
    invalid=deepcopy(record);invalid['provenance']*=31
    with pytest.raises(ResearchError,match='RESEARCH_INVALID_RESULT'):validate_result(invalid)


def test_result_json_schema_matches_executable_capacity():
    import json
    from pathlib import Path
    from polar.research_results import ResearchResult
    import polar.research_results as module
    saved=json.loads(Path(module.__file__).with_name('research_result_schema.json').read_bytes())
    assert saved==ResearchResult.model_json_schema()
    assert saved['properties']['limitations']['maxItems']==31
    assert saved['properties']['provenance']['maxItems']==30
    assert saved['properties']['metrics']['maxItems']==40
