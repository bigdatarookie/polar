"""One closed read-only observation of a failed Band producer's existing output.

Original publication and failure are never changed. This operation cannot
materialize, fetch, normalize, execute policy or certify historical custody.
"""
from datetime import datetime, timezone
from pathlib import Path
import re
import stat
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
        self.comparisons = []
        self.expected_claims = {}

    def compare(self, code, expected, actual):
        if len(self.comparisons) < 256:
            self.comparisons.append({'check': code, 'expected': expected, 'actual': actual})

    def read(self, *args):
        value = self.queue.read(*args)
        safe = {'read': args[0], 'expected_actor': self.expected['actor_session'],
                'expected_generation': self.expected_generation,
                'observer_task': self.expected['consumer_task']}
        if args[0] == 'ps':
            rig,logical=source.ACTORS[self.expected['actor_session']]
            safe['expected']={'cardinality':1,'rigName':rig,'logicalId':logical,
                'canonicalSessionName':self.expected['actor_session'],'sessionStatus':'running',
                'generationProvenance':'resolved','evidenceSource':['native_owner','runtime_hook'],
                'stale':False,'fallback':False,'generation':self.expected_generation}
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
        elif args[:2] == ('queue', 'transitions'):
            safe['expected']={'actorSession':self.expected['actor_session'],
                'identityProvenance':'transport:v1','claim_required':True,
                **self.expected_claims.get(args[2], {})}
            safe['actual']=[{k:e.get(k) for k in
                ('transitionId','state','actorSession','identityProvenance','ts')} |
                {'is_claim':e.get('transitionNote')=='claimed'} for e in value
                if e.get('state') in ('in-progress','done')]
        elif args[:2] == ('queue', 'show'):
            safe['expected']={'qitemId':args[2],'destinationSession':self.expected['actor_session'],
                'tags_required':sorted(source.TAGS),**self.expected_claims.get(args[2], {})}
            safe['actual'] = {k: value.get(k) for k in
                ('qitemId', 'state', 'destinationSession', 'claimedByGeneration', 'claimedAt',
                 'closureReason','closureTarget','handedOffTo','tags')}
            safe['actual']['resolution_sha256']=sha(value['resolution'].encode()) if isinstance(value.get('resolution'),str) else None
            if value.get('qitemId') == self.expected['consumer_task']:
                if self.expected_generation is None:
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
    _compare(queue,'ORIGINAL_PROOF_IDENTITY',
             {'consumer_task':task,'actor':config['actor_session']},
             {k:proof.get(k) for k in ('consumer_task','actor')})
    require(task == config['consumer_task'] == proof['consumer_task'] and
            proof['actor'] == config['actor_session'], 'BAND_RECONCILIATION_ORIGINAL_PROOF')
    if isinstance(queue,Audit):
        queue.expected_claims[task]={'claim_transition':proof['claim_transition'],
            'terminal_transition':terminal_id,'claimedByGeneration':proof['generation'],
            'claimedAt':proof['claimed_at'],'state':'done','closureReason':'no-follow-on'}
    row = queue.read('queue', 'show', task, '--full')
    events = queue.read('queue', 'transitions', task, '--full')
    expected_row={'qitemId':task,'state':'done','destinationSession':proof['actor'],
        'claimedByGeneration':proof['generation'],'claimedAt':proof['claimed_at'],
        'closureReason':'no-follow-on','tags_required':sorted(source.TAGS)}
    _compare(queue,'ORIGINAL_NATIVE_CUSTODY',expected_row,{k:row.get(k) for k in
        ('qitemId','state','destinationSession','claimedByGeneration','claimedAt','closureReason','tags')})
    require(row.get('qitemId') == task and row.get('state') == 'done' and
            row.get('destinationSession') == proof['actor'] and
            row.get('claimedByGeneration') == proof['generation'] and
            row.get('claimedAt') == proof['claimed_at'] and
            row.get('closureReason') == 'no-follow-on' and source.TAGS <= set(row.get('tags', [])),
            'BAND_RECONCILIATION_ORIGINAL_CUSTODY')
    claims = [e for e in events if e.get('state') == 'in-progress' and e.get('transitionNote') == 'claimed']
    terminals = [e for e in events if e.get('state') == 'done']
    _compare(queue,'ORIGINAL_NATIVE_TRANSITION_PRESENCE',{'claim':True,'terminal':True},
             {'claim':bool(claims),'terminal':bool(terminals)})
    require(bool(claims) and bool(terminals), 'BAND_RECONCILIATION_ORIGINAL_TRANSITIONS')
    claim = max(claims, key=lambda e: e['transitionId'])
    terminal = max(terminals, key=lambda e: e['transitionId'])
    _compare(queue,'ORIGINAL_NATIVE_TRANSITIONS',
        {'claim_transition':proof['claim_transition'],'terminal_transition':terminal_id,
         'actorSession':proof['actor'],'identityProvenance':'transport:v1'},
        {'claim':{k:claim.get(k) for k in ('transitionId','actorSession','identityProvenance')},
         'terminal':{k:terminal.get(k) for k in ('transitionId','actorSession','identityProvenance')}})
    require(claim['transitionId'] == proof['claim_transition'] < terminal_id == terminal['transitionId'] and
            all(e.get('actorSession') == proof['actor'] and e.get('identityProvenance') == 'transport:v1'
                for e in (claim, terminal)), 'BAND_RECONCILIATION_ORIGINAL_TRANSITIONS')
    resolution = decode(row['resolution'])
    expected_failure={'schema':'engineering.band-source-producer-failure/1',
        'status':'SOURCE_PUBLICATION_UNQUALIFIED_NATIVE_POSTCHECK_REJECTED','error_code':'BAND_SOURCE_GENERATION',
        'consumer_task':task,'source_preparation_replayed':False,'financial_run':'NOT_RUN',
        'manifest':{k:request['input_ref'][k] for k in ('path','sha256')}}
    _compare(queue,'ORIGINAL_FAILURE_FIELDS',
        {k:sha(canonical(v)) for k,v in expected_failure.items()},
        {k:sha(canonical(resolution.get(k))) for k in expected_failure})
    require(resolution.get('schema') == 'engineering.band-source-producer-failure/1' and
            resolution.get('status') == 'SOURCE_PUBLICATION_UNQUALIFIED_NATIVE_POSTCHECK_REJECTED' and
            resolution.get('error_code') == 'BAND_SOURCE_GENERATION' and
            resolution.get('consumer_task') == task and
            resolution.get('source_preparation_replayed') is False and
            resolution.get('financial_run') == 'NOT_RUN' and
            resolution.get('manifest') == {k: request['input_ref'][k] for k in ('path', 'sha256')},
            'BAND_RECONCILIATION_ORIGINAL_FAILURE')
    if request['namespace'] == 'RETAINED':
        _compare(queue,'EXACT_ORIGINAL_NATIVE_REFERENCE',
                 {'task':ORIGINAL_TASK,'claim':ORIGINAL_CLAIM,'terminal':ORIGINAL_TERMINAL},
                 {'task':task,'claim':claim['transitionId'],'terminal':terminal_id})
        require(task == ORIGINAL_TASK and claim['transitionId'] == ORIGINAL_CLAIM and
                terminal_id == ORIGINAL_TERMINAL, 'BAND_RECONCILIATION_EXACT_ORIGINAL')
    again = queue.read('queue', 'show', task, '--full')
    _compare(queue,'ORIGINAL_CUSTODY_UNCHANGED',
        {k:sha(canonical(row.get(k))) for k in source.TASK_FIELDS},
        {k:sha(canonical(again.get(k))) for k in source.TASK_FIELDS})
    require(all(again.get(k) == row.get(k) for k in source.TASK_FIELDS),
            'BAND_RECONCILIATION_ORIGINAL_CHANGED')
    return {'task': task, 'claim_transition': claim['transitionId'], 'terminal_transition': terminal_id,
            'generation': proof['generation'], 'resolution_sha256': sha(canonical(resolution)),
            'status': resolution['status'], 'historical_postcheck': 'FAILED_CAUSE_UNKNOWN'}


