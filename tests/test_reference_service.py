"""Executable invented one-fit/two-phase service and stored-only/API wire controls."""
import hashlib
import json
from pathlib import Path
import pytest
from polar.reference_service import ReferenceResearchService,A
from polar.research_results import ResearchResults
from reference_fixture import fixture,write


def test_one_fit_two_phases_public_wire_and_no_second_original(tmp_path,monkeypatch):
    root,cfg=fixture(tmp_path,monkeypatch);svc=ReferenceResearchService(root,64*1024**2)
    ready=svc.preflight(cfg);assert ready['scientific_starts']==0
    out=svc.run(cfg);assert out['status']=='SUCCESS' and out['fit_calls']==1 and len(out['results'])==2
    for phase,published in out['results'].items():
        record=ResearchResults(root,64*1024**2).read(published['result_id'])['record']
        assert record['basis']['wealth_basis']=='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT'
        assert record['primary_benchmark_id']=='EW4_MONTHLY'
        assert 'source_coverage' not in record  # preserve immutable legacy wire and IDs
        assert len(record['criteria'])==(4 if phase=='FINAL' else 0)
        assert not any(l['code']=='PRICE_ONLY_DIVIDENDS_OMITTED' for l in record['limitations'])
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    import polar.reference_service as service
    def forbidden(*a,**kw):raise AssertionError('STORED_RECOMPUTE_CALLED_MODEL_OR_NATIVE')
    monkeypatch.setattr(service,'fit_ridge',forbidden);monkeypatch.setattr(service,'bounded_native',forbidden)
    assert svc.recompute(out['semantic_id'])['status']=='REPRODUCED'
    after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    assert before==after
    with pytest.raises(ValueError,match='REFERENCE_ORIGINAL_ALREADY_RECORDED'):svc.run(cfg)


def test_retained_source_cannot_be_relabeled_invented(tmp_path,monkeypatch):
    root,cfg=fixture(tmp_path,monkeypatch)
    cfg['input_ref']['sha256']='070ea3eb9363894aa37ec4254997be34116b745166b173e1ab1e7dcc4182e3cd'
    with pytest.raises(ValueError,match='RETAINED_AS_INVENTED_FORBIDDEN'):
        ReferenceResearchService(root,64*1024**2).preflight(cfg)


@pytest.mark.parametrize('field,value', [('rights','LICENSED_PRIVATE'),('parent_dataset_revision','PRIVATE-ANOTHER-REVISION'),
    ('provenance',{'kind':'RETAINED_SOURCE','producer':'vendor','source_payloads':'PRIVATE'})])
def test_invented_requires_positive_rights_and_provenance(tmp_path,monkeypatch,field,value):
    root,cfg=fixture(tmp_path,monkeypatch);path=Path(cfg['input_ref']['path'])
    manifest=json.loads(path.read_text());manifest[field]=value;cfg['input_ref']=write(path,manifest)
    import polar.reference_service as service
    def forbidden(*a,**k):raise AssertionError('UNADMITTED_SOURCE_NUMERIC_LOADER')
    monkeypatch.setattr(service,'load_reference',forbidden)
    with pytest.raises(ValueError,match='REFERENCE_INVENTED_RIGHTS_PROVENANCE'):
        ReferenceResearchService(root,64*1024**2).preflight(cfg)


@pytest.mark.parametrize('target',['calendar_ref','timezone_ref','protocol_ref'])
def test_invented_control_rejects_unbound_protocol_calendar_timezone(tmp_path,monkeypatch,target):
    root,cfg=fixture(tmp_path,monkeypatch);path=Path(cfg[target]['path'])
    if target=='timezone_ref':
        path.write_bytes(path.read_bytes()+b'changed')
        cfg[target]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    else:
        value=json.loads(path.read_text());value['changed']=True;cfg[target]=write(path,value)
    import polar.reference_service as service
    def forbidden(*a,**k):raise AssertionError('UNADMITTED_SOURCE_NUMERIC_LOADER')
    monkeypatch.setattr(service,'load_reference',forbidden)
    with pytest.raises(ValueError,match='REFERENCE_INVENTED_PROTOCOL_BINDING'):
        ReferenceResearchService(root,64*1024**2).preflight(cfg)


def test_frozen_A_cannot_be_used_as_invented_control(tmp_path,monkeypatch):
    root,cfg=fixture(tmp_path,monkeypatch);cfg['profile_id']=A
    with pytest.raises(ValueError,match='REFERENCE_PROFILE_NAMESPACE'):
        ReferenceResearchService(root,64*1024**2).preflight(cfg)
