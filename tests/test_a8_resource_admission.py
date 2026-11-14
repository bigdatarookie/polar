"""Invented metadata only: per-supervisor caps must be reserved in aggregate."""
from pathlib import Path
import pytest
from polar.gym_contract import canonical,decode,sha
from polar.signed_pair_operation import binding,registry
from test_signed_pair_operation import fixture,put


@pytest.mark.parametrize('limited',['global','store'])
def test_one_log_pair_headroom_rejected_before_debit_or_values(tmp_path,monkeypatch,limited):
    import polar.signed_pair_operation as module
    service,cfg,_=fixture(tmp_path)
    resources=decode(Path(cfg['resources_ref']['path']).read_bytes())
    bound=resources['limits']
    single=bound['operation_store_bytes']+bound['log_bytes']+bound['journal_bytes']
    if limited=='global':resources['global_storage_headroom_bytes']=single
    else:service.store.limit=single
    cfg['resources_ref']=put(Path(cfg['resources_ref']['path']),resources)
    authority=decode(Path(cfg['authority_ref']['path']).read_bytes())
    authority.update(binding_sha256=sha(canonical(binding(cfg))),resources_sha256=cfg['resources_ref']['sha256'])
    cfg['authority_ref']=put(Path(cfg['authority_ref']['path']),authority)
    manifest=decode(Path(cfg['source_manifest_ref']['path']).read_bytes())
    read=module.read_ref
    def metadata_only(ref):
        assert ref!=manifest['encoded_input'],'SOURCE_VALUES_FORBIDDEN'
        return read(ref)
    monkeypatch.setattr(module,'read_ref',metadata_only)
    with pytest.raises(Exception,match='PAIR_OPERATION_CURRENT_RESOURCE_ADMISSION'):
        service.preflight(cfg)
    assert registry(service.store,cfg)==[]
    assert not (service.store.root/'scheduled-reference-attempts').exists()


def test_exact_four_log_pair_boundary_accepts_metadata_only(tmp_path):
    service,cfg,_=fixture(tmp_path)
    resources=decode(Path(cfg['resources_ref']['path']).read_bytes());bound=resources['limits']
    total=bound['operation_store_bytes']+4*(bound['log_bytes']+bound['journal_bytes'])
    resources['global_storage_headroom_bytes']=total;service.store.limit=total
    cfg['resources_ref']=put(Path(cfg['resources_ref']['path']),resources)
    authority=decode(Path(cfg['authority_ref']['path']).read_bytes())
    authority.update(binding_sha256=sha(canonical(binding(cfg))),resources_sha256=cfg['resources_ref']['sha256'])
    cfg['authority_ref']=put(Path(cfg['authority_ref']['path']),authority)
    assert service.preflight(cfg)['source_values_read']==0
    assert registry(service.store,cfg)==[]


@pytest.mark.parametrize('stage,calls',[('ORIGINAL',4),('SAVED',2)])
def test_log_journal_and_cleanup_share_exact_supervisor_census(stage,calls):
    from polar.signed_pair_operation import operation_storage_bound,supervision_phases
    assert len(supervision_phases(stage))==calls
    assert operation_storage_bound({'operation_store_bytes':101,'log_bytes':7,'journal_bytes':11},stage)==101+calls*18
