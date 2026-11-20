"""Private native application of one frozen paired monthly reference descriptor."""
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import os
import re

from . import ief_bil_source as source
from .band_source import actual_runtime, task_custody
from .ci_research import require
from .history_bundle import canonical, read_file, safe_root, sha
from .history_store import HistoryStore
from .research_reference import _load_reference_values, decode, pinned_bytes

OPERATION = 'research-ief-bil-descriptor'
SCHEMA = 'polar.ief-bil-private-descriptor-config/1'
AUTHORITY = 'polar.ief-bil-private-descriptor-authority/1'
RESULT = 'polar.ief-bil-private-descriptor/1'
RECEIPT = 'polar.ief-bil-private-descriptor-receipt/1'
CHECKPOINT = 'polar.ief-bil-private-descriptor-checkpoint/1'
QUANT = 'quant-a@polar-rig'
LEAD = 'org-lead@engineering-rig'
OUTCOME = 'qitem-20261119225310-1632c5a0'
ORIGINAL_TASK = 'qitem-20261119233853-0875958c'
ORIGINAL_REVISION = '9b6600d9f56d62fc3374827ae687fb2db8f60eb3'
ORIGINAL_CLAIM = 105922
ORIGINAL_CLAIMED_AT = '2026-11-19T23:40:16.529Z'
ORIGINAL_BLOCK = 105926
DEPENDENCY_RELEASE_PREFIX = 'queue-dependency-release/1 '
ORIGINAL_GENERATION = '8db46a4f-1921-4c7e-ba07-75c3161f8ef9'
OUTPUT_CORRECTION = 'qitem-20261119234234-0efa12efd67c1199'
OUTPUT_APPROVAL = 'polar.ief-bil-private-output-correction/1'
OUTPUT_VOLUME = 'polar-ief-bil-descriptor-20261120'
OUTPUT_LABELS = {'polar.resource.project': 'polar', 'polar.resource.task': ORIGINAL_TASK,
                 'polar.resource.owner': QUANT}
ACTORS = {QUANT: ('polar-rig', 'quant.a')}
LOCATOR_SHA = 'cd20a22c5812c108c3cb42ab1da6d55b9ae6094c574b176b50ee1d609890c173'
MANIFEST_SHA = '3f6651f222728c8eb630fbb91b988af3163c4d17c04d889fe73d916f4d3e1291'
QUALIFICATION_SHA = '1941787073534e63b8cef307e5d9fb36a4dbcd4737f7d89fef56cc6c803e96c6'
PRODUCER_REVISION = '504ce4740237141ba96d2e576a8178e03628e78f'
PARENT = 'ief-bil-private-descriptors'
OUTPUT_NAME = 'descriptor-store'
LIMIT = 1024 * 1024
FIELDS = {'schema', 'namespace', 'question_id', 'purpose', 'actor_session', 'consumer_task',
          'protocol_ref', 'locator_ref', 'qualification_ref', 'code', 'code_revision',
          'runtime_image_id', 'artifact_root_identity'}
LIMITS = [
    'SOLE_OWNER_PRIVATE_NONCOMMERCIAL',
    'VENDOR_ALL_ADJUSTED_REFERENCE_UNIT',
    'MODELED_MARKET_CALENDAR_AND_EXPOSED_HISTORY',
    'INDEPENDENT_ACTION_COMPLETENESS_VINTAGE_AND_POINT_IN_TIME_UNESTABLISHED',
    'RETROSPECTIVE_DESCRIPTIVE_SUBSET_OF_ALL_MONTHS',
]


