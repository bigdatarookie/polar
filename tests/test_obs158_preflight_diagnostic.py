"""Private-check metadata survives failure; no source, native operation or retry."""
from types import SimpleNamespace
import json
import pytest
from polar.obs158_contract import canonical
from polar.obs158_service import Obs158Service, preflight_diagnostic
from polar.obs158_store import Obs158Store
from polar.obs158_math import Obs158Error
import polar.obs158_service as module


def failed_report():
    return {'schema':'polar.obs158-preflight/1','checks':[
        {'code':'COMPLETE_UNIQUE_GRID','status':'PASS','reason':None,'required':True,'basis':'SUPPLIED_SOURCE'},
        {'code':'AGGREGATION_DATE','status':'FAIL','reason':'SOURCE_DATE_MISMATCH','required':True,'basis':'SUPPLIED_SOURCE'},
        {'code':'ACTUAL_RUNTIME_BINDING','status':'NOT_RUN','reason':'PART_B_NOT_IMPLEMENTED','required':True,'basis':'ENGINEERING'}],
        'bindings':{'PRIVATE_PATH':'/private/never-output','source_rows':['PRIVATE_SOURCE_SENTINEL']}}


def setup_failure(tmp_path,monkeypatch):
    tmp_path.mkdir(parents=True,exist_ok=True)
    svc=Obs158Service(Obs158Store(tmp_path,1024**2));report=failed_report()
    monkeypatch.setattr(svc,'binding',lambda config:{'source_code':{}})
    monkeypatch.setattr(svc,'authorization',lambda *a:{})
    monkeypatch.setattr(svc,'runtime',lambda *a:{})
    monkeypatch.setattr(svc,'controls',lambda *a:{})
    monkeypatch.setattr(svc,'inputs',lambda *a:SimpleNamespace(source_class='INVENTED'))
    monkeypatch.setattr(module,'convert_obs158',lambda *a:{})
    monkeypatch.setattr(module,'preflight_obs158',lambda *a:report)
    monkeypatch.setattr(module,'_simulate',lambda *a:pytest.fail('NATIVE_AFTER_FAILED_PREFLIGHT'))
    return svc,report


def test_preflight_keeps_exact_checks_and_failure_without_store_or_native(tmp_path,monkeypatch):
    svc,report=setup_failure(tmp_path,monkeypatch)
    with pytest.raises(Obs158Error,match='^OBS158_DATA_PREFLIGHT_DISALLOWED$') as raised:svc.preflight({})
    diagnostic=raised.value.preflight_diagnostic
    assert diagnostic['checks']==report['checks'] and diagnostic['runner_execution_allowed'] is False
    assert not list(tmp_path.iterdir()) # no original attempt, family budget or data write
    assert 'PRIVATE' not in canonical(diagnostic).decode()


def test_cli_nonzero_stderr_contains_checks_not_private_payload(tmp_path,monkeypatch,capsys):
    svc,report=setup_failure(tmp_path/'store',monkeypatch)
    original=svc.preflight
    def operation(self,config):return original(config)
    monkeypatch.setattr(Obs158Service,'preflight',operation)
    path=tmp_path/'config.json';path.write_bytes(b'{}')
    monkeypatch.setattr('sys.argv',['polar','obs158-preflight',str(path),'--artifact-root',str(tmp_path/'cli-store')])
    from polar.cli import main
    with pytest.raises(SystemExit) as raised:main()
    assert raised.value.code==1
    captured=capsys.readouterr();assert not captured.out
    result=json.loads(captured.err)
    assert result['code']=='OBS158_DATA_PREFLIGHT_DISALLOWED'
    assert result['preflight_diagnostic']['checks']==report['checks']
    assert 'PRIVATE' not in captured.err and 'source_rows' not in captured.err


def test_started_failed_run_retains_report_without_refund(tmp_path,monkeypatch):
    svc,report=setup_failure(tmp_path,monkeypatch)
    monkeypatch.setattr(svc,'authorization',lambda *a:{'family':'INVENTED_DIAGNOSTIC',
        'max_full_packet_starts':2,'limits':{'total_wall_seconds':60,'native_wall_seconds':30,'cleanup_reserve_seconds':5}})
    with pytest.raises(Obs158Error,match='OBS158_DATA_PREFLIGHT_DISALLOWED'):svc.run({'source_class':'INVENTED'})
    attempts=list((tmp_path/'obs158-attempts').iterdir());assert len(attempts)==1
    recorded=svc.attempt(attempts[0].name)
    assert recorded['status']=='FAILED' and recorded['finish']['preflight_diagnostic']['checks']==report['checks']
    assert recorded['start']['ordinal']==0


def test_arbitrary_or_oversized_diagnostic_cannot_echo_source_strings():
    report=failed_report();report['checks'][1]['reason']='/private/SECRET'
    assert preflight_diagnostic(report)['reason']=='INVALID_CHECK_METADATA'
    report=failed_report();report['checks']*=30
    assert preflight_diagnostic(report)['status']=='UNAVAILABLE'
