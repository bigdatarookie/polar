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
        'next_checkpoint':'independent-review','correction_ref':None,'safe_author_assertion':True,'episode_kind':'new-rights','access_problem':'none','route_change':'none',**updates}


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
    j.append(notes,event('ACCESS-FIXTURE-02',correction_ref='ACCESS-FIXTURE-01',operation='route-revision',route_change='verified-clarification'))
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


@pytest.mark.parametrize('manual_first',[False,True])
def test_existing_framed_id_plus_manual_heading_conflicts_on_identical_retry(notes,manual_first):
    data=event('ACCESS-QA-COLLISION-1')
    if manual_first:
        with notes.open('ab') as stream:stream.write(b'\n### ACCESS-QA-COLLISION-1\nmanual entry\n')
        with notes.open('ab') as stream:stream.write(j.frame(j.validate(data)))
    else:
        assert j.append(notes,data)['status']=='APPENDED'
        with notes.open('ab') as stream:stream.write(b'\n### ACCESS-QA-COLLISION-1\nmanual entry\n')
    before=notes.read_bytes()
    with pytest.raises(j.JournalError,match='EVENT_ID_CONFLICT'):
        j.append(notes,data)
    assert notes.read_bytes()==before


def legacy_event(identity='ACCESS-OLD-1',**updates):
    value=event(identity,schema=j.LEGACY_SCHEMA,**updates)
    return {k:v for k,v in value.items() if k not in j.CLASSIFICATION_FIELDS}


@pytest.mark.parametrize('operation',['read','push','pr','review','merge','git-fetch','pr-create'])
def test_v016_ordinary_github_working_auth_creates_zero_entries(notes,operation):
    before=notes.read_bytes()
    result=j.append(notes,event('ACCESS-ORDINARY-1',provider='github',operation=operation,
        episode_kind='ordinary-operation',method_environment='existing-helper'))
    assert result['status']=='SKIPPED_NON_EPISODE' and notes.read_bytes()==before


def test_v016_expiry_and_multiple_recoveries_are_one_combined_episode(notes):
    data=event('ACCESS-AUTH-RECOVERY-1',operation='reauth',episode_kind='access-problem',access_problem='auth',
               observable_basis='recovered-after-three-attempts',session_continuity='recovered')
    before=notes.read_bytes();assert j.append(notes,data)['status']=='APPENDED'
    exact=notes.read_bytes()
    for _ in range(3):assert j.append(notes,data)['status']=='ALREADY_PRESENT'
    assert notes.read_bytes()==exact and exact.startswith(before) and len(j.records(exact))==1
    assert j.read(notes,'example')['matching_events']==1


def test_v016_successful_repeat_login_one_entry_no_route_expansion(notes):
    before=notes.read_bytes();data=event('ACCESS-LOGIN-1',operation='repeat-login',episode_kind='login')
    assert j.append(notes,data)['status']=='APPENDED'
    assert j.append(notes,data)['status']=='ALREADY_PRESENT'
    assert notes.read_bytes().count(b'### ROUTE-')==before.count(b'### ROUTE-')
    record=j.decode(j.records(notes.read_bytes())['ACCESS-LOGIN-1'])
    assert record['route_change']=='none' and not any(record[k] for k in ('new','unusual','blocking'))


@pytest.mark.parametrize('operation',['api-repeat','same-key-api-call','repeat-api'])
def test_v016_same_working_key_repeats_do_not_log(notes,operation):
    before=notes.read_bytes()
    for i in range(3):
        result=j.append(notes,event('ACCESS-API-'+str(i),operation=operation,episode_kind='ordinary-operation'))
        assert result['status']=='SKIPPED_NON_EPISODE'
    assert notes.read_bytes()==before


@pytest.mark.parametrize('kind',['access-problem','ordinary-operation'])
def test_v016_ordinary_operation_with_real_auth_symptom_is_one_problem_episode(notes,kind):
    data=event('ACCESS-GITHUB-RECOVERED',provider='github',operation='merge',episode_kind=kind,
               access_problem='permission',observable_basis='permission-restored')
    assert j.append(notes,data)['status']=='APPENDED'
    assert j.append(notes,data)['status']=='ALREADY_PRESENT'
    assert j.read(notes,'github')['matching_events']==1


def test_v016_legacy_frames_and_manual_ordinary_history_are_preserved_filtered(notes):
    old=legacy_event('ACCESS-OLD-GH-1',provider='github',operation='merge')
    framed=j.frame(j.validate(old))
    manual=b'\n### ACCESS-OLD-GITHUB-PUSH\n- provider/operation/purpose: GitHub; ordinary push with existing credential helper.\n- outcome: success; no auth failure.\n'
    with notes.open('ab') as stream:stream.write(framed+manual)
    before=notes.read_bytes()
    overview=j.read(notes,'github')
    assert overview['filtered_ordinary_events']==2 and overview['matching_events']==0 and 'ACCESS-OLD' not in overview['text']
    full=j.read(notes,'github',include_ordinary=True)
    assert full['matching_events']==2 and 'ACCESS-OLD-GH-1' in full['text'] and 'ACCESS-OLD-GITHUB-PUSH' in full['text']
    assert notes.read_bytes()==before and j.append(notes,old)['status']=='ALREADY_PRESENT'
    fresh=event('ACCESS-GH-LOGIN',provider='github',operation='repeat-login',episode_kind='login')
    assert j.append(notes,fresh)['status']=='APPENDED' and notes.read_bytes().startswith(before)
    assert j.read(notes,'github')['matching_events']==1


