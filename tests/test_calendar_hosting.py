"""A8 outer consumer: invented metadata and nonfinancial pressure children only."""
from pathlib import Path
import os
import sys
import time

import pytest

from polar import calendar_hosting as host
from polar.ci_research_service import root_identity
from polar.gym_contract import GymError, canonical, decode, sha
from polar.gym_service import code_binding
from polar.history_store import HistoryStore
from polar.history_bundle import decode as physical_decode


def put(path, value):
    raw = canonical(value)
    path.write_bytes(raw)
    return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}


def fixture(tmp_path, config=None):
    root = tmp_path / 'artifacts'
    root.mkdir(exist_ok=True)
    config = config or {'schema': 'polar.calendar-study-config/1', 'namespace': 'INVENTED',
                        'code': code_binding(), 'artifact_root_identity': root_identity(root),
                        'runtime_image_id': 'sha256:' + 'a'*64}
    a = {'schema': host.SCHEMA, 'action': 'PREFLIGHT', 'config_sha256': sha(canonical(config)),
         'artifact_root_identity': config['artifact_root_identity'], 'actor_uid': os.getuid(),
         'actor_gid': os.getgid(), 'runtime_image_id': config['runtime_image_id'], 'export_bytes': 0,
         'limits': {'wall_seconds': 10, 'cpu_seconds': 5, 'outer_wall_seconds': 20, 'outer_cpu_seconds': 10,
                    'host_log_bytes': 65536, 'docker_log_bytes': 65536, 'cleanup_seconds': 1, 'poll_seconds': 1,
                    'rss_bytes': 512*1024**2, 'store_growth_bytes': 1024**2,
                    'output_bytes': 65536, 'journal_bytes': 65536, 'receipt_bytes': 512*1024,
                    'metadata_inflight_bytes': 65536, 'concurrent_growth_bytes': 65536},
         'physical': {'status': 'INVENTED_TEST_ONLY', 'measured_ns': time.time_ns(),
                      'valid_until_ns': time.time_ns() + 60*10**9,
                      'project_ceiling_bytes': 8*1024**2, 'project_used_upper_bytes': 0,
                      'allocated_growth_upper_bytes': 4*1024**2,
                      'unknown_owners_included': True, 'unique_backing_accounting': True,
                      'guard_ref': None}}
    return root, config, bind_guard(tmp_path, a)


def bind_guard(tmp_path, admission):
    p = admission['physical']
    guard = {'schema': 'polar.calendar-host-guard/1', 'status': 'INVENTED_TEST_ONLY',
             'binding_sha256': sha(canonical(host.hosting_binding(admission))),
             'coverage': host.COVERAGE, 'allocated_growth_upper_bytes': p['allocated_growth_upper_bytes'],
             'valid_until_ns': p['valid_until_ns'], 'guard_id': 'INVENTED',
             'root_identity': admission['artifact_root_identity']}
    p['guard_ref'] = put(tmp_path/'guard.json', guard)
    return admission


@pytest.mark.parametrize('bad', ['unknown', 'expired', 'headroom', 'owner', 'double_count',
                                'export', 'actor', 'config', 'bool_limit', 'coverage', 'guard_pin'])
def test_refuse_before_any_writer_child_or_source(tmp_path, monkeypatch, bad):
    root, config, a = fixture(tmp_path)
    if bad == 'unknown': a['physical']['status'] = 'UNKNOWN'
    elif bad == 'expired': a['physical']['valid_until_ns'] = time.time_ns() - 1
    elif bad == 'headroom': a['physical']['project_used_upper_bytes'] = 8*1024**2
    elif bad == 'owner': a['physical']['unknown_owners_included'] = False
    elif bad == 'double_count': a['physical']['unique_backing_accounting'] = False
    elif bad == 'export': a['export_bytes'] = 1
    elif bad == 'actor': a['actor_uid'] += 1
    elif bad == 'config': a['config_sha256'] = '0'*64
    elif bad == 'bool_limit': a['limits']['wall_seconds'] = True
    elif bad == 'coverage':
        g = decode(Path(a['physical']['guard_ref']['path']).read_bytes())
        g['coverage'] = ['store']
        a['physical']['guard_ref'] = put(tmp_path/'guard.json', g)
    elif bad == 'guard_pin': a['physical']['guard_ref']['sha256'] = '0'*64
    monkeypatch.setattr(host, 'supervise', lambda *a, **k: pytest.fail('child started'))
    with pytest.raises((ValueError, GymError, OSError)):
        host.run(root, config, a)
    assert list(root.iterdir()) == []


