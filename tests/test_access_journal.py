"""Disposable notes and synthetic safe events only; never inspect the real journal/credentials."""
import copy
import fcntl
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/access_journal.py'
spec=importlib.util.spec_from_file_location('journal',SCRIPT)
j=importlib.util.module_from_spec(spec);spec.loader.exec_module(j)


def event(identity='ACCESS-FIXTURE-01',**updates):
    return {'schema':j.SCHEMA,'event_id':identity,'utc':'2026-11-07T16:00:00Z','actor':'platform-engineer',
        'qitem':'qitem-20261107154018-9984ef7e4a7ede00','provider':'example','operation':'api-probe',
        'purpose':'source-qualification','alias':'fixture-one','outcome':'success','observable_basis':'fixture-observed',
        'attribution':'observed','new':False,'unusual':False,'blocking':False,'blocker_class':'none',
        'method_environment':'local-fixture','session_continuity':'same-task','pacing_profile':'bounded',
        'missing_tools':'none','user_action':'none','safe_evidence':['state/fixture/result'],
        'next_checkpoint':'independent-review','correction_ref':None,'safe_author_assertion':True,**updates}


@pytest.fixture
def notes(tmp_path):
    path=tmp_path/'NOTES.md';path.write_text('# Fixture notes\n\n### ROUTE-EXAMPLE-v1\nExample official route.\n')
    return path


def test_success_duplicate_unknown_completion_and_collision(notes):
    original=notes.read_bytes();data=event()
    assert j.append(notes,data)['status']=='APPENDED'
    exact=notes.read_bytes()
    assert exact.startswith(original)
    assert j.append(notes,data)['status']=='ALREADY_PRESENT'  # completion receipt lost; inspect before retry
    assert notes.read_bytes()==exact
    with pytest.raises(j.JournalError,match='EVENT_ID_CONFLICT'):
        j.append(notes,event(outcome='partial'))
    assert notes.read_bytes()==exact


def test_blocked_correction_and_route_versions_remain_visible(notes):
    original=notes.read_bytes()
    j.append(notes,event(outcome='blocked',blocking=True,blocker_class='human',user_action='select-country'))
    j.append(notes,event('ACCESS-FIXTURE-02',correction_ref='ACCESS-FIXTURE-01',operation='route-revision'))
    result=j.read(notes,'example',recent=1)
    assert result['matching_events']==2 and result['matching_routes']==1 and result['incomplete']
    assert 'ACCESS-FIXTURE-02' in result['text'] and 'ROUTE-EXAMPLE-v1' in result['text']
    assert notes.read_bytes().startswith(original)


def test_bounded_provider_read_and_explicit_incomplete(notes):
    for i in range(4):j.append(notes,event(f'ACCESS-FIXTURE-{i}'))
    j.append(notes,event('ACCESS-OTHER-1',provider='other'))
    result=j.read(notes,'example',recent=20,max_bytes=256)
    assert result['incomplete'] and len(result['text'].encode())<=256
    assert 'ACCESS-OTHER' not in result['text']
    assert j.read(notes,'absent')['matching_events']==0


def _run_append(path,data,start,results):
    start.wait()
    try:results.put(j.append(path,data)['status'])
    except j.JournalError as exc:results.put(exc.code)


@pytest.mark.parametrize('same',[False,True])
def test_concurrent_whole_events_distinct_and_same_id(notes,same):
    ctx=multiprocessing.get_context('fork');start=ctx.Event();results=ctx.Queue()
    children=[ctx.Process(target=_run_append,args=(notes,event('ACCESS-FIXTURE-'+('0' if same else str(i))),start,results)) for i in range(4)]
    for p in children:p.start()
    start.set()
    values=[results.get(timeout=5) for _ in children]
    for p in children:p.join(5);assert p.exitcode==0
    assert values.count('APPENDED')==(1 if same else 4)
    assert len(j.records(notes.read_bytes()))==(1 if same else 4)


def _hold_lock(path,ready,finish):
    with open(path,'rb') as f:
        fcntl.flock(f,fcntl.LOCK_EX);ready.set();finish.wait(5)


def test_lock_timeout_and_crashed_owner_releases_without_lockfile(notes):
    ctx=multiprocessing.get_context('fork');ready=ctx.Event();finish=ctx.Event()
    p=ctx.Process(target=_hold_lock,args=(notes,ready,finish));p.start();assert ready.wait(5)
    before=notes.read_bytes()
    with pytest.raises(j.JournalError,match='LOCK_TIMEOUT'):j.append(notes,event(),wait=.02)
    assert notes.read_bytes()==before
    p.terminate();p.join(5)
    assert j.append(notes,event())['status']=='APPENDED'
    assert list(notes.parent.iterdir())==[notes]


@pytest.mark.parametrize('cut',[2,5,12,35,100,-8])
def test_partial_crash_record_never_blindly_appends(notes,cut):
    with notes.open('ab') as f:f.write(j.frame(j.validate(event()))[:cut])
    before=notes.read_bytes()
    with pytest.raises(j.JournalError,match='PARTIAL_OR_INVALID_JOURNAL'):j.append(notes,event())
    assert notes.read_bytes()==before


