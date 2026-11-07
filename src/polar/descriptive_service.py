"""One explicit synchronous operation; physical attempts never redefine semantic identities."""
import os
import platform
import re
import sys
import time
import uuid
from datetime import datetime, timezone

from .descriptive import code_projection, compile_files, configuration, identity
from .descriptive_store import DescriptiveStore
from .history_bundle import HistoryError, canonical, decode, sha
from .history_calendar import reference_calendar
from .history_queries import integer, page_rows


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class DescriptiveService:
    def __init__(self, registry, calendar_dir, store=None):
        self.registry, self.calendar_dir = registry, calendar_dir
        self.store = store or DescriptiveStore(registry.store.root, registry.store.limit)

    def run(self, raw_config):
        # Malformed requests are not physical invocations. A validated invocation always records a start first.
        config = configuration(raw_config)
        aid = str(uuid.uuid4())
        source_code = code_projection()
        source_commit = os.environ.get("POLAR_SOURCE_COMMIT", "")
        started = {"schema":"polar.descriptive-attempt-start/1","attempt_id":aid,"started_at":utc(),
            "config":config,"config_id":identity("config",config),"code_id":identity("code",source_code),"code":source_code,
            "environment":{"python":sys.version,"implementation":platform.python_implementation(),
                "platform":sys.platform,"machine":platform.machine(),
                "source_commit":source_commit if re.fullmatch(r"[a-f0-9]{40}", source_commit) else None}}
        begin, cpu = time.monotonic_ns(), time.process_time_ns()
        with self.store.locked():
            self.store.start_attempt(aid, started)
            eid, manifest_hash, status, error_code = None, None, "FAILED", None
            try:
                summary, bundle = self.registry.load_revision(config["dataset_id"], config["dataset_revision"])
                sessions, calendar = reference_calendar(self.calendar_dir, summary, bundle)
                candidate, values = compile_files(config, summary, bundle, sessions, calendar)
                if decode(values["experiment.json"])["code_id"] != started["code_id"]:
                    raise HistoryError("DESCRIPTIVE_CODE_CHANGED")
                manifest_hash = self.store.publish(candidate, values)
                eid, status = candidate, "COMPLETED"
            except BaseException as exc:
                error_code = exc.code if isinstance(exc, HistoryError) else "DESCRIPTIVE_EXECUTION_FAILED"
                if not isinstance(exc, Exception):
                    status, error_code = "INTERRUPTED", "DESCRIPTIVE_INTERRUPTED"
            receipt = {"schema":"polar.descriptive-attempt-receipt/1","attempt_id":aid,
                "started_sha256":sha(canonical(started)),"completed_at":utc(),"status":status,
                "experiment_id":eid,"manifest_sha256":manifest_hash if status == "COMPLETED" else None,
                "error_code":error_code,"elapsed_ns":time.monotonic_ns()-begin,"cpu_ns":time.process_time_ns()-cpu}
            try:
                self.store.finish_attempt(aid, receipt)
            except (HistoryError, OSError):
                return {"status":"UNFINALIZED","attempt_id":aid,"experiment_id":eid,
                        "code":"DESCRIPTIVE_RECEIPT_PUBLICATION_FAILED"}
        return {"status":status,"attempt_id":aid,"experiment_id":eid,
                "manifest_sha256":receipt["manifest_sha256"],"receipt_sha256":sha(canonical(receipt)),
                "code":error_code}

    def experiment(self, experiment_id):
        values = self.store.verify(experiment_id)
        return {**decode(values["experiment.json"]),"schema_version":"polar.history-experiment/1",
            "manifest_sha256":sha(values["manifest.json"]),"config":decode(values["config.json"]),
            "counts":decode(values["counts.json"])["assets"],"inputs":decode(values["inputs.json"]),
            "reference_metadata":decode(values["reference-metadata.json"])["assets"],
            "manifest":decode(values["manifest.json"]),"code":decode(values["code.json"]),
            "protocol":decode(values["protocol.json"])}

    def view(self, view_id):
        eid, metadata, values = self.store.view(view_id)
        return {**metadata,"schema_version":"polar.history-view/1","experiment_id":eid,
                "manifest_sha256":sha(values["manifest.json"]),"config":decode(values["config.json"])}

    def rows(self, view_id, codec, limit="1000", cursor=None):
        count = integer(limit, 1, 1000)
        eid, metadata, values = self.store.view(view_id)
        rows = [decode(line) for line in values[metadata["table"]].splitlines()]
        request = sha(canonical({"projection":"descriptive-rows/1","view_id":view_id,"limit":count,
                                  "rows_sha256":metadata["rows_sha256"],"manifest_sha256":sha(values["manifest.json"])}))
        def make(items, next_cursor, complete):
            return {"schema_version":"polar.history-view-rows/1","view_id":view_id,"experiment_id":eid,
                    "request_identity":request,"rows_sha256":metadata["rows_sha256"],"rows":items,
                    "row_count":len(items),"next_cursor":next_cursor,"window_complete":complete}
        return page_rows(rows, [row["instrument_id"]+":"+row["session_date"] for row in rows], count, cursor,
                         "descriptive-rows/1", request, make, codec)