@pytest.mark.parametrize('manual_first',[False,True])
def test_v016_legacy_policy_does_not_bypass_manual_heading_collision(notes,manual_first):
    old=legacy_event('ACCESS-OLD-COLLISION',operation='merge',provider='github')
    manual=b'\n### ACCESS-OLD-COLLISION\nmanual duplicate\n';frame=j.frame(j.validate(old))
    with notes.open('ab') as stream:stream.write(manual+frame if manual_first else frame+manual)
    before=notes.read_bytes()
    with pytest.raises(j.JournalError,match='EVENT_ID_CONFLICT'):j.append(notes,old)
    assert notes.read_bytes()==before
    assert j.append(notes,event('ACCESS-NEW-LOGIN',operation='login',episode_kind='login'))['status']=='APPENDED'


def test_v016_policy_is_not_historical_structural_validation(notes):
    old=legacy_event('ACCESS-OLD-ORDINARY',operation='merge')
    with notes.open('ab') as stream:stream.write(j.frame(j.validate(old)))
    assert len(j.records(notes.read_bytes()))==1
    assert j.read(notes,'example')['filtered_ordinary_events']==1
    before=notes.read_bytes()
    legacy_genuine=legacy_event('ACCESS-NEW-LEGACY',operation='login')
    with pytest.raises(j.JournalError,match='EPISODE_CLASSIFICATION_REQUIRED'):j.append(notes,legacy_genuine)
    assert notes.read_bytes()==before
    invalid=event('ACCESS-BAD-PROBLEM',operation='recover',episode_kind='access-problem',access_problem='none')
    assert j.validate(invalid)  # structural parsing is deliberately independent of eligibility
    with pytest.raises(j.JournalError,match='INVALID_EPISODE_CLASSIFICATION'):j.append(notes,invalid)


def test_v016_route_changes_require_verified_context_and_do_not_edit_routes(notes):
    before=notes.read_bytes()
    with pytest.raises(j.JournalError,match='UNVERIFIED_ROUTE_CHANGE'):
        j.append(notes,event('ACCESS-ROUTE-1',operation='route-update',episode_kind='new-rights'))
    assert notes.read_bytes()==before
    data=event('ACCESS-ROUTE-1',operation='route-update',episode_kind='new-rights',route_change='verified-clarification')
    assert j.append(notes,data)['status']=='APPENDED' and notes.read_bytes().startswith(before)
    assert notes.read_bytes().count(b'### ROUTE-')==before.count(b'### ROUTE-')


def test_v016_cli_skip_and_include_ordinary_are_explicit_without_writes(notes,tmp_path):
    ordinary=event('ACCESS-NO-LOG',operation='merge',provider='github',episode_kind='ordinary-operation')
    input_file=tmp_path/'event.json';input_file.write_bytes(j.canonical(ordinary));before=notes.read_bytes()
    result=subprocess.run([sys.executable,str(SCRIPT),'--journal',str(notes),'append','--event-file',str(input_file)],capture_output=True,text=True)
    assert result.returncode==0 and json.loads(result.stdout)['status']=='SKIPPED_NON_EPISODE' and notes.read_bytes()==before
    old=legacy_event('ACCESS-CLI-OLD',provider='github',operation='merge')
    with notes.open('ab') as stream:stream.write(j.frame(j.validate(old)))
    command=[sys.executable,str(SCRIPT),'--journal',str(notes),'read','--provider','github']
    default=subprocess.run(command,capture_output=True,text=True)
    explicit=subprocess.run(command+['--include-ordinary'],capture_output=True,text=True)
    assert default.returncode==explicit.returncode==0
    assert json.loads(default.stdout)['matching_events']==0 and json.loads(explicit.stdout)['matching_events']==1



def test_v016_legacy_explicit_auth_recovery_cues_are_not_filtered(notes):
    data=legacy_event('ACCESS-OLD-RECOVERY',provider='github',operation='merge',purpose='auth-recovery',
                      observable_basis='auth-recovered')
    with notes.open('ab') as stream:stream.write(j.frame(j.validate(data)))
    assert j.read(notes,'github')['matching_events']==1
    assert j.read(notes,'github')['filtered_ordinary_events']==0



def test_v016_ambiguous_manual_failure_stays_visible(notes):
    with notes.open('ab') as stream:stream.write(b'\n### ACCESS-OLD-GITHUB-UNKNOWN\n- provider/operation/purpose: GitHub; push.\n- outcome: failed; blocking=yes; diagnosis pending.\n')
    result=j.read(notes,'github')
    assert result['matching_events']==1 and result['unclassified_legacy_events']==1
    assert result['filtered_ordinary_events']==0
