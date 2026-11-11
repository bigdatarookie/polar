"""Invented six-account stress and saved uncertainty through the same service."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from polar.scheduled_policy import profile_value
from scheduled_fixture import inverse_fixture


def test_inverse_base_stress_publication_and_saved_only(tmp_path, monkeypatch):
    root,cfg,profile,calendar = inverse_fixture(tmp_path,monkeypatch)
    service = ReferenceResearchService(root,128*1024**2)
    ready = service.preflight(cfg)
    assert ready['expected_native_accounts'] == 6 and ready['fit_calls'] == 0
    output = service.run(cfg)
    assert output['native_accounts'] == 6 and output['fit_calls'] == output['predict_calls'] == 0
    assert set(output['results']) == {'FINAL','FINAL_COST_STRESS'}
    directory = root/'reference-research-experiments'/output['semantic_id']
    phases = json.loads((directory/'phases.json').read_bytes())
    base,stress = phases['FINAL'],phases['FINAL_COST_STRESS']
    assert {k:v for k,v in base['plan'].items() if k != 'cost_profile'} == {k:v for k,v in stress['plan'].items() if k != 'cost_profile'}
    assert base['plan']['cost_profile'] == {'flat_cents':100,'bps':10}
    assert stress['plan']['cost_profile'] == {'flat_cents':200,'bps':20}
    for phase in phases.values():
        assert len(phase['simulation']['legs']) == 3
        assert len(phase['evaluation']['criteria']) == 10
        assert all(not any(t['nav'][-1]['positions'].values()) for t in phase['simulation']['legs'])
    for phase,publication in output['results'].items():
        record = ResearchResults(root,128*1024**2).read(publication['result_id'])['record']
        assert len(record['metrics']) == (40 if phase == 'FINAL' else 32) and len(record['criteria']) == 10
        assert any(x['code'] == 'CONDITIONAL_ROBUSTNESS' for x in record['limitations'])
        assert any(x['id'] == 'base_bootstrap_sr_valid_count' for x in record['metrics'])
        descriptions = ' '.join(x['description'] for x in record['costs'])
        assert ('20bps' in descriptions) == (phase == 'FINAL_COST_STRESS')
    uncertainty = json.loads((directory/'uncertainty.json').read_bytes())
    assert uncertainty['samples'] == 1000 and len(uncertainty['comparisons']) == 2
    assert uncertainty['robustness'] in ('INSUFFICIENT_EVIDENCE','PASS_CONDITIONAL_EXPOSED_SCENARIO_ONLY')
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    import polar.scheduled_service as module
    def forbidden(*args,**kwargs):raise AssertionError('SAVED_REPRODUCTION_CALLED_SOURCE_OR_NATIVE')
    for name in ('bounded_native','plan_phase','load_reference'): monkeypatch.setattr(module,name,forbidden)
    result = service.recompute(output['semantic_id'])
    assert result['status'] == 'REPRODUCED' and all(result[k] == 0 for k in ('fit_calls','predict_calls','native_calls','store_writes'))
    assert before == {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_inverse_cost_and_uncertainty_closed(tmp_path, monkeypatch):
    _,_,p,_ = inverse_fixture(tmp_path,monkeypatch)
    assert profile_value(p) == p
    for mutate in ('cost','replicates','cap','scale'):
        q=deepcopy(p)
        if mutate=='cost':q['cost_scenarios'][1]['cost_profile']['flat_cents']=100
        elif mutate=='replicates':q['uncertainty']['replicates']=999
        elif mutate=='cap':q['policy']['annual_cap']='0.11'
        else:q['legs'][0]['scale']=[1,2]
        with pytest.raises(ValueError):profile_value(q)


def test_inverse_first_targets_ignore_every_future_quote(tmp_path, monkeypatch):
    from polar.research_reference import load_reference
    from polar.scheduled_policy import plan_phase
    from zoneinfo import ZoneInfo
    _,cfg,p,c = inverse_fixture(tmp_path,monkeypatch)
    market = load_reference(cfg['input_ref']); grid=c['phases']['FINAL']; tz=ZoneInfo('America/New_York')
    original = plan_phase(market,p,grid,tz)
    changed = deepcopy(market); end=grid['decisions'][0]['signal_index']
    for day in changed['dates'][end+1:]:
        changed['prices_micro'][day] = {symbol:999999999 for symbol in p['symbols']}
    altered = plan_phase(changed,p,grid,tz)
    assert original['decisions'][0] == altered['decisions'][0]
    assert original['signals'][0] == altered['signals'][0]
