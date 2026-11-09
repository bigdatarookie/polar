"""Versioned metadata-loader contracts. No provider access on import or plan."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone

ENDPOINT = "https://api.openfigi.com/v3/mapping"
ADAPTER = "openfigi-ticker-us-unlisted/1"
PROFILE = "anonymous-per-ip/1"
ROUTE_POLICY = "4e8032ce5268d9838b027d3ec9c7287c4702a2cc75b5f618b6caad9a279ba4db"
MAX_FILE = 32*1024**2
MAX_RESPONSE = 2*1024**2
MAX_NEW_BYTES = 32*1024**2
POLICY = {"schema": "polar.import-policy/1", "cutover": "anonymous-remaining-v019/1",
          "batch_size": 10, "minimum_start_seconds": 3, "window_seconds": 60,
          "requests_per_window": 25, "initial_unknown_quota_wait": 60,
          "max_posts": 160, "max_job_appearances": 4, "request_seconds": 45,
          "operation_seconds": 900, "backoff_base_seconds": 2, "backoff_cap_seconds": 30,
          "jitter_max_seconds": 1, "rate_safety_seconds": 1,
          "max_response_bytes": MAX_RESPONSE, "max_new_response_bytes": MAX_NEW_BYTES}


class ImportError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code="IMPORT_INVALID_INPUT"):
    if not value:
        raise ImportError(code)


def exact(value, fields):
    require(type(value) is dict and set(value) == set(fields))
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def wire(value):
    return canonical(value)+b"\n"  # retained producer's original encoder, distinct from key encoding


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(values):
        result = {}
        for key,value in values:
            require(key not in result, "IMPORT_DUPLICATE_FIELD")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, "IMPORT_NONFINITE"))
    except (ValueError, UnicodeError, RecursionError):
        raise ImportError("IMPORT_INVALID_JSON") from None


def digest(value):
    return sha(canonical(value))


def hash_value(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}",value), "IMPORT_INVALID_ID")
    return value


def timestamp(seconds=None):
    value = datetime.now(timezone.utc) if seconds is None else datetime.fromtimestamp(seconds, timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def seconds(value):
    require(type(value) is str and len(value) < 64, "IMPORT_INVALID_TIME")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "IMPORT_INVALID_TIME")
        return parsed.timestamp()
    except ValueError:
        raise ImportError("IMPORT_INVALID_TIME") from None


def request(symbol):
    require(type(symbol) is str and 0 < len(symbol) <= 100 and not any(ord(c)<32 for c in symbol),
            "IMPORT_INVALID_SYMBOL")
    return {"idType": "TICKER", "idValue": symbol, "exchCode": "US", "includeUnlistedEquities": True}


def validate_request(value):
    require(type(value) is dict and value == request(value.get("idValue")), "IMPORT_REQUEST_SEMANTICS")
    require(type(value["includeUnlistedEquities"]) is bool, "IMPORT_REQUEST_SEMANTICS")
    return value


def job_id(value):
    validate_request(value)
    return digest({"schema": "polar.import-job-key/1", "adapter": ADAPTER, "profile": PROFILE,
                   "endpoint": ENDPOINT, "request": value})


def result_kind(item):
    require(type(item) is dict, "IMPORT_MALFORMED_POSITIONAL")
    if "data" in item:
        require(type(item["data"]) is list and item["data"] and
                all(type(row) is dict for row in item["data"]) and "error" not in item,
                "IMPORT_MALFORMED_POSITIONAL")
        return "CANDIDATES"
    if "warning" in item and type(item["warning"]) is str and "error" not in item:
        return "WARNING_NO_MATCH" if item["warning"]=="No identifier found." else "PROVIDER_JOB_ERROR"
    if "error" in item and type(item["error"]) is str:
        return "PROVIDER_JOB_ERROR"
    raise ImportError("IMPORT_MALFORMED_POSITIONAL")


def alignment(body, requests):
    value = decode(body)
    require(type(value) is list and len(value) == len(requests), "IMPORT_MALFORMED_POSITIONAL")
    kinds = [result_kind(item) for item in value]  # validate EVERY position before assigning ANY result
    return value,kinds


def scope_id():
    return digest({"adapter": ADAPTER, "profile": PROFILE, "endpoint": ENDPOINT})


def config(value):
    exact(value, {"schema", "adapter", "mode", "requests", "policy", "route_evidence"})
    require(value["schema"] == "polar.import-config/1" and value["policy"] == POLICY and
            value["adapter"] == ADAPTER and value["mode"] in ("fixture","provider"), "IMPORT_POLICY_MISMATCH")
    require(type(value["requests"]) is list and 0 < len(value["requests"]) <= 100000)
    ids = [job_id(r) for r in value["requests"]]
    require(len(set(ids)) == len(ids), "IMPORT_DUPLICATE_JOB")
    exact(value["route_evidence"], {"path", "sha256"})
    hash_value(value["route_evidence"]["sha256"])
    if value["mode"]=="provider":
        require(value["route_evidence"]["sha256"]==ROUTE_POLICY,"IMPORT_ROUTE_POLICY_NOT_BOUND")
    return value
