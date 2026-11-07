"""Invented data only. File/DB doubles are component evidence, not PG qualification."""
import copy
import json
from datetime import datetime, timezone
from decimal import Inexact, Rounded, localcontext
from pathlib import Path

import pytest

from polar.config import Settings
from polar.history_bundle import (ASSETS, BASES, HistoryError, canonical, decode, numeric,
                                  sha, verify_bundle)
from polar.history_registry import HistoryRegistry
from polar.history_store import HistoryStore


def captured(root, *, receipt_time="2026-11-07T09:54:17Z", quoted_volume=False, bad_count=False):
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
    requests = []
    for i, symbol, _ in ASSETS:
        # Numeric tokens are deliberately finer than binary floating point display.
        volume = '"0"' if quoted_volume else "0"
        source = ('[{"date":"2015-11-02","open":1.2300,"high":1.25,"low":1.20,'
                  '"close":1.2300,"adjusted_close":8e-1,"volume":'+volume+'}]').encode()
        obj = put("raw/"+sha(source)+".json", source, raw=True)
        url = (f"https://eodhd.com/api/eod/{symbol}?api_token=demo&from=2015-11-02"
               "&to=2026-11-06&period=d&order=a&fmt=json")
        requests.append({"instrument_id": i, "raw_object": obj, "url": url})
    # Same invented source bytes across assets have one object name; actual first profile
    # requires four distinct raw objects. Give each literal source its own harmless whitespace.
    for n, request in enumerate(requests):
        body = source + b" " * n
        request["raw_object"] = put("raw/"+sha(body)+".json", body, raw=True)
    snapshot_core = {"source_id": "eodhd-public-demo", "requests": requests}
    snapshot_id = "raw-"+sha(canonical(snapshot_core))
    put("raw-snapshot.json", {"content": snapshot_core, "source_snapshot_id": snapshot_id})
    bars, reports, receipts = [], [], []
    for n, ((i, symbol, _), request) in enumerate(zip(ASSETS, requests)):
        row = {"instrument_id": i, "source_symbol": symbol, "session_date": "2015-11-02",
               "source_row_index": 0, "source_snapshot_id": snapshot_id,
               "raw_object_sha256": request["raw_object"]["sha256"], "open": "1.2300", "high": "1.25",
               "low": "1.20", "close": "1.2300", "adjusted_close": "8e-1", "volume": "0",
               "event_at": None, "published_at": None, "historical_available_at": None,
               "source_revision": None, "source_status": "OBSERVED"}
        bars.append(put(f"bars/{i}.ndjson", canonical(row)+b"\n", raw=True))
        put(f"quarantine/{i}.json", [])
        report = {"instrument_id": i, "source_symbol": symbol, "raw_rows": 1, "valid_unique_rows": 1,
                  "quarantined_rows": 0, "duplicate_keys": 0, "duplicate_rows": 0,
                  "quarantine_reason_counts": {}, "extra_source_fields": [], "first_valid_date": "2015-11-02",
                  "last_valid_date": "2015-11-02", "observed_rows_by_year": {"2015": 1},
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
    quality = {"assets": reports, "total_raw_rows": 4, "total_valid_rows": 5 if bad_count else 4,
               "total_quarantined_rows": 0, "structural_status": "VALID", "cross_asset_union_session_count": 1,
               "cross_asset_common_session_count": 1, "cross_asset_absent_dates": {i: [] for i, _, _ in ASSETS},
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


@pytest.mark.parametrize("value,field", [("1e-19", "close"), ("0", "close"), ("NaN", "close"),
    ("1e13", "close"), ("-1", "volume"), ("0.1", "volume"), ("1e19", "volume"), ("+1", "close")])
def test_numeric_rejections(value, field):
    with pytest.raises(HistoryError):
        numeric(value, field)


@pytest.mark.parametrize("options,code", [({"quoted_volume": True}, "HISTORY_SOURCE_NUMERIC_TOKEN"),
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
