"""Invented data only. File/DB doubles are component evidence, not PG qualification."""
import copy
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Inexact, Rounded, localcontext
from pathlib import Path

import pytest

from polar.config import Settings
from polar.history_bundle import (ASSETS, BASES, HistoryError, canonical, decode, numeric,
                                  sha, verify_bundle)
from polar.history_registry import HistoryRegistry
from polar.history_store import HistoryStore


def literal_tape(case="valid", quoted_volume=False):
    base = ('{"date":"2015-11-02","open":1.2300,"high":1.25,"low":1.20,'
            '"close":1.2300,"adjusted_close":8e-1,"volume":0}')
    if quoted_volume:
        base = base.replace('"volume":0', '"volume":"0"')
    if case == "empty": return b"[]", [], []
    if case in ("mixed", "all-quarantine"):
        rows = [base, base, base.replace('"volume":0', '"volume":17'),
                base.replace("2015-11-02", "2015-11-03").replace('"high":1.25', '"high":1.20').replace('"volume":0', '"volume":-1')]
        rejected = [(0, ["DUPLICATE_ASSET_DATE"]), (1, ["DUPLICATE_ASSET_DATE"]),
                    (2, ["DUPLICATE_ASSET_DATE"]), (3, ["INVALID_VOLUME", "OHLC_RANGE"])]
        valid = []
        if case == "mixed":
            rows.append(base.replace("2015-11-02", "2015-11-04"))
            valid = [4]
        return ("["+",".join(rows)+"]").encode(), valid, rejected
    if case == "invalid-records":
        rows = [base.replace("2015-11-02", "2015-11-04"),
                base.replace("2015-11-02", "bad-date").replace('"close":1.2300', '"close":0'), "null",
                base.replace("2015-11-02", "2015-11-05").replace('"open":1.2300', '"open":"1.2300"'),
                base.replace("2015-11-02", "2015-11-06").replace('"volume":0', '"volume":0.1')]
        return ("["+",".join(rows)+"]").encode(), [0], [
            (1, ["INVALID_CLOSE", "INVALID_SESSION_DATE"]), (2, ["ROW_OBJECT_REQUIRED"]),
            (3, ["INVALID_OPEN"]), (4, ["INVALID_VOLUME"])]
    return ("["+base+"]").encode(), [0], []


