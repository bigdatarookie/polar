"""Private-owner history read routes; no admission, jobs, credentials or runtime writes."""
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .history_queries import HistoryReadError, MAX_RESPONSE_BYTES


def install_history_routes(app, service):
    @app.exception_handler(HistoryReadError)
    def history_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"code": exc.code})

    def call(request, allowed, operation, **kwargs):
        query = request.query_params
        if any(k not in allowed or len(query.getlist(k)) != 1 for k in query):
            raise HistoryReadError("HISTORY_INVALID_QUERY")
        try:
            owner = service()
        except (OSError, ValueError):
            raise HistoryReadError("HISTORY_DEPENDENCY_UNAVAILABLE", 503) from None
        result = owner.history_read(operation, **kwargs)
        response = JSONResponse(content=jsonable_encoder(result))
        if len(response.body) > MAX_RESPONSE_BYTES:
            raise HistoryReadError("HISTORY_RESPONSE_LIMIT", 503)
        return response

    @app.get("/v1/history/readyz")
    def ready(request: Request):
        return call(request, set(), "ready")

    @app.get("/v1/history/datasets")
    def catalog(request: Request, limit: str = "50", cursor: str | None = None):
        return call(request, {"limit", "cursor"}, "catalog", limit=limit, cursor=cursor)

    prefix = "/v1/history/datasets/{dataset_id}/revisions/{revision}"

    @app.get(prefix)
    def revision(request: Request, dataset_id: str, revision: str):
        return call(request, set(), "revision", dataset_id=dataset_id, revision=revision)

    @app.get(prefix + "/assets")
    def assets(request: Request, dataset_id: str, revision: str, limit: str = "50", cursor: str | None = None):
        return call(request, {"limit", "cursor"}, "assets", dataset_id=dataset_id, revision=revision, limit=limit, cursor=cursor)

    @app.get(prefix + "/bars")
    def bars(request: Request, dataset_id: str, revision: str, instrument_id: str, start: str, end: str,
             limit: str = "1000", warmup_sessions: str = "0", cursor: str | None = None):
        return call(request, {"instrument_id", "start", "end", "limit", "warmup_sessions", "cursor"}, "bars",
                    dataset_id=dataset_id, revision=revision, instrument_id=instrument_id, start=start, end=end,
                    limit=limit, warmup_sessions=warmup_sessions, cursor=cursor)

    @app.get(prefix + "/series")
    def series(request: Request, dataset_id: str, revision: str, instrument_id: str, start: str, end: str,
               limit: str = "1000", warmup_sessions: str = "0", cursor: str | None = None,
               sma_period: str | None = None, ema_period: str | None = None, bb_period: str | None = None,
               bb_deviation: str | None = None, rsi_period: str | None = None,
               benchmark_instrument_id: str = "hist-us-0004", reference_family: str = "RAW_PRICE_RELATIVE",
               basis: str = "RAW_CLOSE"):
        return call(request, {"instrument_id", "start", "end", "limit", "warmup_sessions", "cursor",
                    "sma_period", "ema_period", "bb_period", "bb_deviation", "rsi_period",
                    "benchmark_instrument_id", "reference_family", "basis"}, "series",
                    dataset_id=dataset_id, revision=revision, instrument_id=instrument_id, start=start, end=end,
                    limit=limit, warmup_sessions=warmup_sessions, cursor=cursor, sma_period=sma_period,
                    ema_period=ema_period, bb_period=bb_period, bb_deviation=bb_deviation, rsi_period=rsi_period,
                    benchmark_instrument_id=benchmark_instrument_id, reference_family=reference_family, basis=basis)

    @app.get("/v1/history/experiments/{experiment_id}")
    def experiment(request: Request, experiment_id: str):
        return call(request, set(), "experiment", experiment_id=experiment_id)

    @app.get("/v1/history/views/{view_id}")
    def experiment_view(request: Request, view_id: str):
        return call(request, set(), "experiment_view", view_id=view_id)

    @app.get("/v1/history/views/{view_id}/rows")
    def experiment_rows(request: Request, view_id: str, limit: str = "1000", cursor: str | None = None):
        return call(request, {"limit","cursor"}, "experiment_rows", view_id=view_id, limit=limit, cursor=cursor)

    @app.get("/v1/history/attempts/{attempt_id}")
    def experiment_attempt(request: Request, attempt_id: str):
        return call(request, set(), "experiment_attempt", attempt_id=attempt_id)
