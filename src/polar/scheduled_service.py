"""Scheduled no-fit operations inside ReferenceResearchService and its existing store."""
import importlib.metadata
import io
import os
from pathlib import Path
import platform
import re
import sys
import time
import uuid
from zoneinfo import ZoneInfo

from .ci_research import require
from .ci_research_service import root_identity, bounded_native
from .gym_contract import canonical, sha, read_ref, decode
from .gym_service import code_binding
from .history_bundle import read_file
from .research_reference import load_reference, pinned_bytes, reference_schedule
from .reference_projection import public_reference
from .scheduled_policy import profile_value, calendar_value, plan_phase, evaluate_policy
from .scheduled_diagnostics import diagnose

CONFIG_SCHEMA = 'polar.scheduled-reference-config/1'
SEMANTIC = 'scheduled-reference-experiment-'
MEMBERS = {'profile.json', 'calendar.json', 'phases.json', 'diagnostics.json', 'bindings.json'}


def binding(config):
    return {k: v for k, v in config.items() if k != 'execution_authority_ref'}


def config_from_seed(seed):
    def ref(key):
        path = Path(seed[key]); require(path.is_absolute(), 'SCHEDULED_SEED_PATH')
        raw = read_file(path.parent, path.name, 32*1024**2)
        return {'path': str(path), 'sha256': sha(raw), 'bytes': len(raw)}
    return {'schema': CONFIG_SCHEMA, 'namespace': seed['namespace'],
            **{k + '_ref': ref(k + '_path') for k in ('profile', 'protocol', 'input', 'calendar', 'timezone')},
            'code': code_binding(), 'code_revision': seed['code_revision'],
            'runtime_image_id': seed['runtime_image_id'], 'candidate_id': seed['candidate_id'],
            'experiment_id': seed['experiment_id'],
            'execution_authority_ref': ref('execution_authority_path') if seed.get('execution_authority_path') else None,
            'artifact_root_identity': root_identity(Path(os.environ.get('POLAR_ARTIFACT_ROOT', '/data/artifacts')))}


def prepare(service, config, *, load_prices=True):
    fields = {'schema', 'namespace', 'profile_ref', 'protocol_ref', 'input_ref', 'calendar_ref', 'timezone_ref',
              'code', 'code_revision', 'runtime_image_id', 'candidate_id', 'experiment_id',
              'execution_authority_ref', 'artifact_root_identity'}
    require(type(config) is dict and set(config) == fields and config['schema'] == CONFIG_SCHEMA and
            config['namespace'] in ('INVENTED', 'RETAINED'), 'SCHEDULED_CONFIG_SCHEMA')
    require(config['artifact_root_identity'] == root_identity(service.store.root), 'PERSISTENT_ARTIFACT_ROOT_IDENTITY')
    require(config['code'] == code_binding() and re.fullmatch('[a-f0-9]{40}', config['code_revision']) and
            re.fullmatch('sha256:[a-f0-9]{64}', config['runtime_image_id']), 'SCHEDULED_CODE_RUNTIME')
    profile = profile_value(decode(read_ref(config['profile_ref'])))
    protocol = read_ref(config['protocol_ref']); calendar_raw = read_ref(config['calendar_ref'])
    tz_raw = read_ref(config['timezone_ref'])
    require(profile['protocol_sha256'] == sha(protocol) and
            profile['input_sha256'] == config['input_ref']['sha256'] and
            profile['calendar_sha256'] == sha(calendar_raw) and profile['timezone_sha256'] == sha(tz_raw), 'SCHEDULED_PROFILE_PINS')
    manifest = decode(read_ref(config['input_ref'])); calendar = decode(calendar_raw)
    require(manifest['schema'] == 'polar.synthetic-reference-source-input/1' and
            calendar['source_schedule']['sha256'] == manifest['schedule']['sha256'], 'SCHEDULED_SOURCE_CALENDAR')
    if config['namespace'] == 'INVENTED':
        require(str(manifest.get('parent_dataset_revision', '')).startswith('INVENTED-') and
                manifest.get('rights') == 'INVENTED_PUBLIC_TEST' and manifest.get('provenance') ==
                {'kind': 'DETERMINISTIC_INVENTED_FIXTURE', 'producer': 'polar-public-tests', 'source_payloads': 'NONE'},
                'SCHEDULED_INVENTED_RIGHTS')
        from .reference_service import INPUT
        require(config['input_ref']['sha256'] != INPUT, 'RETAINED_AS_INVENTED_FORBIDDEN')
    else:
        require(platform.system() == 'Linux' and platform.machine() in ('aarch64', 'x86_64') and
                platform.python_version() == '3.13.18' and os.environ.get('POLAR_RUNTIME_IMAGE_ID') == config['runtime_image_id'] and
                sys.pycache_prefix is not None and os.environ.get('PYTHONDONTWRITEBYTECODE') == '1', 'SCHEDULED_ACTUAL_RUNTIME')
        require(manifest['rights'] == 'SOLE_OWNER_PRIVATE_NONCOMMERCIAL_NO_PUBLIC_DATA_OR_DATA_CONTAINING_RESULT_REDISTRIBUTION', 'SCHEDULED_RETAINED_RIGHTS')
        for package, version in [('nautilus-trader', '1.231.0'), ('numpy', '2.2.6'), ('threadpoolctl', '3.6.0')]:
            require(importlib.metadata.version(package) == version, 'SCHEDULED_RUNTIME_VERSION')
    schedule, days = reference_schedule(decode(pinned_bytes(manifest['schedule'])))
    require(manifest['symbols'] == profile['symbols'], 'SCHEDULED_PROFILE_SYMBOLS')
    grids = calendar_value(calendar, schedule)
    require(all(days.index(g['initial']) >= profile['policy']['lookback'] for g in grids.values()), 'SCHEDULED_WARMUP')
    tz = ZoneInfo.from_file(io.BytesIO(tz_raw), key='America/New_York')
    # Preparation performs no features/weights/policy decision or native operation.
    market = load_reference(config['input_ref']) if load_prices else None
    return profile, calendar, schedule, grids, tz, market