def captured(root, *, receipt_time="2026-11-07T09:54:17Z", quoted_volume=False, bad_count=False, cases=None):
    """A small hand-literal captured-format tape, not historical market evidence."""
    root.mkdir()
    files = {}

    def put(name, value, raw=False):
        body = value if raw else canonical(value)
        files[name] = body
        return {"path": name, "bytes": len(body), "sha256": sha(body)}

    assets = [{"instrument_id": i, "source_symbol": s, "display_symbol": s[:-3], "instrument_type": t}
              for i, s, t in ASSETS]
    profile = {"profile_version": "polar.private-eodhd-acquisition/1", "dataset_id": "invented-history",
               "source_id": "eodhd-public-demo", "rights_scope": "OWNER_ONLY_PRIVATE_NONCOMMERCIAL",
               "request_start_inclusive": "2015-11-02", "request_end_inclusive": "2026-11-06",
               "assets": assets, "source_selection_sha256": "a"*64, "import_contract_sha256": "b"*64,
               "hyp007_addendum_sha256": "c"*64, **BASES}
    profile_obj = put("profile.json", profile)
    normalizer = put("acquire-qualify-v1.py", b"# invented inert witness\n", raw=True)
    requests, tapes = [], {}
    for n, (i, symbol, _) in enumerate(ASSETS):
        case = (cases or {}).get(i, "valid")
        source, valid, rejected = literal_tape(case, quoted_volume)
        source += b" " * n  # four distinct raw objects, as in the captured format
        tapes[i] = (case, json.loads(source, parse_int=str, parse_float=str), valid, rejected)
        obj = put("raw/"+sha(source)+".json", source, raw=True)
        url = (f"https://eodhd.com/api/eod/{symbol}?api_token=demo&from=2015-11-02"
               "&to=2026-11-06&period=d&order=a&fmt=json")
        requests.append({"instrument_id": i, "raw_object": obj, "url": url})
    snapshot_core = {"source_id": "eodhd-public-demo", "requests": requests}
    snapshot_id = "raw-"+sha(canonical(snapshot_core))
    put("raw-snapshot.json", {"content": snapshot_core, "source_snapshot_id": snapshot_id})
    bars, reports, receipts = [], [], []
    for n, ((i, symbol, _), request) in enumerate(zip(ASSETS, requests)):
        case, source_rows, valid, rejected = tapes[i]
        rows = [{"instrument_id": i, "source_symbol": symbol, "session_date": source_rows[index]["date"],
                 "source_row_index": index, "source_snapshot_id": snapshot_id,
                 "raw_object_sha256": request["raw_object"]["sha256"],
                 **{k: source_rows[index][k] for k in ("open", "high", "low", "close", "adjusted_close", "volume")},
                 "event_at": None, "published_at": None, "historical_available_at": None,
                 "source_revision": None, "source_status": "OBSERVED"} for index in valid]
        bars.append(put(f"bars/{i}.ndjson", b"".join(canonical(row)+b"\n" for row in rows), raw=True))
        put(f"quarantine/{i}.json", [{"source_row_index": index, "reasons": reasons, "row": source_rows[index]}
                                       for index, reasons in rejected])
        dates = [row["session_date"] for row in rows]
        report = {"instrument_id": i, "source_symbol": symbol, "raw_rows": len(source_rows), "valid_unique_rows": len(valid),
                  "quarantined_rows": len(rejected), "duplicate_keys": 1 if case in ("mixed", "all-quarantine") else 0,
                  "duplicate_rows": 3 if case in ("mixed", "all-quarantine") else 0,
                  "quarantine_reason_counts": dict(Counter(reason for _, reasons in rejected for reason in reasons)),
                  "extra_source_fields": [], "first_valid_date": dates[0] if dates else None,
                  "last_valid_date": dates[-1] if dates else None,
                  "observed_rows_by_year": {"2015": len(valid)} if valid else {},
                  "source_order_ascending": True,
                  "unobserved_requested_edges": {"leading": not dates or dates[0] != "2015-11-02", "trailing": True},
                  "weekend_observation_dates": [], "ten_year_date_span": False,
                  "calendar_status": "UNVERIFIED", "expected_sessions": None, "missing_expected_sessions": None,
                  "missing_fraction": None, "qualified_ten_year_continuity": "UNVERIFIED",
                  "calendar_days_without_observation_between_edges": [],
                  "requested_start_inclusive": "2015-11-02", "requested_end_inclusive": "2026-11-06"}
        reports.append(report)
        start = {"instrument_id": i, "request_number": n+1, "url": request["url"],
                 "acquisition_started_at": "2026-11-07T09:54:05Z"}
        complete = {**start, "acquisition_completed_at": "2026-11-07T09:54:06Z",
                    "raw_object": request["raw_object"], "http_status": 200, "complete_body": True}
        put(f"receipts/{symbol}-start.json", start)
        put(f"receipts/{symbol}-complete.json", complete)
        receipts.append(complete)
    date_sets = [{r["first_valid_date"]} if r["valid_unique_rows"] else set() for r in reports]
    union = set.union(*date_sets)
    quality = {"assets": reports, "total_raw_rows": sum(r["raw_rows"] for r in reports),
               "total_valid_rows": sum(r["valid_unique_rows"] for r in reports) + int(bad_count),
               "total_quarantined_rows": sum(r["quarantined_rows"] for r in reports),
               "structural_status": "VALID" if all(r["valid_unique_rows"] and not r["quarantined_rows"] for r in reports) else "QUARANTINED",
               "cross_asset_union_session_count": len(union), "cross_asset_common_session_count": len(set.intersection(*date_sets)),
               "cross_asset_absent_dates": {a[0]:sorted(union-dates) for a, dates in zip(ASSETS, date_sets)},
               "calendar_qualification": "UNVERIFIED", "historical_known_by": "UNKNOWN_NULL",
               "rights_status": "ADMITTED_OWNER_PRIVATE_ONLY", "causal_PIT_fitness": "INSUFFICIENT_EVIDENCE",
               "financial_evaluation": "NOT_RUN", "price_basis": BASES["ohlc_basis"],
               "adjusted_close_basis": BASES["adjusted_close_basis"], "volume_basis": BASES["volume_basis"]}
    mappings = [{**a, "currency": "USD", "effective_from": None, "effective_until": None,
                 "mapping_status": "DECLARED_CURRENT_ONLY", "evidence_sha256": "a"*64} for a in assets]
    content = {"format": "polar.private-history-bundle/1", "dataset_id": "invented-history",
               "source_snapshot_id": snapshot_id, "profile_sha256": profile_obj["sha256"],
               "normalizer_sha256": normalizer["sha256"], "instruments": put("instruments.json", mappings),
               "quality": put("quality.json", quality), "bars": bars, **BASES,
               "calendar_status": "UNVERIFIED", "calendar_id": None,
               **{k: profile[k] for k in ("source_selection_sha256", "import_contract_sha256", "hyp007_addendum_sha256")}}
    revision = "histrev-"+sha(canonical(content))
    receipt = put("import-receipt.json", {"dataset_revision": revision, "source_snapshot_id": snapshot_id,
                  "import_started_at": "2026-11-07T09:54:04Z", "import_completed_at": receipt_time,
                  "requests": receipts})
    manifest = put("bundle-manifest.json", {"dataset_id": "invented-history", "dataset_revision": revision,
                   "content": content, "acquisition_receipt": receipt,
                   "artifact_status": "COMPLETE_AUTHOR_VALIDATED", "api_ui_status": "NOT_READY"})
    put("environment.json", {"status": "invented"})
    for name, raw in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return manifest["sha256"]


