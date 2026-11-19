"""Invented exact prices and a closed synthetic native invocation."""
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

import pytest

from polar import ief_bil_descriptor as descriptor, ief_bil_source as source, native_selected_tool as native
from polar.ci_research_service import root_identity
from polar.gym_service import code_binding
from polar.history_bundle import canonical, sha
from polar.reference_input import preflight_input, project_schedule
from polar.research_reference import decode, load_reference, pinned_bytes
from polar.selected_component_input import CONVERTER, SCHEMA
from test_reference_input import put


def position_days():
    months = [(2020, 12)] + [(year, month) for year in range(2021, 2027)
                             for month in range(1, 11 if year == 2026 else 13)]
    days = []
    for year, month in months:
        day = date(year, month, monthrange(year, month)[1])
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        days.append(day.isoformat())
    return days


def synthetic_config(directory, revision, image, *, mutate_quotes=None):
    directory = directory.resolve()
    directory.mkdir(exist_ok=True)
    src, root = directory / 'source', directory / 'output'
    src.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    protocol = put(directory / 'protocol.md', b'Invented review-only protocol')
    fit = put(directory / 'fit.json', {'status': 'INVENTED'})
    dates = position_days()
    calendar_days = [*dates, '2026-11-02']
    calendar = {'schema': 'polar.xnys-reference-schedule/1', 'rows': [
        {'date': day, 'reference_open_utc': day + 'T14:30:00+00:00', 'reference_close_utc': day + 'T21:00:00+00:00',
         'next_reference_date': next_day, 'month_end_in_reference_range': bool(next_day)}
        for day, next_day in zip(calendar_days, [*calendar_days[1:], None])
    ]}
    calendar_pin = put(directory / 'calendar.json', calendar)
    producer = {'schema': source.SOURCE_SCHEMA, 'namespace': 'INVENTED', 'question_id': source.QUESTION,
                'purpose': source.PURPOSE_SCHEMA, 'actor_session': source.PRODUCER,
                'consumer_task': 'qitem-INVENTED-IEF-BIL', 'artifact_root_identity': root_identity(src),
                'code': code_binding(), 'code_revision': revision, 'runtime_image_id': image, 'protocol_ref': protocol,
                'source_fit_ref': fit}
    spec = {'schema': SCHEMA, 'namespace': 'INVENTED', 'schedule': calendar_pin, 'qualification_refs': [fit],
            'date_range': {'start': dates[0], 'end': dates[-1], 'count': len(dates)},
            'leaf_inputs': [{'symbol': 'BIL', 'input_ref': fit}],
            'normalized_inputs': [{'symbol': symbol, 'input_ref': fit, 'binding_ref': fit}
                                  for symbol in ('IEF', 'VTI')]}
    spec['purpose_ref'] = put(directory / 'purpose.json', source.purpose_metadata(producer, spec))
    producer['spec_ref'] = put(directory / 'spec.json', spec)
    proof = {'config': producer, 'status': 'INVENTED_TEST_ONLY', 'scope_sha256': sha(canonical(producer))}
    jobs, parents, bindings = {}, {}, {}
    member_hash = 'c' * 64
    for symbol in source.SYMBOLS:
        parent = {'job_id': f'plan-{symbol}', 'source_record_ids': []}
        digest = sha(canonical(parent))
        parents[digest] = parent
        jobs[symbol] = {'parent_relation_sha256': digest, 'request': {'symbols': symbol},
                        'source_plan_job_id': parent['job_id'], 'source_record_ids': []}
        bindings[symbol] = {'query_symbol': symbol, 'source_symbol': symbol, 'parent_relation_sha256': digest,
                            'normalized_member_sha256': member_hash, 'line_1based': 1, 'line_sha256': 'd' * 64,
                            'original_source_reference': {'raw_file': 'objects/invented.json',
                                'source_body_sha256': 'e' * 64, 'source_array': 'bars/' + symbol,
                                'source_row_ordinal': 0, 'job_id': symbol, 'request_id': None, 'page': 0}}
    relations = canonical({'schema': 'polar.reference-source-relations/1', 'jobs': jobs, 'parent_relations': parents})
    token_sets = ((3, 3, 3), (3, 4, 3), (4, 3, 2), (5, 9, 3))
    rows = []
    for index, day in enumerate(dates):
        for symbol, digits in zip(source.SYMBOLS, token_sets[min(index, 3)]):
            token = f'0.000000{digits}'
            rows.append({'symbol': symbol, 'date': day, 'reference_quote': token, 'source_adjusted_close_token': token,
                         'source_ref': bindings[symbol], 'observed_published_at': None,
                         'observed_historical_available_at': None})
    if mutate_quotes:
        mutate_quotes(rows)
    quotes = b''.join(canonical(row) + b'\n' for row in rows)
    schedule = canonical(project_schedule(calendar, spec['date_range'], endpoints=dates))
    semantic = {'converter': CONVERTER, 'spec': spec, 'source_native_binding': proof,
                'quotes_sha256': sha(quotes), 'schedule_sha256': sha(schedule), 'relations_sha256': sha(relations)}
    name = 'reference-input-' + sha(canonical(semantic))
    published = src / 'reference-inputs' / name
    manifest = {'schema': source.MANIFEST_SCHEMA, 'symbols': source.SYMBOLS, 'rows': 213, 'dates': spec['date_range'],
                'quote_basis': 'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE', 'rights': 'INVENTED_PUBLIC_TEST',
                'unit_type': 'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE',
                'double_action_policy': 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL',
                'parent_dataset_revision': 'INVENTED-' + name, 'source_members': [{'sha256': member_hash}],
                'quotes': put(published / 'quotes.ndjson', quotes), 'schedule': put(published / 'schedule.json', schedule),
                'source_relations': put(published / 'source-relations.json', relations),
                'conversion_metadata': {'converter': CONVERTER, 'spec': spec, 'private_root': str(src),
                                        'source_native_binding': proof, 'parent_schedule': calendar_pin}}
    pin = put(published / 'manifest.json', manifest)
    config = {'schema': descriptor.SCHEMA, 'namespace': 'INVENTED', 'question_id': source.QUESTION,
              'purpose': descriptor.OPERATION, 'actor_session': descriptor.QUANT,
              'consumer_task': 'qitem-INVENTED-IEF-BIL-DESCRIPTOR', 'protocol_ref': protocol,
              'locator_ref': put(directory / 'locator.json', pin),
              'qualification_ref': put(directory / 'qualification.json', {'status': 'INVENTED_TEST_ONLY'}),
              'code': code_binding(), 'code_revision': revision, 'runtime_image_id': image,
              'artifact_root_identity': root_identity(root)}
    return root, config, pin


