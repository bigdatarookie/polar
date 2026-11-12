import importlib.metadata
import hashlib
import json
import multiprocessing as mp
import os
import platform
import time

from .artifacts import ArtifactStore
from .codec import digest
from .config import Settings
from .engine import calculate, InvalidInput
from .models import Dataset, RunConfig
from .registry import Registry


def compute_child(pipe, dataset, config, root, limit, rid, aid, provenance):
    started = time.process_time()
    try:
        report = calculate(Dataset.model_validate(dataset),RunConfig.model_validate(config))
        # Include Parquet writes and atomic publication in the supervised process.
        # A killed publisher can leave only an unreferenced attempt or partial
        # directory; the registry is the completion visibility boundary.
        ref = ArtifactStore(root,limit).publish(rid,aid,report,
                {"dataset":dataset,"config":config,**provenance},environment())
        pipe.send({"artifact_ref":ref,"cpu":time.process_time()-started})
    except (InvalidInput,ValueError) as exc:
        pipe.send({"error":str(exc) if isinstance(exc,InvalidInput) else "INVALID_SCHEMA","cpu":time.process_time()-started})
    finally:
        pipe.close()


def environment():
    from . import __version__
    return {"code_revision":os.environ.get("POLAR_CODE_REVISION","UNRECORDED"),
            "python":platform.python_version(),"platform":platform.platform(),
            "service_version":__version__,
            "dependencies":{p:importlib.metadata.version(p) for p in ["psycopg","pyarrow","pydantic","fastapi"]},
            "image_ref":os.environ.get("POLAR_IMAGE_REF","UNRECORDED"),
            "blinding":"BLINDING_NOT_ENFORCED"}


def work_once(settings):
    reg = Registry(settings)
    reg.check()
    store = ArtifactStore(settings.artifacts,settings.storage_bytes)
    store.check(writable=True)
    row = reg.claim()
    if row is None:
        return None
    rid,aid = row["id"],row["attempt_id"]
    claim_clock = time.monotonic()
    parent_cpu_started = time.process_time()
    print(json.dumps({"event":"claimed","run_id":str(rid),"attempt_id":str(aid),"attempt":row["attempt"]}),flush=True)
    process = None
    recv = send = None
    cpu = settings.job_seconds  # full reservation if killed/crashed; never a free retry
    state,ref,error = "failed",None,"INFRASTRUCTURE_FAILURE"
    try:
        dataset_row = reg.dataset(row["dataset_id"])
        dataset = dataset_row["body"]
        ctx = mp.get_context("spawn")
        recv,send = ctx.Pipe(duplex=False)
        provenance = {"original_dataset_utf8":bytes(dataset_row["source_bytes"]).decode(),
                      "source_sha256":dataset_row["source_hash"],
                      "imported_at":dataset_row["registered_at"].isoformat()}
        process = ctx.Process(target=compute_child,args=(send,dataset,row["config"],settings.artifacts,
                             settings.storage_bytes,rid,aid,provenance))
        process.start()
        send.close()
        # Reserve 20s for bounded DB calls/finalization within the 60s job wall
        # ceiling. Deployment timings still require the actual-host check.
        deadline = claim_clock+max(1,settings.job_seconds-20)
        next_heartbeat = 0
        while True:
            now = time.monotonic()
            if now >= deadline:
                error = "JOB_TIMEOUT"
                break
            if now >= next_heartbeat:
                if not reg.heartbeat(rid,aid):
                    state,error = "canceled","CANCELED_OR_LEASE_LOST"
                    break
                next_heartbeat = now+min(2,settings.lease_seconds/3)
            if recv.poll(0.05):
                result = recv.recv()
                cpu = result["cpu"]
                if "error" in result:
                    error = "INVALID:"+result["error"]
                    break
                # The unique immutable output is visible only after DB fencing.
                if not reg.heartbeat(rid,aid):
                    state,error = "canceled","CANCELED_OR_LEASE_LOST"
                    break
                ref = result["artifact_ref"]
                state,error = "completed",None
                break
            if not process.is_alive():
                error = "COMPUTE_PROCESS_LOST"
                break
    except Exception:
        # Error codes only; do not send data/credentials to logs.
        error = "INFRASTRUCTURE_FAILURE"
    finally:
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join()
        for pipe in [recv,send]:
            if pipe is not None:
                pipe.close()
    if error in {"COMPUTE_PROCESS_LOST","INFRASTRUCTURE_FAILURE"}:
        # Let the lease expire so the explicit infrastructure recovery path owns
        # the one allowed retry; deterministic invalidity is always terminal.
        print(json.dumps({"event":"lease_recovery_required","run_id":str(rid),"attempt_id":str(aid),"code":error}),flush=True)
        return reg.get(rid)
    artifact_hash = hashlib.sha256((store.directory(ref)/"manifest.json").read_bytes()).hexdigest() if ref else None
    cpu = min(settings.job_seconds,cpu+time.process_time()-parent_cpu_started)
    reg.finish(rid,aid,state,cpu,ref,error,artifact_hash)
    print(json.dumps({"event":"finished","run_id":str(rid),"attempt_id":str(aid),"state":state,"code":error}),flush=True)
    return reg.get(rid)


def work_research_delivery_once(settings):
    from .research_delivery import deliver_once
    from .research_results import ResearchResults
    from .history_bundle import HistoryError
    registry = Registry(settings)
    results = ResearchResults(settings.artifacts, settings.storage_bytes)
    try:
        return deliver_once(registry, results)
    except HistoryError:
        # No persisted acknowledgement: retry only saved delivery after lease expiry.
        raise RuntimeError("RESEARCH_DELIVERY_INTEGRITY_ERROR") from None


def run_forever():
    settings = Settings.load()
    while True:
        try:
            work_research_delivery_once(settings)
        except Exception:
            print(json.dumps({"event":"research_delivery_dependency_unavailable"}),flush=True)
        try:
            work_once(settings)
        except Exception:
            print(json.dumps({"event":"dependency_unavailable"}),flush=True)
        time.sleep(1)


if __name__ == "__main__":
    run_forever()
