"""Fixed A8 outer consumer; no allocation, scheduler, export or financial grant.

A current trusted SRE physical/guard receipt is a prerequisite, not a fact this
adapter can derive from logical store bytes, Docker.raw size or sampled RSS.
"""
import os
import sys
import time
import uuid
from pathlib import Path

from .ci_research import require
from .ci_research_service import root_identity
from .gym_contract import MAX_BYTES, canonical, decode, read_ref, sha
from .gym_service import code_binding
from .history_bundle import read_file
from .history_store import HistoryStore
from .process_budget import supervise

SCHEMA = 'polar.calendar-host-admission/1'
COVERAGE = ['parent', 'store', 'staging', 'supervision', 'collector', 'host_logs',
            'docker_logs', 'concurrent_writers', 'metadata_inflight']
LIMITS = {'wall_seconds', 'cpu_seconds', 'outer_wall_seconds', 'outer_cpu_seconds',
          'cleanup_seconds', 'poll_seconds', 'host_log_bytes', 'docker_log_bytes',
          'rss_bytes', 'store_growth_bytes', 'output_bytes', 'journal_bytes',
          'receipt_bytes', 'metadata_inflight_bytes', 'concurrent_growth_bytes'}


def positive(value):
    return type(value) is int and value > 0


def hosting_binding(admission):
    return {**{k: v for k, v in admission.items() if k != 'physical'},
            'physical': {k: v for k, v in admission['physical'].items() if k != 'guard_ref'}}


def prepare(root, config, admission):
    """Only supplied metadata; no calendar/source reader, writer or child."""
    fields = {'schema', 'action', 'config_sha256', 'artifact_root_identity',
              'actor_uid', 'actor_gid', 'runtime_image_id', 'limits', 'physical', 'export_bytes'}
    require(type(admission) is dict and set(admission) == fields and
            admission['schema'] == SCHEMA and admission['action'] in ('PREFLIGHT', 'ORIGINAL'),
            'CALENDAR_HOST_ADMISSION_SCHEMA')
    require(type(config) is dict and config.get('schema') == 'polar.calendar-study-config/1' and
            config.get('namespace') in ('INVENTED', 'RETAINED') and config.get('code') == code_binding() and
            admission['config_sha256'] == sha(canonical(config)), 'CALENDAR_HOST_CONFIG_BINDING')
    # No installed trusted physical/aggregate guard interface currently exists.
    # Caller-supplied status/hash/PID/env/cgroup equality cannot establish one.
    # Keep RETAINED unavailable, including with a fabricated CERTIFIED receipt.
    require(config['namespace'] != 'RETAINED',
            'CALENDAR_HOST_PHYSICAL_UNCERTIFIED_TRUSTED_GUARD_UNAVAILABLE')
    identity = root_identity(root)
    require(identity == config.get('artifact_root_identity') == admission['artifact_root_identity'] and
            type(admission['actor_uid']) is int and admission['actor_uid'] == os.getuid() and
            type(admission['actor_gid']) is int and admission['actor_gid'] == os.getgid() and
            admission['runtime_image_id'] == config.get('runtime_image_id'), 'CALENDAR_HOST_ACTUAL_BINDING')
    bounds = admission['limits']
    require(type(bounds) is dict and set(bounds) == LIMITS and
            all(positive(v) for v in bounds.values()) and
            bounds['output_bytes'] <= MAX_BYTES and bounds['receipt_bytes'] <= MAX_BYTES and
            bounds['poll_seconds'] <= bounds['wall_seconds'] and
            bounds['outer_wall_seconds'] > bounds['wall_seconds'] + bounds['cleanup_seconds'] and
            bounds['outer_cpu_seconds'] >= bounds['cpu_seconds'] and
            type(admission['export_bytes']) is int and admission['export_bytes'] == 0,
            'CALENDAR_HOST_LIMITS')
    physical = admission['physical']
    require(type(physical) is dict and set(physical) == {'status', 'measured_ns', 'valid_until_ns',
            'project_ceiling_bytes', 'project_used_upper_bytes', 'allocated_growth_upper_bytes',
            'unknown_owners_included', 'unique_backing_accounting', 'guard_ref'} and
            physical['status'] == ('CERTIFIED' if config['namespace'] == 'RETAINED' else 'INVENTED_TEST_ONLY') and
            physical['unknown_owners_included'] is True and physical['unique_backing_accounting'] is True and
            positive(physical['measured_ns']) and positive(physical['valid_until_ns']) and
            physical['measured_ns'] <= time.time_ns() and
            time.time_ns() + bounds['outer_wall_seconds']*10**9 < physical['valid_until_ns'] and
            positive(physical['project_ceiling_bytes']) and physical['project_ceiling_bytes'] <= 64*1024**3 and
            type(physical['project_used_upper_bytes']) is int and
            physical['project_used_upper_bytes'] >= 0 and positive(physical['allocated_growth_upper_bytes']),
            'CALENDAR_HOST_PHYSICAL_UNCERTIFIED')
    required = sum(bounds[k] for k in ('store_growth_bytes', 'output_bytes', 'journal_bytes',
                    'receipt_bytes', 'metadata_inflight_bytes', 'concurrent_growth_bytes',
                    'host_log_bytes', 'docker_log_bytes'))
    require(required <= physical['allocated_growth_upper_bytes'] <=
            physical['project_ceiling_bytes'] - physical['project_used_upper_bytes'],
            'CALENDAR_HOST_PHYSICAL_HEADROOM')
    guard = decode(read_ref(physical['guard_ref']))
    require(type(guard) is dict and guard.get('schema') == 'polar.calendar-host-guard/1' and
            guard.get('status') == ('ACTIVE_ENFORCED' if config['namespace'] == 'RETAINED' else 'INVENTED_TEST_ONLY') and
            guard.get('binding_sha256') == sha(canonical(hosting_binding(admission))) and
            guard.get('coverage') == COVERAGE and
            guard.get('allocated_growth_upper_bytes') == physical['allocated_growth_upper_bytes'] and
            guard.get('valid_until_ns') == physical['valid_until_ns'] and
            type(guard.get('guard_id')) is str and bool(guard['guard_id']) and
            guard.get('root_identity') == identity, 'CALENDAR_HOST_GUARD_UNBOUND')
    return bounds