def test_exact_tokens_context_and_hash_literal(tmp_path):
    assert sha(b"{}") == "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    assert canonical({"b": 1, "a": "x"}) == b'{"a":"x","b":1}'
    root = tmp_path / "input"
    pin = captured(root)
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = ctx.traps[Rounded] = True
        before = ctx.copy()
        result = verify_bundle(root, pin)
        assert (ctx.prec, ctx.rounding, ctx.traps, ctx.flags) == (before.prec, before.rounding, before.traps, before.flags)
    assert result.summary["row_count"] == 4
    row = decode(result.files["bars/hist-us-0001.ndjson"])
    assert (row["close"], row["volume"], row["adjusted_close"]) == ("1.2300", "0", "8e-1")
    assert row["historical_available_at"] is None
    assert result.summary["fitness"]["causal_PIT_fitness"] == "INSUFFICIENT_EVIDENCE"


def rebind_receipt_clocks(root, transform):
    """Rewrite only invented operational receipts, keeping content revision unchanged."""
    manifest_path = root/"bundle-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    receipt_path = root/"import-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    for key in ("import_started_at", "import_completed_at"):
        receipt[key] = transform(receipt[key])
    for request, (_, symbol, _) in zip(receipt["requests"], ASSETS):
        for key in ("acquisition_started_at", "acquisition_completed_at"):
            request[key] = transform(request[key])
        (root/f"receipts/{symbol}-complete.json").write_bytes(canonical(request))
        start = {k: request[k] for k in ("instrument_id", "request_number", "url", "acquisition_started_at")}
        (root/f"receipts/{symbol}-start.json").write_bytes(canonical(start))
    raw = canonical(receipt)
    receipt_path.write_bytes(raw)
    manifest["acquisition_receipt"] = {"path": "import-receipt.json", "bytes": len(raw), "sha256": sha(raw)}
    body = canonical(manifest)
    manifest_path.write_bytes(body)
    return sha(body)


@pytest.mark.parametrize("transform", [lambda v:v[:10]+"Z", lambda v:v[:-1],
    lambda v:v[:-1]+".1234567Z", lambda v:v[:-1]+"+01:00", lambda v:v.replace("T", " "),
    lambda v:v.replace(":", ""), lambda v:v[:-1]+"-00:00"])
