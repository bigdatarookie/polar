"""Two preregistered CI8h profiles, exact shared math and isolated event plan.

This module does no I/O or simulation on import. Retained execution is separate
from conversion and requires the exact protocol/input/operation binding.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from zoneinfo import ZoneInfo

from .gym_contract import context, decimal_string, decimal_fraction, read_ref, decode, sha
from .obs158_math import microprice, cent_round_micro

PROFILES = {
    "HYP001-CI3-12M1M-v1": {
        "registration_id": "CI8H-A-MOM3-2017-2019-V1-EXPERIMENT-01",
        "kind": "A_MOMENTUM", "protocol_sha256": "08774eddd65d8280925e1690b5f3e5fc980d0c1fb2ef45fb89d391a013cb6608",
        "input_sha256": "11754099ccfaeb29df4e4ab2e2518c54a229da79d69bcd2f3610acf0ff5c3f1f",
        "symbols": ["AAPL", "AMZN", "TSLA"], "input_start": "2016-01-04",
        "initial": "2017-01-31", "first_entry": "2017-02-01", "end": "2019-12-31",
        "input_dates": 1006, "nav_points": 735, "decision_count": 35,
        "legs": ["MOM12_1_TOP1_MONTHLY", "EW3_INITIAL_BUYHOLD"],
    },
    "HYP010-CI-AMZN-TOM-v1": {
        "registration_id": "HYP010-CI-AMZN-TOM-v1",
        "kind": "B_TOM", "protocol_sha256": "adc674064d6b5bd93c14f41fb85224644d703a96903e25d0c9f16335b592957b",
        "input_sha256": "262b0b7a45dece5d0b05a7af05d30a11a6a62b5011389703b51ffd86026dbd26",
        "symbols": ["AMZN"], "input_start": "2019-01-31", "initial": "2019-01-30",
        "first_entry": "2019-01-31", "end": "2022-01-06", "input_dates": 741,
        "nav_points": 742, "decision_count": 36,
        "legs": ["AMZN_TOM", "AMZN_INITIAL20_BH", "AMZN_INITIAL100_BH", "CASH"],
    },
}
CALENDAR_SHA = "803aaef74549c4887ce7838a1667b7c5e3068e5d6ea661b421baa7331b2de1bb"
SOURCE_SHA = "e01012bf694a78eeb11519032eaabd74f74ba0c0f4be0ac7e3edbc42e40532d8"
TZ_SHA = "d7f2206b3a45989fc9ad63d558922532fa7352280d5f87176bf1db79cb1d1fa9"
INITIAL_CENTS = 10000000


class ResearchRunError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise ResearchRunError(code)


def cents_text(value):
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value)//100}.{abs(value)%100:02d}"


def project(value):
    with localcontext(context()):
        return decimal_string(decimal_fraction(Fraction(value)))


def fee_cents(q, price_micro, *, cost_profile=None):
    require(type(q) is int and 0 <= q <= 1000000000 and type(price_micro) is int and price_micro > 0,
            "ORDER_DOMAIN")
    cost = {'flat_cents': 100, 'bps': 10} if cost_profile is None else cost_profile
    require(type(cost) is dict and set(cost) == {'flat_cents', 'bps'} and
            type(cost['flat_cents']) is int and type(cost['bps']) is int and
            (cost['flat_cents'], cost['bps']) in ((100, 10), (200, 20)), 'COST_PROFILE')
    return cost['flat_cents'] + (q * price_micro * cost['bps'] + 99999999)//100000000 if q else 0


def maximum_buy(desired, price_micro, cash_cents, budget_cents=None, *, cost_profile=None):
    require(type(desired) is int and 0 <= desired <= 1000000000 and cash_cents >= 0, "BUY_DOMAIN")
    if cost_profile is not None:
        fee_cents(0, price_micro, cost_profile=cost_profile)
    budget = min(cash_cents, budget_cents if budget_cents is not None else cash_cents)
    lo, hi = 0, desired
    while lo < hi:
        q = (lo + hi + 1)//2
        if cent_round_micro(q * price_micro) + fee_cents(q, price_micro, cost_profile=cost_profile) <= budget:
            lo = q
        else:
            hi = q - 1
    return lo


def instant(day, hour, minute, tz):
    dt = datetime.combine(date.fromisoformat(day), time(hour, minute), tzinfo=tz)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = dt.astimezone(timezone.utc) - epoch
    return (delta.days * 86400 + delta.seconds) * 10**9


def utc_text(ns):
    seconds, nanos = divmod(ns, 10**9)
    text = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return text + ("." + f"{nanos:09d}" if nanos else "") + "Z"


def convert_input(data, profile, tz):
    """Lossless closed dense grid; never forward fill, read final close or trade."""
    require(set(data) == {"schema", "source_revision", "source_sha256", "calendar_sha256", "dates",
                          "symbols", "rows", "limitations"}, "INPUT_FIELDS")
    require(data["schema"] == "polar.ci-research-input/1", "INPUT_SCHEMA")
    symbols, days = data["symbols"], data["dates"]
    require(symbols == profile["symbols"] and days == sorted(set(days)) and
            1 <= len(days) <= 3000 and len(data["rows"]) == len(days)*len(symbols), "INPUT_GRID")
    require(days[0] == profile["input_start"] and days[-1] == profile["end"], "INPUT_BOUNDARIES")
    for day in days:
        require(date.fromisoformat(day).isoformat() == day, "INPUT_DATE")
    prices = {}
    for row, (day, symbol) in zip(data["rows"], ((d, s) for d in days for s in symbols)):
        require(set(row) == {"symbol", "date", "open", "close", "source_ref"} and
                row["symbol"] == symbol and row["date"] == day, "ROW_IDENTITY_OR_ORDER")
        ref = row["source_ref"]
        require(set(ref) == {"object_sha256", "row"} and type(ref["row"]) is int and ref["row"] >= 0 and
                type(ref["object_sha256"]) is str and len(ref["object_sha256"]) == 64 and
                all(c in "0123456789abcdef" for c in ref["object_sha256"]), "SOURCE_POINTER")
        require((row["close"] is None) == (day == profile["end"]), "TERMINAL_CLOSE_FORBIDDEN")
        prices.setdefault(day, {})[symbol] = {"open_micro": microprice(row["open"]),
                 "close_micro": microprice(row["close"]) if row["close"] is not None else None,
                 "source_ref": ref}
    nav_days = [d for d in days if d >= profile["initial"]]
    if profile["initial"] not in nav_days:
        nav_days.insert(0, profile["initial"])
    require(nav_days[0] == profile["initial"] and nav_days[-1] == profile["end"], "NAV_BOUNDARIES")
    grid = [{"date": d, "nominal_ns": instant(d, 16, 0, tz),
             "sample_ns": instant(d, 16, 0, tz)+100, "initial": i == 0,
             "terminal": d == profile["end"]} for i, d in enumerate(nav_days)]
    decisions = []
    if profile["kind"] == "A_MOMENTUM":
        formation = [d for i, d in enumerate(days[:-1]) if d >= profile["initial"] and
                     d < profile["end"] and days[i+1][:7] != d[:7]]
        for d in formation:
            i = days.index(d)
            require(i >= 252, "INSUFFICIENT_MOMENTUM_HISTORY")
            nxt = days[i+1]
            if nxt >= profile["end"]:
                continue
            next_civil = (date.fromisoformat(d)+timedelta(days=1)).isoformat()
            k = instant(next_civil, 0, 0, tz)
            decisions.append({"kind": "ALLOCATE", "formation": d, "day": nxt, "known_ns": k,
                              "decision_ns": k+60*10**9, "open_ns": instant(nxt, 9, 30, tz),
                              "score_dates": [days[i-252], days[i-21]]})
    else:
        months = sorted({d[:7] for d in days if d < profile["end"]})
        # The terminal January is only the exit channel, never an extra entry.
        months = [m for m in months if m < profile["end"][:7]]
        for month in months:
            entry = max(d for d in days if d[:7] == month)
            y, m = map(int, month.split("-")); next_month = f"{y+(m==12):04d}-{m%12+1:02d}"
            following = [d for d in days if d[:7] == next_month]
            require(len(following) >= 4, "INCOMPLETE_CALENDAR_CYCLE")
            for kind, day in [("ENTER", entry), ("EXIT", following[3])]:
                i = days.index(day)
                previous = days[i-1] if i else profile["initial"]
                k = instant(previous, 16, 0, tz)
                decisions.append({"kind": kind, "formation": previous, "day": day,
                                  "known_ns": k, "decision_ns": k+10**9,
                                  "open_ns": instant(day, 9, 30, tz), "score_dates": []})
    terminal = profile["end"]
    if not any(d["day"] == terminal and d["kind"] == "EXIT" for d in decisions):
        previous = days[-2]; k = instant(previous, 16, 0, tz)
        decisions.append({"kind": "EXIT", "formation": previous, "day": terminal,
                          "known_ns": k, "decision_ns": k+10**9,
                          "open_ns": instant(terminal, 9, 30, tz), "score_dates": []})
    decisions.sort(key=lambda d: d["decision_ns"])
    for d in decisions:
        require(d["known_ns"] < d["decision_ns"] < d["open_ns"], "MODELED_CLOCK_ORDER")
    require(len({d["day"] for d in decisions}) == len(decisions), "DUPLICATE_DECISION")
    return {"schema": "polar.ci-research-plan/1", "profile": profile, "prices": prices,
            "grid": grid, "decisions": decisions, "symbols": symbols,
            "time_assessment": "COUNTERFACTUAL_TIMING_ASSUMPTION_ONLY"}


def prepared(config):
    require(config.get("schema") == "polar.ci-research-config/1" and
            config.get("namespace") in ("INVENTED", "RETAINED"), "CONFIG_SCHEMA")
    require(config.get("profile_id") in PROFILES, "UNSUPPORTED_PROFILE")
    profile = PROFILES[config["profile_id"]]
    protocol = read_ref(config["protocol_ref"])
    require(sha(protocol) == profile["protocol_sha256"], "PROTOCOL_PIN")
    if config["namespace"] == "INVENTED":
        require(config["input_ref"].get("sha256") not in {p["input_sha256"] for p in PROFILES.values()},
                "RETAINED_INPUT_CANNOT_BE_INVENTED")
    raw = read_ref(config["input_ref"])
    require(len(raw) <= 16*1024**2, "INPUT_BOUND")
    if config["namespace"] == "RETAINED":
        require(sha(raw) == profile["input_sha256"], "SELECTED_INPUT_PIN")
    tzraw = read_ref(config["timezone_ref"])
    require(sha(tzraw) == TZ_SHA, "TIMEZONE_PIN")
    import io
    tz = ZoneInfo.from_file(io.BytesIO(tzraw), key="America/New_York")
    data = decode(raw)
    if config["namespace"] == "RETAINED":
        require(data["calendar_sha256"] == CALENDAR_SHA and data["source_sha256"] == SOURCE_SHA,
                "SOURCE_CALENDAR_PIN")
    else:
        require(data["source_sha256"] != SOURCE_SHA, "RETAINED_SOURCE_CANNOT_BE_INVENTED")
    plan = convert_input(data, profile, tz)
    references = decode(Path(__file__).with_name("ci_research_sessions.json").read_bytes())
    require(data["dates"] == references["A" if profile["kind"] == "A_MOMENTUM" else "B"],
            "REFERENCE_DATE_GRID_MISMATCH")
    require(len(plan["grid"]) == profile["nav_points"] and len(data["dates"]) == profile["input_dates"],
            "FIXED_PROFILE_GRID")
    count = sum(d["kind"] == ("ALLOCATE" if profile["kind"] == "A_MOMENTUM" else "ENTER")
                for d in plan["decisions"])
    require(count == profile["decision_count"], "FIXED_DECISION_COUNT")
    return plan, {"protocol_sha256": sha(protocol), "input_sha256": sha(raw),
                  "timezone_sha256": sha(tzraw), "source_sha256": data["source_sha256"],
                  "calendar_sha256": data["calendar_sha256"]}
