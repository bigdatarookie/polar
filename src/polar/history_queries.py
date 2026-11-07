"""Read-only bounded history projections, independent of fixture/numeric engines."""
import base64
import json
import re
from bisect import bisect_left

from .history_bundle import HistoryError, canonical, decode, identifier, label, revision_id, sha

MAX_RESPONSE_BYTES = 1024**2


class HistoryReadError(Exception):
    def __init__(self, code, status=422):
        self.code, self.status = code, status
        super().__init__(code)


def invalid(condition, code="HISTORY_INVALID_QUERY"):
    if not condition:
        raise HistoryReadError(code)


def integer(value, minimum, maximum):
    invalid(type(value) is str and re.fullmatch(r"0|[1-9][0-9]*", value) and len(value) <= 10)
    number = int(value)
    invalid(minimum <= number <= maximum)
    return number


def pinned(dataset_id, revision):
    try:
        identifier(dataset_id)
        revision_id(revision)
    except HistoryError:
        raise HistoryReadError("HISTORY_INVALID_QUERY") from None


def wire(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def cursor_text(cursor):
    invalid(type(cursor) is str and cursor and len(cursor.encode()) <= 2048, "HISTORY_INVALID_CURSOR")


def cursor_position(cursor, projection, identity, keys):
    if cursor is None:
        return 0
    cursor_text(cursor)
    try:
        page = decode(base64.b64decode(cursor, altchars=b"-_", validate=True))
        invalid(type(page) is dict and set(page) == {"version", "projection", "request_identity", "last"},
                "HISTORY_INVALID_CURSOR")
        invalid(page["version"] == "polar.history-cursor/1" and page["projection"] == projection and
                page["request_identity"] == identity and type(page["last"]) is str,
                "HISTORY_INVALID_CURSOR")
        index = keys.index(page["last"])
        invalid(index < len(keys)-1, "HISTORY_INVALID_CURSOR")
        return index + 1
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HistoryReadError("HISTORY_INVALID_CURSOR") from None


def page_rows(rows, keys, limit, cursor, projection, identity, make):
    offset = cursor_position(cursor, projection, identity, keys)

    def build(count):
        stop = offset + count
        next_cursor = None
        if stop < len(rows):
            next_cursor = base64.urlsafe_b64encode(canonical({"version": "polar.history-cursor/1",
                "projection": projection, "request_identity": identity, "last": keys[stop-1]})).decode()
        return make(rows[offset:stop], next_cursor, stop == len(rows))

    if not rows:
        result = make([], None, True)
    else:
        maximum = min(limit, len(rows)-offset)
        candidate = build(maximum)
        if len(wire(candidate)) <= MAX_RESPONSE_BYTES:
            return candidate
        low, high, best = 1, maximum-1, None
        while low <= high:
            count = (low+high)//2
            candidate = build(count)
            if len(wire(candidate)) <= MAX_RESPONSE_BYTES:
                best, low = candidate, count+1
            else:
                high = count-1
        if best is None:
            raise HistoryReadError("HISTORY_RESPONSE_LIMIT", 503)
        result = best
    if len(wire(result)) > MAX_RESPONSE_BYTES:
        raise HistoryReadError("HISTORY_RESPONSE_LIMIT", 503)
    return result


def identity_fields(summary):
    return {k: summary[k] for k in ("dataset_id", "dataset_revision", "import_receipt_id", "manifest_sha256", "basis")}


class HistoryQueries:
    def __init__(self, registry):
        self.registry = registry

    def catalog(self, limit="50", cursor=None):
        count = integer(limit, 1, 50)
        if cursor is not None:
            cursor_text(cursor)
        return self.registry.catalog(count, cursor)

    def revision(self, dataset_id, revision):
        pinned(dataset_id, revision)
        return self.registry.revision(dataset_id, revision)

    def assets(self, dataset_id, revision, limit="50", cursor=None):
        pinned(dataset_id, revision)
        count = integer(limit, 1, 50)
        if cursor is not None:
            cursor_text(cursor)
        summary = self.registry.revision(dataset_id, revision)
        base = identity_fields(summary)
        identity = sha(canonical({**base, "projection": "assets/1", "limit": count}))
        rows = sorted(summary["instruments"], key=lambda item:item["instrument_id"])
        def make(items, next_cursor, complete):
            return {"schema_version": "polar.history-assets/1", **base, "request_identity": identity,
                    "items": items, "item_count": len(items), "fitness": summary["fitness"],
                    "next_cursor": next_cursor}
        return page_rows(rows, [r["instrument_id"] for r in rows], count, cursor, "assets/1", identity, make)

    def bars(self, dataset_id, revision, instrument_id, start, end, limit="1000", warmup_sessions="0", cursor=None):
        pinned(dataset_id, revision)
        count, requested = integer(limit, 1, 1000), integer(warmup_sessions, 0, 2500)
        if cursor is not None:
            cursor_text(cursor)
        try:
            identifier(instrument_id)
            first, last = label(start), label(end)
        except HistoryError:
            raise HistoryReadError("HISTORY_INVALID_QUERY") from None
        invalid(first < last and (last-first).days <= 20*366)
        summary, bundle = self.registry.load_revision(dataset_id, revision)
        asset = next((a for a in summary["instruments"] if a["instrument_id"] == instrument_id), None)
        if asset is None:
            raise HistoryReadError("HISTORY_ASSET_NOT_FOUND", 404)
        bars = [decode(line) for line in bundle.files[f"bars/{instrument_id}.ndjson"].splitlines()]
        dates = [row["session_date"] for row in bars]
        begin, stop = bisect_left(dates, start), bisect_left(dates, end)
        prior = max(0, begin-requested)
        available = begin-prior
        selected = bars[prior:stop]
        rows = []
        for original in selected:
            row = {k: original[k] for k in ("session_date", "open", "high", "low", "close", "adjusted_close", "volume",
                    "event_at", "historical_available_at", "source_row_index", "source_snapshot_id", "raw_object_sha256")}
            row.update({"row_role": "WARMUP" if row["session_date"] < start else "VISIBLE",
                        "publication_at": original["published_at"], "price_status": "OBSERVED", "volume_status": "OBSERVED",
                        "price_reason": None, "volume_reason": None})
            rows.append(row)
        base = identity_fields(summary)
        window = {"start": start, "end_exclusive": end}
        identity = sha(canonical({**base, "instrument_id": instrument_id, "window": window,
                                  "warmup_sessions": requested, "limit": count, "projection": "bars/1"}))
        status = ("NOT_REQUESTED" if not requested else "INSUFFICIENT_HISTORY" if available < requested
                  else "UNRESOLVED" if asset["calendar_status"] != "QUALIFIED" else "SUFFICIENT")
        data_status = "EMPTY_WINDOW" if stop == begin else "PARTIAL" if asset["quarantined_rows"] else "OBSERVED"
        coverage = {"observed_in_window": stop-begin, "observed_total": asset["row_count"],
                    "first_date": asset["first_date"], "last_date": asset["last_date"],
                    "calendar_status": asset["calendar_status"], "expected_sessions": None,
                    "missing_expected_sessions": None, "missing_fraction": None,
                    "quarantined_rows": asset["quarantined_rows"], "duplicate_rows": asset["duplicate_rows"],
                    "quarantine_reason_counts": asset["quarantine_reason_counts"], "quality_scope": "REVISION_ASSET"}
        fitness = {**summary["fitness"], "chart_fitness": asset["chart_fitness"]}
        def make(items, next_cursor, complete):
            return {"schema_version": "polar.history-bars/1", **base, "instrument_id": instrument_id,
                    "request_identity": identity, "window": window, "rows": items, "row_count": len(items),
                    "data_status": data_status, "warmup": {"requested": requested, "available": available,
                    "returned": sum(r["row_role"] == "WARMUP" for r in items), "status": status,
                    "count_basis": "ADMITTED_OBSERVATIONS", "calendar_status": asset["calendar_status"]},
                    "coverage": coverage, "fitness": fitness, "next_cursor": next_cursor, "window_complete": complete}
        return page_rows(rows, [r["session_date"]+":"+r["row_role"] for r in rows],
                         count, cursor, "bars/1", identity, make)

    def ready(self):
        # A verifies extension/legacy DB and the first chart-ready publication.
        # No claim about every dataset, indicators, independent QA or financial fitness.
        page = self.registry.catalog(1)
        from .history_bundle import safe_root
        import os
        root = safe_root(self.registry.store.root)
        if not os.access(root, os.R_OK | os.X_OK):
            raise HistoryReadError("HISTORY_DEPENDENCY_UNAVAILABLE", 503)
        return {"status": "READY", "scope": "HISTORY_READ_DEPENDENCIES", "history_schema_version": 1,
                "chart_data_available": bool(page["items"]), "probe": "FIRST_CHART_READY_REVISION",
                "independent_qualification": "NOT_ASSERTED", "financial_evaluation": "NOT_RUN"}
