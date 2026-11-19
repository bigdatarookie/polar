"""Private native application of one frozen paired monthly reference descriptor."""
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import os
import re

from . import ief_bil_source as source
from .band_source import actual_runtime, task_custody
from .ci_research import require
from .history_bundle import canonical, read_file, sha
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
    require(type(config) is dict and set(config) == FIELDS and config['schema'] == SCHEMA and
            config['question_id'] == source.QUESTION and config['purpose'] == OPERATION and
            config['actor_session'] == QUANT and config['namespace'] in ('RETAINED', 'INVENTED') and
            type(config['consumer_task']) is str and
            re.fullmatch(r'qitem-[A-Za-z0-9_.:-]{1,128}', config['consumer_task']) and
            type(config['artifact_root_identity']) is dict and
            set(config['artifact_root_identity']) == {'path', 'device', 'inode'} and
            type(config['artifact_root_identity']['path']) is str, 'IEF_BIL_DESCRIPTOR_SCOPE')
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
    for task in (config['consumer_task'], OUTCOME, source.TASK):
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
    for path, writable in ((root, True), (source_root, False)):
        mount = by_destination.get(str(path), {})
        require(mount.get('Type') == 'bind' and mount.get('Source') == str(path) and
                mount.get('RW') is writable, 'IEF_BIL_DESCRIPTOR_MOUNTS')
    source_host = source_root.resolve()
    output_host = root.resolve()
    require(not (output_host.is_relative_to(source_host) or source_host.is_relative_to(output_host)) and
            all(not mount['RW'] or destination == str(root)
                for destination, mount in by_destination.items()), 'IEF_BIL_DESCRIPTOR_MOUNTS')


def current_custody(config, queue):
    if config['namespace'] == 'INVENTED':
        return {'status': 'INVENTED_TEST_ONLY'}
    proof = task_custody(config, queue, actors=ACTORS, tags=source.TAGS, dispatcher=LEAD)
    task = queue.read('queue', 'show', config['consumer_task'], '--full')
    parent = queue.read('queue', 'show', OUTCOME, '--full')
    events = queue.read('queue', 'transitions', OUTCOME, '--full')
    finishes = [event for event in events if event.get('state') == 'done']
    finish = max(finishes, key=lambda event: event['transitionId']) if finishes else {}
    require(task.get('handedOffFrom') == OUTCOME and task.get('state') == 'in-progress' and
            task.get('claimedByGeneration') == proof['generation'] and task.get('claimedAt') == proof['claimed_at'] and
            decode(task['body']) == authority(config) and
            parent.get('qitemId') == OUTCOME and parent.get('sourceSession') == QUANT and
            parent.get('destinationSession') == LEAD and parent.get('state') == 'done' and
            parent.get('closureReason') == 'handed_off_to' and parent.get('handedOffTo') == QUANT and
            source.TAGS <= set(parent.get('tags', ())) and finish.get('actorSession') == LEAD and
            finish.get('identityProvenance') == 'transport:v1' and finish['transitionId'] < proof['claim_transition'],
            'IEF_BIL_DESCRIPTOR_NATIVE_AUTHORITY')
    return {**proof, 'authority_task': OUTCOME, 'authority_transition': finish['transitionId']}


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