@pytest.fixture
def invented_runtime(monkeypatch):
    from polar import candidate_binding

    revision = 'a' * 40
    image = 'sha256:' + 'b' * 64
    monkeypatch.setattr(candidate_binding, 'loaded_revision', lambda: revision)
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID', image)
    return revision, image


def test_native_operation_uses_exact_and_private_values_then_reconciles(tmp_path, invented_runtime, monkeypatch):
    root, config, pin = synthetic_config(tmp_path, *invented_runtime)
    monkeypatch.setenv('POLAR_ARTIFACT_ROOT', str(root))
    monkeypatch.setenv('POLAR_STORAGE_BYTES', str(10**8))
    safe = native.consume(descriptor.OPERATION, config, native.source_identity())
    assert set(safe) == {'schema', 'status', 'question_id', 'effect', 'checkpoint_ref', 'strategy_execution'}
    assert safe['status'] == 'PUBLISHED_PRIVATE_DESCRIPTOR'
    checkpoint = decode(pinned_bytes(safe['checkpoint_ref']))
    result_path = Path(safe['checkpoint_ref']['path']).with_name('descriptor.json')
    result = decode(pinned_bytes({'path': str(result_path), 'sha256': checkpoint['descriptor_sha256']}))
    diagnostic, evaluation = result['phases']
    assert diagnostic['all_months'] == {'count': 24, 'positive': 2, 'zero': 21, 'negative': 1,
                                       'mean': {'numerator': '1', 'denominator': '16'}}
    assert diagnostic['vti_down_months']['mean'] == {'numerator': '-7', 'denominator': '12'}
    assert diagnostic['vti_down_months']['count'] == 1
    assert diagnostic['down_minus_all_mean'] == {'numerator': '-31', 'denominator': '48'}
    assert evaluation['all_months']['count'] == evaluation['all_months']['zero'] == 46
    assert evaluation['vti_down_months'] == {'count': 0, 'status': 'NOT_EVALUABLE'}
    assert evaluation['down_minus_all_mean'] == 'NOT_EVALUABLE'
    assert len(result['paired_months']) == 70 and not result['paired_months'][0]['vti_down']
    assert result_path.stat().st_mode & 0o777 == 0o400
    assert preflight_input(pin, root=Path(pin['path']).parents[2])['dates'] == 71
    with pytest.raises(ValueError, match='IEF_BIL_SOURCE_ONLY'):
        load_reference(pin)
    monkeypatch.setattr(descriptor, '_load_reference_values', lambda *a, **k: pytest.fail('duplicate source read'))
    retry = native.consume(descriptor.OPERATION, config, native.source_identity())
    assert retry['status'] == 'RECONCILED_PRIVATE_DESCRIPTOR'
    assert retry['checkpoint_ref'] == safe['checkpoint_ref']