def test_full_verifier_rejects_unsupported_actual_clocks(tmp_path, transform):
    root = tmp_path/"input"
    captured(root)
    pin = rebind_receipt_clocks(root, transform)
    with pytest.raises(HistoryError, match="HISTORY_INVALID_RECEIPT_CLOCK"):
        verify_bundle(root, pin)


@pytest.mark.parametrize("transform", [lambda v:v, lambda v:v[:-1]+".123456Z", lambda v:v[:-1]+"+00:00"])
def test_full_verifier_preserves_supported_clock_bytes(tmp_path, transform):
    root = tmp_path/"input"
    baseline = verify_bundle(root, captured(root))
    pin = rebind_receipt_clocks(root, transform)
    result = verify_bundle(root, pin)
    assert result.revision == baseline.revision
    assert result.receipt_id == sha((root/"import-receipt.json").read_bytes())
    assert result.summary["import_completed_at"] == transform("2026-11-07T09:54:17Z")


def test_full_verifier_rejects_valid_syntax_reversed_receipt(tmp_path):
    root = tmp_path/"input"
    captured(root)
    pin = rebind_receipt_clocks(root, lambda v: v.replace("09:54:04", "09:55:00"))
    with pytest.raises(HistoryError, match="HISTORY_RECEIPT_CLOCK_ORDER"):
        verify_bundle(root, pin)


def test_whole_duplicate_key_quarantine_retains_unrelated_valid_rows(tmp_path):
    root = tmp_path/"input"
    result = verify_bundle(root, captured(root, cases={a[0]: "mixed" for a in ASSETS}))
    assert (result.summary["raw_rows"], result.summary["row_count"], result.summary["quarantined_rows"]) == (20,4,16)
    assert result.summary["fitness"]["structural_status"] == "QUARANTINED"
    assert result.summary["fitness"]["chart_fitness"] == "READY_WITH_LIMITS"
    for instrument, _, _ in ASSETS:
        row = json.loads(result.files[f"bars/{instrument}.ndjson"])
        assert row["source_row_index"] == 4 and row["session_date"] == "2015-11-04" and row["volume"] == "0"
        rejected = json.loads(result.files[f"quarantine/{instrument}.json"])
        assert [q["source_row_index"] for q in rejected] == [0,1,2,3]
        assert all(q["reasons"] == ["DUPLICATE_ASSET_DATE"] for q in rejected[:3])
        assert rejected[3]["reasons"] == ["INVALID_VOLUME", "OHLC_RANGE"]
        assert rejected[0]["row"] == rejected[1]["row"]  # identical duplicates retained twice
        assert rejected[2]["row"]["volume"] == "17"       # conflicting duplicate retained too
    asset = result.summary["instruments"][0]
    assert asset["duplicate_keys"] == 1 and asset["duplicate_rows"] == 3
    assert asset["quarantine_reason_counts"] == {"DUPLICATE_ASSET_DATE":3, "INVALID_VOLUME":1, "OHLC_RANGE":1}
    assert asset["raw_rows"] == asset["row_count"] + asset["quarantined_rows"]


def test_bad_raw_records_are_audited_without_discarding_valid_remainder(tmp_path):
    root = tmp_path/"input"
    result = verify_bundle(root, captured(root, cases={"hist-us-0001": "invalid-records"}))
    asset = result.summary["instruments"][0]
    assert (asset["raw_rows"], asset["row_count"], asset["quarantined_rows"]) == (5,1,4)
    assert asset["quarantine_reason_counts"] == {"INVALID_CLOSE":1, "INVALID_SESSION_DATE":1,
        "ROW_OBJECT_REQUIRED":1, "INVALID_OPEN":1, "INVALID_VOLUME":1}
    assert result.summary["row_count"] == 4


def test_complete_quarantine_with_producer_json_newline_is_preserved(tmp_path):
    root = tmp_path/"input"
    pin = captured(root, cases={"hist-us-0001":"mixed"})
    path = root/"quarantine/hist-us-0001.json"
    raw = path.read_bytes() + b"\n"
    path.write_bytes(raw)
    result = verify_bundle(root, pin)
    assert result.files["quarantine/hist-us-0001.json"] == raw
    assert result.summary["quarantined_rows"] == 4


