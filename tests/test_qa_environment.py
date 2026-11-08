"""Ownership/reconciliation faults against a fake daemon, no Docker or API calls."""
import copy
from pathlib import Path
import time
import pytest
from polar.qa_environment import Environment, Gap, FIXTURE, sha, raw, write, decode, read, config

IMAGE = 'sha256:'+'a'*64
NET, API = 'b'*64, 'c'*64


class Commands:
    end = float('inf')


class Daemon:
    endpoint = 'unix:///fake-daemon.sock'

    def __init__(self):
        self.rows = {}; self.calls = []; self.fail = None; self.volumes = False
        self.foreign = {'owner-container': 'unchanged', 'owner-network': 'unchanged'}

    def image(self, image_id):
        if self.volumes:
            raise Gap('IMAGE_VOLUMES_NOT_PREPARED')

    def find(self, kind, name):
        row = self.rows.get(kind)
        return copy.deepcopy(row) if row and row['Name'].lstrip('/') == name else None

    def create_network(self, name, labels):
        self.calls.append(('create', 'net'))
        self.rows['net'] = {'Name': name, 'Id': NET, 'Labels': labels, 'Driver': 'bridge',
                            'Internal': True, 'Containers': {}}

    def create_api(self, name, labels, cfg, root, network):
        self.calls.append(('create', 'api'))
        if self.fail == 'create':
            raise Gap('COMMAND_FAILED')
        self.rows['api'] = {'Name': '/'+name, 'Id': API, 'Image': IMAGE,
            'Config': {'Labels': labels, 'User': '10001:10001', 'Entrypoint': ['python'],
                       'Cmd': ['-m','uvicorn','polar.api:app','--host','0.0.0.0','--port','8000']},
            'HostConfig': {'ReadonlyRootfs': True, 'Privileged': False, 'NetworkMode': network,
                           'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                           'Tmpfs': {'/tmp':'rw,noexec,nosuid,size=16777216'},
                           'PortBindings': {'8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': ''}]}},
            'Mounts': [{'Source': str(root/'source'), 'Destination': '/candidate', 'Type':'bind','RW':False},
                       {'Source':str(root/'empty'), 'Destination':'/qa-empty','Type':'bind','RW':False}],
            'State': {'Running': False}, 'NetworkSettings': {'Ports': {}}}
        if self.fail == 'after-create':
            raise Gap('COMMAND_DEADLINE')

    def start(self, resource_id):
        self.calls.append(('start', resource_id))
        self.rows['api']['State']['Running'] = True
        self.rows['api']['NetworkSettings']['Ports'] = {'8000/tcp':[{'HostIp':'127.0.0.1','HostPort':'49001'}]}
        self.rows['net']['Containers'] = {API: {}}

    def remove(self, kind, resource_id):
        assert self.rows[kind]['Id'] == resource_id
        self.calls.append(('remove', kind, resource_id))
        del self.rows[kind]
        if kind == 'api':
            self.rows['net']['Containers'] = {}


def export(cfg, dest, commands):
    (dest/'src/polar').mkdir(parents=True)
    (dest/'src/polar/schema.sql').write_bytes(b'synthetic-schema')
    write(dest/'SOURCE-MANIFEST.json', {'commit':cfg['commit'], 'tree':cfg['tree'],
         'files':[{'path':'src/polar/schema.sql','bytes':16,'sha256':sha(b'synthetic-schema')}], 'bytes':16})


@pytest.fixture
def fixture(tmp_path):
    base = tmp_path.resolve()
    repo = base/'repo'; repo.mkdir()
    cfg = {'schema':'polar.qa-environment-config/1','scenario':'synthetic-api-liveness/1',
           'repository':str(repo),'commit':'1'*40,'tree':'2'*40,'image_id':IMAGE,
           'source_schema_sha256':sha(b'synthetic-schema'),'fixture':copy.deepcopy(FIXTURE)}
    d = Daemon()
    e = Environment(base/'environment', Commands(), d, export, lambda url: 'd'*64)
    return e, cfg, d


def clean(e, result):
    return e.cleanup(result['operation'], result['config_sha256'])


def test_repeat_and_exact_idempotent_cleanup(fixture):
    e, cfg, d = fixture
    a = e.prepare(cfg); before = list(d.calls); b = e.prepare(cfg)
    assert a['status'] == b['status'] == 'PREPARED'
    assert a['operation'] == b['operation'] and a['resources'] == b['resources']
    assert d.calls == before
    assert a['db_readiness'] == 'NOT_APPLICABLE' and a['qa_verdict'] == 'NOT_RUN'
    assert clean(e,a)['status'] == 'CLEANED'
    count = len(d.calls)
    assert clean(e,a)['status'] == 'CLEANED' and len(d.calls) == count
    assert d.foreign == {'owner-container':'unchanged','owner-network':'unchanged'}
    with pytest.raises(Gap, match='ALREADY_CLEANED'):
        e.prepare(cfg)