def validate_child(service, config):
    """A caller's environment/PID cannot prove the unavailable guard interface."""
    require(False, 'CALENDAR_HOST_REQUIRED_TRUSTED_GUARD_UNAVAILABLE')


def run(root, config, admission):
    """Run one fixed CLI child; collection is a bounded local read, no export."""
    root = Path(root)
    bounds = prepare(root, config, admission)
    store = HistoryStore(root, 1)  # Set an absolute logical cap under the existing root lock.
    with store.locked():
        prepare(root, config, admission)
        before = store.used()
        store.limit = before + sum(bounds[k] for k in ('store_growth_bytes', 'output_bytes',
            'journal_bytes', 'receipt_bytes', 'metadata_inflight_bytes', 'concurrent_growth_bytes'))
        name = str(uuid.uuid4())
        parent = 'calendar-hosting/' + name
        config_raw, admission_raw = canonical(config), canonical(admission)
        # Reserve collection space before the child. Collection falls back to a
        # fixed failure receipt if a surprising process receipt exceeds reserve.
        require(len(config_raw) + len(admission_raw) + 4096 <= bounds['receipt_bytes'],
                'CALENDAR_HOST_RECEIPT_LIMIT')
        require(len(config_raw) + len(admission_raw) <= bounds['store_growth_bytes'],
                'CALENDAR_HOST_STORE_GROWTH_LIMIT')
        store._publish('calendar-hosting', name,
                       {'config.json': config_raw, 'admission.json': admission_raw}, file_limit=MAX_BYTES)
    directory = root / parent
    env = {**os.environ, 'POLAR_ARTIFACT_ROOT': str(root),
           'POLAR_STORAGE_BYTES': str(before + bounds['store_growth_bytes']),
           'PYTHONDONTWRITEBYTECODE': '1'}
    command = 'research-preflight' if admission['action'] == 'PREFLIGHT' else 'research-run'
    try:
        process = supervise([sys.executable, '-m', 'polar.cli', command, str(directory / 'config.json')],
                        env=env, output=directory / 'console.log',
                        cpu_seconds=bounds['cpu_seconds'], wall_seconds=bounds['wall_seconds'],
                        poll=bounds['poll_seconds'], cleanup_seconds=bounds['cleanup_seconds'],
                        rss_limit_bytes=bounds['rss_bytes'], max_output_bytes=bounds['output_bytes'],
                        max_journal_bytes=bounds['journal_bytes'])
    except (ValueError, OSError) as exc:
        process = {'exit_code': None, 'failure': type(exc).__name__, 'cleanup': 'UNKNOWN'}
    # A killed child may have persisted a completed/partial witness. Never erase,
    # restart, infer missing counters, or synthesize a calendar finish from logs.
    result = {'schema': 'polar.calendar-host-result/1', 'status': 'FAILED_UNFINALIZED',
              'action': admission['action'], 'process': process, 'hosting_path': parent,
              'refund': False, 'automatic_retry': False, 'export_bytes': 0,
              'scientific_frontier': 'UNKNOWN_USE_DURABLE_CALENDAR_WITNESSES',
              'physical_certification': 'SUPPLIED_SRE_PREREQUISITE_NOT_MEASURED_HERE'}
    if process['exit_code'] == 0 and process['failure'] is None and process['cleanup'] == 'COMPLETE':
        try:
            output = decode(read_file(root, parent + '/console.log', bounds['output_bytes']))
            success = type(output) is dict and (
                output.get('status') == 'SUCCESS' if admission['action'] == 'ORIGINAL' else
                output.get('schema') == 'polar.calendar-study-preflight/1' and
                output.get('source_values_read') == 0 and output.get('scientific_starts') == 0 and
                output.get('strategy_execution') == 'NOT_RUN')
            if success:
                result['status'] = 'SUCCESS' if admission['action'] == 'ORIGINAL' else 'PREFLIGHT_ONLY'
                result['semantic_id'] = output.get('semantic_id')
        except (ValueError, OSError):
            pass
    raw = canonical(result)
    if len(config_raw) + len(admission_raw) + len(raw) > bounds['receipt_bytes']:
        result = {'schema': 'polar.calendar-host-result/1', 'status': 'FAILED_UNFINALIZED',
                  'action': admission['action'], 'hosting_path': parent,
                  'error': 'CALENDAR_HOST_COLLECTION_LIMIT', 'refund': False, 'automatic_retry': False,
                  'scientific_frontier': 'UNKNOWN_USE_DURABLE_CALENDAR_WITNESSES'}
        raw = canonical(result)
    with store.locked():
        store._publish(parent, 'collection', {'record.json': raw}, file_limit=MAX_BYTES)
    return result


def main():
    require(len(sys.argv) == 3, 'CALENDAR_HOST_USAGE')
    # Fixed small metadata files only; no arbitrary executable or export path.
    config_path, admission_path = (Path(v) for v in sys.argv[1:])
    config = decode(read_file(config_path.parent, config_path.name, MAX_BYTES))
    admission = decode(read_file(admission_path.parent, admission_path.name, MAX_BYTES))
    result = run(Path(os.environ.get('POLAR_ARTIFACT_ROOT', '/data/artifacts')), config, admission)
    print(canonical({k: result[k] for k in ('status', 'action', 'hosting_path')}).decode())
    if result['status'] == 'FAILED_UNFINALIZED':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
