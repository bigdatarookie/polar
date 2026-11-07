"""Immutable descriptive manifests/tables and append-only physical attempt receipts."""
import fcntl
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .history_bundle import canonical, decode, read_file, require, safe_root, sha
from .history_store import HistoryStore, fsync_directory
from .descriptive import configuration, identity, protocol

MAX_OUTPUT = 32*1024**2  # finite artifact read/write bound per experiment, not a storage subquota


def semantic_id(value, prefix):
    require(type(value) is str and re.fullmatch(re.escape(prefix)+r"-[a-f0-9]{64}", value), "DESCRIPTIVE_INVALID_ID")


def attempt_id(value):
    require(type(value) is str, "DESCRIPTIVE_INVALID_ID")
    try: parsed = uuid.UUID(value)
    except ValueError:
        require(False, "DESCRIPTIVE_INVALID_ID")
    require(str(parsed) == value and parsed.version == 4, "DESCRIPTIVE_INVALID_ID")


class DescriptiveStore(HistoryStore):
    @contextmanager
    def locked(self):
        root = safe_root(self.root)
        fd = os.open(root/".history.lock", os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
        try:
            deadline = time.monotonic()+5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    require(time.monotonic() < deadline, "DESCRIPTIVE_BUSY")
                    time.sleep(.02)
            yield
        finally: os.close(fd)

    def publish(self, eid, files):
        semantic_id(eid, "experiment")
        require(sum(map(len, files.values())) <= MAX_OUTPUT, "DESCRIPTIVE_OUTPUT_LIMIT")
        self._publish("history-experiments", eid, files, file_limit=MAX_OUTPUT)
        self.verify(eid)
        for kind in ("feature", "label", "reference"):
            view_id = decode(files[kind+"-view.json"])["view_id"]
            self._publish("history-views", view_id, {"pointer.json":canonical({"experiment_id":eid,"kind":kind,"view_id":view_id})})
        return sha(files["manifest.json"])

    def _read(self, namespace, name, filename, limit):
        return read_file(safe_root(self.root), namespace+"/"+name+"/"+filename, limit=limit)

    def start_attempt(self, aid, started):
        attempt_id(aid)
        self._publish("history-experiment-attempts", aid, {"started.json":canonical(started)})

    def finish_attempt(self, aid, receipt):
        attempt_id(aid)
        raw = canonical(receipt)
        require(len(raw) <= 65536 and self.used()+len(raw) <= self.limit, "HISTORY_STORAGE_LIMIT")
        directory = self.root/"history-experiment-attempts"/aid
        safe_root(directory)
        target = directory/"receipt.json"
        temporary = directory/(".receipt-"+str(uuid.uuid4()))
        try:
            with temporary.open("xb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            temporary.chmod(0o400)
            os.link(temporary, target, follow_symlinks=False)  # atomic no-clobber publication
            fsync_directory(directory)
        finally:
            if temporary.exists(): temporary.unlink()  # exact unpublished file owned by this invocation only

    def attempt(self, aid):
        attempt_id(aid)
        root = self.root/"history-experiment-attempts"/aid
        require(root.is_dir() and not root.is_symlink(), "DESCRIPTIVE_NOT_FOUND")
        started = decode(self._read("history-experiment-attempts", aid, "started.json", 65536))
        require(started["attempt_id"] == aid and started["schema"] == "polar.descriptive-attempt-start/1",
                "DESCRIPTIVE_ATTEMPT_INTEGRITY")
        final = root/"receipt.json"
        if not final.exists():
            require(not final.is_symlink(), "DESCRIPTIVE_ATTEMPT_INTEGRITY")
            return {"schema":"polar.descriptive-attempt/1","attempt_id":aid,"status":"UNFINALIZED",
                    "started":started,"receipt":None,"meaning":"RUNNING_OR_INTERRUPTED_NOT_RECONCILED"}
        raw = self._read("history-experiment-attempts", aid, "receipt.json", 65536)
        receipt = decode(raw)
        require(receipt["attempt_id"] == aid and receipt["started_sha256"] == sha(canonical(started)),
                "DESCRIPTIVE_ATTEMPT_INTEGRITY")
        if receipt["status"] == "COMPLETED":
            values = self.verify(receipt["experiment_id"])
            require(sha(values["manifest.json"]) == receipt["manifest_sha256"], "DESCRIPTIVE_ATTEMPT_INTEGRITY")
        return {"schema":"polar.descriptive-attempt/1","attempt_id":aid,"status":receipt["status"],
                "started":started,"receipt":receipt,"receipt_sha256":sha(raw)}

    def verify(self, eid):
        semantic_id(eid, "experiment")
        root = self.root/"history-experiments"/eid
        require(root.is_dir() and not root.is_symlink(), "DESCRIPTIVE_NOT_FOUND")
        manifest_raw = self._read("history-experiments", eid, "manifest.json", 65536)
        manifest = decode(manifest_raw)
        expected = set(protocol()["files"])
        require(manifest["schema"] == "polar.descriptive-manifest/1" and manifest["experiment_id"] == eid and
                set(manifest["files"]) == expected-{"manifest.json"}, "DESCRIPTIVE_MANIFEST_INTEGRITY")
        files = {"manifest.json":manifest_raw}
        for name, record in manifest["files"].items():
            value = self._read("history-experiments", eid, name, MAX_OUTPUT)
            require(len(value) == record["bytes"] and sha(value) == record["sha256"], "DESCRIPTIVE_OBJECT_INTEGRITY")
            files[name] = value
            require(sum(map(len,files.values())) <= MAX_OUTPUT, "DESCRIPTIVE_OUTPUT_LIMIT")
        actual = set()
        for file in root.rglob("*"):
            require(not file.is_symlink(), "HISTORY_SYMLINK")
            if file.is_file(): actual.add(str(file.relative_to(root)))
        require(actual == expected, "DESCRIPTIVE_FILE_SET")
        require(files["protocol.json"] == canonical(protocol()), "DESCRIPTIVE_PROTOCOL_INTEGRITY")
        definition = protocol()
        for name, fields in definition["metadata_fields"].items():
            value = decode(files[name])
            require(type(value) is dict and set(value) == set(fields) and canonical(value) == files[name],
                    "DESCRIPTIVE_FIELD_SET")
        cfg = decode(files["config.json"])
        require(configuration({k:v for k,v in cfg.items() if k != "schema"}) == cfg, "DESCRIPTIVE_INPUT_IDENTITY")
        inputs, code = decode(files["inputs.json"]), decode(files["code.json"])
        pid, cid, source_id, iid = (identity(prefix, value) for prefix,value in
            (("protocol",protocol()),("config",cfg),("code",code),("input",inputs)))
        require((inputs["protocol_id"],inputs["config_id"],inputs["code_id"]) == (pid,cid,source_id), "DESCRIPTIVE_INPUT_IDENTITY")
        for key in ("dataset_id","dataset_revision","import_receipt_id","manifest_sha256"):
            require(inputs[key] == cfg[key], "DESCRIPTIVE_INPUT_IDENTITY")
        view_ids = {}
        for kind,table in (("feature","features.ndjson"),("label","labels.ndjson"),("reference","reference.ndjson")):
            view = decode(files[kind+"-view.json"])
            vid = identity(kind+"-view", {k:v for k,v in view.items() if k != "view_id"})
            require(view["view_id"] == vid and (view["input_id"],view["protocol_id"],view["config_id"],view["code_id"]) ==
                    (iid,pid,cid,source_id) and view["table"] == table and view["rows_sha256"] == sha(files[table]),
                    "DESCRIPTIVE_VIEW_INTEGRITY")
            metadata = "reference-metadata.json" if kind == "reference" else "counts.json"
            require(view["metadata_sha256"] == sha(files[metadata]), "DESCRIPTIVE_VIEW_INTEGRITY")
            rows = [decode(line) for line in files[table].splitlines()]
            require(len(rows) == view["row_count"] <= 20000, "DESCRIPTIVE_ROW_LIMIT")
            fields = definition[kind+"_fields"]
            require(all(set(row) == set(fields) for row in rows) and
                    b"".join(canonical(row)+b"\n" for row in rows) == files[table], "DESCRIPTIVE_FIELD_SET")
            keys = [(row["instrument_id"],row["session_date"]) for row in rows]
            require(keys == sorted(set(keys)), "DESCRIPTIVE_ROW_ORDER")
            view_ids[kind] = vid
        experiment = decode(files["experiment.json"])
        require(experiment["experiment_id"] == eid == identity("experiment",{k:v for k,v in experiment.items() if k != "experiment_id"}) and
                (experiment["input_id"],experiment["protocol_id"],experiment["config_id"],experiment["code_id"]) == (iid,pid,cid,source_id) and
                all(experiment[kind+"_view_id"] == vid for kind,vid in view_ids.items()) and
                experiment["counts_sha256"] == sha(files["counts.json"]), "DESCRIPTIVE_EXPERIMENT_INTEGRITY")
        return files

    def view(self, vid):
        kind = next((k for k in ("feature","label","reference") if type(vid) is str and vid.startswith(k+"-view-")), None)
        require(kind is not None, "DESCRIPTIVE_INVALID_ID")
        semantic_id(vid, kind+"-view")
        root = self.root/"history-views"/vid
        require(root.is_dir() and not root.is_symlink(), "DESCRIPTIVE_NOT_FOUND")
        pointer = decode(self._read("history-views", vid, "pointer.json", 65536))
        require(pointer["view_id"] == vid and pointer["kind"] == kind, "DESCRIPTIVE_VIEW_INTEGRITY")
        files = self.verify(pointer["experiment_id"])
        view = decode(files[kind+"-view.json"])
        require(view["view_id"] == vid, "DESCRIPTIVE_VIEW_INTEGRITY")
        return pointer["experiment_id"], view, files
