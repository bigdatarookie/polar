import hashlib
from datetime import datetime,timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from polar.engine import calculate
from polar.models import Dataset,RunConfig
from polar.metrics import metrics
from polar.temporal import eligible_feature


def mutate(data,config,change):
    d = data.model_dump(mode="json")
    change(d)
    updated = Dataset.model_validate(d)
    return updated,config.model_copy(update={"dataset_id":updated.dataset_id})


def test_frozen_source_and_accounting(raw_fixture,data,config):
    assert hashlib.sha256(raw_fixture).hexdigest() == "a6dd88480836e262c565f1ba4dfd5a056e7bbfd1688787dd2a343a82bf0bba14"
    report = calculate(data,config)
    assert report["status"] == "COMPLETED"
    assert [n["nav"] for n in report["nav"]] == ["1000","1039","1031","1032","1026","1014"]
    assert [n["cash"] for n in report["nav"]] == ["1000","599","599","714","714","1014"]
    assert [n["shares"] for n in report["nav"]] == ["0","4","8","6","6","0"]
    assert [f["fill_at"] for f in report["fills"]] == ["2024-01-03T14:30:00+00:00","2024-01-05T14:30:00+00:00"]
    assert report["fills"][0]["receipt_at"] == "2024-01-03T14:30:02+00:00"
    assert report["metrics"]["fees"]["value"] == "2"
    assert report["metrics"]["dividends"]["value"] == "8"
    assert report["gross_counterfactual"]["final_nav"] == "1016"
    assert report["nav"][0]["return"] is None
    assert abs(Decimal(report["metrics"]["sharpe_252"]["value"])-Decimal("2.2676794117917574")) < Decimal("1e-10")
    assert calculate(data,config) == report


def test_cash_baseline_and_metric_nulls(data,config):
    c = config.model_copy(update={"strategy_version":"cash-flat-v1","orders":[]})
    report = calculate(data,c)
    assert [n["nav"] for n in report["nav"]] == ["1000"]*6
    assert report["metrics"]["sharpe_252"]["value"] is None
    assert Decimal(report["metrics"]["volatility_252"]["value"]) == 0
    assert report["metrics"]["alpha"]["status"] == "NOT_RUN"


def test_missing_held_mark_invalid(data,config):
    def change(d):
        d["bars"][2].update(close=None,price_status="MISSING",tradable=False)
    d,c = mutate(data,config,change)
    r = calculate(d,c)
    assert r["status"] == "INVALID" and r["diagnostic"] == "MISSING_HELD_MARK"
    assert r["metrics"]["performance"]["value"] is None


def test_unknown_settlement_invalid(data,config):
    d,c = mutate(data,config,lambda d:d["actions"].pop())
    assert calculate(d,c)["status"] == "INVALID"


def test_temporal_revision_and_future_rejection(data,config):
    selected,excluded = eligible_feature(data,"marker",datetime(2024,1,3,21,0,2,tzinfo=timezone.utc))
    assert selected.source_revision == "r1" and excluded[0]["source_revision"] == "r2"
    d = config.model_dump(mode="json")
    d["orders"][0]["features"] = [{"feature_id":"marker","source_revision":"r2"}]
    assert calculate(data,RunConfig.model_validate(d))["status"] == "INVALID"
    d["orders"][0]["features"][0]["source_revision"] = "r1"
    assert calculate(data,RunConfig.model_validate(d))["status"] == "COMPLETED"


def test_late_ingestion_excluded(data):
    raw = data.model_dump(mode="json")
    raw["features"][0]["ingested_at"] = "2024-01-05T21:01:01Z"
    selected,_ = eligible_feature(Dataset.model_validate(raw),"marker",datetime(2024,1,3,21,0,2,tzinfo=timezone.utc))
    assert selected is None


def test_invalid_shape_unknown_action_and_adjusted_prices(data):
    for patch in [lambda d:d.update(price_basis="adjusted"),lambda d:d["actions"][0].update(kind="merger"),
                  lambda d:d["bars"].append(d["bars"][0]),lambda d:d["bars"][0].update(open=100.0)]:
        raw = data.model_dump(mode="json")
        patch(raw)
        with pytest.raises(ValidationError): Dataset.model_validate(raw)


def test_no_data_and_small_metric_samples(data,config):
    d,c = mutate(data,config,lambda d:d.update(sessions=[],bars=[],actions=[],features=[]))
    c = c.model_copy(update={"orders":[]})
    r = calculate(d,c)
    assert r["status"] == "NO_DATA"
    assert r["metrics"]["total_return"]["value"] is None
    base = [{"at":"2024-01-02T21:00:00+00:00","nav":"1000","shares":"0","mark":None},
            {"at":"2024-01-03T21:00:00+00:00","nav":"1010","shares":"0","mark":None}]
    m = metrics(base,[],Decimal(1000),Decimal(0),Decimal(0),Decimal(0))
    assert m["sharpe_252"]["value"] is None and m["volatility_252"]["value"] is None
    base[-1]["nav"] = "0"
    with pytest.raises(ValueError,match="NONPOSITIVE_NAV"):
        metrics(base,[],Decimal(1000),Decimal(0),Decimal(0),Decimal(0))


def test_rejected_order_preserves_cash(data,config):
    d = config.model_dump(mode="json")
    d["orders"] = [{"decision_session_id":"2024-01-02","quantity":"10"}]
    r = calculate(data,RunConfig.model_validate(d))
    assert r["final_cash"] == "1000" and not r["fills"]
    assert r["orders"][0]["status"] == "REJECTED"
    assert r["gross_counterfactual"]["final_nav"] == "1000"


def test_delayed_open_and_split_adjusts_pending_quantity(data,config):
    def change(d):
        d["bars"][1].update(open=None,tradable=False,price_status="MISSING")
    d,c = mutate(data,config,change)
    c = c.model_copy(update={"orders":[c.orders[0]]})
    r = calculate(d,c)
    assert r["status"] == "COMPLETED"
    assert r["fills"][0]["fill_at"] == "2024-01-04T14:30:00+00:00"
    assert r["fills"][0]["quantity"] == "8"  # split transforms pending shares
    assert r["final_cash"] == "967"
    assert r["diagnostics"][0]["code"] == "NO_ELIGIBLE_OPEN_ORDER_CARRIED"


def test_fractional_rejection_and_explicit_unfilled_order(data,config):
    raw = config.model_dump(mode="json")
    raw["orders"] = [{"decision_session_id":"2024-01-02","quantity":"0.5"}]
    r = calculate(data,RunConfig.model_validate(raw))
    assert not r["fills"] and r["orders"][0]["status"] == "REJECTED"
    def change(d):
        d["sessions"] = d["sessions"][:1]
        d["bars"] = d["bars"][:1]
        d["actions"] = []
        d["features"] = []
    d,c = mutate(data,config,change)
    c = c.model_copy(update={"orders":[c.orders[0]]})
    r = calculate(d,c)
    assert not r["fills"] and r["orders"][0]["status"] == "UNFILLED"