@pytest.mark.parametrize('fault', ['create', 'after-create'])
def test_partial_failure_and_recovery_without_duplicate_network(fixture, fault):
    e,cfg,d = fixture; d.fail = fault
    first = e.prepare(cfg)
    assert first['status'] == 'NOT_PREPARED' and first['resources']['net'] == NET
    d.fail = None
    recovered = e.prepare(cfg)
    assert recovered['status'] == 'PREPARED'
    assert d.calls.count(('create','net')) == 1
    assert d.calls.count(('create','api')) == (2 if fault == 'create' else 1)
    assert clean(e,recovered)['status'] == 'CLEANED'


def test_partial_failure_cleanup(fixture):
    e,cfg,d=fixture; d.fail='create'
    a=e.prepare(cfg)
    assert clean(e,a)['status'] == 'CLEANED'
    assert ('remove','net',NET) in d.calls


@pytest.mark.parametrize('fault', ['label','id','mount','port','foreign-endpoint'])
def test_foreign_or_replaced_resources_block_all_cleanup(fixture, fault):
    e,cfg,d=fixture; a=e.prepare(cfg)
    if fault == 'label': d.rows['api']['Config']['Labels']['polar.qa.config']='foreign'
    if fault == 'id': d.rows['api']['Id']='e'*64
    if fault == 'mount': d.rows['api']['Mounts'][0]['Source']='/owner'
    if fault == 'port': d.rows['api']['HostConfig']['PortBindings']['8000/tcp'][0]['HostIp']='0.0.0.0'
    if fault == 'foreign-endpoint': d.rows['net']['Containers']['f'*64]={}
    result=clean(e,a)
    assert result['status']=='NOT_CLEANED'
    assert not any(x[0]=='remove' for x in d.calls)


def test_conflicting_config_and_cleanup_identity(fixture):
    e,cfg,d=fixture; a=e.prepare(cfg); before=list(d.calls)
    altered={**cfg,'tree':'3'*40}
    with pytest.raises(Gap,match='CONFIG_CONFLICT'): e.prepare(altered)
    with pytest.raises(Gap,match='CLEANUP_IDENTITY_CONFLICT'): e.cleanup(a['operation'],'0'*64)
    assert d.calls==before


@pytest.mark.parametrize('tamper', ['schema','extra','symlink'])
def test_source_tampering_blocks_start(fixture, tamper):
    e,cfg,d=fixture; d.fail='create'; a=e.prepare(cfg); before=list(d.calls)
    source=e.root/'source'
    if tamper=='schema': (source/'src/polar/schema.sql').write_text('wrong')
    if tamper=='extra': (source/'extra').write_text('wrong')
    if tamper=='symlink': (source/'extra').symlink_to('/etc/passwd')
    d.fail=None
    assert e.prepare(cfg)['status']=='NOT_PREPARED' and d.calls==before
    assert clean(e,a)['status']=='CLEANED'


def test_image_volume_rejection_creates_nothing(fixture):
    e,cfg,d=fixture; d.volumes=True
    assert e.prepare(cfg)['reason']=='IMAGE_VOLUMES_NOT_PREPARED' and d.calls==[]


def test_readiness_failure_retains_owned_resources(fixture):
    e,cfg,d=fixture
    def failed(url): raise Gap('HTTP_NOT_READY')
    e.http=failed; e.commands.end=time.monotonic()-1
    a=e.prepare(cfg)
    assert a['status']=='NOT_PREPARED' and a['reason']=='READINESS_DEADLINE'
    assert a['resources']=={'net':NET,'api':API}
    assert clean(e,a)['status']=='CLEANED'


def test_root_symlink_rejected_without_write(fixture):
    e,cfg,d=fixture
    target=e.root.parent/'target';target.mkdir()
    alias=e.root.parent/'alias';alias.symlink_to(target)
    with pytest.raises(Gap,match='CANONICAL'):
        Environment(alias)
    assert list(target.iterdir())==[]


def test_root_in_git_rejected(fixture):
    e,cfg,d=fixture
    env=Environment(Path(cfg['repository'])/'private',Commands(),d,export)
    with pytest.raises(Gap,match='ROOT_INSIDE_REPOSITORY'): env.prepare(cfg)
    assert not env.root.exists()


def test_unsupported_scenario_and_strict_pins(fixture):
    e,cfg,d=fixture
    for change in ({'scenario':'real-owner-copy'}, {'image_id':'some-tag'}, {'commit':'HEAD'},
                   {'fixture':{**FIXTURE,'synthetic':False}}):
        with pytest.raises(Gap): config({**cfg,**change})
    assert not e.root.exists()


def test_existing_foreign_directory_is_not_modified(fixture):
    e,cfg,d=fixture; e.root.mkdir(); (e.root/'foreign').write_text('preserve')
    with pytest.raises(Gap): e.prepare(cfg)
    assert {x.name for x in e.root.iterdir()}=={'foreign'}


