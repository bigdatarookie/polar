"""Pure boundaries over a supplied synthetic calendar, never a fill schedule."""
import hashlib
from calendar import monthrange
from datetime import date
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BeforeValidator, Field, ValidationError, model_validator

from .codec import digest
from .models import Session, Strict

MAX_INPUT_BYTES = 1024**2
MAX_SESSIONS = 2000

# Static timezone support, like other imported schema resources. The operation
# itself never loads files, downloads tzdata or reads the current clock.
try:
    _VENUE_ZONE = ZoneInfo("America/New_York")
except (ZoneInfoNotFoundError, OSError, ValueError):
    _VENUE_ZONE = None


class CalendarError(ValueError):
    """Public diagnostics contain a code only, never source values."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _iso_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("ISO_DATE_REQUIRED")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("ISO_DATE_REQUIRED")
    return parsed


CivilDate = Annotated[date, BeforeValidator(_iso_date)]


class CalendarEnvelope(Strict):
    schema_version: Literal["polar.synthetic-calendar-input/1"]
    synthetic: Literal[True]
    timing_model: Literal["synthetic_replay"]
    calendar_id: str = Field(min_length=1, max_length=64)
    calendar_version: str = Field(min_length=1, max_length=64)
    venue_timezone: Literal["America/New_York"]
    coverage_start: CivilDate
    coverage_end: CivilDate
    sessions: list[Session] = Field(max_length=MAX_SESSIONS)

    @model_validator(mode="before")
    @classmethod
    def explicit_synthetic(cls, value):
        if isinstance(value, dict) and value.get("synthetic") is not True:
            raise ValueError("SYNTHETIC_TRUE_REQUIRED")
        return value


def monthly_session_boundaries(raw_bytes: bytes) -> dict:
    """Return civil-month rows without inventing sessions or availability.

    Dates bound the output to at most 119,988 months (years 0001..9999).
    The caller's full-civil-month coverage declaration is an unverified input
    assumption, not independently verified exchange-calendar completeness.
    """
    if not isinstance(raw_bytes, bytes):
        raise CalendarError("INVALID_INPUT_TYPE")
    if len(raw_bytes) > MAX_INPUT_BYTES:
        raise CalendarError("INPUT_TOO_LARGE")
    try:
        data = CalendarEnvelope.model_validate_json(raw_bytes)
    except (ValidationError, ValueError, ArithmeticError, RecursionError):
        raise CalendarError("INVALID_CALENDAR_INPUT") from None
    if _VENUE_ZONE is None:
        raise CalendarError("TIMEZONE_UNAVAILABLE")
    if data.coverage_start > data.coverage_end:
        raise CalendarError("REVERSED_COVERAGE")

    groups, seen = {}, set()
    previous = None
    for index, session in enumerate(data.sessions):
        if session.session_id in seen:
            raise CalendarError("DUPLICATE_SESSION")
        seen.add(session.session_id)
        if previous is not None and previous.close_at >= session.open_at:
            raise CalendarError("UNORDERED_OR_OVERLAPPING_SESSIONS")
        previous = session
        try:
            local_open = session.open_at.astimezone(_VENUE_ZONE).date()
            local_close = session.close_at.astimezone(_VENUE_ZONE).date()
        except (ValueError, OverflowError):
            raise CalendarError("INVALID_CALENDAR_INPUT") from None
        if session.session_id != local_open.isoformat() or local_open != local_close:
            raise CalendarError("SESSION_DATE_MISMATCH")
        if not data.coverage_start <= local_open <= data.coverage_end:
            raise CalendarError("SESSION_OUTSIDE_COVERAGE")
        groups.setdefault((local_open.year, local_open.month), []).append(index)

    body = data.model_dump(mode="json")
    months = []
    start = (data.coverage_start.year - 1) * 12 + data.coverage_start.month - 1
    end = (data.coverage_end.year - 1) * 12 + data.coverage_end.month - 1
    for number in range(start, end + 1):
        year, month = number // 12 + 1, number % 12 + 1
        first = date(year, month, 1)
        last = date(year, month, monthrange(year, month)[1])
        indices = groups.get((year, month), [])
        row = {
            "month": f"{year:04d}-{month:02d}",
            "session_count": len(indices),
            "status": "PARTIAL_MONTH",
            "last_session_id": None,
            "observation_close": None,
            "next_session_id": None,
            "candidate_next_open": None,
        }
        if data.coverage_start <= first and data.coverage_end >= last:
            row["status"] = "NO_SESSIONS"
            if indices:
                index = indices[-1]
                row.update(last_session_id=body["sessions"][index]["session_id"],
                           observation_close=body["sessions"][index]["close_at"],
                           status="NO_NEXT_SESSION")
                if index + 1 < len(data.sessions):
                    following = body["sessions"][index + 1]
                    row.update(next_session_id=following["session_id"],
                               candidate_next_open=following["open_at"],
                               status="BOUNDARY_FOUND")
        months.append(row)

    return {
        "schema_version": "polar.monthly-session-boundaries/1",
        "synthetic": True,
        "timing_model": "synthetic_replay",
        "calendar_id": data.calendar_id,
        "calendar_version": data.calendar_version,
        "venue_timezone": data.venue_timezone,
        "coverage_start": body["coverage_start"],
        "coverage_end": body["coverage_end"],
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "canonical_input_hash": digest(body),
        "status": "PLANNED" if data.sessions else "NO_DATA",
        "months": months,
        "calendar_qualification": "UNVERIFIED",
        "investment_evaluation": "NOT_RUN",
    }
