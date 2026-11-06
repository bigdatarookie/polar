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

    def ready(self):
        self.registry.check()
        self.artifacts.check()
        return {"status":"READY","schema_version":1,"storage_hard_quota":"NOT_ENFORCED",
                "blinding":"BLINDING_NOT_ENFORCED"}

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
