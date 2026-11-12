"""Public delivery effects in an OWNED schema of the existing isolated CI DB.

Never changes public fixtures, scientific runs, attempts, or runtime credentials.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from importlib.resources import files
import os
import uuid

import psycopg
from psycopg import sql
import pytest

from polar.codec import canonical, digest
from polar.config import Settings
from polar.registry import BudgetExceeded, Conflict, NotFound, Registry


@pytest.fixture
def registry(tmp_path):
    dsn = os.environ.get("POLAR_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("NOT RUN: existing isolated POLAR_TEST_DATABASE_URL is required")
    settings = Settings(dsn, tmp_path, lease_seconds=5)
    base = Registry(settings)
    name = "polar_delivery_test_"+uuid.uuid4().hex
    with base.connect() as db:
        assert db.execute("SELECT current_database() AS n").fetchone()["n"].startswith("polar_test_"), \
            "Refusing a non-test database"
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))

    class IsolatedRegistry(Registry):
        def connect(self):
            db = super().connect()
            try:
                # Exclude public: preexisting legacy fixtures remain invisible/intact.
                db.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
                return db
            except Exception:
                db.close()
                raise

    reg = IsolatedRegistry(settings)
    try:
        yield reg
    finally:
        with base.connect() as db:
            # Only the exact UUID-owned schema created by this fixture is removed.
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def envelope(number=1):
    body = {"schema": "public-invented-delivery/1", "result": "invented", "number": number}
    h = digest(body)
    return "delivery-"+h, "RESULT", "research-"+"a"*64, h, body


def scientific_counts(reg):
    with reg.connect() as db:
        return tuple(db.execute("SELECT count(*) AS n FROM "+table).fetchone()["n"] for table in
                     ("runs", "attempts", "datasets"))


@pytest.mark.postgres
def test_additive_migration_legacy_check_and_checksum(registry):
    reg = registry
    # Original v1 on its own stays acceptable to the legacy check.
    source = files("polar").joinpath("schema.sql").read_bytes()
    checksum = hashlib.sha256(source).hexdigest()
    with reg.connect() as db:
        db.execute(source.decode())
        db.execute("INSERT INTO schema_version(version,checksum) VALUES (1,%s)", (checksum,))
    reg.check()
    with pytest.raises(RuntimeError, match="^RESEARCH_DELIVERY_UNAVAILABLE$"):
        reg.research_delivery(envelope()[0])
    reg.migrate()
    reg.migrate()
    reg.check()
    with reg.connect() as db:
        assert db.execute("SELECT version,checksum FROM schema_version").fetchall() == [{"version": 1, "checksum": checksum}]
        assert db.execute("SELECT version,checksum FROM research_delivery_schema_version").fetchall() == [{
            "version": 1, "checksum": hashlib.sha256(reg._research_delivery_schema()).hexdigest()}]
    # Deliberate mismatch is rolled back in this exact test-owned transaction.
    with pytest.raises(RuntimeError, match="^RESEARCH_DELIVERY_SCHEMA_MISMATCH$"):
        with reg.connect() as db:
            db.execute("UPDATE research_delivery_schema_version SET checksum='invented-mismatch'")
            reg._check_research_delivery(db)
    reg.migrate()
    assert scientific_counts(reg) == (0, 0, 0)


@pytest.mark.postgres
def test_submit_duplicate_conflict_storage_and_terminal_immutability(registry):
    reg = registry
    reg.migrate()
    args = envelope()
    queued = reg.submit_research_delivery(*args)
    assert queued["state"] == "QUEUED" and queued["body_bytes"] == len(canonical(args[-1]))
    assert queued["delivery_attempt_count"] == 0 and queued["started_at"] is None
    assert reg.research_delivery(args[0]) == queued
    assert reg.research_delivery("delivery-"+"f"*64) is None
    assert reg.submit_research_delivery(*args) == queued
    changed = list(args)
    changed[-1] = {**args[-1], "number": 9}
    with pytest.raises(Conflict, match="RESEARCH_DELIVERY_PAYLOAD_CONFLICT"):
        reg.submit_research_delivery(*changed)
    changed = list(args)
    changed[1] = "ASSESSMENT"
    with pytest.raises(Conflict, match="RESEARCH_DELIVERY_PAYLOAD_CONFLICT"):
        reg.submit_research_delivery(*changed)
    # Existing delivery retries do not require new storage admission.
    small = type(reg)(Settings(reg.settings.dsn, reg.settings.artifacts, storage_bytes=1))
    assert small.submit_research_delivery(*args) == queued
    with pytest.raises(BudgetExceeded, match="RETAINED_STORAGE_ADMISSION_LIMIT"):
        small.submit_research_delivery(*envelope(2))
    claimed = reg.claim_research_delivery()
    assert claimed["id"] == queued["id"] and claimed["delivery_attempt_count"] == 1
    receipt = {"record_id": args[2], "publication": "EXACT_PUBLIC_INVENTED"}
    delivered = reg.finish_research_delivery(args[0], claimed["lease_token"], "DELIVERED", receipt)
    assert delivered["receipt"] == receipt and delivered["delivered_at"] >= delivered["started_at"] >= delivered["queued_at"]
    assert delivered["finished_at"] == delivered["delivered_at"]
    assert delivered["lease_token"] is None and delivered["lease_until"] is None
    assert reg.submit_research_delivery(*args) == delivered
    assert reg.claim_research_delivery() is None
    with pytest.raises(Conflict, match="RESEARCH_DELIVERY_LEASE_CONFLICT"):
        reg.finish_research_delivery(args[0], claimed["lease_token"], "REJECTED", error_code="LATE")
    with pytest.raises(psycopg.Error):
        with reg.connect() as db:
            db.execute("UPDATE research_deliveries SET receipt='{}'::jsonb WHERE id=%s", (args[0],))
    assert reg.research_delivery(args[0]) == delivered
    assert scientific_counts(reg) == (0, 0, 0)


@pytest.mark.postgres
def test_restart_expired_delivery_reclaimed_with_new_fence(registry):
    reg = registry
    reg.migrate()
    args = envelope()
    reg.submit_research_delivery(*args)
    # Two consumers cannot claim the same unexpired delivery.
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: reg.claim_research_delivery(), range(2)))
    assert sum(row is not None for row in claims) == 1
    first = next(row for row in claims if row)
    with reg.connect() as db:
        db.execute("UPDATE research_deliveries SET lease_until=now()-interval '1 second' WHERE id=%s", (args[0],))
    with pytest.raises(Conflict, match="RESEARCH_DELIVERY_LEASE_CONFLICT"):
        reg.finish_research_delivery(args[0], first["lease_token"], "DELIVERED")
    restarted = type(reg)(reg.settings)
    second = restarted.claim_research_delivery()
    assert second["id"] == first["id"] and second["lease_token"] != first["lease_token"]
    assert second["delivery_attempt_count"] == 2
    assert second["started_at"] == first["started_at"] and second["last_started_at"] >= first["last_started_at"]
    with pytest.raises(Conflict, match="RESEARCH_DELIVERY_LEASE_CONFLICT"):
        reg.finish_research_delivery(args[0], first["lease_token"], "REJECTED", error_code="STALE_CONSUMER")
    final = restarted.finish_research_delivery(args[0], second["lease_token"], "DELIVERED", {"ok": True})
    assert reg.research_delivery(args[0]) == final
    assert scientific_counts(reg) == (0, 0, 0)


@pytest.mark.postgres
def test_wait_for_result_retry_and_rejected_terminal_are_not_scientific_attempts(registry):
    reg = registry
    reg.migrate()
    args = list(envelope())
    args[1] = "ASSESSMENT"
    reg.submit_research_delivery(*args)
    first = reg.claim_research_delivery()
    waiting = reg.finish_research_delivery(args[0], first["lease_token"], "WAITING_FOR_RESULT", error_code="RESULT_NOT_FOUND")
    assert waiting["state"] == "WAITING_FOR_RESULT" and waiting["not_before"] > waiting["updated_at"]
    assert waiting["lease_token"] is None and waiting["delivered_at"] is None
    assert reg.claim_research_delivery() is None
    with reg.connect() as db:
        db.execute("UPDATE research_deliveries SET not_before=now()-interval '1 second' WHERE id=%s", (args[0],))
    second = reg.claim_research_delivery()
    assert second["id"] == first["id"] and second["delivery_attempt_count"] == 2
    assert second["lease_token"] != first["lease_token"]
    rejected = reg.finish_research_delivery(args[0], second["lease_token"], "REJECTED", error_code="BOUND_SUBJECT_MISMATCH")
    assert rejected["state"] == "REJECTED" and rejected["finished_at"] is not None
    assert rejected["delivered_at"] is None and rejected["error_code"] == "BOUND_SUBJECT_MISMATCH"
    assert reg.submit_research_delivery(*args) == rejected
    assert reg.claim_research_delivery() is None
    with pytest.raises(NotFound, match="RESEARCH_DELIVERY_NOT_FOUND"):
        reg.finish_research_delivery("delivery-"+"f"*64, uuid.uuid4(), "DELIVERED")
    assert scientific_counts(reg) == (0, 0, 0)


def test_delivery_defensive_domains_fail_before_opening_db(tmp_path, monkeypatch):
    reg = Registry(Settings("not-opened-invented", tmp_path))
    monkeypatch.setattr(reg, "connect", lambda: pytest.fail("Invalid public domains must not open DB"))
    for index, value in [(0, "bad"), (1, []), (2, "research-invalid"), (3, "uppercase"), (4, [1])]:
        args = list(envelope())
        args[index] = value
        with pytest.raises(ValueError):
            reg.submit_research_delivery(*args)
    for body in [{"number": float("nan")}, {1: "not-json-object-keys"}, {"secret": object()}]:
        with pytest.raises(ValueError, match="RESEARCH_DELIVERY_INVALID_BODY"):
            reg._research_delivery_json(body)
    with pytest.raises(ValueError, match="RESEARCH_DELIVERY_INVALID_STATE"):
        reg.finish_research_delivery(envelope()[0], uuid.uuid4(), "RUNNING")
    with pytest.raises(ValueError, match="RESEARCH_DELIVERY_INVALID_LEASE_TOKEN"):
        reg.finish_research_delivery(envelope()[0], "invalid", "DELIVERED")
    with pytest.raises(ValueError, match="RESEARCH_DELIVERY_INVALID_ERROR_CODE"):
        reg.finish_research_delivery(envelope()[0], uuid.uuid4(), "REJECTED", error_code="raw DSN not allowed")
