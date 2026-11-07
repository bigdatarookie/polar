"""Bounded verification of captured private-history v1; never fetches or executes it."""
import hashlib
import json
import os
import re
import stat
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Context, Decimal, InvalidOperation
from pathlib import Path

MAX_BUNDLE = 64 * 1024**2
MAX_FILE = 4 * 1024**2
FIELDS = ("open", "high", "low", "close", "adjusted_close", "volume")
BASES = {"ohlc_basis": "VENDOR_RAW_UNADJUSTED",
         "adjusted_close_basis": "VENDOR_SPLIT_AND_DIVIDEND_ADJUSTED",
         "volume_basis": "VENDOR_SPLIT_ADJUSTED", "price_unit": "USD/share",
         "volume_unit": "split-adjusted shares"}
ASSETS = [("hist-us-0001", "AAPL.US", "equity"), ("hist-us-0002", "AMZN.US", "equity"),
          ("hist-us-0003", "TSLA.US", "equity"), ("hist-us-0004", "VTI.US", "ETF")]


class HistoryError(ValueError):
    """Stable codes only; never expose source bodies or local paths."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code="HISTORY_INVALID_BUNDLE"):
    if not condition:
        raise HistoryError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "HISTORY_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def invalid_constant(value):
    raise HistoryError("HISTORY_NONFINITE_JSON")


class Token(str):
    pass


def decode(raw, source=False):
    try:
        return json.loads(raw, object_pairs_hook=object_pairs, parse_constant=invalid_constant,
                          **({"parse_int": Token, "parse_float": Token} if source else {}))
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, HistoryError):
            raise
        raise HistoryError("HISTORY_INVALID_JSON") from None


def hex_hash(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value), "HISTORY_INVALID_HASH")
    return value


def identifier(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", value), "HISTORY_INVALID_ID")
    return value


def revision_id(value):
    require(type(value) is str and value.startswith("histrev-"), "HISTORY_INVALID_REVISION")
    hex_hash(value[8:])
    return value


def label(value):
    require(type(value) is str and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value))
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HistoryError("HISTORY_INVALID_DATE") from None


def clock(value):
    require(type(value) is str and re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)",
        value), "HISTORY_INVALID_RECEIPT_CLOCK")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        raise HistoryError("HISTORY_INVALID_RECEIPT_CLOCK") from None
    require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), "HISTORY_INVALID_RECEIPT_CLOCK")
    return parsed


def numeric(value, field):
    require(type(value) in (str, Token) and len(value) <= 40 and
            re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value),
            "HISTORY_INVALID_NUMBER")
    try:
        n = Decimal(value, context=Context(traps=[InvalidOperation]))
        require(n.is_finite() and n.as_tuple().exponent >= -18, "HISTORY_NUMBER_BOUNDS")
        require(Decimal(0) <= n <= Decimal("1e18" if field == "volume" else "1e12"),
                "HISTORY_NUMBER_BOUNDS")
        require(n != 0 if field != "volume" else n == n.to_integral_value(context=Context(prec=80)),
                "HISTORY_NUMBER_BOUNDS")
        return n
    except ArithmeticError:
        raise HistoryError("HISTORY_NUMBER_BOUNDS") from None


def audit_rows(source, instrument, symbol, snapshot_id, raw_hash, profile):
    """Audit the frozen producer's records/reasons, without executing its normalizer."""
    indexed_dates = Counter(row.get("date") for row in source
                            if isinstance(row, dict) and isinstance(row.get("date"), str))
    valid, quarantine, extra_fields, source_order = [], [], set(), []
    for index, original in enumerate(source):
        reasons, numbers = [], {}
        if type(original) is not dict:
            reasons.append("ROW_OBJECT_REQUIRED")
        else:
            extra_fields.update(set(original) - {"date", *FIELDS})
            try:
                session = label(original.get("date")).isoformat()
                if not profile["request_start_inclusive"] <= session <= profile["request_end_inclusive"]:
                    reasons.append("OUTSIDE_REQUEST_RANGE")
                if indexed_dates[session] > 1:
                    reasons.append("DUPLICATE_ASSET_DATE")
            except HistoryError:
                reasons.append("INVALID_SESSION_DATE")
            for field in FIELDS:
                try:
                    require(type(original.get(field)) is Token, "HISTORY_SOURCE_NUMERIC_TOKEN")
                    numbers[field] = numeric(original[field], field)
                except HistoryError:
                    reasons.append("INVALID_"+field.upper())
            if all(k in numbers for k in ("open", "high", "low", "close")):
                if (numbers["high"] < max(numbers["open"], numbers["close"]) or
                        numbers["low"] > min(numbers["open"], numbers["close"]) or numbers["high"] < numbers["low"]):
                    reasons.append("OHLC_RANGE")
        if reasons:
            quarantine.append({"source_row_index": index, "reasons": sorted(set(reasons)), "row": original})
        else:
            source_order.append(session)
            valid.append({"instrument_id": instrument, "source_symbol": symbol,
                "source_snapshot_id": snapshot_id, "raw_object_sha256": raw_hash,
                "source_row_index": index, "session_date": session,
                **{k: str(original[k]) for k in FIELDS}, "event_at": None, "published_at": None,
                "historical_available_at": None, "source_revision": None, "source_status": "OBSERVED"})
    valid.sort(key=lambda row: row["session_date"])
    dates = [row["session_date"] for row in valid]
    gaps = []
    for left, right in zip(dates, dates[1:]):
        day = label(left) + timedelta(days=1)
        while day.isoformat() < right:
            gaps.append(day.isoformat())
            day += timedelta(days=1)
    report = {"instrument_id": instrument, "source_symbol": symbol, "raw_rows": len(source),
        "valid_unique_rows": len(valid), "quarantined_rows": len(quarantine),
        "duplicate_keys": sum(n > 1 for n in indexed_dates.values()),
        "duplicate_rows": sum(n for n in indexed_dates.values() if n > 1),
        "quarantine_reason_counts": dict(Counter(reason for q in quarantine for reason in q["reasons"])),
        "extra_source_fields": sorted(extra_fields), "source_order_ascending": source_order == sorted(source_order),
        "first_valid_date": dates[0] if dates else None, "last_valid_date": dates[-1] if dates else None,
        "observed_rows_by_year": dict(Counter(d[:4] for d in dates)), "calendar_status": "UNVERIFIED",
        "expected_sessions": None, "missing_expected_sessions": None, "missing_fraction": None,
        "qualified_ten_year_continuity": "UNVERIFIED", "calendar_days_without_observation_between_edges": gaps,
        "requested_start_inclusive": profile["request_start_inclusive"],
        "requested_end_inclusive": profile["request_end_inclusive"],
        "unobserved_requested_edges": {"leading": not dates or dates[0] != profile["request_start_inclusive"],
                                       "trailing": not dates or dates[-1] != profile["request_end_inclusive"]},
        "weekend_observation_dates": [d for d in dates if label(d).weekday() > 4],
        "ten_year_date_span": bool(dates and (label(dates[-1])-label(dates[0])).days >= 3653)}
    return valid, quarantine, report, set(dates)


