import uuid

import psycopg
from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

from .artifacts import ArtifactError
from .config import Settings
from .models import Dataset, RunConfig
from .registry import BudgetExceeded, Conflict, NotFound
from .service import DatasetIntegrityError, Service


def create_app(service=None):
    app = FastAPI(title="Polar fixture API",version="0.1.0")
    # Delay secret/dependency access until a request. /livez proves only liveness.
    def svc():
        return service or Service(Settings.load())

    @app.middleware("http")
    async def bounded_body(request,call_next):
        if request.method == "POST" and request.url.path in {"/v1/datasets","/v1/runs"}:
            length = request.headers.get("content-length","")
            if not length.isdigit() or int(length) > 1024**2:
                return JSONResponse(status_code=413,content={"code":"BODY_LIMIT_1_MIB"})
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    def validation(req,exc):
        return JSONResponse(status_code=422,content={"code":"INVALID_SCHEMA","fields":[list(e["loc"]) for e in exc.errors()][:20]})

    @app.exception_handler(Conflict)
    def conflict(req,exc):
        return JSONResponse(status_code=409,content={"code":str(exc)})

    @app.exception_handler(DatasetIntegrityError)
    def dataset_integrity(req,exc):
        return JSONResponse(status_code=409,content={"code":"DATASET_INTEGRITY_ERROR"})

    @app.exception_handler(NotFound)
    def not_found(req,exc):
        return JSONResponse(status_code=404,content={"code":str(exc)})

    @app.exception_handler(BudgetExceeded)
    def budget(req,exc):
        return JSONResponse(status_code=429,content={"code":str(exc)})

    @app.exception_handler(psycopg.Error)
    @app.exception_handler(OSError)
    @app.exception_handler(ArtifactError)
    def unavailable(req,exc):
        # Do not echo DSNs, SQL, files, credentials or data bodies.
        return JSONResponse(status_code=503,content={"code":"DEPENDENCY_UNAVAILABLE"})

    @app.get("/livez")
    def live():
        return {"status":"ALIVE"}

    @app.get("/readyz")
    def ready():
        try:
            return svc().ready()
        except (OSError,psycopg.Error,ArtifactError,RuntimeError):
            return JSONResponse(status_code=503,content={"status":"NOT_READY"})

    @app.post("/v1/datasets")
    async def register(body: Dataset,request:Request):
        return svc().registry.register_dataset(body.model_dump(mode="json"),await request.body())

    @app.get("/v1/datasets")
    def datasets(limit:int=Query(10,ge=1,le=10),offset:int=Query(0,ge=0)):
        return svc().registry.datasets(limit,offset)

    @app.get("/v1/datasets/{dataset_id}/features/{feature_id}")
    def feature(dataset_id:str,feature_id:str,decision_at:str):
        from datetime import datetime
        from .temporal import eligible_feature
        try:
            data = Dataset.model_validate(svc().registry.dataset(dataset_id)["body"])
            selected,excluded = eligible_feature(data,feature_id,datetime.fromisoformat(decision_at.replace("Z","+00:00")))
            return {"selected":selected.model_dump(mode="json") if selected else None,"excluded":excluded,
                    "status":"SELECTED" if selected else "NO_ELIGIBLE_REVISION"}
        except ValueError:
            return JSONResponse(status_code=422,content={"code":"INVALID_ASOF_SELECTION"})

    @app.get("/v1/datasets/{dataset_id}")
    def dataset(dataset_id:str):
        return svc().dataset(dataset_id)

    @app.post("/v1/runs")
    def submit(body:RunConfig,idempotency_key:str=Header(min_length=1,max_length=128)):
        return svc().registry.submit(idempotency_key,body)

    @app.get("/v1/runs")
    def runs(limit:int=Query(10,ge=1,le=10),offset:int=Query(0,ge=0),dataset_id:str|None=None):
        return svc().registry.search(limit,offset,dataset_id)

    @app.get("/v1/runs/{run_id}")
    def run(run_id:uuid.UUID):
        return svc().registry.get(run_id)

    @app.post("/v1/runs/{run_id}/cancel")
    def cancel(run_id:uuid.UUID):
        return svc().registry.cancel(run_id)

    @app.get("/v1/runs/{run_id}/report")
    def report(run_id:uuid.UUID):
        return svc().report(run_id)

    @app.get("/v1/runs/{run_id}/evidence")
    def evidence(run_id:uuid.UUID):
        from .artifacts import verify
        s = svc()
        row = s.registry.get(run_id)
        if row["state"] != "completed":
            raise Conflict("REPORT_NOT_COMPLETE")
        s.report(run_id)  # includes DB-bound manifest verification
        return verify(s.artifacts.directory(row["artifact_ref"]))

    @app.get("/v1/compare")
    def compare(left:uuid.UUID,right:uuid.UUID):
        return svc().compare(left,right)

    return app


app = create_app()
