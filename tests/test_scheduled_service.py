"""Invented executable no-fit pipeline and exact preserved-attempt controls."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from polar.gym_contract import canonical
from polar.research_reference import load_reference
from polar.scheduled_policy import calendar_value, plan_phase, evaluate_policy, profile_value
from scheduled_fixture import fixture


def snapshot(root):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_nofit_two_phase_original_wire_stored_reproduction_and_duplicate(tmp_path, monkeypatch):
    root, cfg, profile, calendar = fixture(tmp_path, monkeypatch)
    service = ReferenceResearchService(root, 128*1024**2)
    ready = service.preflight(cfg)
    assert ready['fit_calls'] == ready['predict_calls'] == ready['scientific_starts'] == 0
    assert ready['expected_native_accounts'] == 10
    assert not (root/'scheduled-reference-attempts').exists()
    result = service.run(cfg)
    assert result['status'] == 'SUCCESS' and result['native_accounts'] == 10
    assert result['fit_calls'] == result['model_calls'] == result['predict_calls'] == 0
    assert set(result['results']) == {'VALIDATION', 'FINAL'}
    for phase, publication in result['results'].items():
        detail = ResearchResults(root, 128*1024**2).read(publication['result_id']); r = detail['record']
        assert len(r['series']) == 5 and r['primary_benchmark_id'] == 'EW'
        assert len(r['grid']) == calendar['phases'][phase]['nav_points']
        assert len(r['criteria']) == (5 if phase == 'FINAL' else 0)
        assert not any(x['role'] == 'trained_model' for x in r['provenance'])
        assert not any('FORECAST' in x['id'] for x in r['metrics'])
        assert r['basis']['wealth_basis'] == 'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT'
        assert any(x['id'] == 'empirical_tail_mean' for x in r['metrics'])
        assert any(x['id'] == 'worst_full_month' for x in r['metrics'])
        assert any(x['code'].startswith('SAVED_RISK_') for x in r['limitations'])
        assert detail['assessment']['financial'] == 'NOT_REVIEWED'
    before = snapshot(root)
    import polar.scheduled_service as module
    def forbidden(*args, **kwargs): raise AssertionError('STORED_PATH_CALLED_POLICY_SOURCE_MODEL_NATIVE')
    monkeypatch.setattr(module, 'bounded_native', forbidden); monkeypatch.setattr(module, 'plan_phase', forbidden)
    monkeypatch.setattr(module, 'load_reference', forbidden)
    reproduced = service.recompute(result['semantic_id'])
    assert reproduced['status'] == 'REPRODUCED'
    assert all(reproduced[k] == 0 for k in ('fit_calls','predict_calls','model_calls','native_calls','store_writes'))
    assert snapshot(root) == before
    with pytest.raises(ValueError, match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'): service.run(cfg)


def test_start_is_durable_before_first_signal_and_failure_is_not_refunded(tmp_path, monkeypatch):
    root, cfg, profile, calendar = fixture(tmp_path, monkeypatch)
    import polar.scheduled_service as module
    def first_signal(*args, **kwargs):
        starts = list((root/'scheduled-reference-attempts').rglob('start.json'))
        assert len(starts) == 1
        start = json.loads(starts[0].read_bytes())
        assert start['status'] == 'FIRST_START_CONSERVATIVE_DEBIT' and start['fit_calls'] == 0
        raise ValueError('INVENTED_SIGNAL_FAILURE')
    monkeypatch.setattr(module, 'plan_phase', first_signal)
    service = ReferenceResearchService(root, 64*1024**2)
    with pytest.raises(ValueError, match='INVENTED_SIGNAL_FAILURE'): service.run(cfg)
    failure = json.loads(next((root/'scheduled-reference-attempts').rglob('record.json')).read_bytes())
    assert failure['status'] == 'FAILED_UNFINALIZED' and failure['refund'] is False and failure['fit_calls'] == 0
    with pytest.raises(ValueError, match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'): service.run(cfg)


def test_causal_planning_uses_only_formation_prefix_and_named_leg_ids(tmp_path, monkeypatch):
    root, cfg, profile, calendar = fixture(tmp_path, monkeypatch)
    market = load_reference(cfg['input_ref']); grid = calendar['phases']['FINAL']; tz = ZoneInfo('America/New_York')
    one = plan_phase(market, profile, grid, tz); first = grid['decisions'][0]; index = market['dates'].index(first['signal_date'])
    altered = deepcopy(market)
    for day in altered['dates'][index+1:]:
        altered['prices_micro'][day] = {s: 999999999 for s in profile['symbols']}
    two = plan_phase(altered, profile, grid, tz)
    assert one['decisions'][0] == two['decisions'][0]
    assert set(one['decisions'][0]['instructions']) == {x['id'] for x in profile['legs']}
    assert one['decisions'][0]['instructions']['EW_HALF']['weights'] == {s: [1,8] for s in profile['symbols']}
    assert one['decisions'][0]['instructions']['CASH'] == {'kind':'HOLD'}
    assert all(x['kind'] == 'EXIT' for x in one['decisions'][-1]['instructions'].values())
    assert all(d['known_ns'] < d['decision_ns'] < d['open_ns'] for d in one['decisions'])


def test_five_conditions_use_exact_wealth_and_d50_delta_not_display(tmp_path, monkeypatch):
    _, _, profile, _ = fixture(tmp_path, monkeypatch)
    import polar.scheduled_policy as module
    ids = [x['id'] for x in profile['legs']]
    metrics = {i: {'sharpe_252_rf0': {'value': '0.20000000000000000000000000000000000000000000000001' if i=='SLEEVES' else '0.1'},
                   'annual_vol_252': {'value':'0.1'}, **{k:{'value':'0'} for k in ('terminal_nav_usd','net_cagr_act36525','max_drawdown','total_cost_usd')}} for i in ids}
    exact = {i: {'terminal': 10000001 if i=='SLEEVES' else 10000000,
                 'max_drawdown': Fraction(1,10)} for i in ids}
    monkeypatch.setattr(module, 'evaluate_legs', lambda simulation: ([{'id':i,'metrics':metrics[i]} for i in ids], exact))
    fake = {'legs':[{'nav':[{},{}]}]}
    r = evaluate_policy(fake, profile, 'FINAL')
    assert len(r['criteria']) == 5 and all(c['status']=='MET' for c in r['criteria'])
    metrics['SLEEVES']['sharpe_252_rf0']['value'] = '0.19999999999999999999999999999999999999999999999999'
    assert evaluate_policy(fake, profile, 'FINAL')['criteria'][0]['status'] == 'NOT_MET'
    exact['SLEEVES']['terminal'] = 10000000
    assert evaluate_policy(fake, profile, 'FINAL')['criteria'][3]['status'] == 'NOT_MET'
    metrics['SLEEVES']['sharpe_252_rf0']['value'] = None
    assert evaluate_policy(fake, profile, 'FINAL')['point_interpretation'] == 'INDETERMINATE'
    assert evaluate_policy(fake, profile, 'VALIDATION')['criteria'] == []


def test_metadata_fails_without_policy_or_native_calls(tmp_path, monkeypatch):
    root, cfg, profile, calendar = fixture(tmp_path, monkeypatch)
    profile['policy']['kind'] = 'ARBITRARY_PLUGIN'
    with pytest.raises(ValueError, match='SCHEDULED_POLICY'): profile_value(profile)
    market = load_reference(cfg['input_ref']); calendar['phases']['FINAL']['decisions'].pop()
    with pytest.raises(ValueError, match='SCHEDULED_DECISION_GRID'): calendar_value(calendar, market['schedule'])