def check_scope(config):
    require(type(config) is dict and set(config) in (FIELDS, FIELDS | {'output_volume'}) and config['schema'] == SCHEMA and
            config['question_id'] == source.QUESTION and config['purpose'] == OPERATION and
            config['actor_session'] == QUANT and config['namespace'] in ('RETAINED', 'INVENTED') and
            type(config['consumer_task']) is str and
            re.fullmatch(r'qitem-[A-Za-z0-9_.:-]{1,128}', config['consumer_task']) and
            type(config['artifact_root_identity']) is dict and
            set(config['artifact_root_identity']) == {'path', 'device', 'inode'} and
            type(config['artifact_root_identity']['path']) is str, 'IEF_BIL_DESCRIPTOR_SCOPE')
    if 'output_volume' in config:
        volume = config['output_volume']
        require(config['namespace'] == 'RETAINED' and config['consumer_task'] == ORIGINAL_TASK and
                config['code_revision'] != ORIGINAL_REVISION and type(volume) is dict and
                set(volume) == {'name', 'created_at'} and volume['name'] == OUTPUT_VOLUME and
                isinstance(volume['created_at'], str) and bool(volume['created_at']),
                'IEF_BIL_DESCRIPTOR_OUTPUT_CORRECTION_SCOPE')
    if config['namespace'] == 'INVENTED':
        require(config['consumer_task'] == 'qitem-INVENTED-IEF-BIL-DESCRIPTOR', 'IEF_BIL_DESCRIPTOR_SCOPE')
    else:
        require(not config['consumer_task'].startswith('qitem-INVENTED') and
                config['protocol_ref']['sha256'] == source.PROTOCOL_SHA and
                config['locator_ref']['sha256'] == LOCATOR_SHA and
                config['qualification_ref']['sha256'] == QUALIFICATION_SHA, 'IEF_BIL_DESCRIPTOR_PINS')


def authority(config):
    return {'schema': AUTHORITY, 'question_id': source.QUESTION, 'purpose': OPERATION,
            'code_revision': config['code_revision'], 'runtime_image_id': config['runtime_image_id'],
            'output_root': config['artifact_root_identity']['path'], 'protocol_sha256': source.PROTOCOL_SHA,
            'locator_sha256': LOCATOR_SHA, 'manifest_sha256': MANIFEST_SHA,
            'qualification_sha256': QUALIFICATION_SHA}


def permitted_read(args, config):
    from .native_selected_input import generation_read

    allowed = [['whoami'], ['seat', 'status', QUANT], list(generation_read(QUANT))]
    tasks = (config['consumer_task'], OUTCOME, source.TASK)
    if 'output_volume' in config:
        tasks += (OUTPUT_CORRECTION,)
    for task in tasks:
        allowed += [['queue', 'show', task, '--full'], ['queue', 'transitions', task, '--full']]
    return args in allowed


def check_container(container, config):
    import subprocess

    raw = subprocess.run(['docker', 'inspect', '--type', 'container', '--format',
                          '{{json .Image}}\n{{json .HostConfig.NetworkMode}}\n{{json .Mounts}}', container],
                         capture_output=True, timeout=15, check=True).stdout
    image, network, mounts = map(decode, raw.splitlines())
    root = Path(config['artifact_root_identity']['path'])
    source_root = root.with_name('store')
    require(image == config['runtime_image_id'] and network == 'none', 'IEF_BIL_DESCRIPTOR_RUNTIME')
    by_destination = {mount['Destination']: mount for mount in mounts}
    source_mount = by_destination.get(str(source_root), {})
    output_mount = by_destination.get(str(root), {})
    require(source_mount.get('Type') == 'bind' and source_mount.get('Source') == str(source_root) and
            source_mount.get('RW') is False and output_mount.get('RW') is True and
            all(not mount['RW'] or destination == str(root)
                for destination, mount in by_destination.items()), 'IEF_BIL_DESCRIPTOR_MOUNTS')
    if 'output_volume' in config:
        raw = subprocess.run(['docker', 'volume', 'inspect', '--format', '{{json .}}', OUTPUT_VOLUME],
                             capture_output=True, timeout=15, check=True).stdout
        check_private_volume(config, output_mount, decode(raw))
        require(not any(safe_root(root).iterdir()), 'IEF_BIL_DESCRIPTOR_ORIGINAL_OUTPUT_EFFECT')
    else:
        source_host, output_host = source_root.resolve(), root.resolve()
        require(output_mount.get('Type') == 'bind' and output_mount.get('Source') == str(root) and
                not (output_host.is_relative_to(source_host) or source_host.is_relative_to(output_host)),
                'IEF_BIL_DESCRIPTOR_MOUNTS')


