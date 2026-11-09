"""Ownership/reconciliation faults against a fake daemon, no Docker or API calls."""
import copy
from pathlib import Path
import time
import pytest
from polar.qa_environment import (Environment, Gap, FIXTURE, INERT_ENV, sha, raw, write,
                                  decode, read, config, environment_map)

IMAGE = 'sha256:'+'a'*64
NET, API = 'b'*64, 'c'*64
FRONT, PROXY = 'd'*64, 'e'*64
IMAGE_ENV = ['PATH=/image/bin', 'PYTHONPATH=/image-default']


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
        return sha(raw({**environment_map(IMAGE_ENV), **INERT_ENV}))

    def image_identity(self, image_id):
        return {'os': 'linux', 'architecture': 'arm64'}

    def find(self, kind, name):
        row = self.rows.get(kind)
        return copy.deepcopy(row) if row and row['Name'].lstrip('/') == name else None

    def create_network(self, name, labels, *, internal=True):
        kind='net' if internal else 'front'
        self.calls.append(('create', kind))
        self.rows[kind] = {'Name': name, 'Id': NET if internal else FRONT, 'Labels': labels, 'Driver': 'bridge',
                            'Internal': internal, 'Containers': {}}

    def create_api(self, name, labels, cfg, root, network):
        self.calls.append(('create', 'api'))
        if self.fail == 'create':
            raise Gap('COMMAND_FAILED')
        self.rows['api'] = {'Name': '/'+name, 'Id': API, 'Image': IMAGE,
            'Config': {'Labels': labels, 'User': '10001:10001', 'Entrypoint': ['python'],
                       'Env': [k+'='+v for k,v in {**environment_map(IMAGE_ENV),**INERT_ENV}.items()],
                       'Cmd': ['-m','uvicorn','polar.api:app','--host','0.0.0.0','--port','8000']},
            'HostConfig': {'ReadonlyRootfs': True, 'Privileged': False, 'NetworkMode': network,
                           'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                           'Tmpfs': {'/tmp':'rw,noexec,nosuid,size=16777216'},
                           'PortBindings': {}},
            'Mounts': [{'Source': str(root/'source'), 'Destination': '/candidate', 'Type':'bind','RW':False},
                       {'Source':str(root/'empty'), 'Destination':'/qa-empty','Type':'bind','RW':False}],
            'State': {'Running': False, 'Status': 'created'}, 'NetworkSettings': {'Ports': {},'Networks': {self.rows['net']['Name']:{'NetworkID':network}}}}
        if self.fail == 'after-create':
            raise Gap('COMMAND_DEADLINE')

    def create_proxy(self,name,labels,cfg,root,network,upstream):
        # Same immutable image/env/mount safety properties, distinct role/network.
        self.calls.append(('create','proxy'))
        self.rows['proxy']=copy.deepcopy(self.rows['api'])
        row=self.rows['proxy'];row.update(Name='/'+name,Id=PROXY)
        row['Config']['Labels']=labels
        row['Config']['Cmd']=['-S','/candidate/src/polar/qa_environment_proxy.py','--upstream',upstream]
        row['State']={'Running':False,'Status':'created'}
        row['HostConfig']['NetworkMode']=network
        row['HostConfig']['PortBindings']={'8000/tcp':[{'HostIp':'127.0.0.1','HostPort':''}]}
        row['NetworkSettings']={'Ports':{},'Networks':{self.rows['front']['Name']:{'NetworkID':network}}}

    def connect(self,network,resource_id):
        self.calls.append(('connect',network,resource_id))
        self.rows['proxy']['NetworkSettings']['Networks'][self.rows['net']['Name']]={'NetworkID':network}

    def start(self, resource_id):
        self.calls.append(('start', resource_id))
        kind='api' if resource_id==API else 'proxy'
        self.rows[kind]['State']={'Running':True,'Status':'running'}
        self.rows['net']['Containers'][resource_id]={}
        if kind=='proxy':
            self.rows['front']['Containers'][resource_id]={}
            self.rows[kind]['NetworkSettings']['Ports']={'8000/tcp':[{'HostIp':'127.0.0.1','HostPort':'49001'}]}

    def remove(self, kind, resource_id):
        assert self.rows[kind]['Id'] == resource_id
        self.calls.append(('remove', kind, resource_id))
        del self.rows[kind]
        if kind in ('api','proxy'):
            for network in ('net','front'):
                if network in self.rows:self.rows[network]['Containers'].pop(resource_id,None)


