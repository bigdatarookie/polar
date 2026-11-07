"""Frozen retrospective chart arithmetic. No trading, model, display rounding or IO."""
from decimal import (Context, Decimal, DecimalException, DivisionByZero, InvalidOperation,
                     Overflow, ROUND_HALF_EVEN, localcontext)

from .history_bundle import HistoryError, label, numeric, require

DEFINITION_SHA256 = "467df7e251db727ecc35ae413b5416d2a61dea36a7f717850a06b1b03807f424"
NUMERIC_VERSION = "decimal50-v1"
INDICATORS = ("sma", "ema", "bb_middle", "bb_upper", "bb_lower", "rsi")
REFERENCES = ("asset_reference", "benchmark_reference")


def context():
    return Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                   capitals=1, clamp=0, flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])


def derived_text(value):
    require(value.is_finite(), "HISTORY_NONFINITE_CALCULATION")
    if value.is_zero():
        return "0"
    sign, digits, exponent = value.as_tuple()
    digits = list(digits)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = ("-" if sign else "") + "".join(str(d) for d in digits)
    return coefficient + (f"E{exponent:+d}" if exponent else "")


def checked_sessions(sessions):
    require(type(sessions) is list and len(sessions) <= 5000 and
            sessions == sorted(set(sessions)), "HISTORY_INVALID_SERIES_SESSIONS")
    for session in sessions:
        label(session)


def mean(values):
    total = Decimal(0)
    for value in values:  # frozen oldest-to-newest reduction
        total = total + value
    return total / Decimal(len(values))


def set_value(row, name, value):
    row["values"][name] = derived_text(value)
    row["statuses"][name] = {"status": "VALUE", "reason": None}


def unavailable(row, names, reason):
    for name in names:
        row["values"][name] = None
        row["statuses"][name] = {"status": "UNAVAILABLE", "reason": reason}