@pytest.mark.parametrize('change', [lambda days: days.pop(0), lambda days: days.pop(24),
                                    lambda days: days.insert(24, days[24]), lambda days: days.pop(40)])
def test_absent_or_duplicate_endpoint_or_anchor_fails(change):
    dates = position_days()
    change(dates)
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_ENDPOINTS'):
        descriptor.exact_month_pairs(dates)


@pytest.mark.parametrize('mutate,error', [(lambda rows: rows.__setitem__(1, rows[0]), 'REFERENCE_ROW_IDENTITY_ORDER'),
                                         (lambda rows: rows.pop(), 'REFERENCE_ROW_COUNT'),
                                         (lambda rows: rows[0].update(source_adjusted_close_token='0.1'), 'REFERENCE_SCALE_CHANGED')])
def test_malformed_immutable_grid_cannot_publish(tmp_path, invented_runtime, mutate, error):
    root, config, _ = synthetic_config(tmp_path, *invented_runtime, mutate_quotes=mutate)
    with pytest.raises(ValueError, match=error):
        descriptor.run(config, root, 10**8, queue=None)
    assert not list((root / descriptor.PARENT).iterdir())


def test_invalid_binding_and_partial_effect_fail_before_quotes(tmp_path, invented_runtime, monkeypatch):
    root, config, _ = synthetic_config(tmp_path, *invented_runtime)
    monkeypatch.setattr(descriptor, '_load_reference_values', lambda *a, **k: pytest.fail('unexpected quote read'))
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_SCOPE'):
        descriptor.run({**config, 'purpose': 'OTHER'}, root, 10**8, queue=None)
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_RUNTIME_BINDING'):
        descriptor.run({**config, 'code_revision': 'c' * 40}, root, 10**8, queue=None)
    (root / descriptor.PARENT / '.history-partial-preserve').mkdir(parents=True)
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_PARTIAL_EFFECT'):
        descriptor.run(config, root, 10**8, queue=None)
    assert (root / descriptor.PARENT / '.history-partial-preserve').is_dir()


def test_retained_authority_requires_exact_current_quant_claim_and_lead_handoff(tmp_path):
    from copy import deepcopy
    from test_band_source import Queue

    queue = Queue()
    queue.actor = descriptor.QUANT
    task_id = 'qitem-quant-a-current-descriptor'
    config = {'namespace': 'RETAINED', 'consumer_task': task_id, 'actor_session': descriptor.QUANT,
              'code_revision': 'a' * 40, 'runtime_image_id': 'sha256:' + 'b' * 64,
              'artifact_root_identity': {'path': str(tmp_path)}}
    queue.task.update(qitemId=task_id, destinationSession=descriptor.QUANT, sourceSession=descriptor.LEAD,
                      handedOffFrom=descriptor.OUTCOME, tags=sorted(source.TAGS),
                      body=canonical(descriptor.authority(config)).decode())
    queue.events[0].update(transitionId=4, actorSession=descriptor.QUANT)
    parent = {'qitemId': descriptor.OUTCOME, 'state': 'done', 'sourceSession': descriptor.QUANT,
              'destinationSession': descriptor.LEAD, 'closureReason': 'handed_off_to',
              'handedOffTo': descriptor.QUANT, 'tags': sorted(source.TAGS)}
    original = queue.read

    def read(*args):
        assert descriptor.permitted_read(list(args), config)
        if args == ('queue', 'show', task_id, '--full'):
            return deepcopy(queue.task)
        if args == ('queue', 'transitions', task_id, '--full'):
            return deepcopy(queue.events)
        if args == ('queue', 'show', descriptor.OUTCOME, '--full'):
            return deepcopy(parent)
        if args == ('queue', 'transitions', descriptor.OUTCOME, '--full'):
            return [{'state': 'done', 'transitionId': 2, 'actorSession': descriptor.LEAD,
                     'identityProvenance': 'transport:v1'}]
        return original(*args)

    queue.read = read
    assert descriptor.current_custody(config, queue)['authority_transition'] == 2
    assert not descriptor.permitted_read(['queue', 'show', 'qitem-other', '--full'], config)
    queue.task['claimedByGeneration'] = 'stale'
    with pytest.raises(ValueError, match='BAND_SOURCE_GENERATION'):
        descriptor.current_custody(config, queue)
    queue.task['claimedByGeneration'] = queue.generation
    queue.task['body'] = canonical({**descriptor.authority(config), 'manifest_sha256': 'f' * 64}).decode()
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_NATIVE_AUTHORITY'):
        descriptor.current_custody(config, queue)
    queue.task['body'] = canonical(descriptor.authority(config)).decode()
    parent['state'] = 'in-progress'
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_NATIVE_AUTHORITY'):
        descriptor.current_custody(config, queue)