@pytest.mark.parametrize("case", ["empty", "all-quarantine"])
def test_empty_assets_keep_null_bounds_and_their_own_fitness(tmp_path, case):
    root = tmp_path/"partial"
    result = verify_bundle(root, captured(root, cases={"hist-us-0001":case}))
    empty = result.summary["instruments"][0]
    assert empty["row_count"] == 0 and empty["first_date"] is None and empty["last_date"] is None
    assert empty["chart_fitness"] == "NOT_READY" and empty["expected_sessions"] is None
    assert all(a["chart_fitness"] == "READY_WITH_LIMITS" for a in result.summary["instruments"][1:])
    assert result.summary["fitness"]["chart_fitness"] == "READY_WITH_LIMITS"
    entire = tmp_path/"entire"
    all_empty = verify_bundle(entire, captured(entire, cases={a[0]:case for a in ASSETS}))
    assert all_empty.summary["row_count"] == 0 and all_empty.summary["fitness"]["chart_fitness"] == "NOT_READY"
    assert all_empty.summary["raw_rows"] == all_empty.summary["quarantined_rows"]
    artifacts = tmp_path/"published"
    artifacts.mkdir()
    store = HistoryStore(artifacts, 1024**2)
    with store.locked(): publication = store.publish_locked(all_empty)
    assert store.verify(all_empty.revision, all_empty.receipt_id, publication).summary == all_empty.summary


@pytest.mark.parametrize("attack", ["drop", "reason", "index", "row"])
def test_incomplete_or_false_quarantine_is_rejected(tmp_path, attack):
    root = tmp_path/"input"
    pin = captured(root, cases={"hist-us-0001":"mixed"})
    path = root/"quarantine/hist-us-0001.json"
    rejected = json.loads(path.read_bytes())
    if attack == "drop": rejected.pop(0)
    if attack == "reason": rejected[3]["reasons"] = ["INVALID_VOLUME"]
    if attack == "index": rejected[0]["source_row_index"] = 4
    if attack == "row": rejected[0]["row"]["volume"] = "99"
    path.write_bytes(canonical(rejected))
    with pytest.raises(HistoryError, match="HISTORY_QUARANTINE_PROVENANCE"):
        verify_bundle(root, pin)


@pytest.mark.parametrize("value,field", [("1e-19", "close"), ("0", "close"), ("NaN", "close"),
    ("1e13", "close"), ("-1", "volume"), ("0.1", "volume"), ("1e19", "volume"), ("+1", "close")])
def test_numeric_rejections(value, field):
    with pytest.raises(HistoryError):
        numeric(value, field)


@pytest.mark.parametrize("options,code", [({"quoted_volume": True}, "HISTORY_ROW_COUNT"),
                                          ({"bad_count": True}, "HISTORY_QUALITY_COUNTS")])
def test_semantic_rejection_with_consistent_hashes(tmp_path, options, code):
    root = tmp_path / "input"
    pin = captured(root, **options)
    with pytest.raises(HistoryError, match=code):
        verify_bundle(root, pin)


@pytest.mark.parametrize("attack", ["tamper", "partial", "extra", "symlink", "duplicate-json"])
def test_archive_fail_closed(tmp_path, attack):
    root = tmp_path / "input"
    pin = captured(root)
    target = root / "bars/hist-us-0001.ndjson"
    if attack == "tamper": target.write_bytes(target.read_bytes().replace(b"1.2300", b"1.2301"))
    if attack == "partial": target.unlink()
    if attack == "extra": (root/"foreign").write_text("extra")
    if attack == "symlink":
        target.unlink()
        target.symlink_to(root/"bars/hist-us-0002.ndjson")
    if attack == "duplicate-json":
        manifest = root / "bundle-manifest.json"
        body = manifest.read_bytes().replace(b'{', b'{"dataset_id":"duplicate",', 1)
        manifest.write_bytes(body)
        pin = sha(body)
    with pytest.raises(HistoryError):
        verify_bundle(root, pin)


