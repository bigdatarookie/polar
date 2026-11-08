"""Distinct immutable namespaces and nonresetting family write-ahead records."""
import fcntl
import os
import re
import time
import uuid
from contextlib import contextmanager

from .history_bundle import read_file, safe_root
from .history_store import HistoryStore
from .hyp007_contract import (FAMILY, FOLDS, MODELS, MAX_FILE, MAX_OUTPUT,
                              check, canonical, decode, sha, now)

FILES = {"seal.json", "inputs.json", "roster.ndjson", "panel.ndjson", "masks.ndjson",
         "predictions.ndjson", "losses.ndjson", "transforms.json", "models.json", "report.json",
         "resources.json", "fit-slots.json"}


def identifier(value, prefix):
    check(type(value) is str and re.fullmatch(re.escape(prefix)+r"[a-f0-9]{64}", value), "HYP007_INVALID_ID")


def attempt_id(value):
    check(type(value) is str, "HYP007_INVALID_ID")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        check(False, "HYP007_INVALID_ID")
    check(str(parsed) == value and parsed.version == 4, "HYP007_INVALID_ID")


class DiagnosticStore(HistoryStore):
    @contextmanager
    def locked(self):
        fd = os.open(safe_root(self.root)/".hyp007.lock", os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
        try:
            end = time.monotonic()+5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    check(time.monotonic() < end, "HYP007_BUSY")
                    time.sleep(.02)
            yield
        finally:
            os.close(fd)

    def record(self, parent, name, data):
        self._publish(parent, name, {"record.json": canonical(data)}, file_limit=MAX_FILE)

    def read_record(self, parent, name):
        raw = read_file(safe_root(self.root), parent+"/"+name+"/record.json", limit=MAX_FILE)
        data = decode(raw)
        check(canonical(data) == raw, "HYP007_RECORD_CANONICAL")
        directory = self.root/parent/name
        check({p.name for p in directory.iterdir()} == {"record.json"}, "HYP007_FILE_SET")
        return data

    def prepare(self, prepared):
        identifier(prepared["prepare_id"], "")
        with self.locked():
            self.record("hyp007-preparations", prepared["prepare_id"], prepared)

    def begin(self, seal, aid):
        attempt_id(aid)
        with self.locked():
            family = self.root/"hyp007-families"/FAMILY
            check(not family.exists() and not family.is_symlink(), "HYP007_FAMILY_ALREADY_STARTED")
            started = {"schema": "polar.hyp007-attempt-start/1", "attempt_id": aid, "family": FAMILY,
                       "seal_id": seal["seal_id"], "sealed_at": seal["sealed_at"], "started_at": now(),
                       "slots": [{"fold": f, "model": m, "status": "NOT_RUN"} for f in FOLDS for m in MODELS]}
            # Family write is first: even a crash between these publications fails closed.
            self.record("hyp007-families/"+FAMILY, "start", started)
            self.record("hyp007-attempts/"+aid, "start", started)
        return started

    def start_slot(self, aid, ordinal):
        check(type(ordinal) is int and 0 <= ordinal < 9, "HYP007_SLOT_LIMIT")
        with self.locked():
            started = self.read_record("hyp007-families/"+FAMILY, "start")
            check(started["attempt_id"] == aid, "HYP007_FAMILY_IDENTITY")
            check(not (self.root/"hyp007-families"/FAMILY/"finish").exists(), "HYP007_FAMILY_FINISHED")
            for prior in range(ordinal):
                receipt = self.read_record("hyp007-families/"+FAMILY+"/slots/"+str(prior), "finish")
                check(receipt["status"] in ("SUCCESS", "SUCCESS_NATIVE_CONSTANT"), "HYP007_PRIOR_SLOT_FAILED")
            parent = "hyp007-families/"+FAMILY+"/slots/"+str(ordinal)
            check(not (self.root/parent/"start").exists(), "HYP007_SLOT_CONSUMED")
            row = {"schema": "polar.hyp007-slot-start/1", "attempt_id": aid, "ordinal": ordinal,
                   "fold": FOLDS[ordinal//3], "model": MODELS[ordinal%3], "started_at": now()}
            self.record(parent, "start", row)
            return row

    def finish_slot(self, aid, ordinal, status, model_hash=None, code=None):
        with self.locked():
            parent = "hyp007-families/"+FAMILY+"/slots/"+str(ordinal)
            start = self.read_record(parent, "start")
            check(start["attempt_id"] == aid and status in ("SUCCESS", "SUCCESS_NATIVE_CONSTANT", "FAILED"),
                  "HYP007_SLOT_IDENTITY")
            self.record(parent, "finish", {"schema": "polar.hyp007-slot-finish/1", "attempt_id": aid,
                        "ordinal": ordinal, "start_sha256": sha(canonical(start)), "status": status,
                        "model_sha256": model_hash, "code": code, "finished_at": now()})

    def slots(self, aid):
        rows = []
        for ordinal in range(9):
            parent = "hyp007-families/"+FAMILY+"/slots/"+str(ordinal)
            path = self.root/parent
            row = {"ordinal": ordinal, "fold": FOLDS[ordinal//3], "model": MODELS[ordinal%3],
                   "status": "NOT_RUN", "start": None, "finish": None}
            if (path/"start").exists():
                start = self.read_record(parent, "start")
                check(start["attempt_id"] == aid and start["ordinal"] == ordinal, "HYP007_SLOT_IDENTITY")
                row.update(status="STARTED_UNFINALIZED", start=start)
                if (path/"finish").exists():
                    finish = self.read_record(parent, "finish")
                    check(finish["attempt_id"] == aid and finish["start_sha256"] == sha(canonical(start)),
                          "HYP007_SLOT_IDENTITY")
                    row.update(status=finish["status"], finish=finish)
            rows.append(row)
        return rows

    def finish(self, aid, status, code, resources, eid=None, manifest_hash=None):
        with self.locked():
            start = self.read_record("hyp007-attempts/"+aid, "start")
            receipt = {"schema": "polar.hyp007-attempt-finish/1", "attempt_id": aid, "status": status,
                       "start_sha256": sha(canonical(start)), "code": code, "resources": resources,
                       "experiment_id": eid, "manifest_sha256": manifest_hash,
                       "finished_at": now(), "slots": self.slots(aid)}
            self.record("hyp007-families/"+FAMILY, "finish", receipt)
            self.record("hyp007-attempts/"+aid, "finish", receipt)
        return receipt

    def attempt(self, aid):
        attempt_id(aid)
        start = self.read_record("hyp007-attempts/"+aid, "start")
        check(start["attempt_id"] == aid and start["family"] == FAMILY, "HYP007_ATTEMPT_IDENTITY")
        finish = None
        if (self.root/"hyp007-attempts"/aid/"finish").exists():
            finish = self.read_record("hyp007-attempts/"+aid, "finish")
            check(finish["start_sha256"] == sha(canonical(start)), "HYP007_ATTEMPT_IDENTITY")
        return {"schema": "polar.hyp007-attempt/1", "attempt_id": aid,
                "status": finish["status"] if finish else "UNFINALIZED", "started": start,
                "receipt": finish, "slots": self.slots(aid)}

    def publish(self, eid, files):
        identifier(eid, "hyp007-")
        check(set(files) == FILES and sum(map(len, files.values())) <= MAX_OUTPUT, "HYP007_FILE_SET")
        manifest = {"schema": "polar.hyp007-manifest/1", "experiment_id": eid,
                    "files": {k: {"sha256": sha(v), "bytes": len(v)} for k,v in files.items()}}
        files = {**files, "manifest.json": canonical(manifest)}
        with self.locked():
            self._publish("hyp007-experiments", eid, files, file_limit=MAX_FILE)
        return manifest

    def report(self, eid):
        identifier(eid, "hyp007-")
        root = self.root/"hyp007-experiments"/eid
        manifest = decode(read_file(safe_root(self.root), "hyp007-experiments/"+eid+"/manifest.json", limit=MAX_FILE))
        check(manifest["schema"] == "polar.hyp007-manifest/1" and manifest["experiment_id"] == eid and
              set(manifest["files"]) == FILES, "HYP007_MANIFEST_IDENTITY")
        check({p.name for p in root.iterdir()} == FILES|{"manifest.json"}, "HYP007_FILE_SET")
        files = {}
        for name, info in manifest["files"].items():
            raw = read_file(root, name, limit=MAX_FILE)
            check(len(raw) == info["bytes"] and sha(raw) == info["sha256"], "HYP007_ARTIFACT_HASH")
            files[name] = raw
        check(sum(map(len,files.values())) <= MAX_OUTPUT, "HYP007_OUTPUT_LIMIT")
        seal = decode(files["seal.json"])
        from .hyp007_service import validate_seal
        check(not validate_seal(seal), "HYP007_SEAL_NOT_BOUND")
        check(eid == "hyp007-"+seal["seal_id"], "HYP007_EXPERIMENT_IDENTITY")
        report = decode(files["report.json"])
        check(report["experiment_id"] == eid, "HYP007_REPORT_IDENTITY")
        roster = [decode(line) for line in files["roster.ndjson"].splitlines()]
        panel = [decode(line) for line in files["panel.ndjson"].splitlines()]
        masks = [decode(line) for line in files["masks.ndjson"].splitlines()]
        predictions = [decode(line) for line in files["predictions.ndjson"].splitlines()]
        losses = [decode(line) for line in files["losses.ndjson"].splitlines()]
        check(roster == seal["prepared"]["roster"] and [r["key"] for r in panel] == [r["key"] for r in roster],
              "HYP007_ROSTER_INTEGRITY")
        keys = [r["key"] for r in roster]
        check(len(keys) == len(set(keys)) <= 100000 and
              [(r["fold"],r["key"]) for r in masks] == [(f,k) for f in FOLDS for k in keys], "HYP007_MASK_INTEGRITY")
        required_predictions = {(m["fold"],m["key"],name) for m in masks if m["M_score"] for name in MODELS}
        actual_predictions = [(p["fold"],p["key"],p["model"]) for p in predictions]
        check(len(actual_predictions) == len(required_predictions) and set(actual_predictions) == required_predictions,
              "HYP007_PREDICTION_INTEGRITY")
        required_losses = {(m["fold"],m["key"]) for m in masks if m["M_eval"]}
        check(len(losses) == len(required_losses) and {(r["fold"],r["key"]) for r in losses} == required_losses,
              "HYP007_LOSS_INTEGRITY")
        slots = decode(files["fit-slots.json"])
        check(len(slots) == 9 and all(s["status"] in ("SUCCESS", "SUCCESS_NATIVE_CONSTANT") for s in slots),
              "HYP007_SLOT_INTEGRITY")
        models = decode(files["models.json"])
        check(set(models) == {str(f)+":"+m for f in FOLDS for m in MODELS}, "HYP007_MODEL_INTEGRITY")
        for ordinal,slot in enumerate(slots):
            check(slot["ordinal"] == ordinal and slot["fold"] == FOLDS[ordinal//3] and
                  slot["model"] == MODELS[ordinal%3] and
                  sha(canonical(models[str(slot["fold"])+":"+slot["model"]])) == slot["finish"]["model_sha256"],
                  "HYP007_MODEL_INTEGRITY")
        check(decode(files["inputs.json"]) == seal["prepared"]["inventory"], "HYP007_INPUT_INTEGRITY")
        check(report["real_fit_invocations"] == 9 and all(report["pooled"][m]["n"] == len(losses) for m in MODELS),
              "HYP007_REPORT_INTEGRITY")
        return {"schema": "polar.hyp007-report/1", "experiment_id": eid, "manifest": manifest, "report": report}
