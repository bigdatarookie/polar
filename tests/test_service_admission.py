"""Historical metadata regressions; operation double, not PostgreSQL qualification."""
import copy
import hashlib
import json
import uuid
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.config import Settings
from polar.registry import BudgetExceeded, Conflict, Registry


class Result:
    def __init__(self,row=None,rows=None): self.row,self.rows=row,rows
    def fetchone(self): return copy.deepcopy(self.row)
    def fetchall(self): return copy.deepcopy(self.rows)


class History:
    def __init__(self,dataset_id):
        self.dataset_id=dataset_id
        self.runs={}
        self.attempts={}
        self.busy=False
        for i in range(40):
            rid=f"historical-{i:02}"
            self.runs[rid]={"id":rid,"state":"completed" if i%2 else "failed", "attempt":2,
                "idempotency_key":rid,"payload_hash":f"hash-{i}","error_code":None if i%2 else "JOB_TIMEOUT",
                "metric":{"retained":str(i)},"config":{"protocol":"frozen"}}
            for n,state in ((1,"lost"),(2,"completed" if i%2 else "failed")):
                aid=f"{rid}-attempt-{n}"
                self.attempts[aid]={"id":aid,"run_id":rid,"number":n,"state":state,"cpu_seconds":60,
                                    "error_code":"LEASE_EXPIRED" if n==1 else self.runs[rid]["error_code"]}
        self.old_runs=set(self.runs)
        self.old_attempts=set(self.attempts)

    def historical_hash(self):
        body={"runs":{k:self.runs[k] for k in sorted(self.old_runs)},
              "attempts":{k:self.attempts[k] for k in sorted(self.old_attempts)}}
        return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()

    def __enter__(self): return self
    def __exit__(self,*args): return False

    def execute(self,sql,params=()):
        statement=" ".join(sql.split())
        if "pg_advisory_xact_lock" in statement: return Result()
        if statement.startswith("SELECT * FROM runs WHERE idempotency_key"):
            return Result(next((r for r in self.runs.values() if r["idempotency_key"]==params[0]),None))
        if statement.startswith("SELECT id FROM datasets"):
            return Result({"id":self.dataset_id} if params[0]==self.dataset_id else None)
        if statement.startswith("SELECT count(*) AS n FROM runs"): return Result({"n":len(self.runs)})
        if "pg_database_size" in statement: return Result({"n":1})
        if statement.startswith("INSERT INTO runs"):
            rid,key,payload,config,dataset=params
            row={"id":rid,"idempotency_key":key,"payload_hash":payload,"config":copy.deepcopy(config.obj),
                 "dataset_id":dataset,"state":"queued","attempt":0,"cancel_requested":False}
            self.runs[rid]=row
            return Result(row)
        if statement.startswith("SELECT * FROM runs WHERE state='running'"): return Result(rows=[])
        if statement.startswith("SELECT id FROM runs WHERE state='running'"):
            active=next((r for r in self.runs.values() if r["state"]=="running"),None)
            return Result(active or ({"id":"another-active-job"} if self.busy else None))
        if statement.startswith("SELECT coalesce(sum(cpu_seconds)"):
            return Result({"n":sum(a["cpu_seconds"] for a in self.attempts.values())})
        if statement.startswith("UPDATE runs SET state='failed',error_code='CPU_BUDGET'"):
            for row in self.runs.values():
                if row["state"]=="queued": row.update(state="failed",error_code="CPU_BUDGET")
            return Result()
        if statement.startswith("SELECT * FROM runs WHERE state='queued'"):
            return Result(next((r for r in self.runs.values() if r["state"]=="queued"),None))
        if statement.startswith("INSERT INTO attempts"):
            aid,rid,number=params
            self.attempts[aid]={"id":aid,"run_id":rid,"number":number,"state":"running","cpu_seconds":0}
            return Result()
        if statement.startswith("UPDATE runs SET state='running'"):
            aid,lease_seconds,rid=params
            row=self.runs[rid]
            row.update(state="running",attempt=row["attempt"]+1,attempt_id=aid,lease_seconds=lease_seconds,error_code=None)
            return Result(row)
        raise AssertionError("unexpected metadata operation: "+statement)


@pytest.fixture
def retained(tmp_path,config,monkeypatch):
    history=History(config.dataset_id)
    registry=Registry(Settings("unused",tmp_path))
    monkeypatch.setattr(registry,"connect",lambda:history)
    return registry,history,config


