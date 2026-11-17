"""Selected-only retained input within the existing offline preparation path.

The native admission is the Quant's source semantic decision, not an additional
Operator execution grant. No values are opened until current custody, loaded
build, exact graph and private namespace agree. Mixed parent quote files and
excluded normalized spans are never decoded.
"""
import json
from pathlib import Path
import platform
import re
import os

from .ci_research import require
from .history_bundle import canonical, sha
from .history_store import HistoryStore
from .research_reference import decode, pinned_bytes, reference_schedule, MAX_BYTES
from .reference_input import validate_source, microprice
from .research_native_review import current_queue
from .scheduled_drawdown import SEMANTIC_CANDIDATE

SCHEMA = 'polar.reference-input-conversion-config/7'
PROFILE = 'QUANT-A-DRAWDOWN-SELECTED-INPUT-V1'
CONVERTER = 'polar.native-selected-input/1'
RIGHTS = 'SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION'


def scope(config):
    return {k: v for k, v in config.items() if k != 'source_admission_ref'}


def generation_read(actor):
    require(actor == 'quant-a@polar-rig', 'NATIVE_SELECTED_ACTOR')
    return ('ps', '--nodes', '--rig', 'polar-rig', '--session', actor, '--fields',
            'rigName,logicalId,canonicalSessionName,sessionStatus,agentActivity')


def live_generation(queue, actor):
    """Use the daemon's current generation-qualified owner projection.

    The shipped projection resolves a fresh native owner binding, or compares a
    hook generation to the current occupant tenure at read time. Resolved-but-
    stale mismatch, unresolved ownership and legacy fallback never qualify.
    No activity-state inference, claim mutation or caller generation is used.
    """
    snapshot = queue.read(*generation_read(actor))
    rows = snapshot.get('entries') if isinstance(snapshot, dict) else snapshot
    require(isinstance(rows, list) and len(rows) == 1, 'NATIVE_SELECTED_CURRENT_GENERATION')
    row = rows[0]; activity = row.get('agentActivity', {})
    require(row.get('rigName') == 'polar-rig' and row.get('logicalId') == 'quant.a' and
            row.get('canonicalSessionName') == actor and row.get('sessionStatus') == 'running' and
            activity.get('generationProvenance') == 'resolved' and
            activity.get('evidenceSource') in ('native_owner', 'runtime_hook') and
            activity.get('stale') is not True and activity.get('fallback') is not True and
            isinstance(activity.get('generation'), str) and bool(activity['generation']),
            'NATIVE_SELECTED_CURRENT_GENERATION')
    return activity['generation']


def consumer_custody(consumer_task, *, queue=None):
    """Metadata-only current consumer proof; it grants no source admission."""
    require(isinstance(consumer_task, str) and
            re.fullmatch(r'qitem-[A-Za-z0-9_.:-]+', consumer_task), 'NATIVE_SELECTED_CURRENT_TASK')
    queue = queue or current_queue()
    identity = queue.read('whoami').get('identity', {})
    actor = identity.get('sessionName')
    require(identity.get('logicalId') == 'quant.a' and identity.get('rigName') == 'polar-rig' and
            bool(identity.get('nodeId')), 'NATIVE_SELECTED_ACTOR')
    task = queue.read('queue', 'show', consumer_task, '--full')
    seat = queue.read('seat', 'status', actor)
    require(task.get('qitemId') == consumer_task and task.get('state') == 'in-progress' and
            task.get('destinationSession') == actor and task.get('claimedByGeneration') and
            seat.get('current_occupant') == actor and seat.get('logical_id') == 'quant.a' and
            seat.get('rig_name') == 'polar-rig', 'NATIVE_SELECTED_CURRENT_TASK')
    generation = live_generation(queue, actor)
    require(task['claimedByGeneration'] == generation, 'NATIVE_SELECTED_CURRENT_GENERATION')
    journal = queue.read('queue', 'transitions', consumer_task, '--full')
    claims = [x for x in journal if x.get('state') == 'in-progress' and x.get('transitionNote') == 'claimed']
    require(bool(claims), 'NATIVE_SELECTED_CLAIM')
    claim = max(claims, key=lambda x: x['transitionId'])
    require(claim.get('actorSession') == actor and claim.get('identityProvenance') == 'transport:v1',
            'NATIVE_SELECTED_CLAIM')
    return actor, generation, task