def test_manifest_and_bytes_rewrite_blocked_against_recorded_identity(fixture):
    e,cfg,d=fixture; d.fail='create'; e.prepare(cfg)
    m=decode(read(e.root/'source/SOURCE-MANIFEST.json'))
    m['extra']='edited'
    write(e.root/'source/SOURCE-MANIFEST.json',m)
    assert e.prepare(cfg)['reason']=='SOURCE_MANIFEST_CONFLICT'


def test_other_git_tree_root_rejected(fixture):
    e,cfg,d=fixture
    other=e.root.parent/'other';other.mkdir();(other/'.git').write_text('gitdir: other')
    env=Environment(other/'qa',Commands(),d,export)
    with pytest.raises(Gap,match='ROOT_INSIDE_REPOSITORY'):env.prepare(cfg)
    assert not env.root.exists()


@pytest.mark.parametrize('field,value', [('CapDrop',[]),('SecurityOpt',[]),('Privileged',True)])
def test_cleanup_rejects_weakened_container_config(fixture,field,value):
    e,cfg,d=fixture;a=e.prepare(cfg)
    d.rows['api']['HostConfig'][field]=value
    assert clean(e,a)['status']=='NOT_CLEANED'
    assert not any(x[0]=='remove' for x in d.calls)


def test_real_export_helper_without_docker(fixture):
    from polar.qa_environment import Commands, exported, verify_source
    import subprocess
    e,cfg,d=fixture
    # A disposable literal Git repository, independent of mutable checkout HEAD.
    # No owner repository/index/branch write or image/API call.
    repository=Path(cfg['repository'])
    (repository/'src/polar').mkdir(parents=True)
    (repository/'src/polar/schema.sql').write_bytes(b'synthetic-schema')
    (repository/'pyproject.toml').write_text('[project]\nname="literal-qa"\n')
    def git(*args):
        return subprocess.check_output(['git','-C',str(repository),*args],stderr=subprocess.DEVNULL).decode().strip()
    git('init','-q');git('add','src/polar/schema.sql','pyproject.toml')
    git('-c','user.name=QA Fixture','-c','user.email=qa@example.invalid','commit','-qm','literal fixture')
    pin=git('rev-parse','HEAD');tree=git('rev-parse','HEAD^{tree}')
    cfg={**cfg,'commit':pin,'tree':tree}
    e.root.mkdir()
    exported(cfg,e.root/'source',Commands())
    result=verify_source(cfg,e.root)
    assert len(result)==64
    manifest=decode(read(e.root/'source/SOURCE-MANIFEST.json'))
    assert manifest['commit']==pin and manifest['tree']==tree
    assert {r['path'] for r in manifest['files']}=={'src/polar/schema.sql','pyproject.toml'}



def test_docker_command_contract_without_daemon(fixture):
    from polar.qa_environment import Docker
    e,cfg,d=fixture
    class Capture:
        def __init__(self): self.calls=[]
        def run(self,args):self.calls.append(args);return b'[]'
    c=Capture(); client=Docker(c,'unix:///local.sock')
    client.create_api('test',{},cfg,e.root,NET)
    args=c.calls[0]
    assert args[:3]==['docker','--host','unix:///local.sock']
    assert args[3]=='create' and args[args.index('--network')+1]==NET
    assert args[args.index('--publish')+1]=='127.0.0.1::8000'
    assert '--read-only' in args and args[args.index('--entrypoint')+1]=='python'
    assert cfg['image_id'] in args and not any('password=' in x for x in args)
    client.remove('api',API);client.remove('net',NET)
    assert c.calls[-2][3:]==['rm','-f',API] and c.calls[-1][3:]==['network','rm',NET]


def test_bounded_probe_rejects_remote_or_expired_without_child():
    from polar.qa_environment import bounded_probe
    with pytest.raises(Gap,match='LOCAL_PROBE_REQUIRED'):
        bounded_probe('http://owner-service:8000', time.monotonic()+1)
    with pytest.raises(Gap,match='READINESS_DEADLINE'):
        bounded_probe('http://127.0.0.1:1', time.monotonic()-1)


def test_bounded_probe_closed_loopback_reaps_child():
    import multiprocessing
    import socket
    from polar.qa_environment import bounded_probe
    # Hold an unlistening task-owned socket: no API/server and no owner port probing.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        before={p.pid for p in multiprocessing.active_children()}
        with pytest.raises(Gap,match='HTTP_PROBE_FAILED'):
            bounded_probe('http://127.0.0.1:'+str(port),time.monotonic()+5)
        assert {p.pid for p in multiprocessing.active_children()}==before


def test_failed_result_preserved_across_recovery_and_cleanup(fixture):
    e,cfg,d=fixture;d.fail='create'
    e.prepare(cfg)
    previous=decode(read(e.root/'state.json'))['last_result_ref']
    failed=read(e.root/previous)
    d.fail=None
    a=e.prepare(cfg);clean(e,a)
    assert read(e.root/previous)==failed
    assert decode(failed)['status']=='NOT_PREPARED'
    assert len(list(e.root.glob('result-*.json')))==3
