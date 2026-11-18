"""One closed read-only observation of a failed Band producer's existing output.

Original publication and failure are never changed. This operation cannot
materialize, fetch, normalize, execute policy or certify historical custody.
"""
from datetime import datetime, timezone
from pathlib import Path
import re
import time

from . import band_source as source
from .ci_research import require
from .history_bundle import canonical, sha, read_file
from .history_store import HistoryStore
from .research_reference import decode, pinned_bytes, MAX_BYTES

REQUEST = 'polar.band-existing-publication-reconciliation/1'
OBSERVATION = 'polar.band-existing-publication-observation/1'
TERMINAL = 'polar.band-source-reconciliation-result/1'
STATUS = 'CURRENT_EXISTING_ARTIFACT_CUSTODY_AND_INTEGRITY_RECONCILED_WITH_LIMITS'
ORIGINAL_TASK = 'qitem-band-data-source-producer-operation-v2-20261118'
ORIGINAL_CLAIM = 80053
ORIGINAL_TERMINAL = 80057
ORIGINAL_CODE = '5799eda23cd2d09d7d3d50e016f1c3f613dc11583bf1815c4bf2e98706a38553'
ORIGINAL_REVISION = '1f33683fee17fe8f1dff245d202325e4b7da99f2'
ORIGINAL_CONFIG = 'b180991973ab69fc62d659723ff921295a8f96a2a9740fd906e6d01c813b58e0'
ORIGINAL_MANIFEST = 'e7a82913e59a6553f2015c5d9c68ee342534346e84334ec7933b7ffc9c3cf058'
ORIGINAL_RUNTIME = 'sha256:56c8f793099cd979c7d4ccbd329b6ce008a5a4c178f0973972f05da6f77aa219'
FILES = {'manifest.json', 'quotes.ndjson', 'schedule.json', 'source-relations.json', 'quality.json'}
FIELDS = {'schema', 'namespace', 'question_id', 'actor_session', 'consumer_task', 'code',
          'code_revision', 'runtime_image_id', 'artifact_root_identity', 'input_ref',
          'original_failure_ref'}
COMPATIBILITY = 'EXACT_ORIGINAL_BAND_CONFIG11_FAILED_CLOSURE_AND_SAME_CURRENT_OBSERVER_CODE'


class Audit:
    """Retain only custody comparison operands, never source or queue bodies."""
    def __init__(self, queue, expected):
        self.queue, self.expected, self.reads = queue, expected, []
        self.expected_generation = None

    def read(self, *args):
        value = self.queue.read(*args)
        safe = {'read': args[0], 'expected_actor': self.expected['actor_session'],
                'expected_generation': self.expected_generation,
                'observer_task': self.expected['consumer_task']}
        if args[0] == 'ps':
            rows = value.get('entries') if isinstance(value, dict) else value
            safe['cardinality'] = len(rows) if isinstance(rows, list) else None
            safe['actual'] = [{k: row.get(k) for k in
                ('rigName', 'logicalId', 'canonicalSessionName', 'sessionStatus')} |
                {'activity': {k: row.get('agentActivity', {}).get(k) for k in
                    ('generation', 'generationProvenance', 'evidenceSource', 'stale', 'fallback', 'sampledAt')}}
                for row in rows[:2]] if isinstance(rows, list) else None
        elif args[0] == 'whoami':
            safe['actual'] = {k: value.get('identity', {}).get(k) for k in
                              ('sessionName', 'rigName', 'logicalId', 'nodeId')}
        elif args[:2] == ('seat', 'status'):
            safe['actual'] = {k: value.get(k) for k in ('current_occupant', 'rig_name', 'logical_id')}
        elif args[:2] == ('queue', 'show'):
            safe['actual'] = {k: value.get(k) for k in
                ('qitemId', 'state', 'destinationSession', 'claimedByGeneration', 'claimedAt')}
            if value.get('qitemId') == self.expected['consumer_task']:
                self.expected_generation = value.get('claimedByGeneration')
                safe['expected_generation'] = self.expected_generation
        # No resolution, task body, transition body, source ref or source value.
        if len(self.reads) < 128:
            self.reads.append(safe)
        return value


def _pin(path, raw):
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def _base_pin(pin):
    require(type(pin) is dict and {'path', 'sha256'} <= set(pin) <= {'path', 'sha256', 'bytes'},
            'BAND_RECONCILIATION_INPUT_PIN')
    return pin