def test_physical_accounting_is_bound_to_guard_not_just_logical_limits(tmp_path):
    root, config, a = fixture(tmp_path)
    a['physical']['project_used_upper_bytes'] += 1
    with pytest.raises(ValueError, match='CALENDAR_HOST_GUARD_UNBOUND'):
        host.run(root, config, a)
    assert list(root.iterdir()) == []


def test_invented_guard_never_qualifies_retained(tmp_path):
    root, config, a = fixture(tmp_path)
    config['namespace'] = 'RETAINED'; a['config_sha256'] = sha(canonical(config))
    bind_guard(tmp_path, a)
    with pytest.raises(ValueError, match='CALENDAR_HOST_PHYSICAL_UNCERTIFIED'):
        host.run(root, config, a)
    assert list(root.iterdir()) == []


def test_retained_direct_call_has_no_implicit_host_authority(tmp_path, monkeypatch):
    root, config, a = fixture(tmp_path)
    monkeypatch.delenv('POLAR_CALENDAR_HOST_CHILD', raising=False)
    service = type('Service', (), {'store': HistoryStore(root, 1)})()
    with pytest.raises(ValueError, match='CALENDAR_HOST_REQUIRED'):
        host.validate_child(service, config)
    assert list(root.iterdir()) == []


@pytest.mark.skipif(sys.platform != 'linux', reason='actual supervisor requires Linux')
def test_actual_calendar_cli_preflight_child_no_native_or_attempt(tmp_path):
    from test_calendar_study_service import fixture as calendar_fixture
    service, config, *_ = calendar_fixture(tmp_path/'fixture')
    root, _, a = fixture(tmp_path, config)
    # The real metadata fixture owns its separate artifact root.
    root.rmdir(); root = service.store.root
    result = host.run(root, config, a)
    assert result['status'] == 'PREFLIGHT_ONLY'
    assert result['process']['cleanup'] == 'COMPLETE'
    assert not (root/'scheduled-reference-attempts').exists()
    record = physical_decode((root/result['hosting_path']/'collection/record.json').read_bytes())
    assert record['status'] == 'PREFLIGHT_ONLY'
    assert (root/result['hosting_path']/'console.log').stat().st_size <= a['limits']['output_bytes']


@pytest.mark.skipif(sys.platform != 'linux', reason='actual supervisor requires Linux')
@pytest.mark.parametrize('pressure', ['store', 'output', 'wall'])
def test_outer_process_log_store_interaction_preserves_completed(tmp_path, monkeypatch, pressure):
    root, config, a = fixture(tmp_path)
    a['action'] = 'ORIGINAL'
    if pressure == 'output': a['limits']['output_bytes'] = 4096
    if pressure == 'wall': a['limits']['wall_seconds'] = 1
    bind_guard(tmp_path, a)
    real = host.supervise
    # Nonfinancial surrogate at the child boundary: production argv/env still
    # checked here; the real supervisor, store, logs and collector are exercised.
    code = """import os,time
from polar.history_store import HistoryStore
s=HistoryStore(os.environ['POLAR_ARTIFACT_ROOT'],int(os.environ['POLAR_STORAGE_BYTES']))
with s.locked():s._publish('invented-witness','completed',{'record':b'completed'})
MODE
"""
    if pressure == 'store':
        body = "with s.locked():s._publish('invented-witness','rejected',{'record':b'x'*(2*1024**2)})"
    elif pressure == 'output': body = "while True:os.write(2,b'x'*65536)"
    else: body = 'time.sleep(30)'
    def consumer(argv, **kwargs):
        assert argv[:4] == [sys.executable, '-m', 'polar.cli', 'research-run']
        assert kwargs['env']['POLAR_ARTIFACT_ROOT'] == str(root)
        return real([sys.executable, '-c', code.replace('MODE', body)], **kwargs)
    monkeypatch.setattr(host, 'supervise', consumer)
    result = host.run(root, config, a)
    assert result['status'] == 'FAILED_UNFINALIZED'
    assert result['process']['cleanup'] == 'COMPLETE'
    assert result['process']['remaining_owned_pids'] == []
    assert (root/'invented-witness/completed/record').read_bytes() == b'completed'
    assert not (root/'invented-witness/rejected').exists()
    assert not list(root.rglob('.history-partial-*'))
    directory = root/result['hosting_path']
    assert (directory/'console.log').stat().st_size <= a['limits']['output_bytes']
    assert (directory/'console.resources.ndjson').stat().st_size <= a['limits']['journal_bytes']
    assert (directory/'collection/record.json').exists()
    assert result['refund'] is False and result['automatic_retry'] is False