def test_runtime_rejects_writable_selected_source_submount(tmp_path, monkeypatch):
    from subprocess import CompletedProcess
    import subprocess

    store = tmp_path / 'store'
    root = tmp_path / descriptor.OUTPUT_NAME
    image = 'sha256:' + 'f' * 64
    config = {'runtime_image_id': image, 'artifact_root_identity': {'path': str(root)}}
    mounts = [{'Type': 'bind', 'Source': str(path), 'Destination': str(path), 'RW': writable}
              for path, writable in ((store, False), (root, True))]

    def inspect(command, **kwargs):
        return CompletedProcess(command, 0, b'\n'.join(map(canonical, (image, 'none', mounts))))

    monkeypatch.setattr(subprocess, 'run', inspect)
    descriptor.check_container('a' * 12, config)
    mounts[1]['Source'] = str(tmp_path / 'alternate-root')
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_MOUNTS'):
        descriptor.check_container('a' * 12, config)
    mounts[1]['Source'] = str(root)
    mounts.append({'Destination': str(store / 'reference-inputs'), 'RW': True})
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_MOUNTS'):
        descriptor.check_container('a' * 12, config)


def test_existing_effect_with_different_binding_is_preserved(tmp_path, invented_runtime, monkeypatch):
    root, config, _ = synthetic_config(tmp_path, *invented_runtime)
    result = descriptor.run(config, root, 10**8, queue=None)
    checkpoint = Path(result['checkpoint_ref']['path'])
    original = checkpoint.read_bytes()
    monkeypatch.setattr(descriptor, '_load_reference_values', lambda *a, **k: pytest.fail('unexpected quote read'))
    config['locator_ref'] = put(tmp_path / 'copied-locator.json', pinned_bytes(config['locator_ref']))
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_EFFECT_CONFLICT'):
        descriptor.run(config, root, 10**8, queue=None)
    assert checkpoint.read_bytes() == original


def test_custody_rechecked_at_effect_boundary_before_quote_read(tmp_path, invented_runtime, monkeypatch):
    root, config, _ = synthetic_config(tmp_path, *invented_runtime)
    states = iter(({'generation': 'first'}, {'generation': 'changed'}))
    monkeypatch.setattr(descriptor, 'current_custody', lambda *_: next(states))
    monkeypatch.setattr(descriptor, '_load_reference_values', lambda *a, **k: pytest.fail('stale custody quote read'))
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_CUSTODY_CHANGED'):
        descriptor.run(config, root, 10**8, queue=None)
    assert not list((root / descriptor.PARENT).iterdir())


