"""Closed CLI context bridge; no live native task/source or financial execution."""
import json
import subprocess
import sys

import pytest
from polar import native_selected_tool as tool
from polar import research_native_tool as transport
from polar.research_results import ResearchError
from test_native_selected_input import fixture, TASK, ADMISSION


def test_closed_native_read_allowlist():
    cfg = {'consumer_task': TASK, 'source_admission_ref': ADMISSION+'#3'}
    assert tool.permitted(['queue', 'show', TASK, '--full'], cfg)
    assert tool.permitted(['queue', 'transitions', ADMISSION, '--full'], cfg)
    assert not tool.permitted(['queue', 'claim', TASK], cfg)
    from polar.native_selected_input import generation_read
    assert tool.permitted(list(generation_read('quant-a@polar-rig')), cfg)
    for args in [['queue', 'show', 'qitem-foreign', '--full'], ['queue', 'claim', 'qitem-foreign'],
                 ['seat', 'status', 'quant-validator@polar-rig'], ['whoami', '--source', 'forged']]:
        assert not tool.permitted(args, cfg)


def test_input_bridge_delivers_config_and_each_live_tool_read(tmp_path, monkeypatch):
    _, cfg, queue, _, _ = fixture(tmp_path, monkeypatch)
    real_start = subprocess.Popen
    script = '''import json,sys
initial=json.loads(sys.stdin.readline())
assert initial['value']['consumer_task']=='qitem-invented-author'
print(json.dumps({'native_read':['whoami']}),flush=True)
reply=json.loads(sys.stdin.readline())
print(json.dumps({'result':{'actor':reply['value']['identity']['sessionName'],'values':'NOT_RETURNED'}}),flush=True)
'''
    def start(command, **kwargs):
        assert command[:8] == ['docker', 'exec', '-i', 'a'*12, 'python', '-u', '-m', 'polar.native_selected_tool']
        return real_start([sys.executable, '-u', '-c', script], **kwargs)
    monkeypatch.setattr(transport.subprocess, 'Popen', start)
    assert tool.bridge('a'*12, 'research-input-prepare', cfg, queue=queue) == {
        'actor': 'quant-a@polar-rig', 'values': 'NOT_RETURNED'}


def test_source_check_precedes_config_and_settings(monkeypatch):
    monkeypatch.setattr(tool, 'source_identity', lambda: 'a'*64)
    monkeypatch.setattr(tool, 'selected_config', lambda *a: pytest.fail('config opened before source check'))
    with pytest.raises(ResearchError, match='SOURCE_MISMATCH'):
        tool.consume('research-input-prepare', {}, 'b'*64)
    with pytest.raises(ResearchError, match='TOOL_OPERATION'):
        tool.bridge('not-a-container', 'research-run', {})


def test_real_file_only_consumer_uses_inherited_context_and_no_database(tmp_path, monkeypatch):
    from polar.config import Settings
    root, cfg, queue, _, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(tool, 'ToolPipe', lambda: queue)
    monkeypatch.setattr(Settings, 'load_artifacts', classmethod(lambda cls: Settings('unused-file-only', root)))
    out = tool.consume('research-input-prepare', cfg, tool.source_identity())
    assert out['status'] == 'PREPARED_SOURCE_ONLY'
    assert tool.consume('research-input-preflight', out['input_ref'], tool.source_identity())['symbols'] == 2


def test_actual_stdio_consumer_process_prepares_and_reads_only_invented_selected_values(tmp_path, monkeypatch):
    root, cfg, queue, parent, _ = fixture(tmp_path, monkeypatch)
    real_start = subprocess.Popen
    import os
    monkeypatch.setenv('POLAR_ARTIFACT_ROOT', str(root))
    def start(command, **kwargs):
        # Substitute only Docker's outer invocation. Run the actual source
        # module/stdio consumer in this locked runtime, not a mock responder.
        assert command[:8] == ['docker', 'exec', '-i', 'a'*12, 'python', '-u', '-m', 'polar.native_selected_tool']
        return real_start([sys.executable, '-u', '-m', 'polar.native_selected_tool', *command[8:]], **kwargs)
    monkeypatch.setattr(transport.subprocess, 'Popen', start)
    out = tool.bridge('a'*12, 'research-input-prepare', cfg, queue=queue)
    assert out['status'] == 'PREPARED_SOURCE_ONLY'
    assert tool.bridge('a'*12, 'research-input-preflight', out['input_ref'], queue=queue)['symbols'] == 2
    assert tool.bridge('a'*12, 'native-context-probe', {'consumer_task': TASK}, queue=queue)['source_admission'] == 'NOT_ISSUED_BY_PROBE'
    cfg['source_admission_ref'] = None
    with pytest.raises(ResearchError, match='SOURCE_ADMISSION_REQUIRED'):
        tool.bridge('a'*12, 'research-input-prepare', cfg, queue=queue)


def test_metadata_probe_runs_before_source_admission_without_store_or_source_pins(tmp_path, monkeypatch):
    from polar.config import Settings
    _, _, queue, _, _ = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(tool, 'ToolPipe', lambda: queue)
    monkeypatch.setattr(Settings, 'load_artifacts', classmethod(lambda cls: pytest.fail('store opened by metadata probe')))
    result = tool.consume('native-context-probe', {'consumer_task': TASK}, tool.source_identity())
    assert result['status'] == 'CURRENT_NATIVE_CONSUMER_CUSTODY_VERIFIED'
    assert result['source_admission'] == 'NOT_ISSUED_BY_PROBE'
    assert all(call[:2] != ('queue', 'claim') for call in queue.calls)