def export(cfg, dest, commands):
    (dest/'src/polar').mkdir(parents=True)
    (dest/'src/polar/schema.sql').write_bytes(b'synthetic-schema')
    (dest/'src/polar/qa_environment_proxy.py').write_bytes(b'synthetic-relay')
    write(dest/'SOURCE-MANIFEST.json', {'commit':cfg['commit'], 'tree':cfg['tree'],
         'files':[{'path':'src/polar/schema.sql','bytes':16,'sha256':sha(b'synthetic-schema')},
                  {'path':'src/polar/qa_environment_proxy.py','bytes':len(b'synthetic-relay'),'sha256':sha(b'synthetic-relay')}], 'bytes':16+len(b'synthetic-relay')})


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
    if fault == 'port': d.rows['proxy']['HostConfig']['PortBindings']['8000/tcp'][0]['HostIp']='0.0.0.0'
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
    assert a['resources']=={'net':NET,'api':API,'front':FRONT,'proxy':PROXY}
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
    assert '--publish' not in args
    client.create_proxy('relay',{},cfg,e.root,FRONT,'polar-qa-'+'1'*32+'-api')
    relay=c.calls[-1]
    assert relay[relay.index('--publish')+1]=='127.0.0.1::8000'
    assert relay[relay.index('--network')+1]==FRONT
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


@pytest.mark.parametrize('fault', ['altered','missing','extra','duplicate'])
def test_unbound_recovery_environment_rejects_without_resource_mutation(fixture,fault):
    e,cfg,d=fixture;a=e.prepare(cfg)
    state=decode(read(e.root/'state.json'));state['resources'].pop('api')
    write(e.root/'state.json',state)
    d.rows['api']['State']['Running']=False
    entries=d.rows['api']['Config']['Env']
    if fault=='altered':
        entries[:]=['POLAR_DATABASE_URL=postgresql://owner.invalid/private' if x.startswith('POLAR_DATABASE_URL=') else x for x in entries]
    if fault=='missing':
        entries[:]=[x for x in entries if not x.startswith('POLAR_DB_PASSWORD_FILE=')]
    if fault=='extra':entries.append('POLAR_OWNER_DATA=/owner')
    if fault=='duplicate':entries.append(entries[0])
    before=list(d.calls)
    assert e.prepare(cfg)['status']=='NOT_PREPARED'
    assert 'api' not in decode(read(e.root/'state.json'))['resources']
    assert clean(e,a)['status']=='NOT_CLEANED'
    assert 'api' not in decode(read(e.root/'state.json'))['resources']
    assert d.calls==before and d.rows['api']['State']['Running'] is False


def test_legacy_missing_environment_binding_derived_before_adoption(fixture):
    e,cfg,d=fixture;a=e.prepare(cfg)
    state=decode(read(e.root/'state.json'));state.pop('expected_environment_sha256')
    write(e.root/'state.json',state)
    assert clean(e,a)['status']=='CLEANED'
    assert decode(read(e.root/'state.json'))['expected_environment_sha256']==sha(raw({**environment_map(IMAGE_ENV),**INERT_ENV}))


def test_exact_image_environment_merge_and_hash_without_docker(fixture):
    from polar.qa_environment import Docker
    e,cfg,d=fixture
    class Image:
        def run(self,argv):
            return raw([{'Id':IMAGE,'Config':{'Env':IMAGE_ENV,'Volumes':None}}])
    expected=Docker(Image(),'unix:///fake.sock').image(IMAGE)
    assert expected==sha(raw({**environment_map(IMAGE_ENV),**INERT_ENV}))
    assert INERT_ENV['PYTHONPATH']=='/candidate/src'


