"""Public invented controls for the new selected-profile runner, no retained data."""
from copy import deepcopy
from fractions import Fraction
from zoneinfo import ZoneInfo

import pytest

from polar.ci_research import (fee_cents, maximum_buy, convert_input, instant,
                               ResearchRunError, project, utc_text)
from polar.ci_research_evaluation import evaluate
from polar.ci_research_native import simulate


def test_fee_and_half_even_affordability_boundaries():
    assert fee_cents(0, 1125000) == 0
    assert fee_cents(1, 1125000) == 101
    assert maximum_buy(1, 1125000, 212) == 0
    assert maximum_buy(1, 1125000, 213) == 1  # 1.125->1.12 settled, fee1.01
    assert maximum_buy(100, 10000000000, 10000000, 2000000) == 1
    assert maximum_buy(100, 10000000000, 10000000) == 9


def test_reservation_experiment_registration_is_not_always_profile_id():
    from polar.ci_research_service import validate_reservation
    for profile, registration in [
        ("HYP001-CI3-12M1M-v1", "CI8H-A-MOM3-2017-2019-V1-EXPERIMENT-01"),
        ("HYP010-CI-AMZN-TOM-v1", "HYP010-CI-AMZN-TOM-v1"),
    ]:
        card = {"schema": "polar.native-hypothesis-reservation/1", "state": "RESERVED",
                "candidate_id": "invented-card", "experiment_registration_id": registration}
        cfg = {"profile_id": profile, "candidate_id": "invented-card"}
        validate_reservation(card, cfg)
        card["experiment_registration_id"] = "wrong-registration"
        with pytest.raises(ResearchRunError, match="CANDIDATE_RESERVATION_PIN"):
            validate_reservation(card, cfg)


def test_modeled_new_york_dst_is_not_fixed_utc_open():
    tz = ZoneInfo("America/New_York")
    assert utc_text(instant("2019-03-08", 9, 30, tz)) == "2019-03-08T14:30:00Z"
    assert utc_text(instant("2019-03-11", 9, 30, tz)) == "2019-03-11T13:30:00Z"


def invented_plan():
    tz = ZoneInfo("America/New_York")
    profile = {"kind": "B_TOM", "end": "2024-02-06", "legs":
               ["AMZN_TOM", "AMZN_INITIAL20_BH", "AMZN_INITIAL100_BH", "CASH"]}
    days = ["2024-01-30", "2024-01-31", "2024-02-06"]
    decisions = []
    for kind, previous, day in [("ENTER", days[0], days[1]), ("EXIT", days[1], days[2])]:
        k = instant(previous, 16, 0, tz)
        decisions.append({"kind": kind, "formation": previous, "day": day, "known_ns": k,
                          "decision_ns": k+10**9, "open_ns": instant(day, 9, 30, tz), "score_dates": []})
    return {"schema": "polar.ci-research-plan/1", "profile": profile, "symbols": ["AMZN"],
            "prices": {days[1]: {"AMZN": {"open_micro": 10000005000, "close_micro": 10000005000}},
                       days[2]: {"AMZN": {"open_micro": 10000015000, "close_micro": None}}},
            "decisions": decisions,
            "grid": [{"date": d, "nominal_ns": instant(d, 16, 0, tz),
                      "sample_ns": instant(d, 16, 0, tz)+100, "initial": i == 0, "terminal": i == 2}
                     for i,d in enumerate(days)]}


def test_native_cent_fee_calendar_account_and_cash_control():
    # Runs in the same official image as CI. No mock account or private control.
    simulation = simulate(invented_plan())
    legs = {r["id"]: r for r in simulation["legs"]}
    full = legs["AMZN_TOM"]
    assert [f["q"] for f in full["fills"]] == [9, 9]
    assert [f["settled_cents"] for f in full["fills"]] == [9000004, 9000014]
    assert [f["fee_cents"] for f in full["fills"]] == [9101, 9101]
    assert full["nav"][-1]["cash_cents"] == full["nav"][-1]["nav_cents"] == 9981808
    primary = legs["AMZN_INITIAL20_BH"]
    assert primary["intents"][0]["targets"] is None
    assert primary["intents"][0]["spending_budgets_cents"] == {"AMZN": 2000000}
    assert [f["q"] for f in primary["fills"]] == [1, 1]
    assert primary["nav"][-1]["nav_cents"] == 9997800
    assert legs["CASH"]["fills"] == []
    assert all(r["nav_cents"] == 10000000 for r in legs["CASH"]["nav"])
    assert all(not any(r["nav"][-1]["positions"].values()) for r in legs.values())
    result = evaluate(simulation, invented_plan()["profile"])
    cash = next(r for r in result["legs"] if r["id"] == "CASH")["metrics"]
    assert cash["annual_vol_252"]["value"] == "0"
    assert cash["sharpe_252_rf0"] == {"value": None, "status": "UNAVAILABLE", "reason": "ZERO_VARIANCE"}
    assert result["exposure_denominator"] == 2


