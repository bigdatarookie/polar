"""Regression witnesses for the independent F1/F2/F3 review of 547ba77."""
from copy import deepcopy
from decimal import Decimal
from itertools import permutations
import hashlib
import json
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from polar.engine import calculate
from polar.models import Dataset
from polar.artifacts import ArtifactStore
import pyarrow.parquet as pq
from fastapi.testclient import TestClient
from polar.api import create_app


def rebind(raw, config):
    data = Dataset.model_validate(raw)
    return data, config.model_copy(update={"dataset_id": data.dataset_id})


def simultaneous(raw):
    dividend = next(a for a in raw["actions"] if a["kind"] == "dividend")
    for key in ["event_time", "effective_time", "ex_at", "pay_at"]:
        dividend[key] = "2024-01-04T14:30:00Z"
    dividend.update(entitlement_at="2024-01-03T21:00:00Z",
                    published_at="2024-01-03T21:01:00Z",
                    available_at="2024-01-03T21:01:00Z",
                    ingested_at="2024-01-03T21:01:01Z")


@pytest.mark.parametrize("action_index", [0, 1, 2])
def test_f1_late_action_rejected_before_accounting(data, action_index):
    raw = data.model_dump(mode="json")
    raw["actions"][action_index]["ingested_at"] = "2024-01-10T21:00:02Z"
    with pytest.raises(ValidationError, match="ACTION_NOT_AVAILABLE_AT_EFFECTIVE_TIME"):
        Dataset.model_validate(raw)
    calls = []
    registry = SimpleNamespace(register_dataset=lambda *args: calls.append(args))
    response = TestClient(create_app(SimpleNamespace(registry=registry))).post("/v1/datasets", json=raw)
    assert response.status_code == 422 and response.json()["code"] == "INVALID_SCHEMA"
    assert calls == []  # Actual request validation prevents registration effects.


def test_f1_effective_open_is_inclusive_boundary(data, config):
    raw = data.model_dump(mode="json")
    for action in raw["actions"]:
        action["ingested_at"] = action["effective_time"]
    updated, bound = rebind(raw, config)
    report = calculate(updated, bound)
    assert report["status"] == "COMPLETED"
    assert report["nav"][-1]["nav"] == "1014"
    assert all(a["receipt_at"] == a["at"] for a in report["corporate_action_ledger"])


def test_f1_ingestion_just_after_effective_open_is_explicitly_unsupported(data):
    raw = data.model_dump(mode="json")
    raw["actions"][0]["ingested_at"] = "2024-01-04T14:30:00.000001Z"
    with pytest.raises(ValidationError, match="ACTION_NOT_AVAILABLE_AT_EFFECTIVE_TIME"):
        Dataset.model_validate(raw)


def test_f2_split_transforms_prior_entitlement_independent_of_input_order(data, config):
    raw = data.model_dump(mode="json")
    simultaneous(raw)
    expected = None
    for actions in permutations(raw["actions"]):
        updated, bound = rebind({**raw, "actions": list(actions)}, config)
        report = calculate(updated, bound)
        assert report["status"] == "COMPLETED"
        assert [Decimal(n["nav"]) for n in report["nav"]] == list(map(Decimal, ["1000", "1039", "1039", "1032", "1026", "1014"]))
        assert report["nav"][2]["cash"] == "607"
        assert report["nav"][2]["shares"] == "8"
        assert report["metrics"]["dividends"]["value"] == "8"
        assert report["metrics"]["fees"]["value"] == "2"
        ledger = report["corporate_action_ledger"]
        assert [a["kind"] for a in ledger[:2]] == ["split", "dividend"]
        assert ledger[1]["cash"] == "607" and ledger[1]["shares"] == "8"
        # Input identity differs by permutation; the accounting effect must not.
        effect = {key: report[key] for key in ["nav", "fills", "corporate_action_ledger", "metrics", "gross_counterfactual"]}
        if expected is not None:
            assert effect == expected
        expected = effect


def test_f2_pending_buy_does_not_receive_prior_close_dividend(data, config):
    raw = data.model_dump(mode="json")
    simultaneous(raw)
    raw["bars"][1].update(open=None, tradable=False, price_status="MISSING")
    updated, bound = rebind(raw, config)
    report = calculate(updated, bound.model_copy(update={"orders": [bound.orders[0]]}))
    assert report["status"] == "COMPLETED"
    assert report["fills"][0]["quantity"] == "8"
    assert report["nav"][2]["cash"] == "559"
    assert report["metrics"]["dividends"]["value"] == "0"


