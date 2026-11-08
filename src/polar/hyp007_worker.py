"""Fixed supervised worker entrypoint. No source fetch, dynamic callable, retry or fixture lease."""
import math
import os
import signal
import ctypes
import sys

from .history_bundle import read_file
from .hyp007_contract import (FOLDS, MODELS, MAX_FILE, MAX_OUTPUT, DiagnosticError, check,
                              canonical, decode, sha, utc)
from .hyp007_numeric import representations, ridge_fit, ridge_predict, tree_fit, tree_predict, losses
from .hyp007_panel import Panel
from .hyp007_service import binding, verify_build
from .hyp007_source import Source
from .hyp007_store import DiagnosticStore


def ndjson(rows):
    return b"".join(canonical(row)+b"\n" for row in rows)


def compile_output(source, seal, store, aid, defaults):
    panel = Panel(source, source.evidence)
    rows, masks = panel.realize(utc(seal["sealed_at"]))
    roster = {row["key"]: row for row in rows}
    folds = {}
    # Freeze numerical panel/masks and every training transform before the first fit.
    for fold in FOLDS:
        train = [m["key"] for m in masks if m["fold"] == fold and m["M_train"]]
        score = [m["key"] for m in masks if m["fold"] == fold and m["M_score"]]
        evaluation = [m["key"] for m in masks if m["fold"] == fold and m["M_eval"]]
        check(len(train) >= 200 and len(evaluation) > 0, "HYP007_INSUFFICIENT_EVIDENCE")
        transform, xtrain, xscore = representations([roster[k]["packet"]["features"] for k in train],
                                                   [roster[k]["packet"]["features"] for k in score])
        folds[fold] = {"train": train, "score": score, "eval": evaluation, "transforms": transform,
                       "xtrain": xtrain, "xscore": xscore,
                       "y": [roster[k]["target"]["value"] for k in train]}
    parent = "hyp007-attempts/"+aid
    frozen = {"panel.ndjson": ndjson(rows), "masks.ndjson": ndjson(masks),
              "transforms.json": canonical({str(f): folds[f]["transforms"] for f in FOLDS})}
    check(sum(map(len,frozen.values())) <= MAX_OUTPUT, "HYP007_OUTPUT_LIMIT")
    with store.locked():
        store._publish(parent, "frozen-panel", frozen, file_limit=MAX_FILE)
    models, predictions, loss_rows, summaries = {}, [], [], []
    ordinal = 0
    for fold in FOLDS:
        item = folds[fold]
        fold_predictions = {}
        for model_name in MODELS:
            store.start_slot(aid, ordinal)  # durable/fsynced before ANY learner call
            try:
                model = tree_fit(item["xtrain"][model_name], item["y"], defaults) if model_name == "tree" else \
                    ridge_fit(item["xtrain"][model_name], item["y"])
                predict = tree_predict if model_name == "tree" else ridge_predict
                output = predict(model, item["xscore"][model_name])
                check(len(output) == len(item["score"]) and all(math.isfinite(v) for v in output),
                      "HYP007_PREDICTION_INVALID")
                model_bytes = canonical(model)
                folded = dict(zip(item["score"], output))
                # Keep partial successful output even if a later learner or serialization fails.
                with store.locked():
                    store.record(parent+"/fit-outputs", str(ordinal), {"fold": fold, "model": model_name,
                                 "artifact": model, "predictions": folded})
                store.finish_slot(aid, ordinal, model.get("status", "SUCCESS"), sha(model_bytes))
                models[str(fold)+":"+model_name] = model
                fold_predictions[model_name] = folded
                predictions.extend({"fold": fold, "key": key, "model": model_name, "prediction": folded[key],
                                    "target_known": roster[key]["target"]["reason"] is None}
                                   for key in item["score"])
            except Exception as exc:
                code = exc.code if isinstance(exc, DiagnosticError) else "HYP007_FIT_FAILED"
                # If finish already published, immutable history remains authoritative; never refit.
                if store.slots(aid)[ordinal]["finish"] is None:
                    store.finish_slot(aid, ordinal, "FAILED", code=code)
                raise
            ordinal += 1
        fold_losses = {}
        summary = {"fold": fold, "n_train": len(item["train"]), "n_score": len(item["score"]),
                   "n_eval": len(item["eval"]), "models": {}}
        for name in MODELS:
            result = losses([fold_predictions[name][k] for k in item["eval"]],
                            [roster[k]["target"]["value"] for k in item["eval"]])
            fold_losses[name] = dict(zip(item["eval"], result["losses"]))
            summary["models"][name] = {k:v for k,v in result.items() if k != "losses"}
        for key in item["eval"]:
            loss_rows.append({"fold": fold, "key": key, "instrument": roster[key]["instrument"],
                              "losses": {name: fold_losses[name][key] for name in MODELS}})
        summaries.append(summary)
    pooled = {name: {"n": len(loss_rows), "SSE": math.fsum(r["losses"][name] for r in loss_rows)} for name in MODELS}
    for result in pooled.values():
        result["MSE"] = result["SSE"]/result["n"]
    contrasts = {"tree_minus_"+name: math.fsum(r["losses"]["tree"]-r["losses"][name] for r in loss_rows)/len(loss_rows)
                 for name in ("ridge6", "ridge21")}
    check(all(math.isfinite(v) for r in pooled.values() for v in r.values()) and
          all(math.isfinite(v) for v in contrasts.values()), "HYP007_LOSS_INVALID")
    report = {"schema": "polar.hyp007-calculation/1", "experiment_id": "hyp007-"+seal["seal_id"],
              "attempt_id": aid, "status": "CALCULATION_COMPLETED_PENDING_FINALIZATION", "folds": summaries,
              "pooled": pooled, "paired_contrasts": contrasts,
              "meaning": "CONDITIONAL_DESCRIPTIVE_LOSS_NOT_ALPHA_OR_UNTOUCHED_OOS",
              "census": {s: {"opportunities": sum(r["instrument"] == s for r in rows),
                             "info": sum(r["instrument"] == s and r["M_info"] for r in rows),
                             "unknown_target": sum(r["instrument"] == s and r["target"]["reason"] is not None for r in rows)}
                         for s in source.bars},
              "source_reads": {"bytes": source.bytes_read, "passes": source.read_passes},
              "real_fit_invocations": ordinal, "repeated_fit_reproducibility": "NOT_RUN"}
    return {"seal.json": canonical(seal), "inputs.json": canonical(source.inventory),
            "roster.ndjson": ndjson(source.roster), **frozen, "predictions.ndjson": ndjson(predictions),
            "losses.ndjson": ndjson(loss_rows), "models.json": canonical(models), "report.json": canonical(report)}