def context_probe(consumer_task, *, queue=None):
    queue = queue or current_queue()
    actor, generation, task = consumer_custody(consumer_task, queue=queue)
    current = queue.read('queue', 'show', consumer_task, '--full')
    require(all(current.get(k) == task.get(k) for k in
                ('state', 'destinationSession', 'claimedByGeneration', 'claimedAt')) and
            live_generation(queue, actor) == generation, 'NATIVE_SELECTED_CUSTODY_CHANGED')
    return {'status': 'CURRENT_NATIVE_CONSUMER_CUSTODY_VERIFIED', 'actor': actor,
            'consumer_task': consumer_task, 'generation': generation,
            'source_admission': 'NOT_ISSUED_BY_PROBE', 'protected_value_reads': 0}


def authorize(config, root, *, queue=None):
    fields = {'schema', 'profile_id', 'namespace', 'semantic_candidate', 'code_revision', 'code',
              'runtime_image_id', 'consumer_task', 'source_admission_ref', 'artifact_root_identity',
              'purpose_ref', 'purpose_fit_ref', 'protocol_ref', 'vti_binding_ref', 'vti_parent_ref',
              'bil_input_ref', 'operation'}
    require(type(config) is dict and set(config) == fields and config['schema'] == SCHEMA and
            config['profile_id'] == PROFILE and config['namespace'] in ('INVENTED', 'RETAINED') and
            config['semantic_candidate'] == SEMANTIC_CANDIDATE and
            config['operation'] == 'SELECTED_INPUT_PREPARE_AND_READ', 'NATIVE_SELECTED_CONFIG')
    from .ci_research_service import root_identity
    require(Path(root).is_absolute() and Path(root).resolve() == Path(root) and
            config['artifact_root_identity'] == root_identity(Path(root)), 'NATIVE_SELECTED_NAMESPACE')
    from .gym_service import code_binding
    require(config['code'] == code_binding(), 'NATIVE_SELECTED_CODE_BINDING')
    if config['namespace'] == 'RETAINED':
        from .candidate_binding import loaded_revision
        require(config['code_revision'] == loaded_revision(), 'NATIVE_SELECTED_CANDIDATE')
        require(platform.system() == 'Linux' and platform.python_version() == '3.13.18' and
                os.environ.get('POLAR_RUNTIME_IMAGE_ID') == config['runtime_image_id'] and
                re.fullmatch('sha256:[a-f0-9]{64}', config['runtime_image_id']) is not None,
                'NATIVE_SELECTED_RUNTIME')
    # This happens before even a caller-selected metadata pin is opened.
    queue = queue or current_queue()
    actor, generation, task = consumer_custody(config['consumer_task'], queue=queue)
    ref = config['source_admission_ref']
    require(type(ref) is str and re.fullmatch(r'qitem-[A-Za-z0-9_.:-]+#[1-9][0-9]*', ref),
            'NATIVE_SELECTED_SOURCE_ADMISSION_REQUIRED')
    qid, transition = ref.rsplit('#', 1); transition = int(transition)
    row = queue.read('queue', 'show', qid, '--full')
    events = queue.read('queue', 'transitions', qid, '--full')
    closing = [x for x in events if x.get('transitionId') == transition]
    require(row.get('state') == 'done' and row.get('destinationSession') == actor and
            row.get('claimedByGeneration') == generation and
            row.get('closingTransition', {}).get('transitionId') == transition and len(closing) == 1 and
            closing[0].get('state') == 'done' and closing[0].get('actorSession') == actor and
            closing[0].get('identityProvenance') == 'transport:v1', 'NATIVE_SELECTED_SOURCE_ADMISSION')
    try:
        decision = decode(row['resolution'])
    except (ValueError, TypeError, KeyError):
        require(False, 'NATIVE_SELECTED_SOURCE_ADMISSION_BINDING')
    require(decision == {'schema': 'polar.native-selected-source-admission/1',
            'status': 'ADMITTED_WITH_LIMITS', 'consumer_task': config['consumer_task'],
            'claimed_generation': generation, 'scope_sha256': sha(canonical(scope(config))),
            'symbols': ['BIL', 'VTI'], 'scientific_verdict': 'NOT_REVIEWED'},
            'NATIVE_SELECTED_SOURCE_ADMISSION_BINDING')
    # Reject concurrent reassign/reopen and stale cached source decisions.
    for q, original in [(config['consumer_task'], task), (qid, row)]:
        current = queue.read('queue', 'show', q, '--full')
        require(all(current.get(k) == original.get(k) for k in
                    ('state', 'destinationSession', 'claimedByGeneration', 'claimedAt',
                     'closingTransition', 'resolution')), 'NATIVE_SELECTED_CUSTODY_CHANGED')
    require(live_generation(queue, actor) == generation, 'NATIVE_SELECTED_CUSTODY_CHANGED')
    return {'actor': actor, 'generation': generation, 'source_admission_ref': ref,
            'scope_sha256': sha(canonical(scope(config)))}