def indicators(sessions, observations, periods, deviation=Decimal(2), qualified=True):
    checked_sessions(sessions)
    require(set(periods) == {"sma", "ema", "bb", "rsi"}, "HISTORY_INVALID_SERIES_PARAMETERS")
    for n in periods.values():
        require(n is None or type(n) is int and 2 <= n <= 500, "HISTORY_INVALID_SERIES_PARAMETERS")
    require(type(deviation) is Decimal and deviation.is_finite() and 0 < deviation <= 10,
            "HISTORY_INVALID_SERIES_PARAMETERS")
    enabled = [name for name in INDICATORS if periods["bb" if name.startswith("bb_") else name] is not None]
    rows, resets, segment = [], [], []
    origin = None
    ema = gain = loss = None
    broken = set()
    with localcontext(context()) as ctx:
        alpha = Decimal(2) / (Decimal(periods["ema"]) + 1) if periods["ema"] else None
        for session in sessions:
            row = {"session_date": session, "segment_origin": origin,
                   "values": {k: None for k in (*INDICATORS, *REFERENCES)},
                   "statuses": {k: {"status": "DISABLED", "reason": None} for k in (*INDICATORS, *REFERENCES)}}
            unavailable(row, enabled, "WARMUP" if qualified else "UNRESOLVED_GAPS")
            if not qualified:
                rows.append(row)
                continue
            reason = None
            if session not in observations:
                reason = "GAP"
            else:
                try:
                    close = numeric(observations[session], "close")
                except HistoryError:
                    reason = "INVALID_PRICE"
            if reason:
                unavailable(row, enabled, reason)
                resets.append({"session_date": session, "reason": reason})
                segment, origin, ema, gain, loss = [], None, None, None, None
                broken.clear()
                row["segment_origin"] = None
                rows.append(row)
                continue
            if not segment:
                origin = session
            row["segment_origin"] = origin
            segment.append(close)
            for name in ("sma", "ema", "bb", "rsi"):
                n = periods[name]
                if n is None:
                    continue
                keys = ("bb_middle", "bb_upper", "bb_lower") if name == "bb" else (name,)
                if name in broken:
                    unavailable(row, keys, "CALCULATION_NOT_READY")
                    continue
                required = n + (name == "rsi")
                if len(segment) < required:
                    continue
                try:
                    if name == "sma":
                        set_value(row, name, mean(segment[-n:]))
                    elif name == "ema":
                        ema = mean(segment) if len(segment) == n else ema + alpha * (close - ema)
                        set_value(row, name, ema)
                    elif name == "bb":
                        window = segment[-n:]
                        middle = mean(window)
                        squares = Decimal(0)
                        for value in window:
                            difference = value - middle
                            squares = squares + difference * difference
                        sigma = (squares / Decimal(n)).sqrt(context=ctx)
                        for key, value in (("bb_middle", middle), ("bb_upper", middle + deviation * sigma),
                                           ("bb_lower", middle - deviation * sigma)):
                            set_value(row, key, value)
                    else:
                        if len(segment) == n + 1:
                            changes = [right-left for left, right in zip(segment, segment[1:])]
                            gain = mean([max(change, Decimal(0)) for change in changes])
                            loss = mean([max(-change, Decimal(0)) for change in changes])
                        else:
                            change = close - segment[-2]
                            gain = (Decimal(n-1) * gain + max(change, Decimal(0))) / Decimal(n)
                            loss = (Decimal(n-1) * loss + max(-change, Decimal(0))) / Decimal(n)
                        value = Decimal(50) if gain == loss == 0 else Decimal(100) * gain / (gain + loss)
                        set_value(row, name, value)
                except (DecimalException, HistoryError, TypeError):
                    unavailable(row, keys, "ARITHMETIC_ERROR")
                    if name in {"ema", "rsi"}:
                        broken.add(name)  # Never silently reseed after state failure.
            rows.append(row)
    metadata = {}
    for key in INDICATORS:
        n = periods["bb" if key.startswith("bb_") else key]
        first = next((r["session_date"] for r in rows if r["statuses"][key]["status"] == "VALUE"), None)
        errors = sum(r["statuses"][key]["reason"] in {"ARITHMETIC_ERROR", "CALCULATION_NOT_READY"} for r in rows)
        metadata[key] = {"status": "DISABLED" if n is None else "UNRESOLVED_GAPS" if not qualified else
                         "CALCULATION_NOT_READY" if errors else "READY" if first else "INSUFFICIENT_HISTORY",
                         "basis": "RAW_CLOSE", "period": n, "first_valid_session": first,
                         "required_history": n + (key == "rsi") if n else None,
                         "available_history": len(segment), "available_history_scope": "FINAL_REVISION_SEGMENT",
                         "computed_from": sessions[0] if sessions else None, "segment_origin": origin,
                         "reset_count": len(resets), "arithmetic_error_count": errors}
    return rows, metadata, resets


def references(rows, asset, benchmark, family, qualified=True):
    require(family in {"RAW_PRICE_RELATIVE", "PROVIDER_ADJUSTED_CLOSE_INDEX"}, "HISTORY_INVALID_REFERENCE_FAMILY")
    common = []
    with localcontext(context()):
        if qualified:
            for row in rows:
                session = row["session_date"]
                try:
                    a, b = numeric(asset.get(session), "close"), numeric(benchmark.get(session), "close")
                    common.append((session, a, b))
                except HistoryError:
                    pass
        anchor = common[0] if common else None
        valid = {session: (a, b) for session, a, b in common}
        for row in rows:
            session = row["session_date"]
            if not qualified or anchor is None or session not in valid:
                unavailable(row, REFERENCES, "UNRESOLVED_GAPS" if not qualified else "NO_OVERLAP" if anchor is None else "GAP")
                continue
            a, b = valid[session]
            try:
                set_value(row, "asset_reference", Decimal(100) * a / anchor[1])
                set_value(row, "benchmark_reference", Decimal(100) * b / anchor[2])
            except (DecimalException, HistoryError):
                unavailable(row, REFERENCES, "ARITHMETIC_ERROR")
    return {"family": family, "anchor_session": anchor[0] if anchor else None,
            "asset_anchor": derived_text(anchor[1]) if anchor else None,
            "benchmark_anchor": derived_text(anchor[2]) if anchor else None,
            "common_valid_sessions": len(common), "status": "UNRESOLVED_GAPS" if not qualified else
            "READY" if anchor else "NO_OVERLAP"}
