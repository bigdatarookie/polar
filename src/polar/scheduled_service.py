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
from .scheduled_policy import profile_value, calendar_value, plan_phase, evaluate_policy, gate_accounting, optimization_counts
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
    require(set(profile['symbols']) <= set(manifest['symbols']) if profile['schema'].endswith('/6') else manifest['symbols']==profile['symbols'], 'SCHEDULED_PROFILE_SYMBOLS')
    if profile['schema'].endswith('/6'):
        lo,hi=profile['policy']['calibration'];labels=[d for d in days if lo<=d<=hi]
        require(len(labels)==1259 and labels[0]==lo and labels[-1]==hi and all(hi<g['initial'] for g in calendar['phases'].values()),'SCHEDULED_TEMPORAL_CALIBRATION_GRID')
    require((profile['schema'] == 'polar.scheduled-reference-profile/3') ==
            (calendar.get('schema') == 'polar.daily-gate-policy-calendar/1'), 'SCHEDULED_CALENDAR_POLICY')
    grids = calendar_value(calendar, schedule)
    list(operation_phases(profile, grids))
    history = profile['policy']['window']-1 if profile['schema'] == 'polar.scheduled-reference-profile/3' else profile['policy']['lookback']
    require(all(days.index(g['initial']) >= history for g in grids.values()), 'SCHEDULED_WARMUP')
    tz = ZoneInfo.from_file(io.BytesIO(tz_raw), key='America/New_York')
    # Preparation performs no features/weights/policy decision or native operation.
    market = load_reference(config['input_ref']) if load_prices else None
    return profile, calendar, schedule, grids, tz, market


def account_count(profile, grids):
    return len(profile['legs'])*len(grids)*len(profile.get('cost_scenarios', [None]))


def operation_phases(profile, grids):
    if profile['schema'].endswith(('/2','/4','/6')):
        require(set(grids) == {'FINAL'}, 'SCHEDULED_UNCERTAINTY_FINAL_ONLY')
        for scenario in profile['cost_scenarios']:
            yield ('FINAL' if scenario['id'] == 'BASE' else 'FINAL_COST_STRESS'), 'FINAL', scenario
    else:
        for phase in grids:
            yield phase, phase, None


def preflight(service, config):
    p, _, _, grids, _, _ = prepare(service, config, load_prices=False)
    result = {'schema': 'polar.scheduled-reference-preflight/1', 'status': 'READY_FOR_BOUND_OPERATION',
            'operation_binding_sha256': sha(canonical(binding(config))), 'policy_execution': 'NOT_RUN',
            'scientific_starts': 0, 'fit_calls': 0, 'predict_calls': 0,
            'expected_native_accounts': account_count(p, grids)}
    if p['schema'].endswith('/6'):
        n=sum(len(g['decisions']) for g in grids.values())
        result['expected_estimator_counts']={'estimator_calls':n+1,'calibration_estimates':1,'rolling_estimates':n,'completed_estimates':n+1}
    if p['schema'].endswith('/4'):
        n=sum(len(g['decisions']) for g in grids.values())
        result['expected_optimizer_counts']={'covariance_estimates':n,'spd_certifications':n,'portfolio_optimizations':n,'support_linear_system_attempts':15*n}
    return result