def test_partial_os_write_and_uncertain_fsync_retry(notes,monkeypatch):
    real_write=os.write
    with monkeypatch.context() as m:
        m.setattr(j.os,'write',lambda fd,data:real_write(fd,data[:12]))
        with pytest.raises(j.JournalError,match='UNKNOWN_WRITE_EFFECT'):j.append(notes,event())
    with pytest.raises(j.JournalError,match='PARTIAL_OR_INVALID_JOURNAL'):j.append(notes,event())
    # A different disposable journal simulates complete write but lost fsync receipt.
    second=notes.parent/'SECOND.md';second.write_text('# second\n')
    with monkeypatch.context() as m:
        m.setattr(j.os,'fsync',lambda fd:(_ for _ in ()).throw(OSError()))
        with pytest.raises(j.JournalError,match='UNKNOWN_WRITE_EFFECT'):j.append(second,event())
    assert j.append(second,event())['status']=='ALREADY_PRESENT'


@pytest.mark.parametrize('unsafe',['alias','observable_basis','event_id','safe_evidence'])
def test_secret_sentinel_rejected_with_safe_errors(notes,tmp_path,unsafe):
    data=event()
    sentinel='SECRET_SENTINEL_DO_NOT_PRINT'
    data[unsafe]=[sentinel] if unsafe=='safe_evidence' else 'ACCESS-'+sentinel if unsafe=='event_id' else sentinel
    source=tmp_path/'event.json';source.write_text(json.dumps(data))
    before=notes.read_bytes()
    result=subprocess.run([sys.executable,str(SCRIPT),'--journal',str(notes),'append','--event-file',str(source)],capture_output=True,text=True)
    assert result.returncode==1 and sentinel not in result.stdout+result.stderr
    assert sentinel not in ' '.join(result.args) and notes.read_bytes()==before
    assert set(json.loads(result.stdout))=={'code'}


def test_unsafe_targets_hardlinks_and_parent_symlinks(notes,tmp_path):
    link=tmp_path/'link';link.symlink_to(notes)
    with pytest.raises(j.JournalError):j.append(link,event())
    parent=tmp_path/'directory';parent.mkdir();target=parent/'notes';target.write_text('# notes\n')
    alias=tmp_path/'alias';alias.symlink_to(parent,target_is_directory=True)
    with pytest.raises(j.JournalError):j.append(alias/'notes',event())
    hard=tmp_path/'hard';os.link(notes,hard)
    with pytest.raises(j.JournalError,match='UNSAFE_JOURNAL'):j.append(hard,event())


def test_manual_collision_bounds_and_cli_roundtrip(notes,tmp_path):
    with notes.open('a') as f:f.write('\n### ACCESS-FIXTURE-01\nmanual entry\n')
    with pytest.raises(j.JournalError,match='EVENT_ID_CONFLICT'):j.append(notes,event())
    with pytest.raises(j.JournalError):j.read(notes,'example',recent=21)
    with pytest.raises(j.JournalError):j.append(notes,event(),wait=float('nan'))
    source=tmp_path/'event.json';source.write_text(json.dumps(event('ACCESS-CLI-1')))
    command=[sys.executable,str(SCRIPT),'--journal',str(notes)]
    added=subprocess.run(command+['append','--event-file',str(source)],capture_output=True,text=True)
    assert added.returncode==0 and json.loads(added.stdout)['status']=='APPENDED'
    viewed=subprocess.run(command+['read','--provider','example'],capture_output=True,text=True)
    assert viewed.returncode==0 and 'ACCESS-CLI-1' in json.loads(viewed.stdout)['text']


def test_record_tamper_and_unknown_fields_refused(notes):
    j.append(notes,event());notes.write_bytes(notes.read_bytes().replace(b'fixture-observed',b'changed-observed'))
    with pytest.raises(j.JournalError,match='PARTIAL_OR_INVALID_JOURNAL'):j.read(notes,'example')
    with pytest.raises(j.JournalError,match='INVALID_EVENT'):j.validate({**event(),'password':'secret'})


def test_structured_provider_match_does_not_match_other_event_alias(notes):
    j.append(notes,event('ACCESS-OTHER-1',provider='other',alias='example'))
    j.append(notes,event('ACCESS-RIGHT-1'))
    result=j.read(notes,'example')
    assert result['matching_events']==1
    assert 'ACCESS-OTHER-1' not in result['text']
    assert '<!--' not in result['text']


def test_bounded_journal_size_and_incomplete_output(notes):
    notes.write_bytes(b'x'*(j.MAX_JOURNAL+1))
    with pytest.raises(j.JournalError,match='JOURNAL_LIMIT'):j.read(notes,'example')
    with pytest.raises(j.JournalError,match='JOURNAL_LIMIT'):j.append(notes,event())