def _compare(queue, code, expected, actual):
    if isinstance(queue, Audit):
        queue.compare(code, expected, actual)


def _signature(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode]


def _read_saved(pin, queue, *, limit=MAX_BYTES):
    """Bounded descriptor read with exact safe byte/inode rejection operands."""
    path=Path(pin['path'])
    expected={k:pin.get(k) for k in ('sha256','bytes')}
    expected.update(path=str(path),max_bytes=limit,kind='REGULAR_NO_SYMLINK',
                    canonical_absolute_path=True)
    actual={'path':str(path),'sha256':None,'bytes':None,'identity':None,
            'canonical_absolute_path':path.is_absolute() and path.resolve()==path}
    try:
        info=path.stat(follow_symlinks=False)
        actual.update(bytes=info.st_size,identity=_signature(info),
                      kind='REGULAR_NO_SYMLINK' if stat.S_ISREG(info.st_mode) else 'OTHER')
        require(actual['canonical_absolute_path'], 'REFERENCE_PATH')
        raw=read_file(path.parent,path.name,limit=limit)
        actual['sha256']=sha(raw)
        _compare(queue,'SAVED_FILE_INTEGRITY',expected,actual)
        require(sha(raw)==pin['sha256'] and
                ('bytes' not in pin or len(raw)==pin['bytes']), 'REFERENCE_FILE_HASH')
        after=_signature(path.stat(follow_symlinks=False))
        _compare(queue,'SAVED_FILE_IDENTITY_UNCHANGED',{'identity':actual['identity']},{'identity':after})
        require(actual['identity']==after,'BAND_RECONCILIATION_OBJECT_CHANGED')
        return raw
    except (OSError,ValueError) as exc:
        actual['read_status']='MISSING' if isinstance(exc,FileNotFoundError) else 'REJECTED'
        _compare(queue,'SAVED_FILE_INTEGRITY',expected,actual)
        raise