def test_publication_replay_receipts_quota_and_tamper(tmp_path):
    root = tmp_path/"input"
    pin = captured(root)
    bundle = verify_bundle(root, pin)
    artifacts = tmp_path/"artifacts"
    artifacts.mkdir()
    store = HistoryStore(artifacts, 1024**2)
    with store.locked():
        publication = store.publish_locked(bundle)
        again = store.publish_locked(bundle)
    assert again == publication
    assert store.verify(bundle.revision, bundle.receipt_id, publication).summary == bundle.summary
    repeat_root = tmp_path/"repeat"
    repeat = verify_bundle(repeat_root, captured(repeat_root, receipt_time="2026-11-07T10:00:00Z"))
    assert repeat.revision == bundle.revision and repeat.receipt_id != bundle.receipt_id
    before = {p: p.stat().st_mtime_ns for p in (artifacts/"history").rglob("*") if p.is_file()}
    with store.locked():
        second = store.publish_locked(repeat)
    assert before == {p: p.stat().st_mtime_ns for p in before}
    assert store.verify(repeat.revision, repeat.receipt_id, second).receipt_id == repeat.receipt_id
    too_small = tmp_path/"small"
    too_small.mkdir()
    limited = HistoryStore(too_small, 1)
    with limited.locked(), pytest.raises(HistoryError, match="HISTORY_STORAGE_LIMIT"):
        limited.publish_locked(bundle)
    assert not (too_small/"history").exists()
    path = artifacts/"history"/bundle.revision/"bars/hist-us-0001.ndjson"
    path.chmod(0o600)
    path.write_text("tampered")
    with pytest.raises(HistoryError, match="HISTORY_OBJECT_HASH"):
        store.verify(bundle.revision, bundle.receipt_id, publication)


class Rows:
    def __init__(self, row=None, rows=None): self.row, self.rows = row, rows
    def fetchone(self): return self.row
    def fetchall(self): return self.rows


class MetadataDB:
    """Retained metadata double: no PostgreSQL proof or emulated SQL semantics."""
    def __init__(self): self.revisions, self.receipts, self.fail_insert = {}, {}, False
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=()):
        if "pg_database_size" in sql: return Rows({"n": 1})
        if sql.startswith("INSERT INTO history_revisions"):
            if self.fail_insert: raise RuntimeError("injected metadata outage")
            ds, rev, receipt, manifest, publication, summary = params
            self.revisions.setdefault(rev, {"dataset_id": ds, "revision": rev,
                "primary_import_receipt_id": receipt, "manifest_hash": manifest,
                "publication_hash": publication, "summary": copy.deepcopy(summary.obj),
                "registered_at": datetime.now(timezone.utc)})
        if sql.startswith("SELECT * FROM history_revisions"): return Rows(self.revisions.get(params[-1]))
        if sql.startswith("INSERT INTO history_receipts"):
            rev, receipt, manifest, publication = params
            self.receipts.setdefault((rev, receipt), {"manifest_hash": manifest, "publication_hash": publication})
        if sql.startswith("SELECT * FROM history_receipts"): return Rows(self.receipts.get(params))
        return Rows()


def test_db_publication_order_first_receipt_and_failure(tmp_path, monkeypatch):
    root = tmp_path/"input"
    pin = captured(root)
    artifacts = tmp_path/"artifacts"
    artifacts.mkdir()
    registry = HistoryRegistry(Settings("unused", artifacts, storage_bytes=8*1024**2))
    db = MetadataDB()
    monkeypatch.setattr(registry.legacy, "check", lambda: None)
    monkeypatch.setattr(registry.legacy, "connect", lambda: db)
    monkeypatch.setattr(registry, "_check", lambda db: None)
    # File publication precedes DB admission even when DB fails; orphan is reusable.
    db.fail_insert = True
    with pytest.raises(RuntimeError, match="injected metadata outage"):
        registry.register(root, pin)
    assert not db.revisions
    assert list((artifacts/"history-receipts").iterdir())
    db.fail_insert = False
    first = registry.register(root, pin)
    assert first["row_count"] == 4
    repeat_root = tmp_path/"repeat"
    repeat_pin = captured(repeat_root, receipt_time="2026-11-07T10:00:00Z")
    repeat = registry.register(repeat_root, repeat_pin)
    assert repeat["import_receipt_id"] == first["import_receipt_id"]
    assert repeat["submitted_import_receipt_id"] != first["import_receipt_id"]
    assert len(db.revisions) == 1 and len(db.receipts) == 2
    detail = registry.revision(first["dataset_id"], first["dataset_revision"])
    assert detail["manifest_sha256"] == pin
    assert "rows" not in detail and detail["runtime_qualification"] == "NOT_RUN"