def preflight(service, config):
    p, _, _, grids, _, _ = prepare(service, config)
    return {'schema': 'polar.scheduled-reference-preflight/1', 'status': 'READY_FOR_BOUND_OPERATION',
            'operation_binding_sha256': sha(canonical(binding(config))), 'policy_execution': 'NOT_RUN',
            'scientific_starts': 0, 'fit_calls': 0, 'predict_calls': 0,
            'expected_native_accounts': len(p['legs'])*len(grids)}


def authority_for(service, config, profile, grids):
    if config['namespace'] == 'INVENTED':
        return None
    authority = decode(read_ref(config['execution_authority_ref']))
    require(authority.get('schema') == 'polar.scheduled-reference-operation/1' and authority.get('action') == 'ORIGINAL' and
            authority.get('binding_sha256') == sha(canonical(binding(config))) and
            authority.get('allowed_fit_calls') == 0 and authority.get('allowed_predict_calls') == 0 and
            authority.get('allowed_native_accounts') == len(profile['legs'])*len(grids), 'SCHEDULED_OPERATION_NOT_BOUND')
    method = decode(read_ref(authority['method_ref']))
    require(method.get('schema') == 'polar.prospective-method-disposition/1' and method.get('method_verdict') == 'PASS' and
            method.get('protocol', {}).get('sha256') == config['protocol_ref']['sha256'] and
            method.get('candidate_id') == config['candidate_id'], 'SCHEDULED_METHOD_BINDING')
    candidate = decode(read_ref(authority['candidate_ref']))
    require(candidate.get('schema') == 'polar.native-hypothesis-reservation/1' and candidate.get('state') == 'RESERVED' and
            candidate.get('candidate_id') == config['candidate_id'] and
            candidate.get('experiment_registration_id') == config['experiment_id'], 'SCHEDULED_CANDIDATE_BINDING')
    qualification = __import__('json').loads(read_ref(authority['qualification_ref']))
    require(qualification.get('schema') == 'polar.ci-result/1' and qualification.get('status') == 'PASS' and
            qualification.get('candidate_sha') == config['code_revision'] and
            any(t in ('tests', 'tests/test_scheduled_service.py') for t in qualification.get('selection', [])), 'SCHEDULED_TECHNICAL_BINDING')
    return authority