def check_private_volume(config, mount, volume):
    require(mount.get('Type') == 'volume' and mount.get('Name') == OUTPUT_VOLUME and
            mount.get('Driver') == 'local' and mount.get('Source') == volume.get('Mountpoint') and
            bool(volume.get('Mountpoint')) and volume.get('Name') == OUTPUT_VOLUME and
            volume.get('Driver') == 'local' and volume.get('Scope') == 'local' and
            not volume.get('Options') and volume.get('Labels') == OUTPUT_LABELS and
            volume.get('CreatedAt') == config['output_volume']['created_at'],
            'IEF_BIL_DESCRIPTOR_PRIVATE_VOLUME')


def output_correction_approval(config):
    original = authority({**config, 'code_revision': ORIGINAL_REVISION})
    return {'schema': OUTPUT_APPROVAL, 'status': 'APPROVE_PRIVATE_DESCRIPTOR_VOLUME',
            'consumer_task': ORIGINAL_TASK, 'original_authority_sha256': sha(canonical(original)),
            'original_claim': ORIGINAL_CLAIM, 'original_generation': ORIGINAL_GENERATION,
            'replacement_authority': authority(config), 'output_volume': config['output_volume'],
            'output_root_identity': config['artifact_root_identity'], 'prior_descriptor_effect': 'ABSENT'}


def output_correction_custody(config, proof, queue):
    row = queue.read('queue', 'show', OUTPUT_CORRECTION, '--full')
    events = queue.read('queue', 'transitions', OUTPUT_CORRECTION, '--full')
    closing_id = (row.get('closingTransition') or {}).get('transitionId')
    terminal = next((event for event in events if event['transitionId'] == closing_id), {})
    try:
        resolution = decode(row.get('resolution'))
    except (TypeError, ValueError):
        resolution = None
    require(row.get('qitemId') == OUTPUT_CORRECTION and row.get('sourceSession') == QUANT and
            row.get('destinationSession') == LEAD and row.get('state') == 'done' and
            row.get('closureReason') == 'no-follow-on' and source.TAGS <= set(row.get('tags', ())) and
            terminal.get('qitemId') == OUTPUT_CORRECTION and terminal.get('state') == 'done' and
            terminal.get('closureReason') == 'no-follow-on' and terminal.get('actorSession') == LEAD and
            terminal.get('identityProvenance') == 'transport:v1' and
            resolution == output_correction_approval(config),
            'IEF_BIL_DESCRIPTOR_OUTPUT_CORRECTION_AUTHORITY')
    events = queue.read('queue', 'transitions', ORIGINAL_TASK, '--full')
    return {'output_correction_task': OUTPUT_CORRECTION, 'output_correction_transition': closing_id,
            'dependency_release_transition': verify_output_release(events, proof, closing_id)}


def blocker_wake(event, phase):
    wake = event.get('wake') or {}
    return (wake.get('transitionId') == event.get('transitionId') and wake.get('qitemId') == ORIGINAL_TASK and
            wake.get('phase') == phase and wake.get('kind') == 'blocker' and wake.get('ref') == OUTPUT_CORRECTION)


def system_release_event(event):
    return (event.get('qitemId') == ORIGINAL_TASK and event.get('state') == 'in-progress' and
            event.get('actorSession') == 'queue@system' and
            'identityProvenance' in event and event['identityProvenance'] is None)


