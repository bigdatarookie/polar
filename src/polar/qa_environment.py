"""Explicit task-owned synthetic API liveness, not application/financial QA."""
import argparse
import fcntl
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

LIMIT = 1024 * 1024
HEX = re.compile(r'[a-f0-9]{64}\Z')
GIT = re.compile(r'[a-f0-9]{40}\Z')
FIXTURE = {'schema': 'polar.qa-liveness-input/1', 'synthetic': True,
           'dataset': 'EMPTY', 'artifacts': 'EMPTY'}
LAYOUT='internal-api-loopback-relay/1'
CONTAINERS=('api','proxy')
NETWORKS=('net','front')


class Gap(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(ok, code):
    if not ok:
        raise Gap(code)


def raw(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def pairs(rows):
    result = {}
    for k, v in rows:
        require(k not in result, 'DUPLICATE_JSON_KEY')
        result[k] = v
    return result


def decode(data):
    require(len(data) <= LIMIT, 'JSON_SIZE_BOUND')
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Gap('INVALID_JSON')))
    except (ValueError, UnicodeError, RecursionError):
        raise Gap('INVALID_JSON') from None


def canonical(path):
    p = Path(path)
    require(p.is_absolute() and p == p.resolve(), 'CANONICAL_ABSOLUTE_PATH_REQUIRED')
    return p


def read(path, limit=LIMIT):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as f:
            require(stat.S_ISREG(os.fstat(f.fileno()).st_mode), 'REGULAR_FILE_REQUIRED')
            data = f.read(limit+1)
        require(len(data) <= limit, 'FILE_SIZE_BOUND')
        return data
    except OSError:
        raise Gap('FILE_UNAVAILABLE') from None


def write(path, value, exclusive=False):
    data = raw(value)
    require(len(data) <= LIMIT, 'STATE_SIZE_BOUND')
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
    else:
        # Refuse replacing a symlink/foreign file type, even though replace is atomic.
        if path.exists() or path.is_symlink():
            require(stat.S_ISREG(path.lstat().st_mode), 'REGULAR_FILE_REQUIRED')
        fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)