def public_config(config, profile):
    return {'protocol_id': profile['protocol_id'], 'primary_strategy': profile['primary_strategy'],
            'primary_benchmark': profile['primary_benchmark'],
            **{key: profile[key] for key in ('question_label', 'question_summary', 'clock_description', 'partition_description')},
            'additional_limitations': [tuple(x) for x in profile['additional_limitations']],
            'bindings': {'protocol_id': profile['protocol_id'], 'protocol_sha256': config['protocol_ref']['sha256'],
                'data_revision': 'selected-' + config['input_ref']['sha256'], 'data_sha256': config['input_ref']['sha256'],
                'code_revision': config['code_revision'], 'evaluator_revision': config['code_revision'],
                'runtime_id': config['runtime_image_id'], 'producer_id': 'polar-scheduled-reference',
                'candidate_id': config['candidate_id'], 'experiment_id': config['experiment_id']},
            'provenance': [{'role': 'scheduled_policy', 'id': profile['protocol_id'], 'sha256': config['profile_ref']['sha256']},
                           {'role': 'reference_input', 'id': 'source-projection', 'sha256': config['input_ref']['sha256']},
                           {'role': 'calendar_contract', 'id': 'calendar-contract', 'sha256': config['calendar_ref']['sha256']}],
            'evidence_level': 'RETAINED_DESCRIPTIVE' if config['namespace'] == 'RETAINED' else 'INVENTED_CONTROL'}


def run(service, config):
    profile, calendar, schedule, grids, tz, _ = prepare(service, config, load_prices=False)
    authority = authority_for(service, config, profile, grids)
    # Stable family across source repair/code revisions; an unsuccessful start is never refunded.
    family = sha(canonical({'protocol_id': profile['protocol_id'], 'input': config['input_ref']['sha256'], 'namespace': config['namespace']}))
    parent = 'scheduled-reference-attempts/' + family; aid = str(uuid.uuid4())
    with service.store.locked():
        directory = service.store.root/parent
        prior = sorted(p.name for p in directory.iterdir()) if directory.exists() else []
        require(not directory.is_symlink() and not prior, 'SCHEDULED_ORIGINAL_ALREADY_RECORDED')
        if authority is not None:
            require(authority.get('expected_prior_attempts') == prior, 'SCHEDULED_ATTEMPT_HISTORY')
        service.store._publish(parent, aid, {'start.json': canonical({'schema': 'polar.scheduled-reference-start/1',
            'attempt_id': aid, 'status': 'FIRST_START_CONSERVATIVE_DEBIT', 'binding': binding(config),
            'fit_calls': 0, 'predict_calls': 0, 'model_calls': 0, 'started_ns': time.time_ns()}),
            'config.json': canonical(config), 'authority.json': canonical(authority)})
    completed = 0
    try:
        market = load_reference(config['input_ref'])
        phases = {}; diagnostics = {}
        for phase, grid in grids.items():
            plan = plan_phase(market, profile, grid, tz)
            simulation = bounded_native(plan); completed += len(simulation['legs'])
            evaluation = evaluate_policy(simulation, profile, phase)
            diagnostics[phase] = {t['id']: diagnose(t, schedule,
                subperiods=profile['subperiods'] if phase == 'FINAL' else ()) for t in simulation['legs']}
            phases[phase] = {'plan': plan, 'simulation': simulation, 'evaluation': evaluation}
            with service.store.locked():
                service.store._publish(parent+'/'+aid+'/phases', phase,
                    {'phase.json': canonical(phases[phase]), 'diagnostics.json': canonical(diagnostics[phase])}, file_limit=32*1024**2)
        saved_calendar = {**calendar, 'source_schedule_rows': schedule}
        files = {'profile.json': canonical(profile), 'calendar.json': canonical(saved_calendar), 'phases.json': canonical(phases),
                 'diagnostics.json': canonical(diagnostics), 'bindings.json': canonical(binding(config))}
        manifest = {'schema': 'polar.scheduled-reference-semantic-manifest/1',
                    'files': {n: {'sha256': sha(b), 'bytes': len(b)} for n, b in files.items()}}
        raw = canonical(manifest); sid = SEMANTIC+sha(raw)
        with service.store.locked():
            service.store._publish('reference-research-experiments', sid, {**files, 'manifest.json': raw}, file_limit=32*1024**2)
        publications = {}
        for phase, data in phases.items():
            record = public_reference(public_config(config, profile), data['simulation'], data['evaluation'],
                                      semantic_id=sid, semantic_hash=sha(raw), phase=phase)
            # Display labels come from the bound profile, never a per-run UI branch.
            for series in record['series']:
                series['label'] = next(x['label'] for x in profile['legs'] if x['id'] == series['id'])
            project_diagnostics(record, diagnostics[phase])
            publications[phase] = service.results.publish(record)
        finish = {'status': 'SUCCESS', 'attempt_id': aid, 'semantic_id': sid, 'results': publications,
                  'fit_calls': 0, 'predict_calls': 0, 'model_calls': 0, 'native_accounts': completed,
                  'financial_acceptance': 'NOT_REVIEWED', 'finished_ns': time.time_ns()}
    except BaseException as exc:
        finish = {'status': 'FAILED_UNFINALIZED', 'attempt_id': aid, 'error': str(exc)[:240],
                  'fit_calls': 0, 'predict_calls': 0, 'model_calls': 0, 'completed_native_accounts': completed,
                  'refund': False, 'automatic_retry': False, 'finished_ns': time.time_ns()}
        with service.store.locked():
            service.store._publish(parent+'/'+aid, 'finish', {'record.json': canonical(finish),
                'diagnostics.json': canonical(getattr(exc, 'events', []))}, file_limit=32*1024**2)
        raise
    with service.store.locked():
        service.store._publish(parent+'/'+aid, 'finish', {'record.json': canonical(finish)})
    return finish