def observer_binding(request, root):
    from .candidate_binding import loaded_revision
    from .ci_research_service import root_identity
    from .gym_service import code_binding
    question, _, _, _ = source.method_binding()
    require(type(request) is dict and set(request) == FIELDS and request['schema'] == REQUEST and
            request['namespace'] in ('INVENTED', 'RETAINED') and request['question_id'] == question and
            request['actor_session'] in source.ACTORS and
            type(request['consumer_task']) is str and
            re.fullmatch(r'qitem-[A-Za-z0-9_.:-]+', request['consumer_task']) is not None,
            'BAND_RECONCILIATION_SCOPE')
    require(request['consumer_task'] != request['original_failure_ref'].split('#')[0],
            'BAND_RECONCILIATION_SEPARATE_OBSERVER')
    require((request['namespace'] == 'INVENTED') ==
            request['consumer_task'].startswith('qitem-INVENTED'), 'BAND_RECONCILIATION_NAMESPACE')
    require(Path(root).is_absolute() and Path(root).resolve() == Path(root) and
            request['artifact_root_identity'] == root_identity(root), 'BAND_RECONCILIATION_ROOT')
    require(request['code'] == code_binding() and request['code_revision'] == loaded_revision(),
            'BAND_RECONCILIATION_CURRENT_CODE')
    source.actual_runtime(request)
    _base_pin(request['input_ref'])
    require(re.fullmatch(r'qitem-[A-Za-z0-9_.:-]+#[1-9][0-9]*', request['original_failure_ref']) is not None,
            'BAND_RECONCILIATION_FAILURE_REFERENCE')


def _failure(request, config, proof, queue):
    task, terminal_id = request['original_failure_ref'].split('#')
    terminal_id = int(terminal_id)
    require(task == config['consumer_task'] == proof['consumer_task'] and
            proof['actor'] == config['actor_session'], 'BAND_RECONCILIATION_ORIGINAL_PROOF')
    row = queue.read('queue', 'show', task, '--full')
    events = queue.read('queue', 'transitions', task, '--full')
    require(row.get('qitemId') == task and row.get('state') == 'done' and
            row.get('destinationSession') == proof['actor'] and
            row.get('claimedByGeneration') == proof['generation'] and
            row.get('claimedAt') == proof['claimed_at'] and
            row.get('closureReason') == 'no-follow-on' and source.TAGS <= set(row.get('tags', [])),
            'BAND_RECONCILIATION_ORIGINAL_CUSTODY')
    claims = [e for e in events if e.get('state') == 'in-progress' and e.get('transitionNote') == 'claimed']
    terminals = [e for e in events if e.get('state') == 'done']
    require(bool(claims) and bool(terminals), 'BAND_RECONCILIATION_ORIGINAL_TRANSITIONS')
    claim = max(claims, key=lambda e: e['transitionId'])
    terminal = max(terminals, key=lambda e: e['transitionId'])
    require(claim['transitionId'] == proof['claim_transition'] < terminal_id == terminal['transitionId'] and
            all(e.get('actorSession') == proof['actor'] and e.get('identityProvenance') == 'transport:v1'
                for e in (claim, terminal)), 'BAND_RECONCILIATION_ORIGINAL_TRANSITIONS')
    resolution = decode(row['resolution'])
    require(resolution.get('schema') == 'engineering.band-source-producer-failure/1' and
            resolution.get('status') == 'SOURCE_PUBLICATION_UNQUALIFIED_NATIVE_POSTCHECK_REJECTED' and
            resolution.get('error_code') == 'BAND_SOURCE_GENERATION' and
            resolution.get('consumer_task') == task and
            resolution.get('source_preparation_replayed') is False and
            resolution.get('financial_run') == 'NOT_RUN' and
            resolution.get('manifest') == {k: request['input_ref'][k] for k in ('path', 'sha256')},
            'BAND_RECONCILIATION_ORIGINAL_FAILURE')
    if request['namespace'] == 'RETAINED':
        require(task == ORIGINAL_TASK and claim['transitionId'] == ORIGINAL_CLAIM and
                terminal_id == ORIGINAL_TERMINAL, 'BAND_RECONCILIATION_EXACT_ORIGINAL')
    again = queue.read('queue', 'show', task, '--full')
    require(all(again.get(k) == row.get(k) for k in source.TASK_FIELDS),
            'BAND_RECONCILIATION_ORIGINAL_CHANGED')
    return {'task': task, 'claim_transition': claim['transitionId'], 'terminal_transition': terminal_id,
            'generation': proof['generation'], 'resolution_sha256': sha(canonical(resolution)),
            'status': resolution['status'], 'historical_postcheck': 'FAILED_CAUSE_UNKNOWN'}


