"""Bounded stdio transport controls; actual container/native proof is separate."""
import json
import subprocess
import sys

import pytest

from polar import research_native_tool as tool
from polar.config import Settings
from polar.research_results import ResearchError

REF = 'qitem-invented-binding#3'
CID = '1'*12


@pytest.mark.parametrize('args', [
    ['queue','show','qitem-other','--full'], ['queue','claim','qitem-invented-binding'],
    ['send','quant-validator@polar-rig','forged'], ['seat','status','quant-a@polar-rig'],
    ['whoami','--source','forged'], ['whoami; echo unsafe'],
])
def test_native_read_scope_excludes_writes_foreign_tasks_and_actor_overrides(args):
    assert not tool.permitted(args, REF)


def peer(monkeypatch, script):
    original = subprocess.Popen
    def start(command, **kwargs):
        assert command[:5] == ['docker','exec','-i',CID,'python']
        assert command[5:8] == ['-u','-m','polar.research_native_tool']
        assert '--source-sha256' in command
        return original([sys.executable,'-u','-c',script], **kwargs)
    monkeypatch.setattr(tool.subprocess, 'Popen', start)


def test_bridge_uses_each_actual_host_adapter_read_and_no_actor_environment(monkeypatch):
    peer(monkeypatch, '''import json,sys
print(json.dumps({'native_read':['whoami']}),flush=True)
r=json.loads(sys.stdin.readline())
print(json.dumps({'result':{'native_actor':r['value']['identity']['sessionName']}}),flush=True)
''')
    class Adapter:
        def read(self, *args):
            assert args == ('whoami',)
            return {'identity':{'sessionName':'invented-actual-host@rig'}}
    assert tool.bridge(CID,'probe',REF,queue=Adapter()) == {'native_actor':'invented-actual-host@rig'}


def test_bridge_rejects_unsolicited_native_operation_and_closes_owned_peer(monkeypatch):
    peer(monkeypatch, '''import json,sys
print(json.dumps({'native_read':['queue','claim','qitem-invented-binding']}),flush=True)
sys.stdin.readline()
''')
    class Adapter:
        def read(self, *args): pytest.fail('Unauthorized tool called')
    with pytest.raises(ResearchError, match='RESEARCH_NATIVE_TOOL_PROTOCOL'):
        tool.bridge(CID,'probe',REF,queue=Adapter())


def test_consumer_source_and_writer_gate_before_credentials_or_operations(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, 'source_identity', lambda: 'a'*64)
    monkeypatch.setattr(Settings,'load',classmethod(lambda cls: pytest.fail('Credentials opened before source match')))
    with pytest.raises(ResearchError, match='RESEARCH_NATIVE_CONSUMER_SOURCE_MISMATCH'):
        tool.consume('submit',REF,'b'*64)
    monkeypatch.setattr(Settings,'load',classmethod(lambda cls: Settings('unused',tmp_path)))
    with pytest.raises(ResearchError, match='RESEARCH_NATIVE_REVIEW_WRITER_DISABLED'):
        tool.consume('submit',REF,'a'*64)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('container', ['container-name', '../unsafe', 'a;touch something', '', '1'*65])
def test_container_address_is_exact_hex_id(container):
    with pytest.raises(ResearchError, match='RESEARCH_NATIVE_TOOL_OPERATION'):
        tool.bridge(container,'probe',REF)
