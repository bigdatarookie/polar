"""Author checks derived from design-before-implementation.md, not peer oracles.

Jan31 early close18:00Z -> exact supplied Feb2 open14:30Z, never Feb1.
UTC Feb1 00:30Z remains local Jan31. Full empty month differs from partial
coverage and from malformed zero bytes. These are synthetic calendar mechanics.
"""
import builtins
import hashlib
import json
import socket
from datetime import date, timedelta

import pytest

from polar import monthly_sessions as module
from polar.monthly_sessions import CalendarError, monthly_session_boundaries


def session(day, *, open_at=None, close_at=None):
    return {"session_id": day, "open_at": open_at or day + "T14:30:00Z",
            "close_at": close_at or day + "T21:00:00Z"}


def envelope(sessions=(), start="2024-01-01", end="2024-02-29", **changes):
    body = {"schema_version": "polar.synthetic-calendar-input/1", "synthetic": True,
            "timing_model": "synthetic_replay", "calendar_id": "literal-synthetic",
            "calendar_version": "v1", "venue_timezone": "America/New_York",
            "coverage_start": start, "coverage_end": end, "sessions": list(sessions)}
    body.update(changes)
    return body


def plan(body):
    return monthly_session_boundaries(json.dumps(body).encode())


def tape():
    return [session("2024-01-30"),
            session("2024-01-31", close_at="2024-01-31T18:00:00Z"),
            session("2024-02-02")]


def test_full_month_early_close_gap_and_no_next():
    result = plan(envelope(tape()))
    assert result["status"] == "PLANNED"
    assert result["calendar_qualification"] == "UNVERIFIED"
    assert result["investment_evaluation"] == "NOT_RUN"
    assert result["months"] == [
        {"month": "2024-01", "session_count": 2, "status": "BOUNDARY_FOUND",
         "last_session_id": "2024-01-31", "observation_close": "2024-01-31T18:00:00Z",
         "next_session_id": "2024-02-02", "candidate_next_open": "2024-02-02T14:30:00Z"},
        {"month": "2024-02", "session_count": 1, "status": "NO_NEXT_SESSION",
         "last_session_id": "2024-02-02", "observation_close": "2024-02-02T21:00:00Z",
         "next_session_id": None, "candidate_next_open": None},
    ]


def test_partial_months_keep_counts_not_boundaries():
    rows = plan(envelope(tape(), start="2024-01-15", end="2024-02-15"))["months"]
    assert [r["status"] for r in rows] == ["PARTIAL_MONTH", "PARTIAL_MONTH"]
    assert [r["session_count"] for r in rows] == [2, 1]
    for row in rows:
        assert all(row[k] is None for k in ["last_session_id", "observation_close",
                                            "next_session_id", "candidate_next_open"])


def test_empty_month_and_exact_next_supplied_after_gap():
    rows = plan(envelope([session("2024-01-31"), session("2024-03-01")],
                         end="2024-03-01"))["months"]
    assert [r["status"] for r in rows] == ["BOUNDARY_FOUND", "NO_SESSIONS", "PARTIAL_MONTH"]
    assert rows[0]["candidate_next_open"] == "2024-03-01T14:30:00Z"
    assert rows[1]["session_count"] == 0
    assert rows[1]["observation_close"] is None
    assert rows[2]["session_count"] == 1 and rows[2]["candidate_next_open"] is None


def test_empty_tape_overall_vs_month_status_and_zero_bytes():
    result = plan(envelope(end="2024-02-10"))
    assert result["status"] == "NO_DATA"
    assert [r["status"] for r in result["months"]] == ["NO_SESSIONS", "PARTIAL_MONTH"]
    assert all(r["last_session_id"] is None and r["candidate_next_open"] is None
               for r in result["months"])
    with pytest.raises(CalendarError, match="^INVALID_CALENDAR_INPUT$"):
        monthly_session_boundaries(b"")


def test_local_date_is_not_utc_date():
    supplied = [session("2024-01-31", open_at="2024-02-01T00:30:00Z",
                        close_at="2024-02-01T01:00:00Z"), session("2024-02-02")]
    rows = plan(envelope(supplied))["months"]
    assert rows[0]["session_count"] == 1
    assert rows[0]["last_session_id"] == "2024-01-31"
    assert rows[0]["observation_close"] == "2024-02-01T01:00:00Z"


def test_dst_supplied_times_and_year_boundary():
    rows = plan(envelope([session("2024-02-29"), session("2024-03-08"),
                          session("2024-03-11", open_at="2024-03-11T13:30:00Z"),
                          session("2024-03-29", open_at="2024-03-29T13:30:00Z",
                                  close_at="2024-03-29T20:00:00Z"),
                          session("2024-04-01", open_at="2024-04-01T13:30:00Z")],
                         start="2024-02-01", end="2024-04-01"))["months"]
    assert rows[0]["candidate_next_open"] == "2024-03-08T14:30:00Z"
    assert rows[1]["observation_close"] == "2024-03-29T20:00:00Z"
    assert rows[1]["candidate_next_open"] == "2024-04-01T13:30:00Z"
    rows = plan(envelope([session("2023-12-29"), session("2024-01-02")],
                         start="2023-12-01", end="2024-01-02"))["months"]
    assert rows[0]["month"] == "2023-12" and rows[0]["next_session_id"] == "2024-01-02"
    assert rows[1]["status"] == "PARTIAL_MONTH"


