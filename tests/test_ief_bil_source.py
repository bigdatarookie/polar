"""Source-free witnesses for the closed month-end preparation and preflight."""
from pathlib import Path

import pytest

from polar import ief_bil_source as source
from polar import native_selected_tool as tool
from polar import selected_component_input as component
from polar.ci_research_service import root_identity
from polar.gym_service import code_binding
from polar.reference_input import preflight_input, prepare_input
from polar.research_reference import decode, load_reference, pinned_bytes
from test_reference_input import put
from test_selected_component_input import selected_fixture_graph


@pytest.fixture
def scope(tmp_path, monkeypatch):
    from polar import candidate_binding

    monkeypatch.setattr(candidate_binding, 'loaded_revision', lambda: 'a' * 40)
    monkeypatch.setenv('POLAR_CI_RUNTIME_IMAGE_ID', 'sha256:' + 'b' * 64)
    root, spec, parent, _ = selected_fixture_graph(tmp_path, ('IEF', 'VTI', 'GLD'))
    spec['normalized_inputs'][0]['symbol'] = 'IEF'
    spec['normalized_inputs'].append({**spec['normalized_inputs'][0], 'symbol': 'VTI'})
    spec['date_range'] = {'start': '2024-01-31', 'end': '2024-01-31', 'count': 1}
    config = {'schema': source.SOURCE_SCHEMA, 'namespace': 'INVENTED', 'question_id': source.QUESTION,
              'purpose': source.PURPOSE_SCHEMA, 'actor_session': source.PRODUCER,
              'consumer_task': 'qitem-INVENTED-IEF-BIL', 'artifact_root_identity': root_identity(root),
              'code': code_binding(), 'code_revision': 'a' * 40, 'runtime_image_id': 'sha256:' + 'b' * 64,
              'protocol_ref': put(tmp_path / 'protocol.md', b'Invented protocol'),
              'source_fit_ref': put(tmp_path / 'fit.json', {'status': 'INVENTED'})}
    spec['qualification_refs'] = [config['source_fit_ref']]
    spec['purpose_ref'] = put(tmp_path / 'purpose.json', source.purpose_metadata(config, spec))
    config['spec_ref'] = put(tmp_path / 'spec.json', spec)
    return root, config, spec, decode(pinned_bytes(parent))


def test_closed_route_excludes_gld_mixed_quotes_and_non_month_ends(scope, monkeypatch):
    root, config, _, parent = scope
    reads = []
    original_decode = component.decode

    def read(pin):
        assert pin['path'] != parent['quotes']['path'] and '/objects/' not in pin['path']
        return pinned_bytes(pin)

    def selected_decode(raw):
        row = original_decode(raw)
        if 'query_symbol' in row or 'reference_quote' in row:
            symbol = row.get('query_symbol', row.get('symbol'))
            day = row.get('reference_date', row.get('date'))
            assert symbol in ('BIL', 'IEF', 'VTI') and day == '2024-01-31'
            reads.append(symbol)
        return row

    monkeypatch.setattr(component, 'pinned_bytes', read)
    monkeypatch.setattr(component, 'decode', selected_decode)
    assert tool.selected_config('research-input-prepare', config) == config
    pin = prepare_input(config, root, 10**8)['input_ref']
    assert tool.selected_config('research-input-preflight', pin) == config
    receipt = preflight_input(pin, root=root)
    assert receipt['dates'] == 1 and receipt['symbols'] == receipt['rows'] == 3
    assert receipt['producer_terminal_result']['input_manifest_sha256'] == pin['sha256']
    assert set(reads) == {'BIL', 'IEF', 'VTI'}
    manifest = decode(pinned_bytes(pin))
    quotes = [decode(line) for line in pinned_bytes(manifest['quotes']).splitlines()]
    assert quotes[1]['reference_quote'] == quotes[1]['source_adjusted_close_token'] == '20.1'
    with pytest.raises(ValueError, match='IEF_BIL_SOURCE_ONLY'):
        load_reference(pin)


@pytest.mark.parametrize(('field', 'value'), [('question_id', 'OTHER'), ('purpose', 'OTHER'),
                                             ('namespace', 'FOREIGN'), ('consumer_task', source.TASK)])
def test_foreign_scope_fails_on_both_dispatches(scope, tmp_path, field, value):
    _, config, _, _ = scope
    invalid = {**config, field: value}
    manifest = {'schema': source.MANIFEST_SCHEMA,
                'provenance': {'source_native_binding': {'config': invalid}}}
    for operation, payload in (('research-input-prepare', invalid),
                               ('research-input-preflight', put(tmp_path / 'manifest.json', manifest))):
        with pytest.raises(ValueError, match='IEF_BIL_SOURCE_SCOPE'):
            tool.selected_config(operation, payload)


