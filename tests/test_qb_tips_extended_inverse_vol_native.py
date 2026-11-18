"""Invented expanded-cohort native integration; no archived TIP inputs."""
from hashlib import sha256
import json
from pathlib import Path
import pytest

from polar.qb_tips_extended_inverse_vol import profile, SYMBOLS
from polar.reference_service import ReferenceResearchService
from polar.research_results import ResearchResults
from reference_fixture import write
from test_scheduled_erc import fixture as four_asset_fixture
from test_scheduled_service import snapshot


def test_fixed_five_asset_profile_native_accounts_and_saved_only(tmp_path, monkeypatch):
    root, old, _, _ = four_asset_fixture(tmp_path, monkeypatch)
    manifest = json.loads(Path(old['input_ref']['path']).read_bytes())
    path = Path(manifest['quotes']['path'])
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    extra = []
    for i, row in enumerate(r for r in rows if r['symbol'] == 'BIL'):
        micro = 80_000_000 + (i*i*3571+i*7919) % 1_000_000
        token = f'{micro//1_000_000}.{micro%1_000_000:06d}'
        extra.append({**row, 'symbol':'TIP', 'reference_quote':token,
                      'source_adjusted_close_token':token})
    rows.extend(extra)
    rows.sort(key=lambda row:(row['date'],row['symbol']))
    path.write_bytes(b''.join((json.dumps(row,sort_keys=True)+'\n').encode() for row in rows))
    manifest.update(symbols=list(SYMBOLS), rows=len(rows), quotes={
        'path':str(path),'sha256':sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    source = write(tmp_path/'invented-five-asset-input.json',manifest)
    p = profile(protocol_sha256=old['protocol_ref']['sha256'],input_sha256=source['sha256'],
                calendar_sha256=old['calendar_ref']['sha256'],timezone_sha256=old['timezone_ref']['sha256'])
    cfg = {**old,'input_ref':source,'profile_ref':write(tmp_path/'author-profile.json',p),
           'candidate_id':'INVENTED-QB-TIP-EXPANSION','experiment_id':'INVENTED-QB-TIP-EXPANSION-ORIGINAL'}
    assert cfg['namespace'] == 'INVENTED'
    service = ReferenceResearchService(root,128*1024**2)
    assert service.preflight(cfg)['scientific_starts'] == 0
    result = service.run(cfg)
    assert result['status'] == 'SUCCESS'
    directory = root/'reference-research-experiments'/result['semantic_id']
    phases = json.loads((directory/'phases.json').read_bytes())
    assert phases['FINAL']['plan']['decisions'] == phases['FINAL_COST_STRESS']['plan']['decisions']
    for phase, scenario in zip(('FINAL','FINAL_COST_STRESS'),p['cost_scenarios']):
        data = phases[phase]
        assert data['simulation']['cost_profile'] == scenario['cost_profile']
        assert {leg['id'] for leg in data['simulation']['legs']} == {'INV','EW','MOM'}
        for leg in data['simulation']['legs']:
            assert set(leg['nav'][-1]['positions']) == set(SYMBOLS)
            assert not any(leg['nav'][-1]['positions'].values())
        record = ResearchResults(root,128*1024**2).read(result['results'][phase]['result_id'])
        assert len(record['record']['criteria']) == 9
        assert record['assessment']['financial'] == 'NOT_REVIEWED'
    with pytest.raises(ValueError,match='SCHEDULED_ORIGINAL_ALREADY_RECORDED'):
        service.run(cfg)
    before = snapshot(root)
    import polar.scheduled_service as module

    def forbidden(*args,**kwargs):
        raise AssertionError('SAVED_SOURCE_POLICY_OR_NATIVE_EXECUTION')

    for name in ('load_reference','load_market','plan_phase','bounded_native','read_ref'):
        monkeypatch.setattr(module,name,forbidden)
    reproduced = service.recompute(result['semantic_id'])
    assert reproduced['status'] == 'REPRODUCED'
    assert reproduced['native_calls'] == reproduced['store_writes'] == 0
    assert snapshot(root) == before
