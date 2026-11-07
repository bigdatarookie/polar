"""Source-only fixtures: no Docker/DB commands or real dumps/archives are produced."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

import pytest

from test_ops_inventory import ops, runtime, SENTINEL, REV, IMAGE


@pytest.fixture
def stable():
    value = {'database_major': 17, 'schema_version': 1, 'schema_sha256': 'e'*64,
             'counts': dict(datasets=4, runs=10, attempts=11, artifact_manifests=8),
             'fingerprints': {k:'a'*64 for k in ('datasets','runs','attempts','artifact_manifests')}}
    return ops.seal_content(value, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00')


def later(stable, **changes):
    value = copy.deepcopy(ops.content_identity(stable))
    value.update(changes)
    return ops.seal_content(value, '2026-01-01T00:00:02+00:00', '2026-01-01T00:00:03+00:00')


def test_matching_stale_tampered_and_restore_are_distinct(stable):
    match = ops.compare_content(stable, later(stable), 'PASS')
    assert match['current_state_coverage'] == 'CURRENT'
    assert match['restore_effect'] == 'NOT_RUN'
    assert match['snapshot_observation']['window_finished_at'] < match['current_observation']['window_started_at']
    changed = copy.deepcopy(stable['fingerprints']); changed['datasets'] = 'b'*64
    stale = ops.compare_content(stable, later(stable, fingerprints=changed), 'PASS')
    assert stale['current_state_coverage'] == 'STALE'
    assert stale['reason'] == 'SCOPED_IDENTITIES_DIFFER'
    tampered = copy.deepcopy(stable); tampered['fingerprints']['datasets'] = 'b'*64
    assert ops.compare_content(tampered, later(stable))['reason'] == 'SNAPSHOT_INVALID'
    failure = ops.compare_content(stable, later(stable, fingerprints=changed), 'FAIL')
    assert failure['reason'] == 'FILE_INTEGRITY_FAILED'
    assert failure['current_state_coverage'] == 'UNKNOWN'


@pytest.mark.parametrize('change', ['time','major','schema','invalid_time','unsupported_protocol'])
def test_compatibility_is_not_staleness(stable, change):
    current = later(stable)
    if change == 'major': current = later(stable, database_major=18)
    if change == 'schema': current = later(stable, schema_sha256='f'*64)
    if change == 'time': current = ops.seal_content(ops.content_identity(stable), '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:01+00:00')
    if change == 'invalid_time': current['window_started_at'] = SENTINEL
    if change == 'unsupported_protocol': current['schema'] = 'polar.snapshot-content/2'
    result = ops.compare_content(stable,current)
    assert result['current_state_coverage'] == 'UNKNOWN'
    assert SENTINEL not in json.dumps(result)


def probe_read(stable, *, concurrent=False, active=0, extra=SENTINEL):
    calls = []; passes = []
    db = {'database_major':17,'schema_version':1,'schema_sha256':'e'*64,'active':active,'password':extra}
    for k in ('datasets','runs','attempts'):
        db[k] = stable['fingerprints'][k]; db[k+'_count'] = stable['counts'][k]
    def read(args):
        calls.append(args)
        if 'psql' in args:
            assert 'REPEATABLE READ READ ONLY' in args[-1]
            assert 'LIMIT 1025' in args[-1]
            assert 'source_bytes' not in args[-1] and 'body' not in args[-1]
            passes.append(1)
            value = {**db}
            if concurrent and len(passes)>1: value['datasets'] = 'b'*64
            return json.dumps(value)
        assert args[:3] == ['docker','exec','api']
        return json.dumps({'status':'OBSERVED','count':8,'sha256':'a'*64,'credential':extra})
    return read,calls,db


def test_two_pass_stability_and_safe_observation_failure(stable):
    read,calls,_ = probe_read(stable)
    observation = ops.observe_content(['docker','exec','db'], ['docker','exec','api'], read)
    assert ops.valid_content(observation)
    assert SENTINEL not in json.dumps(observation)
    assert len(calls)==4
    concurrent,_,_ = probe_read(stable, concurrent=True)
    result=ops.observe_content(['docker','exec','db'], ['docker','exec','api'], concurrent)
    assert result=={'status':'UNKNOWN','reason':'CONCURRENT_CHANGE'}
    assert ops.compare_content(stable,result)['current_state_coverage']=='UNKNOWN'
    active,_,_=probe_read(stable,active=1)
    assert ops.observe_content([],[],active)['reason']=='NOT_QUIESCENT'
    def fail(args): raise ops.InventoryError('INVENTORY_COMMAND_FAILED')
    assert ops.observe_content([],[],fail)['reason']=='OBSERVATION_UNAVAILABLE'


def test_metadata_bounds_and_no_arbitrary_fields(stable):
    read,_,db = probe_read(stable)
    db['datasets_count']=1025
    assert ops.observe_content(['docker','exec','db'],['docker','exec','api'],read)['status']=='UNKNOWN'
    bad=copy.deepcopy(stable); bad['unrequested_secret']=SENTINEL
    sanitized=ops.valid_content(bad)
    assert sanitized is not None and SENTINEL not in json.dumps(sanitized)


def test_artifact_manifest_identity_scope_and_symlink_refusal(tmp_path):
    run,attempt=str(uuid.uuid4()),str(uuid.uuid4())
    path=tmp_path/run/attempt;path.mkdir(parents=True)
    m=path/'manifest.json'
    body={'schema_version':'polar.manifest/1','run_id':run,'attempt_id':attempt,'credential':SENTINEL}
    m.write_text(json.dumps(body))
    a=ops.artifact_content(tmp_path)
    assert a['status']=='OBSERVED' and a['count']==1
    assert SENTINEL not in json.dumps(a)
    # Unscoped payload bytes do not become an unsupported payload-integrity proof.
    (path/'report.json').write_text('synthetic unscoped payload')
    assert ops.artifact_content(tmp_path)==a
    body['new_manifest_identity']=True;m.write_text(json.dumps(body))
    assert ops.artifact_content(tmp_path)['sha256']!=a['sha256']
    m.unlink();m.symlink_to(path/'report.json')
    assert ops.artifact_content(tmp_path)['status']=='UNKNOWN'
    m.unlink();m.write_bytes(b'x'*65537)
    assert ops.artifact_content(tmp_path)['status']=='UNKNOWN'


def synthetic_backup(tmp_path, stable=None):
    # Fixed test blobs, not pg_dump output or an archive.
    files={}
    for name in ('metadata.dump','artifacts.tar'):
        (tmp_path/name).write_bytes(b'synthetic checksum fixture')
        files[name]=ops.sha(tmp_path/name)
    m={'schema_version':1,'scope':'POL.0.4.0.1','code_revision':REV,'files':files}
    if stable is not None: m.update(schema_version=2,snapshot_content=stable)
    (tmp_path/'backup-manifest.json').write_text(json.dumps(m))
    return m


def test_file_integrity_separate_from_legacy_and_content(runtime,tmp_path,stable):
    _,_,_,_,read=runtime
    m=synthetic_backup(tmp_path)
    original=(tmp_path/'backup-manifest.json').read_bytes()
    result=ops.inventory_manifest(backup_directory=tmp_path,read=read,verify_files=True)['backup_handle']
    assert result['file_verification']=='PASS'
    assert result['current_state_coverage']=='UNKNOWN' and result['reason']=='LEGACY_NO_SNAPSHOT'
    assert result['restore_effect']=='NOT_RUN'
    assert (tmp_path/'backup-manifest.json').read_bytes()==original
    (tmp_path/'artifacts.tar').write_bytes(b'changed fixture')
    assert ops.verify_backup_content_files(tmp_path,m)=='FAIL'
    (tmp_path/'artifacts.tar').unlink();(tmp_path/'artifacts.tar').symlink_to(tmp_path/'metadata.dump')
    assert ops.verify_backup_content_files(tmp_path,m)=='UNKNOWN'


def test_inventory_new_snapshot_comparison_is_bounded_and_readonly(runtime,tmp_path,stable,monkeypatch):
    _,_,_,calls,read=runtime
    m=synthetic_backup(tmp_path,stable)
    monkeypatch.setattr(ops,'observe_content',lambda *a,**k:later(stable))
    result=ops.inventory_manifest(backup_directory=tmp_path,read=read,verify_files=True)['backup_handle']
    assert result['file_verification']=='PASS' and result['current_state_coverage']=='CURRENT'
    assert result['restore_effect']=='NOT_RUN'
    assert not any('run' in c or 'stop' in c for c in calls)
    (tmp_path/'metadata.dump').write_bytes(b'tampered fixed fixture')
    result=ops.inventory_manifest(backup_directory=tmp_path,read=read,verify_files=True)['backup_handle']
    assert result['file_verification']=='FAIL' and result['current_state_coverage']=='UNKNOWN'
    assert result['reason']=='FILE_INTEGRITY_FAILED'


@pytest.mark.parametrize('changing',[False,True])
def test_backup_fingerprints_bracket_copy_without_implicit_restart(tmp_path,stable,monkeypatch,changing):
    calls=[]
    monkeypatch.setattr(ops,'check_ownership',lambda:None)
    def run(args,**kw):
        calls.append(args)
        if 'pg_dump' in args: kw['stdout'].write(b'synthetic metadata fixture')
        stdout='db\n' if '--services' in args else ('0\n' if 'psql' in args else '')
        return subprocess.CompletedProcess(args,0,stdout)
    monkeypatch.setattr(ops,'run',run)
    monkeypatch.setattr(ops,'stream_helper',lambda code,output:output.write(b'synthetic artifact fixture'))
    value=copy.deepcopy(stable['fingerprints']);value['datasets']='b'*64
    passes=iter([stable,later(stable,fingerprints=value) if changing else later(stable)])
    monkeypatch.setattr(ops,'backup_content_observation',lambda:next(passes))
    target=tmp_path/'new'
    if changing:
        with pytest.raises(SystemExit,match='BACKUP_CONTENT_CHANGED'):ops.backup(target)
        assert not (target/'backup-manifest.json').exists()
        assert (target/'metadata.dump').exists()
    else:
        ops.backup(target)
        m=json.loads((target/'backup-manifest.json').read_text())
        assert m['schema_version']==2 and ops.valid_content(m['snapshot_content'])
        assert m['snapshot_content']['window_started_at']==stable['window_started_at']
        assert m['snapshot_content']['window_finished_at']==later(stable)['window_finished_at']
        assert ops.verify_backup_content_files(target,m)=='PASS'
        assert m['restore_effect']=='NOT_RUN'
    assert not any(any(word in c for word in ('up','restore','prune')) for c in calls)


def test_checksum_limits_and_snapshot_helper_command(tmp_path,stable,monkeypatch):
    m=synthetic_backup(tmp_path)
    monkeypatch.setattr(ops,'FILE_VERIFY_LIMIT',1)
    assert ops.verify_backup_content_files(tmp_path,m)=='UNKNOWN'
    seen=[]
    monkeypatch.setattr(ops,'inventory_read',lambda args:seen.append(args) or '{}')
    ops.backup_probe_read(ops.COMPOSE+['run','--entrypoint','python','snapshot','python','-c','controlled'])
    assert seen[0][-3:]==['snapshot','-c','controlled']


def test_future_and_malformed_envelopes_never_retrofit_legacy(runtime,tmp_path,stable):
    _,_,_,_,read=runtime
    m=synthetic_backup(tmp_path,stable)
    m['schema_version']=3
    (tmp_path/'backup-manifest.json').write_text(json.dumps(m))
    result=ops.inventory_manifest(backup_directory=tmp_path,read=read)['backup_handle']
    assert result['reason']=='INCOMPATIBLE_BACKUP_VERSION' and result['current_state_coverage']=='UNKNOWN'
    m['schema_version']=1
    (tmp_path/'backup-manifest.json').write_text(json.dumps(m))
    assert ops.inventory_manifest(backup_directory=tmp_path,read=read)['backup_handle']['reason']=='LEGACY_NO_SNAPSHOT'
    m['schema_version']=2;m.pop('snapshot_content')
    (tmp_path/'backup-manifest.json').write_text(json.dumps(m))
    assert ops.inventory_manifest(backup_directory=tmp_path,read=read)['backup_handle']['reason']=='SNAPSHOT_INVALID'


@pytest.mark.parametrize('future_snapshot,future_current', [(True,False),(False,True),(True,True)])
def test_future_windows_rejected_with_explicit_fixed_clock(stable,future_snapshot,future_current):
    from datetime import datetime,timezone
    now=datetime(2030,1,1,tzinfo=timezone.utc)
    snapshot=stable
    current=later(stable)
    if future_snapshot:
        snapshot=ops.seal_content(ops.content_identity(stable),'2099-01-01T00:00:00+00:00','2099-01-01T00:01:00+00:00')
        assert ops.valid_content(snapshot,now=now) is None
    if future_current:
        current=ops.seal_content(ops.content_identity(stable),'2099-01-01T00:02:00+00:00','2099-01-01T00:03:00+00:00')
        assert ops.valid_content(current,now=now) is None
    result=ops.compare_content(snapshot,current,now=now)
    assert result['current_state_coverage']=='UNKNOWN'
    assert result['restore_effect']=='NOT_RUN'


def test_current_time_boundary_and_offset_instants(stable):
    from datetime import datetime,timezone
    now=datetime(2030,1,1,0,3,tzinfo=timezone.utc)
    value=ops.content_identity(stable)
    snapshot=ops.seal_content(value,'2030-01-01T00:00:00+00:00','2030-01-01T00:03:00+00:00')
    current=ops.seal_content(value,now.isoformat(),now.isoformat())
    assert ops.valid_content(snapshot,now=now) is not None
    assert ops.compare_content(snapshot,current,now=now)['current_state_coverage']=='CURRENT'
    future=ops.seal_content(value,now.isoformat(),'2030-01-01T00:03:00.000001+00:00')
    assert ops.compare_content(snapshot,future,now=now)['current_state_coverage']=='UNKNOWN'
    offset=ops.seal_content(value,'2030-01-01T01:03:00+01:00','2030-01-01T01:03:00+01:00')
    assert ops.compare_content(snapshot,offset,now=now)['current_state_coverage']=='CURRENT'


@pytest.mark.parametrize('start,end',[
    ('not-a-time','2030-01-01T00:03:00+00:00'),
    ('2030-01-01T00:00:00','2030-01-01T00:03:00'),
    ('2030-01-01T00:03:00+00:00','2030-01-01T00:00:00+00:00'),
])
def test_fixed_clock_rejects_malformed_unzoned_and_reversed_windows(stable,start,end):
    from datetime import datetime,timezone
    block=ops.seal_content(ops.content_identity(stable),start,end)
    now=datetime(2030,1,1,0,3,tzinfo=timezone.utc)
    assert ops.valid_content(block,now=now) is None
    assert ops.compare_content(stable,block,now=now)['current_state_coverage']=='UNKNOWN'


def test_default_comparison_captures_one_shared_clock(stable,monkeypatch):
    from datetime import datetime,timezone
    calls=[]
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            calls.append(tz)
            return datetime(2030,1,1,tzinfo=timezone.utc)
    monkeypatch.setattr(ops,'datetime',Clock)
    assert ops.compare_content(stable,later(stable))['current_state_coverage']=='CURRENT'
    assert len(calls)==1
    future=ops.seal_content(ops.content_identity(stable),'2099-01-01T00:00:00+00:00','2099-01-01T00:01:00+00:00')
    assert ops.compare_content(future,future)['current_state_coverage']=='UNKNOWN'
    assert len(calls)==2
