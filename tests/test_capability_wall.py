"""Focused, unexecuted repair fixtures: fake clock/process only, no Docker/native."""
import subprocess

import pytest

from polar.capability_contract import CapabilityError
from polar.capability_runtime import (
    _WallBudget, _stop_owned, _cleanup_owned, CLEANUP_RESERVE_NS, FINAL_ACCOUNTING_NS)


class Clock:
    def __init__(self):self.ns=1000000000000
    def __call__(self):return self.ns
    def advance(self,seconds):self.ns+=int(seconds*1000000000)


class Process:
    def __init__(self,clock,exits=False):
        self.clock=clock;self.exits=exits;self.pid=123456;self.returncode=None;self.waits=[]
    def poll(self):return self.returncode
    def wait(self,timeout=None):
        assert timeout is not None and timeout>0, 'No unbounded wait is permitted'
        self.waits.append(timeout)
        if self.exits:
            self.clock.advance(min(.1,timeout));self.returncode=0;return 0
        self.clock.advance(timeout)
        raise subprocess.TimeoutExpired('invented-owned-process',timeout)


def test_remaining_family_wall_preserves_cleanup_before_scenario():
    clock=Clock()
    wall=_WallBudget(clock(),860000000000,clock)
    assert CLEANUP_RESERVE_NS==36000000000
    assert wall.scenario_ms()==4000  # 40 remaining minus the fixed36-second reserve.
    clock.advance(4)
    with pytest.raises(CapabilityError,match='RESOURCE_WALL_LIMIT'):wall.work_timeout()
    assert wall.remaining_ns()==CLEANUP_RESERVE_NS


def test_nonexiting_owned_process_cannot_force_unbounded_reap(monkeypatch):
    clock=Clock();wall=_WallBudget(clock(),895000000000,clock)
    process=Process(clock);signals=[]
    monkeypatch.setattr('polar.capability_runtime.os.killpg',lambda *args:signals.append(args))
    assert _stop_owned(process,wall,reserve_ns=FINAL_ACCOUNTING_NS) is False
    assert process.waits==[2.0] and len(signals)==1
    assert wall.remaining_ns()==3000000000  # Still inside the same family deadline.


def test_cleanup_timeout_retains_unknown_and_accounting_reserve(monkeypatch):
    clock=Clock();wall=_WallBudget(clock(),890000000000,clock)
    launcher=Process(clock,exits=True);launcher.returncode=0
    cleanup=Process(clock)
    signals=[];commands=[]
    monkeypatch.setattr('polar.capability_runtime.os.killpg',lambda *args:signals.append(args))
    def create(argv,**kwargs):
        commands.append(argv)
        assert kwargs['start_new_session'] is True
        return cleanup
    monkeypatch.setattr('polar.capability_runtime.subprocess.Popen',create)
    outcome=_cleanup_owned(launcher,['reviewed-launcher','docker-cleanup','owned-config','owned-root'],wall)
    assert outcome['launcher_reaped'] is True and outcome['cleanup_reaped'] is False
    assert outcome['verified'] is False and outcome['exit_code'] is None
    assert commands==[['reviewed-launcher','docker-cleanup','owned-config','owned-root']]
    assert launcher.waits==[]  # Already reaped, so no fresh launch wait.
    assert cleanup.waits==[6.0,2.0]
    assert wall.remaining_ns()==FINAL_ACCOUNTING_NS
    assert len(signals)==1



def test_unreaped_preprocess_marks_resource_evidence_incomplete(monkeypatch,tmp_path):
    from polar.capability_service import CapabilityService, _UnreapedPreprocess
    clock=Clock();started=clock()
    process=Process(clock);polls=[]
    def poll():
        if not polls:clock.advance(15)
        polls.append(1)
        return None
    process.poll=poll
    monkeypatch.setattr('polar.capability_service.time.monotonic_ns',clock)
    monkeypatch.setattr('polar.capability_service.host_cpu_us',lambda:0)
    monkeypatch.setattr('polar.capability_service.os.cpu_count',lambda:1)
    monkeypatch.setattr('polar.capability_service.immutable',lambda *args:None)
    monkeypatch.setattr('polar.capability_service.subprocess.Popen',lambda *args,**kwargs:process)
    monkeypatch.setattr('polar.capability_runtime.os.killpg',lambda *args:None)
    class Family:
        def state(self):return {'spent':{'cpu_us':0,'wall_ns':850000000000}}
        def resources(self,*args):pass
    service=CapabilityService.__new__(CapabilityService)
    with pytest.raises(_UnreapedPreprocess,match='OBSERVATION_MISSING'):
        service._preprocess({},Family(),'invented-attempt',tmp_path,started,0)
    assert process.waits==[1.0]
    assert clock()==started+16000000000
