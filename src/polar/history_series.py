"""Bounded, full-prefix retrospective series projection, with authenticated pagination."""
from bisect import bisect_left
from decimal import Decimal, InvalidOperation, Context
import re

from .history_bundle import (BASES, HistoryError, canonical, decode, identifier, label, require, sha)
from .history_calendar import reference_calendar
from .history_numeric import (DEFINITION_SHA256, NUMERIC_VERSION, derived_text, indicators, references)
from .history_queries import HistoryReadError, cursor_text, identity_fields, integer, invalid, page_rows, pinned

CALCULATION_VERSION = "polar.history-calculation/1"


def parameters(sma_period, ema_period, bb_period, bb_deviation, rsi_period, basis, reference_family):
    invalid(basis == "RAW_CLOSE" and reference_family in
            {"RAW_PRICE_RELATIVE", "PROVIDER_ADJUSTED_CLOSE_INDEX"})
    periods = {key: integer(value, 2, 500) if value is not None else None for key, value in
               (("sma", sma_period), ("ema", ema_period), ("bb", bb_period), ("rsi", rsi_period))}
    invalid(bb_deviation is None or bb_period is not None)
    text = bb_deviation if bb_deviation is not None else "2"
    invalid(type(text) is str and len(text) <= 40 and
            re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", text))
    try:
        deviation = Decimal(text, context=Context(traps=[InvalidOperation]))
        invalid(deviation.is_finite() and deviation.as_tuple().exponent >= -18 and 0 < deviation <= 10)
    except ArithmeticError:
        raise HistoryReadError("HISTORY_INVALID_QUERY") from None
    effective = {key+"_period": value for key, value in periods.items()}
    return periods, deviation, {**effective, "bb_deviation": derived_text(deviation) if periods["bb"] else None,
        "basis": basis, "reference_family": reference_family}


def admitted_rows(bundle, instrument_id):
    raw = bundle.files["bars/"+instrument_id+".ndjson"]
    rows = [decode(line) for line in raw.splitlines()]
    dates = [row["session_date"] for row in rows]
    require(len(rows) <= 5000 and dates == sorted(set(dates)), "HISTORY_AMBIGUOUS_SERIES")
    for session in dates:
        label(session)
    return rows


def series(owner, dataset_id, revision, instrument_id, start, end, limit="1000", warmup_sessions="0",
           cursor=None, sma_period=None, ema_period=None, bb_period=None, bb_deviation=None, rsi_period=None,
           benchmark_instrument_id="hist-us-0004", reference_family="RAW_PRICE_RELATIVE", basis="RAW_CLOSE"):
    pinned(dataset_id, revision)
    count, requested = integer(limit, 1, 1000), integer(warmup_sessions, 0, 2500)
    periods, deviation, effective = parameters(sma_period, ema_period, bb_period, bb_deviation,
                                               rsi_period, basis, reference_family)
    try:
        identifier(instrument_id); identifier(benchmark_instrument_id)
        first, last = label(start), label(end)
    except HistoryError:
        raise HistoryReadError("HISTORY_INVALID_QUERY") from None
    invalid(first < last and (last-first).days <= 20*366)
    codec = owner.codec
    if cursor is not None:
        cursor_text(cursor)
    summary, bundle = owner.registry.load_revision(dataset_id, revision)
    assets = {a["instrument_id"]: a for a in summary["instruments"]}
    if instrument_id not in assets or benchmark_instrument_id not in assets:
        raise HistoryReadError("HISTORY_ASSET_NOT_FOUND", 404)
    require(summary["basis"] == BASES, "HISTORY_UNAVAILABLE_SERIES_BASIS")
    asset, benchmark = assets[instrument_id], assets[benchmark_instrument_id]
    require(asset["currency"] == benchmark["currency"], "HISTORY_INCOMPARABLE_SERIES")
    bars = admitted_rows(bundle, instrument_id)
    other = admitted_rows(bundle, benchmark_instrument_id)
    sessions, calendar = reference_calendar(owner.calendar_dir, summary, bundle)
    qualified = sessions is not None
    if qualified:
        require(all(r["session_date"] in sessions for r in (*bars, *other)), "HISTORY_OUTSIDE_REFERENCE_CALENDAR")
        # No invented prehistory or padded OHLCV: series-only gap points between admitted bounds.
        sessions = [s for s in sessions if bars and bars[0]["session_date"] <= s <= bars[-1]["session_date"]]
    else:
        sessions = [r["session_date"] for r in bars]
    rowmap, othermap = ({r["session_date"]: r for r in source} for source in (bars, other))
    points, metadata, resets = indicators(sessions, {s:r["close"] for s,r in rowmap.items()}, periods,
                                           deviation, qualified)
    field = "close" if reference_family == "RAW_PRICE_RELATIVE" else "adjusted_close"
    reference = references(points, {s:r[field] for s,r in rowmap.items()},
                           {s:r[field] for s,r in othermap.items()}, reference_family, qualified)
    reference.update({"instrument_id": instrument_id, "benchmark_instrument_id": benchmark_instrument_id,
                      "currency": asset["currency"], "computed_from": sessions[0] if sessions else None})
    for name, item in metadata.items():
        item.update({"calculation_version": CALCULATION_VERSION, "numeric_version": NUMERIC_VERSION,
                     "deviation": effective["bb_deviation"] if name.startswith("bb_") else None})
    begin, stop = bisect_left(sessions, start), bisect_left(sessions, end)
    prior = max(0, begin-requested)
    selected = points[prior:stop]
    for row in selected:
        row["row_role"] = "WARMUP" if row["session_date"] < start else "VISIBLE"
    visible = points[begin:stop]
    observed = sum(s in rowmap for s in sessions[begin:stop])
    missing = stop-begin-observed if qualified else None
    coverage = {"observed_in_window": observed, "observed_total": len(bars),
                "expected_sessions": stop-begin if qualified else None, "missing_expected_sessions": missing,
                "missing_fraction": None, "calendar": calendar, "original_calendar_status": asset["calendar_status"],
                "quarantined_rows": asset["quarantined_rows"], "duplicate_rows": asset["duplicate_rows"],
                "quarantine_reason_counts": asset["quarantine_reason_counts"],
                "first_date": asset["first_date"], "last_date": asset["last_date"]}
    if qualified and stop > begin:
        from decimal import localcontext
        from .history_numeric import context
        with localcontext(context()):
            coverage["missing_fraction"] = derived_text(Decimal(missing)/Decimal(stop-begin))
    base = identity_fields(summary)
    window = {"start": start, "end_exclusive": end}
    effective["benchmark_instrument_id"] = benchmark_instrument_id
    identity = sha(canonical({**base, "instrument_id": instrument_id, "window": window,
        "warmup_sessions": requested, "limit": count, "projection": "series/1", "parameters": effective,
        "calculation_version": CALCULATION_VERSION, "numeric_version": NUMERIC_VERSION,
        "definition_sha256": DEFINITION_SHA256, "calendar": calendar,
        "reference": reference, "input_sha256": sha(bundle.files["bars/"+instrument_id+".ndjson"]),
        "benchmark_sha256": sha(bundle.files["bars/"+benchmark_instrument_id+".ndjson"])}))
    available = begin-prior
    warmup_status = "NOT_REQUESTED" if not requested else "UNRESOLVED" if not qualified else (
        "INSUFFICIENT_HISTORY" if available < requested else "SUFFICIENT")
    comparable = sum(r["values"]["asset_reference"] is not None for r in visible)
    def make(items, next_cursor, complete):
        return {"schema_version": "polar.history-series/1", **base, "instrument_id": instrument_id,
            "request_identity": identity, "window": window, "rows": items, "row_count": len(items),
            "data_status": "EMPTY_WINDOW" if not visible else "PARTIAL" if missing or asset["quarantined_rows"] else "OBSERVED",
            "warmup": {"requested": requested, "available": available,
                "returned": sum(r["row_role"] == "WARMUP" for r in items), "status": warmup_status,
                "count_basis": "REFERENCE_SESSIONS" if qualified else "UNQUALIFIED_OBSERVATIONS"},
            "coverage": coverage, "fitness": {**summary["fitness"], "chart_fitness": asset["chart_fitness"]},
            "calculation_version": CALCULATION_VERSION, "numeric_version": NUMERIC_VERSION,
            "definition_sha256": DEFINITION_SHA256, "parameters": effective, "series_metadata": metadata,
            "reference_metadata": {**reference, "comparable_in_window": comparable,
                "window_status": "COMPARABLE" if comparable else "NO_COMPARABLE_DATA"},
            "resets": {"count": len(resets), "scope": "FULL_REVISION_PREFIX",
                "policy": "MISSING_OR_INVALID_CLOSE_RESETS_STATE"},
            "next_cursor": next_cursor, "window_complete": complete}
    return page_rows(selected, [r["session_date"]+":"+r["row_role"] for r in selected],
                     count, cursor, "series/1", identity, make, codec)