def publish_preparation(path, value):
    """Same fsync + atomic no-clobber hard-link boundary as PR30 publish()."""
    data = raw(value)
    require(len(data) <= LIMIT, 'RECEIPT_SIZE_BOUND')
    fd, name = tempfile.mkstemp(prefix='.preparation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.link(name, path)  # Never overwrite even an incomplete/foreign receipt.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(name)


def config(value):
    require(type(value) is dict and set(value) == {
        'schema', 'scenario', 'repository', 'commit', 'tree', 'image_id',
        'source_schema_sha256', 'fixture'}, 'INVALID_CONFIG')
    require(value['schema'] == 'polar.qa-environment-config/1', 'INVALID_CONFIG_SCHEMA')
    require(value['scenario'] == 'synthetic-api-liveness/1', 'SCENARIO_NOT_PREPARED')
    for field in ('commit', 'tree'):
        require(type(value[field]) is str and GIT.fullmatch(value[field]), 'INVALID_GIT_PIN')
    require(type(value['image_id']) is str and value['image_id'].startswith('sha256:')
            and HEX.fullmatch(value['image_id'][7:]), 'FULL_IMAGE_ID_REQUIRED')
    require(type(value['source_schema_sha256']) is str and HEX.fullmatch(value['source_schema_sha256']),
            'SCHEMA_HASH_REQUIRED')
    require(raw(value['fixture']) == raw(FIXTURE), 'EMPTY_SYNTHETIC_FIXTURE_REQUIRED')
    require(type(value['repository']) is str, 'INVALID_REPOSITORY')
    canonical(value['repository'])
    return value


class Commands:
    def __init__(self):
        self.end = time.monotonic()+180

    def run(self, argv):
        remaining = min(30, self.end-time.monotonic())
        require(remaining > 0, 'INVOCATION_DEADLINE')
        try:
            p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        except OSError:
            raise Gap('COMMAND_UNAVAILABLE') from None
        end = time.monotonic()+remaining
        output = bytearray()
        selector = selectors.DefaultSelector()
        try:
            selector.register(p.stdout, selectors.EVENT_READ)
            while True:
                left = end-time.monotonic()
                require(left > 0, 'COMMAND_DEADLINE')
                if not selector.select(min(.1, left)):
                    continue
                # Never spool stdout. One extra detection byte is discarded,
                # and overflow immediately enters owned group termination.
                chunk = os.read(p.stdout.fileno(), min(65536, LIMIT-len(output)+1))
                if not chunk:
                    break
                require(len(chunk) <= LIMIT-len(output), 'COMMAND_OUTPUT_BOUND')
                output.extend(chunk)
            try:
                code = p.wait(timeout=max(.001, end-time.monotonic()))
            except subprocess.TimeoutExpired:
                raise Gap('COMMAND_DEADLINE') from None
            require(code == 0, 'COMMAND_FAILED')
            return bytes(output)
        finally:
            selector.close()
            p.stdout.close()
            # Until wait() we retain the parent's PID even if it exited;
            # descendants holding stdout cannot evade the group deadline.
            if p.returncode is None:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                p.wait()


INERT_ENV = {
    'PYTHONPATH': '/candidate/src', 'PYTHONDONTWRITEBYTECODE': '1',
    'POLAR_ARTIFACT_ROOT': '/qa-empty',
    'POLAR_DATABASE_URL': 'postgresql://127.0.0.1:1/qa?connect_timeout=1',
    'POLAR_DB_PASSWORD_FILE': '/qa-absent',
    'POLAR_HISTORY_CURSOR_KEY_FILE': '/qa-absent',
    'POLAR_HISTORY_CALENDAR_DIR': '',
}


def environment_map(entries):
    require(type(entries) is list and len(entries) <= 1024, 'ENVIRONMENT_INVALID')
    result = {}
    for item in entries:
        require(type(item) is str and len(item) <= 65536 and '=' in item
                and '\x00' not in item, 'ENVIRONMENT_INVALID')
        key, value = item.split('=', 1)
        require(key and len(key) <= 256 and key not in result, 'ENVIRONMENT_INVALID')
        result[key] = value
    return result


class Docker:
    def __init__(self, commands, endpoint=None):
        self.commands = commands
        self.endpoint = endpoint or decode(commands.run([
            'docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}']))
        require(type(self.endpoint) is str and self.endpoint.startswith('unix:///')
                and '\n' not in self.endpoint, 'LOCAL_UNIX_DOCKER_REQUIRED')

    def run(self, *args):
        return self.commands.run(['docker', '--host', self.endpoint, *args])

    def image(self, image_id):
        rows = decode(self.run('image', 'inspect', image_id))
        require(type(rows) is list and len(rows) == 1 and rows[0]['Id'] == image_id,
                'IMAGE_NOT_AVAILABLE')
        require(not rows[0]['Config'].get('Volumes'), 'IMAGE_VOLUMES_NOT_PREPARED')
        image_env = rows[0]['Config'].get('Env')
        inherited = environment_map([] if image_env is None else image_env)
        inherited.update(INERT_ENV)
        return sha(raw(inherited))

    def image_identity(self, image_id):
        rows = decode(self.run('image', 'inspect', image_id))
        require(type(rows) is list and len(rows) == 1 and rows[0]['Id'] == image_id,
                'IMAGE_NOT_AVAILABLE')
        row = rows[0]
        require(row.get('Os') == 'linux' and row.get('Architecture') in ('arm64', 'amd64'),
                'IMAGE_PLATFORM_NOT_PREPARED')
        return {'os': row['Os'], 'architecture': row['Architecture']}

    def find(self, kind, name):
        args = ['container', 'ls', '-a'] if kind in CONTAINERS else ['network', 'ls']
        ids = self.run(*args, '--no-trunc', '--filter', 'name='+name,
                       '--format', '{{.ID}}').decode().splitlines()
        rows = []
        for resource_id in ids:
            require(HEX.fullmatch(resource_id), 'FULL_RESOURCE_ID_REQUIRED')
            row = decode(self.run('inspect' if kind in CONTAINERS else 'network',
                                 *([] if kind in CONTAINERS else ['inspect']), resource_id))[0]
            actual = row['Name'].lstrip('/')
            if actual == name:
                rows.append(row)
        require(len(rows) <= 1, 'RESOURCE_NAME_CONFLICT')
        return rows[0] if rows else None

    def create_network(self, name, labels, *, internal=True):
        args = ['network', 'create', '--driver', 'bridge']
        if internal:args.append('--internal')
        for k, v in sorted(labels.items()):
            args.extend(['--label', k+'='+v])
        self.run(*args, name)

    def create_api(self, name, labels, cfg, root, network):
        args = ['create', '--name', name, '--network', network, '--user', '10001:10001',
                '--read-only', '--no-healthcheck', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--tmpfs', '/tmp:rw,noexec,nosuid,size=16777216',
                '--entrypoint', 'python',
                '--mount', 'type=bind,src='+str(root/'source')+',dst=/candidate,readonly',
                '--mount', 'type=bind,src='+str(root/'empty')+',dst=/qa-empty,readonly']
        for k, v in sorted(labels.items()):
            args.extend(['--label', k+'='+v])
        for key, value in INERT_ENV.items():
            args.extend(['--env', key+'='+value])
        self.run(*args, cfg['image_id'], '-m', 'uvicorn', 'polar.api:app',
                 '--host', '0.0.0.0', '--port', '8000')

    def create_proxy(self,name,labels,cfg,root,network,upstream):
        args=['create','--name',name,'--network',network,'--user','10001:10001',
              '--read-only','--no-healthcheck','--cap-drop','ALL','--security-opt','no-new-privileges',
              '--tmpfs','/tmp:rw,noexec,nosuid,size=16777216',
              '--publish','127.0.0.1::8000','--entrypoint','python',
              '--mount','type=bind,src='+str(root/'source')+',dst=/candidate,readonly',
              '--mount','type=bind,src='+str(root/'empty')+',dst=/qa-empty,readonly']
        for k,v in sorted(labels.items()):args.extend(['--label',k+'='+v])
        for k,v in INERT_ENV.items():args.extend(['--env',k+'='+v])
        self.run(*args,cfg['image_id'],'-S','/candidate/src/polar/qa_environment_proxy.py','--upstream',upstream)

    def connect(self,network,resource_id):
        self.run('network','connect',network,resource_id)

    def start(self, resource_id):
        self.run('start', resource_id)

    def remove(self, kind, resource_id):
        self.run(*(['rm', '-f'] if kind in CONTAINERS else ['network', 'rm']), resource_id)


def exported(cfg, dest, commands):
    helper = Path(__file__).resolve().parents[2]/'scripts'/'polar-local.mjs'
    commands.run(['node', str(helper), 'export', cfg['repository'], cfg['commit'], cfg['tree'], str(dest)])


def verify_source(cfg, root):
    source = root/'source'
    require(source.is_dir() and not source.is_symlink(), 'SOURCE_UNAVAILABLE')
    manifest_bytes = read(source/'SOURCE-MANIFEST.json')
    m = decode(manifest_bytes)
    require(m['commit'] == cfg['commit'] and m['tree'] == cfg['tree'], 'SOURCE_PIN_CONFLICT')
    require(type(m['files']) is list and len(m['files']) <= 2000, 'SOURCE_MANIFEST_INVALID')
    expected = {'SOURCE-MANIFEST.json'}
    total = 0
    for row in m['files']:
        name = row['path']
        require(type(name) is str and name not in expected and not name.startswith('/')
                and '..' not in Path(name).parts, 'SOURCE_MANIFEST_INVALID')
        p = source/name
        require(p == p.resolve(), 'SOURCE_SYMLINK')
        data = read(p, 16*LIMIT)
        require(sha(data) == row['sha256'] and len(data) == row['bytes'], 'SOURCE_HASH_CONFLICT')
        total += len(data)
        require(total < 16*LIMIT, 'SOURCE_SIZE_BOUND')
        expected.add(name)
    observed = set()
    visited = 0
    for p in source.rglob('*'):
        visited += 1
        require(visited <= 4000, 'SOURCE_FILESET_BOUND')
        require(not p.is_symlink(), 'SOURCE_SYMLINK')
        if not p.is_dir():
            observed.add(str(p.relative_to(source)))
    require(observed == expected, 'SOURCE_FILESET_CONFLICT')
    require(sha(read(source/'src/polar/schema.sql')) == cfg['source_schema_sha256'], 'SCHEMA_HASH_CONFLICT')
    return sha(manifest_bytes)


def probe(url):
    # No proxy, redirects, or caller-selected remote route.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def get(route):
        with opener.open(url+route, timeout=2) as response:
            require(response.status == 200, 'HTTP_NOT_READY')
            data = response.read(LIMIT+1)
            require(len(data) <= LIMIT, 'HTTP_SIZE_BOUND')
            return data
    require(decode(get('/livez')) == {'status': 'ALIVE'}, 'LIVENESS_NOT_READY')
    body = get('/openapi.json')
    obj = decode(body)
    require(type(obj) is dict and '/livez' in obj.get('paths', {}), 'OPENAPI_NOT_READY')
    return sha(body)


def _probe_child(connection, url):
    try:
        connection.send(probe(url))
    except (OSError, ValueError, KeyError, TypeError):
        connection.send(None)
    finally:
        connection.close()


def bounded_probe(url, deadline):
    require(re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}', url), 'LOCAL_PROBE_REQUIRED')
    remaining = min(5, deadline-time.monotonic())
    require(remaining > 0, 'READINESS_DEADLINE')
    ctx = multiprocessing.get_context('spawn')
    parent, child = ctx.Pipe(duplex=False)
    worker = ctx.Process(target=_probe_child, args=(child, url))
    worker.start(); child.close()
    try:
        require(parent.poll(remaining), 'HTTP_PROBE_DEADLINE')
        try:
            result = parent.recv()
        except EOFError:
            raise Gap('HTTP_PROBE_FAILED') from None
        require(type(result) is str and HEX.fullmatch(result), 'HTTP_PROBE_FAILED')
        return result
    finally:
        parent.close()
        worker.join(.05)
        if worker.is_alive():
            worker.terminate(); worker.join(1)
        if worker.is_alive():
            worker.kill(); worker.join(1)
        require(not worker.is_alive(), 'HTTP_PROBE_CLEANUP_FAILED')


@contextmanager
def locked(root):
    require(root.is_dir() and root == root.resolve() and not root.is_symlink()
            and root.stat().st_uid == os.geteuid() and root.stat().st_mode & 0o077 == 0,
            'PRIVATE_OWNED_ROOT_REQUIRED')
    fd = os.open(root/'.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'LOCK_INVALID')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Gap('ROOT_BUSY') from None
        yield
    finally:
        os.close(fd)


class Environment:
    def __init__(self, root, commands=None, docker=None, exporter=exported, http=None):
        self.root = canonical(root)
        self.commands = commands or Commands()
        self.docker = docker
        self.exporter = exporter
        self.http = http or (lambda url: bounded_probe(url, self.commands.end))

    def state(self):
        owner = decode(read(self.root/'owner.json'))
        state = decode(read(self.root/'state.json'))
        require(owner.get('schema') == 'polar.qa-environment-owner/1'
                and state.get('schema') == 'polar.qa-environment-state/1', 'STATE_INVALID')
        require(owner['root'] == str(self.root) and owner['root_sha256'] == sha(str(self.root).encode()), 'ROOT_IDENTITY_CONFLICT')
        require(str(uuid.UUID(owner['operation'])) == owner['operation'], 'OPERATION_INVALID')
        require(state['operation'] == owner['operation'] and state['config_sha256'] == owner['config_sha256'], 'STATE_IDENTITY_CONFLICT')
        cfg = config(decode(read(self.root/'config.json', 65536)))
        require(sha(raw(cfg)) == owner['config_sha256'], 'CONFIG_CONFLICT')
        return owner, state, cfg

    def save(self, state):
        state['observed_at'] = datetime.now(timezone.utc).isoformat()
        write(self.root/'state.json', state)

    def labels(self, owner, cfg, kind):
        return {'polar.qa.operation': owner['operation'], 'polar.qa.config': owner['config_sha256'],
                'polar.qa.root': owner['root_sha256'], 'polar.qa.candidate': cfg['commit'],
                'polar.qa.role': kind}

    def resource(self, owner, state, cfg, kind):
        name = 'polar-qa-'+uuid.UUID(owner['operation']).hex+'-'+kind
        row = self.docker.find(kind, name)
        saved = state['resources'].get(kind)
        if row is None:
            return name, None
        require(HEX.fullmatch(row['Id']) and (saved is None or row['Id'] == saved), 'RESOURCE_ID_CONFLICT')
        labels = row.get('Labels', {}) if kind in NETWORKS else row['Config'].get('Labels', {})
        require(type(labels) is dict and all(labels.get(k) == v for k, v in self.labels(owner, cfg, kind).items())
                and 'com.docker.compose.project' not in labels, 'RESOURCE_LABEL_CONFLICT')
        relay=state.get('network_layout')==LAYOUT
        if kind in NETWORKS:
            require(row['Driver'] == 'bridge' and row['Internal'] is (kind=='net'), 'NETWORK_CONFLICT')
        else:
            require(sha(raw(environment_map(row['Config'].get('Env')))) ==
                    state.get('expected_environment_sha256'), 'CONTAINER_ENVIRONMENT_CONFLICT')
            h = row['HostConfig']
            command=(['-S','/candidate/src/polar/qa_environment_proxy.py','--upstream',
                      'polar-qa-'+uuid.UUID(owner['operation']).hex+'-api'] if kind=='proxy' else
                     ['-m','uvicorn','polar.api:app','--host','0.0.0.0','--port','8000'])
            require(row['Image'] == cfg['image_id'] and row['Config']['User'] == '10001:10001'
                    and row['Config']['Entrypoint'] == ['python']
                    and row['Config']['Cmd'] == command
                    and h['ReadonlyRootfs'] is True
                    and h['NetworkMode'] == state['resources'].get('front' if kind=='proxy' else 'net')
                    and h.get('Privileged') is False and h.get('CapDrop') == ['ALL']
                    and h.get('SecurityOpt') == ['no-new-privileges'], 'CONTAINER_CONFLICT')
            require(h.get('Tmpfs') == {'/tmp': 'rw,noexec,nosuid,size=16777216'}, 'TMPFS_CONFLICT')
            mounts = {(x['Source'], x['Destination'], x['RW'], x['Type'])
                      for x in row['Mounts'] if x['Type'] != 'tmpfs'}
            for x in row['Mounts']:
                if x['Type'] == 'tmpfs':
                    require(x['Destination'] == '/tmp' and x['RW'] is True, 'TMPFS_CONFLICT')
            require(mounts == {(str(self.root/'source'), '/candidate', False, 'bind'),
                               (str(self.root/'empty'), '/qa-empty', False, 'bind')}, 'MOUNT_CONFLICT')
            binds = h.get('PortBindings', {})
            if kind=='api' and relay:
                require(not binds and h.get('PublishAllPorts',False) is False,'PORT_CONFLICT')
                require(not any(row['NetworkSettings'].get('Ports',{}).values()),'PORT_CONFLICT')
            else:
                require(set(binds) == {'8000/tcp'} and len(binds['8000/tcp']) == 1
                        and binds['8000/tcp'][0]['HostIp'] == '127.0.0.1'
                        and (kind!='proxy' or binds['8000/tcp'][0].get('HostPort')==''), 'PORT_CONFLICT')
            if relay:
                expected={'polar-qa-'+uuid.UUID(owner['operation']).hex+'-'+k:state['resources'].get(k)
                          for k in (NETWORKS if kind=='proxy' else ('net',))}
                actual=row['NetworkSettings'].get('Networks',{})
                required=set(expected) if row['State']['Running'] or kind=='api' else {
                    'polar-qa-'+uuid.UUID(owner['operation']).hex+'-front'}
                require(required<=set(actual)<=set(expected),'CONTAINER_NETWORK_CONFLICT')
                for key,value in actual.items():
                    require(value['NetworkID']==expected[key] or
                            not row['State']['Running'] and value['NetworkID']=='',
                            'CONTAINER_NETWORK_CONFLICT')
        state['resources'][kind] = row['Id']
        self.save(state)  # recover exact create whose ID was not yet written
        return name, row

    def validate_endpoints(self,resources):
        api=resources.get('api');proxy=resources.get('proxy')
        for kind,allowed in (('net',{r['Id'] for r in (api,proxy) if r}),
                             ('front',{proxy['Id']} if proxy else set())):
            network=resources.get(kind)
            if network:require(set(network.get('Containers',{}))<=allowed,'FOREIGN_NETWORK_ENDPOINT')

    def preparation(self, owner, state, cfg, api, image_identity, proxy):
        # resource() already rejects image/user/command/env/mount/ownership mismatches.
        # Persist only allowed command strings and a hash of the COMPLETE environment.
        observed_image = self.docker.image_identity(api['Image'])
        require(observed_image == image_identity, 'RUNTIME_PLATFORM_CONFLICT')
        observed = {
            'container_id': api['Id'], 'image_id': api['Image'],
            'image_identity_type': 'docker-local-image-id', **observed_image,
            'configured_user': api['Config']['User'],
            'entrypoint': api['Config']['Entrypoint'], 'command': api['Config']['Cmd'],
            'effective_environment_sha256': sha(raw(environment_map(api['Config']['Env']))),
        }
        expected = {
            'candidate': {'commit': cfg['commit'], 'tree': cfg['tree']},
            'config_sha256': owner['config_sha256'], 'operation': owner['operation'],
            'source_manifest_sha256': state['source_manifest_sha256'],
            'source_schema_sha256': cfg['source_schema_sha256'],
            'fixture_sha256': sha(raw(FIXTURE)),
            'observer_source_sha256': sha(read(Path(__file__).resolve())),
            'image_id': cfg['image_id'], **image_identity,
            'configured_user': '10001:10001', 'entrypoint': ['python'],
            'command': ['-m', 'uvicorn', 'polar.api:app', '--host', '0.0.0.0', '--port', '8000'],
            'effective_environment_sha256': state['expected_environment_sha256'],
        }
        require(all(observed[k] == expected[k] for k in (
            'image_id', 'os', 'architecture', 'configured_user', 'entrypoint',
            'command', 'effective_environment_sha256')), 'RUNTIME_BINDING_MISMATCH')
        proxy_identity=self.docker.image_identity(proxy['Image'])
        require(proxy_identity==image_identity,'RUNTIME_PLATFORM_CONFLICT')
        observed['relay']={'container_id':proxy['Id'],'image_id':proxy['Image'],**proxy_identity,
                           'configured_user':proxy['Config']['User'],'entrypoint':proxy['Config']['Entrypoint'],
                           'command':proxy['Config']['Cmd'],
                           'effective_environment_sha256':sha(raw(environment_map(proxy['Config']['Env'])))}
        expected['relay']={'container_id':state['resources']['proxy'],'image_id':cfg['image_id'],**image_identity,
                           'configured_user':'10001:10001','entrypoint':['python'],
                           'command':['-S','/candidate/src/polar/qa_environment_proxy.py','--upstream',
                                      'polar-qa-'+uuid.UUID(owner['operation']).hex+'-api'],
                           'effective_environment_sha256':state['expected_environment_sha256']}
        expected['network_layout']=LAYOUT
        expected['relay_source_sha256']=sha(read(self.root/'source/src/polar/qa_environment_proxy.py'))
        require(observed['relay']==expected['relay'],'RUNTIME_BINDING_MISMATCH')
        path = self.root/'preparation.json'
        if path.exists() or path.is_symlink():
            body = read(path)
            receipt = decode(body)
            require(body == raw(receipt) and receipt.get('schema') == 'polar.observed-preparation/1'
                    and receipt.get('preparation') == 'PREPARED'
                    and receipt.get('scenario_started') is False
                    and receipt.get('expected') == expected
                    and receipt.get('observed') == observed
                    and receipt.get('not_started') is True,
                    'PREPARATION_RECEIPT_CONFLICT')
        else:
            require(api['State'].get('Status') == 'created'
                    and api['State']['Running'] is False
                    and proxy['State'].get('Status')=='created' and proxy['State']['Running'] is False,
                    'PRESTART_OBSERVATION_REQUIRED')
            stamp = datetime.now(timezone.utc).isoformat()
            receipt = {
                'schema': 'polar.observed-preparation/1',
                'producer': {'version': 'polar.qa-environment-observation/1',
                             'sha256': sha(read(Path(__file__).resolve()))},
                'created_at': stamp, 'observed_at': stamp, 'compared_at': stamp,
                'published_at': datetime.now(timezone.utc).isoformat(),
                'preparation': 'PREPARED', 'scenario_started': False,
                'not_started': True, 'expected': expected, 'observed': observed,
                'environment_values': 'REDACTED_HASH_ONLY',
                'source_binding': 'EXACT_VERIFIED_READ_ONLY_GIT_OVERLAY',
            }
            publish_preparation(path, receipt)
            body = read(path)
            require(body == raw(receipt), 'PREPARATION_PUBLICATION_CONFLICT')
        # Also close a prior crash window after link but before directory fsync.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        ref = {'path': str(path), 'sha256': sha(body)}
        require(state.get('preparation_ref', ref) == ref, 'PREPARATION_REFERENCE_CONFLICT')
        state['preparation_ref'] = ref
        self.save(state)
        return ref

    def result(self, owner, state, status, reason=None, **extra):
        result = {'schema': 'polar.qa-environment-result/1', 'status': status, 'reason': reason,
                  'operation': owner['operation'], 'config_sha256': owner['config_sha256'],
                  'root': str(self.root), 'resources': dict(state['resources']),
                  'db_readiness': 'NOT_APPLICABLE', 'qa_verdict': 'NOT_RUN',
                  'preparation': state.get('preparation_ref'), **extra}
        result['observed_at'] = datetime.now(timezone.utc).isoformat()
        result_file = 'result-'+str(uuid.uuid4())+'.json'
        write(self.root/result_file, result, exclusive=True)
        state['last_result_ref'] = result_file
        state['last_result'] = result
        self.save(state)
        return result

    def prepare(self, cfg):
        cfg = config(cfg)
        repo = canonical(cfg['repository'])
        require(not self.root.is_relative_to(repo)
                and not any((p/'.git').exists() for p in self.root.parents),
                'ROOT_INSIDE_REPOSITORY')
        require(',' not in str(self.root) and '\n' not in str(self.root), 'INVALID_MOUNT_PATH')
        if not self.root.exists():
            self.root.mkdir(mode=0o700)
            owner = {'schema': 'polar.qa-environment-owner/1', 'operation': str(uuid.uuid4()),
                     'root': str(self.root), 'root_sha256': sha(str(self.root).encode()),
                     'config_sha256': sha(raw(cfg))}
            write(self.root/'owner.json', owner, True)
            write(self.root/'config.json', cfg, True)
            write(self.root/'state.json', {'schema': 'polar.qa-environment-state/1',
                  'operation': owner['operation'], 'config_sha256': owner['config_sha256'],
                  'resources': {}, 'phase': 'CREATED', 'attempts': 0,'network_layout':LAYOUT}, True)
        # No mutation, even .lock creation, in a foreign existing directory.
        self.state()
        with locked(self.root):
            owner, state, stored = self.state()
            require(stored == cfg, 'CONFIG_CONFLICT')
            require(state['phase'] != 'CLEANED', 'OPERATION_ALREADY_CLEANED')
            state['attempts'] += 1
            state['host'] = {'observed_at': datetime.now(timezone.utc).isoformat(),
                             'load': list(os.getloadavg()), 'logical_cpus': os.cpu_count(),
                             'python_version': sys.version.split()[0], 'python_executable': sys.executable,
                             'python_sha256': sha(read(Path(sys.executable).resolve(), 64*LIMIT)),
                             'disk_free_bytes': shutil.disk_usage(self.root).free,
                             'storage_policy_bytes': 64*1024**3,
                             'total_polar_attribution': 'UNKNOWN'}
            self.save(state)
            try:
                require(state.get('network_layout')==LAYOUT,'LEGACY_LAYOUT_REQUIRES_FRESH_ROOT')
                self.docker = self.docker or Docker(self.commands, state.get('docker_endpoint'))
                state['docker_endpoint'] = self.docker.endpoint
                self.save(state)
                expected_env = self.docker.image(cfg['image_id'])
                image_identity = self.docker.image_identity(cfg['image_id'])
                require(state.get('expected_environment_sha256', expected_env) == expected_env,
                        'IMAGE_ENVIRONMENT_CONFLICT')
                state['expected_environment_sha256'] = expected_env
                self.save(state)
                if not (self.root/'source').exists():
                    self.exporter(cfg, self.root/'source', self.commands)
                manifest = verify_source(cfg, self.root)
                require(state.get('source_manifest_sha256', manifest) == manifest, 'SOURCE_MANIFEST_CONFLICT')
                state['source_manifest_sha256'] = manifest
                self.save(state)
                if not (self.root/'empty').exists():
                    (self.root/'empty').mkdir(mode=0o555)
                require((self.root/'empty').is_dir() and not (self.root/'empty').is_symlink()
                        and not list((self.root/'empty').iterdir()), 'EMPTY_SCOPE_CONFLICT')
                # Verify both existing resources before creating either.
                net_name, net = self.resource(owner, state, cfg, 'net')
                api_name, api = self.resource(owner, state, cfg, 'api')
                require(not api or net is not None, 'NETWORK_MISSING')
                front_name,front=self.resource(owner,state,cfg,'front')
                proxy_name,proxy=self.resource(owner,state,cfg,'proxy')
                self.validate_endpoints({'net':net,'api':api,'front':front,'proxy':proxy})
                if net is None:
                    require('net' not in state['resources'], 'RECORDED_NETWORK_MISSING')
                    state['phase'] = 'NETWORK_INTENT'; self.save(state)
                    self.docker.create_network(net_name, self.labels(owner, cfg, 'net'))
                    _, net = self.resource(owner, state, cfg, 'net')
                    require(net is not None, 'NETWORK_CREATE_UNOBSERVED')
                if api is None:
                    require('api' not in state['resources'], 'RECORDED_CONTAINER_MISSING')
                    state['phase'] = 'CONTAINER_INTENT'; self.save(state)
                    self.docker.create_api(api_name, self.labels(owner, cfg, 'api'), cfg, self.root, net['Id'])
                    _, api = self.resource(owner, state, cfg, 'api')
                    require(api is not None, 'CONTAINER_CREATE_UNOBSERVED')
                if front is None:
                    require('front' not in state['resources'],'RECORDED_NETWORK_MISSING')
                    state['phase']='FRONT_INTENT';self.save(state)
                    self.docker.create_network(front_name,self.labels(owner,cfg,'front'),internal=False)
                    _,front=self.resource(owner,state,cfg,'front')
                    require(front is not None,'NETWORK_CREATE_UNOBSERVED')
                if proxy is None:
                    require('proxy' not in state['resources'],'RECORDED_CONTAINER_MISSING')
                    state['phase']='RELAY_INTENT';self.save(state)
                    self.docker.create_proxy(proxy_name,self.labels(owner,cfg,'proxy'),cfg,self.root,front['Id'],api_name)
                    _,proxy=self.resource(owner,state,cfg,'proxy')
                    require(proxy is not None,'CONTAINER_CREATE_UNOBSERVED')
                if net_name not in proxy['NetworkSettings']['Networks']:
                    require(not proxy['State']['Running'],'CONTAINER_NETWORK_CONFLICT')
                    self.docker.connect(net['Id'],proxy['Id'])
                    _,proxy=self.resource(owner,state,cfg,'proxy')
                require(set(proxy['NetworkSettings']['Networks'])=={net_name,front_name},'CONTAINER_NETWORK_CONFLICT')
                self.validate_endpoints({'net':net,'api':api,'front':front,'proxy':proxy})
                preparation = self.preparation(owner, state, cfg, api, image_identity,proxy)
                if not api['State']['Running']:
                    self.docker.start(api['Id'])
                    _, api = self.resource(owner, state, cfg, 'api')
                require(api['State']['Running'], 'CONTAINER_NOT_RUNNING')
                if not proxy['State']['Running']:
                    self.docker.start(proxy['Id'])
                    _,proxy=self.resource(owner,state,cfg,'proxy')
                require(proxy['State']['Running'],'CONTAINER_NOT_RUNNING')
                _,net=self.resource(owner,state,cfg,'net')
                _,front=self.resource(owner,state,cfg,'front')
                self.validate_endpoints({'net':net,'front':front,'api':api,'proxy':proxy})
                ports = proxy['NetworkSettings']['Ports'].get('8000/tcp')
                require(type(ports) is list and len(ports) == 1 and ports[0]['HostIp'] == '127.0.0.1'
                        and ports[0]['HostPort'].isdigit() and 1 <= int(ports[0]['HostPort']) <= 65535, 'LOOPBACK_PORT_UNOBSERVED')
                url = 'http://127.0.0.1:'+ports[0]['HostPort']
                end = min(time.monotonic()+30, self.commands.end)
                while True:
                    try:
                        openapi_hash = self.http(url)
                        break
                    except (OSError, ValueError):
                        require(time.monotonic() < end, 'READINESS_DEADLINE')
                        time.sleep(.1)
                state['phase'] = 'PREPARED'
                return self.result(owner, state, 'PREPARED', endpoint=url,
                                   openapi_sha256=openapi_hash, source_manifest_sha256=manifest,
                                   source_schema_sha256=cfg['source_schema_sha256'], fixture_sha256=sha(raw(FIXTURE)),
                                   observed_image_id=api['Image'], commit=cfg['commit'], tree=cfg['tree'])
            except Gap as exc:
                return self.result(owner, state, 'NOT_PREPARED', exc.code)
            except OSError:
                return self.result(owner, state, 'NOT_PREPARED', 'PREPARATION_OR_STORAGE_UNAVAILABLE')

    def cleanup(self, operation, config_sha256):
        self.state()
        with locked(self.root):
            owner, state, cfg = self.state()
            require(owner['operation'] == operation and owner['config_sha256'] == config_sha256,
                    'CLEANUP_IDENTITY_CONFLICT')
            try:
                self.docker = self.docker or Docker(self.commands, state.get('docker_endpoint'))
                if 'expected_environment_sha256' not in state:
                    state['expected_environment_sha256'] = self.docker.image(cfg['image_id'])
                    self.save(state)
                _, net = self.resource(owner, state, cfg, 'net')
                _, api = self.resource(owner, state, cfg, 'api')
                front=proxy=None
                if state.get('network_layout')==LAYOUT:
                    _,front=self.resource(owner,state,cfg,'front')
                    _,proxy=self.resource(owner,state,cfg,'proxy')
                # A foreign endpoint on our network blocks ALL deletion.
                self.validate_endpoints({'net':net,'api':api,'front':front,'proxy':proxy})
                for kind, row in (('proxy',proxy),('api', api),('front',front),('net', net)):
                    if row:
                        self.docker.remove(kind, row['Id'])
                        _, after = self.resource(owner, state, cfg, kind)
                        require(after is None, 'CLEANUP_NOT_OBSERVED')
                state['phase'] = 'CLEANED'
                return self.result(owner, state, 'CLEANED')
            except Gap as exc:
                return self.result(owner, state, 'NOT_CLEANED', exc.code)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='verb', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('config'); prep.add_argument('--root', required=True)
    clean = sub.add_parser('cleanup'); clean.add_argument('--root', required=True)
    clean.add_argument('--operation', required=True); clean.add_argument('--config-sha256', required=True)
    args = p.parse_args(argv)
    try:
        env = Environment(args.root)
        result = (env.prepare(decode(read(canonical(args.config), 65536))) if args.verb == 'prepare'
                  else env.cleanup(args.operation, args.config_sha256))
    except Gap as exc:
        result = {'schema': 'polar.qa-environment-result/1', 'status': 'NOT_PREPARED' if args.verb == 'prepare' else 'NOT_CLEANED',
                  'reason': exc.code, 'qa_verdict': 'NOT_RUN'}
    except (OSError, KeyError, TypeError, AttributeError, ValueError, RecursionError):
        result = {'schema': 'polar.qa-environment-result/1', 'status': 'NOT_PREPARED' if args.verb == 'prepare' else 'NOT_CLEANED',
                  'reason': 'INVALID_OR_UNAVAILABLE_INPUT', 'qa_verdict': 'NOT_RUN'}
    body = raw(result)
    require(len(body) <= 65536, 'OUTPUT_BOUND')
    print(body.decode(), end='')
    return 0 if result['status'] in ('PREPARED', 'CLEANED') else 1