@pytest.mark.parametrize('bad', [False,0,{},'', ['A=1','A=2'], ['MISSING_EQUALS']])
def test_malformed_environment_is_not_falsey_absence(bad):
    with pytest.raises(Gap,match='ENVIRONMENT_INVALID'):environment_map(bad)


def test_command_exact_output_bound_and_no_spool(monkeypatch):
    import sys
    from polar import qa_environment as module
    def forbidden(*args,**kwargs):raise AssertionError('STDOUT_SPOOL_FORBIDDEN')
    monkeypatch.setattr(module.tempfile,'TemporaryFile',forbidden)
    value=module.Commands().run([sys.executable,'-c','import os;os.write(1,b"x"*1048576)'])
    assert len(value)==module.LIMIT


def test_command_overflow_immediately_reaps_owned_child_without_spool(monkeypatch):
    import sys,subprocess
    from polar import qa_environment as module
    spawned=[];original=subprocess.Popen
    def capture(*args,**kwargs):
        child=original(*args,**kwargs);spawned.append(child);return child
    monkeypatch.setattr(module.subprocess,'Popen',capture)
    monkeypatch.setattr(module.tempfile,'TemporaryFile',lambda *a,**k: (_ for _ in ()).throw(AssertionError('NO_SPOOL')))
    with pytest.raises(Gap,match='COMMAND_OUTPUT_BOUND'):
        module.Commands().run([sys.executable,'-c','import os,time;os.write(1,b"x"*4194304);time.sleep(10)'])
    assert len(spawned)==1 and spawned[0].returncode is not None and spawned[0].stdout.closed


def test_command_nonzero_and_deadline_reap(monkeypatch):
    import sys,subprocess
    from polar import qa_environment as module
    spawned=[];original=subprocess.Popen
    def capture(*args,**kwargs):
        child=original(*args,**kwargs);spawned.append(child);return child
    monkeypatch.setattr(module.subprocess,'Popen',capture)
    with pytest.raises(Gap,match='COMMAND_FAILED'):
        module.Commands().run([sys.executable,'-c','raise SystemExit(7)'])
    command=module.Commands();command.end=time.monotonic()+.15
    with pytest.raises(Gap,match='COMMAND_DEADLINE'):
        command.run([sys.executable,'-c','import time;time.sleep(10)'])
    assert all(p.returncode is not None and p.stdout.closed for p in spawned)


def test_command_parent_exit_does_not_evade_pipe_deadline(monkeypatch):
    import sys,subprocess
    from polar import qa_environment as module
    original=subprocess.Popen;spawned=[]
    def capture(*args,**kwargs):
        child=original(*args,**kwargs);spawned.append(child);return child
    monkeypatch.setattr(module.subprocess,'Popen',capture)
    command=module.Commands();command.end=time.monotonic()+.5
    code='import subprocess,sys;subprocess.Popen([sys.executable,"-c","import time;time.sleep(10)"])'
    with pytest.raises(Gap,match='COMMAND_DEADLINE'):
        command.run([sys.executable,'-c',code])
    assert len(spawned)==1 and spawned[0].returncode is not None and spawned[0].stdout.closed


def test_image_falsey_environment_does_not_become_empty():
    from polar.qa_environment import Docker
    class Image:
        def run(self,argv):return raw([{'Id':IMAGE,'Config':{'Env':False,'Volumes':None}}])
    with pytest.raises(Gap,match='ENVIRONMENT_INVALID'):
        Docker(Image(),'unix:///fake.sock').image(IMAGE)


