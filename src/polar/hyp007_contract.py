"""Fixed HYP007 v1.1 contracts; no dependencies on numerical packages at import."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone

PROTOCOL = "60dbc42dacb9c75bf6c84be807787c1e909749fba262626e1b4529c34268717d"
RAW = "e01012bf694a78eeb11519032eaabd74f74ba0c0f4be0ac7e3edbc42e40532d8"
ACTIONS = "7492fc27210715d5867f271a982f9f248b4d70f1fc9f32c1ef4b8883eca2ae3b"
CALENDAR = "803aaef74549c4887ce7838a1667b7c5e3068e5d6ea661b421baa7331b2de1bb"
TZDATA = "d7f2206b3a45989fc9ad63d558922532fa7352280d5f87176bf1db79cb1d1fa9"
EVIDENCE = "691495dfebd31c041d48cb81c427a6c3726522028f48ac8b10ad44e960a65544"
FEATURES = ("RET1", "RET5", "MOM252_21", "VOL20", "DV_MEAN20", "DV_RATIO_PRIOR20")
COHORT = ("AAPL", "AMZN", "TSLA", "TWTR")
MODELS = ("ridge6", "ridge21", "tree")
FOLDS = (2022, 2023, 2024)
FAMILY = "hyp007-source-cohort-predictor-v1"  # independent of config/job/seed/revision
TARGET = "HYP007_DIAG_OPEN_WEALTH_RECEIVABLE_V1.1"
MAX_FILE = 32 * 1024**2
MAX_OUTPUT = 256 * 1024**2


class DiagnosticError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def check(predicate, code="HYP007_INVALID_INPUT"):
    if not predicate:
        raise DiagnosticError(code)


def exact(value, keys, schema=None):
    check(type(value) is dict and set(value) == set(keys))
    if schema is not None:
        check(value.get("schema") == schema)
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            check(k not in out, "HYP007_DUPLICATE_FIELD")
            out[k] = v
        return out
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: check(False, "HYP007_NONFINITE"))
    except (ValueError, UnicodeError, RecursionError):
        raise DiagnosticError("HYP007_INVALID_JSON") from None


def hexhash(value):
    check(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value), "HYP007_INVALID_HASH")
    return value


def finite(value):
    check(math.isfinite(value), "HYP007_NUMERICAL_INVALID")
    return value


def utc(value):
    check(type(value) is str and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", value),
          "HYP007_INVALID_TIME")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DiagnosticError("HYP007_INVALID_TIME") from None


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def now():
    return stamp(datetime.now(timezone.utc))


def definitions():
    return {"protocol": PROTOCOL, "features": list(FEATURES), "target": TARGET,
            "feature_manifest": "5316e711fe2af122e8b6b65a6a89db4748ff36c3bd4217e0a5ed0f036c5e043c",
            "terminal": "34d7fea739aa47615f9f172a0a4978ee43e3f991005f3cabc06aff95120993de",
            "calendar": CALENDAR, "tzdata": TZDATA, "raw": RAW, "actions": ACTIONS, "evidence": EVIDENCE,
            "known_by": "NY_MIDNIGHT_AFTER_TWO_STRICT_REFERENCE_SESSIONS/1",
            "assurance": ["REVISED_VINTAGE_BEST_EFFORT", "USD_AS_OWNER_REFERENCE_ASSUMPTION",
                          "PROVIDER_CASH_EX_DATES_AS_CONDITIONAL_BOUNDARIES",
                          "CAPTURED_SET_NO_OTHER_EVENT_CONDITIONAL", "NO_STRICT_PIT_CLAIM"],
            "masks": {"info": "GREATEST_COHERENT_READY_PACKET",
                      "train": "D_LT_F_MATURE_K_LE_F_PURGE_FIXED_OPEN_EDGES",
                      "score": "EVAL_YEAR_INFO_COMMON_READY_LE_ISSUE_INDEPENDENT_OF_LABEL",
                      "eval": "SCORE_FINITE_TARGET_K_LE_S_OBJECTS_BY_S"}}
