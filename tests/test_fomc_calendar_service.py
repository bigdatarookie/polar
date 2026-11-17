"""Invented calendar/source/atomic operation and source-absent private graph."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import replace
from fractions import Fraction
import json
import pytest
from zoneinfo import ZoneInfo

from polar.gym_contract import canonical, sha
from polar.gym_service import code_binding
from polar.ci_research_service import root_identity
from polar.fomc_calendar import geometry, QUESTION, POLICY_SHA, CONTRACT_SHA, PROPOSAL_SHA, plan_phase
from polar.fomc_calendar_service import prepare, preflight, run, recompute, config_from_seed, REFS
from test_calendar_study_service import fixture as legacy_fixture, put


def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv('POLAR_RUNTIME_IMAGE_ID', 'sha256:'+'b'*64)
    service, old, quotes = legacy_fixture(tmp_path)
    manifest = json.loads(Path(old['input_ref']['path']).read_bytes())
    schedule = json.loads(Path(manifest['schedule']['path']).read_bytes())['rows']
    phases = {'VALIDATION': ['2023-12-24', '2024-01-01'], 'FINAL': ['2024-01-02', '2024-01-12']}
    oldroles = json.loads(Path(old['roles_ref']['path']).read_bytes())
    roles = {'schema': 'polar.fomc-source-roles/1', 'input_ref': old['input_ref'], 'phase_bounds': phases, 'phases': {}}
    for phase, bounds in phases.items():
        rows = []
        for row in oldroles['source_rows']:
            if row['date'] > bounds[1]: continue
            role = ('NAV' if bounds[0] <= row['date'] else 'VTI_WARMUP_CANDIDATE' if row['symbol'] == 'VTI'
                    else 'BIL_UNUSED_WARMUP_CONTEXT')
            rows.append({**row, 'role': role})
        roles['phases'][phase] = rows
    events = []
    for i, day in enumerate(['2023-12-27', '2024-01-05']):
        events.append({'event_id': 'INVENTED-'+str(i), 'statement_date': day, 'clock_status': 'MODEL_CLOCK',
                       'regular_exception_cancel_reschedule_classification': 'REGULAR_SCHEDULED_POLICY_STATEMENT_ROW',
                       'clock_basis': 'MODEL_CLOCK_FROM_OFFICIAL_STANDING_SCHEDULE_CONVENTION',
                       'statement_url': 'https://example.invalid/invented', 'scheduled_clock': '14:00',
                       'scheduled_zone': 'America/New_York'})
    events.append({'event_id': 'INVENTED-UNKNOWN', 'statement_date': None, 'clock_status': 'UNKNOWN',
                   'regular_exception_cancel_reschedule_classification': 'AMBIGUOUS'})
    index = {'completeness_and_exclusions': {'event_rows': events}}
    calendar = geometry(events, schedule, phases, ZoneInfo('America/New_York'))
    root = Path(__file__).resolve().parents[1]
    refs = {'input': old['input_ref'], 'index': put(tmp_path/'index.json', index),
            'roles': put(tmp_path/'fomc-roles.json', roles), 'timezone': old['timezone_ref'],
            'protocol': put(tmp_path/'fomc-protocol.md', (root/'research_candidates/quant_a_fomc_calendar/protocol.md').read_bytes()),
            'contract': put(tmp_path/'fomc-contract.json', (root/'research_candidates/quant_a_fomc_calendar/author_contract.json').read_bytes()),
            'geometry': put(tmp_path/'geometry.json', calendar)}
    for key in ('method', 'qualification'):
        refs[key] = put(tmp_path/('fomc-'+key+'.json'), {'schema': 'polar.fomc-'+key+'/1',
            'namespace': 'INVENTED', 'question_id': QUESTION, 'policy_sha256': POLICY_SHA, 'contract_sha256': CONTRACT_SHA,
            'status': 'ACCEPTED_WITH_LIMITS' if key == 'method' else 'PASS',
            **({'code': code_binding(), 'code_revision': 'a'*40, 'runtime_image_id': 'sha256:'+'b'*64,
                'source_free': True, 'selection': ['tests/test_fomc_calendar_service.py']} if key == 'qualification' else {})})
    refs['resources'] = put(tmp_path/'fomc-resources.json', {'schema': 'polar.fomc-resources/1', 'namespace': 'INVENTED',
        'limits': {'native_wall_seconds': 180, 'stored_wall_seconds': 30, 'cleanup_seconds': 10,
                   'remaining_family_wall_seconds': 400, 'storage_upper_bound_bytes': 100*1024**2}})
    refs['clock'] = put(tmp_path/'fomc-clock.json', {'schema': 'polar.fomc-quote-clock/1', 'namespace': 'INVENTED',
        'basis': 'INVENTED', 'roles_sha256': refs['roles']['sha256'], 'assumption_ref': None, 'source_fit_ref': None})
    cfg = {'schema': 'polar.fomc-calendar-config/1', 'namespace': 'INVENTED', 'question_id': QUESTION,
           'candidate_id': 'INVENTED-FOMC', 'experiment_id': 'INVENTED-FROZEN', 'consumer_task': 'qitem-INVENTED',
           'source_admission_ref': None, 'code': code_binding(), 'code_revision': 'a'*40,
           'runtime_image_id': 'sha256:'+'b'*64, 'artifact_root_identity': root_identity(service.store.root),
           **{k+'_ref': v for k, v in refs.items()}}
    return service, cfg, quotes, calendar


def test_factory_closed_and_does_not_follow_refs(tmp_path, monkeypatch):
    service, cfg, _, _ = fixture(tmp_path, monkeypatch)
    import polar.candidate_binding as candidate
    monkeypatch.setattr(candidate, 'loaded_revision', lambda: 'a'*40)
    seed = {k: v for k, v in cfg.items() if k not in ('code', 'code_revision', 'runtime_image_id', 'artifact_root_identity')}
    seed['schema'] = 'polar.fomc-calendar-seed/1'
    seed['input_ref'] = {'path': '/does/not/exist', 'sha256': 'c'*64, 'bytes': 1}
    result = config_from_seed(seed, service.store.root)
    assert result['code_revision'] == 'a'*40 and result['input_ref'] == seed['input_ref']
    with pytest.raises(Exception, match='FOMC_CLOSED_SEED'):
        config_from_seed({**seed, 'execution_authority_ref': {}}, service.store.root)


def test_preflight_is_metadata_only_and_rejects_wrong_geometry(tmp_path, monkeypatch):
    service, cfg, quotes, calendar = fixture(tmp_path, monkeypatch)
    import polar.fomc_calendar_service as module
    def forbidden(*a, **k): raise AssertionError('NO_SOURCE_NATIVE')
    monkeypatch.setattr(module, 'load_reference', forbidden)
    monkeypatch.setattr(module, 'bounded_native', forbidden)
    assert preflight(service, cfg)['scientific_starts'] == 0
    assert not (service.store.root/'scheduled-reference-attempts').exists()
    bad = deepcopy(calendar); bad['clusters']['FINAL'][0]['entry_ns'] += 1
    cfg['geometry_ref'] = put(tmp_path/'bad-geometry.json', bad)
    with pytest.raises(Exception, match='FOMC_RUNTIME_GEOMETRY_EQUALITY'): preflight(service, cfg)


@pytest.mark.parametrize('field,code', [('protocol_ref', 'FOMC_FROZEN_METHOD'), ('contract_ref', 'FOMC_FROZEN_METHOD'),
                                      ('runtime_image_id', 'FOMC_CURRENT_RUNTIME'), ('code', 'FOMC_CURRENT_CODE_ROOT')])
def test_current_binding_rejects_before_values_and_debit(tmp_path, monkeypatch, field, code):
    service, cfg, _, _ = fixture(tmp_path, monkeypatch)
    cfg[field] = {} if field == 'code' else 'sha256:'+'c'*64 if field == 'runtime_image_id' else put(tmp_path/'wrong.json', {})
    with pytest.raises(Exception, match=code): preflight(service, cfg)
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_quote_unknown_does_not_manufacture_midnight_or_debit(tmp_path, monkeypatch):
    service, cfg, _, _ = fixture(tmp_path, monkeypatch)
    roles = json.loads(Path(cfg['roles_ref']['path']).read_bytes())
    for rows in roles['phases'].values():
        for r in rows: r['available_ns'] = None
    cfg['roles_ref'] = put(tmp_path/'unknown-roles.json', roles)
    cfg['clock_ref'] = put(tmp_path/'unknown-clock.json', {'schema': 'polar.fomc-quote-clock/1', 'namespace': 'INVENTED',
        'basis': 'UNKNOWN', 'roles_sha256': cfg['roles_ref']['sha256'], 'assumption_ref': None, 'source_fit_ref': None})
    assert preflight(service, cfg)['quote_clock_readiness'] == 'UNKNOWN'
    with pytest.raises(Exception, match='FOMC_QUOTE_CLOCK_UNQUALIFIED'): run(service, cfg)
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_actual_retained_guard_is_unavailable_even_with_fake_claims():
    from polar.fomc_calendar_hosting import validate_child
    with pytest.raises(Exception, match='FOMC_HOST_TRUSTED_PARENT_CHILD_GUARD_UNAVAILABLE'):
        validate_child(None, {'namespace': 'RETAINED', 'CERTIFIED': True, 'pid': 123})


def test_geometry_touching_return_merges_labels_and_preserves_unknown(tmp_path, monkeypatch):
    service, cfg, _, calendar = fixture(tmp_path, monkeypatch)
    assert any(r['status'] == 'SOURCE_UNRESOLVED_NO_ACTION' for r in calendar['records'])
    m = prepare(service, cfg)
    market = __import__('polar.research_reference', fromlist=['load_reference']).load_reference(cfg['input_ref'])
    plan = plan_phase(market, m['roles']['phases']['FINAL'], calendar, 'FINAL', m['roles']['phase_bounds']['FINAL'],
                      'INVENTED/test', m['manifest']['parent_dataset_revision'], QUESTION)
    from polar.event_native import validate_plan
    validate_plan(plan)
    static = [s for s in plan.instructions if s['leg'] == 'STATIC_50']
    assert all(s['decision_ns'] == plan.nav_closes[i]+60*10**9 for i, s in enumerate(static))
    assert plan.daily_decisions[0].q_ns == plan.nav_closes[1]
    # An afternoon entry cannot consume the still-unclosed same-day quote.
    group = calendar['clusters']['FINAL'][0]
    from polar.event_native import eligible_closes
    assert max(r.close_ns for r in eligible_closes(plan.source, group['decision_ns'], 'VTI')) < group['decision_ns']


def test_failure_retains_first_start_no_refund_and_no_retry(tmp_path, monkeypatch):
    service, cfg, _, _ = fixture(tmp_path, monkeypatch)
    import polar.fomc_calendar_service as module
    def fail(*a, **k): raise RuntimeError('INVENTED_STOP_BEFORE_NATIVE')
    monkeypatch.setattr(module, 'bounded_native', fail)
    with pytest.raises(RuntimeError, match='INVENTED_STOP'): run(service, cfg)
    finish = next((service.store.root/'scheduled-reference-attempts').glob('*/*/finish/record.json'))
    assert json.loads(finish.read_bytes())['refund'] is False
    with pytest.raises(Exception, match='FOMC_ORIGINAL_ALREADY_RECORDED'): run(service, cfg)


def test_actual_invented_service_and_source_absent_recompute(tmp_path, monkeypatch):
    service, cfg, quotes, _ = fixture(tmp_path, monkeypatch)
    result = service.run(cfg)
    assert result['status'] == 'SUCCESS'
    before = {str(p): sha(p.read_bytes()) for p in service.store.root.rglob('*') if p.is_file()}
    Path(quotes['path']).unlink()
    import polar.fomc_calendar_service as module
    def forbidden(*a, **k): raise AssertionError('NO_SOURCE_POLICY_OR_NATIVE_REPLAY')
    monkeypatch.setattr(module, 'load_reference', forbidden)
    monkeypatch.setattr(module, 'bounded_native', forbidden)
    import polar.fomc_calendar as algebra
    monkeypatch.setattr(algebra, 'author_policy', forbidden)
    assert service.recompute(result['semantic_id'])['status'] == 'REPRODUCED'
    assert before == {str(p): sha(p.read_bytes()) for p in service.store.root.rglob('*') if p.is_file()}


def test_fomc_current_native_scope_and_stale_generation(tmp_path, monkeypatch):
    from test_native_selected_input import Queue, TASK, ADMISSION
    from polar import fomc_source
    import polar.candidate_binding as candidate
    import polar.offline_author_binding as offline
    service, cfg, _, _ = fixture(tmp_path, monkeypatch)
    cfg.update(namespace='RETAINED', consumer_task=TASK, source_admission_ref=ADMISSION+'#3')
    monkeypatch.setattr(candidate, 'loaded_revision', lambda: 'a'*40)
    monkeypatch.setattr(fomc_source, 'actual_runtime', lambda config: None)
    queue = Queue(cfg)
    resolution = json.loads(queue.row['resolution']); resolution['schema'] = 'polar.fomc-source-admission/1'
    queue.row['resolution'] = json.dumps(resolution)
    assert fomc_source.authorize(cfg, service.store.root, queue=queue)['generation'] == 'invented-generation'
    changed = {**cfg, 'protocol_ref': {'path': '/never/read', 'sha256': 'f'*64, 'bytes': 1}}
    with pytest.raises(Exception, match='FOMC_NATIVE_SOURCE_BINDING'):
        fomc_source.authorize(changed, service.store.root, queue=queue)
    queue.owner['agentActivity']['generation'] = 'new-generation'
    with pytest.raises(Exception, match='CURRENT_GENERATION'):
        fomc_source.authorize(cfg, service.store.root, queue=queue)


def test_fomc_saved_instruction_tamper_is_rejected_without_policy(tmp_path, monkeypatch):
    service, cfg, _, calendar = fixture(tmp_path, monkeypatch)
    m = prepare(service, cfg)
    market = __import__('polar.research_reference', fromlist=['load_reference']).load_reference(cfg['input_ref'])
    plan = plan_phase(market, m['roles']['phases']['FINAL'], calendar, 'FINAL', m['roles']['phase_bounds']['FINAL'],
                      'INVENTED/test', m['manifest']['parent_dataset_revision'], QUESTION)
    from polar.event_native import validate_plan
    bad = [dict(s) for s in plan.instructions]
    next(s for s in bad if s['leg'] == 'STATIC_50')['q_ns'] = plan.nav_closes[0]
    with pytest.raises(Exception, match='FOMC_STEP_FIELDS'):
        validate_plan(replace(plan, instructions=tuple(bad)))


def test_labels_do_not_create_a_retry_family(tmp_path, monkeypatch):
    service, cfg, _, _ = fixture(tmp_path, monkeypatch)
    from polar.fomc_calendar_service import family
    assert family(cfg) == family({**cfg, 'candidate_id': 'INVENTED-ALIAS', 'experiment_id': 'NEW-LABEL'})


def test_closed_source_scope_precedes_materializer_access(tmp_path, monkeypatch):
    service, cfg, _, _ = fixture(tmp_path, monkeypatch)
    from polar.fomc_source import SOURCE_SCHEMA, SOURCE_PROFILE, prepare_source_input
    source = {k: cfg[k] for k in ('namespace', 'question_id', 'candidate_id', 'experiment_id', 'code', 'code_revision',
                                  'runtime_image_id', 'artifact_root_identity', 'consumer_task', 'source_admission_ref',
                                  'contract_ref', 'protocol_ref', 'method_ref')}
    source.update(schema=SOURCE_SCHEMA, profile_id=SOURCE_PROFILE,
                  spec_ref={'path': '/never/read', 'sha256': 'a'*64, 'bytes': 1}, namespace='RETAINED')
    import polar.fomc_source as module
    def forbidden(*a, **k): raise AssertionError('NO_SPEC_OR_SOURCE_BEFORE_NATIVE_SCOPE')
    monkeypatch.setattr(__import__('polar.gym_contract', fromlist=['read_ref']), 'read_ref', forbidden)
    with pytest.raises(Exception, match='FOMC_NATIVE_SOURCE_SCOPE|CANDIDATE_CHECKOUT_UNVERIFIED|FOMC_SOURCE_ACTUAL_RUNTIME'):
        prepare_source_input(source, service.store.root, service.store.limit)


def test_material_start_intervals_include_cash_and_strict_threshold():
    from polar.fomc_calendar import material_fraction
    nav = [{'nav_cents': 100, 'position_cents': {'VTI': v}} for v in (0, 75, 74, 100)]
    assert material_fraction(nav) == Fraction(2, 3)
    assert material_fraction([{**r, 'nav_cents': 0} if i == 1 else r for i, r in enumerate(nav)]) is None


def test_fee_budget_clamps_negative_extra_and_uses_civil_dates():
    from polar.fomc_calendar import extra_fee_budget
    s = [{'date': '2024-03-08', 'flat_cents': 0, 'bps_cents': 0},
         {'date': '2024-03-12', 'flat_cents': 100, 'bps_cents': 0}]
    b = [s[0], {**s[1], 'flat_cents': 200}]
    assert extra_fee_budget(s, b) == (0, Fraction(10_000_000, 200)*Fraction(4*4, 1461))


def test_date_geometry_coalesces_touching_risk_end_not_label_end():
    dates = [(datetime(2024, 1, 1)+timedelta(days=i)).date().isoformat() for i in range(15)]
    schedule = [{'date': d, 'reference_close_utc': d+'T21:00:00Z'} for d in dates]
    rows = [{'event_id': 'INVENTED-'+str(i), 'statement_date': d, 'clock_status': 'MODEL_CLOCK',
             'regular_exception_cancel_reschedule_classification': 'REGULAR_SCHEDULED_POLICY_STATEMENT_ROW',
             'clock_basis': 'MODEL_CLOCK_FROM_OFFICIAL_STANDING_SCHEDULE_CONVENTION',
             'statement_url': 'https://example.invalid', 'scheduled_clock': '14:00',
             'scheduled_zone': 'America/New_York'} for i, d in enumerate(['2024-01-04', '2024-01-07'])]
    value = geometry(rows, schedule, {'FINAL': [dates[0], dates[-1]]}, ZoneInfo('America/New_York'))
    a, b = value['records']
    assert a['return_ns'] == b['entry_ns'] and a['label_ns'] < b['entry_ns']
    assert len(value['clusters']['FINAL']) == 1
    cluster = value['clusters']['FINAL'][0]
    assert cluster['members'] == ['INVENTED-0', 'INVENTED-1']
    assert cluster['label_ns'] == b['label_ns'] and cluster['return_ns'] == b['return_ns']


def test_actual_file_cli_factory_and_value_absent_preflight(tmp_path, monkeypatch):
    import os, subprocess, sys
    from polar.candidate_binding import loaded_revision
    service, cfg, quotes, _ = fixture(tmp_path, monkeypatch)
    runtime = os.environ.get('POLAR_CI_RUNTIME_IMAGE_ID') or 'sha256:'+'b'*64
    qa = json.loads(Path(cfg['qualification_ref']['path']).read_bytes())
    qa.update(code_revision=loaded_revision(), runtime_image_id=runtime)
    cfg['qualification_ref'] = put(tmp_path/'current-qa.json', qa)
    seed = {k: v for k, v in cfg.items() if k not in ('code', 'code_revision', 'runtime_image_id', 'artifact_root_identity')}
    seed['schema'] = 'polar.fomc-calendar-seed/1'
    pin = put(tmp_path/'current-seed.json', seed)
    env = {**os.environ, 'POLAR_ARTIFACT_ROOT': str(service.store.root), 'POLAR_RUNTIME_IMAGE_ID': runtime}
    made = subprocess.run([sys.executable, '-m', 'polar.cli', 'research-config', pin['path']],
                           env=env, text=True, capture_output=True, timeout=30)
    assert made.returncode == 0, made.stderr
    current = json.loads(made.stdout)
    assert current['code_revision'] == loaded_revision()
    Path(quotes['path']).unlink()
    configpin = put(tmp_path/'current-config.json', current)
    ready = subprocess.run([sys.executable, '-m', 'polar.cli', 'research-preflight', configpin['path']],
                            env=env, text=True, capture_output=True, timeout=30)
    assert ready.returncode == 0, ready.stderr
    assert json.loads(ready.stdout)['source_values_read'] == 0
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_actual_closed_selected_route_and_read_time_spec_binding(tmp_path, monkeypatch):
    from test_native_selected_input import fixture as source_fixture
    from polar.fomc_source import SOURCE_SCHEMA, SOURCE_PROFILE
    from polar.reference_input import prepare_input
    from polar.research_reference import load_reference
    service, cfg, _, _ = fixture(tmp_path/'operation', monkeypatch)
    folder = tmp_path/'source'; folder.mkdir()
    _, old, _, parent, _ = source_fixture(folder, monkeypatch)
    purpose = old['purpose_ref']
    spec = {'schema': 'polar.selected-component-materialization/1', 'namespace': 'INVENTED',
            'leaf_inputs': [{'input_ref': old['bil_input_ref'], 'symbol': 'BIL'}],
            'normalized_inputs': [{'input_ref': old['vti_parent_ref'], 'binding_ref': old['vti_binding_ref'], 'symbol': 'VTI'}],
            'schedule': parent['schedule'], 'date_range': {'start': '2024-02-01', 'end': '2024-02-02', 'count': 2},
            'purpose_ref': purpose, 'qualification_refs': [purpose]}
    source = {k: cfg[k] for k in ('namespace', 'question_id', 'candidate_id', 'experiment_id', 'code', 'code_revision',
                                  'runtime_image_id', 'artifact_root_identity', 'consumer_task', 'source_admission_ref',
                                  'contract_ref', 'protocol_ref', 'method_ref')}
    source.update(schema=SOURCE_SCHEMA, profile_id=SOURCE_PROFILE, spec_ref=put(tmp_path/'spec.json', spec))
    result = prepare_input(source, service.store.root, service.store.limit)
    assert load_reference(result['input_ref'])['symbols'] == ['BIL', 'VTI']
    # A changed spec under copied proof is rejected before its quotes are opened.
    manifest = json.loads(Path(result['input_ref']['path']).read_bytes())
    manifest['conversion_metadata']['spec']['date_range']['count'] = 999
    manifest['quotes']['path'] = '/never/open/prices'
    bad = put(tmp_path/'tampered-manifest.json', manifest)
    with pytest.raises(Exception, match='FOMC_PREPARED_SPEC_BINDING'): load_reference(bad)
