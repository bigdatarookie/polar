"""Modeled clocks use the exact hash-verified timezone member, never host tzdata."""
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from io import BytesIO

from .hyp007_contract import check, decode, sha, stamp, CALENDAR, TZDATA, COHORT


class Clock:
    def __init__(self, sessions, zone):
        check(type(sessions) is list and sessions and sessions == sorted(set(sessions)))
        self.sessions = [date.fromisoformat(s) for s in sessions]
        self.index = {d: i for i, d in enumerate(self.sessions)}
        self.zone = zone

    @classmethod
    def pinned(cls, calendar, tzdata):
        check(sha(calendar) == CALENDAR and sha(tzdata) == TZDATA, "HYP007_CLOCK_HASH")
        return cls(decode(calendar)["sessions"], ZoneInfo.from_file(BytesIO(tzdata)))

    def civil(self, day, at):
        if isinstance(day, str):
            day = date.fromisoformat(day)
        return datetime.combine(day, at, self.zone).astimezone(timezone.utc)

    def opening(self, day):
        return self.civil(day, time(9, 30))

    def completion(self, day):
        if isinstance(day, str):
            day = date.fromisoformat(day)
        return self.civil(day + timedelta(days=1), time())

    def known_by(self, day):
        if isinstance(day, str):
            day = date.fromisoformat(day)
        i = bisect_right(self.sessions, day)
        if i + 1 >= len(self.sessions):
            return None
        return self.completion(self.sessions[i+1])

    def opportunities(self):
        first = self.index.get(date(2017, 1, 3))
        check(first is not None, "HYP007_CALENDAR_PHASE_MISSING")
        rows = []
        for i in range(first, len(self.sessions), 5):
            d = self.sessions[i]
            if d > date(2024, 12, 31):
                break
            check(i + 6 < len(self.sessions), "HYP007_CALENDAR_HORIZON")
            decision = self.civil(d, time(23, 59, 59, 999999))
            opens = self.sessions[i+1:i+7]
            issue = self.opening(opens[0]) - timedelta(minutes=30)
            check(decision <= issue < self.opening(opens[0]), "HYP007_CLOCK_ORDER")
            for symbol in COHORT:
                rows.append({"key": d.isoformat()+":"+symbol, "instrument": symbol,
                             "decision_date": d.isoformat(), "D": stamp(decision),
                             "open_dates": [s.isoformat() for s in opens], "I_D": stamp(issue),
                             "openings": [stamp(self.opening(s)) for s in opens]})
        check(len(rows) <= 100000, "HYP007_OPPORTUNITY_LIMIT")
        return rows