@pytest.mark.parametrize(('source_path', 'destination'), [
    ('store', '/tmp/source-alias'), ('store/reference-inputs', '/tmp/member-alias'),
    ('.', '/tmp/source-parent'), ('protocol.md', '/protocol.md'),
    ('spec.json', '/spec.json'), ('qualification.json', '/qualification.json'),
])
def test_runtime_rejects_writable_source_aliases_and_metadata_mounts(tmp_path, monkeypatch, source_path, destination):
    from subprocess import CompletedProcess
    import subprocess

    store = tmp_path / 'store'
    root = tmp_path / descriptor.OUTPUT_NAME
    image = 'sha256:' + 'f' * 64
    config = {'runtime_image_id': image, 'artifact_root_identity': {'path': str(root)}}
    mounts = [{'Type': 'bind', 'Source': str(path), 'Destination': str(path), 'RW': writable}
              for path, writable in ((store, False), (root, True))]
    mounts.append({'Type': 'bind', 'Source': str(tmp_path / source_path), 'Destination': destination, 'RW': False})
    monkeypatch.setattr(subprocess, 'run', lambda command, **_: CompletedProcess(
        command, 0, b'\n'.join(map(canonical, (image, 'none', mounts)))))
    descriptor.check_container('a' * 12, config)
    mounts[-1]['RW'] = True
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_MOUNTS'):
        descriptor.check_container('a' * 12, config)