def test_f2_ambiguous_duplicate_kind_fails_closed(data, config):
    raw = data.model_dump(mode="json")
    duplicate = deepcopy(raw["actions"][0])
    duplicate["action_id"] = "second-split"
    raw["actions"].append(duplicate)
    updated, bound = rebind(raw, config)
    report = calculate(updated, bound)
    assert report["status"] == "INVALID"
    assert report["diagnostic"] == "AMBIGUOUS_SIMULTANEOUS_ACTIONS"
    assert not report["nav"] and not report["fills"]


def test_f2_settlement_follows_split_and_dividend_before_pending_sale(data, config):
    raw = data.model_dump(mode="json")
    simultaneous(raw)
    settlement = raw["actions"][2]
    for key in ["event_time", "effective_time"]:
        settlement[key] = "2024-01-04T14:30:00Z"
    settlement.update(published_at="2024-01-03T21:01:00Z",
                      available_at="2024-01-03T21:01:00Z",
                      ingested_at="2024-01-03T21:01:01Z")
    # A prior-close sale is adjusted by the split then canceled by settlement.
    orders = [config.orders[0], config.orders[1].model_copy(update={"decision_session_id": "2024-01-03"})]
    for actions in permutations(raw["actions"]):
        updated, bound = rebind({**raw, "actions": list(actions)}, config)
        report = calculate(updated, bound.model_copy(update={"orders": orders}))
        assert report["status"] == "COMPLETED"
        assert [a["kind"] for a in report["corporate_action_ledger"]] == ["split", "dividend", "delisting_cash_settlement"]
        assert report["nav"][2]["cash"] == "1007"  # 599 + 8 + 8*50
        assert report["nav"][2]["shares"] == "0"
        assert len(report["fills"]) == 1
        assert report["orders"][-1]["status"] == "CANCELED"
        assert report["orders"][-1]["reason"] == "DELISTING"


@pytest.mark.parametrize("row_present", [True, False])
def test_f3_missing_flat_price_is_valid_cash_with_incomplete_coverage(data, config, row_present):
    raw = data.model_dump(mode="json")
    if row_present:
        raw["bars"][2].update(open=None, high=None, low=None, close=None,
                              price_status="MISSING", tradable=False)
    else:
        raw["bars"].pop(2)
    updated, bound = rebind(raw, config)
    report = calculate(updated, bound.model_copy(update={"strategy_version": "cash-flat-v1", "orders": []}))
    assert report["status"] == "COMPLETED"
    assert [n["nav"] for n in report["nav"]] == ["1000"] * 6
    affected = report["nav"][2]
    assert affected["mark"] is None and affected["status"] == "MISSING"
    assert affected["price_status"] == ("MISSING" if row_present else None)
    assert {"session_id": "2024-01-04", "code": "MISSING_FLAT_MARK"} in report["diagnostics"]
    assert report["coverage"] == {"expected_sessions": 6, "present_bars": 6 if row_present else 5,
                                  "observed_bars": 4, "settlement_only_bars": 1,
                                  "missing_price_sessions": 1, "status": "INCOMPLETE"}
    assert updated.model_dump(mode="json") == Dataset.model_validate(raw).model_dump(mode="json")


def test_f3_base_settlement_is_covered_without_inventing_observation(data, config):
    report = calculate(data, config)
    assert report["coverage"] == {"expected_sessions": 6, "present_bars": 6,
                                  "observed_bars": 5, "settlement_only_bars": 1,
                                  "missing_price_sessions": 0, "status": "COMPLETE"}
    assert report["nav"][-1]["status"] == "SETTLED"
    assert report["nav"][-1]["price_status"] == "SETTLEMENT_ONLY"
    assert report["nav"][-1]["mark"] is None


def test_f3_missing_status_nulls_and_original_input_survive_publication(tmp_path, data, config):
    raw = data.model_dump(mode="json")
    raw["bars"][2].update(open=None, high=None, low=None, close=None,
                          price_status="MISSING", tradable=False)
    # Keep the actual original representation separately from normalized data.
    original = json.dumps(raw, indent=2) + "\n"
    updated, bound = rebind(raw, config)
    bound = bound.model_copy(update={"strategy_version": "cash-flat-v1", "orders": []})
    report = calculate(updated, bound)
    store = ArtifactStore(tmp_path)
    inputs = {"dataset": updated.model_dump(mode="json"), "config": bound.model_dump(mode="json"),
              "original_dataset_utf8": original, "source_sha256": hashlib.sha256(original.encode()).hexdigest()}
    ref = store.publish(uuid.uuid4(), uuid.uuid4(), report, inputs, {"scope": "local-regression"})
    assert store.report(ref) == report
    stored_inputs = json.loads((store.directory(ref)/"inputs.json").read_bytes())
    assert stored_inputs == inputs
    row = pq.read_table(store.directory(ref)/"nav.parquet").to_pylist()[2]
    assert row["mark"] is None and row["price_status"] == "MISSING" and row["status"] == "MISSING"