def test_preparation_is_published_before_same_container_start(fixture):
    e, cfg, d = fixture
    original = d.start
    def start(resource_id):
        receipt = decode(read(e.root/'preparation.json'))
        assert resource_id in (API,PROXY)
        assert receipt['observed']['container_id'] == API
        assert receipt['observed']['relay']['container_id'] == PROXY
        assert receipt['observed']['image_id'] == IMAGE
        assert receipt['not_started'] is True
        assert receipt['expected']['candidate'] == {'commit': cfg['commit'], 'tree': cfg['tree']}
        assert 'PATH' not in str(receipt) and '/image/bin' not in str(receipt)
        original(resource_id)
    d.start = start
    result = e.prepare(cfg)
    assert result['status'] == 'PREPARED'
    assert result['preparation'] == {
        'path': str(e.root/'preparation.json'),
        'sha256': sha(read(e.root/'preparation.json'))}
    assert result['observed_image_id'] == IMAGE and 'image_id' not in result
    receipt_bytes = read(e.root/'preparation.json')
    assert e.prepare(cfg)['preparation'] == result['preparation']
    assert read(e.root/'preparation.json') == receipt_bytes


@pytest.mark.parametrize('fault', ['publication', 'platform', 'running-without-receipt'])
def test_receipt_failure_blocks_scenarios(fixture, monkeypatch, fault):
    e, cfg, d = fixture
    probes = []
    e.http = lambda url: probes.append(url)
    if fault == 'publication':
        def fail(*args):
            raise OSError('no publication')
        monkeypatch.setattr('polar.qa_environment.publish_preparation', fail)
    elif fault == 'platform':
        calls = []
        def identity(image_id):
            calls.append(image_id)
            return {'os': 'linux', 'architecture': 'arm64' if len(calls) == 1 else 'amd64'}
        d.image_identity = identity
    else:
        create = d.create_api
        def running(*args):
            create(*args)
            d.rows['api']['State'] = {'Running': True, 'Status': 'running'}
        d.create_api = running
    result = e.prepare(cfg)
    assert result['status'] == 'NOT_PREPARED' and result['qa_verdict'] == 'NOT_RUN'
    assert not probes and not any(call[0] == 'start' for call in d.calls)


def test_receipt_tampering_blocks_restart_without_overwrite(fixture):
    e, cfg, d = fixture
    assert e.prepare(cfg)['status'] == 'PREPARED'
    path = e.root/'preparation.json'
    receipt = decode(read(path))
    receipt['observed']['container_id'] = 'f'*64
    write(path, receipt)
    tampered = read(path)
    d.rows['api']['State'] = {'Running': False, 'Status': 'exited'}
    before = list(d.calls)
    result = e.prepare(cfg)
    assert result['status'] == 'NOT_PREPARED'
    assert result['reason'] == 'PREPARATION_RECEIPT_CONFLICT'
    assert d.calls == before and read(path) == tampered


def test_internal_api_and_dual_network_relay(fixture):
    e,cfg,d=fixture;result=e.prepare(cfg)
    assert result['status']=='PREPARED'
    assert d.rows['api']['HostConfig']['PortBindings']=={}
    assert d.rows['api']['NetworkSettings']['Ports']=={}
    assert len(d.rows['api']['NetworkSettings']['Networks'])==1
    assert len(d.rows['proxy']['NetworkSettings']['Networks'])==2
    assert d.rows['net']['Internal'] is True and d.rows['front']['Internal'] is False
    receipt=decode(read(e.root/'preparation.json'))
    assert receipt['observed']['relay']['container_id']==PROXY
    assert receipt['observed']['container_id']==API
    assert receipt['expected']['relay_source_sha256']==sha(b'synthetic-relay')


@pytest.mark.parametrize('phase',['created','connected'])
def test_interrupted_relay_connect_recovers_exact_graph(fixture,phase):
    e,cfg,d=fixture;original=d.connect
    def interrupted(network,resource_id):
        if phase=='connected':original(network,resource_id)
        raise Gap('COMMAND_DEADLINE')
    d.connect=interrupted
    first=e.prepare(cfg)
    assert first['status']=='NOT_PREPARED'
    assert not any(call[0]=='start' for call in d.calls)
    d.connect=original
    assert e.prepare(cfg)['status']=='PREPARED'
    for kind in ('api','proxy','net','front'):
        assert d.calls.count(('create',kind))==1
    assert clean(e,first)['status']=='CLEANED'


