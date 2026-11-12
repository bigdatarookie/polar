"""Invented delivery effects; no producer, native, model, or solver invocation."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from polar.api import create_app
from polar.codec import digest
from polar.config import Settings
from polar.history_bundle import canonical, sha
from polar.research_delivery import deliver_once, validate_delivery
from polar.research_results import ResearchError, ResearchResults
from polar.service import Service
from test_research_delivery_registry import registry
from test_research_results import invented_result


def envelope(payload, kind="RESULT"):
    h = sha(canonical(payload)) if kind == "RESULT" else payload["content_sha256"]
    return {"schema_version": "polar.research-delivery/1", "kind": kind,
            "display_scope": "OWNER_LOCAL", "content_sha256": h, "payload": payload}


def review(result):
    h = sha(canonical(result))
    return {"schema_version": "polar.research-review/1", "result_id": "research-"+h,
            "content_sha256": h, "reviewer_id": "invented-independent", "scope": "FINANCIAL",
            "verdict": "NOT_SUPPORTED", "scope_description": "Invented saved delivery test",
            "reference": {"role": "review", "id": "invented-report", "sha256": "7"*64},
            "recorded_at": "2026-11-12T08:00:00Z", "evidence_status": "ASSESSED_WITH_LIMITS", "reason": None}


@pytest.mark.postgres
def test_api_saved_delivery_restart_out_of_order_review_and_duplicate(registry, monkeypatch):
    reg = registry
    reg.migrate()
    svc = Service(reg.settings)
    svc.registry = reg
    # Calling a scientific path from delivery must fail the test immediately.
    monkeypatch.setattr(svc, "_research_engine", lambda *a, **k: pytest.fail("scientific engine called"))
    client = TestClient(create_app(svc))
    result = invented_result()
    assessment = envelope(review(result), "ASSESSMENT")
    before = client.get('/v1/research/revision').json()
    submitted = client.post('/v1/research/deliveries', json=assessment)
    assert submitted.status_code == 202
    aid = submitted.json()['id']
    assert 'body' not in submitted.json() and 'lease_token' not in submitted.json()
    assert deliver_once(reg, svc._research())['state'] == 'WAITING_FOR_RESULT'
    with reg.connect() as db:
        db.execute("UPDATE research_deliveries SET not_before=now()+interval '1 hour' WHERE id=%s", (aid,))
    rid = client.post('/v1/research/deliveries', json=envelope(result)).json()['id']
    # Only result is eligible while assessment waits. Simulate crash AFTER saved
    # publication and BEFORE registry acknowledgement, then reclaim expired lease.
    claimed = reg.claim_research_delivery()
    assert claimed['id'] == rid
    svc._research().publish(result)
    preliminary = svc.research_result(claimed['result_id'])
    assert preliminary['assessment']['financial'] == 'NOT_REVIEWED'
    with reg.connect() as db:
        db.execute("UPDATE research_deliveries SET lease_until=now()-interval '1 second' WHERE id=%s", (rid,))
    import polar.worker as worker
    monkeypatch.setattr(worker, 'Registry', lambda settings: reg)
    monkeypatch.setattr(worker, 'calculate', lambda *a, **k: pytest.fail('scientific calculate called'))
    resumed = worker.work_research_delivery_once(reg.settings)
    assert resumed['id'] == rid and resumed['state'] == 'DELIVERED'
    with reg.connect() as db:
        db.execute("UPDATE research_deliveries SET not_before=now()-interval '1 second' WHERE id=%s", (aid,))
    done = deliver_once(reg, svc._research())
    assert done['id'] == aid and done['state'] == 'DELIVERED'
    assert done['receipt']['assessment']['financial'] == 'NOT_SUPPORTED'
    after = client.get('/v1/research/revision').json()
    assert after['revision'] != before['revision'] and after['result_count'] == after['assessment_count'] == 1
    # Restart/duplicate does not erase current independent assessment or enqueue.
    again = client.post('/v1/research/deliveries', json=envelope(result)).json()
    assert again['id'] == rid and again['state'] == 'DELIVERED'
    assert client.get('/v1/research/deliveries/'+aid).json()['receipt']['assessment']['financial'] == 'NOT_SUPPORTED'
    assert deliver_once(reg, svc._research()) is None
    assert client.get('/v1/research/revision').json() == after
    with reg.connect() as db:
        assert [db.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] for table in ('runs','attempts')] == [0,0]


@pytest.mark.postgres
def test_self_review_rejected_not_retried_or_financial_pass(registry):
    reg = registry
    reg.migrate()
    svc = Service(reg.settings); svc.registry = reg
    result = invented_result(); svc.research_publish(result)
    bad = review(result); bad['reviewer_id'] = result['bindings']['producer_id']
    row = svc.research_delivery_submit(envelope(bad, 'ASSESSMENT'))
    done = deliver_once(reg, svc._research())
    assert done['id'] == row['id'] and done['state'] == 'REJECTED'
    assert done['error_code'] == 'RESEARCH_REVIEW_BINDING'
    assert svc.research_result(row['result_id'])['assessment']['financial'] == 'NOT_REVIEWED'
    assert deliver_once(reg, svc._research()) is None


@pytest.mark.parametrize('mutation', [
    lambda b: b.update(display_scope='PUBLIC'),
    lambda b: b.update(content_sha256='0'*64),
    lambda b: b.update(unexpected='private'),
    lambda b: b['payload']['bindings'].update(code_revision='not-a-revision'),
    lambda b: b['payload']['question'].update(summary='/private/source'),
])
def test_delivery_rejects_unbound_or_unadmitted_shape(mutation):
    body = envelope(invented_result()); mutation(body)
    with pytest.raises(ResearchError): validate_delivery(body)


def test_revision_ignores_partial_and_rejects_symlink(tmp_path):
    store = ResearchResults(tmp_path, 64*1024**3)
    before = store.revision()
    parent = tmp_path/'research-results'; parent.mkdir()
    (parent/'.history-partial-invented').mkdir()
    assert store.revision() == before
    (parent/('research-'+'0'*64)).symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ResearchError, match='RESEARCH_UNSAFE_DIRECTORY'): store.revision()


@pytest.mark.postgres
def test_damaged_existing_subject_is_rejected_not_waiting(registry):
    reg = registry; reg.migrate()
    svc = Service(reg.settings); svc.registry = reg
    result = invented_result()
    published = svc.research_publish(result)
    path = reg.settings.artifacts/'research-results'/published['result_id']/'result.json'
    path.chmod(0o600); path.write_text('{}')
    row = svc.research_delivery_submit(envelope(review(result), 'ASSESSMENT'))
    done = deliver_once(reg, svc._research())
    assert done['id'] == row['id'] and done['state'] == 'REJECTED'
    assert done['error_code'] == 'RESEARCH_CONTENT_MISMATCH'
    assert deliver_once(reg, svc._research()) is None


def test_missing_payload_in_existing_subject_is_integrity_failure(tmp_path):
    store = ResearchResults(tmp_path, 64*1024**3)
    rid = store.publish(invented_result())['result_id']
    path = tmp_path/'research-results'/rid/'result.json'
    path.unlink()
    from polar.history_bundle import HistoryError
    with pytest.raises(HistoryError): store.read(rid)


@pytest.mark.postgres
def test_transient_read_failure_keeps_delivery_recoverable(registry, monkeypatch):
    from polar.history_bundle import HistoryError
    reg = registry; reg.migrate()
    svc = Service(reg.settings); svc.registry = reg
    body = envelope(invented_result())
    queued = svc.research_delivery_submit(body)
    store = svc._research()
    def failed(*args): raise HistoryError('HISTORY_UNSAFE_OR_MISSING_FILE')
    monkeypatch.setattr(store, 'publish', failed)
    with pytest.raises(HistoryError): deliver_once(reg, store)
    assert reg.research_delivery(queued['id'])['state'] == 'DELIVERING'
    with reg.connect() as db:
        db.execute("UPDATE research_deliveries SET lease_until=now()-interval '1 second' WHERE id=%s", (queued['id'],))
    assert deliver_once(reg, svc._research())['state'] == 'DELIVERED'


@pytest.mark.postgres
def test_worker_combines_db_and_artifact_capacity(registry, monkeypatch):
    from dataclasses import replace
    import polar.worker as worker
    reg = registry; reg.migrate()
    svc = Service(reg.settings); svc.registry = reg
    queued = svc.research_delivery_submit(envelope(invented_result()))
    monkeypatch.setattr(worker, 'Registry', lambda settings: reg)
    with reg.connect() as db:
        size = db.execute('SELECT pg_database_size(current_database()) AS n').fetchone()['n']
    # Existing DB alone uses the allocation: no artifact copy is admitted.
    with pytest.raises(RuntimeError, match='RESEARCH_DELIVERY_STORAGE_UNAVAILABLE'):
        worker.work_research_delivery_once(replace(reg.settings, storage_bytes=size))
    assert reg.research_delivery(queued['id'])['state'] == 'QUEUED'
    assert svc.research_catalog()['total'] == 0
    assert worker.work_research_delivery_once(reg.settings)['state'] == 'DELIVERED'
