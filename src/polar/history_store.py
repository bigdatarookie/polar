"""Publish captured content once and immutable receipts separately, before PG references."""
import fcntl
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .history_bundle import (MAX_FILE, HistoryError, canonical, decode, hex_hash, read_file,
                             relative, require, revision_id, safe_root, sha, verify_files)


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class HistoryStore:
    def __init__(self, root, limit):
        self.root, self.limit = Path(root), limit

    @contextmanager
    def locked(self):
        root = safe_root(self.root)
        fd = os.open(root / ".history.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def used(self):
        total = 0
        for path in safe_root(self.root).rglob("*"):
            require(not path.is_symlink(), "HISTORY_SYMLINK")
            if path.is_file():
                total += path.stat().st_size
        return total

    def _directory(self, relative_path):
        path = self.root
        for part in Path(relative(relative_path)).parts:
            path /= part
            require(not path.is_symlink(), "HISTORY_SYMLINK")
            if not path.exists():
                path.mkdir(mode=0o700)
                fsync_directory(path.parent)
            require(path.is_dir(), "HISTORY_DIRECTORY_INVALID")
        return path

    def _publish(self, parent_name, name, files, *, file_limit=MAX_FILE):
        parent = self._directory(parent_name)
        final = parent / name
        require(not final.is_symlink(), "HISTORY_SYMLINK")
        if final.exists():
            actual = {str(p.relative_to(final)) for p in final.rglob("*") if p.is_file()}
            require(all(not p.is_symlink() for p in final.rglob("*")) and actual == set(files),
                    "HISTORY_IMMUTABLE_CONFLICT")
            require(all(read_file(final, key, limit=file_limit) == raw for key, raw in files.items()), "HISTORY_IMMUTABLE_CONFLICT")
            return
        require(self.used() + sum(map(len, files.values())) <= self.limit, "HISTORY_STORAGE_LIMIT")
        staging = Path(tempfile.mkdtemp(prefix=".history-partial-", dir=parent))
        try:
            for key, raw in files.items():
                destination = staging / relative(key)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with destination.open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                destination.chmod(0o400)
                require(read_file(staging, key, limit=file_limit) == raw, "HISTORY_STAGING_HASH")
            for directory in sorted((p for p in staging.rglob("*") if p.is_dir()),
                                    key=lambda p: len(p.parts), reverse=True):
                fsync_directory(directory)
            fsync_directory(staging)
            require(self.used() <= self.limit, "HISTORY_STORAGE_LIMIT")
            # Caller holds the root registration lock; no overwrite of another publisher.
            require(not final.exists(), "HISTORY_IMMUTABLE_CONFLICT")
            os.rename(staging, final)
            fsync_directory(parent)
        finally:
            if staging.exists():
                shutil.rmtree(staging)  # only this call's unpublished exact directory

    def publish_locked(self, bundle):
        """Caller holds locked(); DB must not point here until this returns."""
        content = {k: v for k, v in bundle.files.items() if k in bundle.content_files}
        receipt = {k: v for k, v in bundle.files.items() if k not in bundle.content_files}
        inventory = {k: {"sha256": sha(v), "bytes": len(v),
                          "storage": "content" if k in bundle.content_files else "receipt"}
                     for k, v in bundle.files.items()}
        publication = canonical({"format": "polar.history-publication/1", "dataset_revision": bundle.revision,
                                 "import_receipt_id": bundle.receipt_id, "manifest_sha256": bundle.manifest_hash,
                                 "files": inventory})
        receipt["publication.json"] = publication
        # Reserve space for BOTH parts before publishing either.
        missing = 0
        for parent, name, values in (("history", bundle.revision, content),
                                     ("history-receipts", bundle.receipt_id, receipt)):
            path = self.root / parent / name
            require(not (self.root / parent).is_symlink() and not path.is_symlink(), "HISTORY_SYMLINK")
            if not path.exists():
                missing += sum(map(len, values.values()))
        require(self.used() + missing <= self.limit, "HISTORY_STORAGE_LIMIT")
        self._publish("history", bundle.revision, content)
        self._publish("history-receipts", bundle.receipt_id, receipt)
        return sha(publication)

    def verify(self, revision, receipt_id, publication_hash):
        revision_id(revision)
        hex_hash(receipt_id)
        hex_hash(publication_hash)
        safe_root(self.root)
        receipt_root = self.root / "history-receipts" / receipt_id
        raw = read_file(self.root, f"history-receipts/{receipt_id}/publication.json")
        require(sha(raw) == publication_hash, "HISTORY_PUBLICATION_HASH")
        publication = decode(raw)
        try:
            require(publication["format"] == "polar.history-publication/1" and
                    publication["dataset_revision"] == revision and publication["import_receipt_id"] == receipt_id)
            require(1 <= len(publication["files"]) <= 64, "HISTORY_FILE_SET")
            files = {}
            for key, record in publication["files"].items():
                require(record["storage"] in ("content", "receipt"))
                parent = f"history/{revision}" if record["storage"] == "content" else f"history-receipts/{receipt_id}"
                value = read_file(self.root, parent + "/" + relative(key))
                require(len(value) == record["bytes"] and sha(value) == record["sha256"], "HISTORY_OBJECT_HASH")
                files[key] = value
            bundle = verify_files(files, publication["manifest_sha256"])
            require(bundle.revision == revision and bundle.receipt_id == receipt_id, "HISTORY_RECEIPT_IDENTITY")
            for prefix, base, extras in (("content", self.root / "history" / revision, set()),
                                         ("receipt", receipt_root, {"publication.json"})):
                expected = {k for k, v in publication["files"].items() if v["storage"] == prefix} | extras
                actual = set()
                for path in base.rglob("*"):
                    require(not path.is_symlink(), "HISTORY_SYMLINK")
                    if path.is_file():
                        actual.add(str(path.relative_to(base)))
                require(actual == expected, "HISTORY_FILE_SET")
            return bundle
        except (KeyError, TypeError, AttributeError):
            raise HistoryError("HISTORY_INVALID_PUBLICATION") from None
