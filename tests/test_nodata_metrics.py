"""Frozen N08: an empty tape provides no numeric metric evidence."""
from decimal import Decimal

import pytest

from polar.engine import calculate
from polar.metrics import metrics
from polar.models import Dataset


@pytest.mark.parametrize("strategy", ["accounting-tape-v1", "cash-flat-v1"])
def test_empty_report_has_null_metrics_and_no_invented_gross(data, config, strategy):
    raw = data.model_dump(mode="json")
    raw.update(sessions=[], bars=[], actions=[], features=[])
    empty = Dataset.model_validate(raw)
    bound = config.model_copy(update={"dataset_id": empty.dataset_id,
                                     "orders": [], "strategy_version": strategy})
    report = calculate(empty, bound)
    assert report["status"] == "NO_DATA" and report["financial_verdict"] == "NOT_RUN"
    assert report["nav"] == [] and report["fills"] == [] and report["orders"] == []
    assert "gross_counterfactual" not in report  # No gross observation/final NAV invented.
    for name, metric in report["metrics"].items():
        assert metric["value"] is None, name
        assert metric["status"] == ("NOT_RUN" if name in {
            "beta", "factor_attribution", "confidence_interval", "alpha"
        } else "INSUFFICIENT_EVIDENCE"), name


def test_observed_cash_zero_accounting_retained_in_net_and_gross(data, config):
    report = calculate(data, config.model_copy(update={"strategy_version": "cash-flat-v1", "orders": []}))
    assert report["status"] == "COMPLETED"
    for result in [report["metrics"], report["gross_counterfactual"]["metrics"]]:
        for name in ["turnover", "fees", "dividends", "settlement"]:
            assert result[name]["value"] == "0" and result[name]["status"] == "OK"
        assert Decimal(result["volatility_252"]["value"]) == 0
        assert result["sharpe_252"]["value"] is None
    assert report["gross_counterfactual"]["final_nav"] == "1000"


def navs(values):
    return [{"at": f"2024-01-0{index+2}T21:00:00+00:00", "nav": value,
             "shares": "0", "mark": None} for index, value in enumerate(values)]


@pytest.mark.parametrize("values", [["1000"], ["1000", "1100"], ["1000", "1100", "1210"]])
def test_small_sample_and_constant_excess_boundaries(values):
    result = metrics(navs(values), [], Decimal(1000), Decimal(0), Decimal(0), Decimal(0))
    assert result["sharpe_252"]["value"] is None
    assert result["sharpe_252"]["status"] == "INSUFFICIENT_EVIDENCE"
    if len(values) == 3:
        assert Decimal(result["volatility_252"]["value"]) == 0
    else:
        assert result["volatility_252"]["value"] is None
    assert result["fees"]["value"] == "0" and result["fees"]["status"] == "OK"


@pytest.mark.parametrize("invalid", ["0", "-1"])
def test_nonpositive_observation_stays_invalid(invalid):
    with pytest.raises(ValueError, match="NONPOSITIVE_NAV"):
        metrics(navs(["1000", invalid]), [], Decimal(1000), Decimal(0), Decimal(0), Decimal(0))