def authority_for(service, config, profile, grids):
    if config['namespace'] == 'INVENTED':
        return None
    authority = decode(read_ref(config['execution_authority_ref']))
    require(authority.get('schema') == 'polar.scheduled-reference-operation/1' and authority.get('action') == 'ORIGINAL' and
            authority.get('binding_sha256') == sha(canonical(binding(config))) and
            authority.get('allowed_fit_calls') == 0 and authority.get('allowed_predict_calls') == 0 and
            authority.get('allowed_native_accounts') == account_count(profile, grids), 'SCHEDULED_OPERATION_NOT_BOUND')
    if profile['schema'].endswith('/6'):
        require(authority.get('allowed_estimator_calls')==1+sum(len(g['decisions']) for g in grids.values()) and
                authority.get('allowed_optimizer_calls')==0,'SCHEDULED_TEMPORAL_OPERATION_BOUND')
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
    optimizer_counts = optimization_counts([])
    estimator_counts={'estimator_calls':0,'calibration_estimates':0,'rolling_estimates':0,'completed_estimates':0}
    try:
        market = load_reference(config['input_ref'])
        phases = {}; diagnostics = {}; plans = {}
        for phase, reference_phase, scenario in operation_phases(profile, grids):
            if reference_phase not in plans:
                plans[reference_phase] = plan_phase(market, profile, grids[reference_phase], tz)
                if profile['schema'].endswith('/6'):
                    estimator_counts=plans[reference_phase]['actual_estimator_counts']
                if profile['schema'].endswith('/4'):
                    optimizer_counts = optimization_counts([s for plan in plans.values() for s in plan['signals']])
            # Stress reuses every frozen signal/weight/time but re-executes its
            # own account NAV/quantity/fee-aware cash clipping from fresh capital.
            plan = plans[reference_phase]
            if scenario is not None:
                plan = {**plan, 'cost_profile': scenario['cost_profile']}
            simulation = bounded_native(plan); completed += len(simulation['legs'])
            evaluation = evaluate_policy(simulation, profile, reference_phase)
            diagnostics[phase] = {t['id']: diagnose_phase(t, schedule, profile,
                subperiods=profile['subperiods'] if reference_phase == 'FINAL' and (scenario is None or scenario['id'] == 'BASE') else ()) for t in simulation['legs']}
            phases[phase] = {'plan': plan, 'simulation': simulation, 'evaluation': evaluation}
            if scenario is not None:
                phases[phase]['reference_phase'] = reference_phase
                phases[phase]['cost_scenario'] = scenario
            with service.store.locked():
                service.store._publish(parent+'/'+aid+'/phases', phase,
                    {'phase.json': canonical(phases[phase]), 'diagnostics.json': canonical(diagnostics[phase])}, file_limit=32*1024**2)
        saved_calendar = {**calendar, 'source_schedule_rows': schedule}
        files = {'profile.json': canonical(profile), 'calendar.json': canonical(saved_calendar), 'phases.json': canonical(phases),
                 'diagnostics.json': canonical(diagnostics), 'bindings.json': canonical(binding(config))}
        manifest = {'schema': 'polar.scheduled-reference-semantic-manifest/1',
                    'files': {n: {'sha256': sha(b), 'bytes': len(b)} for n, b in files.items()}}
        uncertainty = None
        if profile['schema'].endswith(('/2','/4','/6')):
            base = phases['FINAL']['simulation']
            uncertainty = uncertainty_for(base,profile)
            screens_met = all(c['status'] == 'MET' for phase in phases.values() for c in phase['evaluation']['criteria'])
            uncertainty['point_screens_all_met'] = screens_met
            uncertainty['robustness'] = 'INSUFFICIENT_EVIDENCE' if profile['schema'].endswith('/6') else robustness(uncertainty, screens_met)
            files['uncertainty.json'] = canonical(uncertainty)
            manifest['files']['uncertainty.json'] = {'sha256':sha(files['uncertainty.json']), 'bytes':len(files['uncertainty.json'])}
        raw = canonical(manifest); sid = SEMANTIC+sha(raw)
        with service.store.locked():
            service.store._publish('reference-research-experiments', sid, {**files, 'manifest.json': raw}, file_limit=32*1024**2)
        publications = {}
        for phase, data in phases.items():
            public = public_config(config, profile)
            if 'cost_scenario' in data:
                public['cost_profile'] = data['cost_scenario']['cost_profile']
            record = public_reference(public, data['simulation'], data['evaluation'],
                                      semantic_id=sid, semantic_hash=sha(raw), phase=phase)
            # Display labels come from the bound profile, never a per-run UI branch.
            for series in record['series']:
                series['label'] = next(x['label'] for x in profile['legs'] if x['id'] == series['id'])
            project_diagnostics(record, diagnostics[phase])
            if profile['schema'] == 'polar.scheduled-reference-profile/3':
                project_gate_accounting(record, data['plan'], data['simulation'])
            if uncertainty is not None:
                project_uncertainty(record, uncertainty)
            if profile['schema'].endswith('/6'):
                project_estimation(record,estimator_counts)
            if profile['schema'].endswith('/4'):
                project_optimization(record, optimizer_counts)
            publications[phase] = service.results.publish(record)
        finish = {'status': 'SUCCESS', 'attempt_id': aid, 'semantic_id': sid, 'results': publications,
                  'fit_calls': 0, 'predict_calls': 0, 'model_calls': 0, 'native_accounts': completed,
                  'financial_acceptance': 'NOT_REVIEWED', 'finished_ns': time.time_ns()}
        if profile['schema'].endswith('/6'):
            n=sum(len(g['decisions']) for g in grids.values())
            require(estimator_counts=={'estimator_calls':n+1,'calibration_estimates':1,'rolling_estimates':n,'completed_estimates':n+1},'SCHEDULED_TEMPORAL_COMPLETION_COUNTS')
            finish['actual_estimator_counts']=estimator_counts
        if profile['schema'].endswith('/4'):
            n=sum(len(g['decisions']) for g in grids.values())
            require(optimizer_counts=={'covariance_estimates':n,'spd_certifications':n,'portfolio_optimizations':n,'support_linear_system_attempts':15*n},'SCHEDULED_GMV_COMPLETION_COUNTS')
            finish['actual_optimizer_counts'] = optimizer_counts
    except BaseException as exc:
        finish = {'status': 'FAILED_UNFINALIZED', 'attempt_id': aid, 'error': str(exc)[:240],
                  'fit_calls': 0, 'predict_calls': 0, 'model_calls': 0, 'completed_native_accounts': completed,
                  'refund': False, 'automatic_retry': False, 'finished_ns': time.time_ns()}
        if profile['schema'].endswith('/6'):
            from .scheduled_temporal import TemporalEstimationError
            if isinstance(exc,TemporalEstimationError):finish['scientific_status']='INVALID'
            events=getattr(exc,'events',{})
            finish['actual_estimator_counts']=events.get('actual_counts',estimator_counts) if isinstance(events,dict) else estimator_counts
        if profile['schema'].endswith('/4'):
            events=getattr(exc,'events',{})
            finish['actual_optimizer_counts'] = events.get('actual_counts',optimizer_counts) if isinstance(events,dict) else optimizer_counts
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
    require(manifest['schema'] == 'polar.scheduled-reference-semantic-manifest/1' and set(manifest['files']) in (MEMBERS, MEMBERS | {'uncertainty.json'}), 'SCHEDULED_MEMBER_SET')
    files = {}
    for name, pin in manifest['files'].items():
        body = read_file(service.store.root, parent+'/'+name, 32*1024**2)
        require(len(body) == pin['bytes'] and sha(body) == pin['sha256'], 'SCHEDULED_MEMBER_HASH')
        files[name] = decode(body)
    profile = profile_value(files['profile.json'])
    expected_members = MEMBERS | ({'uncertainty.json'} if profile['schema'].endswith(('/2','/4','/6')) else set())
    require(set(files) == expected_members, 'SCHEDULED_PROFILE_MEMBER_SET')
    require(files['bindings.json']['code'] == code_binding(), 'SCHEDULED_REPRODUCTION_CODE_BINDING')
    if profile['schema'].endswith(('/4','/6')):
        base=files['phases.json']['FINAL']['plan'];stress=files['phases.json']['FINAL_COST_STRESS']['plan']
        require({k:v for k,v in base.items() if k!='cost_profile'}=={k:v for k,v in stress.items() if k!='cost_profile'},'SCHEDULED_GMV_STRESS_SHARED_PLAN')
    expected_diagnostics = {}
    # Only saved output arrays are used; no source, policy feature, model or native call.
    calendar = files['calendar.json']
    for phase, data in files['phases.json'].items():
        if profile['schema'].endswith('/6'):
            from .scheduled_temporal_plan import verify_plan
            verify_plan(data['plan'],profile,calendar['source_schedule_rows'])
        if profile['schema'].endswith('/4'):
            verify_gmv_plan(data['plan'], profile)
        if profile['schema'] == 'polar.scheduled-reference-profile/3':
            require(data['plan'].get('gate_accounting') == gate_accounting(data['plan']), 'SCHEDULED_GATE_ACCOUNTING_RECOMPUTE')
        require(canonical(evaluate_policy(data['simulation'], profile, data.get('reference_phase', phase))) == canonical(data['evaluation']), 'SCHEDULED_RECOMPUTE_MISMATCH')
        schedule = calendar['source_schedule_rows']
        expected_diagnostics[phase] = {t['id']: diagnose_phase(t, schedule, profile,
            subperiods=profile['subperiods'] if data.get('reference_phase', phase) == 'FINAL' and data.get('cost_scenario',{}).get('id','BASE') == 'BASE' else ()) for t in data['simulation']['legs']}
    require(canonical(expected_diagnostics) == canonical(files['diagnostics.json']), 'SCHEDULED_DIAGNOSTIC_RECOMPUTE')
    if 'uncertainty.json' in files:
        actual = uncertainty_for(files['phases.json']['FINAL']['simulation'],profile)
        met = all(c['status'] == 'MET' for phase in files['phases.json'].values() for c in phase['evaluation']['criteria'])
        actual['point_screens_all_met'] = met; actual['robustness'] = 'INSUFFICIENT_EVIDENCE' if profile['schema'].endswith('/6') else robustness(actual, met)
        require(canonical(actual) == canonical(files['uncertainty.json']), 'SCHEDULED_UNCERTAINTY_RECOMPUTE')
    result={'status': 'REPRODUCED', 'semantic_id': semantic_id, 'fit_calls': 0, 'model_calls': 0,
            'predict_calls': 0, 'native_calls': 0, 'store_writes': 0}
    if profile['schema'].endswith('/6'):
        result['actual_estimator_counts']={'estimator_calls':0,'calibration_estimates':0,'rolling_estimates':0,'completed_estimates':0}
    if profile['schema'].endswith('/4'):
        result['actual_optimizer_counts']=optimization_counts([])
    return result


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
                                  ('metrics', 'max_drawdown', 'fraction'), ('costs', 'total_fee_usd', 'USD')]:
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
            scalar = lambda section, key: (segment.get(section, {}).get(key) or {}).get('value', 'unavailable')
            record['limitations'].append({'code': f'SEGMENT_{index}_'+series['id'], 'scope': series['label'],
                'text': (f"Saved subperiod {index+1}: {segment.get('first_return_date')} through {segment.get('last_return_date')}, "
                         f"preceding-close anchor {segment.get('initial_date')}; {segment.get('intervals')} returns. "
                         f"Normalization initial NAV cents {segment.get('costs', {}).get('normalization_initial_nav_cents')}. "
                         f"CAGR {scalar('metrics', 'net_cagr_act36525')}, annual volatility {scalar('metrics', 'annual_vol_252')}; "
                         f"exact gross USD {scalar('costs', 'gross_exact_notional_usd')}, settled gross USD {scalar('costs', 'gross_settled_notional_usd')}, "
                         f"fills {scalar('costs', 'positive_fill_count')}, gross/initial {scalar('costs', 'gross_notional_over_initial')}. "
                         'Carried holdings and cumulative end-minus-anchor costs; no reset, refit or extra liquidation.')})