QUALITY={'status':'SELECTED_SOURCE_ONLY','excluded_value_decodes':0,
         'mixed_parent_quote_reads':0,'raw_source_body_reads':0,'financial_or_provider_calls':0,
         'integrity_scope':'SELECTED_MEMBERS_HASHED_SELECTED_ROWS_VALIDATED_EXCLUDED_VALUES_UNDECODED'}


def _inventory(pin, manifest, queue):
    directory=Path(pin['path']).parent
    names={p.name for p in directory.iterdir()}
    _compare(queue,'SAVED_OBJECT_SET',{'names':sorted(FILES),'canonical_directory':True},
             {'names':sorted(n for n in names if n in FILES),
              'other_name_hashes':sorted(sha(n.encode()) for n in names-FILES),
              'canonical_directory':directory.resolve()==directory})
    for name in sorted(FILES):
        _compare(queue,'SAVED_FILE_PRESENCE',{'file':name,'present':True},{'file':name,'present':name in names})
    require(directory.name.startswith('reference-input-') and directory.parent.name=='reference-inputs' and
            directory.resolve()==directory and names==FILES,'BAND_RECONCILIATION_OBJECT_SET')
    quality=canonical(QUALITY)
    pins={'manifest.json':pin,'quotes.ndjson':manifest['quotes'],'schedule.json':manifest['schedule'],
          'source-relations.json':manifest['source_relations'],
          'quality.json':_pin(directory/'quality.json',quality)}
    result={}
    for name in sorted(FILES):
        _compare(queue,'SAVED_FILE_PATH',{'path':str(directory/name)}, {'path':pins[name].get('path')})
        require(pins[name].get('path')==str(directory/name),'BAND_RECONCILIATION_FILE_PIN')
        raw=_read_saved(pins[name],queue)
        info=(directory/name).stat(follow_symlinks=False)
        result[name]={'sha256':sha(raw),'bytes':len(raw),'identity':_signature(info)}
    return result


