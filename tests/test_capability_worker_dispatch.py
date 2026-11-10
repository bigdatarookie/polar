"""Mocked module-entry controls; no packet family, score restore or native calls."""
import importlib
from pathlib import Path
import runpy
import sys
import pytest
from polar.capability_store import record


def setup_prepare(tmp_path,monkeypatch,fail=None):
    import polar.capability_inputs as inputs
    import polar.capability_profile as profile
    cfg=tmp_path/'config.json';cfg.write_text('{}\n')
    class Admitted:
        def __init__(self,config):assert config=={}
        def load(self):
            if fail is not None:raise fail
            return {'score_rows':['invented'],'scores_payload':{},'observations':[], 'lineage_refs':{}}
    monkeypatch.setattr(inputs,'AdmittedInputs',Admitted)
    monkeypatch.setattr(profile,'targets',lambda rows:{'literal_targets':rows})
    monkeypatch.setattr(sys,'argv',['polar.capability_worker','--prepare',str(cfg),str(tmp_path)])


def test_module_entry_calls_prepare_and_writes_output(tmp_path,monkeypatch):
    setup_prepare(tmp_path,monkeypatch)
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module('polar.capability_worker',run_name='__main__')
    assert stopped.value.code==0
    result=record(tmp_path/'prepared-native.json')
    assert result['schema']=='polar.capability-prepared-native/1'
    assert result['targets']=={'literal_targets':['invented']}
    assert not (tmp_path/'preparation-failure.json').exists()


def test_module_prepare_retains_bounded_unicode_failure(tmp_path,monkeypatch):
    setup_prepare(tmp_path,monkeypatch,ValueError('failure-'+ '\U0001f680'*10000))
    with pytest.raises(SystemExit) as stopped:
        runpy.run_module('polar.capability_worker',run_name='__main__')
    assert stopped.value.code==1
    failure=record(tmp_path/'preparation-failure.json')
    assert failure['error_type']=='ValueError'
    assert 0<len(failure['traceback'].encode('utf-8'))<=16384
    assert not (tmp_path/'prepared-native.json').exists()


def test_import_is_inert_and_nonprepare_still_dispatches_worker(monkeypatch):
    module=importlib.import_module('polar.capability_worker')
    seen=[]
    monkeypatch.setattr(module,'worker',lambda *args:seen.append(args) or 23)
    monkeypatch.setattr(sys,'argv',['module','INPUT','EXPECTED','CONFIG','OUTPUT'])
    assert module.main()==23 and seen==[('INPUT','EXPECTED','CONFIG','OUTPUT')]