def robustness(uncertainty, screens_met):
    comparisons = uncertainty.get('comparisons', [])
    if not screens_met or not uncertainty.get('all_components_valid') or len(comparisons) != 2:
        return 'INSUFFICIENT_EVIDENCE'
    try:
        from decimal import Decimal
        positive = all(c['sr_delta']['valid_count'] == 1000 and c['sr_delta']['lower'] is not None and
                       Decimal(c['sr_delta']['lower']) > 0 for c in comparisons)
    except (ValueError, KeyError, ArithmeticError):
        positive = False
    return 'PASS_CONDITIONAL_EXPOSED_SCENARIO_ONLY' if positive else 'INSUFFICIENT_EVIDENCE'


def project_uncertainty(record, uncertainty):
    """Finite public summary; every replicate/reason remains in the saved artifact."""
    by_id = {c['benchmark_id']:c for c in uncertainty['comparisons']}
    for key, label, unit in [('lower','BASE saved paired SR delta lower central95 bound','ratio'),
                             ('upper','BASE saved paired SR delta upper central95 bound','ratio'),
                             ('valid_count','BASE saved paired SR delta valid replicates','count')]:
        values = {}
        for series in record['series']:
            statistic = by_id.get(series['id'], {}).get('sr_delta')
            if statistic is None:
                values[series['id']] = {'value':None,'status':'NOT_APPLICABLE','reason':'PRIMARY_VS_CONTROL_COMPARISONS_ONLY'}
            elif statistic[key] is None:
                values[series['id']] = {'value':None,'status':'UNAVAILABLE','reason':'NO_VALID_BOOTSTRAP_STATISTIC'}
            else:
                values[series['id']] = {'value':str(statistic[key]),'status':'OK','reason':None}
        record['metrics'].append({'id':'base_bootstrap_sr_'+key,'label':label,
                                  'unit':unit,'values':values})
    for comparison in uncertainty['comparisons']:
        text = (f"BASE saved-return paired circular blocks63, seed{uncertainty['seed']}, 1000 draws; "
                'deltas are primary strategy minus this control. ')
        for key in ('sr_delta','growth_delta','drawdown_delta'):
            stat = comparison[key]
            text += (f"{key}: {stat['status']}, central95 [{stat['lower']}, {stat['upper']}], "
                     f"valid {stat['valid_count']}/1000, invalid {stat['invalid_count']}; "
                     f"reasons {stat['invalid_reason_counts']}. ")
        text += 'Full per-replicate statistics/reasons and shared index hash in immutable semantic uncertainty.json.'
        record['limitations'].append({'code':'SAVED_BOOTSTRAP_'+comparison['benchmark_id'],
            'scope':comparison['benchmark_id'],'text':text[:1000]})
    record['limitations'].append({'code':'CONDITIONAL_ROBUSTNESS','scope':'Entire modeled comparison',
        'text':f"{uncertainty['robustness']}. All point screens across BASE and actual doubled-cost accounts MET: "
               f"{uncertainty['point_screens_all_met']}; all six components have exactly1000 valid draws: "
               f"{uncertainty['all_components_valid']}. Bootstrap applies to BASE saved returns only, including on this cost-scenario page. "
               'Conditional on exposed history, selected survivors and block assumption; not calibrated market confidence, pristine holdout or general adoption evidence.'})