def prepared_authorization(manifest):
    provenance = manifest.get('conversion_metadata', manifest.get('provenance', {}))
    if provenance.get('converter') == CONVERTER:
        config = provenance['config']
        # This exact namespace is part of the native semantic decision. An
        # arbitrary relocated copy must not turn into a new readable root.
        from .ci_research_service import root_identity
        root = Path(provenance['private_root'])
        authorize(config, root)
        require(config['artifact_root_identity'] == root_identity(root) and
                Path(manifest['quotes']['path']).is_relative_to(root/'reference-inputs'),
                'NATIVE_SELECTED_NAMESPACE')


def scheduled_authorization(config, manifest, root):
    """Mandatory retained profile14 boundary for every Service/CLI entry.

    The optional converter hook in the legacy reader cannot enforce a new
    profile's source contract. Check it before FIRST_START, independent of the
    native stdio wrapper, and bind the preparation to this actual author build.
    """
    provenance = manifest.get('provenance', {})
    require(type(provenance) is dict and provenance.get('converter') == CONVERTER and
            type(provenance.get('config')) is dict and manifest.get('symbols') == ['BIL', 'VTI'],
            'NATIVE_SELECTED_PROFILE_INPUT_REQUIRED')
    source = provenance['config']
    require(source.get('namespace') == 'RETAINED' and
            source.get('code_revision') == config['code_revision'] and
            source.get('code') == config['code'] and
            source.get('runtime_image_id') == config['runtime_image_id'] and
            source.get('artifact_root_identity') == config['artifact_root_identity'] and
            source.get('protocol_ref') == config['protocol_ref'] and
            provenance.get('private_root') == str(root), 'NATIVE_SELECTED_AUTHOR_BINDING')
    authorize(source, root)
    for key in ('quotes', 'schedule', 'source_relations'):
        require(Path(manifest[key]['path']).is_relative_to(Path(root)/'reference-inputs'),
                'NATIVE_SELECTED_NAMESPACE')


def _merge(target, source):
    for k, v in source.items():
        require(k not in target or target[k] == v, 'NATIVE_SELECTED_RELATION_CONFLICT')
        target[k] = v