@pytest.mark.parametrize('fault',['label','environment','network','foreign-endpoint'])
def test_relay_foreign_evidence_blocks_reuse_and_all_cleanup(fixture,fault):
    e,cfg,d=fixture;result=e.prepare(cfg)
    if fault=='label':d.rows['proxy']['Config']['Labels']['polar.qa.role']='owner'
    if fault=='environment':d.rows['proxy']['Config']['Env'].append('UNEXPECTED=value')
    if fault=='network':d.rows['proxy']['NetworkSettings']['Networks']['foreign']={'NetworkID':'f'*64}
    if fault=='foreign-endpoint':d.rows['front']['Containers']['f'*64]={}
    before=list(d.calls)
    assert e.prepare(cfg)['status']=='NOT_PREPARED'
    assert clean(e,result)['status']=='NOT_CLEANED'
    assert d.calls==before


def test_relay_binding_mismatch_prevents_both_starts(fixture):
    e,cfg,d=fixture;original=d.create_proxy
    def wrong(*args):
        original(*args);d.rows['proxy']['Image']='sha256:'+'f'*64
    d.create_proxy=wrong
    assert e.prepare(cfg)['status']=='NOT_PREPARED'
    assert not any(call[0]=='start' for call in d.calls)


def test_relay_fixed_upstream_routes_and_body_bound(monkeypatch):
    from polar import qa_environment_proxy as relay
    calls=[]
    class Response:
        status=302
        def read(self,size):calls.append(('read',size));return b'{}'
        def getheader(self,key,default):return default
    class Connection:
        def __init__(self,*args,**kwargs):calls.append((args,kwargs))
        def request(self,*args,**kwargs):calls.append((args,kwargs))
        def getresponse(self):return Response()
        def close(self):calls.append('closed')
    monkeypatch.setattr(relay.http.client,'HTTPConnection',Connection)
    upstream='polar-qa-'+'a'*32+'-api'
    assert relay.fetch(upstream,'/livez')==(302,b'{}','application/json')
    assert calls[0]==((upstream,8000),{'timeout':2})
    assert calls[1]==(('GET','/livez'),{'headers':{'Accept':'application/json','Connection':'close'}})
    assert ('read',relay.LIMIT+1) in calls and calls[-1]=='closed'
    before=list(calls)
    for host,path in [('owner','/livez'),(upstream,'http://owner/'),(upstream,'/livez?target=owner')]:
        with pytest.raises(ValueError):relay.fetch(host,path)
    assert calls==before
    monkeypatch.setattr(Response,'read',lambda self,size:b'x'*(relay.LIMIT+1))
    with pytest.raises(ValueError,match='BODY_BOUND'):relay.fetch(upstream,'/openapi.json')
    assert calls[-1]=='closed'


@pytest.mark.parametrize('host_port',['49001','0',None])
def test_relay_non_ephemeral_config_blocks_start_and_cleanup(fixture,host_port):
    e,cfg,d=fixture;original=d.create_proxy
    def changed(*args):
        original(*args)
        d.rows['proxy']['HostConfig']['PortBindings']['8000/tcp'][0]['HostPort']=host_port
    d.create_proxy=changed
    result=e.prepare(cfg)
    assert result['status']=='NOT_PREPARED' and result['reason']=='PORT_CONFLICT'
    assert not any(call[0]=='start' for call in d.calls)
    before=list(d.calls)
    assert clean(e,result)['status']=='NOT_CLEANED'
    assert d.calls==before


def test_fixed_relay_host_port_reuse_blocks_all_mutation(fixture):
    e,cfg,d=fixture;result=e.prepare(cfg)
    d.rows['proxy']['HostConfig']['PortBindings']['8000/tcp'][0]['HostPort']='49001'
    before=list(d.calls)
    refused=e.prepare(cfg)
    assert refused['status']=='NOT_PREPARED' and refused['reason']=='PORT_CONFLICT'
    assert clean(e,result)['status']=='NOT_CLEANED'
    assert d.calls==before