def project_gate_accounting(record, plan, simulation):
    counts=plan['gate_accounting']; primary=next(s['id'] for s in record['series'] if s['role'] == 'STRATEGY')
    for key,label in [('observations','Daily complete gate-vector observations'),('target_count','Nonterminal TARGET instructions'),
                      ('hold_count','Nonterminal HOLD instructions without sizing')]:
        values={}
        for series in record['series']:
            identity=series['id']
            values[identity]=({'value':None,'status':'NOT_APPLICABLE','reason':'NO_DAILY_GATE_POLICY'}
                 if key == 'observations' and identity != primary else
                 {'value':str(counts[key] if key == 'observations' else counts[key][identity]),'status':'OK','reason':None})
        record['metrics'].append({'id':'daily_gate_'+key,'label':label,'unit':'count','values':values})
    orders={leg['id']:sum(o['routed_quantity'] > 0 for o in leg['orders']) for leg in simulation['legs']}
    record['limitations'].append({'code':'DAILY_GATE_STATE_ACCOUNTING','scope':'Entire modeled comparison',
      'text':f"{counts['observations']} complete observed vectors; {counts['vector_changes_excluding_first']} changes excluding first. "
             f"Actual positive submitted order counts: {orders}. First/change/month-end triggers coalesce to one portfolio TARGET; "
             'state follows previous observed vector independently of fills. Monthly controls HOLD otherwise; terminal EXIT overrides all. '
             'Complete state/trigger/target/hold/exit accounting is saved in the semantic plan, not a learned model or risk guarantee.'})


