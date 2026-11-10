"""Disposable metadata only: no finance/native strategy/provider execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from polar.gym_contract import canonical,SEMANTIC_FILES
from polar.state_reader import read_state,StateError,native_queue

NOW=1794135600*10**9
AID='11111111-1111-4111-8111-111111111111'
QID='qitem-20261108112350-cbcc21f66eebcd9c'
SECRET='PRIVATE_TEST_PAYLOAD_MUST_NOT_APPEAR'

def write(root,name,value):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(canonical(value));return p

def experiment(root):
    blobs={name:canonical({'opaque':SECRET}) for name in SEMANTIC_FILES}
    manifest={'schema':'polar.gym-semantic-manifest/1','bindings':{'private':SECRET},
              'files':{name:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in blobs.items()}}
    raw=canonical(manifest);eid='gym-'+hashlib.sha256(raw).hexdigest()
    for name,content in {**blobs,'manifest.json':raw}.items():
        p=root/'gym-experiments'/eid/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
    return eid

def attempt(root,*,terminal=True,age=0):
    eid=experiment(root)
    write(root,f'gym-attempts/{AID}/start/record.json',{'schema':'polar.gym-attempt-start/1','attempt_id':AID,
          'status':'UNFINALIZED','started_ns':NOW-age*10**9-10**9,'bindings':{'private':SECRET}})
    if terminal:write(root,f'gym-attempts/{AID}/finish/record.json',{'schema':'polar.gym-attempt-finish/1','status':'SUCCESS',
                     'finished_ns':NOW-age*10**9,'experiment_id':eid,'code':SECRET})
    return eid

def queue(**changes):
    data={'qitemId':QID,'state':'in-progress','destinationSession':'platform-engineer@polar-rig',
          'waiting':{'state':'in-progress','obligation':QID,'owner':'platform-engineer@polar-rig'},
          'blockedOn':None,'body':SECRET,'metadata':{'duration':1.5,'password':SECRET}}
    data.update(changes);return lambda _:json.dumps(data).encode()

def files(root):
    return {str(p.relative_to(root)):(p.read_bytes(),p.stat().st_mtime_ns,p.stat().st_mode) for p in root.rglob('*') if p.is_file()}

def test_active_native_owner_is_not_worker_liveness(tmp_path):
    attempt(tmp_path,terminal=False)
    result=read_state(root=tmp_path.resolve(),qitem=QID,attempt=AID,now_ns=NOW,queue_reader=queue())
    f=result['facts']
    assert f['queue_state']['value']=='in-progress'
    assert f['owner']['value']=='platform-engineer@polar-rig'
    assert f['source_custody']['status']=='UNKNOWN'
    assert f['worker_liveness']['status']=='UNKNOWN' and f['worker_liveness']['value'] is None
    assert f['checkpoint']['status']=='UNKNOWN' and f['terminal_result']['status']=='UNKNOWN'
    assert SECRET not in json.dumps(result)
    assert all(v['evidence'] and all('observed_at' in e for e in v['evidence']) for v in f.values())

def test_terminal_consumer_unknown_no_mutation_or_private_output(tmp_path):
    eid=attempt(tmp_path);before=files(tmp_path)
    result=read_state(root=tmp_path.resolve(),attempt=AID,now_ns=NOW)
    assert files(tmp_path)==before
    assert result['facts']['terminal_result']['value']=='SUCCESS'
    assert result['facts']['semantic_result']['value']=={'experiment_id':eid,'verified_members':4}
    assert result['facts']['consumer_ack']['status']=='UNKNOWN'
    assert result['facts']['next_step']['value']=='CHECK_CONSUMER_ACKNOWLEDGMENT_WITH_OWNER'
    assert SECRET not in json.dumps(result)
    assert result['actions_performed']==[]

def test_stale_terminal_is_not_current_success(tmp_path):
    attempt(tmp_path,age=301)
    f=read_state(root=tmp_path.resolve(),attempt=AID,now_ns=NOW)['facts']['terminal_result']
    assert f['status']=='UNKNOWN' and f['freshness']=='STALE' and f['value'] is None
    assert f['last_recorded']=='SUCCESS'

@pytest.mark.parametrize('field',['owner','state'])
def test_contradictory_native_projection_is_unknown(field):
    waiting={'owner':'platform-engineer@polar-rig','state':'in-progress','obligation':QID}
    waiting[field]='other@polar-rig' if field=='owner' else 'done'
    result=read_state(qitem=QID,now_ns=NOW,queue_reader=queue(waiting=waiting))
    fact=result['facts']['owner' if field=='owner' else 'queue_state']
    assert fact['status']=='UNKNOWN' and 'CONTRADICTORY' in fact['reason']
    assert result['facts']['next_step']['value']=='RECONCILE_CONTRADICTORY_EVIDENCE_WITH_OWNER'

def test_contradictory_selected_experiment_is_not_followed(tmp_path):
    attempt(tmp_path)
    result=read_state(root=tmp_path.resolve(),attempt=AID,experiment='gym-'+'f'*64,now_ns=NOW)
    assert result['facts']['terminal_result']['reason']=='CONTRADICTORY_RESULT_REFERENCE'
    assert result['facts']['semantic_result']['status']=='UNKNOWN'

def test_missing_records_remain_unknown(tmp_path):
    result=read_state(root=tmp_path.resolve(),attempt=AID,now_ns=NOW)
    assert result['facts']['terminal_result']['status']=='UNKNOWN'
    assert result['facts']['worker_liveness']['status']=='UNKNOWN'

@pytest.mark.parametrize('corrupt',['member','manifest','extra','clock'])
def test_integrity_and_time_fail_closed(tmp_path,corrupt):
    eid=attempt(tmp_path)
    if corrupt=='member':(tmp_path/'gym-experiments'/eid/'converted.json').write_text('corrupt')
    elif corrupt=='manifest':(tmp_path/'gym-experiments'/eid/'manifest.json').write_text('{}')
    elif corrupt=='extra':(tmp_path/'gym-experiments'/eid/'private.json').write_text(SECRET)
    else:
        path=tmp_path/f'gym-attempts/{AID}/finish/record.json';r=json.loads(path.read_text());r['finished_ns']=NOW-10**10;path.write_bytes(canonical(r))
    result=read_state(root=tmp_path.resolve(),attempt=AID,now_ns=NOW)
    assert result['facts']['terminal_result']['status']=='UNKNOWN'
    assert SECRET not in json.dumps(result)

def test_member_limit_and_total_limit(tmp_path):
    attempt(tmp_path)
    result=read_state(root=tmp_path.resolve(),attempt=AID,now_ns=NOW,max_file_bytes=32,max_total_bytes=32)
    assert result['facts']['terminal_result']['status']=='UNKNOWN'
    assert result['limits']['bytes_read']<=32

def test_path_and_symlink_are_not_followed(tmp_path):
    outside=tmp_path/'outside';outside.mkdir();attempt(outside)
    root=tmp_path/'root';root.mkdir();(root/'gym-attempts').symlink_to(outside/'gym-attempts',target_is_directory=True)
    result=read_state(root=root.resolve(),attempt=AID,now_ns=NOW)
    assert result['facts']['terminal_result']['status']=='UNKNOWN'
    with pytest.raises(StateError):read_state(root=root.resolve(),attempt='../outside',now_ns=NOW)
    linked=tmp_path/'linked';linked.symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):read_state(root=linked,attempt=AID,now_ns=NOW)

def test_fifo_is_rejected_without_blocking(tmp_path):
    eid=attempt(tmp_path);p=tmp_path/'gym-experiments'/eid/'converted.json';p.unlink();os.mkfifo(p)
    before=time.monotonic();result=read_state(root=tmp_path.resolve(),attempt=AID,now_ns=NOW)
    assert time.monotonic()-before<1
    assert result['facts']['terminal_result']['status']=='UNKNOWN'

def test_native_reader_bounds_stdout_and_discards_private_stderr(tmp_path,monkeypatch):
    program=tmp_path/'rig';program.write_text('#!'+sys.executable+'\nimport sys\nsys.stderr.write('+repr(SECRET)+')\nprint("x"*300000)\n');program.chmod(0o700)
    monkeypatch.setenv('PATH',str(tmp_path)+os.pathsep+os.environ['PATH'])
    with pytest.raises(StateError,match='NATIVE_QUERY_LIMIT'):native_queue(QID)

def test_cli_stdout_only_and_no_artifact_mutation(tmp_path):
    attempt(tmp_path);before=files(tmp_path)
    script=Path(__file__).resolve().parents[1]/'scripts/polar_state.py'
    r=subprocess.run([sys.executable,str(script),'--root',str(tmp_path.resolve()),'--attempt',AID],capture_output=True,text=True,timeout=5)
    assert r.returncode==0 and r.stderr=='' and SECRET not in r.stdout
    assert json.loads(r.stdout)['schema']=='polar.state/1'
    assert files(tmp_path)==before

@pytest.mark.parametrize('waiting',[[], '', 0, False])
def test_explicit_nonobject_waiting_is_unknown(waiting):
    result=read_state(qitem=QID,now_ns=NOW,queue_reader=queue(waiting=waiting))
    assert result['facts']['queue_state']['status']=='UNKNOWN'
    assert result['facts']['owner']['status']=='UNKNOWN'
    assert result['facts']['queue_state']['reason']=='INVALID_NATIVE_WAITING'

@pytest.mark.parametrize('absent',[True,False])
def test_missing_or_null_waiting_keeps_native_top_level_compatibility(absent):
    data={'qitemId':QID,'state':'in-progress','destinationSession':'platform-engineer@polar-rig'}
    if not absent:data['waiting']=None
    result=read_state(qitem=QID,now_ns=NOW,queue_reader=lambda _:json.dumps(data).encode())
    assert result['facts']['queue_state']['value']=='in-progress'
    assert result['facts']['owner']['value']=='platform-engineer@polar-rig'
    assert result['facts']['worker_liveness']['status']=='UNKNOWN'