def relative(value):
    require(type(value) is str and value and "\\" not in value and
            all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) and part not in (".", "..")
                for part in value.split("/")), "HISTORY_INVALID_PATH")
    return value


def safe_root(directory):
    directory = Path(directory).absolute()
    require(all(not p.is_symlink() for p in (directory, *directory.parents)), "HISTORY_SYMLINK")
    require(directory.is_dir(), "HISTORY_DIRECTORY_MISSING")
    return directory


def read_file(root, name, limit=MAX_FILE):
    parts = relative(name).split("/")
    opened = []
    try:
        # Open each component relative to a retained descriptor: symlink swaps
        # between the check and read cannot redirect this snapshot outside root.
        opened.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in parts[:-1]:
            opened.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=opened[-1]))
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=opened[-1])
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, "HISTORY_FILE_LIMIT")
            raw = stream.read(limit + 1)
        require(len(raw) <= limit, "HISTORY_FILE_LIMIT")
        return raw
    except OSError:
        raise HistoryError("HISTORY_UNSAFE_OR_MISSING_FILE") from None
    finally:
        for fd in reversed(opened):
            os.close(fd)


@dataclass(frozen=True)
class VerifiedBundle:
    dataset_id: str
    revision: str
    receipt_id: str
    manifest_hash: str
    files: dict
    content_files: frozenset
    summary: dict


