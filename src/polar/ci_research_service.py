"""One immutable economic attempt, stored-only recomputation and public projection.

Trusted local operation grants are explicit bindings, not a public run endpoint.
No queue, orchestration controller, source fetch, dynamic strategy or auto retry.
"""
import importlib.metadata
import multiprocessing
import os
from pathlib import Path
import platform
import re
import sys
import time
import traceback
import uuid

from .ci_research import (PROFILES, ResearchRunError, require, prepared, utc_text, project, cents_text)
from .ci_research_evaluation import evaluate
from .gym_contract import canonical, decode, read_ref, sha
from .gym_service import code_binding
from .history_bundle import read_file, safe_root, decode as metadata_decode
from .history_store import HistoryStore
from .research_results import ResearchResults

METHODS = {"A_MOMENTUM": "53d503307cadb16b7c9b983de49a1dcb77e8b97033a9647a5c2230524aa2a25d",
           "B_TOM": "277d4e1ac05627d2736df8ef3781efdb4438077aaf4eeaf6ab24d027fe0a5c1a"}


def config_from_seed(seed):
    """Deterministic local config assembly, not a run/grant or financial output."""
    def ref(name):
        path = Path(seed[name])
        require(path.is_absolute() and not path.is_symlink(), "CONFIG_SEED_PATH")
        body = read_file(path.parent, path.name, 16*1024**2)
        return {"path": str(path), "sha256": sha(body)}
    return {"schema": "polar.ci-research-config/1", "namespace": seed["namespace"],
            "profile_id": seed["profile_id"], "protocol_ref": ref("protocol_path"),
            "input_ref": ref("input_path"), "timezone_ref": ref("timezone_path"),
            "code": code_binding(), "code_revision": seed["code_revision"],
            "runtime_image_id": seed["runtime_image_id"], "execution_authority_ref":
                ref("execution_authority_path") if seed.get("execution_authority_path") else None,
            "candidate_id": seed["candidate_id"], "experiment_id": seed["experiment_id"],
            "artifact_root_identity": root_identity(Path(os.environ.get("POLAR_ARTIFACT_ROOT", "/data/artifacts")))}


def root_identity(root):
    path = safe_root(root); st = path.stat()
    return {"path": str(path), "device": str(st.st_dev), "inode": str(st.st_ino)}


def operation_binding(config, pins):
    return {"config_sha256": sha(canonical({k:v for k,v in config.items() if k != "execution_authority_ref"})),
            "pins": pins, "runtime_image_id": config["runtime_image_id"], "code_revision": config["code_revision"]}


def worker(connection, plan, expected_code):
    invoked = False
    try:
        require(code_binding() == expected_code, "CHILD_LOADED_CODE_BINDING")
        from .ci_research_native import simulate
        invoked = True
        connection.send(("SUCCESS", simulate(plan, lambda event: connection.send(("DIAGNOSTIC", event)))))
    except BaseException as exc:
        code = str(exc)
        raw = traceback.format_exc().encode("utf-8")
        connection.send(("DIAGNOSTIC", {"phase": "PRIVATE_FAILURE_TRACE", "traceback_utf8": raw[:32768].decode("utf-8", "ignore"),
                                       "original_bytes": len(raw), "truncated": len(raw) > 32768}))
        if not invoked:
            connection.send(("DIAGNOSTIC", {"phase": "NOT_REACHED_NATIVE", "basis": "Worker failed before invoking simulate"}))
        connection.send(("FAILED", code if re.fullmatch(r"[A-Z][A-Z0-9_]{0,120}", code) else type(exc).__name__))
    finally:
        connection.close()


def bounded_native(plan):
    ctx = multiprocessing.get_context("spawn"); parent, child = ctx.Pipe(False)
    process = ctx.Process(target=worker, args=(child, plan, code_binding())); process.start(); child.close()
    events = []; started = time.monotonic()
    try:
        while True:
            remaining = max(0, 300-(time.monotonic()-started))
            require(parent.poll(remaining), "NATIVE_WALL_TIMEOUT")
            status, value = parent.recv()
            if status != "DIAGNOSTIC":
                break
            require(len(events) < 100, "NATIVE_DIAGNOSTIC_BOUND")
            events.append(value)
        process.join(5)
        if status != "SUCCESS":
            raise NativeFailure("NATIVE_FAILED_"+str(value), events)
        require(not process.is_alive() and process.exitcode == 0 and status == "SUCCESS",
                "NATIVE_FAILED_" + str(value) if status != "SUCCESS" else "NATIVE_NOT_REAPED")
        return {**value, "physical_native_events": events}
    except NativeFailure:
        raise
    except BaseException as exc:
        code = str(exc) if re.fullmatch(r"[A-Z][A-Z0-9_]{0,120}", str(exc)) else type(exc).__name__
        raise NativeFailure(code, events) from None
    finally:
        parent.close()
        if process.is_alive(): process.terminate(); process.join(2)
        if process.is_alive(): process.kill(); process.join(2)
        require(not process.is_alive(), "NATIVE_REAP_UNVERIFIED")


