"""Explicit task-owned synthetic API liveness, not application/financial QA."""
import argparse
import fcntl
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
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
        with tempfile.TemporaryFile() as out:
            try:
                p = subprocess.Popen(argv, stdout=out, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
            except OSError:
                raise Gap('COMMAND_UNAVAILABLE') from None
            try:
                end = time.monotonic()+remaining
                while p.poll() is None:
                    require(time.monotonic() < end, 'COMMAND_DEADLINE')
                    require(os.fstat(out.fileno()).st_size <= LIMIT, 'COMMAND_OUTPUT_BOUND')
                    time.sleep(.025)
                require(p.returncode == 0, 'COMMAND_FAILED')
                out.seek(0); data = out.read(LIMIT+1)
                require(len(data) <= LIMIT, 'COMMAND_OUTPUT_BOUND')
                return data
            finally:
                if p.poll() is None:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait()


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

    def find(self, kind, name):
        args = ['container', 'ls', '-a'] if kind == 'api' else ['network', 'ls']
        ids = self.run(*args, '--no-trunc', '--filter', 'name='+name,
                       '--format', '{{.ID}}').decode().splitlines()
        rows = []
        for resource_id in ids:
            require(HEX.fullmatch(resource_id), 'FULL_RESOURCE_ID_REQUIRED')
            row = decode(self.run('inspect' if kind == 'api' else 'network',
                                 *([] if kind == 'api' else ['inspect']), resource_id))[0]
            actual = row['Name'].lstrip('/')
            if actual == name:
                rows.append(row)
        require(len(rows) <= 1, 'RESOURCE_NAME_CONFLICT')
        return rows[0] if rows else None

    def create_network(self, name, labels):
        args = ['network', 'create', '--internal', '--driver', 'bridge']
        for k, v in sorted(labels.items()):
            args.extend(['--label', k+'='+v])
        self.run(*args, name)

    def create_api(self, name, labels, cfg, root, network):
        args = ['create', '--name', name, '--network', network, '--user', '10001:10001',
                '--read-only', '--no-healthcheck', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--tmpfs', '/tmp:rw,noexec,nosuid,size=16777216',
                '--publish', '127.0.0.1::8000', '--entrypoint', 'python',
                '--mount', 'type=bind,src='+str(root/'source')+',dst=/candidate,readonly',
                '--mount', 'type=bind,src='+str(root/'empty')+',dst=/qa-empty,readonly']
        for k, v in sorted(labels.items()):
            args.extend(['--label', k+'='+v])
        for item in ('PYTHONPATH=/candidate/src', 'PYTHONDONTWRITEBYTECODE=1',
                     'POLAR_ARTIFACT_ROOT=/qa-empty',
                     'POLAR_DATABASE_URL=postgresql://127.0.0.1:1/qa?connect_timeout=1',
                     'POLAR_DB_PASSWORD_FILE=/qa-absent',
                     'POLAR_HISTORY_CURSOR_KEY_FILE=/qa-absent', 'POLAR_HISTORY_CALENDAR_DIR='):
            args.extend(['--env', item])
        self.run(*args, cfg['image_id'], '-m', 'uvicorn', 'polar.api:app',
                 '--host', '0.0.0.0', '--port', '8000')

    def start(self, resource_id):
        self.run('start', resource_id)

    def remove(self, kind, resource_id):
        self.run(*(['rm', '-f'] if kind == 'api' else ['network', 'rm']), resource_id)


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
        name = 'polar-qa-'+uuid.UUID(owner['operation']).hex+('-api' if kind == 'api' else '-net')
        row = self.docker.find(kind, name)
        saved = state['resources'].get(kind)
        if row is None:
            return name, None
        require(HEX.fullmatch(row['Id']) and (saved is None or row['Id'] == saved), 'RESOURCE_ID_CONFLICT')
        labels = row.get('Labels', {}) if kind == 'net' else row['Config'].get('Labels', {})
        require(type(labels) is dict and all(labels.get(k) == v for k, v in self.labels(owner, cfg, kind).items())
                and 'com.docker.compose.project' not in labels, 'RESOURCE_LABEL_CONFLICT')
        if kind == 'net':
            require(row['Driver'] == 'bridge' and row['Internal'] is True, 'NETWORK_CONFLICT')
        else:
            h = row['HostConfig']
            require(row['Image'] == cfg['image_id'] and row['Config']['User'] == '10001:10001'
                    and row['Config']['Entrypoint'] == ['python']
                    and row['Config']['Cmd'] == ['-m', 'uvicorn', 'polar.api:app', '--host', '0.0.0.0', '--port', '8000']
                    and h['ReadonlyRootfs'] is True and h['NetworkMode'] == state['resources'].get('net')
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
            require(set(binds) == {'8000/tcp'} and len(binds['8000/tcp']) == 1
                    and binds['8000/tcp'][0]['HostIp'] == '127.0.0.1', 'PORT_CONFLICT')
        state['resources'][kind] = row['Id']
        self.save(state)  # recover exact create whose ID was not yet written
        return name, row

    def result(self, owner, state, status, reason=None, **extra):
        result = {'schema': 'polar.qa-environment-result/1', 'status': status, 'reason': reason,
                  'operation': owner['operation'], 'config_sha256': owner['config_sha256'],
                  'root': str(self.root), 'resources': dict(state['resources']),
                  'db_readiness': 'NOT_APPLICABLE', 'qa_verdict': 'NOT_RUN', **extra}
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
                  'resources': {}, 'phase': 'CREATED', 'attempts': 0}, True)
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
                self.docker = self.docker or Docker(self.commands, state.get('docker_endpoint'))
                state['docker_endpoint'] = self.docker.endpoint
                self.save(state)
                self.docker.image(cfg['image_id'])
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
                if net:
                    require(set(net.get('Containers', {})) <= ({api['Id']} if api else set()),
                            'FOREIGN_NETWORK_ENDPOINT')
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
                if not api['State']['Running']:
                    self.docker.start(api['Id'])
                    _, api = self.resource(owner, state, cfg, 'api')
                require(api['State']['Running'], 'CONTAINER_NOT_RUNNING')
                ports = api['NetworkSettings']['Ports'].get('8000/tcp')
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
                                   image_id=cfg['image_id'], commit=cfg['commit'], tree=cfg['tree'])
            except Gap as exc:
                return self.result(owner, state, 'NOT_PREPARED', exc.code)

    def cleanup(self, operation, config_sha256):
        self.state()
        with locked(self.root):
            owner, state, cfg = self.state()
            require(owner['operation'] == operation and owner['config_sha256'] == config_sha256,
                    'CLEANUP_IDENTITY_CONFLICT')
            try:
                self.docker = self.docker or Docker(self.commands, state.get('docker_endpoint'))
                _, net = self.resource(owner, state, cfg, 'net')
                _, api = self.resource(owner, state, cfg, 'api')
                # A foreign endpoint on our network blocks ALL deletion.
                if net:
                    require(set(net.get('Containers', {})) <= ({api['Id']} if api else set()),
                            'FOREIGN_NETWORK_ENDPOINT')
                for kind, row in (('api', api), ('net', net)):
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
