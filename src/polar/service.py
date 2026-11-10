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

    def _research(self):
        from .research_results import ResearchResults
        return ResearchResults(self.artifacts.root, self.artifacts.limit)

    def _research_engine(self):
        from .ci_research_service import ResearchService
        return ResearchService(self.artifacts.root, self.artifacts.limit)

    def research_preflight(self, config):
        from .ci_research_service import operation_binding
        from .gym_contract import canonical, sha
        plan, pins = self._research_engine().prepare(config)
        return {"schema": "polar.ci-research-preflight/1", "status": "READY_FOR_BOUND_OPERATION",
                "profile_id": config["profile_id"], "pins": pins, "nav_points": len(plan["grid"]),
                "decisions": len(plan["decisions"]), "strategy_execution": "NOT_RUN",
                "operation_binding_sha256": sha(canonical(operation_binding(config, pins)))}

    def research_config(self, seed):
        from .ci_research_service import config_from_seed
        return config_from_seed(seed)

    def research_run(self, config):
        return self._research_engine().run(config)

    def research_recompute(self, semantic_id):
        return self._research_engine().recompute(semantic_id)

    def research_publish(self, result):
        return self._research_call("publish", result)

    def research_review(self, review):
        return self._research_call("review", review)

    def research_catalog(self, limit=10, offset=0):
        return self._research_call("catalog", limit, offset)

    def research_result(self, result_id):
        return self._research_call("read", result_id)

    def _research_call(self, operation, *args):
        from .history_bundle import HistoryError
        from .research_results import ResearchError
        try:
            return getattr(self._research(), operation)(*args)
        except HistoryError:
            raise ResearchError("RESEARCH_INTEGRITY_ERROR") from None

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

    def _imports(self, fixture=False, raw_sip=False, raw_profile='first-unit'):
        from .import_service import ImportService
        from .import_store import ImportStore
        return ImportService(ImportStore(self.artifacts.root,self.artifacts.limit,fixture=fixture,
                                        raw_sip=raw_sip,raw_profile=raw_profile))

    def _import_plan_service(self,plan_id):
        if plan_id.startswith(('rawsipaggregate-','rawsipaggregatefixture-')):
            return self._imports(plan_id.startswith('rawsipaggregatefixture-'),True,'remaining3490')
        return self._imports(plan_id.startswith(("fixture-","rawsipfixture-")),
                             plan_id.startswith(("rawsip-","rawsipfixture-")))

    def import_plan(self, config):
        if config.get('adapter')=='alpaca-raw-sip-remaining/1':
            return self._imports(config.get('mode')=='fixture',True,'remaining3490').plan(config)
        return self._imports(config.get("mode")=="fixture",config.get("adapter")=="alpaca-raw-sip-first-unit/1").plan(config)

    def import_cache_import(self, config, fixture=False):
        from .import_migration import migration
        return migration(config,self._imports(fixture).store)

    def import_status(self, plan_id):
        return self._import_plan_service(plan_id).status(plan_id)

    def import_result(self, plan_id, job_id):
        return self._import_plan_service(plan_id).result(plan_id,job_id)

    def import_execute(self, plan_id, *, fixture=None, network=False, attempt_id=None, scope=None):
        return self._import_plan_service(plan_id).execute(plan_id,fixture=fixture,network=network,attempt_id=attempt_id,scope=scope)

    def import_attempt_path(self, plan_id, attempt_id):
        return self._import_plan_service(plan_id).attempt_path(plan_id,attempt_id)

    def import_attempts(self, plan_id):
        return self._import_plan_service(plan_id).attempts(plan_id)

    def import_control(self, plan_id, action):
        return self._import_plan_service(plan_id).control(plan_id,action)

    def import_terminal(self, plan_id, attempt_id, manifest_sha256):
        from .import_contract import require
        service = self._import_plan_service(plan_id)
        service.load(plan_id)
        manifest,state = service.terminal(attempt_id,manifest_sha256)
        require(manifest["plan_id"]==plan_id,"IMPORT_TERMINAL_IDENTITY")
        return {"schema":"polar.import-terminal-read/1","manifest":manifest,"state":state}

    def import_consume(self, plan_id, attempt_id, manifest_sha256, assessment):
        return self._import_plan_service(plan_id).consume(plan_id,attempt_id,manifest_sha256,assessment)

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

    def _hyp007_capability(self):
        from .capability_service import CapabilityService
        return CapabilityService(self.artifacts.root, self.artifacts.limit)

    def hyp007_capability_prepare(self, config):
        return self._hyp007_capability().prepare(config)

    def hyp007_capability_run(self, sealed_config):
        return self._hyp007_capability().run(sealed_config)

    def hyp007_capability_replay(self, sealed_config, packet_id):
        return self._hyp007_capability().replay(sealed_config, packet_id)

    def hyp007_capability_attempt(self, attempt_id):
        return self._hyp007_capability().attempt(attempt_id)

    def hyp007_capability_report(self, packet_id):
        return self._hyp007_capability().report(packet_id)

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