def verify_files(files, expected_manifest_hash):
    """All input bytes are bounded snapshots; no TOCTOU reread during publication."""
    try:
        return _verify_files(files, expected_manifest_hash)
    except (KeyError, TypeError, IndexError, AttributeError, OverflowError):
        raise HistoryError("HISTORY_INVALID_BUNDLE") from None


def _verify_files(files, expected_manifest_hash):
    hex_hash(expected_manifest_hash)
    require(len(files) == 28 and sum(map(len, files.values())) <= MAX_BUNDLE, "HISTORY_BUNDLE_LIMIT")
    require(sha(files["bundle-manifest.json"]) == expected_manifest_hash, "HISTORY_MANIFEST_HASH")
    bundle = decode(files["bundle-manifest.json"])
    content = bundle["content"]
    revision = revision_id(bundle["dataset_revision"])
    require(revision == "histrev-" + sha(canonical(content)), "HISTORY_REVISION_HASH")
    dataset = identifier(bundle["dataset_id"])
    require(dataset == content["dataset_id"] and content["format"] == "polar.private-history-bundle/1")
    require(bundle["artifact_status"] == "COMPLETE_AUTHOR_VALIDATED" and bundle["api_ui_status"] == "NOT_READY")
    for key, value in BASES.items():
        require(content[key] == value, "HISTORY_BASIS_MISMATCH")
    require(content["calendar_status"] == "UNVERIFIED" and content["calendar_id"] is None)
    profile = decode(files["profile.json"])
    require(sha(files["profile.json"]) == content["profile_sha256"] and
            sha(files["acquire-qualify-v1.py"]) == content["normalizer_sha256"], "HISTORY_PROFILE_HASH")
    require(profile["profile_version"] == "polar.private-eodhd-acquisition/1" and
            profile["dataset_id"] == dataset and profile["source_id"] == "eodhd-public-demo" and
            profile["rights_scope"] == "OWNER_ONLY_PRIVATE_NONCOMMERCIAL")
    for key in (*BASES, "source_selection_sha256", "import_contract_sha256", "hyp007_addendum_sha256"):
        require(profile[key] == content[key], "HISTORY_PROFILE_MISMATCH")
    require(profile["request_start_inclusive"] == "2015-11-02" and
            profile["request_end_inclusive"] == "2026-11-06")
    require([(a["instrument_id"], a["source_symbol"], a["instrument_type"])
             for a in profile["assets"]] == ASSETS)

    content_files = {"profile.json", "acquire-qualify-v1.py", "raw-snapshot.json"}
    expected = set(content_files) | {"bundle-manifest.json", "import-receipt.json", "environment.json"}

    def bound(obj, path):
        require(obj["path"] == path, "HISTORY_OBJECT_PATH")
        raw = files[path]
        require(type(obj["bytes"]) is int and len(raw) == obj["bytes"] and
                sha(raw) == hex_hash(obj["sha256"]), "HISTORY_OBJECT_HASH")
        expected.add(path)
        return raw

    instruments = decode(bound(content["instruments"], "instruments.json"))
    require(instruments == [{**a, "currency": "USD", "effective_from": None, "effective_until": None,
                            "mapping_status": "DECLARED_CURRENT_ONLY",
                            "evidence_sha256": profile["source_selection_sha256"]} for a in profile["assets"]])
    quality = decode(bound(content["quality"], "quality.json"))
    snapshot = decode(files["raw-snapshot.json"])
    snapshot_id = "raw-" + sha(canonical(snapshot["content"]))
    require(snapshot_id == snapshot["source_snapshot_id"] == content["source_snapshot_id"], "HISTORY_SNAPSHOT_HASH")
    require(snapshot["content"]["source_id"] == profile["source_id"])
    receipt_raw = bound(bundle["acquisition_receipt"], "import-receipt.json")
    receipt_id = sha(receipt_raw)
    receipt = decode(receipt_raw)
    require(receipt["dataset_revision"] == revision and receipt["source_snapshot_id"] == snapshot_id,
            "HISTORY_RECEIPT_IDENTITY")
    started, completed = clock(receipt["import_started_at"]), clock(receipt["import_completed_at"])
    require(started <= completed, "HISTORY_RECEIPT_CLOCK_ORDER")
    require(len(content["bars"]) == len(receipt["requests"]) == len(snapshot["content"]["requests"]) ==
            len(quality["assets"]) == 4)
    summaries, date_sets = [], []
    for i, (instrument, symbol, kind) in enumerate(ASSETS):
        request = receipt["requests"][i]
        raw_obj = request["raw_object"]
        raw_path = "raw/" + hex_hash(raw_obj["sha256"]) + ".json"
        raw = bound(raw_obj, raw_path)
        require(len(raw) <= MAX_FILE)
        source = decode(raw, source=True)
        require(type(source) is list and len(source) <= 5000, "HISTORY_ROW_LIMIT")
        url = (f"https://eodhd.com/api/eod/{symbol}?api_token=demo&from=2015-11-02"
               "&to=2026-11-06&period=d&order=a&fmt=json")
        require(snapshot["content"]["requests"][i] == {"instrument_id": instrument,
                "raw_object": raw_obj, "url": url})
        require(request["instrument_id"] == instrument and request["url"] == url and
                request["request_number"] == i + 1 and request["http_status"] == 200 and
                request["complete_body"] is True)
        require(started <= clock(request["acquisition_started_at"]) <=
                clock(request["acquisition_completed_at"]) <= completed, "HISTORY_RECEIPT_CLOCK_ORDER")
        complete_name, start_name = f"receipts/{symbol}-complete.json", f"receipts/{symbol}-start.json"
        expected.update((complete_name, start_name))
        require(decode(files[complete_name]) == request)
        require(decode(files[start_name]) == {k: request[k] for k in
                ("instrument_id", "request_number", "url", "acquisition_started_at")})
        bar_path = f"bars/{instrument}.ndjson"
        lines = bound(content["bars"][i], bar_path).splitlines()
        quarantine = f"quarantine/{instrument}.json"
        expected.add(quarantine)
        valid, quarantined, checks, dates = audit_rows(source, instrument, symbol, snapshot_id,
                                                      raw_obj["sha256"], profile)
        require(len(lines) == len(valid), "HISTORY_ROW_COUNT")
        require(canonical([decode(line) for line in lines]) == canonical(valid), "HISTORY_ROW_PROVENANCE")
        # Audit every field, token and reason; producer JSON has a trailing newline.
        # Preserve original q bytes separately in the publication inventory/hash.
        require(canonical(decode(files[quarantine])) == canonical(quarantined), "HISTORY_QUARANTINE_PROVENANCE")
        require(len(source) == len(valid) + len(quarantined), "HISTORY_ROW_COUNT")
        report = quality["assets"][i]
        require(canonical({k: report[k] for k in checks}) == canonical(checks), "HISTORY_QUALITY_COUNTS")
        summaries.append({**instruments[i], "row_count": len(valid), "raw_rows": len(source),
                          "quarantined_rows": len(quarantined), "duplicate_keys": checks["duplicate_keys"],
                          "duplicate_rows": checks["duplicate_rows"],
                          "quarantine_reason_counts": checks["quarantine_reason_counts"],
                          "chart_fitness": "READY_WITH_LIMITS" if valid else "NOT_READY",
                          "first_date": checks["first_valid_date"], "last_date": checks["last_valid_date"],
                          "expected_sessions": None, "calendar_status": "UNVERIFIED",
                          "qualified_ten_year_continuity": "UNVERIFIED"})
        date_sets.append(dates)
        content_files.update((raw_path, bar_path, quarantine))
    content_files.update(("quality.json", "instruments.json"))
    total = sum(a["row_count"] for a in summaries)
    raw_total = sum(a["raw_rows"] for a in summaries)
    quarantine_total = sum(a["quarantined_rows"] for a in summaries)
    structural = "VALID" if all(a["row_count"] and not a["quarantined_rows"] for a in summaries) else "QUARANTINED"
    counts = {"total_raw_rows": raw_total, "total_valid_rows": total,
              "total_quarantined_rows": quarantine_total, "structural_status": structural}
    require(raw_total <= 20000 and raw_total == total + quarantine_total and
            canonical({k: quality[k] for k in counts}) == canonical(counts), "HISTORY_QUALITY_COUNTS")
    require(quality["cross_asset_union_session_count"] == len(set.union(*date_sets)) and
            quality["cross_asset_common_session_count"] == len(set.intersection(*date_sets)) and
            quality["cross_asset_absent_dates"] == {a[0]: sorted(set.union(*date_sets)-dates)
                                                       for a, dates in zip(ASSETS, date_sets)})
    for key, value in {"calendar_qualification": "UNVERIFIED", "historical_known_by": "UNKNOWN_NULL",
                       "rights_status": "ADMITTED_OWNER_PRIVATE_ONLY", "causal_PIT_fitness": "INSUFFICIENT_EVIDENCE",
                       "financial_evaluation": "NOT_RUN", "price_basis": BASES["ohlc_basis"],
                       "adjusted_close_basis": BASES["adjusted_close_basis"], "volume_basis": BASES["volume_basis"]}.items():
        require(quality[key] == value, "HISTORY_QUALITY_STATUS")
    require(set(files) == expected, "HISTORY_FILE_SET")
    summary = {"schema_version": "polar.history-revision/1", "dataset_id": dataset,
               "dataset_revision": revision, "import_receipt_id": receipt_id,
               "manifest_sha256": expected_manifest_hash, "basis": BASES,
               "instruments": summaries, "row_count": total, "raw_rows": raw_total,
               "quarantined_rows": quarantine_total, "calendar_status": "UNVERIFIED",
               "fitness": {"rights_status": "ADMITTED", "structural_status": structural,
                           "chart_fitness": "READY_WITH_LIMITS" if total else "NOT_READY",
                           "retrospective_analysis_fitness": "NOT_ASSESSED",
                           "causal_PIT_fitness": "INSUFFICIENT_EVIDENCE", "financial_evaluation": "NOT_RUN"},
               "rights_scope": "OWNER_ONLY_PRIVATE_NONCOMMERCIAL",
               "import_started_at": receipt["import_started_at"], "import_completed_at": receipt["import_completed_at"]}
    return VerifiedBundle(dataset, revision, receipt_id, expected_manifest_hash, files, frozenset(content_files), summary)


def verify_bundle(directory, expected_manifest_hash):
    root = safe_root(directory)
    files = {}
    for path in root.rglob("*"):
        require(not path.is_symlink(), "HISTORY_SYMLINK")
        if path.is_file():
            require(len(files) < 28, "HISTORY_FILE_SET")
            name = str(path.relative_to(root))
            files[name] = read_file(root, name)
            require(sum(map(len, files.values())) <= MAX_BUNDLE, "HISTORY_BUNDLE_LIMIT")
    return verify_files(files, expected_manifest_hash)
