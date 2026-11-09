from types import SimpleNamespace
import pytest
from polar.capability_contract import CapabilityError
from polar.capability_runtime import ObservedRuntime


def test_reobserved_periodic_receipt_after_final_does_not_rollback_charge():
    r=SimpleNamespace(worker_cpu=873371,worker_sample_cpu=873371,native_ns=67026999)
    r.worker_cpu=897718;r.native_ns=100880040  # actual retained final receipt
    ObservedRuntime.sample_usage(r,{'cpu_us':873371,'native_wall_ns':67026999})
    assert r.worker_cpu==897718 and r.native_ns==100880040
    ObservedRuntime.sample_usage(r,{'cpu_us':873371,'native_wall_ns':67026999})
    assert r.worker_cpu==897718


@pytest.mark.parametrize('value',[873370,True,-1,'873371'])
def test_real_periodic_regression_or_bad_type_still_rejects(value):
    r=SimpleNamespace(worker_cpu=897718,worker_sample_cpu=873371,native_ns=100880040)
    with pytest.raises(CapabilityError,match='INTERNAL_EXECUTION_ERROR'):
        ObservedRuntime.sample_usage(r,{'cpu_us':value,'native_wall_ns':67026999})
    assert r.worker_cpu==897718 and r.worker_sample_cpu==873371


def test_packet_producer_uses_the_frozen_manifest_schema_tag(tmp_path,monkeypatch):
    import polar.capability_store as store
    from polar.capability_contract import FILES,PROFILE_ID,SCHEMA
    captured={}
    real_validate=store.validate
    def validate(value,name):
        if name=='semantic_manifest':return real_validate(value,name)
        return value  # member bodies are deliberately outside this affected literal control
    monkeypatch.setattr(store,'validate',validate)
    p=store.PacketStore(tmp_path,64*1024**3)
    monkeypatch.setattr(p,'_publish',lambda parent,pid,files,**kw:captured.update(files))
    p.publish({n:{'stage_status':'COMPLETE'} for n in FILES},'a'*64)
    import json
    manifest=json.loads(captured['semantic-manifest.json'])
    assert manifest['schema']==SCHEMA['$defs']['semantic_manifest']['properties']['schema']['const']
