"""Public invented controls supplied by Validator; no retained input or producer."""
import ast
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from polar import saved_verifier as checker
from polar import saved_verifier_math as arithmetic

FIXTURES = Path(__file__).parent / "fixtures"
CONTROLS = json.loads((FIXTURES / "saved_verifier_known_answers.json").read_text())
spec = importlib.util.spec_from_file_location("independent_reference", FIXTURES / "saved_verifier_reference_arithmetic.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


def pack(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def token(value):
    if value is None:
        return None
    with localcontext(arithmetic.CONTEXT):
        number = Decimal(value.numerator) / Decimal(value.denominator) if isinstance(value, Fraction) else Decimal(value)
        return reference.canonical(number)


def value(number):
    return {"value": token(number), "status": "OK" if number is not None else "UNAVAILABLE",
            "reason": None if number is not None else "ZERO_VARIANCE"}


def literal_metrics(rows, fills):
    """Independent contribution oracle and explicit finite cost/position formulas."""
    points = [x["nav_cents"] for x in rows]
    calc = reference.metrics(points, rows[-1]["nominal_ns"] - rows[0]["nominal_ns"])
    peak, dd = points[0], Fraction(0)
    for point in points:
        peak = max(peak, point)
        dd = max(dd, 1 - Fraction(point, peak))
    fee = sum(x["fee_cents"] for x in fills)
    gross = sum((Fraction(x["exact_notional_micro"], 10**6) for x in fills), Fraction(0))
    metric = {"terminal_nav_usd": Fraction(points[-1], 100), "net_total_return": Fraction(points[-1], points[0]) - 1,
        "net_cagr_act36525": calc["cagr"], "daily_mean_return": calc["mean_exact"],
        "daily_sample_variance": calc["variance_exact"], "annual_vol_252": calc["volatility"],
        "sharpe_252_rf0": calc["sharpe"], "max_drawdown": dd, "flat_fee_usd": Fraction(100 * len(fills), 100),
        "bps_cost_usd": Fraction(fee - 100 * len(fills), 100), "total_cost_usd": Fraction(fee, 100),
        "gross_exact_notional_usd": gross, "gross_settled_notional_usd": Fraction(sum(x["settled_cents"] for x in fills), 100),
        "gross_notional_over_initial": gross / Fraction(points[0], 100), "positive_fill_count": Fraction(len(fills)),
        "mean_close_exposure": sum((Fraction(r["exposure_cents"], r["nav_cents"]) for r in rows[1:]), Fraction(0)) / (len(rows) - 1),
        "invested_session_fraction": Fraction(sum(any(r["positions"].values()) for r in rows[1:]), len(rows) - 1),
        "max_close_concentration": max(Fraction(p, r["nav_cents"]) for r in rows for p in r["position_cents"].values())}
    return {k: value(v) for k, v in metric.items()}, [
        {"numerator": str(r.numerator), "denominator": str(r.denominator), "decimal": token(r)} for r in calc["returns_exact"]]


def toy_subject(mutation=None):
    control = deepcopy(CONTROLS["complete_ledger"])
    symbols, days = control["symbols"], list(control["prices_micro"])
    grids = [{"date": day, "nominal_ns": reference.utc_ns(stamp), "sample_ns": reference.utc_ns(stamp) + 1000,
              "initial": i == 0, "terminal": i == 2} for i, (day, stamp) in enumerate(zip(days, control["grid"]))]
    decisions = []
    for i, row in enumerate(control["intents"]):
        decisions.append({"day": days[i + 1], "formation": row["formation"], "known_ns": reference.utc_ns(row["known"]),
            "decision_ns": reference.utc_ns(row["decision"]), "open_ns": reference.utc_ns(row["execution"]),
            "instructions": {"TOY": {"kind": "TARGET", "weights": {s: [4, 5] if s == "AAPL" else [0, 1] for s in symbols}}
                             if i == 0 else {"kind": "EXIT"}, "CASH": {"kind": "HOLD"}}})
    nav = [{**row, "date": days[i], "nominal_ns": grids[i]["nominal_ns"], "sample_ns": grids[i]["sample_ns"],
            "exposure_cents": sum(row["position_cents"].values())} for i, row in enumerate(control["nav"])]
    fills = []
    for row in control["fills"]:
        stamp = grids[days.index(row["day"])]["nominal_ns"] + (200 if row["side"] == "BUY" else 100)
        fills.append({k: v for k, v in row.items() if k != "day"} | {
            "id": f"TOY/{row['day']}/{row['side']}/AAPL", "at_ns": stamp,
            "exact_notional_micro": row["q"] * row["price_micro"], "native_cash_after_cents": row["cash_after_cents"]})
    orders = [{"id": f["id"], "symbol": f["symbol"], "side": f["side"], "at_ns": f["at_ns"],
               "intended_quantity": 8 if i == 0 else 7, "routed_quantity": 7,
               "reason": "FEE_AWARE_BUDGET_CAP" if i == 0 else None} for i, f in enumerate(fills)]
    intents = [{k: d[k] for k in ("day", "formation", "known_ns", "decision_ns")} | {
        "targets": {s: 8 if i == 0 and s == "AAPL" else 0 for s in symbols}} for i, d in enumerate(decisions)]
    cash_nav = [{**row, "cash_cents": 1000, "exposure_cents": 0, "nav_cents": 1000,
                 "positions": dict.fromkeys(symbols, 0), "position_cents": dict.fromkeys(symbols, 0),
                 "flat_cents": 0, "bps_cents": 0} for row in nav]
    simulation = {"legs": [{"id": "TOY", "nav": nav, "fills": fills, "orders": orders, "intents": intents},
                           {"id": "CASH", "nav": cash_nav, "fills": [], "orders": [],
                            "intents": [{**i, "targets": dict.fromkeys(symbols, 0)} for i in intents]}]}
    plan = {"profile": {"kind": "REFERENCE_TARGETS"}, "symbols": symbols, "grid": grids, "decisions": decisions,
            "prices": {d: {s: {"close_micro": p} for s, p in rows.items()} for d, rows in control["prices_micro"].items()}}
    saved = {"plan": plan, "simulation": simulation}
    if mutation:
        mutation(saved)
    evaluated = []
    for leg in simulation["legs"]:
        m, returns = literal_metrics(leg["nav"], leg["fills"])
        evaluated.append({"id": leg["id"], "metrics": m, "returns": returns})
    difference = Decimal(evaluated[0]["metrics"]["net_total_return"]["value"]) - Decimal(evaluated[1]["metrics"]["net_total_return"]["value"])
    comparison = {"metric_id": "net_total_return", "left_id": "TOY", "right_id": "CASH", "result": value(difference)}
    saved["evaluation"] = {"legs": evaluated, "comparisons": [comparison], "criteria": []}
    return saved


def write_packet(root, mutation=None):
    saved = toy_subject(mutation)
    symbols = CONTROLS["complete_ledger"]["symbols"]
    days = list(CONTROLS["complete_ledger"]["prices_micro"])
    profile = {"schema": "polar.scheduled-reference-profile/1", "protocol_id": "PUBLIC_TOY",
               "symbols": symbols, "legs": [{"id": "TOY"}, {"id": "CASH"}], "criteria": [],
               "primary_strategy": "TOY", "primary_benchmark": "CASH"}
    calendar = {"source_schedule_rows": [{"date": d, "reference_close_utc": stamp} for d, stamp in
                                          zip(days, CONTROLS["complete_ledger"]["grid"])],
                "phases": {"FINAL": {"nav_dates": days, "nav_points": 3, "return_count": 2, "decision_count": 1}}}
    bindings = {"code_revision": "a" * 40, "runtime_image_id": "sha256:" + "b" * 64,
                "protocol_ref": {"sha256": "c" * 64}, "input_ref": {"sha256": "d" * 64},
                "candidate_id": "PUBLIC_TOY", "experiment_id": "EXPERIMENT_1"}
    contents = {"profile.json": profile, "calendar.json": calendar, "bindings.json": bindings,
                "phases.json": {"FINAL": saved}, "diagnostics.json": {}}
    raw_members = {n: pack(v) for n, v in contents.items()}
    def pin(name, raw):
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    manifest = {"schema": "polar.scheduled-reference-semantic-manifest/1", "files": {
        n: {k: v for k, v in pin(n, raw).items() if k != "path"} for n, raw in raw_members.items()}}
    manifest_raw = pack(manifest)
    semantic_id = "scheduled-reference-experiment-" + hashlib.sha256(manifest_raw).hexdigest()
    expected = {"code_revision": bindings["code_revision"], "runtime_image_id": bindings["runtime_image_id"],
                "protocol_sha256": "c" * 64, "input_sha256": "d" * 64,
                "candidate_id": "PUBLIC_TOY", "experiment_id": "EXPERIMENT_1",
                "profile_sha256": manifest["files"]["profile.json"]["sha256"],
                "calendar_sha256": manifest["files"]["calendar.json"]["sha256"]}
    public = {"schema_version": "polar.research-result/1", "question": {"id": "PUBLIC_TOY.FINAL"},
              "bindings": {"code_revision": "a" * 40, "runtime_id": bindings["runtime_image_id"], "protocol_sha256": "c" * 64,
                           "data_sha256": "d" * 64, "candidate_id": "PUBLIC_TOY", "experiment_id": "EXPERIMENT_1"},
              "basis": {"wealth_basis": "SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT"},
              "primary_benchmark_id": "CASH",
              "grid": CONTROLS["complete_ledger"]["grid"], "series": [], "metrics": [],
              "provenance": [{"role": "semantic_manifest", "id": semantic_id, "sha256": semantic_id[-64:]}],
              "criteria": [], "comparisons": [{**saved["evaluation"]["comparisons"][0], "metric_id": "adjusted_reference_return_after_costs"}]}
    for leg, ev in zip(saved["simulation"]["legs"], saved["evaluation"]["legs"]):
        ledger = [{"cash": token(Fraction(n["cash_cents"], 100)), "exposure": token(Fraction(n["exposure_cents"], 100)),
                   "cumulative_flat_fees": token(Fraction(n["flat_cents"], 100)), "cumulative_bps_fees": token(Fraction(n["bps_cents"], 100)),
                   "positions": n["positions"], "net_return": value(Fraction(ev["returns"][i - 1]["decimal"])) if i else
                   {"value": None, "status": "NOT_APPLICABLE", "reason": "INITIAL_POINT"}} for i, n in enumerate(leg["nav"])]
        public["series"].append({"id": leg["id"], "role": "STRATEGY" if leg["id"] == "TOY" else "BENCHMARK",
                                 "values": [value(Fraction(n["nav_cents"], 100)) for n in leg["nav"]], "ledger": ledger})
    for key in saved["evaluation"]["legs"][0]["metrics"]:
        public["metrics"].append({"id": checker.ALIASES.get(key, key), "values": {v["id"]: v["metrics"][key] for v in saved["evaluation"]["legs"]}})
    written = {"semantic/" + n: raw for n, raw in raw_members.items()}
    written["semantic/manifest.json"] = manifest_raw
    written["public-FINAL/result.json"] = pack(public)
    for name, raw in written.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    graph = pack({"members": {n: {k: v for k, v in pin(n, raw).items() if k != "path"} for n, raw in written.items()}})
    (root / "CONTENT-GRAPH.json").write_bytes(graph)
    return {"schema": "polar.saved-verifier-packet/1", "root": str(root), "profile": checker.PROFILE,
            "initial_capital_cents": 1000, "expected_bindings": expected, "semantic_id": semantic_id,
            "manifest": pin("semantic/manifest.json", manifest_raw), "graph": pin("CONTENT-GRAPH.json", graph),
            "publications": [{**pin("public-FINAL/result.json", written["public-FINAL/result.json"]),
                              "phase": "FINAL", "result_id": "research-" + hashlib.sha256(written["public-FINAL/result.json"]).hexdigest()}]}


def test_literal_controls():
    for row in CONTROLS["money_controls"]:
        assert arithmetic.round_micro_to_cents(row["q"] * row["price_micro"]) == row["settled_cents"]
        assert arithmetic.fee_cents(row["q"], row["price_micro"]) == row["fee_cents"]
    assert arithmetic.affordable(8, 1125000, 1000) == 7
    assert arithmetic.round_micro_to_cents(8 * 1125000) + arithmetic.fee_cents(8, 1125000) == 1001
    for row in CONTROLS["metric_controls"]:
        got = arithmetic.statistics(row["nav_cents"], row["elapsed_ns"])
        assert got["mean"] == Fraction(row["mean"])
        assert got["variance"] == Fraction(row["sample_variance"])
        assert arithmetic.decimal_token(got["sharpe"]) == row["sharpe"]
        assert arithmetic.decimal_token(got["cagr"]) == row["cagr"]


def test_exact_criterion_boundaries_are_not_display_rounding_or_ordinary_drawdown():
    scaled = {"kind": "DRAWDOWN_SCALED_LE", "factor": [4, 5]}
    benchmark = {"max_drawdown": Fraction(1, 10)}
    assert arithmetic.criterion(scaled, {"max_drawdown": Fraction(2, 25)}, benchmark, 1000)
    assert not arithmetic.criterion(scaled, {"max_drawdown": Fraction(2, 25) + Fraction(1, 10**30)}, benchmark, 1000)
    assert arithmetic.criterion({"kind": "TERMINAL_GE"}, {"terminal_nav_usd": Fraction(100001, 100)},
                                {"terminal_nav_usd": Fraction(1000)}, 100000)
    assert not arithmetic.criterion({"kind": "POSITIVE_GROWTH"}, {"terminal_nav_usd": Fraction(1000)}, None, 100000)
    sr = {"kind": "SR_DELTA_GE", "threshold": "0.10"}
    assert arithmetic.criterion(sr, {"sharpe_252_rf0": Decimal("0.2")}, {"sharpe_252_rf0": Decimal("0.1")}, 1000)
    assert not arithmetic.criterion(sr, {"sharpe_252_rf0": Decimal("0.1999999999999999999999")},
                                    {"sharpe_252_rf0": Decimal("0.1")}, 1000)
    assert arithmetic.criterion(sr, {"sharpe_252_rf0": None}, {"sharpe_252_rf0": Decimal("0.1")}, 1000) is None
    with pytest.raises(NotImplementedError):
        arithmetic.criterion({"kind": "GMV_CERTIFICATE"}, {}, {}, 1000)


def test_boolean_position_is_not_an_integer_position(tmp_path):
    def mutate(saved):
        saved["simulation"]["legs"][0]["nav"][0]["positions"]["AMZN"] = False
    report = checker.verify(write_packet(tmp_path, mutate))
    assert report["checks"]["shape"]["status"] == "FAIL"


def test_missing_saved_native_cash_is_unknown(tmp_path):
    def mutate(saved):
        for f in saved["simulation"]["legs"][0]["fills"]:
            del f["native_cash_after_cents"]
    report = checker.verify(write_packet(tmp_path, mutate))
    assert report["checks"]["native_cash"]["status"] == "UNKNOWN"
    assert report["covered_verdict"] == "UNKNOWN"


def test_complete_known_answer_is_covered_pass_with_explicit_unknowns(tmp_path):
    packet = write_packet(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    report = checker.verify(packet)
    assert report["covered_verdict"] == "PASS", report["checks"]
    assert report["overall_verdict"] == "UNKNOWN"
    assert all(v["status"] == "UNKNOWN" for v in report["unverified_properties"])
    assert report["financial_verdict"] == "NOT_ASSESSED"
    assert set(report["scientific_calls"].values()) == {0}
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("kind,group", [("fee", "costs"), ("nav", "ledger"), ("clock", "clocks"), ("terminal", "terminal_liquidation")])
def test_semantic_mutants_rehash_then_fail_applicable_check(tmp_path, kind, group):
    def mutate(saved):
        leg = saved["simulation"]["legs"][0]
        if kind == "fee":
            leg["fills"][0]["fee_cents"] += 1
        elif kind == "nav":
            leg["nav"][1]["nav_cents"] += 1
        elif kind == "clock":
            saved["plan"]["decisions"][0]["decision_ns"] = saved["plan"]["decisions"][0]["open_ns"]
            leg["intents"][0]["decision_ns"] = saved["plan"]["decisions"][0]["decision_ns"]
            saved["simulation"]["legs"][1]["intents"][0]["decision_ns"] = saved["plan"]["decisions"][0]["decision_ns"]
        else:
            leg["nav"][-1]["positions"]["AAPL"] = 1
            leg["nav"][-1]["position_cents"]["AAPL"] = 150
            leg["nav"][-1]["exposure_cents"] = 150
            leg["nav"][-1]["nav_cents"] += 150
    report = checker.verify(write_packet(tmp_path, mutate))
    assert report["checks"]["content_identity"]["status"] == "PASS"
    assert report["checks"][group]["status"] == "FAIL"
    assert report["covered_verdict"] == "FAIL"


def test_wrong_binding_and_raw_tamper_are_distinct(tmp_path):
    packet = write_packet(tmp_path)
    packet["expected_bindings"]["protocol_sha256"] = "e" * 64
    report = checker.verify(packet)
    assert report["checks"]["bindings"]["status"] == "FAIL"
    packet["expected_bindings"]["protocol_sha256"] = "c" * 64
    (tmp_path / "semantic/phases.json").write_bytes(b"{}")
    report = checker.verify(packet)
    assert report["checks"]["content_identity"]["status"] == "FAIL"


def test_unsupported_profile_and_cost_are_never_silent_pass(tmp_path):
    packet = write_packet(tmp_path)
    packet["profile"] = "gmv-bootstrap/1"
    assert checker.verify(packet)["covered_verdict"] == "UNKNOWN"
    def stress(saved):
        saved["plan"]["cost_profile"] = {"flat_cents": 200, "bps": 20}
    packet = write_packet(tmp_path, stress)
    report = checker.verify(packet)
    assert report["covered_verdict"] == "UNKNOWN"
    assert report["checks"]["profile"]["status"] == "UNKNOWN"


def test_nofollow_symlink_and_path_escape(tmp_path):
    packet = write_packet(tmp_path)
    source = tmp_path / "semantic/phases.json"
    raw = source.read_bytes()
    source.unlink()
    target = tmp_path / "alternate.json"
    target.write_bytes(raw)
    source.symlink_to(target)
    assert checker.verify(packet)["covered_verdict"] == "FAIL"
    packet["manifest"]["path"] = "../manifest.json"
    assert checker.verify(packet)["covered_verdict"] == "FAIL"


def test_cli_and_no_producer_imports(tmp_path):
    packet = write_packet(tmp_path)
    raw = pack(packet)
    path = tmp_path.parent / (tmp_path.name + "-packet.json")
    path.write_bytes(raw)
    p = subprocess.run([sys.executable, "-m", "polar.saved_verifier", "--packet", str(path),
                        "--packet-sha256", hashlib.sha256(raw).hexdigest()], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["covered_verdict"] == "PASS"
    for module in [checker, arithmetic]:
        tree = ast.parse(Path(module.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.module == "saved_verifier_math"
            if isinstance(node, ast.Import):
                assert not any(n.name.startswith(("polar", "numpy", "torch", "nautilus", "subprocess", "socket")) for n in node.names)