def verify_output_release(events, proof, closing_id):
    error = 'IEF_BIL_DESCRIPTOR_OUTPUT_CORRECTION_LINEAGE'
    original = next((event for event in events if event['transitionId'] == ORIGINAL_CLAIM), {})
    blocked = next((event for event in events if event['transitionId'] == ORIGINAL_BLOCK), {})
    after_block = [event for event in events if event['transitionId'] > ORIGINAL_BLOCK]
    require(original.get('qitemId') == blocked.get('qitemId') == ORIGINAL_TASK and
            original.get('state') == 'in-progress' and original.get('transitionNote') == 'claimed' and
            original.get('ts') == proof['claimed_at'] == ORIGINAL_CLAIMED_AT and
            original.get('actorSession') == blocked.get('actorSession') == proof['actor'] == QUANT and
            original.get('identityProvenance') == blocked.get('identityProvenance') == 'transport:v1' and
            blocked.get('state') == 'blocked' and blocker_wake(blocked, 'armed') and
            proof['generation'] == ORIGINAL_GENERATION and proof['claim_transition'] == ORIGINAL_CLAIM and
            bool(after_block), error)
    release, *receipts = after_block
    note = release.get('transitionNote')
    require(system_release_event(release) and type(closing_id) is int and
            ORIGINAL_CLAIM < ORIGINAL_BLOCK < closing_id < release['transitionId'] and
            isinstance(note, str) and len(note) <= 2048 and note.startswith(DEPENDENCY_RELEASE_PREFIX), error)
    try:
        packet = decode(note[len(DEPENDENCY_RELEASE_PREFIX):])
    except ValueError:
        packet = None
    expected = {'version': 1, 'qitemId': ORIGINAL_TASK, 'owner': QUANT, 'generation': ORIGINAL_GENERATION,
                'claimedAt': ORIGINAL_CLAIMED_AT, 'claimTransitionId': ORIGINAL_CLAIM,
                'blockedTransitionId': ORIGINAL_BLOCK, 'blockerId': OUTPUT_CORRECTION,
                'blockerClosingTransitionId': closing_id}
    require(packet == expected and all(type(packet[key]) is type(value) for key, value in expected.items()), error)
    # The daemon can append a delivery receipt without changing the active claim.
    ids = [event['transitionId'] for event in after_block]
    require(ids == sorted(set(ids)) and all(system_release_event(event) and blocker_wake(event, 'fired') and
            not str(event.get('transitionNote', '')).startswith(DEPENDENCY_RELEASE_PREFIX)
            for event in receipts), error)
    return release['transitionId']


def current_custody(config, queue):
    if config['namespace'] == 'INVENTED':
        return {'status': 'INVENTED_TEST_ONLY'}
    proof = task_custody(config, queue, actors=ACTORS, tags=source.TAGS, dispatcher=LEAD)
    task = queue.read('queue', 'show', config['consumer_task'], '--full')
    parent = queue.read('queue', 'show', OUTCOME, '--full')
    events = queue.read('queue', 'transitions', OUTCOME, '--full')
    finishes = [event for event in events if event.get('state') == 'done']
    finish = max(finishes, key=lambda event: event['transitionId']) if finishes else {}
    original_code = ORIGINAL_REVISION if 'output_volume' in config else config['code_revision']
    require(task.get('handedOffFrom') == OUTCOME and task.get('state') == 'in-progress' and
            task.get('claimedByGeneration') == proof['generation'] and task.get('claimedAt') == proof['claimed_at'] and
            decode(task['body']) == authority({**config, 'code_revision': original_code}) and
            parent.get('qitemId') == OUTCOME and parent.get('sourceSession') == QUANT and
            parent.get('destinationSession') == LEAD and parent.get('state') == 'done' and
            parent.get('closureReason') == 'handed_off_to' and parent.get('handedOffTo') == QUANT and
            source.TAGS <= set(parent.get('tags', ())) and finish.get('actorSession') == LEAD and
            finish.get('identityProvenance') == 'transport:v1' and finish['transitionId'] < proof['claim_transition'],
            'IEF_BIL_DESCRIPTOR_NATIVE_AUTHORITY')
    proof = {**proof, 'authority_task': OUTCOME, 'authority_transition': finish['transitionId']}
    if 'output_volume' in config:
        require(task.get('blockedOn') is None, 'IEF_BIL_DESCRIPTOR_OUTPUT_CORRECTION_LINEAGE')
        proof.update(output_correction_custody(config, proof, queue))
    return proof


def exact_month_pairs(days):
    # The full frozen monthly sequence is required even for the invented data.
    months = ['2020-12', *(f'{year}-{month:02d}' for year in range(2021, 2027)
                          for month in range(1, 11 if year == 2026 else 13))]
    require([day[:7] for day in days] == months and days[0] == source.FIRST and
            days[24] == source.PHASE_ANCHOR and days[-1] == source.LAST, 'IEF_BIL_DESCRIPTOR_ENDPOINTS')
    return list(zip(days, days[1:]))


def rational(value):
    # Decimal accepts an integer exactly, including integers larger than the
    # interpreter's default limit for int-to-decimal string conversion.
    return {'numerator': format(Decimal(value.numerator), 'f'),
            'denominator': format(Decimal(value.denominator), 'f')}


