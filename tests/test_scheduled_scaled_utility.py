"""Invented fixed-annual utility thresholds, never retained market operands."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path

import pytest

from reference_fixture import write
from test_scheduled_fixed import fixed_fixture
from test_scheduled_service import snapshot
from polar.reference_service import ReferenceResearchService
from polar.scheduled_policy import profile_value, evaluate_policy


def utility_fixture(tmp_path, monkeypatch):
    root, cfg, p, cal = fixed_fixture(tmp_path, monkeypatch)
    zero = {s: [0, 1] for s in p['symbols']}
    weights = [('DEPLOY', {**zero, 'AAA': [1, 3], 'BBB': [2, 3]}),
               ('THIRD', {**zero, 'AAA': [1, 3]}),
               ('FULL', {**zero, 'AAA': [1, 1]}),
               ('OTHER', {**zero, 'BBB': [1, 1]}), ('CASH', zero)]
    p['legs'] = [{'id': i, 'label': i, 'rule': 'CASH' if i == 'CASH' else 'FIXED_WEIGHTS',
                  'weights': w} for i, w in weights]
    p.update(primary_strategy='DEPLOY', primary_benchmark='THIRD', subperiods=[])
    p['criteria'] = [{'id': k, 'description': k, 'kind': k, 'left_id': 'DEPLOY',
                      **({} if k == 'POSITIVE_GROWTH' else {'right_id': 'THIRD'}),
                      **({'factor': [11, 10]} if k == 'TERMINAL_SCALED_GE' else
                         {'factor': [6, 5]} if k in ('VOL_SCALED_LE', 'DRAWDOWN_SCALED_LE') else
                         {'threshold': '0'} if k == 'SR_DELTA_GE' else {})}
                     for k in ['TERMINAL_SCALED_GE', 'SR_DELTA_GE', 'VOL_SCALED_LE',
                               'DRAWDOWN_SCALED_LE', 'POSITIVE_GROWTH']]
    cfg['profile_ref'] = write(tmp_path/'utility-profile.json', p)
    return root, cfg, p, cal


@pytest.mark.parametrize('factor', [[True, 1], [1.1, 1], [-1, 1], [1, 0],
                                   [1000001, 1], [1, 1000001]])
def test_invalid_factor_stays_rejected(tmp_path, monkeypatch, factor):
    _, _, p, _ = utility_fixture(tmp_path, monkeypatch)
    p['criteria'][0]['factor'] = factor
    with pytest.raises(ValueError, match='SCHEDULED_CRITERION_FACTOR'):
        profile_value(p)


def test_factor_domains_do_not_admit_leverage_or_nonterminating_vol(tmp_path, monkeypatch):
    _, _, p, _ = utility_fixture(tmp_path, monkeypatch)
    assert profile_value(p) == p
    p['criteria'][2]['factor'] = [12, 10]
    assert profile_value(p) == p
    bad = deepcopy(p); bad['criteria'][2]['factor'] = [4, 3]
    with pytest.raises(ValueError, match='VOL_FACTOR_NONTERMINATING'): profile_value(bad)
    bad = deepcopy(p); bad['legs'][0]['weights']['AAA'] = [2, 3]
    with pytest.raises(ValueError, match='FIXED_WEIGHTS'): profile_value(bad)
    # The factor extension belongs to exact schema/5, not the shared version5 flag.
    from test_scheduled_fixed_costs import cost_fixture
    _, _, old, _ = cost_fixture(tmp_path/'old', monkeypatch)
    old['criteria'] = deepcopy(p['criteria'])
    for c in old['criteria']:
        c['left_id'] = 'THIRDS'
        if 'right_id' in c: c['right_id'] = 'THIRD'
    with pytest.raises(ValueError, match='SCHEDULED_CRITERION_FACTOR'): profile_value(old)


@pytest.mark.parametrize('terminal,dd,vol,expected', [
    (11000000, Fraction(3, 25), '.12', ['MET']*5),
    (10999999, Fraction(120001, 1000000), '.12000000000000000000000000000000000000000000001',
     ['NOT_MET', 'MET', 'NOT_MET', 'NOT_MET', 'MET'])])
def test_exact_utility_boundaries(tmp_path, monkeypatch, terminal, dd, vol, expected):
    _, _, p, _ = utility_fixture(tmp_path, monkeypatch)
    keys = ['terminal_nav_usd', 'net_cagr_act36525', 'sharpe_252_rf0', 'max_drawdown',
            'total_cost_usd', 'annual_vol_252']
    legs = [{'id': leg['id'], 'metrics': {k: {'value': '0'} for k in keys}} for leg in p['legs']]
    for leg in legs: leg['metrics']['annual_vol_252']['value'] = vol if leg['id'] == 'DEPLOY' else '.1'
    exact = {leg['id']: {'terminal': terminal if leg['id'] == 'DEPLOY' else 10000000,
                         'max_drawdown': dd if leg['id'] == 'DEPLOY' else Fraction(1, 10)}
             for leg in p['legs']}
    monkeypatch.setattr('polar.scheduled_policy.evaluate_legs', lambda _: (legs, exact))
    result = evaluate_policy({'legs': [{'nav': [{}, {}]}]}, p, 'FINAL')
    assert [c['status'] for c in result['criteria']] == expected


def test_five_native_accounts_zero_aliases_and_saved_only_replay(tmp_path, monkeypatch):
    import polar.scheduled_service as module
    root, cfg, _, _ = utility_fixture(tmp_path, monkeypatch)
    service = ReferenceResearchService(root, 128*1024**2)
    assert service.preflight(cfg)['expected_native_accounts'] == 5
    result = service.run(cfg)
    assert result['status'] == 'SUCCESS' and result['native_accounts'] == 5
    assert result['fit_calls'] == result['predict_calls'] == result['model_calls'] == 0
    phases = json.loads((root/'reference-research-experiments'/result['semantic_id']/'phases.json').read_bytes())
    assert set(phases) == {'FINAL'} and 'initial_state_control' not in phases['FINAL']
    for tape in phases['FINAL']['simulation']['legs']:
        assert all(mark['positions']['CCC'] == mark['positions']['DDD'] == 0 for mark in tape['nav'])
        assert not any(o['symbol'] in ('CCC', 'DDD') for o in tape['orders'])
    before = snapshot(root)
    def forbidden(*a, **k): raise AssertionError('STORED_SOURCE_POLICY_NATIVE_CALL')
    for name in ('load_reference', 'plan_phase', 'bounded_native'): monkeypatch.setattr(module, name, forbidden)
    replay = service.recompute(result['semantic_id'])
    assert replay['status'] == 'REPRODUCED' and replay['native_calls'] == replay['store_writes'] == 0
    assert snapshot(root) == before