def test_failed_publication_cleans_only_own_staging(tmp_path, monkeypatch):
    source = tmp_path/"input"
    bundle = verify_bundle(source, captured(source))
    artifacts = tmp_path/"artifacts"
    artifacts.mkdir()
    protected = artifacts/"owner.txt"
    protected.write_text("owner")
    store = HistoryStore(artifacts, 1024**2)
    def fail(*args): raise OSError("injected publication failure")
    monkeypatch.setattr("polar.history_store.os.rename", fail)
    with store.locked(), pytest.raises(OSError):
        store.publish_locked(bundle)
    assert protected.read_text() == "owner"
    assert not list(artifacts.rglob(".history-partial-*"))
    assert not (artifacts/"history"/bundle.revision).exists()


def test_separate_extension_refuses_unknown_and_partial(tmp_path, monkeypatch):
    registry = HistoryRegistry(Settings("unused", tmp_path))
    monkeypatch.setattr(registry.legacy, "check", lambda: None)
    class SchemaDB:
        def __init__(self, existing): self.existing, self.mutations = existing, []
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=()):
            if sql.startswith("SELECT to_regclass"): return Rows({"name": "history_schema_version" if self.existing else None})
            if "SELECT version,checksum" in sql: return Rows(rows=[{"version": 2, "checksum": "unknown"}])
            if "SELECT tablename" in sql: return Rows(rows=[{"tablename": "history_receipts"}])
            if not sql.startswith("SELECT"): self.mutations.append(sql)
            return Rows()
    for existing, error in [(True, "HISTORY_SCHEMA_MISMATCH"), (False, "HISTORY_SCHEMA_PARTIAL")]:
        db = SchemaDB(existing)
        monkeypatch.setattr(registry.legacy, "connect", lambda: db)
        with pytest.raises(HistoryError, match=error): registry.migrate()
        assert db.mutations == []


def test_catalog_snapshot_and_boundaries(tmp_path, monkeypatch):
    registry = HistoryRegistry(Settings("unused", tmp_path))
    monkeypatch.setattr(registry.legacy, "check", lambda: None)
    monkeypatch.setattr(registry, "_check", lambda db: None)
    revisions = [(1, "histrev-"+"1"*64), (2, "histrev-"+"3"*64)]
    class CatalogDB:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, sql, params=()):
            if "max(catalog_sequence)" in sql: return Rows({"n": max(n for n, _ in revisions)})
            if "SELECT dataset_id,revision" in sql:
                snapshot, after, limit = params
                return Rows(rows=[{"dataset_id": "invented", "revision": r} for n, r in sorted(revisions, key=lambda x:x[1])
                                  if n <= snapshot and r > after][:limit])
            return Rows()
    monkeypatch.setattr(registry.legacy, "connect", lambda: CatalogDB())
    monkeypatch.setattr(registry, "revision", lambda d,r: {"dataset_id":d,"dataset_revision":r,
                        "registered_at":datetime(2026,11,7,tzinfo=timezone.utc)})
    first = registry.catalog(1)
    revisions.append((3, "histrev-"+"2"*64))
    second = registry.catalog(1, first["next_cursor"])
    assert [p["items"][0]["dataset_revision"][-64:] for p in (first, second)] == ["1"*64,"3"*64]
    assert second["next_cursor"] is None and second["catalog_snapshot"] == 2
    for limit in (0, 51, True):
        with pytest.raises(HistoryError, match="HISTORY_INVALID_PAGE"): registry.catalog(limit)
    with pytest.raises(HistoryError, match="HISTORY_INVALID_CURSOR"):
        registry.catalog(2, first["next_cursor"])
    with pytest.raises(HistoryError, match="HISTORY_INVALID_CURSOR"):
        registry.catalog(1, "../../secret")