@pytest.mark.parametrize("start,end,expected", [
    ("2024-02-01", "2024-02-28", "PARTIAL_MONTH"),
    ("2024-02-01", "2024-02-29", "NO_SESSIONS"),
    ("2023-02-01", "2023-02-28", "NO_SESSIONS"),
    ("9999-12-01", "9999-12-31", "NO_SESSIONS"),
    ("0001-01-01", "0001-01-31", "NO_SESSIONS"),
])
def test_civil_endpoints_and_date_limits(start, end, expected):
    assert plan(envelope(start=start, end=end))["months"][0]["status"] == expected


@pytest.mark.parametrize("records,code", [
    ([session("2024-01-30"), session("2024-01-30")], "DUPLICATE_SESSION"),
    ([session("2024-01-31"), session("2024-01-30")], "UNORDERED_OR_OVERLAPPING_SESSIONS"),
    ([session("2024-01-30"), session("2024-01-31", open_at="2024-01-30T21:00:00Z")],
     "UNORDERED_OR_OVERLAPPING_SESSIONS"),
    ([session("2024-01-30"), session("2024-01-31", open_at="2024-01-30T20:00:00Z")],
     "UNORDERED_OR_OVERLAPPING_SESSIONS"),
    ([session("2024-01-31", close_at="2024-02-01T14:00:00Z")], "SESSION_DATE_MISMATCH"),
    ([session("2024-02-01", open_at="2024-02-01T00:30:00Z",
              close_at="2024-02-01T01:00:00Z")], "SESSION_DATE_MISMATCH"),
    ([session("2024-03-01")], "SESSION_OUTSIDE_COVERAGE"),
    ([session("2024-01-31", open_at="2024-01-31T14:30:00")], "INVALID_CALENDAR_INPUT"),
    ([session("2024-01-31", open_at="2024-01-31T14:30:00+01:00")], "INVALID_CALENDAR_INPUT"),
    ([session("2024-01-31", close_at="2024-01-31T14:00:00Z")], "INVALID_CALENDAR_INPUT"),
])
def test_bad_sessions_fail_closed(records, code):
    with pytest.raises(CalendarError, match=f"^{code}$"):
        plan(envelope(records))


@pytest.mark.parametrize("changes", [
    {"schema_version": "unsupported-secret"}, {"synthetic": False}, {"synthetic": 1},
    {"venue_timezone": "UTC"}, {"timing_model": "real"},
    {"calendar_id": ""}, {"calendar_version": ""},
    {"calendar_id": "a" * 65}, {"calendar_version": "a" * 65},
    {"coverage_start": "20240101"}, {"coverage_end": "2024-02-30"},
    {"coverage_start": "2024-01-01T00:00:00Z"}, {"coverage_start": 0},
    {"secret": "do-not-echo"},
])
def test_bad_envelope_sanitized(changes):
    with pytest.raises(CalendarError) as error:
        plan(envelope(**changes))
    assert str(error.value) == error.value.code == "INVALID_CALENDAR_INPUT"


def test_request_bounds_and_timezone_absence(monkeypatch):
    records = [session((date(2020, 1, 1) + timedelta(days=i)).isoformat()) for i in range(2001)]
    with pytest.raises(CalendarError, match="^INVALID_CALENDAR_INPUT$"):
        plan(envelope(records, start="2020-01-01", end="2026-01-01"))
    assert sum(r["session_count"] for r in plan(envelope(records[:2000], start="2020-01-01",
                                                         end="2026-01-01"))["months"]) == 2000
    for raw, code in [(b"x" * (1024**2 + 1), "INPUT_TOO_LARGE"),
                      (b"{secret", "INVALID_CALENDAR_INPUT"), ("{}", "INVALID_INPUT_TYPE")]:
        with pytest.raises(CalendarError, match=f"^{code}$"):
            monthly_session_boundaries(raw)
    with pytest.raises(CalendarError, match="^REVERSED_COVERAGE$"):
        plan(envelope(start="2024-02-01", end="2024-01-31"))
    monkeypatch.setattr(module, "_VENUE_ZONE", None)
    with pytest.raises(CalendarError, match="^TIMEZONE_UNAVAILABLE$"):
        plan(envelope())


def test_determinism_identity_and_no_operation_io(monkeypatch):
    raw = json.dumps(envelope(tape())).encode()
    original = bytes(raw)
    def forbidden(*args, **kwargs):
        raise AssertionError("operation attempted I/O")
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    result = monthly_session_boundaries(raw)
    assert result == monthly_session_boundaries(raw)
    assert raw == original
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    reformatted = json.dumps(json.loads(raw), indent=2, sort_keys=True).encode()
    other = monthly_session_boundaries(reformatted)
    assert result["source_sha256"] != other["source_sha256"]
    assert result["canonical_input_hash"] == other["canonical_input_hash"]
    assert result["months"] == other["months"]