def test_native_buyhold_does_not_exit_on_intermediate_tom_cycle():
    plan = invented_plan(); tz = ZoneInfo("America/New_York")
    # First February exit is intermediate; BH controls must keep their shares.
    plan["profile"]["end"] = "2024-03-06"
    plan["grid"][-1]["terminal"] = False
    plan["prices"]["2024-02-06"]["AMZN"]["close_micro"] = 10000005000
    for kind, previous, day in [("ENTER", "2024-02-06", "2024-02-29"), ("EXIT", "2024-02-29", "2024-03-06")]:
        k = instant(previous, 16, 0, tz)
        plan["decisions"].append({"kind": kind, "formation": previous, "day": day, "known_ns": k,
            "decision_ns": k+10**9, "open_ns": instant(day, 9, 30, tz), "score_dates": []})
        plan["prices"][day] = {"AMZN": {"open_micro": 10000005000, "close_micro": None if kind == "EXIT" else 10000005000}}
        plan["grid"].append({"date": day, "nominal_ns": instant(day, 16, 0, tz), "sample_ns": instant(day, 16, 0, tz)+100,
                             "initial": False, "terminal": kind == "EXIT"})
    result = simulate(plan)
    assert len(result["legs"][0]["fills"]) == 4
    for control in result["legs"][1:3]:
        assert len(control["fills"]) == 2
        assert control["nav"][2]["positions"]["AMZN"] > 0


def test_native_monthly_no_positive_filter_and_no_forced_roundtrip():
    tz = ZoneInfo("America/New_York"); plan = invented_plan()
    profile = {"kind": "A_MOMENTUM", "end": "2024-03-06", "legs": ["MOM12_1_TOP1_MONTHLY", "EW3_INITIAL_BUYHOLD"]}
    symbols = ["AAPL", "AMZN", "TSLA"]
    days = ["2024-01-30", "2024-01-31", "2024-02-29", "2024-03-06"]
    prices = {d: {s: {"open_micro": 10000005000, "close_micro": None if d == days[-1] else 10000005000} for s in symbols} for d in days}
    for d,price in [("2022-01-01", 20000000000), ("2023-12-01", 10000000000)]:
        prices[d] = {s: {"open_micro": price, "close_micro": price} for s in symbols}
    decisions = []
    for kind, previous, day in [("ALLOCATE", days[0], days[1]), ("ALLOCATE", days[1], days[2]), ("EXIT", days[2], days[3])]:
        k = instant(previous, 16, 0, tz)
        decisions.append({"kind": kind, "formation": previous, "day": day, "known_ns": k,
            "decision_ns": k+10**9, "open_ns": instant(day, 9, 30, tz), "score_dates": ["2022-01-01", "2023-12-01"]})
    plan = {"profile": profile, "symbols": symbols, "prices": prices, "decisions": decisions,
            "grid": [{"date": d, "nominal_ns": instant(d, 16, 0, tz), "sample_ns": instant(d, 16, 0, tz)+100,
                      "initial": i == 0, "terminal": i == len(days)-1} for i,d in enumerate(days)]}
    result = simulate(plan)
    strategy, benchmark = result["legs"]
    assert strategy["intents"][0]["signal"]["winner"] == "AAPL"  # exact negative ties -> literal alias
    assert [(f["symbol"], f["side"]) for f in strategy["fills"]] == [("AAPL", "BUY"), ("AAPL", "SELL")]
    assert len(benchmark["fills"]) == 6  # initial3 buys and final3 sells, no monthly rebalance
    assert [f["symbol"] for f in benchmark["fills"][:3]] == symbols