def test_wrong_purpose_metadata_or_wrong_endpoint_scope_never_materializes(scope, tmp_path, monkeypatch):
    root, config, spec, _ = scope
    monkeypatch.setattr(component, 'prepare_selected_components',
                        lambda *a, **k: pytest.fail('unexpected materialization'))
    purpose = source.purpose_metadata(config, spec)
    spec['purpose_ref'] = put(tmp_path / 'wrong-purpose.json', {**purpose, 'question_id': 'OTHER'})
    config['spec_ref'] = put(tmp_path / 'wrong-spec.json', spec)
    with pytest.raises(ValueError, match='IEF_BIL_SOURCE_PURPOSE'):
        prepare_input(config, root, 10**8)
    spec['date_range'] = {'start': '2024-02-01', 'end': '2024-02-02', 'count': 2}
    spec['purpose_ref'] = put(tmp_path / 'purpose.json', source.purpose_metadata(config, spec))
    config['spec_ref'] = put(tmp_path / 'wrong-spec.json', spec)
    with pytest.raises(ValueError, match='IEF_BIL_SOURCE_ENDPOINT_SCOPE'):
        prepare_input(config, root, 10**8)


def test_read_time_manifest_location_is_part_of_input_binding(scope, tmp_path, monkeypatch):
    root, config, _, _ = scope
    prepared = prepare_input(config, root, 10**8)['input_ref']
    copied = put(tmp_path / 'copied-manifest.json', Path(prepared['path']).read_bytes())
    from polar import research_reference
    monkeypatch.setattr(research_reference, '_load_reference_values',
                        lambda *a, **k: pytest.fail('unexpected quote read'))
    with pytest.raises(ValueError, match='IEF_BIL_SOURCE_PREPARED_BINDING'):
        preflight_input(copied, root=root)


def test_retained_native_custody_pairs_task_dispatch_and_live_generation(scope, monkeypatch):
    from polar.band_source import generation_read
    from test_band_source import Queue

    root, config, _, _ = scope
    config.update(namespace='RETAINED', consumer_task=source.TASK)
    monkeypatch.setattr(source, 'actual_runtime', lambda _: None)
    queue = Queue()
    queue.task.update(qitemId=source.TASK, sourceSession=source.DISPATCHER, tags=sorted(source.TAGS))
    read = queue.read

    def native_read(*args):
        if args[:2] == ('queue', 'show'):
            assert args[2:] == (source.TASK, '--full')
            return queue.task.copy()
        if args[:2] == ('queue', 'transitions'):
            assert args[2:] == (source.TASK, '--full')
            return queue.events
        return read(*args)

    queue.read = native_read
    assert tool.permitted(list(generation_read(source.PRODUCER)), config)
    assert tool.permitted(['queue', 'show', source.TASK, '--full'], config)
    assert not tool.permitted(['queue', 'show', 'qitem-unrelated', '--full'], config)
    proof = source.authorize(config, root, queue=queue)
    assert proof['generation'] == queue.generation and proof['consumer_task'] == source.TASK
    queue.task['claimedByGeneration'] = 'superseded-generation'
    with pytest.raises(ValueError, match='BAND_SOURCE_GENERATION'):
        source.authorize(config, root, queue=queue, prior=proof)
    queue.task['sourceSession'] = 'foreign-dispatcher'
    with pytest.raises(ValueError, match='BAND_SOURCE_CURRENT_TASK'):
        source.authorize(config, root, queue=queue)


def test_retained_bridge_verifies_actual_container_image_before_execution(scope, monkeypatch):
    _, config, _, _ = scope
    config.update(namespace='RETAINED', consumer_task=source.TASK)

    def inspect(command, **kwargs):
        assert command == ['docker', 'inspect', '--type', 'container', '--format', '{{.Image}}', 'a' * 12]
        return tool.subprocess.CompletedProcess(command, 0, 'sha256:' + 'c' * 64 + '\n')

    monkeypatch.setattr(tool.subprocess, 'run', inspect)
    monkeypatch.setattr(tool, 'pipe_bridge', lambda *a, **k: pytest.fail('unexpected container execution'))
    with pytest.raises(tool.ResearchError, match='IEF_BIL_SOURCE_RUNTIME_IMAGE'):
        tool.bridge('a' * 12, 'research-input-prepare', config)