def recompute(service, semantic_id):
    require(re.fullmatch(SEMANTIC+'[a-f0-9]{64}', semantic_id), 'SCHEDULED_SEMANTIC_ID')
    parent = 'reference-research-experiments/' + semantic_id
    raw = read_file(service.store.root, parent+'/manifest.json', 32*1024**2)
    require(semantic_id == SEMANTIC+sha(raw), 'SCHEDULED_MANIFEST_HASH')
    manifest = decode(raw)
    require(manifest['schema'] == 'polar.scheduled-reference-semantic-manifest/1' and set(manifest['files']) == MEMBERS, 'SCHEDULED_MEMBER_SET')
    files = {}
    for name, pin in manifest['files'].items():
        body = read_file(service.store.root, parent+'/'+name, 32*1024**2)
        require(len(body) == pin['bytes'] and sha(body) == pin['sha256'], 'SCHEDULED_MEMBER_HASH')
        files[name] = decode(body)
    profile = profile_value(files['profile.json'])
    require(files['bindings.json']['code'] == code_binding(), 'SCHEDULED_REPRODUCTION_CODE_BINDING')
    expected_diagnostics = {}
    # Only saved output arrays are used; no source, policy feature, model or native call.
    calendar = files['calendar.json']
    for phase, data in files['phases.json'].items():
        require(canonical(evaluate_policy(data['simulation'], profile, phase)) == canonical(data['evaluation']), 'SCHEDULED_RECOMPUTE_MISMATCH')
        schedule = calendar['source_schedule_rows']
        expected_diagnostics[phase] = {t['id']: diagnose(t, schedule,
            subperiods=profile['subperiods'] if phase == 'FINAL' else ()) for t in data['simulation']['legs']}
    require(canonical(expected_diagnostics) == canonical(files['diagnostics.json']), 'SCHEDULED_DIAGNOSTIC_RECOMPUTE')
    return {'status': 'REPRODUCED', 'semantic_id': semantic_id, 'fit_calls': 0, 'model_calls': 0,
            'predict_calls': 0, 'native_calls': 0, 'store_writes': 0}