class NativeFailure(ResearchRunError):
    def __init__(self, code, events):
        self.events = events
        super().__init__(code)


def public_projection(config, pins, simulation, evaluation, semantic_id, semantic_hash):
    profile = PROFILES[config["profile_id"]]; ids = profile["legs"]
    grid = [utc_text(r["nominal_ns"]) for r in simulation["legs"][0]["nav"]]
    by_id = {r["id"]: r for r in evaluation["legs"]}
    series = []
    for i, leg in enumerate(simulation["legs"]):
        returns = by_id[leg["id"]]["returns"]
        ledger = []
        for j,row in enumerate(leg["nav"]):
            ledger.append({"cash": cents_text(row["cash_cents"]), "exposure": cents_text(row["exposure_cents"]),
                           "cumulative_flat_fees": cents_text(row["flat_cents"]),
                           "cumulative_bps_fees": cents_text(row["bps_cents"]), "positions": row["positions"],
                           "net_return": {"value": returns[j-1]["decimal"] if j else None,
                              "status": "OK" if j else "NOT_APPLICABLE", "reason": None if j else "INITIAL_POINT"}})
        series.append({"id": leg["id"], "label": leg["id"], "role": "STRATEGY" if i == 0 else "BENCHMARK" if i == 1 else "CONTROL",
                       "unit": "USD", "values": [{"value": cents_text(r["nav_cents"]), "status": "OK", "reason": None} for r in leg["nav"]],
                       "ledger": ledger})
    monetary = {"terminal_nav_usd", "flat_fee_usd", "bps_cost_usd", "total_cost_usd", "gross_exact_notional_usd", "gross_settled_notional_usd"}
    units = {name: "USD" if name in monetary else "count" if name == "positive_fill_count" else "ratio" if name == "sharpe_252_rf0" else "fraction"
             for name in evaluation["legs"][0]["metrics"]}
    metrics = [{"id": name, "label": name.replace("_", " "), "unit": units[name],
                "values": {leg["id"]: leg["metrics"][name] for leg in evaluation["legs"]}}
               for name in units]
    aliases = {}
    if profile["kind"] == "B_TOM":
        aliases = {"net_total_return": "price_return_after_costs", "net_cagr_act36525": "price_cagr_after_costs",
                   "annual_vol_252": "annual_volatility", "sharpe_252_rf0": "net_sharpe",
                   "total_cost_usd": "fees_usd", "gross_exact_notional_usd": "gross_traded_notional_usd",
                   "positive_fill_count": "filled_order_count", "invested_session_fraction": "invested_close_fraction",
                   "mean_close_exposure": "mean_close_equity_fraction"}
        for item in metrics:
            item["id"] = aliases.get(item["id"], item["id"])
    costs = [{"id": "FLAT_ORDER_COST", "label": "Flat order costs", "kind": "CHARGED_FEES", "unit": "USD",
              "values": {leg["id"]: leg["metrics"]["flat_fee_usd"] for leg in evaluation["legs"]},
              "description": "Modeled USD1 per positive fill, debited once inside native commission."},
             {"id": "BPS_EXECUTION_COST", "label": "Modeled 10bps cost", "kind": "MODELED_SLIPPAGE", "unit": "USD",
              "values": {leg["id"]: leg["metrics"]["bps_cost_usd"] for leg in evaluation["legs"]},
              "description": "Ceiling-cent 10bps exact notional, debited once inside commission; no additional spread/slippage debit."}]
    if profile["kind"] == "B_TOM":
        costs[1]["kind"] = "CHARGED_FEES"
        costs[1]["label"] = "10bps commission component"
    costs.append({"id": "UNMODELED_CAPACITY_AND_TAX", "label": "Unmodeled capacity and tax effects", "kind": "UNMODELED", "unit": "USD",
                  "values": {leg: {"value": None, "status": "NOT_APPLICABLE" if leg == "CASH" else "UNAVAILABLE",
                                     "reason": "NO_ORDER_EXPOSURE" if leg == "CASH" else "NOT_ESTIMATED_BY_MODEL"} for leg in ids},
                  "description": "Not debited or estimated; this is not a zero-cost claim and does not change the frozen fee scenario."})
    limitations = [
        ("SURVIVOR_CONDITIONED", "Fixed known-survivor cohort; not the historical full universe."),
        ("PRICE_ONLY_DIVIDENDS_OMITTED", "Modeled price-ledger returns after costs, not investor total returns; dividends deliberately omitted."),
        ("COUNTERFACTUAL_TIMING", "New York K, decision, open and close are counterfactual clock assumptions, not observed historic availability."),
        ("ACTION_COMPLETENESS_UNVERIFIED", "No-other-actions model; captured later splits do not establish complete action history."),
        ("EXECUTION_COST_MODEL", "Raw opening quotes, whole shares and immediate fills/settlement are modeled; costs are not calibrated capacity proof."),
        ("RETROSPECTIVE_EXPOSED_SINGLE_WINDOW", "One exposed retrospective window; dependent observations and no significance or live evidence."),
        ("NOT_RISK_MATCHED", "Initial benchmark allocations drift and are not matched-risk controls."),
        ("NO_INFERENTIAL_ORIGINAL_HYP_CLAIM", "Point conditions do not validate the original broad hypothesis or establish adoption.")]
    criteria = evaluation["criteria"]
    if profile["kind"] == "B_TOM":
        criteria = [{**c, "id": mapped} for c,mapped in zip(criteria,
                    ("sharpe_delta_ge_0p10", "positive_growth", "drawdown_le_full_bh"))]
    return {"schema_version": "polar.research-result/1",
            "question": {"id": config["profile_id"], "label": "Monthly lagged momentum" if profile["kind"] == "A_MOMENTUM" else "Turn-of-month calendar timing",
                         "summary": "Fixed survivor-conditioned modeled raw price-ledger question; protocol and limitations govern interpretation."},
            "bindings": {"protocol_id": config["profile_id"], "protocol_sha256": pins["protocol_sha256"],
                         "data_revision": "selected-"+pins["input_sha256"], "data_sha256": pins["input_sha256"],
                         "code_revision": config["code_revision"], "evaluator_revision": config["code_revision"],
                         "runtime_id": config["runtime_image_id"], "producer_id": "polar-ci-research",
                         "candidate_id": config["candidate_id"], "experiment_id": config["experiment_id"]},
            "basis": {"currency": "USD", "frequency": "DAILY", "timezone": "UTC" if profile["kind"] == "A_MOMENTUM" else "America/New_York", "wealth_basis": "PRICE_ONLY",
                      "cost_basis": "NET", "cash_basis": "MODELED_ZERO_CASH_CREDIT", "risk_free_basis": "MODELED_ZERO_REFERENCE"},
            "grid": grid, "series": series, "primary_benchmark_id": ids[1], "metrics": metrics,
            "comparisons": [{**c, "metric_id": aliases.get(c["metric_id"], c["metric_id"]), "unit": units[c["metric_id"]], "interpretation": "Producer-computed point difference, not significance or adoption."} for c in evaluation["comparisons"]],
            "costs": costs, "limitations": [{"code": c, "text": t, "scope": "Entire modeled comparison"} for c,t in limitations],
            "provenance": [{"role": "semantic_manifest", "id": semantic_id, "sha256": semantic_hash},
                           {"role": "protocol", "id": config["profile_id"], "sha256": pins["protocol_sha256"]},
                           {"role": "source_manifest", "id": "retained-source", "sha256": pins["source_sha256"]},
                           {"role": "reference_calendar", "id": "XNYS_REFERENCE_DATES_ONLY", "sha256": pins["calendar_sha256"]}],
            "evidence_level": "RETAINED_DESCRIPTIVE" if config["namespace"] == "RETAINED" else "INVENTED_CONTROL",
            "financial_claim": "Limited modeled price-ledger point comparison; no original-hypothesis, total-return or adoption claim.",
            "criteria": criteria, "point_interpretation": evaluation["point_interpretation"]}


