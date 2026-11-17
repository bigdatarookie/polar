"""Closed two-phase private FOMC operation on the existing store and worker.

No retained hosting is inferred from a file, environment variable or source
acceptance. The actual trusted guard remains mandatory before FIRST_START.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import io, os, platform, re, sys, time, uuid
from zoneinfo import ZoneInfo, TZPATH

from .ci_research import require
from .gym_contract import canonical, decode, sha, read_ref, MAX_BYTES
from .gym_service import code_binding
from .ci_research_service import root_identity, bounded_native
from .research_reference import load_reference, pinned_bytes, reference_schedule
from .history_bundle import read_file
from .event_native_witness import encode, restore, publish_witnesses, verify_stored_witnesses
from .fomc_calendar import (QUESTION, POLICY_SHA, CONTRACT_SHA, PROPOSAL_SHA, INDEX_SHA, PHASES,
                            geometry, plan_phase, evaluate_phase, author_policy, ns)

CONFIG = 'polar.fomc-calendar-config/1'
SEED = 'polar.fomc-calendar-seed/1'
SEMANTIC = 'fomc-calendar-experiment-'
REFS = ('input', 'index', 'protocol', 'contract', 'roles', 'timezone', 'geometry', 'method', 'qualification', 'resources', 'clock')
SEED_FIELDS = {'schema', 'namespace', 'question_id', 'candidate_id', 'experiment_id',
               'consumer_task', 'source_admission_ref', *(k+'_ref' for k in REFS)}
CONFIG_FIELDS = SEED_FIELDS | {'code', 'code_revision', 'runtime_image_id', 'artifact_root_identity'}


@dataclass(frozen=True)
class FomcRequest:
    plan: object
    calendar: dict
    phase: str
    role_rows: list


def config_from_seed(seed, root):
    require(type(seed) is dict and set(seed) == SEED_FIELDS and seed['schema'] == SEED and
            seed['namespace'] in ('INVENTED', 'RETAINED') and seed['question_id'] == QUESTION,
            'FOMC_CLOSED_SEED')
    from .candidate_binding import loaded_revision
    from .offline_author_binding import pair_runtime
    return {**seed, 'schema': CONFIG, 'code': code_binding(), 'code_revision': loaded_revision(),
            'runtime_image_id': pair_runtime(seed['namespace']), 'artifact_root_identity': root_identity(root)}


def binding(config):
    return {k: v for k, v in config.items() if k != 'source_admission_ref'}


def family(config):
    return sha(canonical({'question': QUESTION, 'candidate_id': config['candidate_id'],
                          'experiment_id': config['experiment_id'], 'namespace': config['namespace']}))


def prepare(service, config):
    require(type(config) is dict and set(config) == CONFIG_FIELDS and config['schema'] == CONFIG and
            config['question_id'] == QUESTION and config['namespace'] in ('INVENTED', 'RETAINED'), 'FOMC_CONFIG_SCHEMA')
    require(all(type(config[k]) is str and config[k] for k in ('candidate_id', 'experiment_id', 'consumer_task')),
            'FOMC_CONFIG_IDENTITIES')
    require(config['code'] == code_binding() and config['artifact_root_identity'] == root_identity(service.store.root),
            'FOMC_CURRENT_CODE_ROOT')
    from .offline_author_binding import pair_runtime
    require(config['runtime_image_id'] == pair_runtime(config['namespace']), 'FOMC_CURRENT_RUNTIME')
    native = None
    if config['namespace'] == 'RETAINED':
        require(platform.system() == 'Linux' and platform.python_version() == '3.13.18' and
                os.getuid() == 10001 and sys.pycache_prefix is not None and
                os.environ.get('PYTHONDONTWRITEBYTECODE') == '1', 'FOMC_RETAINED_RUNTIME')
        from .fomc_source import authorize
        native = authorize(config, service.store.root)
    else:
        require(config['source_admission_ref'] is None and config['candidate_id'].startswith('INVENTED'),
                'FOMC_INVENTED_NAMESPACE')
    # Actual native custody/scope precedes even caller-selected metadata refs.
    raw = {k: read_ref(config[k+'_ref']) for k in REFS}
    require(sha(raw['contract']) == CONTRACT_SHA and sha(raw['protocol']) == PROPOSAL_SHA,
            'FOMC_FROZEN_METHOD')
    author_policy()
    manifest = decode(raw['input']); roles = decode(raw['roles'])
    require(manifest['schema'] == 'polar.synthetic-reference-source-input/2' and manifest['symbols'] == ['BIL', 'VTI'] and
            manifest['quote_basis'] == 'VENDOR_ALL_ADJUSTED_REFERENCE_CLOSE' and
            manifest['unit_type'] == 'SYNTHETIC_REFERENCE_UNIT_NOT_RAW_SHARE' and
            manifest['double_action_policy'] == 'NO_ADDITIONAL_SPLIT_DIVIDEND_CREDIT_IN_REFERENCE_UNIT_MODEL', 'FOMC_INPUT_BASIS')
    invented = config['namespace'] == 'INVENTED'
    require(manifest['rights'] == ('INVENTED_PUBLIC_TEST' if invented else
            'SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION'), 'FOMC_INPUT_RIGHTS')
    require((manifest.get('provenance') == {'kind': 'DETERMINISTIC_INVENTED_FIXTURE',
            'producer': 'polar-public-tests', 'source_payloads': 'NONE'}) == invented, 'FOMC_SOURCE_NAMESPACE')
    schedule, days = reference_schedule(decode(pinned_bytes(manifest['schedule'])))
    require(set(roles) == {'schema', 'input_ref', 'phase_bounds', 'phases'} and
            roles['schema'] == 'polar.fomc-source-roles/1' and roles['input_ref'] == config['input_ref'] and
            set(roles['phases']) == {'VALIDATION', 'FINAL'} and set(roles['phase_bounds']) == {'VALIDATION', 'FINAL'},
            'FOMC_SOURCE_ROLES')
    phases = roles['phase_bounds']
    if not invented:
        require(canonical(phases) == canonical(PHASES) and sha(raw['index']) == INDEX_SHA, 'FOMC_ACTUAL_INDEX_PHASES')
    for phase, bounds in phases.items():
        require(type(bounds) in (list, tuple) and len(bounds) == 2 and bounds[0] < bounds[1] and
                all(d in days for d in bounds), 'FOMC_PHASE_BOUNDS')
        rows = roles['phases'][phase]
        wanted = [d for d in days if bounds[0] <= d <= bounds[1]]
        for symbol in ('BIL', 'VTI'):
            selected = [r for r in rows if r['symbol'] == symbol]
            require([r['date'] for r in selected if r['role'] == 'NAV'] == wanted and
                    [r['date'] for r in selected] == [d for d in days if d <= bounds[1]], 'FOMC_FULL_PREFIX_ROLES')
        require(len({r['source_id'] for r in rows}) == len(rows), 'FOMC_SOURCE_LOCATOR_CENSUS')
        for row in rows:
            require(set(row) == {'symbol', 'date', 'close_ns', 'available_ns', 'source_id', 'role'} and
                    row['symbol'] in ('BIL', 'VTI') and row['date'] in days and
                    row['close_ns'] == ns(__import__('datetime').datetime.fromisoformat(
                        schedule[days.index(row['date'])]['reference_close_utc'].replace('Z', '+00:00'))) and
                    (row['available_ns'] is None or type(row['available_ns']) is int and row['available_ns'] >= row['close_ns']) and
                    row['source_id'] == manifest['parent_dataset_revision']+'/'+row['symbol']+'/'+row['date'] and
                    row['role'] == ('NAV' if row['date'] in wanted else
                         'VTI_WARMUP_CANDIDATE' if row['symbol'] == 'VTI' else 'BIL_UNUSED_WARMUP_CONTEXT'),
                    'FOMC_CAUSAL_SOURCE_ROLE')
    if not invented:
        actual = next((Path(p)/'America/New_York' for p in TZPATH if (Path(p)/'America/New_York').is_file()), None)
        require(actual is not None and actual.read_bytes() == raw['timezone'], 'FOMC_ACTUAL_TIMEZONE_BYTES')
    ny = ZoneInfo.from_file(io.BytesIO(raw['timezone']), key='America/New_York')
    index = decode(raw['index'])
    source_rows = index['completeness_and_exclusions']['event_rows']
    calendar = geometry(source_rows, schedule, phases, ny)
    require(decode(raw['geometry']) == calendar, 'FOMC_RUNTIME_GEOMETRY_EQUALITY')
    for key in ('method', 'qualification'):
        value = decode(raw[key])
        require(value.get('schema') == 'polar.fomc-'+key+'/1' and value.get('question_id') == QUESTION and
                value.get('policy_sha256') == POLICY_SHA and value.get('contract_sha256') == CONTRACT_SHA and
                value.get('status') == ('ACCEPTED_WITH_LIMITS' if key == 'method' else 'PASS') and
                value.get('namespace') == config['namespace'], 'FOMC_'+key.upper()+'_BINDING')
    clock = decode(raw['clock'])
    require(type(clock) is dict and set(clock) == {'schema', 'namespace', 'basis', 'roles_sha256',
            'assumption_ref', 'source_fit_ref'} and clock['schema'] == 'polar.fomc-quote-clock/1' and
            clock['namespace'] == config['namespace'] and clock['roles_sha256'] == config['roles_ref']['sha256'] and
            clock['basis'] in ('UNKNOWN', 'INVENTED', 'EXPLICIT_AUTHORED_SYNTHETIC_ASSUMPTION'), 'FOMC_QUOTE_CLOCK')
    if clock['basis'] == 'UNKNOWN':
        require(clock['assumption_ref'] is None and all(r['available_ns'] is None for rows in
                roles['phases'].values() for r in rows), 'FOMC_UNKNOWN_CLOCK_NOT_MANUFACTURED')
    elif clock['basis'] == 'INVENTED':
        require(invented and clock['assumption_ref'] is None, 'FOMC_INVENTED_CLOCK_SCOPE')
    else:
        assumption = decode(read_ref(clock['assumption_ref']))
        fit = decode(read_ref(clock['source_fit_ref']))
        require(not invented and assumption.get('schema') == 'polar.fomc-explicit-quote-clock-assumption/1' and
                assumption.get('question_id') == QUESTION and assumption.get('roles_sha256') == clock['roles_sha256'] and
                assumption.get('historical_K') == 'UNKNOWN' and assumption.get('basis') == clock['basis'] and
                fit.get('quote_clock_assumption_sha256') == clock['assumption_ref']['sha256'] and
                fit.get('question_id') == QUESTION and fit.get('status') == 'ACCEPTED_WITH_LIMITS',
                'FOMC_EXPLICIT_CLOCK_ASSUMPTION_QUALIFICATION')
    resources = decode(raw['resources'])
    require(type(resources) is dict and set(resources) == {'schema', 'namespace', 'limits'} and
            resources['schema'] == 'polar.fomc-resources/1' and resources['namespace'] == config['namespace'] and
            set(resources['limits']) == {'native_wall_seconds', 'stored_wall_seconds', 'cleanup_seconds',
                'remaining_family_wall_seconds', 'storage_upper_bound_bytes'} and
            all(type(v) is int and v > 0 for v in resources['limits'].values()), 'FOMC_FINITE_RESOURCES')
    limits = resources['limits']
    require(limits['native_wall_seconds'] <= 300 and
            2*limits['native_wall_seconds']+limits['stored_wall_seconds']+limits['cleanup_seconds'] <=
                limits['remaining_family_wall_seconds'] and
            limits['storage_upper_bound_bytes'] <= service.store.limit-service.store.used(), 'FOMC_PROSPECTIVE_RESOURCES')
    return {'calendar': calendar, 'roles': roles, 'manifest': manifest, 'native': native, 'limits': limits, 'quote_clock': clock}


def preflight(service, config):
    value = prepare(service, config)
    directory = service.store.root/'scheduled-reference-attempts'/family(config)
    require(not directory.is_symlink() and (not directory.exists() or not any(directory.iterdir())), 'FOMC_ORIGINAL_ALREADY_RECORDED')
    return {'schema': 'polar.fomc-preflight/1', 'status': 'METADATA_VALID_NOT_RUNNABLE_HOST_GUARD_UNAVAILABLE'
            if config['namespace'] == 'RETAINED' else 'INVENTED_TECHNICAL_CONTROL_ONLY',
            'binding_sha256': sha(canonical(binding(config))), 'geometry_sha256': sha(canonical(value['calendar'])),
            'source_values_read': 0, 'native_calls': 0, 'scientific_starts': 0,
            'financial_acceptance': 'NOT_REVIEWED', 'execution_intent_only': True,
            'quote_clock_readiness': 'UNKNOWN' if value['quote_clock']['basis'] == 'UNKNOWN' else 'EXPLICIT_MODEL_ONLY',
            'hosting_readiness': 'FOMC_HOST_TRUSTED_PARENT_CHILD_GUARD_UNAVAILABLE' if config['namespace'] == 'RETAINED' else 'INVENTED_ONLY'}


def produce(request, diagnostics=None):
    from .event_native import simulate_event_component
    component = simulate_event_component(request.plan, diagnostics, preserve_accounts=True)
    evaluation = evaluate_phase(component['accounts'], request.calendar, request.phase, request.role_rows)
    return {'accounts': component['accounts'], 'evaluation': evaluation}


def run(service, config):
    metadata = prepare(service, config)
    require(metadata['quote_clock']['basis'] != 'UNKNOWN', 'FOMC_QUOTE_CLOCK_UNQUALIFIED')
    if config['namespace'] == 'RETAINED':
        # Existing guard is genuinely unavailable; source intent cannot bypass it.
        from .fomc_calendar_hosting import validate_child
        validate_child(service, config)
    from .candidate_binding import loaded_revision
    if config['namespace'] == 'RETAINED':
        require(config['code_revision'] == loaded_revision(), 'FOMC_CURRENT_CANDIDATE')
    family_id = family(config); aid = str(uuid.uuid4()); parent = 'scheduled-reference-attempts/'+family_id
    intent = {'schema': 'polar.fomc-offline-author-binding/1', 'question_id': QUESTION,
              'candidate_sha': config['code_revision'], 'runtime_image_id': config['runtime_image_id'],
              'config_sha256': sha(canonical(binding(config))), 'run_id': aid,
              'scientific_acceptance': 'NOT_REVIEWED', 'execution_intent_only': True}
    with service.store.locked():
        prepare(service, config)
        directory = service.store.root/parent
        require(not directory.is_symlink() and (not directory.exists() or not any(directory.iterdir())), 'FOMC_ORIGINAL_ALREADY_RECORDED')
        service.store._publish(parent, aid, {'start.json': canonical({'schema': 'polar.scheduled-reference-start/1',
            'status': 'FIRST_START_CONSERVATIVE_DEBIT', 'binding': binding(config), 'execution_binding': intent,
            'attempt_id': aid, 'started_ns': time.time_ns()}), 'config.json': canonical(config)})
    phase_graphs = {}; phase_evaluations = {}; events = []
    def diagnostic(event):
        raw = canonical(encode(event))
        with service.store.locked():
            service.store._publish(parent+'/'+aid, 'diagnostic-'+str(len(events)), {'record.json': raw}, file_limit=MAX_BYTES)
        events.append(event.get('phase'))
        if event.get('phase') == 'ACCOUNT_SAVED_WITNESS':
            ref = publish_witnesses(service.store, event['account'])
            return {'phase': event['phase'], 'leg': event['leg'], 'cost_id': event['cost_id'], 'witness_ref': encode(ref)}
        if event.get('phase') == 'ACCOUNT_PARTIAL':
            raw = canonical(encode(event['evidence']))
            with service.store.locked(): service.store._publish(parent+'/'+aid, 'partial-'+sha(raw), {'evidence.json': raw}, file_limit=MAX_BYTES)
            return {'phase': 'ACCOUNT_PARTIAL', 'evidence_sha256': sha(raw)}
        return event
    try:
        market = load_reference(config['input_ref'])  # First value read after FIRST_START.
        for phase, bounds in metadata['roles']['phase_bounds'].items():
            plan = plan_phase(market, metadata['roles']['phases'][phase], metadata['calendar'], phase, bounds,
                              family_id+'/'+phase, metadata['manifest']['parent_dataset_revision'], QUESTION)
            value = bounded_native(FomcRequest(plan, metadata['calendar'], phase, metadata['roles']['phases'][phase]),
                wall_seconds=metadata['limits']['native_wall_seconds'], diagnostics_callback=diagnostic)
            refs = [publish_witnesses(service.store, a) for a in value['accounts']]
            phase_graphs[phase] = encode(refs); phase_evaluations[phase] = encode(value['evaluation'])
        graph = {'schema': 'polar.fomc-private-study/1', 'binding': binding(config), 'execution_binding': intent,
                 'calendar': metadata['calendar'], 'roles': metadata['roles'], 'accounts': phase_graphs,
                 'evaluations': phase_evaluations, 'financial_acceptance': 'NOT_REVIEWED'}
        raw = canonical(graph); sid = SEMANTIC+sha(raw)
        with service.store.locked(): service.store._publish('reference-research-experiments', sid, {'manifest.json': raw}, file_limit=MAX_BYTES)
        finish = {'status': 'SUCCESS', 'attempt_id': aid, 'semantic_id': sid, 'financial_acceptance': 'NOT_REVIEWED'}
    except BaseException as exc:
        finish = {'status': 'FAILED_UNFINALIZED', 'attempt_id': aid, 'error_type': type(exc).__name__,
                  'refund': False, 'automatic_retry': False, 'completed_phases': list(phase_graphs),
                  'durable_native_entries_minimum': events.count('NATIVE_RUN_ENTERED'),
                  'durable_native_completions_minimum': events.count('ACCOUNT_COMPLETED'),
                  'unobserved_frontier': 'UNKNOWN_USE_PARTIAL_WITNESSES'}
        with service.store.locked(): service.store._publish(parent+'/'+aid, 'finish', {'record.json': canonical(finish)}, file_limit=MAX_BYTES)
        raise
    with service.store.locked(): service.store._publish(parent+'/'+aid, 'finish', {'record.json': canonical(finish)}, file_limit=MAX_BYTES)
    return finish


def recompute(service, sid):
    require(type(sid) is str and re.fullmatch(SEMANTIC+'[a-f0-9]{64}', sid), 'FOMC_SEMANTIC_ID')
    raw = read_file(service.store.root, 'reference-research-experiments/'+sid+'/manifest.json', MAX_BYTES)
    require(sid == SEMANTIC+sha(raw), 'FOMC_SAVED_GRAPH_HASH')
    graph = decode(raw)
    require(graph['schema'] == 'polar.fomc-private-study/1' and graph['binding']['code'] == code_binding(), 'FOMC_SAVED_CODE')
    config = {**graph['binding'], 'source_admission_ref': None}
    start = 'scheduled-reference-attempts/'+family(config)+'/'+graph['execution_binding']['run_id']
    finish = decode(read_file(service.store.root, start+'/finish/record.json', MAX_BYTES))
    require(finish['status'] == 'SUCCESS' and finish['semantic_id'] == sid, 'FOMC_SAVED_SUCCESS_ONLY')
    require(set(graph['accounts']) == set(graph['evaluations']) == {'VALIDATION', 'FINAL'}, 'FOMC_SAVED_PHASE_CENSUS')
    for phase, refs in graph['accounts'].items():
        accounts = []
        for ref in restore(refs):
            item = verify_stored_witnesses(service.store.root, ref['id'], ref['context'])
            require(item['immutable_payload_sha256'] == ref['payload_sha256'], 'FOMC_SAVED_WITNESS_HASH')
            accounts.append(item['account'])
        evaluation = evaluate_phase(accounts, graph['calendar'], phase, graph['roles']['phases'][phase])
        require(canonical(encode(evaluation)) == canonical(graph['evaluations'][phase]), 'FOMC_SAVED_EVALUATION')
    return {'status': 'REPRODUCED', 'semantic_id': sid, 'source_reads': 0, 'native_calls': 0,
            'policy_calls': 0, 'writes': 0, 'financial_acceptance': 'NOT_REVIEWED'}