def project_diagnostics(record, diagnostics):
    """Use the existing scalar metrics/limitations wire, no per-run UI or new field."""
    def at(value, path):
        for key in path:
            if not isinstance(value, dict) or key not in value:
                return {'value': None, 'status': 'UNAVAILABLE', 'reason': 'SAVED_DIAGNOSTIC_UNAVAILABLE'}
            value = value[key]
        if isinstance(value, int): return {'value': str(value), 'status': 'OK', 'reason': None}
        if isinstance(value, dict) and 'value' in value:
            return {k: value[k] for k in ('value', 'status', 'reason')}
        return {'value': None, 'status': 'UNAVAILABLE', 'reason': (value.get('reason') or 'SAVED_DIAGNOSTIC_UNAVAILABLE') if isinstance(value, dict) else 'SAVED_DIAGNOSTIC_UNAVAILABLE'}
    fields = [('empirical_tail_fraction', 'Empirical lower-tail sample fraction', 'fraction', ('daily_tail', 'actual_tail_fraction')),
              ('empirical_tail_mean', 'Empirical 5% lower-tail mean daily return', 'fraction', ('daily_tail', 'lower_tail_mean_return')),
              ('empirical_tail_threshold', 'Empirical 5% lower daily-return threshold', 'fraction', ('daily_tail', 'lower_return_threshold')),
              ('empirical_ES_loss', 'Empirical 5% expected shortfall (signed loss)', 'fraction', ('daily_tail', 'expected_shortfall_loss')),
              ('tail_sample_count', 'Lower-tail observed daily intervals', 'count', ('daily_tail', 'k')),
              ('time_underwater', 'Observed close intervals below running high', 'fraction', ('drawdown', 'time_underwater_fraction')),
              ('worst_full_month', 'Worst complete calendar-month net return', 'fraction', ('calendar_months', 'worst_full_month', 'net_return')),
              ('complete_month_count', 'Observed complete calendar months', 'count', ('calendar_months', 'complete_count'))]
    for h in ('1', '21', '63'):
        fields.append(('worst_'+h+'_interval_return', 'Worst '+h+'-interval cumulative net return', 'fraction', ('worst_horizons', h, 'net_return')))
    for identity, label, unit, path in fields:
        record['metrics'].append({'id': identity, 'label': label, 'unit': unit,
                                  'values': {s['id']: at(diagnostics[s['id']], path) for s in record['series']}})
    subperiod_count = max((len(x.get('subperiods', [])) for x in diagnostics.values()), default=0)
    for index in range(subperiod_count):
        for section, key, unit in [('metrics', 'net_total_return', 'fraction'), ('metrics', 'sharpe_252_rf0', 'ratio'),
                                  ('metrics', 'max_drawdown', 'fraction'), ('costs', 'total_fee_usd', 'USD'),
                                  ('costs', 'gross_exact_notional_usd', 'USD'), ('costs', 'gross_settled_notional_usd', 'USD'),
                                  ('costs', 'positive_fill_count', 'count'), ('costs', 'gross_notional_over_initial', 'fraction')]:
            values = {}
            for s in record['series']:
                segments = diagnostics[s['id']].get('subperiods', [])
                values[s['id']] = at(segments[index], (section, key)) if index < len(segments) else {
                    'value': None, 'status': 'UNAVAILABLE', 'reason': 'SUBPERIOD_UNAVAILABLE'}
            record['metrics'].append({'id': f'SEGMENT_{index}_{key}', 'label': f'Saved subperiod {index+1}: '+key.replace('_', ' '), 'unit': unit, 'values': values})
    for series in record['series']:
        d = diagnostics[series['id']]; episode = d.get('drawdown', {}); months = d.get('calendar_months', {})
        point = lambda key: (episode.get(key) or {}).get('date', 'not applicable')
        text = (f"{series['label']}: saved close drawdown {episode.get('status', 'UNAVAILABLE')}; "
                f"peak {point('peak')}, trough {point('trough')}, recovery {point('recovery')}. "
                f"Peak-to-trough intervals {episode.get('peak_to_trough_intervals')}; "
                f"peak-to-recovery {episode.get('peak_to_recovery_intervals')}; "
                f"unrecovered peak-to-terminal censor {episode.get('censored_peak_to_terminal_intervals')}. "
                f"Complete months {months.get('complete_count')}, partial months {months.get('partial_count')}. "
                'Finite saved-ledger descriptions; no future tail or recovery guarantee.')
        record['limitations'].append({'code': 'SAVED_RISK_'+series['id'], 'text': text[:1000], 'scope': series['label']})
        for index, segment in enumerate(d.get('subperiods', [])):
            record['limitations'].append({'code': f'SEGMENT_{index}_'+series['id'], 'scope': series['label'],
                'text': (f"Saved subperiod {index+1}: {segment.get('first_return_date')} through {segment.get('last_return_date')}, "
                         f"preceding-close anchor {segment.get('initial_date')}; {segment.get('intervals')} returns. "
                         f"Normalization initial NAV cents {segment.get('costs', {}).get('normalization_initial_nav_cents')}. "
                         'Carried holdings and cumulative end-minus-anchor costs; no reset, refit or extra liquidation.')})
