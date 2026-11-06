import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .codec import canonical, digest


class ArtifactError(Exception):
    pass


def storage_used(root):
    return sum(p.stat().st_size for p in Path(root).rglob("*") if p.is_file())


def verify(directory):
    directory = Path(directory)
    manifest = json.loads((directory/"manifest.json").read_bytes())
    expected = {"report.json", "nav.parquet", "fills.parquet", "inputs.json", "environment.json"}
    if set(manifest["files"]) != expected:
        raise ArtifactError("MANIFEST_FILE_SET")
    for name, h in manifest["files"].items():
        p = directory/name
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            raise ArtifactError("ARTIFACT_HASH_MISMATCH")
    return manifest


class ArtifactStore:
    def __init__(self, root, limit=4*1024**3):
        self.root,self.limit = Path(root),limit

    def check(self, writable=False):
        if not self.root.is_dir():
            raise ArtifactError("ARTIFACT_ROOT_MISSING")
        if storage_used(self.root) >= self.limit:
            raise ArtifactError("ARTIFACT_STORAGE_LIMIT")
        if writable:
            with tempfile.TemporaryFile(dir=self.root) as f:
                f.write(b"ready")
                f.flush()
                os.fsync(f.fileno())
        elif not os.access(self.root,os.R_OK | os.X_OK):
            raise ArtifactError("ARTIFACT_ROOT_UNREADABLE")

    def publish(self, run_id, attempt_id, report, inputs, environment):
        self.check(writable=True)
        parent = self.root/str(run_id)
        parent.mkdir(exist_ok=True)
        final = parent/str(attempt_id)
        if final.exists():
            raise ArtifactError("IMMUTABLE_ARTIFACT_EXISTS")
        staging = Path(tempfile.mkdtemp(prefix=".partial-",dir=parent))
        try:
            for name,body in [("report.json",report),("inputs.json",inputs),("environment.json",environment)]:
                (staging/name).write_bytes(canonical(body))
            for name,rows in [("nav",report["nav"]),("fills",report["fills"])]:
                # Values remain strings in Parquet, preserving exact Decimal values.
                table = pa.Table.from_pylist(rows) if rows else pa.table({"empty":pa.array([],type=pa.string())})
                pq.write_table(table, staging/(name+".parquet"),compression="zstd")
            files = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in staging.iterdir()}
            manifest = {"schema_version":"polar.manifest/1","run_id":str(run_id),"attempt_id":str(attempt_id),
                        "report_hash":digest(report),"files":files}
            (staging/"manifest.json").write_bytes(canonical(manifest))
            verify(staging)
            if storage_used(self.root) > self.limit:
                raise ArtifactError("ARTIFACT_STORAGE_LIMIT")
            for p in staging.iterdir():
                with p.open("rb") as f:
                    os.fsync(f.fileno())
                p.chmod(0o444)
            os.rename(staging,final)
            # Persist the rename before PostgreSQL points to the completed output.
            fd = os.open(parent,os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            return str(final.relative_to(self.root))
        finally:
            if staging.exists():
                shutil.rmtree(staging)  # exact unpublished directory owned by this call

    def directory(self, ref):
        p = (self.root/ref).resolve()
        if not p.is_relative_to(self.root.resolve()) or len(Path(ref).parts) != 2:
            raise ArtifactError("INVALID_ARTIFACT_REFERENCE")
        return p

    def report(self, ref):
        directory = self.directory(ref)
        verify(directory)
        return json.loads((directory/"report.json").read_bytes())
