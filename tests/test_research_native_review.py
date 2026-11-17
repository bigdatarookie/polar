"""Invented authenticated-adapter controls, separate from actual native proof."""
from copy import deepcopy
import json

import pytest

from polar.history_bundle import canonical, sha
from polar.research_native_review import resolve
from polar.research_results import ResearchError, ResearchResults
from polar.research_delivery import deliver_once, submit
from test_research_results import invented_result
from test_research_delivery_registry import registry

ACTOR = 'quant-validator@polar-rig'
AUTHOR = 'quant-a@polar-rig'
QID = 'qitem-invented-binding'
REF = QID+'#3'


class Queue:
    def __init__(self, result):
        h = sha(canonical(result))
        self.decision = {'schema_version': 'polar.native-research-decision/1',
            'result_id': 'research-'+h, 'content_sha256': h, 'bindings': result['bindings'],
            'author_sessions': [AUTHOR], 'claimed_generation': 'invented-generation',
            'review': {'scope': 'FINANCIAL', 'verdict': 'NOT_SUPPORTED',
                'scope_description': 'Invented negative assessment, not alpha acceptance',
                'reference': {'role': 'assessment', 'id': 'invented-assessment', 'sha256': '7'*64},
                'evidence_status': 'ASSESSED_WITH_LIMITS', 'reason': None}}
        self.row = {'qitemId': QID, 'state': 'done', 'closureReason': 'no-follow-on',
            'destinationSession': ACTOR, 'sourceSession': AUTHOR,
            'claimedAt': '2026-11-17T09:00:00.001Z', 'claimedByGeneration': 'invented-generation',
            'closingTransition': {'transitionId': 3}}
        self.journal = [{'transitionId': 2, 'state': 'in-progress', 'transitionNote': 'claimed',
            'actorSession': ACTOR, 'identityProvenance': 'transport:v1', 'ts': '2026-11-17T09:00:00.002Z'},
            {'transitionId': 3, 'state': 'done', 'actorSession': ACTOR,
             'identityProvenance': 'transport:v1', 'ts': '2026-11-17T09:01:00.123Z'}]
        self.seat = {'current_occupant': ACTOR, 'logical_id': 'quant.validator', 'rig_name': 'polar-rig'}
        self.reads = 0
        self.change_on_reread = False

    def read(self, *args):
        if args[0] == 'whoami': return {'identity': {'sessionName': AUTHOR, 'nodeId': 'invented-node'}}
        if args[0] == 'seat': return deepcopy(self.seat)
        if args[1] == 'transitions': return deepcopy(self.journal)
        self.reads += 1
        row = {**self.row, 'resolution': json.dumps(self.decision)}
        if self.change_on_reread and self.reads > 1: row['claimedByGeneration'] = 'changed-generation'
        return deepcopy(row)


def test_native_negative_assessment_proof_restart_and_legacy_replay(tmp_path):
    result = invented_result(); queue = Queue(result)
    store = ResearchResults(tmp_path, 10**8, native_queue=queue, native_review_writer_enabled=True)
    pub = store.publish(result)
    receipt = store.review({'decision_ref': REF})
    assert receipt['status'] == 'VERIFIED_NATIVE_DECISION'
    assert store.review({'decision_ref': REF}) == receipt
    fresh = ResearchResults(tmp_path, 10**8)
    detail = fresh.read(pub['result_id'])
    assert detail['assessment']['financial'] == 'NOT_SUPPORTED'
    recorded = detail['assessment']['reviews'][0]
    assert recorded['provenance_status'] == 'VERIFIED_NATIVE_DECISION'
    assert recorded['native_provenance']['validator_session'] == ACTOR
    # The old external entry cannot create trust, but may replay exact old
    # outbox bytes on the qualified dualreader floor without dropping proof.
    review, proof = resolve(REF, Queue(result))
    fresh.review(review)
    assert fresh.read(pub['result_id']) == detail
    other = deepcopy(review); other['scope_description'] = 'Forged trust'
    with pytest.raises(ResearchError, match='RESEARCH_NATIVE_DECISION_REQUIRED'):
        fresh.review(other)
    assert fresh.revision()['assessment_count'] == 1
    path = tmp_path/'research-reviews'/pub['result_id']/receipt['review_sha256']/'native-provenance.json'
    path.chmod(0o600); path.write_bytes(canonical({**proof, 'claimed_generation': 'forged'}))
    with pytest.raises(ResearchError, match='RESEARCH_NATIVE_PROOF_BINDING'):
        fresh.read(pub['result_id'])


@pytest.mark.parametrize('mutate', [
    lambda q: q.row.update(state='in-progress'),
    lambda q: q.journal[-1].update(actorSession=AUTHOR),
    lambda q: q.journal[-1].update(identityProvenance='claimed:v1'),
    lambda q: q.journal[0].update(actorSession=AUTHOR),
    lambda q: q.decision.update(claimed_generation='old-generation'),
    lambda q: q.decision['author_sessions'].append(ACTOR),
    lambda q: q.row.update(sourceSession=ACTOR),
    lambda q: q.seat.update(logical_id='quant.a'),
    lambda q: q.row['closingTransition'].update(transitionId=4),
    lambda q: setattr(q, 'change_on_reread', True),
])
def test_forged_role_actor_claim_coauthor_stale_and_changed_custody_rejected(mutate):
    queue = Queue(invented_result()); mutate(queue)
    with pytest.raises(ResearchError): resolve(REF, queue)