def test_invented_service_publication_and_stored_only_recompute(tmp_path, monkeypatch):
    from polar.ci_research_service import ResearchService
    from polar.research_results import ResearchResults
    from polar.gym_contract import sha
    engine = ResearchService(tmp_path, 64*1024**3)
    plan = invented_plan()
    config = {"profile_id": "HYP010-CI-AMZN-TOM-v1", "namespace": "INVENTED", "code_revision": "a"*40,
              "runtime_image_id": "sha256:"+"b"*64, "candidate_id": "invented-candidate", "experiment_id": "invented-experiment"}
    pins = {k: str(i)*64 for i,k in enumerate(["protocol_sha256", "input_sha256", "timezone_sha256", "source_sha256", "calendar_sha256"], 1)}
    # Component seam supplies a small explicitly invented prepared plan; it is
    # not evidence that retained protocol/input/native admission was exercised.
    monkeypatch.setattr(engine, "prepare", lambda _: (plan, pins))
    finish = engine.run(config)
    assert finish["status"] == "SUCCESS"
    public = ResearchResults(tmp_path, 64*1024**3).read(finish["result_id"])
    assert public["record"]["evidence_level"] == "INVENTED_CONTROL"
    assert public["record"]["series"][1]["values"][-1]["value"] == "99978.00"
    assert public["assessment"]["financial"] == "NOT_REVIEWED"
    before = {str(p): sha(p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    import polar.ci_research_service as module
    monkeypatch.setattr(module, "bounded_native", lambda _: (_ for _ in ()).throw(AssertionError("must not run")))
    monkeypatch.setattr(engine, "prepare", lambda _: (_ for _ in ()).throw(AssertionError("must not load source")))
    assert engine.recompute(finish["semantic_id"])["native_calls"] == 0
    assert {str(p): sha(p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()} == before


def test_decimal50_is_significant_not_fractional_places():
    token = project(Fraction(1, 3*10**30))
    assert len(token.split(".")[1]) > 50
    from polar.research_results import Value
    assert Value(value=token, status="OK", reason=None).value == token


def test_full_741_interval_exact_moments_do_not_serialize_huge_integers():
    # Deliberately non-economic NAV arithmetic tape. Pairwise varying integer
    # denominators grow far beyond small-control examples; no private prices,
    # source outcomes or native scenarios are used for this math-domain check.
    profile = invented_plan()["profile"]
    tapes = []
    start = instant("2019-01-30", 16, 0, ZoneInfo("UTC"))
    for leg_index, leg in enumerate(profile["legs"]):
        nav = []
        for i in range(742):
            v = 10000000 if i == 0 or leg == "CASH" else 10000000 + ((i*7919+leg_index*101) % 100003)
            nav.append({"nav_cents": v, "nominal_ns": start+i*86400*10**9,
                        "exposure_cents": 0, "position_cents": {"AMZN": 0}, "positions": {"AMZN": 0},
                        "flat_cents": 0, "bps_cents": 0})
        tapes.append({"id": leg, "nav": nav, "fills": []})
    result = evaluate({"legs": tapes}, profile)
    assert result["exposure_denominator"] == 741
    assert len(result["legs"][0]["returns"]) == 741
    for leg in result["legs"]:
        for item in leg["metrics"].values():
            assert item["value"] is None or isinstance(item["value"], str) and len(item["value"]) < 200


def test_file_only_research_cli_needs_no_database_secret(tmp_path, monkeypatch, capsys):
    import json
    from polar.cli import main
    from test_research_results import invented_result
    monkeypatch.setenv("POLAR_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("POLAR_DB_PASSWORD_FILE", str(tmp_path/"does-not-exist"))
    monkeypatch.delenv("POLAR_DATABASE_URL", raising=False)
    source = tmp_path/"public-input.json"; source.write_text(json.dumps(invented_result()))
    main(["research-publish", str(source)])
    assert json.loads(capsys.readouterr().out)["result_id"].startswith("research-")


def tiny_source():
    days = ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-02", "2024-02-05", "2024-02-06"]
    return {"schema": "polar.ci-research-input/1", "source_revision": "invented", "source_sha256": "1"*64,
            "calendar_sha256": "2"*64, "dates": days, "symbols": ["AMZN"], "limitations": ["INVENTED"],
            "rows": [{"symbol": "AMZN", "date": d, "open": "10.005000", "close": None if i == len(days)-1 else "10.000001",
                      "source_ref": {"object_sha256": "3"*64, "row": i}} for i,d in enumerate(days)]}


def test_lossless_conversion_calendar_and_terminal_open_only():
    data = tiny_source()
    profile = {"kind": "B_TOM", "symbols": ["AMZN"], "input_start": data["dates"][0],
               "initial": "2024-01-29", "end": data["dates"][-1]}
    plan = convert_input(data, profile, ZoneInfo("America/New_York"))
    assert plan["prices"]["2024-01-31"]["AMZN"]["close_micro"] == 10000001
    assert plan["prices"]["2024-02-06"]["AMZN"]["close_micro"] is None
    assert [d["day"] for d in plan["decisions"]] == ["2024-01-31", "2024-02-06"]
    assert all(d["known_ns"] < d["decision_ns"] < d["open_ns"] for d in plan["decisions"])
    for mutation in [lambda d: d["rows"].pop(), lambda d: d["rows"].reverse(),
                     lambda d: d["rows"][-1].update(close="10")]:
        changed = deepcopy(data); mutation(changed)
        with pytest.raises(ResearchRunError):
            convert_input(changed, profile, ZoneInfo("America/New_York"))
