"""Exact author composition through native accounts on invented data only."""
import json
from pathlib import Path

import pytest

from polar.qb_risk_matched_priced_reserve import profile
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from reference_fixture import write
from test_scheduled_priced_reserve import fixture
from test_scheduled_service import snapshot


def test_author_profile_native_costs_publishing_and_saved_only(tmp_path, monkeypatch):
    root, cfg, _, _ = fixture(tmp_path, monkeypatch)
    p = profile(protocol_sha256=cfg['protocol_ref']['sha256'],
                input_sha256=cfg['input_ref']['sha256'],
                calendar_sha256=cfg['calendar_ref']['sha256'],
                timezone_sha256=cfg['timezone_ref']['sha256'])
    cfg['profile_ref'] = write(tmp_path/'author-profile.json', p)
    cfg.update(candidate_id='INVENTED-QB-PRICED-RESERVE',
               experiment_id='INVENTED-QB-PRICED-RESERVE-ORIGINAL')
    assert cfg['namespace'] == 'INVENTED'
    service = ReferenceResearchService(root, 128*1024**2)
    assert service.preflight(cfg)['scientific_starts'] == 0
    result = service.run(cfg)
    assert result['status'] == 'SUCCESS'
    assert set(result['results']) == {'FINAL', 'FINAL_COST_STRESS'}
    directory = root/'reference-research-experiments'/result['semantic_id']
    phases = json.loads((directory/'phases.json').read_bytes())
    assert phases['FINAL']['plan']['decisions'] == phases['FINAL_COST_STRESS']['plan']['decisions']
    for phase, scenario in zip(('FINAL', 'FINAL_COST_STRESS'), p['cost_scenarios']):
        data = phases[phase]
        assert data['simulation']['cost_profile'] == scenario['cost_profile']
        assert [leg['id'] for leg in data['simulation']['legs']] == ['SWEPT', 'CASH_TARGET', 'BIL_ONLY']
        assert len(data['evaluation']['criteria']) == 6
        for leg in data['simulation']['legs']:
            assert not any(leg['nav'][-1]['positions'].values())
        record = ResearchResults(root, 128*1024**2).read(result['results'][phase]['result_id'])
        assert record['assessment']['financial'] == 'NOT_REVIEWED'
        assert record['record']['primary_benchmark_id'] == 'CASH_TARGET'
        assert len(record['record']['criteria']) == 6
    before = snapshot(root)
    import polar.scheduled_service as module
    import polar.scheduled_priced_reserve as adapter
    import polar.qb_priced_reserve_prototype as author

    def forbidden(*args, **kwargs):
        raise AssertionError('SAVED_SOURCE_ESTIMATOR_SELECTOR_OR_NATIVE_CALL')

    for name in ('load_reference', 'load_market', 'plan_phase', 'bounded_native', 'read_ref'):
        monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(adapter, 'sample_covariance', forbidden)
    monkeypatch.setattr(author, 'reserve_targets', forbidden)
    monkeypatch.setattr(author, '_select', forbidden)
    reproduced = service.recompute(result['semantic_id'])
    assert reproduced['status'] == 'REPRODUCED'
    assert all(reproduced[k] == 0 for k in
               ('estimator_calls', 'rule_calls', 'risk_search_calls', 'native_calls', 'store_writes'))
    assert snapshot(root) == before
    with pytest.raises(ValueError, match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):
        service.run(cfg)