def verify_gmv_plan(plan, profile):
    from .scheduled_signals import verify_gmv_signal
    require(len(plan['signals']) == len(plan['decisions'])-1, 'SCHEDULED_GMV_SIGNAL_COUNT')
    for index,(signal,decision) in enumerate(zip(plan['signals'],plan['decisions'])):
        weights=verify_gmv_signal(signal,plan['symbols'])
        require(signal['formation']==decision['formation'] and signal['execution']==decision['day'], 'SCHEDULED_GMV_SIGNAL_BINDING')
        for leg in profile['legs']:
            instruction=decision['instructions'][leg['id']]
            expected={s:[v.numerator,v.denominator] for s,v in weights[leg['rule']].items()}
            require(instruction['kind']=='TARGET' and instruction['weights']==expected and
                    instruction['signal']=={'kind':'SHRUNK_GMV_COMMON_RISK','certificate_signal_index':index}, 'SCHEDULED_GMV_INSTRUCTION_BINDING')
    counts=optimization_counts(plan['signals']);n=len(plan['signals'])
    require(counts=={'covariance_estimates':n,'spd_certifications':n,'portfolio_optimizations':n,'support_linear_system_attempts':15*n}, 'SCHEDULED_GMV_COUNTS')
    return counts


def project_optimization(record, counts):
    record['provenance'].append({'role':'portfolio_optimizer','id':'EXACT_SHRUNK_GMV_ALL15_SUPPORTS',
                                'sha256':sha(canonical(counts))})
    record['limitations'].append({'code':'PORTFOLIO_OPTIMIZATION_ACCOUNTING','scope':'Entire modeled comparison',
        'text':f"Actual original work {counts}; zero ML fits/predictions is not zero optimization. "
               'All15 exact support solves and rational KKT/SPD certificates are saved per formation; cost stress reuses that one weight set. '
               'Saved verification checks certificate identities without source, estimation, solver, native execution or writes. '
               'Shared forecast risk uses the same fixed50percent diagonal-shrunk covariance for strategy and both new controls; no future-risk guarantee.'})