def _inventory(pin):
    directory = Path(pin['path']).parent
    require(directory.name.startswith('reference-input-') and directory.parent.name == 'reference-inputs' and
            directory.resolve() == directory and {p.name for p in directory.iterdir()} == FILES,
            'BAND_RECONCILIATION_OBJECT_SET')
    result = {}
    for name in sorted(FILES):
        path = directory/name
        before = path.stat(follow_symlinks=False)
        require(not path.is_symlink() and path.is_file(), 'BAND_RECONCILIATION_OBJECT')
        raw = read_file(directory, name, limit=MAX_BYTES)
        after = path.stat(follow_symlinks=False)
        signature = lambda s: [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode]
        require(signature(before) == signature(after), 'BAND_RECONCILIATION_OBJECT_CHANGED')
        result[name] = {'sha256': sha(raw), 'bytes': len(raw), 'identity': signature(after)}
    require(result['manifest.json']['sha256'] == pin['sha256'], 'BAND_RECONCILIATION_MANIFEST')
    return result


def verify_publication(request, root, queue):
    """Validate saved bytes/relationships only; no original price-member reader."""
    from .research_reference import _load_reference_values
    pin = request['input_ref']
    require(Path(pin['path']).is_relative_to(Path(root)/'reference-inputs') and
            Path(pin['path']).name == 'manifest.json', 'BAND_RECONCILIATION_INPUT_ROOT')
    manifest = decode(pinned_bytes(pin))
    metadata = manifest.get('conversion_metadata', manifest.get('provenance', {}))
    proof = metadata.get('source_native_binding', {})
    config = proof.get('config', {})
    require(config.get('schema') == source.SOURCE_SCHEMA and config.get('namespace') == request['namespace'] and
            config.get('artifact_root_identity') == request['artifact_root_identity'],
            'BAND_RECONCILIATION_PRODUCER_SCOPE')
    source.current_binding(config, root, historical=True)
    require(proof.get('scope_sha256') == sha(canonical(config)), 'BAND_RECONCILIATION_ORIGINAL_PROOF')
    if request['namespace'] == 'RETAINED':
        require(config['code_revision'] == ORIGINAL_REVISION and sha(canonical(config['code'])) == ORIGINAL_CODE and
                sha(canonical(config)) == ORIGINAL_CONFIG and pin['sha256'] == ORIGINAL_MANIFEST and
                config['runtime_image_id'] == ORIGINAL_RUNTIME, 'BAND_RECONCILIATION_COMPATIBILITY')
    else:
        require(config['consumer_task'].startswith('qitem-INVENTED') and
                config['candidate_id'].startswith('INVENTED'), 'BAND_RECONCILIATION_NAMESPACE')
    failure = _failure(request, config, proof, queue)
    spec = source.checked_spec(config)
    require(metadata.get('converter') == 'polar.selected-component-materializer/1' and
            metadata.get('spec') == spec and metadata.get('private_root') == str(root) and
            metadata.get('parent_schedule') == spec['schedule'] and
            manifest.get('symbols') == ['BIL', 'VTI'] and manifest.get('dates') == spec['date_range'],
            'BAND_RECONCILIATION_SAVED_SPEC')
    before = _inventory(pin)
    directory = Path(pin['path']).parent
    for key, name in (('quotes', 'quotes.ndjson'), ('schedule', 'schedule.json'), ('source_relations', 'source-relations.json')):
        require(manifest[key] == {'path': str(directory/name), 'sha256': before[name]['sha256'],
                                 'bytes': before[name]['bytes']}, 'BAND_RECONCILIATION_FILE_PIN')
    quality = decode(read_file(directory, 'quality.json', limit=MAX_BYTES))
    require(quality == {'status': 'SELECTED_SOURCE_ONLY', 'excluded_value_decodes': 0,
            'mixed_parent_quote_reads': 0, 'raw_source_body_reads': 0, 'financial_or_provider_calls': 0,
            'integrity_scope': 'SELECTED_MEMBERS_HASHED_SELECTED_ROWS_VALIDATED_EXCLUDED_VALUES_UNDECODED'} and
            metadata.get('integrity_scope') == quality['integrity_scope'] and
            metadata.get('raw_source_bodies') == 'POINTER_HASH_BINDING_ONLY_NOT_REOPENED',
            'BAND_RECONCILIATION_SAVED_QUALITY')
    # Shared existing reader verifies every saved row's units/token/calendar/
    # original source pointer/normalization relation. Never calls materializer.
    market = _load_reference_values(pin, manifest)
    from .selected_reference_input import RIGHTS
    rights = 'INVENTED_PUBLIC_TEST' if request['namespace'] == 'INVENTED' else RIGHTS
    relations = market['source_relations']
    require(manifest.get('rights') == rights and relations.get('source_purpose') == spec['purpose_ref'] and
            relations.get('source_qualifications') == spec['qualification_refs'] and
            relations.get('eligibility_ledger') == {'selected_aliases_fixed_order': ['BIL', 'VTI']} and
            sorted(r['literal_alias'] for r in relations['records']) == ['BIL', 'VTI'] and
            all(r.get('selected_for_purpose') is True for r in relations['records']),
            'BAND_RECONCILIATION_SAVED_RELATIONS')
    for record in relations['records']:
        if 'canonical_job_id' in record:
            request_basis = relations['jobs'][record['canonical_job_id']]['request']
        elif 'capture_return' in record:
            request_basis = relations['captures'][record['capture_return']['sha256']]['request']
        elif 'capture_receipt' in record:
            request_basis = relations['single_symbol_captures'][record['capture_receipt']['sha256']]['request']
        else:
            require(False, 'BAND_RECONCILIATION_SAVED_RELATIONS')
        require(request_basis.get('symbols') == record['literal_alias'] and
                request_basis.get('adjustment') == 'all', 'BAND_RECONCILIATION_SAVED_RELATIONS')
    semantic = {'converter': metadata['converter'], 'spec': spec, 'source_native_binding': proof,
                'quotes_sha256': before['quotes.ndjson']['sha256'], 'schedule_sha256': before['schedule.json']['sha256'],
                'relations_sha256': before['source-relations.json']['sha256']}
    revision = 'reference-input-' + sha(canonical(semantic))
    require(directory.name == revision and manifest['parent_dataset_revision'] ==
            ('INVENTED-' if request['namespace'] == 'INVENTED' else '') + revision,
            'BAND_RECONCILIATION_SAVED_IDENTITY')
    require(_inventory(pin) == before, 'BAND_RECONCILIATION_OBJECT_CHANGED')
    return manifest, market, before, failure


