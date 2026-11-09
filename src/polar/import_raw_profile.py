"""Versioned finite raw-SIP scopes. Hash pins are metadata, never private jobs."""
from .import_contract import require, exact, decode, sha

AGGREGATE_ADAPTER = 'alpaca-raw-sip-remaining/1'
AGGREGATE_SHA = 'c687eb3b3b976b4ec68cf0019137110f514adaf2fe14a88d75ba1fa22a7d1c15'
JOBS_SHA = '62ad45b2e8ffbc63af029ad28657c4c823340e2d0d0f31294c6c09449d467cd5'
CATALOG_SHA = '9ede957d6d949f994cb9b95d9a6be62e8a4fd901df054cc78f0e97a49f95e803'
AGGREGATE_POLICY = {
    'schema': 'polar.raw-sip-policy/2', 'basis': 'INTERNAL_REMAINING_AGGREGATE_V1',
    'jobs': 3490, 'gets': 6980, 'pages': 2, 'body_bytes': 1048576,
    'total_bytes': 536870912, 'wall_seconds': 10800, 'spacing_seconds': 1,
    'request_seconds': 45, 'retries': 0, 'redirects': False,
    'additional_bytes': 20*1024**3, 'partition_bytes': 16*1024**2,
    'materialization_reserve_seconds': 300,
    'terminal_reserve_bytes': 256*1024**2,
}


def aggregate_unit(value, fixture):
    """Select only the declared remaining list, never an arbitrary larger roster."""
    from .import_service import bound_file
    from .import_raw_sip import UNIT_SHA
    exact(value, ('schema', 'adapter', 'mode', 'aggregate_ref', 'jobs_ref', 'seed_refs'))
    require(value['schema'] == 'polar.raw-sip-aggregate-config/1'
            and value['adapter'] == AGGREGATE_ADAPTER, 'IMPORT_POLICY_MISMATCH')
    raw = bound_file(value['aggregate_ref']); jobs_raw = bound_file(value['jobs_ref'])
    spec = decode(raw)
    if not fixture:
        require(sha(raw) == AGGREGATE_SHA and sha(jobs_raw) == JOBS_SHA,
                'IMPORT_SCOPE_MISMATCH')
        require(spec['completed_unit']['sha256'] == UNIT_SHA
                and spec['catalog']['sha256'] == CATALOG_SHA
                and spec['remaining_jobs']['sha256'] == JOBS_SHA,
                'IMPORT_SCOPE_MISMATCH')
    jobs = [decode(line) for line in jobs_raw.splitlines() if line.strip()]
    require(0 < len(jobs) <= AGGREGATE_POLICY['jobs']
            and (fixture or len(jobs) == AGGREGATE_POLICY['jobs']), 'IMPORT_SCOPE_MISMATCH')
    require(all(type(j) is dict and type(j.get('population_record_id')) is str
                and type(j.get('job_id')) is str for j in jobs), 'IMPORT_SCOPE_MISMATCH')
    require(len({j['population_record_id'] for j in jobs}) == len(jobs)
            and len({j['job_id'] for j in jobs}) == len(jobs), 'IMPORT_DUPLICATE_JOB')
    # Credentials remain a reference only. A provider operation must separately
    # bind the existing first-unit metadata and the actual operation authority.
    return {'jobs': jobs, 'aggregate': spec, 'lineage': spec.get('counter_lineage'),
            'scope_sha256': sha(raw), 'jobs_sha256': sha(jobs_raw)}
