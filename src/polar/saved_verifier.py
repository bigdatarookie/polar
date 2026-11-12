"""Versioned independent checks over saved scheduled-reference outputs only.

No producer/evaluator/model/native imports; no calls to scientific entrypoints.
The first profile extracts Validator's v037 A/A2 saved-ledger audit. Signals,
source fitness and financial interpretation remain explicitly unverified.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from zoneinfo import ZoneInfo

from .saved_verifier_math import (CONTEXT, affordable, criterion, decimal_token, fee_cents,
                                  metrics, round_micro_to_cents, utc_ns)

PROFILE = "scheduled-reference-flat100-bps10/1"
MAX_MEMBER = 32 * 1024**2  # Existing saved-semantic producer member envelope.
MEMBERS = {"profile.json", "calendar.json", "phases.json", "diagnostics.json", "bindings.json"}
HASH = re.compile(r"[a-f0-9]{64}")
ALIASES = {"net_total_return": "adjusted_reference_return_after_costs",
           "net_cagr_act36525": "adjusted_reference_cagr_after_costs"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))


class SavedFiles:
    """Read regular bounded files through retained no-follow directory descriptors."""
    def __init__(self, root):
        self.root = Path(root).absolute()
        if any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise ValueError("SYMLINK_ROOT")

    def read(self, name, maximum=MAX_MEMBER):
        if (type(name) is not str or not name or "\\" in name or
                any(not re.fullmatch(r"[A-Za-z0-9_.-]+", s) or s in (".", "..") for s in name.split("/"))):
            raise ValueError("UNSAFE_MEMBER_NAME")
        descriptors = []
        try:
            descriptors.append(os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
            for part in name.split("/")[:-1]:
                descriptors.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                           dir_fd=descriptors[-1]))
            fd = os.open(name.split("/")[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=descriptors[-1])
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                    raise ValueError("MEMBER_SIZE_OR_TYPE")
                raw = stream.read(maximum + 1)
            if len(raw) > maximum:
                raise ValueError("MEMBER_SIZE")
            return raw
        finally:
            for fd in reversed(descriptors):
                os.close(fd)


class Checks:
    def __init__(self):
        self.groups = {}

    def check(self, group, condition, address, reason="SAVED_VALUE_MISMATCH"):
        item = self.groups.setdefault(group, {"status": "PASS", "checked": 0, "failures": 0, "details": []})
        item["checked"] += 1
        if not condition:
            item["status"] = "FAIL"
            item["failures"] += 1
            if len(item["details"]) < 20:
                item["details"].append({"address": address, "reason": reason})

    def unknown(self, group, reason):
        item = self.groups.setdefault(group, {"status": "UNKNOWN", "checked": 0, "failures": 0, "details": []})
        if item["status"] != "FAIL":
            item["status"] = "UNKNOWN"
        if len(item["details"]) < 20:
            item["details"].append({"reason": reason})

    def require(self, group, condition, address):
        self.check(group, condition, address)
        if not condition:
            raise ValueError("REQUIRED_BINDING_OR_SHAPE")

    def pinned(self, files, ref, group="content_identity"):
        self.require(group, type(ref) is dict and type(ref.get("bytes")) is int and
                     ref["bytes"] >= 0 and type(ref.get("sha256")) is str and
                     HASH.fullmatch(ref["sha256"]) is not None, "member.pin")
        raw = files.read(ref["path"])
        self.require(group, len(raw) == ref["bytes"] and digest(raw) == ref["sha256"], ref["path"])
        return raw


def record(value):
    return {"value": decimal_token(value), "status": "OK" if value is not None else "UNAVAILABLE",
            "reason": None if value is not None else "ZERO_VARIANCE"}


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def midnight_ns(day):
    dt = (datetime.fromisoformat(day) + timedelta(days=1)).replace(tzinfo=ZoneInfo("America/New_York"))
    return utc_ns(dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def calendar_expectations(contract, checks, address):
    """Read the two existing calendar representations without changing the subject."""
    checks.require("clocks", type(contract) is dict and type(contract.get("nav_dates")) is list and
                   len(contract["nav_dates"]) >= 3, address + ".nav_dates")
    days = contract["nav_dates"]
    checks.require("clocks", all(type(d) is str for d in days) and days == sorted(set(days)), address + ".nav_dates.order")
    monthly = ("nav_points", "return_count", "decision_count")
    if any(k in contract for k in monthly):
        for key in monthly:
            checks.require("clocks", key in contract and integer(contract[key]), address + "." + key)
        return {"dates": days, "nav_points": contract["nav_points"], "return_count": contract["return_count"],
                "decision_count": contract["decision_count"] + 1, "decision_pairs": None}
    if "daily_gate_decisions" in contract:
        rows = contract["daily_gate_decisions"]
        checks.require("clocks", type(rows) is list and len(rows) == len(days) - 2, address + ".daily_gate_decisions")
        for key in ("initial", "terminal", "terminal_decision_reference", "terminal_execution"):
            checks.require("clocks", key in contract, address + "." + key)
        checks.require("clocks", contract["initial"] == days[0] and contract["terminal"] == days[-1] and
                       contract["terminal_decision_reference"] == days[-2] and
                       contract["terminal_execution"] == days[-1], address + ".terminal_bounds")
        pairs = []
        for i, row in enumerate(rows):
            checks.require("clocks", type(row) is dict and row.get("formation") == days[i] and
                           row.get("execution_day") == days[i + 1], address + f".daily_gate_decisions[{i}]")
            pairs.append((row["formation"], row["execution_day"]))
        pairs.append((contract["terminal_decision_reference"], contract["terminal_execution"]))
        return {"dates": days, "nav_points": len(days), "return_count": len(days) - 1,
                "decision_count": len(rows) + 1, "decision_pairs": pairs}
    checks.unknown("calendar_shape", "UNSUPPORTED_CALENDAR_DECISION_CENSUS")
    return None


def verify_phase(name, saved, public, profile, calendar, checks, initial_cents):
    """Fold recorded fills and validate saved states; do not rerun the policy."""
    at = "phases." + name
    plan, simulation, evaluation = saved["plan"], saved["simulation"], saved["evaluation"]
    symbols = profile["symbols"]
    checks.require("profile", len(symbols) == len(set(symbols)) and symbols == sorted(symbols) and
                   plan["symbols"] == symbols and plan["profile"]["kind"] == "REFERENCE_TARGETS", at + ".symbols")
    if plan.get("cost_profile", {"flat_cents": 100, "bps": 10}) != {"flat_cents": 100, "bps": 10}:
        checks.unknown("profile", "COST_PROFILE_OUTSIDE_FLAT100_BPS10")
        return
    schedule = {r["date"]: r for r in calendar["source_schedule_rows"]}
    checks.require("clocks", len(schedule) == len(calendar["source_schedule_rows"]), "calendar.unique_dates")
    close = lambda day: utc_ns(schedule[day]["reference_close_utc"].replace("+00:00", "Z"))
    grids = plan["grid"]
    checks.require("clocks", len(grids) >= 3 and len({r["date"] for r in grids}) == len(grids), at + ".grid")
    dates = [r["date"] for r in grids]
    checks.require("clocks", dates == sorted(dates), at + ".date_order")
    calendar_phase = saved.get("reference_phase", name)
    checks.require("clocks", type(calendar.get("phases")) is dict and calendar_phase in calendar["phases"],
                   "calendar.phases." + str(calendar_phase))
    expected = calendar_expectations(calendar["phases"][calendar_phase], checks, "calendar.phases." + str(calendar_phase))
    if expected is None:
        return
    checks.check("clocks", dates == expected["dates"] and len(grids) == expected["nav_points"] and
                 len(grids) - 1 == expected["return_count"], at + ".calendar_grid")
    for i, row in enumerate(grids):
        checks.check("clocks", row["nominal_ns"] == close(row["date"]) and
                     row["sample_ns"] == close(row["date"]) + 1000, f"{at}.grid[{i}]")
    decisions = {r["day"]: r for r in plan["decisions"]}
    checks.require("clocks", len(decisions) == len(plan["decisions"]) and
                   len(decisions) == expected["decision_count"], at + ".decisions")
    if expected["decision_pairs"] is not None:
        checks.check("clocks", [(r["formation"], r["day"]) for r in plan["decisions"]] == expected["decision_pairs"],
                     at + ".daily_calendar_plan_correspondence")
    schedule_days = list(schedule)
    for day, decision in decisions.items():
        formation = decision["formation"]
        index = schedule_days.index(formation)
        checks.check("clocks", index + 1 < len(schedule_days) and schedule_days[index + 1] == day and
                     decision["known_ns"] == midnight_ns(formation) and
                     decision["decision_ns"] == midnight_ns(formation) + 60 * 10**9 and
                     decision["known_ns"] < decision["decision_ns"] < decision["open_ns"] == close(day), at + ".decision." + day)
    legs, evaluated = simulation["legs"], evaluation["legs"]
    ids = [r["id"] for r in legs]
    checks.require("shape", ids == [r["id"] for r in profile["legs"]] and len(ids) == len(set(ids)) and
                   [r["id"] for r in evaluated] == ids, at + ".leg_identity")
    checks.require("public_correspondence", [r["id"] for r in public["series"]] == ids and
                   public["basis"]["wealth_basis"] == "SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT" and
                   len(public["grid"]) == len(grids), at + ".public.legs_basis_grid")
    checks.check("public_correspondence", public["primary_benchmark_id"] == profile["primary_benchmark"] and
                 [r["id"] for r in public["series"] if r["role"] == "STRATEGY"] == [profile["primary_strategy"]] and
                 [r["id"] for r in public["series"] if r["role"] == "BENCHMARK"] == [profile["primary_benchmark"]],
                 at + ".public.strategy_benchmark_roles")
    metric_rows = {r["id"]: r for r in public["metrics"]}
    checks.require("public_correspondence", len(metric_rows) == len(public["metrics"]), at + ".public.unique_metrics")
    expected_by_leg = {}
    for leg, actual_metrics, public_leg in zip(legs, evaluated, public["series"]):
        address = at + ".legs." + leg["id"]
        nav, fills, orders = leg["nav"], leg["fills"], leg["orders"]
        checks.require("shape", len(nav) == len(grids) and len(public_leg["values"]) == len(grids) and
                       len(public_leg["ledger"]) == len(grids), address + ".grid_lengths")
        for i, row in enumerate(nav):
            checks.require("shape", all(integer(row.get(k)) for k in
                           ("cash_cents", "exposure_cents", "nav_cents", "flat_cents", "bps_cents")) and
                           row["nav_cents"] > 0 and set(row["positions"]) == set(symbols) and
                           set(row["position_cents"]) == set(symbols) and
                           all(integer(v) for v in row["positions"].values()) and
                           all(integer(v) for v in row["position_cents"].values()), address + f".nav[{i}].integer_domain")
        intents = {r["day"]: r for r in leg["intents"]}
        checks.require("clocks", list(intents) == list(decisions) and len(intents) == len(leg["intents"]), address + ".intent_identity")
        fills_by_day = {day: [] for day in dates}
        for fill in fills:
            checks.require("shape", all(integer(fill.get(k), 1) for k in ("q", "price_micro", "at_ns")) and
                           all(integer(fill.get(k)) for k in ("fee_cents", "settled_cents", "cash_after_cents", "exact_notional_micro")),
                           address + ".fill_integer_domain")
            chunks = fill["id"].split("/")
            checks.require("fills", len(chunks) == 4 and chunks[0] == leg["id"] and
                           chunks[1] in decisions, address + ".fill_identity")
            fills_by_day[chunks[1]].append(fill)
        cash, held = initial_cents, dict.fromkeys(symbols, 0)
        cumulative_flat = cumulative_bps = order_index = 0
        prices = plan["prices"]
        for index, day in enumerate(dates):
            if day in decisions:
                decision, intent = decisions[day], intents[day]
                checks.check("clocks", all(intent[k] == decision[k] for k in ("formation", "known_ns", "decision_ns")), address + ".intent." + day)
                instruction = decision["instructions"][leg["id"]]
                if instruction["kind"] == "EXIT":
                    targets = dict.fromkeys(symbols, 0)
                elif instruction["kind"] == "HOLD":
                    targets = dict(held)
                elif instruction["kind"] == "TARGET":
                    weights = {s: Fraction(*instruction["weights"][s]) for s in symbols}
                    checks.require("saved_target_quantities", all(w >= 0 for w in weights.values()) and
                                   sum(weights.values()) <= 1, address + ".weight_domain")
                    marks = {s: prices[decision["formation"]][s]["close_micro"] for s in symbols}
                    checks.require("shape", all(integer(p, 1) for p in marks.values()), address + ".formation_marks")
                    wealth = cash + sum(round_micro_to_cents(held[s] * marks[s]) for s in symbols)
                    targets = {s: (Fraction(wealth * 10000) * weights[s] / marks[s]).__floor__() for s in symbols}
                else:
                    checks.unknown("saved_target_quantities", "UNSUPPORTED_INSTRUCTION")
                    return
                checks.check("saved_target_quantities", intent["targets"] == targets, address + ".frozen_targets." + day)
                expected_fills = []
                for side in ("SELL", "BUY"):
                    for offset, symbol in enumerate(symbols):
                        desired = max(held[symbol] - targets[symbol], 0) if side == "SELL" else max(targets[symbol] - held[symbol], 0)
                        if not desired:
                            continue
                        price = prices[day][symbol]["close_micro"]
                        checks.require("shape", integer(price, 1), address + ".execution_quote")
                        quantity = desired if side == "SELL" else affordable(desired, price, cash)
                        stamp = close(day) + (100 if side == "SELL" else 200) + offset
                        source_id = f"{leg['id']}/{day}/{side}/{symbol}"
                        expected_order = {"id": source_id, "symbol": symbol, "side": side, "at_ns": stamp,
                                          "intended_quantity": desired, "routed_quantity": quantity,
                                          "reason": "FEE_AWARE_BUDGET_CAP" if quantity < desired else None}
                        checks.check("orders", order_index < len(orders) and orders[order_index] == expected_order,
                                     address + f".orders[{order_index}]")
                        order_index += 1
                        if not quantity:
                            continue
                        settlement, fee = round_micro_to_cents(quantity * price), fee_cents(quantity, price)
                        sign = 1 if side == "BUY" else -1
                        cash -= sign * settlement + fee
                        held[symbol] += sign * quantity
                        cumulative_flat += 100
                        cumulative_bps += fee - 100
                        epsilon = settlement * 10000 - quantity * price
                        expected_fills.append({"id": source_id, "symbol": symbol, "side": side, "at_ns": stamp,
                            "q": quantity, "price_micro": price, "fee_cents": fee, "settled_cents": settlement,
                            "cash_after_cents": cash, "exact_notional_micro": quantity * price,
                            "settlement_epsilon_micro": epsilon, "cash_rounding_micro": -sign * epsilon})
                        checks.check("ledger", cash >= 0 and all(q >= 0 for q in held.values()), address + ".no_borrow_short")
                actual_fills = fills_by_day[day]
                checks.check("fills", len(actual_fills) == len(expected_fills), address + ".fill_count." + day)
                for fill_index, (actual, expected) in enumerate(zip(actual_fills, expected_fills)):
                    for key, value in expected.items():
                        group = "clocks" if key == "at_ns" else "costs" if "fee" in key or "rounding" in key or "epsilon" in key else "fills"
                        checks.check(group, actual.get(key) == value, address + f".fills.{day}[{fill_index}]." + key)
                    if "native_cash_after_cents" in actual:
                        checks.check("native_cash", actual["native_cash_after_cents"] == expected["cash_after_cents"], address + ".native_cash." + day)
                    else:
                        checks.unknown("native_cash", "SAVED_NATIVE_CASH_NOT_PRESENT")
            row = nav[index]
            amounts = {s: round_micro_to_cents(held[s] * prices[day][s]["close_micro"]) for s in symbols}
            expected = {"cash_cents": cash, "positions": dict(held), "position_cents": amounts,
                        "exposure_cents": sum(amounts.values()), "nav_cents": cash + sum(amounts.values()),
                        "flat_cents": cumulative_flat, "bps_cents": cumulative_bps}
            checks.check("ledger", all(row.get(k) == v for k, v in expected.items()), address + f".nav[{index}]")
            checks.check("clocks", row["date"] == day and row["nominal_ns"] == close(day) and
                         row["sample_ns"] == close(day) + 1000, address + f".nav[{index}].clock")
            checks.check("public_correspondence", utc_ns(public["grid"][index]) == row["nominal_ns"] and
                         public_leg["values"][index] == record(Fraction(row["nav_cents"], 100)), address + f".public.nav[{index}]")
            ledger = public_leg["ledger"][index]
            checks.check("public_correspondence", all(ledger.get(k) == decimal_token(Fraction(row[v], 100))
                         for k, v in [("cash", "cash_cents"), ("exposure", "exposure_cents"),
                                      ("cumulative_flat_fees", "flat_cents"), ("cumulative_bps_fees", "bps_cents")]) and
                         ledger["positions"] == row["positions"], address + f".public.ledger[{index}]")
        checks.check("orders", order_index == len(orders), address + ".all_orders_accounted")
        checks.check("terminal_liquidation", not any(held.values()) and not any(nav[-1]["positions"].values()) and
                     nav[-1]["exposure_cents"] == 0 and nav[-1]["nav_cents"] == nav[-1]["cash_cents"], address + ".terminal")
        expected_metrics, returns = metrics(nav, fills)
        expected_by_leg[leg["id"]] = expected_metrics
        for key, value in expected_metrics.items():
            expected_value = record(value)
            checks.check("metrics", actual_metrics["metrics"].get(key) == expected_value, address + ".metrics." + key)
            public_metric = metric_rows.get(ALIASES.get(key, key), {})
            checks.check("public_correspondence", public_metric.get("values", {}).get(leg["id"]) == expected_value,
                         address + ".public.metrics." + key)
        checks.check("metrics", len(actual_metrics["returns"]) == len(returns), address + ".return_count")
        for index, (actual, expected) in enumerate(zip(actual_metrics["returns"], returns)):
            checks.check("metrics", Fraction(int(actual["numerator"]), int(actual["denominator"])) == expected and
                         actual["decimal"] == decimal_token(expected), address + f".returns[{index}]")
            checks.check("public_correspondence", public_leg["ledger"][index + 1]["net_return"] == record(expected),
                         address + f".public.returns[{index}]")
        checks.check("public_correspondence", public_leg["ledger"][0]["net_return"] == {
            "value": None, "status": "NOT_APPLICABLE", "reason": "INITIAL_POINT"}, address + ".initial_return")
    for i, comparison in enumerate(evaluation["comparisons"]):
        key, left, right = comparison["metric_id"], comparison["left_id"], comparison["right_id"]
        checks.require("comparisons", left in expected_by_leg and right in expected_by_leg and
                       key in expected_by_leg[left] and key in expected_by_leg[right], at + f".comparisons[{i}].linkage")
        a, b = expected_by_leg[left][key], expected_by_leg[right][key]
        if a is None or b is None:
            expected = {"value": None, "status": "UNAVAILABLE", "reason": "PAIRED_METRIC_UNAVAILABLE"}
        else:
            with localcontext(CONTEXT):
                expected = record(Decimal(decimal_token(a)) - Decimal(decimal_token(b)))
        checks.check("comparisons", comparison["result"] == expected, at + f".comparisons[{i}].difference")
        public_matches = [r for r in public["comparisons"] if r["metric_id"] == ALIASES.get(key, key) and
                          r["left_id"] == left and r["right_id"] == right]
        checks.check("public_correspondence", len(public_matches) == 1 and public_matches[0]["result"] == expected,
                     at + f".public.comparisons[{i}]")
    checks.check("public_correspondence", len(public["comparisons"]) == len(evaluation["comparisons"]) and
                 public["criteria"] == evaluation["criteria"], at + ".criteria_and_comparison_linkage")
    specs = profile["criteria"] if saved.get("reference_phase", name) == "FINAL" else []
    checks.require("criteria", [c["id"] for c in evaluation["criteria"]] == [c["id"] for c in specs], at + ".criteria_identity")
    for spec, actual in zip(specs, evaluation["criteria"]):
        left = expected_by_leg[spec["left_id"]]
        right = expected_by_leg.get(spec.get("right_id"))
        try:
            met = criterion(spec, left, right, initial_cents)
        except NotImplementedError:
            checks.unknown("criteria", "UNSUPPORTED_PREDICATE_" + str(spec["kind"]))
            continue
        if met is None:
            checks.check("criteria", actual["status"] == "UNAVAILABLE" and bool(actual["reason"]), at + ".criteria." + spec["id"])
            continue
        checks.check("criteria", actual["status"] == ("MET" if met else "NOT_MET") and actual["reason"] is None,
                     at + ".criteria." + spec["id"])


def verify(packet, packet_sha256=None):
    checks = Checks()
    raw = canonical(packet)
    if type(packet) is not dict:
        packet = {}
        checks.check("packet", False, "packet.object_required")
    subject = {"semantic_id": packet.get("semantic_id"), "expected_bindings": packet.get("expected_bindings", {})}
    try:
        checks.require("packet", packet.get("schema") == "polar.saved-verifier-packet/1", "packet.schema")
        if packet.get("profile") != PROFILE:
            checks.unknown("profile", "UNSUPPORTED_SAVED_OUTPUT_PROFILE")
        else:
            initial = packet.get("initial_capital_cents")
            checks.require("profile", integer(initial, 1), "initial_capital_cents")
            files = SavedFiles(packet["root"])
            manifest_raw = checks.pinned(files, packet["manifest"])
            checks.require("content_identity", packet["semantic_id"] == "scheduled-reference-experiment-" + digest(manifest_raw), "semantic_id")
            manifest = decode(manifest_raw)
            checks.require("content_identity", manifest.get("schema") == "polar.scheduled-reference-semantic-manifest/1" and
                           set(manifest["files"]) == MEMBERS, "semantic.schema_members")
            directory = str(PurePosixPath(packet["manifest"]["path"]).parent)
            saved = {}
            for name, pin in manifest["files"].items():
                saved[name] = decode(checks.pinned(files, {**pin, "path": directory + "/" + name}))
            if packet.get("graph"):
                graph = decode(checks.pinned(files, packet["graph"]))
                for name, pin in graph["members"].items():
                    checks.pinned(files, {**pin, "path": name}, "content_graph")
            else:
                checks.unknown("content_graph", "NO_GRAPH_PIN_SUPPLIED")
            bindings, profile, calendar = saved["bindings.json"], saved["profile.json"], saved["calendar.json"]
            actual_bindings = {"code_revision": bindings["code_revision"], "runtime_image_id": bindings["runtime_image_id"],
                               "protocol_sha256": bindings["protocol_ref"]["sha256"], "input_sha256": bindings["input_ref"]["sha256"],
                               "candidate_id": bindings["candidate_id"], "experiment_id": bindings["experiment_id"],
                               "profile_sha256": manifest["files"]["profile.json"]["sha256"],
                               "calendar_sha256": manifest["files"]["calendar.json"]["sha256"]}
            checks.require("bindings", packet.get("expected_bindings") == actual_bindings, "expected_bindings")
            subject["verified_bindings"] = actual_bindings
            publications = packet["publications"]
            phases = saved["phases.json"]
            checks.require("bindings", len(publications) == len(phases) and
                           {r["phase"] for r in publications} == set(phases), "phase_publication_set")
            for ref in publications:
                name = ref["phase"]
                try:
                    public_raw = checks.pinned(files, ref)
                    checks.require("public_correspondence", ref["result_id"] == "research-" + digest(public_raw), name + ".result_id")
                    public = decode(public_raw)
                    checks.require("public_correspondence", canonical(public) == public_raw and
                                   public["schema_version"] == "polar.research-result/1" and
                                   public["bindings"]["code_revision"] == actual_bindings["code_revision"] and
                                   public["bindings"]["runtime_id"] == actual_bindings["runtime_image_id"] and
                                   public["bindings"]["protocol_sha256"] == actual_bindings["protocol_sha256"] and
                                   public["bindings"]["data_sha256"] == actual_bindings["input_sha256"] and
                                   public["bindings"]["candidate_id"] == actual_bindings["candidate_id"] and
                                   public["bindings"]["experiment_id"] == actual_bindings["experiment_id"] and
                                   public["question"]["id"] == profile["protocol_id"] + "." + name and
                                   [p for p in public["provenance"] if p["role"] == "semantic_manifest"] ==
                                   [{"role": "semantic_manifest", "id": packet["semantic_id"], "sha256": digest(manifest_raw)}], name + ".binding")
                    verify_phase(name, phases[name], public, profile, calendar, checks, initial)
                except (ValueError, KeyError, TypeError, IndexError, ArithmeticError) as exc:
                    if isinstance(exc, KeyError):
                        key = str(exc.args[0])
                        key = key if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key) else "unknown_field"
                        checks.check("shape", False, at_phase_address(name, key), "MISSING_SAVED_FIELD")
                    else:
                        checks.check("shape", False, "phases." + name + "." + type(exc).__name__)
    except (ValueError, KeyError, TypeError, IndexError, ArithmeticError, OSError) as exc:
        checks.check("input_integrity", False, type(exc).__name__)
    statuses = [v["status"] for v in checks.groups.values()]
    verdict = "FAIL" if "FAIL" in statuses else "UNKNOWN" if "UNKNOWN" in statuses else "PASS"
    unverified = [{"property": name, "status": "UNKNOWN", "reason": reason} for name, reason in [
        ("signal_feature_construction", "SAVED_INSTRUCTIONS_CONSUMED_NOT_POLICY_REEXECUTED"),
        ("source_fitness_and_historical_availability", "OUTSIDE_SAVED_OUTPUT_EVIDENCE"),
        ("diagnostic_tail_and_bootstrap", "NOT_IMPLEMENTED_IN_THIS_PROFILE"),
        ("financial_adoption", "SEPARATE_VALIDATOR_INTERPRETATION_REQUIRED")]]
    source_hashes = {p.name: digest(p.read_bytes()) for p in [Path(__file__), Path(__file__).with_name("saved_verifier_math.py")]}
    return {"schema": "polar.saved-verifier-report/1", "profile": packet.get("profile"), "subject": subject,
            "packet_sha256": packet_sha256 or digest(raw), "checker": {"version": "1.1", "source_sha256": source_hashes},
            "covered_verdict": verdict, "overall_verdict": "FAIL" if verdict == "FAIL" else "UNKNOWN",
            "checks": checks.groups, "unverified_properties": unverified,
            "summary": dict(Counter(v["status"] for v in checks.groups.values())),
            "scientific_calls": {"producer": 0, "evaluator": 0, "fit": 0, "native": 0, "reproduction": 0},
            "financial_verdict": "NOT_ASSESSED"}


def at_phase_address(phase, missing_field):
    return "phases." + phase + ".missing_field." + missing_field


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--packet-sha256")
    args = parser.parse_args(argv)
    try:
        path = Path(args.packet)
        raw = SavedFiles(path.absolute().parent).read(path.name, maximum=1024**2)
        if args.packet_sha256 and digest(raw) != args.packet_sha256:
            raise ValueError("PACKET_HASH_MISMATCH")
        result = verify(decode(raw), digest(raw))
    except (ValueError, OSError, TypeError) as exc:
        result = {"schema": "polar.saved-verifier-report/1", "covered_verdict": "FAIL", "overall_verdict": "FAIL",
                  "error": type(exc).__name__, "financial_verdict": "NOT_ASSESSED"}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 1 if result["covered_verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