def main(argv=None):
    root, aid, limit, expected_parent = sys.argv[1:] if argv is None else argv
    # No labels/fits if the supervisor disappeared during Python startup. The fixed
    # worker never forks, uses one native thread and cannot survive parent death.
    check(sys.platform == "linux", "HYP007_EXECUTABLE_BUILD_UNAVAILABLE")
    check(ctypes.CDLL(None).prctl(1, signal.SIGKILL, 0, 0, 0) == 0 and
          os.getppid() == int(expected_parent), "HYP007_SUPERVISOR_LOST")
    store = DiagnosticStore(root, int(limit))
    seal = store.read_record("hyp007-attempts/"+aid, "request")
    try:
        # This worker can only continue an already admitted nonresetting family.
        started = store.read_record("hyp007-families/hyp007-source-cohort-predictor-v1", "start")
        check(started["attempt_id"] == aid and started["seal_id"] == seal["seal_id"], "HYP007_FAMILY_IDENTITY")
        with store.locked():
            check(not (store.root/"hyp007-attempts"/aid/"worker-start").exists(), "HYP007_WORKER_ALREADY_STARTED")
            store.record("hyp007-attempts/"+aid, "worker-start", {"attempt_id": aid, "seal_id": seal["seal_id"]})
        defaults_raw = binding(seal["bindings"]["learner_defaults"])
        defaults = decode(defaults_raw)
        runtime = verify_build(binding(seal["bindings"]["build"]), defaults_raw)
        source = Source(seal["prepared"]["config"])
        check(source.inventory == seal["prepared"]["inventory"], "HYP007_SOURCE_CHANGED")
        check(all((source.root/name).stat().st_mtime <= utc(seal["sealed_at"]).timestamp()
                  for name in source.inventory), "HYP007_OBJECT_AFTER_SEAL")
        files = compile_output(source, seal, store, aid, defaults)
        check(sum(map(len,files.values())) <= MAX_OUTPUT, "HYP007_OUTPUT_LIMIT")
        with store.locked():
            store._publish("hyp007-attempts/"+aid, "output", files, file_limit=MAX_FILE)
    except Exception as exc:
        code = exc.code if isinstance(exc, DiagnosticError) else "HYP007_WORKER_FAILED"
        with store.locked():
            store.record("hyp007-attempts/"+aid, "failure", {"status": "FAILED", "code": code})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
