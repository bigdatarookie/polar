"""Controlled inventory boundaries; no Docker daemon or PostgreSQL required."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location('polar_ops', Path(__file__).parents[1]/'scripts/ops.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
SENTINEL = 'credential-SENTINEL-do-not-disclose'
REV = 'a'*40
IMAGE = 'sha256:'+'b'*64


@pytest.fixture
def runtime():
    config = {'name': 'polar', 'volumes': {'db': {'name': 'polar_test_db'}, 'artifacts': {'name': 'polar_test_artifacts'}},
              'networks': {'service': {'name': 'polar_test_service'}, 'api_host': {'name': 'polar_test_api'}}, 'services': {}}
    items = []
    for n, service in enumerate(ops.SERVICES, 1):
        config['services'][service] = {'cpus': .5, 'mem_limit': 512*1024**2, 'pids_limit': 100}
        mount = {'Destination': '/var/lib/postgresql/data' if service == 'db' else '/data/artifacts',
                 'Type': 'volume', 'Name': 'polar_test_db' if service == 'db' else 'polar_test_artifacts', 'RW': service != 'api'}
        items.append({'Id': str(n)*64, 'Image': IMAGE,
                      'Config': {'Env': ['PASSWORD='+SENTINEL], 'Labels': {'com.docker.compose.project': 'polar',
                          'com.docker.compose.project.working_dir': str(ops.ROOT), 'com.docker.compose.service': service,
                          'com.docker.compose.oneoff': 'False', 'com.docker.compose.config-hash': 'c'*64,
                          'org.opencontainers.image.revision': REV, 'secret': SENTINEL}},
                      'State': {'Status': 'running', 'Error': SENTINEL},
                      'HostConfig': {'NanoCpus': 500000000, 'Memory': 512*1024**2, 'PidsLimit': 100},
                      'Mounts': [mount, {'Destination': '/run/secrets/db_password', 'Source': SENTINEL}],
                      'Networks': {'polar_test_service': {}}, 'Ports': {}})
    items[1]['Networks']['polar_test_api'] = {}
    items[1]['Ports'] = {'8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18081'}]}
    config['services']['api']['ports'] = [{'host_ip': '127.0.0.1', 'published': '18081'}]
    calls = []
    schema = {'schema_version': 1, 'schema_sha256': ops.sha(ops.ROOT/'src/polar/schema.sql'),
              'datasets': 4, 'runs': 10, 'attempts': 11, 'active': 0}

    def read(args):
        calls.append(args)
        if args[0] == 'git':
            if args[-1] == 'HEAD:scripts/ops.py':
                return Path(ops.__file__).read_text()
            return REV+'\n'
        if args[:2] == ['docker', 'compose']:
            return json.dumps(config) if 'config' in args else '\n'.join(i['Id'] for i in items)
        if args[:2] == ['docker', 'inspect']:
            assert '--format' in args
            assert '.Config.Env' not in args[args.index('--format')+1]
            return '\n'.join(json.dumps(i) for i in items)
        if args[:3] in (['docker', 'volume', 'inspect'], ['docker', 'network', 'inspect']):
            return json.dumps([{'Name': args[-1], 'Labels': {'com.docker.compose.project': 'polar', 'polar.scope': 'POL.0.4.0.1', 'password': SENTINEL}}])
        if args[:2] == ['docker', 'exec']:
            assert 'BEGIN READ ONLY' in args[-1]
            return json.dumps(schema)+'\n'
        raise AssertionError(args)
    return config, items, schema, calls, read


def test_allowlist_binding_and_separate_selected_tooling(runtime):
    _, _, _, calls, read = runtime
    m = ops.inventory_manifest(REV, IMAGE, read=read)
    assert m['schema'] == 'polar.runtime-inventory/1'
    assert m['selected_tooling']['ops_matches_commit'] is True
    assert m['observed']['database']['schema_equal_selected'] is True
    assert m['observed']['database']['counters'] == {'datasets': 4, 'runs': 10, 'attempts': 11, 'active': 0}
    assert m['checks']['api']['image_equal_expected'] is True
    assert m['checks']['worker']['caps_equal_desired'] is True
    assert m['limits']['running_source_bytes_verification'] == 'NOT_RUN'
    assert m['limits']['hard_storage_quota'] == 'NOT_ENFORCED'
    assert m['backup_handle']['status'] == 'NOT_RUN'
    assert SENTINEL not in json.dumps(m)
    # A tooling revision can differ from the accepted running app without a false code-proof claim.
    _, items, _, _, _ = runtime
    items[1]['Config']['Labels']['org.opencontainers.image.revision'] = 'd'*40
    m = ops.inventory_manifest(read=read)
    assert m['observed']['services']['api']['revision_label'] == 'd'*40
    assert m['checks']['api']['app_revision_equal_expected'] == 'NOT_RUN'
    assert all(not any(v in c for v in ['up', 'run', 'stop', 'build', 'rm', 'migrate']) for c in calls)


@pytest.mark.parametrize('defect', ['project', 'root', 'duplicate', 'mount', 'network', 'port'])
def test_refuses_wrong_or_ambiguous_runtime_before_db_probe(runtime, defect):
    _, items, _, calls, read = runtime
    if defect == 'project': items[0]['Config']['Labels']['com.docker.compose.project'] = SENTINEL
    if defect == 'root': items[0]['Config']['Labels']['com.docker.compose.project.working_dir'] = SENTINEL
    if defect == 'duplicate': items.append(copy.deepcopy(items[1]))
    if defect == 'mount': items[1]['Mounts'][0]['Name'] = 'foreign'
    if defect == 'network': items[1]['Networks']['foreign'] = {}
    if defect == 'port': items[1]['Ports']['8000/tcp'][0]['HostIp'] = '0.0.0.0'
    with pytest.raises(ops.InventoryError) as e:
        ops.inventory_manifest(read=read)
    assert SENTINEL not in str(e.value)
    assert not any(c[:2] == ['docker', 'exec'] for c in calls)


def test_unavailable_measurements_are_unknown(runtime):
    _, items, schema, _, read = runtime
    schema['schema_sha256'] = SENTINEL
    items[1]['Config']['Labels']['org.opencontainers.image.revision'] = SENTINEL
    items[1]['HostConfig']['Memory'] = None
    m = ops.inventory_manifest(read=read)
    assert m['observed']['database']['schema_equal_selected'] == 'UNKNOWN'
    assert m['observed']['services']['api']['revision_label'] == 'UNKNOWN'
    assert m['observed']['services']['api']['caps']['memory_bytes'] == 'UNKNOWN'
    assert SENTINEL not in json.dumps(m)
    def unavailable(args):
        if args[:2] == ['docker', 'exec']: raise ops.InventoryError('INVENTORY_COMMAND_FAILED')
        return read(args)
    assert ops.inventory_manifest(read=unavailable)['observed']['database']['status'] == 'UNKNOWN'


def test_output_boundary_new_external_file_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ops, 'inventory_manifest', lambda *args, **kwargs: {'schema': 'controlled'})
    output = tmp_path/'new.json'
    ops.inventory(output)
    assert json.loads(output.read_text()) == {'schema': 'controlled'}
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SystemExit, match='NEW_EXTERNAL'):
        ops.inventory(output)
    assert output.read_text() == '{\n  "schema": "controlled"\n}\n'
    with pytest.raises(SystemExit, match='EXTERNAL'):
        ops.inventory(ops.ROOT/'forbidden.json')
    with pytest.raises(SystemExit, match='NEW_EXTERNAL'):
        ops.inventory(Path('relative.json'))
    link = tmp_path/'link.json'; link.symlink_to(output)
    with pytest.raises(SystemExit, match='NEW_EXTERNAL'):
        ops.inventory(link)
    assert 'controlled' not in capsys.readouterr().out


def test_foreign_git_and_sentinel_failures_leave_no_output(tmp_path, monkeypatch, capsys):
    repo = tmp_path/'other'; repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    with pytest.raises(SystemExit, match='EXTERNAL'):
        ops.inventory(repo/'manifest.json')
    def fail(*args): raise ValueError(SENTINEL)
    monkeypatch.setattr(ops, 'inventory_manifest', fail)
    output = tmp_path/'failure.json'
    with pytest.raises(SystemExit, match='^INVENTORY_UNAVAILABLE$') as e:
        ops.inventory(output)
    assert not output.exists() and SENTINEL not in str(e.value)
    monkeypatch.setattr(ops.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 1, SENTINEL, SENTINEL))
    with pytest.raises(ops.InventoryError, match='^INVENTORY_COMMAND_FAILED$'):
        ops.inventory_read(['docker', 'info'])
    assert SENTINEL not in ''.join(capsys.readouterr())


def test_ownership_refusal_preserves_existing_mutating_guard(runtime, monkeypatch):
    _, items, _, _, _ = runtime
    items[0]['Config']['Labels']['com.docker.compose.project'] = 'wrong'
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, items[0]['Id'] if args[0:2] == ['docker', 'compose'] else json.dumps(items))
    monkeypatch.setattr(ops, 'run', run)
    with pytest.raises(SystemExit, match='Container ownership mismatch'):
        ops.check_ownership()


def test_resource_ownership_and_bounds(runtime):
    _, items, _, _, read = runtime
    def wrong_volume(args):
        if args[:2] == ['docker', 'volume']:
            return json.dumps([{'Name': args[-1], 'Labels': {'com.docker.compose.project': 'foreign'}}])
        return read(args)
    with pytest.raises(ops.InventoryError, match='RESOURCE_OWNERSHIP'):
        ops.inventory_manifest(read=wrong_volume)
    with pytest.raises(ops.InventoryError, match='INVALID_REVISION'):
        ops.inventory_manifest(SENTINEL, read=read)
    items.extend(copy.deepcopy(items[0]) for _ in range(10))
    with pytest.raises(ops.InventoryError, match='AMBIGUOUS_CONTAINERS'):
        ops.inventory_manifest(read=read)


def test_static_desired_does_not_become_observed(runtime):
    _, items, _, _, read = runtime
    del items[1]
    manifest = ops.inventory_manifest(read=read)
    assert manifest['observed']['services']['api']['status'] == 'UNKNOWN'
    assert manifest['checks']['api'] == 'UNKNOWN'
    assert 'caps' in manifest['desired']['services']['api']


def test_backup_binds_existing_format_without_opening_dump(runtime, tmp_path):
    _, _, _, _, read = runtime
    (tmp_path/'backup-manifest.json').write_text(json.dumps({'scope': 'POL.0.4.0.1', 'code_revision': REV,
        'files': {'metadata.dump': 'e'*64, 'artifacts.tar': 'f'*64}, 'password': SENTINEL}))
    # No dump files exist: inventory reads only metadata and never claims restore/coverage.
    manifest = ops.inventory_manifest(backup_directory=tmp_path, read=read)
    assert manifest['backup_handle']['status'] == 'METADATA_ONLY'
    assert manifest['backup_handle']['file_verification'] == 'NOT_RUN'
    assert manifest['backup_handle']['current_state_coverage'] == 'UNKNOWN'
    assert SENTINEL not in json.dumps(manifest)


def test_output_size_bound_and_sanitized_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, 'inventory_manifest', lambda *args, **kwargs: {'over_limit': 'x'*65536})
    with pytest.raises(SystemExit, match='OUTPUT_LIMIT'):
        ops.inventory(tmp_path/'too-large.json')
    assert not (tmp_path/'too-large.json').exists()
    def timeout(*args, **kwargs): raise subprocess.TimeoutExpired(SENTINEL, 8, output=SENTINEL)
    monkeypatch.setattr(ops.subprocess, 'run', timeout)
    with pytest.raises(ops.InventoryError, match='^INVENTORY_COMMAND_UNAVAILABLE$'):
        ops.inventory_read(['docker', 'info'])