def test_retained_metadata_read_checks_effective_mount_before_pin(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    pin = put(tmp_path / 'qualification.json', {'invented': True})
    monkeypatch.setattr(os, 'statvfs', lambda _: SimpleNamespace(f_flag=os.ST_RDONLY))
    assert descriptor.readonly_metadata(pin) == canonical({'invented': True})
    monkeypatch.setattr(os, 'statvfs', lambda _: SimpleNamespace(f_flag=0))
    monkeypatch.setattr(descriptor, 'pinned_bytes', lambda _: pytest.fail('writable metadata read'))
    with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_METADATA_WRITABLE'):
        descriptor.readonly_metadata(pin)


def test_output_correction_binds_native_lead_resolution_to_original_quant_claim(tmp_path):
    from copy import deepcopy
    from test_band_source import Queue

    queue = Queue()
    queue.actor = descriptor.QUANT
    queue.generation = descriptor.ORIGINAL_GENERATION
    task_id = descriptor.ORIGINAL_TASK
    config = {'namespace': 'RETAINED', 'consumer_task': task_id, 'actor_session': descriptor.QUANT,
              'code_revision': 'a' * 40, 'runtime_image_id': 'sha256:' + 'b' * 64,
              'artifact_root_identity': {'path': str(tmp_path), 'device': '1', 'inode': '2'},
              'output_volume': {'name': descriptor.OUTPUT_VOLUME, 'created_at': '2026-11-20T00:00:00Z'}}
    initial = descriptor.authority({**config, 'code_revision': descriptor.ORIGINAL_REVISION})
    queue.task.update(qitemId=task_id, destinationSession=descriptor.QUANT, sourceSession=descriptor.LEAD,
                      claimedByGeneration=queue.generation,
                      handedOffFrom=descriptor.OUTCOME, tags=sorted(source.TAGS), body=canonical(initial).decode())
    initial_id = descriptor.ORIGINAL_CLAIM
    claim = {'state': 'in-progress', 'transitionNote': 'claimed',
             'actorSession': descriptor.QUANT, 'identityProvenance': 'transport:v1'}
    resumed = {'transitionId': initial_id + 3, 'state': 'pending', 'actorSession': descriptor.LEAD,
               'transitionNote': f"auto-unparked: blocker {descriptor.OUTPUT_CORRECTION} reached terminal state 'done'"}
    queue.events = [{**claim, 'transitionId': initial_id}, resumed, {**claim, 'transitionId': initial_id + 4}]
    parent = {'qitemId': descriptor.OUTCOME, 'state': 'done', 'sourceSession': descriptor.QUANT,
              'destinationSession': descriptor.LEAD, 'closureReason': 'handed_off_to',
              'handedOffTo': descriptor.QUANT, 'tags': sorted(source.TAGS)}
    expected = descriptor.output_correction_approval(config)
    lead = {'qitemId': descriptor.OUTPUT_CORRECTION, 'state': 'done', 'sourceSession': descriptor.QUANT,
            'destinationSession': descriptor.LEAD, 'closureReason': 'no-follow-on',
            'tags': sorted(source.TAGS), 'resolution': canonical(expected).decode()}
    closing = {'state': 'done', 'transitionId': initial_id + 2,
               'actorSession': descriptor.LEAD, 'identityProvenance': 'transport:v1'}
    parent_closing = {**closing, 'transitionId': initial_id - 1}
    original = queue.read

    def read(*args):
        assert descriptor.permitted_read(list(args), config)
        if args[:2] == ('queue', 'show'):
            return deepcopy({task_id: queue.task, descriptor.OUTCOME: parent,
                             descriptor.OUTPUT_CORRECTION: lead}[args[2]])
        if args[:2] == ('queue', 'transitions'):
            return deepcopy({task_id: queue.events, descriptor.OUTCOME: [parent_closing],
                             descriptor.OUTPUT_CORRECTION: [closing]}[args[2]])
        return original(*args)

    queue.read = read
    proof = descriptor.current_custody(config, queue)
    assert proof['consumer_task'] == descriptor.ORIGINAL_TASK
    assert proof['output_correction_transition'] == closing['transitionId']
    assert proof['claim_transition'] == queue.events[-1]['transitionId']
    lead['state'] = 'in-progress'
    with pytest.raises(ValueError, match='OUTPUT_CORRECTION_AUTHORITY'):
        descriptor.current_custody(config, queue)
    lead['state'] = 'done'
    for change in ({'prior_descriptor_effect': 'UNKNOWN'}, {'output_root_identity': {'path': '/alternate'}},
                   {'output_volume': {**config['output_volume'], 'created_at': 'other'}}):
        lead['resolution'] = canonical({**expected, **change}).decode()
        with pytest.raises(ValueError, match='OUTPUT_CORRECTION_AUTHORITY'):
            descriptor.current_custody(config, queue)
    lead['resolution'] = canonical(expected).decode()
    closing['actorSession'] = descriptor.QUANT
    with pytest.raises(ValueError, match='OUTPUT_CORRECTION_AUTHORITY'):
        descriptor.current_custody(config, queue)
    closing['actorSession'] = descriptor.LEAD
    queue.events.remove(resumed)
    with pytest.raises(ValueError, match='OUTPUT_CORRECTION_LINEAGE'):
        descriptor.current_custody(config, queue)
    queue.events.insert(1, resumed)
    queue.generation = queue.task['claimedByGeneration'] = 'other-generation'
    with pytest.raises(ValueError, match='OUTPUT_CORRECTION_LINEAGE'):
        descriptor.current_custody(config, queue)


def test_output_correction_caps_the_volume_to_the_original_retained_scope(tmp_path, invented_runtime):
    _, invented, _ = synthetic_config(tmp_path, *invented_runtime)
    volume = {'name': descriptor.OUTPUT_VOLUME, 'created_at': '2026-11-20T00:00:00Z'}
    with pytest.raises(ValueError, match='OUTPUT_CORRECTION_SCOPE'):
        descriptor.check_scope({**invented, 'output_volume': volume})
    retained = {**invented, 'namespace': 'RETAINED', 'consumer_task': descriptor.ORIGINAL_TASK,
                'protocol_ref': {'sha256': source.PROTOCOL_SHA}, 'locator_ref': {'sha256': descriptor.LOCATOR_SHA},
                'qualification_ref': {'sha256': descriptor.QUALIFICATION_SHA}, 'output_volume': volume}
    descriptor.check_scope(retained)
    with pytest.raises(ValueError, match='OUTPUT_CORRECTION_SCOPE'):
        descriptor.check_scope({**retained, 'consumer_task': 'qitem-unrelated'})

    mountpoint = '/var/lib/docker/volumes/local-private/_data'
    mount = {'Type': 'volume', 'Name': descriptor.OUTPUT_VOLUME, 'Driver': 'local', 'Source': mountpoint}
    inspected = {'Name': descriptor.OUTPUT_VOLUME, 'Driver': 'local', 'Scope': 'local',
                 'Labels': descriptor.OUTPUT_LABELS, 'Options': None, 'CreatedAt': volume['created_at'],
                 'Mountpoint': mountpoint}
    descriptor.check_private_volume(retained, mount, inspected)
    for change in ({'Options': {'type': 'none', 'o': 'bind', 'device': '/protected'}},
                   {'CreatedAt': 'recreated'}, {'Labels': {}}, {'Mountpoint': '/another-path'}):
        with pytest.raises(ValueError, match='IEF_BIL_DESCRIPTOR_PRIVATE_VOLUME'):
            descriptor.check_private_volume(retained, mount, {**inspected, **change})