def result(receipt, observation_ref):
    return {'schema': TERMINAL, 'status': STATUS, 'observer_task': receipt['request']['consumer_task'],
            'request_sha256': sha(canonical(receipt['request'])), 'observation_ref': observation_ref,
            'input_ref': receipt['request']['input_ref'],
            'original_failure_ref': receipt['request']['original_failure_ref'],
            'original_preparation_status': 'FAILED_CAUSE_UNKNOWN'}


def reconcile(request, root, limit, *, queue=None):
    observer_binding(request, root)  # before opening any selected input pin
    audit = Audit(queue or source.current_queue(), request)
    store = HistoryStore(root, limit)
    name = sha(request['consumer_task'].encode())
    parent = 'band-source-reconciliation-attempts'
    with store.locked():
        require(not (Path(root)/parent/name).exists(), 'BAND_RECONCILIATION_ALREADY_RECORDED')
        store._publish(parent, name, {'request.json': canonical(request)})
    started = time.time_ns()
    try:
        proof = source.task_custody(request, audit)
        manifest, _, inventory, failure = verify_publication(request, root, audit)
        source.task_custody(request, audit, prior=proof)
        observer_binding(request, root)
        receipt = {'schema': OBSERVATION, 'status': STATUS, 'request': request,
                   'observer_proof': proof, 'started_ns': started, 'finished_ns': time.time_ns(),
                   'original_failure': failure, 'files': inventory, 'compatibility': COMPATIBILITY,
                   'original_preparation_status': 'FAILED_CAUSE_UNKNOWN',
                   'source_only': True, 'source_materialization_calls': 0, 'financial_calls': 0}
        raw = canonical(receipt)
        with store.locked():
            store._publish(parent+'/'+name, 'finish',
                           {'observation.json': raw, 'custody-comparisons.json': canonical(audit.reads)})
        observation_ref = _pin(Path(root)/parent/name/'finish/observation.json', raw)
        return {'schema': 'polar.band-reconciliation-return/1', 'status': STATUS,
                'observation_ref': observation_ref, 'producer_terminal_result': result(receipt, observation_ref),
                'input_ref': {**request['input_ref'], 'reconciliation_ref': {
                    'observation_ref': observation_ref, 'observer_task': request['consumer_task']}},
                'source_only_preflight': 'NOT_RUN_REQUIRES_SEPARATE_NATIVE_TERMINAL',
                'original_preparation_status': 'FAILED_CAUSE_UNKNOWN'}
    except BaseException as exc:
        code = str(exc)
        if re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}', code) is None:
            code = 'BAND_RECONCILIATION_FAILED'
        with store.locked():
            store._publish(parent+'/'+name, 'failure', {'failure.json': canonical({
                'status': 'RECONCILIATION_FAILED_UNQUALIFIED', 'error_code': code,
                'started_ns': started, 'finished_ns': time.time_ns()}),
                'custody-comparisons.json': canonical(audit.reads)})
        raise ValueError(code) from None