class ResearchService:
    def __init__(self, root, limit):
        self.store = HistoryStore(root, limit)
        self.results = ResearchResults(root, limit)

    def prepare(self, config):
        expected = {"schema", "namespace", "profile_id", "protocol_ref", "input_ref", "timezone_ref",
                    "code", "code_revision", "runtime_image_id", "execution_authority_ref", "candidate_id", "experiment_id",
                    "artifact_root_identity"}
        require(set(config) == expected, "CONFIG_FIELDS")
        require(config["artifact_root_identity"] == root_identity(self.store.root), "PERSISTENT_ARTIFACT_ROOT_IDENTITY")
        require(config["code"] == code_binding() and type(config["code_revision"]) is str and
                re.fullmatch(r"[a-f0-9]{40}", config["code_revision"]), "LOADED_CODE_BINDING")
        require(type(config["runtime_image_id"]) is str and re.fullmatch(r"sha256:[a-f0-9]{64}", config["runtime_image_id"]), "IMAGE_ID")
        if config["namespace"] == "RETAINED":
            require(sys.pycache_prefix is not None and os.environ.get("PYTHONDONTWRITEBYTECODE") == "1",
                    "ISOLATED_SOURCE_CACHE_REQUIRED")
            require(os.environ.get("POLAR_RUNTIME_IMAGE_ID") == config["runtime_image_id"], "ACTUAL_RUNTIME_IMAGE_BINDING")
            require(platform.system() == "Linux" and platform.machine() in ("aarch64", "x86_64"), "OFFICIAL_PLATFORM")
            require(platform.python_version() == "3.13.18", "OFFICIAL_PYTHON")
            for name,version in {"nautilus-trader": "1.231.0", "numpy": "2.2.6", "scipy": "1.15.3"}.items():
                require(importlib.metadata.version(name) == version, "OFFICIAL_NATIVE_VERSION")
        plan, pins = prepared(config)
        return plan, pins

    def run(self, config):
        # All static readiness/input/source/native bindings precede the debit.
        plan, pins = self.prepare(config)
        binding = operation_binding(config, pins)
        family = sha(canonical({"profile": config["profile_id"], "input": pins["input_sha256"], "namespace": config["namespace"]}))
        parent = "ci-research-attempts/"+family
        directory = self.store.root/parent
        aid = str(uuid.uuid4())
        authority = None
        if config["namespace"] == "RETAINED":
            authority = decode(read_ref(config["execution_authority_ref"]))
            require(authority.get("schema") == "polar.ci-research-operation/1" and
                    authority.get("binding_sha256") == sha(canonical(binding)) and
                    authority.get("input_classification") == "RETAINED" and authority.get("action") == "ORIGINAL",
                    "RETAINED_OPERATION_NOT_BOUND")
            for key in ("method_ref", "candidate_ref", "qualification_ref"):
                read_ref(authority[key])
            kind = PROFILES[config["profile_id"]]["kind"]
            require(authority["method_ref"]["sha256"] == METHODS[kind], "METHOD_REVIEW_PIN")
            candidate = metadata_decode(read_ref(authority["candidate_ref"]), source=True)
            require(candidate.get("schema") == "polar.native-hypothesis-reservation/1" and
                    candidate.get("state") == "RESERVED" and candidate.get("candidate_id") == config["candidate_id"] and
                    candidate.get("experiment_registration_id") == config["profile_id"], "CANDIDATE_RESERVATION_PIN")
            # CI durations are nonfinancial metadata, never binary-float inputs
            # to the evaluator. Preserve their lexical tokens while checking
            # the exact SHA/candidate/PASS/selected-test association.
            qualification = metadata_decode(read_ref(authority["qualification_ref"]), source=True)
            require(qualification.get("schema") == "polar.ci-result/1" and qualification.get("status") == "PASS" and
                    qualification.get("candidate_sha") == config["code_revision"] and
                    any(t in ("tests", "tests/test_ci_research.py") for t in qualification.get("selection", [])),
                    "EXACT_RUNNER_CI_QUALIFICATION")
        with self.store.locked():
            require(not directory.is_symlink(), "UNSAFE_ATTEMPT_DIRECTORY")
            prior = sorted(p.name for p in directory.iterdir()) if directory.exists() else []
            if authority is not None:
                require(authority.get("expected_prior_attempts") == prior, "ATTEMPT_HISTORY_MISMATCH")
                previous = []
                for pid in prior:
                    require(str(uuid.UUID(pid)) == pid, "ATTEMPT_IDENTITY")
                    try:
                        previous.append(decode(read_file(self.store.root, parent+"/"+pid+"/finish/record.json")))
                    except FileNotFoundError:
                        previous.append({"status": "UNFINALIZED", "actual_native_boundary": "UNKNOWN"})
                require(not any(p["status"] == "SUCCESS" for p in previous), "SUCCESSFUL_ORIGINAL_ALREADY_EXISTS")
                if PROFILES[config["profile_id"]]["kind"] == "B_TOM":
                    require(all(p.get("actual_native_boundary") == "NOT_REACHED" for p in previous), "B_ORIGINAL_ALREADY_CHARGED")
                elif prior:
                    read_ref(authority["correction_ref"])
            self.store._publish(parent, aid, {"start.json": canonical({"schema": "polar.ci-research-start/1",
                "attempt_id": aid, "family": family, "binding": binding, "status": "INTENT_CONSERVATIVE_DEBIT",
                "actual_native_boundary": "UNKNOWN_UNTIL_MATCHED_NATIVE_EVIDENCE", "started_ns": time.time_ns(),
                "authority_sha256": sha(canonical(authority)) if authority is not None else None}),
                "config.json": canonical(config), "authority.json": canonical(authority)})
        try:
            simulation = bounded_native(plan)
            evaluation = evaluate(simulation, plan["profile"])
            semantic = {"simulation.json": canonical(simulation), "evaluation.json": canonical(evaluation),
                        "bindings.json": canonical(binding)}
            manifest = {"schema": "polar.ci-research-semantic-manifest/1",
                        "files": {n: {"bytes": len(raw), "sha256": sha(raw)} for n,raw in semantic.items()}}
            mr = canonical(manifest); semantic_id = "ci-experiment-"+sha(mr)
            semantic["manifest.json"] = mr
            with self.store.locked():
                self.store._publish("ci-research-experiments", semantic_id, semantic, file_limit=32*1024**2)
            public = public_projection(config, pins, simulation, evaluation, semantic_id, sha(mr))
            publication = self.results.publish(public)
            finish = {"status": "SUCCESS", "attempt_id": aid, "semantic_id": semantic_id,
                      "result_id": publication["result_id"], "actual_native_boundary": "COMPLETED_MATCHED_NATIVE_EVIDENCE",
                      "financial_acceptance": "NOT_REVIEWED", "finished_ns": time.time_ns()}
        except BaseException as exc:
            code = str(exc) if re.fullmatch(r"[A-Z][A-Z0-9_]{0,120}", str(exc)) else type(exc).__name__
            with self.store.locked():
                events = getattr(exc, "events", [])
                self.store._publish(parent+"/"+aid, "finish", {"record.json": canonical({"status": "FAILED_UNFINALIZED",
                    "attempt_id": aid, "code": code, "actual_native_boundary":
                        "NOT_REACHED" if any(e.get("phase") == "NOT_REACHED_NATIVE" for e in events) else "UNKNOWN",
                    "refund": False}), "native-diagnostics.json": canonical(events)}, file_limit=32*1024**2)
            raise
        with self.store.locked():
            self.store._publish(parent+"/"+aid, "finish", {"record.json": canonical(finish)})
        return finish

    def recompute(self, semantic_id):
        require(re.fullmatch(r"ci-experiment-[a-f0-9]{64}", semantic_id), "EXPERIMENT_ID")
        base = "ci-research-experiments/"+semantic_id
        raw = read_file(self.store.root, base+"/manifest.json", 32*1024**2)
        require(semantic_id == "ci-experiment-"+sha(raw), "SEMANTIC_MANIFEST_HASH")
        manifest = decode(raw)
        require(set(manifest["files"]) == {"simulation.json", "evaluation.json", "bindings.json"}, "SEMANTIC_FILE_SET")
        files = {}
        for name,ref in manifest["files"].items():
            body = read_file(self.store.root, base+"/"+name, 32*1024**2)
            require(len(body) == ref["bytes"] and sha(body) == ref["sha256"], "SEMANTIC_MEMBER_HASH")
            files[name] = decode(body)
        simulation = files["simulation.json"]
        legs = [r["id"] for r in simulation["legs"]]
        matches = [p for p in PROFILES.values() if p["legs"] == legs]
        require(len(matches) == 1, "STORED_PROFILE_IDENTITY")
        require(canonical(evaluate(simulation, matches[0])) == canonical(files["evaluation.json"]), "STORED_RECOMPUTATION_MISMATCH")
        return {"status": "REPRODUCED", "semantic_id": semantic_id, "native_calls": 0, "store_writes": 0}