def describe(pairs, closes):
    trace = []
    for prior, end in pairs:
        returns = {symbol: closes[end, symbol] / closes[prior, symbol] - 1 for symbol in source.SYMBOLS}
        trace.append((prior, end, returns, returns['IEF'] - returns['BIL']))
    phases = []
    for phase, months in (('2021-2022_DIAGNOSTIC', trace[:24]), ('2023-2026_EXPOSED_DESCRIPTIVE', trace[24:])):
        all_pairs = [spread for _, _, _, spread in months]
        down_pairs = [spread for _, _, returns, spread in months if returns['VTI'] < 0]
        all_mean = sum(all_pairs) / len(all_pairs)
        all_summary = summarize(all_pairs, all_mean)
        if down_pairs:
            down_mean = sum(down_pairs) / len(down_pairs)
            down_summary = summarize(down_pairs, down_mean)
            contrast = rational(down_mean - all_mean)
        else:
            down_summary = {'count': 0, 'status': 'NOT_EVALUABLE'}
            contrast = 'NOT_EVALUABLE'
        phases.append({'phase': phase, 'anchor': months[0][0], 'all_months': all_summary,
                       'vti_down_months': down_summary, 'down_minus_all_mean': contrast})
    audit = [{'prior': prior, 'end': end, 'returns': {key: rational(value) for key, value in returns.items()},
              'ief_minus_bil': rational(spread), 'vti_down': returns['VTI'] < 0}
             for prior, end, returns, spread in trace]
    return phases, audit


def summarize(values, mean):
    return {'count': len(values), 'mean': rational(mean), 'positive': sum(value > 0 for value in values),
            'zero': sum(value == 0 for value in values), 'negative': sum(value < 0 for value in values)}


def readonly_metadata(pin):
    try:
        read_only = os.statvfs(pin['path']).f_flag & os.ST_RDONLY
    except OSError:
        raise ValueError('IEF_BIL_DESCRIPTOR_METADATA_UNAVAILABLE') from None
    require(read_only, 'IEF_BIL_DESCRIPTOR_METADATA_WRITABLE')
    return pinned_bytes(pin)


def input_binding(config, root, queue):
    retained = config['namespace'] == 'RETAINED'
    read = readonly_metadata if retained else pinned_bytes
    read(config['protocol_ref'])
    qualification = decode(read(config['qualification_ref']))
    pin = decode(read(config['locator_ref']))
    if retained:
        require(pin['sha256'] == MANIFEST_SHA and
                qualification['status'] == 'SOURCE_ONLY_SEMANTIC_PREFLIGHT_PASSED' and
                qualification['locator']['observed_sha256'] == LOCATOR_SHA and
                qualification['locator']['manifest_sha256'] == MANIFEST_SHA and
                qualification['runtime_binding']['code_revision'] == PRODUCER_REVISION and
                qualification['runtime_binding']['image_id'] == config['runtime_image_id'],
                'IEF_BIL_DESCRIPTOR_SOURCE_QUALIFICATION')
    else:
        require(qualification == {'status': 'INVENTED_TEST_ONLY'}, 'IEF_BIL_DESCRIPTOR_SOURCE_QUALIFICATION')
    manifest = decode(read(pin))
    metadata, proof, producer, receipt = source.prepared_binding(pin, manifest)
    source_root = Path(producer['artifact_root_identity']['path'])
    require(producer['namespace'] == config['namespace'] and
            producer['protocol_ref'] == config['protocol_ref'] and
            source_root != root and not root.is_relative_to(source_root) and not source_root.is_relative_to(root),
            'IEF_BIL_DESCRIPTOR_SOURCE_BINDING')
    if retained:
        from .ci_research_service import root_identity

        require(source_root == root.with_name('store') and root.name == OUTPUT_NAME and
                producer['code_revision'] == PRODUCER_REVISION and
                producer['runtime_image_id'] == config['runtime_image_id'] and
                producer['artifact_root_identity'] == root_identity(source_root), 'IEF_BIL_DESCRIPTOR_SOURCE_ROOT')
        source.producer_custody(producer, queue, prior=proof, terminal_result=receipt, require_terminal=True)
    else:
        source.authorize(producer, source_root, prior=proof, terminal_result=receipt)
    days = source.prepared_endpoints(pin, manifest, source_root, metadata, proof, producer, read=read)
    return pin, manifest, exact_month_pairs(days)


