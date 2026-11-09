"""Invented admission/storage controls; no simulator, source data or retained run."""
import pytest
from polar.obs158_contract import canonical, sha
from polar.obs158_math import Obs158Error
from polar.obs158_service import Obs158Service
from polar.obs158_store import Obs158Store
import polar.obs158_service as service_module


def authorization(maximum=2):
    return {'family':'invented_admission_control','max_full_packet_starts':maximum}


def test_invented_appends_past_legacy_cap_without_changing_failed_history(tmp_path):
    store=Obs158Store(tmp_path,1024**2)
    first=store.begin_packet('INVENTED',{},authorization(1),None)
    store.finish_packet(first['attempt_id'],{'status':'FAILED','code':'INVENTED_FAILURE'})
    before={str(p.relative_to(tmp_path)):p.read_bytes() for p in tmp_path.rglob('record.json')}
    for ordinal in (1,2,3):
        row=store.begin_packet('INVENTED',{},authorization(1),None)
        assert row['ordinal']==ordinal and row['family']==first['family']
    assert all((tmp_path/p).read_bytes()==body for p,body in before.items())
    assert store.packet(first['attempt_id'])['status']=='FAILED'
    assert first['status']=='UNFINALIZED'


def test_retained_first_success_then_exact_replay_only_and_two_start_limit(tmp_path):
    store=Obs158Store(tmp_path,1024**2);bindings={'control':'literal'}
    first=store.begin_packet('RETAINED',bindings,authorization(),None)
    store.finish_packet(first['attempt_id'],{'status':'SUCCESS','experiment_id':'literal-result'})
    with pytest.raises(Obs158Error,match='RETAINED_SECOND_START_REPLAY_ONLY'):
        store.begin_packet('RETAINED',bindings,authorization(),None)
    second=store.begin_packet('RETAINED',bindings,authorization(),'literal-result')
    assert second['ordinal']==1
    with pytest.raises(Obs158Error,match='OBS158_PACKET_BUDGET_EXHAUSTED'):
        store.begin_packet('RETAINED',bindings,authorization(),'literal-result')


def test_retained_failed_start_is_not_refunded_or_replayable(tmp_path):
    store=Obs158Store(tmp_path,1024**2)
    first=store.begin_packet('RETAINED',{},authorization(),None)
    store.finish_packet(first['attempt_id'],{'status':'FAILED'})
    with pytest.raises(Obs158Error,match='REPLAY_BINDING_MISMATCH'):
        store.begin_packet('RETAINED',{},authorization(),'literal-result')
    with pytest.raises(Obs158Error,match='RETAINED_SECOND_START_REPLAY_ONLY'):
        store.begin_packet('RETAINED',{},authorization(),None)


@pytest.mark.parametrize('namespace,maximum,valid',[
    ('INVENTED',1,True),('INVENTED',2,True),('INVENTED',3,True),
    ('INVENTED',False,False),('INVENTED',0,False),
    ('RETAINED',2,True),('RETAINED',1,False),('RETAINED',3,False)])
def test_authorization_representation_preserves_retained_authority(
        tmp_path,monkeypatch,namespace,maximum,valid):
    store=Obs158Store(tmp_path,1024**2);bindings={'control':'literal'}
    auth={'schema':'polar.obs158-execution-authorization/1',
          'bindings_sha256':sha(canonical(bindings)),'artifact_root':str(tmp_path.resolve()),
          'operations':['RUN'],'purpose':'FIXED_PAIR_AND_REPLAY' if namespace=='RETAINED'
              else 'INVENTED_FIXED_PAIR','family':'literal_family','max_full_packet_starts':maximum,
          'limits':{'total_wall_seconds':60,'native_wall_seconds':30,'cleanup_reserve_seconds':5}}
    monkeypatch.setattr(service_module,'read_bound',lambda ref,limit:canonical(auth))
    config={'authorization_ref':{},'source_class':namespace}
    if valid:
        assert Obs158Service(store).authorization(config,bindings,'RUN')==auth
    else:
        with pytest.raises(Obs158Error,match='OBS158_PACKET_BUDGET'):
            Obs158Service(store).authorization(config,bindings,'RUN')
