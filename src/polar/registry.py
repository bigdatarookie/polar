"""PostgreSQL is the sole metadata authority. No SQLite qualification path."""
import uuid
import hashlib
import json
import re
from importlib.resources import files

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .codec import digest,canonical


class Conflict(Exception):
    pass


class NotFound(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class Registry:
    def __init__(self, settings):
        self.settings = settings

    def connect(self):
        return psycopg.connect(self.settings.dsn, row_factory=dict_row, connect_timeout=3,
                               options="-c statement_timeout=5000 -c lock_timeout=5000")

    def migrate(self):
        source = files("polar").joinpath("schema.sql").read_text()
        checksum = hashlib.sha256(source.encode()).hexdigest()
        with self.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(734901)")
            if db.execute("SELECT to_regclass('schema_version') AS name").fetchone()["name"]:
                old = db.execute("SELECT version,checksum FROM schema_version").fetchall()
                if old != [{"version":1,"checksum":checksum}]:
                    raise RuntimeError("SCHEMA_MISMATCH")
            db.execute(source)
            db.execute("INSERT INTO schema_version(version,checksum) VALUES (1,%s) ON CONFLICT DO NOTHING",(checksum,))
            self._migrate_research_delivery(db)

    @staticmethod
    def _research_delivery_schema():
        return files("polar").joinpath("research_delivery_schema.sql").read_bytes()

    def _check_research_delivery(self, db):
        existing = db.execute("SELECT to_regclass('research_delivery_schema_version') AS name").fetchone()
        if not existing["name"]:
            raise RuntimeError("RESEARCH_DELIVERY_UNAVAILABLE")
        checksum = hashlib.sha256(self._research_delivery_schema()).hexdigest()
        rows = db.execute("SELECT version,checksum FROM research_delivery_schema_version").fetchall()
        if rows != [{"version": 1, "checksum": checksum}]:
            raise RuntimeError("RESEARCH_DELIVERY_SCHEMA_MISMATCH")
        db.execute("""SELECT id,kind,result_id,payload_hash,body,body_bytes,state,
            delivery_attempt_count,lease_token,lease_until,queued_at,started_at,
            last_started_at,delivered_at,finished_at,updated_at,not_before,receipt,error_code
            FROM research_deliveries LIMIT 0""")

    def _migrate_research_delivery(self, db):
        # Same transaction/advisory lock as legacy migration; never alter its v1.
        existing = db.execute("SELECT to_regclass('research_delivery_schema_version') AS name").fetchone()
        if existing["name"]:
            self._check_research_delivery(db)
            return
        collision = db.execute("SELECT to_regclass('research_deliveries') AS name").fetchone()
        function = db.execute("SELECT to_regproc('protect_research_delivery') AS name").fetchone()
        if collision["name"] or function["name"]:
            raise RuntimeError("RESEARCH_DELIVERY_SCHEMA_PARTIAL")
        source = self._research_delivery_schema()
        db.execute(source.decode())
        db.execute("INSERT INTO research_delivery_schema_version(version,checksum) VALUES (1,%s)",
                   (hashlib.sha256(source).hexdigest(),))
        self._check_research_delivery(db)

    @staticmethod
    def _research_delivery_id(value, prefix):
        if type(value) is not str or re.fullmatch(prefix+r"-[0-9a-f]{64}", value) is None:
            raise ValueError("RESEARCH_DELIVERY_INVALID_ID")
        return value

    @staticmethod
    def _research_delivery_json(body):
        if not isinstance(body, dict):
            raise ValueError("RESEARCH_DELIVERY_INVALID_BODY")
        try:
            encoded = canonical(body)
            if json.loads(encoded) != body:
                raise ValueError("RESEARCH_DELIVERY_INVALID_BODY")
            return encoded
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise ValueError("RESEARCH_DELIVERY_INVALID_BODY") from None

    def submit_research_delivery(self, delivery_id, kind, result_id, payload_hash, body):
        """Admit immutable validated public delivery bytes, never a scientific job."""
        self._research_delivery_id(delivery_id, "delivery")
        self._research_delivery_id(result_id, "research")
        if type(kind) is not str or kind not in {"RESULT", "ASSESSMENT"}:
            raise ValueError("RESEARCH_DELIVERY_INVALID_KIND")
        if type(payload_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", payload_hash) is None:
            raise ValueError("RESEARCH_DELIVERY_INVALID_HASH")
        encoded = self._research_delivery_json(body)
        if delivery_id != "delivery-"+payload_hash or hashlib.sha256(encoded).hexdigest() != payload_hash:
            raise Conflict("RESEARCH_DELIVERY_PAYLOAD_CONFLICT")
        try:
            with self.connect() as db:
                self._check_research_delivery(db)
                # Reuse admission serialization/storage accounting, not run attempts.
                db.execute("SELECT pg_advisory_xact_lock(734902)")
                old = db.execute("SELECT * FROM research_deliveries WHERE id=%s", (delivery_id,)).fetchone()
                if old:
                    if (old["kind"] != kind or old["result_id"] != result_id or
                            old["payload_hash"] != payload_hash or old["body"] != body):
                        raise Conflict("RESEARCH_DELIVERY_PAYLOAD_CONFLICT")
                    return old
                from .artifacts import storage_used
                db_bytes = db.execute("SELECT pg_database_size(current_database()) AS n").fetchone()["n"]
                if db_bytes + storage_used(self.settings.artifacts) + len(encoded) > self.settings.storage_bytes:
                    raise BudgetExceeded("RETAINED_STORAGE_ADMISSION_LIMIT")
                return db.execute("""INSERT INTO research_deliveries(id,kind,result_id,payload_hash,body,body_bytes)
                    VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (delivery_id, kind, result_id, payload_hash, Jsonb(body), len(encoded))).fetchone()
        except psycopg.Error:
            raise RuntimeError("RESEARCH_DELIVERY_UNAVAILABLE") from None

    def research_delivery(self, delivery_id):
        self._research_delivery_id(delivery_id, "delivery")
        try:
            with self.connect() as db:
                self._check_research_delivery(db)
                return db.execute("SELECT * FROM research_deliveries WHERE id=%s", (delivery_id,)).fetchone()
        except psycopg.Error:
            raise RuntimeError("RESEARCH_DELIVERY_UNAVAILABLE") from None

    def claim_research_delivery(self):
        """Fence one delivery, including only its expired delivery lease/retry."""
        try:
            with self.connect() as db:
                self._check_research_delivery(db)
                row = db.execute("""SELECT * FROM research_deliveries
                    WHERE (state IN ('QUEUED','WAITING_FOR_RESULT') AND not_before<=now())
                       OR (state='DELIVERING' AND lease_until<=now())
                    ORDER BY queued_at,id LIMIT 1 FOR UPDATE SKIP LOCKED""").fetchone()
                if not row:
                    return None
                token = uuid.uuid4()
                return db.execute("""UPDATE research_deliveries SET state='DELIVERING',lease_token=%s,
                    lease_until=now()+make_interval(secs => %s),delivery_attempt_count=delivery_attempt_count+1,
                    started_at=coalesce(started_at,now()),last_started_at=now(),updated_at=now(),error_code=NULL
                    WHERE id=%s RETURNING *""", (token, self.settings.lease_seconds, row["id"])).fetchone()
        except psycopg.Error:
            raise RuntimeError("RESEARCH_DELIVERY_UNAVAILABLE") from None

    def finish_research_delivery(self, delivery_id, lease_token, state, receipt=None, error_code=None):
        self._research_delivery_id(delivery_id, "delivery")
        if type(state) is not str or state not in {"WAITING_FOR_RESULT", "DELIVERED", "REJECTED"}:
            raise ValueError("RESEARCH_DELIVERY_INVALID_STATE")
        try:
            token = uuid.UUID(str(lease_token))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("RESEARCH_DELIVERY_INVALID_LEASE_TOKEN") from None
        if receipt is not None:
            self._research_delivery_json(receipt)
        if error_code is not None and (type(error_code) is not str or
                re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", error_code) is None):
            raise ValueError("RESEARCH_DELIVERY_INVALID_ERROR_CODE")
        try:
            with self.connect() as db:
                self._check_research_delivery(db)
                row = db.execute("SELECT * FROM research_deliveries WHERE id=%s FOR UPDATE", (delivery_id,)).fetchone()
                if not row:
                    raise NotFound("RESEARCH_DELIVERY_NOT_FOUND")
                if (row["state"] != "DELIVERING" or row["lease_token"] != token or not
                        db.execute("SELECT %s::timestamptz>now() AS valid", (row["lease_until"],)).fetchone()["valid"]):
                    raise Conflict("RESEARCH_DELIVERY_LEASE_CONFLICT")
                return db.execute("""UPDATE research_deliveries SET state=%s,receipt=%s,error_code=%s,
                    lease_token=NULL,lease_until=NULL,updated_at=now(),
                    not_before=CASE WHEN %s='WAITING_FOR_RESULT' THEN now()+interval '1 second' ELSE not_before END,
                    delivered_at=CASE WHEN %s='DELIVERED' THEN now() ELSE NULL END,
                    finished_at=CASE WHEN %s IN ('DELIVERED','REJECTED') THEN now() ELSE NULL END
                    WHERE id=%s RETURNING *""", (state, Jsonb(receipt) if receipt is not None else None,
                                               error_code, state, state, state, delivery_id)).fetchone()
        except psycopg.Error:
            raise RuntimeError("RESEARCH_DELIVERY_UNAVAILABLE") from None

    def check(self):
        checksum = hashlib.sha256(files("polar").joinpath("schema.sql").read_bytes()).hexdigest()
        with self.connect() as db:
            rows = db.execute("SELECT version,checksum FROM schema_version").fetchall()
            if rows != [{"version":1,"checksum":checksum}]:
                raise RuntimeError("SCHEMA_MISMATCH")
            db.execute("""SELECT r.config,r.artifact_hash,r.lease_until,a.cpu_seconds,d.body,d.source_hash,d.source_bytes
                FROM runs r JOIN attempts a ON a.run_id=r.id JOIN datasets d ON d.id=r.dataset_id LIMIT 0""")

    def register_dataset(self, body, raw_bytes=None):
        from .models import Dataset
        raw_bytes = raw_bytes if raw_bytes is not None else canonical(body)
        if len(raw_bytes) > 1024**2:
            raise ValueError("DATASET_BYTE_LIMIT")
        data = Dataset.model_validate(body)
        body = data.model_dump(mode="json")
        h = digest(body)
        with self.connect() as db:
            db.execute("INSERT INTO datasets(id,content_hash,body,source_hash,source_bytes) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                       (data.dataset_id,h,Jsonb(body),hashlib.sha256(raw_bytes).hexdigest(),raw_bytes))
            row = db.execute("SELECT id,content_hash,source_hash,registered_at FROM datasets WHERE id=%s", (data.dataset_id,)).fetchone()
            if not row or row["content_hash"] != h:
                raise Conflict("DATASET_VERSION_CONFLICT")
            return row

    def dataset(self, dataset_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM datasets WHERE id=%s", (dataset_id,)).fetchone()
            if not row:
                raise NotFound("DATASET_NOT_FOUND")
            return row

    def datasets(self, limit=10, offset=0):
        with self.connect() as db:
            return db.execute("SELECT id,content_hash,source_hash,registered_at FROM datasets ORDER BY id LIMIT %s OFFSET %s",
                              (limit, offset)).fetchall()

    def submit(self, key, config):
        body = config.model_dump(mode="json")
        h = digest(body)
        with self.connect() as db:
            # Global lock serializes admission and the single worker's claims.
            db.execute("SELECT pg_advisory_xact_lock(734902)")
            old = db.execute("SELECT * FROM runs WHERE idempotency_key=%s", (key,)).fetchone()
            if old:
                if old["payload_hash"] != h:
                    raise Conflict("IDEMPOTENCY_PAYLOAD_CONFLICT")
                return old
            if not db.execute("SELECT id FROM datasets WHERE id=%s", (config.dataset_id,)).fetchone():
                raise NotFound("DATASET_NOT_FOUND")
            from .artifacts import storage_used
            db_bytes = db.execute("SELECT pg_database_size(current_database()) AS n").fetchone()["n"]
            if db_bytes + storage_used(self.settings.artifacts) + 1024**2 > self.settings.storage_bytes:
                raise BudgetExceeded("RETAINED_STORAGE_ADMISSION_LIMIT")
            run_id = uuid.uuid4()
            return db.execute("""INSERT INTO runs(id,idempotency_key,payload_hash,config,dataset_id,state)
                VALUES (%s,%s,%s,%s,%s,'queued') RETURNING *""",
                (run_id, key, h, Jsonb(body), config.dataset_id)).fetchone()

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=%s", (run_id,)).fetchone()
            if not row:
                raise NotFound("RUN_NOT_FOUND")
            row["attempts"] = db.execute("SELECT * FROM attempts WHERE run_id=%s ORDER BY number", (run_id,)).fetchall()
            return row

    def search(self, limit=10, offset=0, dataset_id=None):
        with self.connect() as db:
            return db.execute("""SELECT id,dataset_id,state,created_at,artifact_ref,error_code
                FROM runs WHERE (%s::text IS NULL OR dataset_id=%s)
                ORDER BY created_at,id LIMIT %s OFFSET %s""", (dataset_id, dataset_id, limit, offset)).fetchall()

    def cancel(self, run_id):
        with self.connect() as db:
            old = db.execute("SELECT * FROM runs WHERE id=%s FOR UPDATE", (run_id,)).fetchone()
            if not old:
                raise NotFound("RUN_NOT_FOUND")
            if old["state"] in {"completed","failed","canceled"}:
                return old
            row = db.execute("""UPDATE runs SET cancel_requested=true,
                state=CASE WHEN state='queued' THEN 'canceled' ELSE state END, updated_at=now()
                WHERE id=%s RETURNING *""", (run_id,)).fetchone()
            if not row:
                raise NotFound("RUN_NOT_FOUND")
            return row

    def claim(self):
        with self.connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(734902)")
            # An expired attempt consumes the full wall allowance as conservative CPU
            # reservation. Retry is infrastructure-only and uses a new attempt identity.
            expired = db.execute("SELECT * FROM runs WHERE state='running' AND lease_until < now() FOR UPDATE").fetchall()
            for row in expired:
                db.execute("""UPDATE attempts SET state='lost',finished_at=now(),cpu_seconds=%s,
                    error_code='LEASE_EXPIRED' WHERE id=%s""", (self.settings.job_seconds, row["attempt_id"]))
                state = "canceled" if row["cancel_requested"] else ("queued" if row["attempt"] < 2 else "failed")
                db.execute("""UPDATE runs SET state=%s,lease_until=NULL,updated_at=now(),
                    error_code='LEASE_EXPIRED' WHERE id=%s""", (state, row["id"]))
            # Claiming is globally serialized; concurrent workers cannot execute jobs.
            if db.execute("SELECT id FROM runs WHERE state='running' LIMIT 1").fetchone():
                return None
            row = db.execute("SELECT * FROM runs WHERE state='queued' ORDER BY created_at,id LIMIT 1 FOR UPDATE").fetchone()
            if not row:
                return None
            aid = uuid.uuid4()
            db.execute("INSERT INTO attempts(id,run_id,number,state) VALUES (%s,%s,%s,'running')",
                       (aid,row["id"],row["attempt"] + 1))
            return db.execute("""UPDATE runs SET state='running',attempt=attempt+1,attempt_id=%s,
                lease_until=now()+make_interval(secs => %s),error_code=NULL,updated_at=now()
                WHERE id=%s RETURNING *""", (aid,self.settings.lease_seconds,row["id"])).fetchone()

    def heartbeat(self, run_id, aid):
        with self.connect() as db:
            return db.execute("""UPDATE runs SET lease_until=now()+make_interval(secs => %s),updated_at=now()
                WHERE id=%s AND attempt_id=%s AND state='running' AND lease_until>now()
                  AND NOT cancel_requested RETURNING id""", (self.settings.lease_seconds,run_id,aid)).fetchone() is not None

    def finish(self, run_id, aid, state, cpu_seconds, artifact_ref=None, error=None, artifact_hash=None):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=%s FOR UPDATE", (run_id,)).fetchone()
            if not row or row["attempt_id"] != aid or row["state"] != "running":
                return False
            if not db.execute("SELECT %s::timestamptz>now() AS valid",(row["lease_until"],)).fetchone()["valid"]:
                return False
            if row["cancel_requested"]:
                state,artifact_ref,artifact_hash,error = "canceled",None,None,"CANCELED"
            db.execute("""UPDATE runs SET state=%s,artifact_ref=%s,artifact_hash=%s,error_code=%s,lease_until=NULL,
                updated_at=now() WHERE id=%s""", (state,artifact_ref,artifact_hash,error,run_id))
            db.execute("""UPDATE attempts SET state=%s,cpu_seconds=%s,finished_at=now(),error_code=%s
                WHERE id=%s""", (state,cpu_seconds,error,aid))
            return True
