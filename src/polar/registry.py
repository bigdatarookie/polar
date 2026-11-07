"""PostgreSQL is the sole metadata authority. No SQLite qualification path."""
import uuid
import hashlib
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