def verify_publication(request, root, queue):
    """Validate saved bytes/relationships only; no original price-member reader."""
    from .research_reference import _load_reference_values
    pin = request['input_ref']
    _compare(queue,'SAVED_INPUT_ROOT',{'root':str(Path(root)/'reference-inputs'),'filename':'manifest.json'},
             {'path':pin['path'],'filename':Path(pin['path']).name})
    require(Path(pin['path']).is_relative_to(Path(root)/'reference-inputs') and
            Path(pin['path']).name == 'manifest.json', 'BAND_RECONCILIATION_INPUT_ROOT')
    manifest = decode(_read_saved(pin, queue))
    metadata = manifest.get('conversion_metadata', manifest.get('provenance', {}))
    proof = metadata.get('source_native_binding', {})
    config = proof.get('config', {})
    _compare(queue,'ORIGINAL_PRODUCER_SCOPE',
        {'schema':source.SOURCE_SCHEMA,'namespace':request['namespace'],
         'root_identity':request['artifact_root_identity']},
        {'schema':config.get('schema'),'namespace':config.get('namespace'),
         'root_identity':config.get('artifact_root_identity')})
    require(config.get('schema') == source.SOURCE_SCHEMA and config.get('namespace') == request['namespace'] and
            config.get('artifact_root_identity') == request['artifact_root_identity'],
            'BAND_RECONCILIATION_PRODUCER_SCOPE')
    source.current_binding(config, root, historical=True)
    _compare(queue,'ORIGINAL_PROOF_SCOPE_HASH',
             {'scope_sha256':sha(canonical(config))},{'scope_sha256':proof.get('scope_sha256')})
    require(proof.get('scope_sha256') == sha(canonical(config)), 'BAND_RECONCILIATION_ORIGINAL_PROOF')
    if request['namespace'] == 'RETAINED':
        _compare(queue,'ORIGINAL_PRODUCER_COMPATIBILITY',
            {'revision':ORIGINAL_REVISION,'code_hash':ORIGINAL_CODE,'config_hash':ORIGINAL_CONFIG,
             'manifest_hash':ORIGINAL_MANIFEST,'runtime':ORIGINAL_RUNTIME},
            {'revision':config['code_revision'],'code_hash':sha(canonical(config['code'])),
             'config_hash':sha(canonical(config)),'manifest_hash':pin['sha256'],'runtime':config['runtime_image_id']})
        require(config['code_revision'] == ORIGINAL_REVISION and sha(canonical(config['code'])) == ORIGINAL_CODE and
                sha(canonical(config)) == ORIGINAL_CONFIG and pin['sha256'] == ORIGINAL_MANIFEST and
                config['runtime_image_id'] == ORIGINAL_RUNTIME, 'BAND_RECONCILIATION_COMPATIBILITY')
    else:
        require(config['consumer_task'].startswith('qitem-INVENTED') and
                config['candidate_id'].startswith('INVENTED'), 'BAND_RECONCILIATION_NAMESPACE')
    failure = _failure(request, config, proof, queue)
    spec = source.checked_spec(config,read=lambda p:_read_saved(p,queue,limit=32*1024**2))
    expected_spec={'converter':'polar.selected-component-materializer/1','spec':spec,
                   'private_root':str(root),'parent_schedule':spec['schedule'],'symbols':['BIL','VTI'],
                   'dates':spec['date_range']}
    actual_spec={**{k:metadata.get(k) for k in ('converter','spec','private_root','parent_schedule')},
                 'symbols':manifest.get('symbols'),'dates':manifest.get('dates')}
    _compare(queue,'SAVED_SPEC_FIELDS',
        {k:sha(canonical(v)) for k,v in expected_spec.items()},
        {k:sha(canonical(v)) for k,v in actual_spec.items()})
    require(metadata.get('converter') == 'polar.selected-component-materializer/1' and
            metadata.get('spec') == spec and metadata.get('private_root') == str(root) and
            metadata.get('parent_schedule') == spec['schedule'] and
            manifest.get('symbols') == ['BIL', 'VTI'] and manifest.get('dates') == spec['date_range'],
            'BAND_RECONCILIATION_SAVED_SPEC')
    before = _inventory(pin, manifest, queue)
    directory = Path(pin['path']).parent
    for key, name in (('quotes', 'quotes.ndjson'), ('schedule', 'schedule.json'), ('source_relations', 'source-relations.json')):
        _compare(queue,'SAVED_FILE_DECLARATION',
                 {'path':str(directory/name),'sha256':before[name]['sha256'],'bytes':before[name]['bytes']},
                 {k:manifest[key].get(k) for k in ('path','sha256','bytes')})
        require(manifest[key] == {'path': str(directory/name), 'sha256': before[name]['sha256'],
                                 'bytes': before[name]['bytes']}, 'BAND_RECONCILIATION_FILE_PIN')
    quality_raw = read_file(directory, 'quality.json', limit=MAX_BYTES)
    quality = decode(quality_raw)
    _compare(queue,'SAVED_QUALITY',
        {'sha256':sha(canonical(QUALITY)),'bytes':len(canonical(QUALITY)),
         'integrity_scope_hash':sha(canonical(QUALITY['integrity_scope'])),
         'raw_source_status_hash':sha(canonical('POINTER_HASH_BINDING_ONLY_NOT_REOPENED'))},
        {'sha256':sha(quality_raw),'bytes':len(quality_raw),
         'integrity_scope_hash':sha(canonical(metadata.get('integrity_scope'))),
         'raw_source_status_hash':sha(canonical(metadata.get('raw_source_bodies')))})
    require(quality_raw == canonical(quality) and
            before['quality.json']['sha256'] == sha(quality_raw) and
            quality == {'status': 'SELECTED_SOURCE_ONLY', 'excluded_value_decodes': 0,
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
    expected_relations={'rights':rights,'source_purpose':spec['purpose_ref'],
        'source_qualifications':spec['qualification_refs'],
        'eligibility_ledger':{'selected_aliases_fixed_order':['BIL','VTI']}}
    actual_relations={'rights':manifest.get('rights'),**{
        k:relations.get(k) for k in ('source_purpose','source_qualifications','eligibility_ledger')}}
    _compare(queue,'SAVED_RELATION_FIELDS',
        {k:sha(canonical(v)) for k,v in expected_relations.items()},
        {k:sha(canonical(v)) for k,v in actual_relations.items()})
    _compare(queue,'SAVED_SELECTED_RECORDS',
        {'aliases_hash':sha(canonical(['BIL','VTI'])),'all_selected':True},
        {'aliases_hash':sha(canonical(sorted(r['literal_alias'] for r in relations['records']))),
         'all_selected':all(r.get('selected_for_purpose') is True for r in relations['records'])})
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
        _compare(queue,'SAVED_RECORD_BASIS',
            {'symbols_hash':sha(canonical(record['literal_alias'])),'adjustment_hash':sha(canonical('all'))},
            {k+'_hash':sha(canonical(request_basis.get(k))) for k in ('symbols','adjustment')})
        require(request_basis.get('symbols') == record['literal_alias'] and
                request_basis.get('adjustment') == 'all', 'BAND_RECONCILIATION_SAVED_RELATIONS')
    semantic = {'converter': metadata['converter'], 'spec': spec, 'source_native_binding': proof,
                'quotes_sha256': before['quotes.ndjson']['sha256'], 'schedule_sha256': before['schedule.json']['sha256'],
                'relations_sha256': before['source-relations.json']['sha256']}
    revision = 'reference-input-' + sha(canonical(semantic))
    _compare(queue,'SAVED_SEMANTIC_IDENTITY',
        {'directory':revision,'revision':('INVENTED-' if request['namespace']=='INVENTED' else '')+revision},
        {'directory':directory.name,'revision':manifest['parent_dataset_revision']})
    require(directory.name == revision and manifest['parent_dataset_revision'] ==
            ('INVENTED-' if request['namespace'] == 'INVENTED' else '') + revision,
            'BAND_RECONCILIATION_SAVED_IDENTITY')
    after=_inventory(pin, manifest, queue)
    _compare(queue,'SAVED_OBJECT_IDENTITY_UNCHANGED',before,after)
    require(after == before, 'BAND_RECONCILIATION_OBJECT_CHANGED')
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
        audit.expected_claims[request['consumer_task']]={'state':'in-progress'}
        proof = source.task_custody(request, audit)
        audit.expected_claims[request['consumer_task']].update(
            claimedByGeneration=proof['generation'],claim_transition=proof['claim_transition'],
            claimedAt=proof['claimed_at'])
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
                           {'observation.json': raw, 'custody-comparisons.json': canonical(audit.reads),
                            'comparison-operands.json':canonical(audit.comparisons)})
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
                'custody-comparisons.json': canonical(audit.reads),
                'comparison-operands.json':canonical(audit.comparisons)})
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