def authorize_existing(manifest, reference, *, queue=None):
    """New native terminal PLUS unchanged original failure; no success rewrite."""
    require(type(reference) is dict and set(reference) == {'observation_ref', 'observer_task'},
            'BAND_RECONCILIATION_REFERENCE')
    receipt = decode(pinned_bytes(reference['observation_ref']))
    require(receipt.get('schema') == OBSERVATION and receipt.get('status') == STATUS and
            receipt.get('original_preparation_status') == 'FAILED_CAUSE_UNKNOWN' and
            receipt.get('compatibility') == COMPATIBILITY and receipt.get('source_only') is True and
            receipt.get('source_materialization_calls') == receipt.get('financial_calls') == 0 and
            type(receipt.get('started_ns')) is int and type(receipt.get('finished_ns')) is int and
            receipt['started_ns'] <= receipt['finished_ns'], 'BAND_RECONCILIATION_OBSERVATION')
    request = receipt['request'];root = Path(request['artifact_root_identity']['path'])
    expected_path = root/'band-source-reconciliation-attempts'/sha(request['consumer_task'].encode())/'finish/observation.json'
    require(reference['observer_task'] == request['consumer_task'] and
            Path(reference['observation_ref']['path']) == expected_path,
            'BAND_RECONCILIATION_REFERENCE')
    # Observer revision stays historical. Current reader must run the same
    # accepted code and actual runtime/root, not the old producer's build.
    from .candidate_binding import loaded_revision
    observer_binding({**request, 'code_revision': loaded_revision()}, root)
    queue = queue or source.current_queue()
    proof = source.task_custody(request, queue, prior=receipt['observer_proof'],
                               terminal_result=result(receipt, reference['observation_ref']), require_terminal=True)
    actual, _, inventory, failure = verify_publication(request, root, queue)
    require(canonical(actual) == canonical(manifest) and inventory == receipt['files'] and
            failure == receipt['original_failure'], 'BAND_RECONCILIATION_RECEIPT_BINDING')
    events = queue.read('queue', 'transitions', request['consumer_task'], '--full')
    terminal = max((e for e in events if e.get('state') == 'done'), key=lambda e: e['transitionId'])
    closed = datetime.fromisoformat(terminal['ts'].replace('Z', '+00:00')).astimezone(timezone.utc)
    require(int(closed.timestamp()*1_000_000_000) >= receipt['finished_ns'],
            'BAND_RECONCILIATION_TERMINAL_CLOCK')
    source.task_custody(request, queue, prior=proof, terminal_result=result(receipt, reference['observation_ref']),
                        require_terminal=True)
    return {'status': STATUS, 'original_failure': failure, 'observer_proof': proof,
            'observation_ref': reference['observation_ref']}
