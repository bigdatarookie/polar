"""Additive history registry in the same PG; legacy registry/worker untouched."""
import base64
from importlib.resources import files

from psycopg.types.json import Jsonb

from .history_bundle import (HistoryError, canonical, decode, identifier, require,
                             revision_id, sha, verify_bundle)
from .history_store import HistoryStore
from .registry import Registry

LOCK = 734910


class HistoryRegistry:
    def __init__(self, settings):
        self.settings = settings
        self.legacy = Registry(settings)
        self.store = HistoryStore(settings.artifacts, settings.storage_bytes)

    @staticmethod
    def schema():
        return files("polar").joinpath("history_schema.sql").read_bytes()

    def _check(self, db):
        row = db.execute("SELECT to_regclass('history_schema_version') AS name").fetchone()
        require(row["name"] is not None, "HISTORY_SCHEMA_MISSING")
        rows = db.execute("SELECT version,checksum FROM history_schema_version").fetchall()
        require(rows == [{"version": 1, "checksum": sha(self.schema())}], "HISTORY_SCHEMA_MISMATCH")
        db.execute("""SELECT r.dataset_id,r.revision,r.catalog_sequence,r.primary_import_receipt_id,r.manifest_hash,
            r.publication_hash,r.summary,a.receipt_id,a.manifest_hash,a.publication_hash FROM history_revisions r
            JOIN history_receipts a ON a.revision=r.revision LIMIT 0""")

    def migrate(self):
        self.legacy.check()  # never implicitly initialize or replace legacy metadata
        with self.legacy.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            existing = db.execute("SELECT to_regclass('history_schema_version') AS name").fetchone()
            if existing["name"]:
                self._check(db)
                return {"history_schema_version": 1}
            collisions = db.execute("""SELECT tablename FROM pg_tables WHERE schemaname=current_schema()
                AND tablename IN ('history_revisions','history_receipts')""").fetchall()
            require(not collisions, "HISTORY_SCHEMA_PARTIAL")
            function = db.execute("SELECT to_regproc('history_protect_immutable') AS name").fetchone()
            require(function["name"] is None, "HISTORY_SCHEMA_PARTIAL")
            source = self.schema()
            db.execute(source.decode())
            db.execute("INSERT INTO history_schema_version(version,checksum) VALUES(1,%s)", (sha(source),))
            self._check(db)
        return {"history_schema_version": 1}

    def register(self, directory, manifest_sha256):
        bundle = verify_bundle(directory, manifest_sha256)
        self.legacy.check()
        with self.legacy.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            self._check(db)
            db_size = db.execute("SELECT pg_database_size(current_database()) AS n").fetchone()["n"]
            # Same budget convention as legacy registry; no global quota claim.
            require(db_size + 1024**2 < self.settings.storage_bytes, "HISTORY_STORAGE_LIMIT")
            store = HistoryStore(self.settings.artifacts, self.settings.storage_bytes - db_size - 1024**2)
            with store.locked():
                publication_hash = store.publish_locked(bundle)
                store.verify(bundle.revision, bundle.receipt_id, publication_hash)
                summary = {**bundle.summary, "publication_sha256": publication_hash}
                require(len(canonical(summary)) <= 128 * 1024, "HISTORY_SUMMARY_LIMIT")
                db.execute("""INSERT INTO history_revisions(dataset_id,revision,primary_import_receipt_id,
                    manifest_hash,publication_hash,summary) VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""", (bundle.dataset_id, bundle.revision, bundle.receipt_id,
                                              bundle.manifest_hash, publication_hash, Jsonb(summary)))
                row = db.execute("SELECT * FROM history_revisions WHERE revision=%s", (bundle.revision,)).fetchone()
                require(row is not None and row["dataset_id"] == bundle.dataset_id, "HISTORY_IDENTITY_CONFLICT")
                # Preserve first receipt, including its byte-exact wrapper/manifest identity.
                primary = store.verify(bundle.revision, row["primary_import_receipt_id"], row["publication_hash"])
                require(primary.manifest_hash == row["manifest_hash"] and
                        {**primary.summary, "publication_sha256": row["publication_hash"]} == row["summary"],
                        "HISTORY_IDENTITY_CONFLICT")
                db.execute("""INSERT INTO history_receipts(revision,receipt_id,manifest_hash,publication_hash)
                    VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                           (bundle.revision, bundle.receipt_id, bundle.manifest_hash, publication_hash))
                receipt = db.execute("SELECT * FROM history_receipts WHERE revision=%s AND receipt_id=%s",
                                     (bundle.revision, bundle.receipt_id)).fetchone()
                require(receipt["manifest_hash"] == bundle.manifest_hash and
                        receipt["publication_hash"] == publication_hash, "HISTORY_RECEIPT_CONFLICT")
                result = {**row["summary"], "registered_at": row["registered_at"],
                          "submitted_import_receipt_id": bundle.receipt_id,
                          "runtime_qualification": "NOT_RUN"}
        return result

    def revision(self, dataset_id, revision):
        summary, _ = self.load_revision(dataset_id, revision)
        return summary

    def load_revision(self, dataset_id, revision):
        """Internal verified data access; bytes never appear in catalog projections."""
        identifier(dataset_id)
        revision_id(revision)
        self.legacy.check()
        with self.legacy.connect() as db:
            self._check(db)
            row = db.execute("SELECT * FROM history_revisions WHERE dataset_id=%s AND revision=%s",
                             (dataset_id, revision)).fetchone()
        require(row is not None, "HISTORY_REVISION_NOT_FOUND")
        bundle = self.store.verify(revision, row["primary_import_receipt_id"], row["publication_hash"])
        require(bundle.dataset_id == dataset_id and bundle.manifest_hash == row["manifest_hash"] and
                {**bundle.summary, "publication_sha256": row["publication_hash"]} == row["summary"],
                "HISTORY_IDENTITY_CONFLICT")
        return ({**row["summary"], "registered_at": row["registered_at"], "runtime_qualification": "NOT_RUN"}, bundle)

    def catalog(self, limit=50, cursor=None):
        require(type(limit) is int and 1 <= limit <= 50, "HISTORY_INVALID_PAGE")
        snapshot, after = None, ""
        if cursor is not None:
            require(type(cursor) is str and len(cursor) <= 2048, "HISTORY_INVALID_CURSOR")
            try:
                page = decode(base64.b64decode(cursor, altchars=b"-_", validate=True))
                require(set(page) == {"snapshot", "after", "limit"} and type(page["limit"]) is int and page["limit"] == limit and
                        type(page["snapshot"]) is int and 0 <= page["snapshot"] <= 2**63-1,
                        "HISTORY_INVALID_CURSOR")
                snapshot, after = page["snapshot"], revision_id(page["after"])
            except (ValueError, KeyError, TypeError):
                raise HistoryError("HISTORY_INVALID_CURSOR") from None
        self.legacy.check()
        with self.legacy.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            self._check(db)
            if snapshot is None:
                snapshot = db.execute("SELECT coalesce(max(catalog_sequence),0) AS n FROM history_revisions").fetchone()["n"]
            rows = db.execute("""SELECT dataset_id,revision FROM history_revisions
                WHERE catalog_sequence<=%s AND revision>%s
                AND summary->'fitness'->>'chart_fitness'='READY_WITH_LIMITS'
                ORDER BY revision LIMIT %s""",
                              (snapshot, after, limit + 1)).fetchall()
        items, size = [], 0
        for row in rows[:limit]:
            item = self.revision(row["dataset_id"], row["revision"])
            encoded = canonical({**item, "registered_at": item["registered_at"].isoformat()})
            if size + len(encoded) > 1024**2 - 4096:
                require(items, "HISTORY_RESPONSE_LIMIT")
                break
            size += len(encoded)
            items.append(item)
        next_cursor = None
        if len(rows) > len(items):
            next_cursor = base64.urlsafe_b64encode(canonical({"snapshot": snapshot, "limit": limit,
                                                             "after": items[-1]["dataset_revision"]})).decode()
        return {"schema_version": "polar.history-catalog/1", "items": items,
                "next_cursor": next_cursor, "catalog_snapshot": snapshot}


    def research_navigation(self, input_sha256, native_symbol):
        """Resolve only an exact registered content correspondence, never ticker.

        Every selected publication is reverified through load_revision; multiple
        matching revisions are ambiguous and cannot silently choose newest.
        """
        from .history_bundle import hex_hash
        hex_hash(input_sha256);identifier(native_symbol)
        self.legacy.check()
        with self.legacy.connect() as db:
            self._check(db)
            rows=db.execute("""SELECT dataset_id,revision FROM history_revisions
                WHERE summary->'research_bindings' @> %s::jsonb LIMIT 2""",
                (Jsonb([{'input_sha256':input_sha256,'native_symbol':native_symbol}]),)).fetchall()
        if len(rows)!=1:return None
        summary,_=self.load_revision(rows[0]['dataset_id'],rows[0]['revision'])
        links=[x for x in summary.get('research_bindings',[]) if x['input_sha256']==input_sha256 and x['native_symbol']==native_symbol]
        require(len(links)==1,'HISTORY_RESEARCH_MAPPING_IDENTITY')
        link=links[0];asset=next((x for x in summary['instruments'] if x['instrument_id']==link['instrument_id']),None)
        require(asset is not None and asset['source_symbol']==link['source_symbol'],'HISTORY_RESEARCH_MAPPING_IDENTITY')
        return {**{k:v for k,v in link.items() if k!='native_symbol'},'dataset_id':summary['dataset_id'],
                'dataset_revision':summary['dataset_revision'],'mapping_status':'DECLARED_CURRENT_ONLY',
                'instrument_type':asset['instrument_type']}
