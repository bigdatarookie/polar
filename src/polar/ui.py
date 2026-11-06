"""Read-only, allowlisted retained-record projection for the selected UI."""
import json
import hashlib
import os
import re

from .artifacts import ArtifactError, verify
from .codec import digest
from .models import Dataset


class UIError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


def _fields(row, names):
    return {name: row[name] for name in names if name in row}


def _page(limit, offset):
    if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 10 or offset < 0:
        raise UIError("INVALID_PAGINATION", 422)


def _revision(value):
    return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}", value) else "UNKNOWN"


class UIProjection:
    def __init__(self, service):
        self.service = service

    def dataset(self, dataset_id):
        # Existing immutable rows make the second read stable. Never bypass the
        # original-bytes/canonical/ID/source-hash checks for this display path.
        identity = self.service.dataset(dataset_id)
        data = Dataset.model_validate(self.service.registry.dataset(dataset_id)["body"])
        instrument = data.instruments[0]
        return {
            "dataset_id": dataset_id, "content_hash": identity["content_hash"],
            "source_sha256": identity["source_hash"], "registered_at": identity["registered_at"],
            "name": data.dataset_name, "synthetic": data.synthetic,
            "market": data.market_profile.model_dump(mode="json"),
            "instrument": {"instrument_id": instrument.instrument_id, "currency": instrument.currency,
                "ticker_history": [_fields(t.model_dump(mode="json"),
                    ("ticker", "effective_from", "effective_until")) for t in instrument.ticker_history]},
            "sessions": [s.model_dump(mode="json") for s in data.sessions],
            "bars": [_fields(b.model_dump(mode="json"),
                ("session_id", "open", "high", "low", "close", "price_status", "tradable")) for b in data.bars],
            "inspection": identity["inspection"],
        }

    def datasets(self, limit=10, offset=0):
        _page(limit, offset)
        return {"items": [self.dataset(r["id"]) for r in self.service.registry.datasets(limit, offset)],
                "limit": limit, "offset": offset}

    def run(self, run_id, dataset_id=None):
        row = self.service.registry.get(run_id)
        if dataset_id is not None and dataset_id != row["dataset_id"]:
            raise UIError("RUN_DATASET_MISMATCH")
        dataset = self.dataset(row["dataset_id"])
        config = row["config"]
        if config.get("dataset_id") != dataset["dataset_id"]:
            raise UIError("RUN_DATASET_MISMATCH")
        result = {
            "schema_version": "polar.ui-run/1", "dataset": dataset,
            "run": {**_fields(row, ("id", "dataset_id", "state", "created_at")),
                    **_fields(config, ("strategy_version", "protocol_version"))},
            "report_availability": "AVAILABLE" if row["state"] == "completed" else "NOT_COMPLETE",
            "report": None, "evidence": None,
            "calculation_revision": "UNKNOWN", "api_revision": _revision(os.environ.get("POLAR_CODE_REVISION")),
        }
        if row["state"] != "completed":
            return result
        # Service.report verifies DB -> manifest bytes -> each retained file.
        report = self.service.report(run_id)
        directory = self.service.artifacts.directory(row["artifact_ref"])
        manifest_bytes = (directory / "manifest.json").read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != row["artifact_hash"]:
            raise ArtifactError("MANIFEST_HASH_MISMATCH")
        manifest = json.loads(manifest_bytes)
        if manifest != verify(directory):
            raise ArtifactError("MANIFEST_HASH_MISMATCH")
        if (manifest.get("run_id") != str(row["id"])
                or manifest.get("attempt_id") != str(row["attempt_id"])
                or manifest.get("report_hash") != digest(report)
                or report.get("dataset_id") != row["dataset_id"]
                or report.get("config_hash") != digest(config)
                or report.get("strategy_version") != config.get("strategy_version")
                or report.get("protocol_version") != config.get("protocol_version")):
            raise UIError("REPORT_IDENTITY_MISMATCH")
        try:
            environment_bytes = (directory / "environment.json").read_bytes()
            if hashlib.sha256(environment_bytes).hexdigest() != manifest["files"]["environment.json"]:
                raise ArtifactError("ARTIFACT_HASH_MISMATCH")
            environment = json.loads(environment_bytes)
            result["calculation_revision"] = _revision(environment.get("code_revision"))
        except (ValueError, TypeError, AttributeError):
            # Unknown historical revision is explicit, never replaced by API revision.
            result["calculation_revision"] = "UNKNOWN"
        result["evidence"] = {"manifest_sha256": row["artifact_hash"], "report_hash": manifest["report_hash"],
                              "run_id": manifest["run_id"], "attempt_id": manifest["attempt_id"]}
        # No environment/config/provenance/paths leak into the UI projection.
        result["report"] = {
            **_fields(report, ("schema_version", "status", "qualification", "financial_verdict", "units",
                "dataset_id", "strategy_version", "protocol_version", "config_hash", "initial_cash", "coverage")),
            "units": _fields(report.get("units", {}), ("cash", "nav", "quantity", "return", "fee")),
            "coverage": _fields(report.get("coverage", {}), ("expected_sessions", "present_bars", "observed_bars",
                "settlement_only_bars", "missing_price_sessions", "status")),
            "nav": [_fields(n, ("session_id", "at", "cash", "shares", "mark", "nav", "status", "price_status", "available_at")) for n in report.get("nav", [])],
            "fills": [_fields(f, ("instrument_id", "decision_session_id", "fill_at", "receipt_at", "price", "quantity", "fee", "currency"))
                      for f in report.get("fills", [])],
            "orders": [_fields(o, ("decision_session_id", "status", "reason")) for o in report.get("orders", [])],
            "order_tape": [_fields(o, ("decision_session_id", "decision_at", "quantity"))
                           for o in report.get("order_tape", [])],
            "metrics": {key: _fields(report.get("metrics", {}).get(key, {}),
                        ("value", "unit", "status", "evidence_status", "reason"))
                        for key in ("total_return", "sharpe_252", "max_drawdown", "fees")},
        }
        return result

    def runs(self, dataset_id, limit=10, offset=0):
        _page(limit, offset)
        self.service.dataset(dataset_id)  # missing/corrupt dataset is not an empty run page
        items = []
        for row in self.service.registry.search(limit, offset, dataset_id):
            view = self.service.ui_run(row["id"], dataset_id)
            report = view["report"]
            items.append({"run": view["run"], "report_availability": view["report_availability"],
                          "report_status": report["status"] if report else None,
                          "metrics": report["metrics"] if report else None})
        return {"items": items, "limit": limit, "offset": offset}