def prepare_selected(config, root, limit, *, queue=None):
    proof = authorize(config, root, queue=queue)
    # The exact purpose/protocol/graph pins were bound by the native decision.
    for key in ('purpose_ref', 'purpose_fit_ref', 'protocol_ref'):
        require(type(decode(pinned_bytes(config[key]))) is dict, 'NATIVE_SELECTED_PURPOSE')
    bil = decode(pinned_bytes(config['bil_input_ref']))
    parent = decode(pinned_bytes(config['vti_parent_ref']))
    binding = decode(pinned_bytes(config['vti_binding_ref']))
    rights = 'INVENTED_PUBLIC_TEST' if config['namespace'] == 'INVENTED' else RIGHTS
    require(bil.get('schema') == parent.get('schema') == 'polar.synthetic-reference-source-input/2' and
            bil['symbols'] == ['BIL'] and 'VTI' in parent['symbols'] and
            bil['rights'] == parent['rights'] == binding['rights'] == rights,
            'NATIVE_SELECTED_SOURCE_GRAPH')
    if config['namespace'] == 'INVENTED':
        positive = {'kind': 'DETERMINISTIC_INVENTED_FIXTURE', 'producer': 'polar-public-tests', 'source_payloads': 'NONE'}
        require(bil.get('provenance') == parent.get('provenance') == positive and
                str(bil['parent_dataset_revision']).startswith('INVENTED-') and
                str(parent['parent_dataset_revision']).startswith('INVENTED-'), 'NATIVE_SELECTED_INVENTED')
    require(binding.get('schema') == 'polar.selected-source-consumer-metadata-binding/1',
            'NATIVE_SELECTED_BINDING')
    records = [r for r in binding['records'] if r.get('literal_alias') == 'VTI']
    require(len(records) == 1 and records[0]['selected_for_purpose'] is True and
            records[0]['request']['symbols'] == 'VTI', 'NATIVE_SELECTED_VTI_RECORD')
    record = records[0]
    # Read schedule/relation metadata, never the mixed parent quotes pin.
    schedule_raw = pinned_bytes(bil['schedule'])
    require(schedule_raw == pinned_bytes(parent['schedule']), 'NATIVE_SELECTED_SCHEDULE')
    schedule, days = reference_schedule(decode(schedule_raw))
    relations_bil = decode(pinned_bytes(bil['source_relations']))
    relations_vti = decode(pinned_bytes(parent['source_relations']))
    require(record in relations_vti['records'], 'NATIVE_SELECTED_PARENT_RECORD')
    collection = decode(pinned_bytes(binding['source_collection']))
    require(collection['schema'] == 'polar.vendor-all-adjusted-source-collection/1' and
            collection['source_plan_id'] == binding['source_plan_id'], 'NATIVE_SELECTED_COLLECTION')
    source_root = Path(binding['source_collection']['path']).parent
    jobs = {}; parents = {}; members = {}; selected = {}; all_records = []
    for relations, symbol in [(relations_bil, 'BIL'), (relations_vti, 'VTI')]:
        chosen = [r for r in relations['records'] if r['literal_alias'] == symbol]
        require(len(chosen) == 1, 'NATIVE_SELECTED_RELATIONS')
        r = chosen[0]; all_records.append(r)
        job = relations['jobs'][r['canonical_job_id']]
        _merge(jobs, {r['canonical_job_id']: job})
        h = job['parent_relation_sha256']; _merge(parents, {h: relations['parent_relations'][h]})
    # Leaf-only BIL grid is safe to decode; never use BIL/SHY composition.
    raw_bil = pinned_bytes(bil['quotes'])
    require(len(raw_bil.splitlines()) == len(days), 'NATIVE_SELECTED_BIL_GRID')
    for line in raw_bil.splitlines(keepends=True):
        value = decode(line)
        require(value['symbol'] == 'BIL', 'NATIVE_SELECTED_BIL_SYMBOL')
        key = (value['date'], 'BIL'); require(key not in selected, 'NATIVE_SELECTED_DUPLICATE')
        selected[key] = line
    for pin in bil['source_members']:
        members[pin['sha256']] = pin
    offset = 0
    for segment in record['segments']:
        pp = Path(segment['partition_manifest']); mp = Path(segment['normalized_member'])
        require(pp.is_relative_to(source_root) and mp.is_relative_to(source_root) and
                pp.parent == mp.parent and mp.name == 'bars.ndjson', 'NATIVE_SELECTED_MEMBER_PATH')
        for path, digest in [(pp, segment['partition_manifest_sha256']), (mp, segment['normalized_member_sha256'])]:
            require(collection['objects'][str(path.relative_to(source_root))]['sha256'] == digest,
                    'NATIVE_SELECTED_MEMBER_GRAPH')
        part = decode(pinned_bytes({'path': str(pp), 'sha256': segment['partition_manifest_sha256']}))
        require(part['schema'] == 'polar.vendor-all-adjusted-source-content/1' and
                part['source_plan_id'] == binding['source_plan_id'] and
                part['objects']['bars.ndjson']['sha256'] == segment['normalized_member_sha256'],
                'NATIVE_SELECTED_PARTITION')
        pin = {'path': str(mp), 'sha256': segment['normalized_member_sha256']}
        lines = pinned_bytes(pin).splitlines(keepends=True)
        start, count = segment['member_first_line_1based']-1, segment['rows']
        require(type(start) is int and type(count) is int and start >= 0 and count > 0 and
                start+count <= len(lines) and segment['first_job_row_0based'] == offset,
                'NATIVE_SELECTED_SEGMENT')
        members[pin['sha256']] = pin
        # Only selected spans enter the JSON decoder. Excluded bytes may be
        # hashed as part of a member; that is not full-parent semantic validation.
        for index in range(start, start+count):
            line = lines[index]; value = decode(line)
            require(line.endswith(b'\n') and value['query_symbol'] == value['source_symbol'] == 'VTI' and
                    value['reference_date'] in days and value['adjustment'] == 'all' and
                    value['source_reference']['job_id'] == record['canonical_job_id'],
                    'NATIVE_SELECTED_ROW')
            token = value['source_fields_exact_tokens']['c']
            require(value['vendor_adjusted_close'] == token, 'NATIVE_SELECTED_TOKEN')
            price = microprice(token)
            parent_hash = sha(canonical(value['parent_relation']))
            require(parent_hash == jobs[record['canonical_job_id']]['parent_relation_sha256'],
                    'NATIVE_SELECTED_PARENT')
            original = value['source_reference']
            require(part['objects'][original['raw_file']]['sha256'] == original['source_body_sha256'],
                    'NATIVE_SELECTED_RAW_POINTER')
            projected = {'symbol': 'VTI', 'date': value['reference_date'],
                'reference_quote': f'{price//1000000}.{price%1000000:06d}',
                'source_adjusted_close_token': token,
                'source_ref': {'normalized_member_sha256': pin['sha256'], 'line_1based': index+1,
                    'line_sha256': sha(line), 'original_source_reference': original,
                    'query_symbol': 'VTI', 'source_symbol': 'VTI', 'parent_relation_sha256': parent_hash},
                'observed_published_at': value['observed_published_at'],
                'observed_historical_available_at': value['observed_historical_available_at']}
            key = (projected['date'], 'VTI'); require(key not in selected, 'NATIVE_SELECTED_DUPLICATE')
            selected[key] = canonical(projected)+b'\n'
        offset += count
    require(offset == len(days) and set(selected) == {(d, s) for d in days for s in ['BIL', 'VTI']},
            'NATIVE_SELECTED_GRID')
    relations = {'schema': 'polar.reference-source-relations/1', 'records': all_records,
                 'jobs': jobs, 'parent_relations': parents, 'source_coverage_records': [],
                 'eligibility_ledger': {'selected_aliases_fixed_order': ['BIL', 'VTI']},
                 'source_purpose': config['purpose_ref']}
    fields = {'symbol', 'date', 'reference_quote', 'source_adjusted_close_token', 'source_ref',
              'observed_published_at', 'observed_historical_available_at'}
    for (day, symbol), line in selected.items():
        value = decode(line)
        require(set(value) == fields and day in days and value['symbol'] == symbol and
                microprice(value['reference_quote']) == microprice(value['source_adjusted_close_token']),
                'NATIVE_SELECTED_QUOTE')
        validate_source(value, set(members), relations)
    raw = b''.join(selected[d, s] for d in days for s in ['BIL', 'VTI'])
    require(len(raw) <= MAX_BYTES, 'NATIVE_SELECTED_BYTES')
    provenance = {'converter': CONVERTER, 'config': config, 'private_root': str(root),
                  'native_source_binding': proof, 'parent_schedule': bil['schedule'],
                  'integrity_scope': 'SELECTED_MEMBERS_HASHED_SELECTED_ROWS_VALIDATED_EXCLUDED_PARENT_QUOTES_UNINSPECTED',
                  'raw_source_bodies': 'POINTER_HASH_BINDING_ONLY_NOT_REOPENED'}
    revision = 'reference-input-'+sha(canonical({'config': config, 'quotes_sha256': sha(raw)}))
    destination = Path(root)/'reference-inputs'/revision
    pin = lambda name, data: {'path': str(destination/name), 'sha256': sha(data), 'bytes': len(data)}
    relraw = canonical(relations)
    manifest = {'schema': 'polar.synthetic-reference-source-input/2',
        'quote_basis': 'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE', 'unit_type': 'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
        'double_action_policy': 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
        'symbols': ['BIL', 'VTI'], 'dates': bil['dates'], 'rows': len(selected),
        'rights': rights, 'parent_dataset_revision': ('INVENTED-' if config['namespace'] == 'INVENTED' else '')+
            'selected-'+sha(canonical([config['bil_input_ref'], config['vti_parent_ref'], config['vti_binding_ref']])),
        'quotes': pin('quotes.ndjson', raw), 'schedule': pin('schedule.json', schedule_raw),
        'source_relations': pin('source-relations.json', relraw),
        'source_members': list(members.values()), 'provenance': provenance}
    if config['namespace'] == 'INVENTED':
        manifest['conversion_metadata'] = provenance
        manifest['provenance'] = positive
    # Recheck current native custody before publishing any prepared values.
    require(authorize(config, root, queue=queue) == proof, 'NATIVE_SELECTED_CUSTODY_CHANGED')
    files = {'manifest.json': canonical(manifest), 'quotes.ndjson': raw,
             'schedule.json': schedule_raw, 'source-relations.json': relraw}
    store = HistoryStore(root, limit)
    with store.locked():
        store._publish('reference-inputs', revision, files, file_limit=MAX_BYTES)
    return {'schema': 'polar.reference-input-preparation/1', 'status': 'PREPARED_SOURCE_ONLY',
            'revision': revision, 'input_ref': pin('manifest.json', files['manifest.json']),
            'symbols': 2, 'rows': len(selected), 'scientific_fitness': 'NOT_ASSESSED', 'strategy_execution': 'NOT_RUN'}