def test_submit_beyond_historical_twenty_preserves_every_record(retained):
    registry,history,config=retained
    before=history.historical_hash()
    assert len(history.runs)==40 and sum(a["cpu_seconds"] for a in history.attempts.values())==4800
    run=registry.submit("new-bounded-run",config)
    assert run["state"]=="queued" and len(history.runs)==41
    assert history.historical_hash()==before
    assert registry.submit("new-bounded-run",config)["id"]==run["id"]
    with pytest.raises(Conflict,match="IDEMPOTENCY_PAYLOAD_CONFLICT"):
        registry.submit("new-bounded-run",config.model_copy(update={"actor":"changed"}))
    claimed=registry.claim()
    assert claimed["id"]==run["id"] and claimed["state"]=="running"
    assert history.historical_hash()==before


def test_claim_beyond_historical_cpu_preserves_history_and_current_queue(retained):
    registry,history,config=retained
    rid=uuid.uuid4()
    history.runs[rid]={"id":rid,"idempotency_key":"pending","state":"queued","attempt":0,"cancel_requested":False}
    before=history.historical_hash()
    claimed=registry.claim()
    assert claimed is not None and claimed["id"]==rid and claimed["state"]=="running" and claimed["attempt"]==1
    assert history.historical_hash()==before
    assert len(history.attempts)==81 and sum(a["cpu_seconds"] for a in history.attempts.values())==4800
    assert registry.claim() is None  # single active-job load protection remains
    assert history.historical_hash()==before


def test_storage_guard_and_busy_worker_still_refuse_without_history_changes(retained):
    registry,history,config=retained
    before=history.historical_hash()
    registry.settings=Settings("unused",registry.settings.artifacts,storage_bytes=1)
    with pytest.raises(BudgetExceeded,match="RETAINED_STORAGE_ADMISSION_LIMIT"):
        registry.submit("no-storage",config)
    assert history.historical_hash()==before
    history.busy=True
    assert registry.claim() is None and history.historical_hash()==before


def test_http_reports_current_storage_refusal_without_historical_caps(retained):
    registry,history,config=retained
    before=history.historical_hash()
    client=TestClient(create_app(SimpleNamespace(registry=registry)))
    response=client.post("/v1/runs",json=config.model_dump(mode="json"),headers={"Idempotency-Key":"new-http"})
    assert response.status_code==200 and response.json()["state"]=="queued"
    registry.settings=Settings("unused",registry.settings.artifacts,storage_bytes=1)
    refusal=client.post("/v1/runs",json=config.model_dump(mode="json"),headers={"Idempotency-Key":"storage-http"})
    assert refusal.status_code==429 and refusal.json()=={"code":"RETAINED_STORAGE_ADMISSION_LIMIT"}
    assert history.historical_hash()==before


def test_cli_storage_error_names_remaining_guard(retained,tmp_path,monkeypatch,capsys):
    from polar.cli import main
    registry,history,config=retained
    before=history.historical_hash()
    registry.settings=Settings("unused",registry.settings.artifacts,storage_bytes=1)
    monkeypatch.setattr(Settings,"load",lambda:registry.settings)
    monkeypatch.setattr("polar.service.Service",lambda settings:SimpleNamespace(registry=registry))
    payload=tmp_path/"config.json"
    payload.write_text(json.dumps(config.model_dump(mode="json")))
    with pytest.raises(SystemExit) as error:
        main(["submit",str(payload),"--key","storage-cli"])
    assert error.value.code==1
    assert json.loads(capsys.readouterr().err)=={"status":"ERROR","code":"RETAINED_STORAGE_ADMISSION_LIMIT"}
    assert history.historical_hash()==before


def test_merged_settings_preserve_B_storage_and_key_configuration(monkeypatch):
    monkeypatch.setenv("POLAR_DATABASE_URL","unused")
    monkeypatch.delenv("POLAR_STORAGE_BYTES",raising=False)
    monkeypatch.delenv("POLAR_HISTORY_CURSOR_KEY_FILE",raising=False)
    settings=Settings.load()
    assert settings.storage_bytes==64*1024**3
    assert settings.history_cursor_key_file==Path("/run/secrets/history_cursor_key")
    assert (settings.lease_seconds,settings.job_seconds)==(15,60)
    assert not hasattr(settings,"max_jobs") and not hasattr(settings,"cpu_seconds")
    monkeypatch.setenv("POLAR_STORAGE_BYTES",str(16*1024**3))
    monkeypatch.setenv("POLAR_HISTORY_CURSOR_KEY_FILE","/private/tmp/invented-key-path")
    changed=Settings.load()
    assert changed.storage_bytes==16*1024**3 and changed.history_cursor_key_file==Path("/private/tmp/invented-key-path")
    monkeypatch.setenv("POLAR_STORAGE_BYTES",str(64*1024**3+1))
    with pytest.raises(ValueError,match="INVALID_STORAGE_ALLOCATION"): Settings.load()