def existing_effect(directory, binding):
    require(directory.is_dir() and not directory.is_symlink() and
            {path.name for path in directory.iterdir()} == {'checkpoint.json', 'descriptor.json'},
            'IEF_BIL_DESCRIPTOR_INDETERMINATE_EFFECT')
    checkpoint = read_file(directory, 'checkpoint.json', limit=LIMIT)
    saved = decode(checkpoint)
    require(saved['schema'] == CHECKPOINT and saved['binding'] == binding and saved['effect'] == directory.name,
            'IEF_BIL_DESCRIPTOR_EFFECT_CONFLICT')
    result = read_file(directory, 'descriptor.json', limit=LIMIT)
    require(saved['descriptor_sha256'] == sha(result), 'IEF_BIL_DESCRIPTOR_EFFECT_INTEGRITY')
    return checkpoint


def run(config, root, limit, *, queue):
    from .candidate_binding import loaded_revision
    from .ci_research_service import root_identity
    from .gym_service import code_binding

    check_scope(config)
    root = Path(root)
    require(root.is_absolute() and config['artifact_root_identity'] == root_identity(root) and
            config['code_revision'] == loaded_revision() and config['code'] == code_binding(),
            'IEF_BIL_DESCRIPTOR_RUNTIME_BINDING')
    if config['namespace'] == 'RETAINED':
        require(root.name == OUTPUT_NAME and root.stat().st_uid == os.getuid() and
                root.stat().st_mode & 0o077 == 0, 'IEF_BIL_DESCRIPTOR_PRIVATE_ROOT')
    actual_runtime(config)
    custody = current_custody(config, queue)
    pin, manifest, pairs = input_binding(config, root, queue)
    stable = {'question_id': source.QUESTION, 'namespace': config['namespace'],
              'protocol_sha256': config['protocol_ref']['sha256'], 'input_sha256': pin['sha256']}
    effect = 'ief-bil-' + sha(canonical(stable))
    # Use one effect location across transient config or claim changes.
    binding = {**stable, 'scope_sha256': sha(canonical(config)), 'custody': custody, 'code_revision': config['code_revision'],
               'runtime_image_id': config['runtime_image_id'], 'qualification_sha256': config['qualification_ref']['sha256']}
    directory = root / PARENT / effect
    store = HistoryStore(root, limit)
    with store.locked():
        parent = store._directory(PARENT)
        require(not any(parent.glob('.history-partial-*')), 'IEF_BIL_DESCRIPTOR_PARTIAL_EFFECT')
        if directory.exists() or directory.is_symlink():
            checkpoint = existing_effect(directory, binding)
            state = 'RECONCILED_PRIVATE_DESCRIPTOR'
        else:
            # The lock or metadata reads may outlast the original claim.
            require(current_custody(config, queue) == custody, 'IEF_BIL_DESCRIPTOR_CUSTODY_CHANGED')
            closes = {}

            def retain_close(day, symbol, value):
                closes[day, symbol] = Fraction(value)

            _load_reference_values(pin, manifest, source_only=True, consume_exact_close=retain_close)
            phases, trace = describe(pairs, closes)
            result = canonical({'schema': RESULT, 'binding': binding, 'phases': phases,
                                'paired_months': trace, 'limits': LIMITS})
            checkpoint = canonical({'schema': CHECKPOINT, 'binding': binding, 'effect': effect,
                                    'descriptor_sha256': sha(result)})
            require(current_custody(config, queue) == custody, 'IEF_BIL_DESCRIPTOR_CUSTODY_CHANGED')
            store._publish(PARENT, effect, {'descriptor.json': result, 'checkpoint.json': checkpoint}, file_limit=LIMIT)
            state = 'PUBLISHED_PRIVATE_DESCRIPTOR'
        require(current_custody(config, queue) == custody, 'IEF_BIL_DESCRIPTOR_CUSTODY_CHANGED')
    return {'schema': RECEIPT, 'status': state, 'question_id': source.QUESTION, 'effect': effect,
            'checkpoint_ref': {'path': str(directory / 'checkpoint.json'), 'sha256': sha(checkpoint),
                               'bytes': len(checkpoint)}, 'strategy_execution': 'NOT_RUN'}