def uncertainty_for(simulation,profile):
    from .scheduled_uncertainty import bootstrap
    temporal=profile['schema'].endswith('/6')
    wanted={x['id'] for x in profile['legs'] if not temporal or x['rule']!='CASH'}
    base={'legs':[l for l in simulation['legs'] if l['id'] in wanted]}
    return bootstrap(base,profile['primary_strategy'],[x['id'] for x in profile['legs']
        if x['id'] in wanted and x['id']!=profile['primary_strategy']],seed=profile['uncertainty']['seed'],
        recipe='TEMPORAL_DESCRIPTIVE' if temporal else 'LEGACY')


def diagnose_phase(tape,schedule,profile,*,subperiods=()):
    result=diagnose(tape,schedule,subperiods=subperiods)
    if profile['schema'].endswith('/6'):
        from .scheduled_diagnostics import _nav,_drawdown
        nav,reason=_nav(tape)
        if not reason:
            result['schema']='polar.temporal-saved-diagnostics/1'
            result['drawdown']=_drawdown(nav,latest_equal_peak=True)
            for segment in result['subperiods']:
                if segment['status']=='OK':
                    selected=[r for r in nav if segment['initial_date']<=r['date']<=segment['last_return_date']]
                    segment['drawdown']=_drawdown(selected,latest_equal_peak=True)
    return result


def project_estimation(record,counts):
    record['limitations'].append({'code':'ORIGINAL_VOLATILITY_ESTIMATION_COUNTS','scope':'EXPERIMENT',
        'text':f"Original estimator calls {counts['estimator_calls']}: one preperiod calibration {counts['calibration_estimates']}, causal rolling estimates {counts['rolling_estimates']}, completed {counts['completed_estimates']}. One saved weight sequence shared by both cost accounts. Zero ML fits/predictions/optimizations; computational completeness is not financial or robustness acceptance."})