def test_wrong_content_candidate_config_and_decision_address(tmp_path):
    result = invented_result(); store = ResearchResults(tmp_path, 10**8, native_review_writer_enabled=True); store.publish(result)
    for key, wrong in [('candidate_id', 'changed-candidate'), ('code_revision', '8'*40),
                       ('protocol_sha256', '9'*64), ('data_sha256', 'a'*64)]:
        queue = Queue(result); queue.decision['bindings'] = {**result['bindings'], key: wrong}
        with pytest.raises(ResearchError, match='RESEARCH_NATIVE_DECISION_BINDING'):
            store.native_review(REF, queue=queue)
    for ref in [REF+'extra', 'qitem-invented-binding#4', 'arbitrary-url', '../qitem#3']:
        with pytest.raises(ResearchError): resolve(ref, Queue(result))
    assert store.read('research-'+sha(canonical(result)))['assessment']['financial'] == 'NOT_REVIEWED'


@pytest.mark.postgres
def test_native_delivery_before_result_replay_and_no_scientific_run(registry):
    reg = registry; reg.migrate()
    result = invented_result(); queue = Queue(result)
    store = ResearchResults(reg.settings.artifacts, 10**8, native_queue=queue, native_review_writer_enabled=True)
    unrelated = invented_result(); unrelated['question']['label'] = 'Unrelated queued subject'
    other = submit(reg, {'schema_version': 'polar.research-delivery/1', 'kind': 'RESULT',
        'display_scope': 'OWNER_LOCAL', 'content_sha256': sha(canonical(unrelated)), 'payload': unrelated})
    submitted = submit(reg, {'decision_ref': REF}, native_queue=queue)
    assert deliver_once(reg, store, delivery_id=submitted['id'])['state'] == 'WAITING_FOR_RESULT'
    assert reg.research_delivery(other['id'])['state'] == 'QUEUED'
    with reg.connect() as db:
        db.execute("UPDATE research_deliveries SET not_before=now()+interval '1 hour' WHERE id=%s", (submitted['id'],))
    h = sha(canonical(result))
    result_row = submit(reg, {'schema_version': 'polar.research-delivery/1', 'kind': 'RESULT',
        'display_scope': 'OWNER_LOCAL', 'content_sha256': h, 'payload': result})
    assert deliver_once(reg, store, delivery_id=result_row['id'])['state'] == 'DELIVERED'
    with reg.connect() as db:
        db.execute("UPDATE research_deliveries SET not_before=now()-interval '1 second' WHERE id=%s", (submitted['id'],))
    done = deliver_once(reg, store, delivery_id=submitted['id'])
    assert done['id'] == submitted['id'] and done['state'] == 'DELIVERED'
    assert done['receipt']['status'] == 'VERIFIED_NATIVE_DECISION'
    assert store.read('research-'+h)['assessment']['native_review']['financial'] == 'NOT_SUPPORTED'
    assert submit(reg, {'decision_ref': REF}, native_queue=queue)['state'] == 'DELIVERED'
    assert deliver_once(reg, store, delivery_id=submitted['id']) is None
    assert reg.research_delivery(other['id'])['state'] == 'QUEUED'
    with reg.connect() as db:
        assert [db.execute('SELECT count(*) AS n FROM '+t).fetchone()['n'] for t in ('runs','attempts')] == [0,0]


def test_native_writer_is_off_until_reader_and_replay_floor(tmp_path):
    store = ResearchResults(tmp_path, 10**8)
    pub = store.publish(invented_result())
    with pytest.raises(ResearchError, match='RESEARCH_NATIVE_REVIEW_WRITER_DISABLED'):
        store.review({'decision_ref': REF})
    assert store.read(pub['result_id'])['assessment']['native_review']['financial'] == 'NOT_REVIEWED'


def test_retained_native_review_requires_tool_run_and_config(tmp_path):
    result=invented_result();result['evidence_level']='RETAINED_DESCRIPTIVE'
    store=ResearchResults(tmp_path,10**8,native_review_writer_enabled=True)
    store.publish(result)
    with pytest.raises(ResearchError,match='RESEARCH_NATIVE_EXECUTION_BINDING'):
        store.native_review(REF,queue=Queue(result))
    result['bindings'].update(config_sha256='b'*64,run_id='11111111-1111-4111-8111-111111111111')
    publication=store.publish(result)
    for key,value in [('config_sha256','c'*64),('run_id','22222222-2222-4222-8222-222222222222')]:
        q=Queue(result);q.decision['bindings']={**q.decision['bindings'],key:value}
        with pytest.raises(ResearchError,match='RESEARCH_NATIVE_DECISION_BINDING'):
            store.native_review(REF,queue=q)
    store.native_review(REF,queue=Queue(result))
    assert store.read(publication['result_id'])['assessment']['native_review']['financial']=='NOT_SUPPORTED'
