"""Drawdown integration uses invented prices only; no retained source access."""
from copy import deepcopy
from datetime import date, timedelta, timezone
from fractions import Fraction as F
import json
from pathlib import Path

import pytest
from polar import scheduled_drawdown as adapter
from polar.scheduled_policy import profile_value, plan_phase, calendar_value
from polar.research_reference import load_reference
from polar.reference_service import ReferenceResearchService
from polar.scheduled_service import prepare, preflight, run, recompute
from polar.gym_service import code_binding
from reference_fixture import write
from test_reference_input import put
from scheduled_fixture import sma_fixture


def fixture(tmp_path, monkeypatch):
    root, cfg, p, cal = sma_fixture(tmp_path, monkeypatch)
    m = json.loads(Path(cfg['input_ref']['path']).read_bytes())
    quotes = [json.loads(l) for l in Path(m['quotes']['path']).read_bytes().splitlines()]
    chosen = [v for v in quotes if v['symbol'] in ('AAA', 'BBB')]
    for v in chosen:
        v['symbol'] = {'AAA': 'BIL', 'BBB': 'VTI'}[v['symbol']]
    raw = b''.join(json.dumps(v, sort_keys=True, separators=(',', ':')).encode()+b'\n' for v in chosen)
    m.update(symbols=['BIL', 'VTI'], rows=len(chosen), quotes=put(tmp_path/'drawdown-quotes.ndjson', raw))
    cfg['input_ref'] = write(tmp_path/'drawdown-input.json', m)
    cfg['calendar_ref'] = write(tmp_path/'drawdown-calendar.json', cal)
    p.update(schema=adapter.SCHEMA, policy={'kind': 'QUANT_A_DRAWDOWN_RECOVERY',
        'semantic_candidate': adapter.SEMANTIC_CANDIDATE, 'policy_sha256': adapter.POLICY_SHA},
        symbols=['BIL', 'VTI'], cost_scenarios=deepcopy(adapter.COSTS),
        input_sha256=cfg['input_ref']['sha256'], calendar_sha256=cfg['calendar_ref']['sha256'],
        legs=[{'id': i, 'label': i, 'rule': rule, 'scale': [1, 1]} for i, rule in
              zip(adapter.IDS, ['DRAWDOWN', 'FULL_VTI', 'MONTHLY_HALF', 'FULL_BIL'])],
        primary_strategy='DRAWDOWN_GATE', primary_benchmark='FIXED_HALF', subperiods=[],
        criteria=[{'id': str(i), 'description': kind, 'kind': kind, 'left_id': 'DRAWDOWN_GATE',
                   **({'right_id': 'FIXED_HALF'} if i < 2 else {})}
                  for i, kind in enumerate(['DRAWDOWN_LE', 'TERMINAL_GE', 'POSITIVE_GROWTH'])])
    cfg['profile_ref'] = write(tmp_path/'drawdown-profile.json', p)
    cfg['code'] = code_binding()
    return root, cfg, p, cal


def history(count=252, last=F(100)):
    start = date(2000, 1, 1)
    return [(start+timedelta(days=i), last if i == count-1 else F(100)) for i in range(count)]


def test_exact_author_policy_and_static_binding():
    binding = adapter.policy_binding()
    assert code_binding()[adapter.POLICY_PATH] == binding[adapter.POLICY_PATH] == adapter.POLICY_SHA
    for old, last, kind, state in [(None, F(80), 'TARGET', False), (True, F(80), 'TARGET', False),
                                   (False, F(90), 'TARGET', True), (False, F(85), 'HOLD', False)]:
        rows = history(last=last)
        value, signal, observed = adapter.instruction(rows, old, rows[-1][0])
        assert (value['kind'], observed) == (kind, state)
        assert signal['previous_observed_risk_on'] is old
        if kind == 'TARGET':assert value['weights']['VTI'] == [int(state), 1]
        else:assert 'weights' not in value
    short = history(count=251)
    assert adapter.instruction(short, None, short[-1][0])[0] == {'kind': 'HOLD'}
    rows = history(count=253, last=F(90)); rows[0] = (rows[0][0], F(120))
    assert adapter.instruction(rows, False, rows[-1][0])[2] is True
    with pytest.raises(ValueError, match='NONCAUSAL'):
        adapter.instruction(rows, False, rows[-2][0])
    rows[-1] = (rows[-1][0], 90.0)
    with pytest.raises(ValueError, match='EXACT_POSITIVE'):
        adapter.instruction(rows, False, rows[-1][0])


