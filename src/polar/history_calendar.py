"""Read-only dates-only sidecar binding; never upgrades the original archive quality."""
from .history_bundle import HistoryError, decode, read_file, require, safe_root, sha
from .history_numeric import checked_sessions

CALENDAR_SHA256 = "803aaef74549c4887ce7838a1667b7c5e3068e5d6ea661b421baa7331b2de1bb"
BINDING_SHA256 = "bf0ef723e49a4fa1cf73c4c1eba140b751d030e88eea3eea155d606d7a2cba45"


def reference_calendar(directory, summary, bundle):
    metadata = {"status": "UNRESOLVED_GAPS", "scope": "COMMON_US_EQUITY_REFERENCE",
                "calendar_sha256": None, "binding_sha256": None,
                "close_utc": "UNRESOLVED", "historical_availability": "UNKNOWN_NULL",
                "primary_venue": "UNQUALIFIED", "listing_PIT": "UNQUALIFIED"}
    try:
        root = safe_root(directory)
    except HistoryError as exc:
        if exc.code != "HISTORY_DIRECTORY_MISSING":
            raise
        return None, metadata
    if any(not (root/name).exists() and not (root/name).is_symlink()
           for name in ("calendar.json", "binding.json")):
        return None, metadata
    try:
        raw = read_file(root, "calendar.json", limit=128*1024)
        binding_raw = read_file(root, "binding.json", limit=32*1024)
    except FileNotFoundError:
        return None, metadata
    require(sha(raw) == CALENDAR_SHA256 and sha(binding_raw) == BINDING_SHA256,
            "HISTORY_CALENDAR_INTEGRITY_ERROR")
    calendar, binding = decode(raw), decode(binding_raw)
    if (binding["dataset_revision"] != summary["dataset_revision"] or
            binding["manifest_sha256"] != summary["manifest_sha256"] or
            binding["primary_import_receipt_id"] != summary["import_receipt_id"]):
        return None, metadata
    sessions = calendar["sessions"]
    checked_sessions(sessions)
    require(calendar["dates_only"] is True and calendar["applicability"] ==
            "COMMON_US_EQUITY_REFERENCE_NOT_PRIMARY_VENUE", "HISTORY_CALENDAR_INTEGRITY_ERROR")
    for comparison in binding["comparisons"]:
        name = "bars/"+comparison["instrument_id"]+".ndjson"
        require(name in bundle.files and sha(bundle.files[name]) == comparison["bar_object_sha256"],
                "HISTORY_CALENDAR_INTEGRITY_ERROR")
    return sessions, {**metadata, "status": "QUALIFIED_REFERENCE_DATES_ONLY",
        "calendar_sha256": CALENDAR_SHA256, "binding_sha256": BINDING_SHA256,
        "calendar_id": calendar["calendar"], "calendar_version": calendar["calendar_version"],
        "start": calendar["start"], "end_inclusive": calendar["end_inclusive"]}
