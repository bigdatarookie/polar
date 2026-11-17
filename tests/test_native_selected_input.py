"""Inert current-native authority and invented source graph; no private sources."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from polar import native_selected_input as selected
from polar.history_bundle import canonical, sha
from polar.ci_research_service import root_identity
from polar.gym_service import code_binding
from polar.reference_input import prepare_input, preflight_input
from polar.research_reference import load_reference
from test_reference_input import put
from test_selected_reference_input import selected_fixture

ACTOR = 'quant-a@polar-rig'
TASK = 'qitem-invented-author'
ADMISSION = 'qitem-invented-semantic'


class Queue:
    def __init__(self, cfg):
        claim = {'transitionId': 2, 'state': 'in-progress', 'transitionNote': 'claimed',
                 'actorSession': ACTOR, 'identityProvenance': 'transport:v1'}
        self.claims = [claim]
        self.task = {'qitemId': TASK, 'state': 'in-progress', 'destinationSession': ACTOR,
                     'claimedByGeneration': 'invented-generation', 'claimedAt': '2026-01-01T00:00:00Z'}
        self.identity = {'sessionName': ACTOR, 'nodeId': 'invented-node', 'logicalId': 'quant.a', 'rigName': 'polar-rig'}
        self.seat = {'current_occupant': ACTOR, 'logical_id': 'quant.a', 'rig_name': 'polar-rig'}
        self.closing = [{'transitionId': 3, 'state': 'done', 'actorSession': ACTOR, 'identityProvenance': 'transport:v1'}]
        self.row = {'qitemId': ADMISSION, 'state': 'done', 'destinationSession': ACTOR,
            'claimedByGeneration': 'invented-generation', 'closingTransition': {'transitionId': 3},
            'resolution': json.dumps({'schema': 'polar.native-selected-source-admission/1',
                'status': 'ADMITTED_WITH_LIMITS', 'consumer_task': TASK,
                'claimed_generation': 'invented-generation', 'scope_sha256': sha(canonical(selected.scope(cfg))),
                'symbols': ['BIL', 'VTI'], 'scientific_verdict': 'NOT_REVIEWED'})}
    def read(self, *args):
        if args == ('whoami',):return {'identity': deepcopy(self.identity)}
        if args[:2] == ('seat', 'status'):return deepcopy(self.seat)
        if args[:2] == ('queue', 'show'):return deepcopy(self.task if args[2] == TASK else self.row)
        if args == ('queue', 'claim', TASK):return deepcopy(self.task)
        if args[:2] == ('queue', 'transitions'):return deepcopy(self.claims if args[2] == TASK else self.closing)
        raise AssertionError(args)


def fixture(tmp_path, monkeypatch):
    store, old, records, rows = selected_fixture(tmp_path, targets=['VTI', 'BIL', 'SHY'])
    # The old converter is exercised only to build an invented parent fixture.
    result = prepare_input(old, store, 10**8)
    parent = json.loads(Path(result['input_ref']['path']).read_bytes())
    raw = Path(parent['quotes']['path']).read_bytes()
    bilrows = [line for line in raw.splitlines(keepends=True) if json.loads(line)['symbol'] == 'BIL']
    bil = deepcopy(parent)
    bil.update(symbols=['BIL'], rows=len(bilrows), quotes=put(tmp_path/'bil-only-quotes.ndjson', b''.join(bilrows)))
    bilpin = put(tmp_path/'bil-only-input.json', bil)
    meta = put(tmp_path/'semantic-purpose.json', {'kind': 'INVENTED_SOURCE_PURPOSE_WITH_LIMITS'})
    cfg = {'schema': selected.SCHEMA, 'profile_id': selected.PROFILE, 'namespace': 'INVENTED',
        'semantic_candidate': selected.SEMANTIC_CANDIDATE, 'code_revision': 'a'*40,
        'code': code_binding(), 'runtime_image_id': 'sha256:'+'b'*64,
        'consumer_task': TASK, 'source_admission_ref': ADMISSION+'#3',
        'artifact_root_identity': root_identity(store), 'purpose_ref': meta, 'purpose_fit_ref': meta,
        'protocol_ref': meta, 'vti_binding_ref': old['binding'], 'vti_parent_ref': result['input_ref'],
        'bil_input_ref': bilpin, 'operation': 'SELECTED_INPUT_PREPARE_AND_READ'}
    queue = Queue(cfg)
    monkeypatch.setattr(selected, 'current_queue', lambda: queue)
    return store, cfg, queue, parent, rows


def test_selected_spans_only_preserve_tokens_graph_clocks_and_replay(tmp_path, monkeypatch):
    root, cfg, queue, parent, original = fixture(tmp_path, monkeypatch)
    seen = []; real_read = selected.pinned_bytes; real_decode = selected.decode
    def read(pin):
        seen.append(pin['path']); return real_read(pin)
    def decode(raw):
        value = real_decode(raw)
        if isinstance(value, dict):assert value.get('query_symbol') != 'SHY'
        return value
    monkeypatch.setattr(selected, 'pinned_bytes', read)
    monkeypatch.setattr(selected, 'decode', decode)
    out = prepare_input(cfg, root, 10**8, native_queue=queue)
    assert parent['quotes']['path'] not in seen  # Mixed parent never opened.
    assert not any('/objects/' in p for p in seen)  # No raw source-body decode.
    market = load_reference(out['input_ref'])
    assert market['symbols'] == ['BIL', 'VTI'] and market['dates'] == ['2024-01-31', '2024-02-01', '2024-02-02']
    manifest = json.loads(Path(out['input_ref']['path']).read_bytes())
    quotes = [json.loads(l) for l in Path(manifest['quotes']['path']).read_bytes().splitlines()]
    assert {v['symbol'] for v in quotes} == {'BIL', 'VTI'}
    assert all(v['observed_published_at'] is v['observed_historical_available_at'] is None for v in quotes)
    assert [v['source_adjusted_close_token'] for v in quotes if v['symbol'] == 'VTI'] == ['20.1']*3
    assert quotes[1]['source_ref']['line_sha256'] == sha(original['VTI'][0])
    assert len(market['source_relations']['records']) == 2
    assert 'UNINSPECTED' in manifest['conversion_metadata']['integrity_scope']
    assert preflight_input(out['input_ref'])['status'] == 'STRUCTURALLY_VALID_SOURCE_ONLY'
    assert prepare_input(cfg, root, 10**8, native_queue=queue) == out
    # Existing prepared values cannot bypass a current consumer generation check.
    queue.task['claimedByGeneration'] = 'successor-generation'
    with pytest.raises(ValueError, match='SOURCE_ADMISSION'):load_reference(out['input_ref'])


@pytest.mark.parametrize('field,value', [
    ('semantic_candidate', 'f'*40), ('code_revision', 'f'*40), ('purpose_ref', {'path': '/never/read', 'sha256': '0'*64}),
    ('protocol_ref', {'path': '/never/read', 'sha256': '0'*64}), ('artifact_root_identity', 'foreign-root'),
    ('runtime_image_id', 'sha256:'+'f'*64), ('operation', 'BACKTEST'),
    ('source_admission_ref', None), ('bil_input_ref', {'path': '/never/read', 'sha256': '0'*64}),
])
def test_changed_scope_rejects_before_any_pin_read(tmp_path, monkeypatch, field, value):
    root, cfg, queue, _, _ = fixture(tmp_path, monkeypatch)
    cfg[field] = value
    monkeypatch.setattr(selected, 'pinned_bytes', lambda _: pytest.fail('opened a pin before admission'))
    with pytest.raises((ValueError, TypeError)):prepare_input(cfg, root, 10**8, native_queue=queue)


@pytest.mark.parametrize('part', ['actor', 'generation', 'claim', 'terminal', 'seat', 'task'])
def test_untrusted_native_context_fails_before_source_read(tmp_path, monkeypatch, part):
    root, cfg, queue, _, _ = fixture(tmp_path, monkeypatch)
    if part == 'actor':queue.identity['logicalId'] = 'engineering.platform'
    if part == 'generation':queue.row['claimedByGeneration'] = 'old-generation'
    if part == 'claim':queue.claims[0]['identityProvenance'] = 'request-body'
    if part == 'terminal':queue.closing[0]['actorSession'] = 'forged@polar-rig'
    if part == 'seat':queue.seat['current_occupant'] = 'successor@polar-rig'
    if part == 'task':queue.task['state'] = 'done'
    monkeypatch.setattr(selected, 'pinned_bytes', lambda _: pytest.fail('opened a protected member'))
    with pytest.raises(ValueError):prepare_input(cfg, root, 10**8, native_queue=queue)


def test_wrong_member_hash_symlink_and_selected_alias_escape_fail(tmp_path, monkeypatch):
    root, cfg, queue, parent, _ = fixture(tmp_path, monkeypatch)
    binding = json.loads(Path(cfg['vti_binding_ref']['path']).read_bytes())
    vti = next(r for r in binding['records'] if r['literal_alias'] == 'VTI')
    member = Path(vti['segments'][0]['normalized_member'])
    saved = member.read_bytes(); member.write_bytes(saved+b'corrupted\n')
    with pytest.raises(ValueError, match='FILE_'):prepare_input(cfg, root, 10**8, native_queue=queue)
    member.write_bytes(saved)
    real = member.with_name('real-bars.ndjson'); member.rename(real); member.symlink_to(real)
    with pytest.raises(ValueError, match='REFERENCE_PATH'):prepare_input(cfg, root, 10**8, native_queue=queue)
    member.unlink(); real.rename(member)
    # A changed selection graph cannot inherit the old semantic admission.
    cfg['vti_binding_ref'] = put(tmp_path/'foreign-selection.json', {'schema': 'forged'})
    with pytest.raises(ValueError, match='SOURCE_ADMISSION_BINDING'):
        prepare_input(cfg, root, 10**8, native_queue=queue)


def test_transport_claim_generation_invalidates_previous_occupant_admission(tmp_path, monkeypatch):
    root, cfg, queue, _, _ = fixture(tmp_path, monkeypatch)
    original = queue.read
    def read(*args):
        if args == ('queue', 'claim', TASK):
            queue.task['claimedByGeneration'] = 'new-actual-transport-generation'
        return original(*args)
    queue.read = read
    monkeypatch.setattr(selected, 'pinned_bytes', lambda _: pytest.fail('read before current generation check'))
    with pytest.raises(ValueError, match='SOURCE_ADMISSION'):
        prepare_input(cfg, root, 10**8, native_queue=queue)