def test_plan_causal_state_hold_baselines_and_common_terminal(tmp_path, monkeypatch):
    root, cfg, p, cal = fixture(tmp_path, monkeypatch)
    service = ReferenceResearchService(root, 10**8)
    profile, _, _, grids, tz, market = prepare(service, cfg)
    first = grids['FINAL']['decisions'][0]['signal_date']
    market['prices_micro'][first]['VTI'] = 80*1000000
    # Invented prefix is flat100, then exit80, HOLD85 and reentry90. State is
    # carried even though no native account/fill exists during plan formation.
    for d in market['dates']:market['prices_micro'][d]['VTI'] = 100*1000000
    events = grids['FINAL']['decisions']
    market['prices_micro'][events[0]['signal_date']]['VTI'] = 80*1000000
    market['prices_micro'][events[1]['signal_date']]['VTI'] = 85*1000000
    market['prices_micro'][events[2]['signal_date']]['VTI'] = 90*1000000
    plan = plan_phase(market, profile, grids['FINAL'], tz)
    gate = [d['instructions']['DRAWDOWN_GATE'] for d in plan['decisions']]
    assert [x['kind'] for x in gate[:3]] == ['TARGET', 'HOLD', 'TARGET']
    assert [s['observed_risk_on'] for s in plan['signals'][:3]] == [False, False, True]
    assert plan['signals'][1]['previous_observed_risk_on'] is False
    assert all(d['instructions']['FULL_VTI']['kind'] == 'HOLD' for d in plan['decisions'][1:-1])
    assert all(x['kind'] == 'EXIT' for x in plan['decisions'][-1]['instructions'].values())
    for d in plan['decisions']:
        assert d['known_ns'] < d['decision_ns'] < d['open_ns']
    # An unknown future price cannot affect an earlier signal.
    changed = deepcopy(market); changed['prices_micro'][events[3]['signal_date']]['VTI'] = 100000000000
    assert plan_phase(changed, profile, grids['FINAL'], tz)['signals'][:3] == plan['signals'][:3]


def test_closed_profile_rejects_policy_and_threshold_substitution(tmp_path, monkeypatch):
    _, _, p, _ = fixture(tmp_path, monkeypatch)
    assert profile_value(p) == p
    for key, value in [('policy', {**p['policy'], 'window': 200}), ('symbols', ['SHY', 'VTI']),
                       ('cost_scenarios', []), ('decision_delay_seconds', 1)]:
        changed = deepcopy(p); changed[key] = value
        with pytest.raises(ValueError):profile_value(changed)


def test_complete_invented_scheduled_lifecycle_reuses_frozen_plan(tmp_path, monkeypatch):
    root, cfg, p, _ = fixture(tmp_path, monkeypatch)
    service = ReferenceResearchService(root, 10**8)
    import polar.scheduled_service as scheduled
    real_plan = scheduled.plan_phase; calls = []
    def once(*args):
        calls.append(True); return real_plan(*args)
    monkeypatch.setattr(scheduled, 'plan_phase', once)
    assert preflight(service, cfg)['expected_native_accounts'] == 16
    result = run(service, cfg)
    assert len(calls) == 2
    assert recompute(service, result['semantic_id'])['native_calls'] == 0
    with pytest.raises(ValueError, match='ORIGINAL_ALREADY_RECORDED'):run(service, cfg)


def test_wrong_loaded_policy_or_modified_blob_never_forms_a_binding(tmp_path, monkeypatch):
    fake = tmp_path/'policy.py'; fake.write_text('# invented foreign module\n')
    monkeypatch.setattr(adapter.author, '__file__', str(fake))
    with pytest.raises(ValueError, match='STATIC_IMPORT_BINDING'):code_binding()
