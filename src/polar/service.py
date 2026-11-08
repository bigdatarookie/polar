import json
import hashlib

from .artifacts import ArtifactStore
from .registry import Registry, Conflict
from .codec import digest
from .data_quality import InspectionError, inspect_dataset


class DatasetIntegrityError(Exception):
    """Retained dataset does not match its immutable registration binding."""

    def __init__(self):
        super().__init__("DATASET_INTEGRITY_ERROR")


class Service:
    def __init__(self, settings):
        self.registry = Registry(settings)
        self.artifacts = ArtifactStore(settings.artifacts,settings.storage_bytes)
        from .history_registry import HistoryRegistry
        self.history_registry = HistoryRegistry(settings)
        self.history_cursor_key_file = settings.history_cursor_key_file
        self.history_calendar_dir = settings.history_calendar_dir or settings.artifacts/"history-calendar"

    def history_read(self, operation, **kwargs):
        import psycopg
        from .history_bundle import HistoryError
        from .history_cursor import HistoryCursorError
        from .history_queries import HistoryQueries, HistoryReadError
        try:
            return getattr(HistoryQueries(self.history_registry, self.history_cursor_key_file, self.history_calendar_dir), operation)(**kwargs)
        except HistoryCursorError as exc:
            raise HistoryReadError(exc.code, exc.status) from None
        except HistoryError as exc:
            status = (404 if exc.code in {"HISTORY_REVISION_NOT_FOUND", "DESCRIPTIVE_NOT_FOUND", "DESCRIPTIVE_ASSET_NOT_FOUND"} else
                      422 if exc.code == "HISTORY_INVALID_CURSOR" or exc.code.startswith("DESCRIPTIVE_INVALID") else
                      503 if exc.code in {"HISTORY_SCHEMA_MISSING", "HISTORY_SCHEMA_MISMATCH", "HISTORY_SCHEMA_PARTIAL",
                                          "HISTORY_DIRECTORY_MISSING"} else 409)
            raise HistoryReadError(exc.code, status) from None
        except (psycopg.Error, OSError):
            raise HistoryReadError("HISTORY_DEPENDENCY_UNAVAILABLE", 503) from None
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise HistoryReadError("HISTORY_RETAINED_RECORD_INVALID", 409) from None

    def history_experiment_run(self, config):
        from .descriptive_service import DescriptiveService
        from .descriptive_store import DescriptiveStore
        # Same retained-storage admission convention as registration/legacy; no global-quota claim.
        with self.registry.connect() as db:
            db_bytes = db.execute("SELECT pg_database_size(current_database()) AS n").fetchone()["n"]
        store = DescriptiveStore(self.artifacts.root, self.artifacts.limit-db_bytes-1024**2)
        return DescriptiveService(self.history_registry, self.history_calendar_dir, store).run(config)

    def _hyp007(self):
        from .hyp007_service import DiagnosticService
        from .hyp007_store import DiagnosticStore
        return DiagnosticService(DiagnosticStore(self.artifacts.root, self.artifacts.limit))

    def hyp007_diagnostic_prepare(self, config):
        return self._hyp007().prepare(config)

    def hyp007_diagnostic_run(self, sealed_manifest):
        return self._hyp007().run(sealed_manifest)

    def hyp007_diagnostic_attempt(self, attempt_id):
        return self._hyp007().attempt(attempt_id)

    def hyp007_diagnostic_report(self, experiment_id):
        return self._hyp007().report(experiment_id)

    def _gym(self):
        from .gym_service import GymService
        from .gym_store import GymStore
        return GymService(GymStore(self.artifacts.root, self.artifacts.limit))

    def gym_preflight(self, config):
        return self._gym().preflight(config)

    def gym_run(self, config):
        return self._gym().run(config)

    def gym_replay(self, config, experiment_id):
        return self._gym().replay(config, experiment_id)

    def gym_attempt(self, attempt_id):
        return self._gym().attempt(attempt_id)

    def gym_report(self, experiment_id):
        return self._gym().report(experiment_id)

    def ready(self):
        self.registry.check()
        self.artifacts.check()
        return {"status":"READY","schema_version":1,"storage_hard_quota":"NOT_ENFORCED",
                "blinding":"BLINDING_NOT_ENFORCED"}

    def ui_datasets(self, limit=10, offset=0):
        return self._ui_call("datasets", limit, offset)

    def ui_dataset(self, dataset_id):
        return self._ui_call("dataset", dataset_id)

    def ui_runs(self, dataset_id, limit=10, offset=0):
        return self._ui_call("runs", dataset_id, limit, offset)

    def ui_run(self, run_id, dataset_id=None):
        return self._ui_call("run", run_id, dataset_id)

    def _ui_call(self, operation, *args):
        from .ui import UIError, UIProjection
        try:
            return getattr(UIProjection(self), operation)(*args)
        except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
            raise UIError("RETAINED_RECORD_INVALID") from None

    def dataset(self, dataset_id):
        row = self.registry.dataset(dataset_id)
        try:
            inspection = inspect_dataset(row["source_bytes"])
            valid = (
                row["id"] == dataset_id == inspection["dataset_id"]
                and row["content_hash"] == inspection["content_hash"] == digest(row["body"])
                and row["source_hash"] == inspection["source_sha256"]
            )
        except (InspectionError, KeyError, TypeError, ValueError, RecursionError):
            raise DatasetIntegrityError() from None
        if not valid:
            raise DatasetIntegrityError()
        return {"id":row["id"], "content_hash":row["content_hash"],
                "source_hash":row["source_hash"], "registered_at":row["registered_at"],
                "inspection":inspection}

    def report(self, run_id):
        run = self.registry.get(run_id)
        if run["state"] != "completed":
            raise Conflict("REPORT_NOT_COMPLETE")
        manifest = self.artifacts.directory(run["artifact_ref"])/"manifest.json"
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != run["artifact_hash"]:
            from .artifacts import ArtifactError
            raise ArtifactError("MANIFEST_HASH_MISMATCH")
        return self.artifacts.report(run["artifact_ref"])

    def compare(self, left, right):
        a,b = self.report(left),self.report(right)
        return {"left":str(left),"right":str(right),"metrics":{"left":a["metrics"],"right":b["metrics"]},
                "status":"DESCRIPTIVE_ONLY","financial_verdict":"NOT_RUN"}
