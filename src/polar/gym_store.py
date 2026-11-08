"""Gym namespaces reuse immutable HistoryStore publication; no queue/job tracker."""
import fcntl
import os
import re
import time
import uuid
from contextlib import contextmanager
from .history_bundle import safe_root, read_file
from .history_store import HistoryStore
from .gym_contract import GymError, canonical, decode, sha, MAX_BYTES, SEMANTIC_FILES

class GymStore(HistoryStore):
    @contextmanager
    def locked(self):
        fd=os.open(safe_root(self.root)/'.gym.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            stop=time.monotonic()+5
            while True:
                try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    if time.monotonic()>=stop:raise GymError('GYM_BUSY')
                    time.sleep(.02)
            yield
        finally:os.close(fd)
    def record(self,parent,name,value):
        self._publish(parent,name,{'record.json':canonical(value)},file_limit=MAX_BYTES)
    def read_record(self,parent,name):
        raw=read_file(self.root,f'{parent}/{name}/record.json',MAX_BYTES)
        if {p.name for p in (self.root/parent/name).iterdir()}!={'record.json'}: raise GymError('RECORD_FILE_SET')
        value=decode(raw)
        if canonical(value)!=raw:raise GymError('NONCANONICAL_RECORD')
        return value
    def begin(self,config,bindings):
        aid=str(uuid.uuid4());namespace=config['namespace'];family='fixed-public-v1.1' if namespace=='retained' else sha(canonical(bindings))
        with self.locked():
            parent=f'gym-budgets/{namespace}/{family}';directory=self.root/parent
            existing=list(directory.iterdir()) if directory.exists() else []
            if namespace=='retained' and len(existing)>=2:raise GymError('RETAINED_PAIR_REPLAY_BUDGET_EXHAUSTED')
            row={'schema':'polar.gym-attempt-start/1','attempt_id':aid,'namespace':namespace,
                 'bindings':bindings,'started_ns':time.time_ns(),'status':'UNFINALIZED',
                 'family':family,'ordinal':len(existing)}
            self.record(parent,aid,row)
            self.record('gym-attempts/'+aid,'start',row)
        return row
    def finish(self,aid,value):
        self.validate_attempt(aid)
        with self.locked():self.record('gym-attempts/'+aid,'finish',value)
    def validate_attempt(self,aid):
        try:
            if str(uuid.UUID(aid))!=aid:raise ValueError()
        except (ValueError,AttributeError):raise GymError('INVALID_ATTEMPT_ID') from None
    def attempt(self,aid):
        self.validate_attempt(aid)
        start=self.read_record('gym-attempts/'+aid,'start')
        finishpath=self.root/'gym-attempts'/aid/'finish'
        if finishpath.is_symlink():raise GymError('UNSAFE_RECORD')
        finish=self.read_record('gym-attempts/'+aid,'finish') if finishpath.exists() else None
        return {'schema':'polar.gym-attempt/1','attempt_id':aid,'status':finish['status'] if finish else 'UNFINALIZED','start':start,'finish':finish}
    def publish(self,files,bindings):
        raws={name:canonical(files[name]) for name in SEMANTIC_FILES}
        manifest={'schema':'polar.gym-semantic-manifest/1','bindings':bindings,
                  'files':{n:{'sha256':sha(v),'bytes':len(v)} for n,v in raws.items()}}
        raw=canonical(manifest);experiment='gym-'+sha(raw);raws['manifest.json']=raw
        with self.locked(): self._publish('gym-experiments',experiment,raws,file_limit=MAX_BYTES)
        return experiment
    def report(self,experiment):
        if not isinstance(experiment,str) or not re.fullmatch(r'gym-[a-f0-9]{64}',experiment):raise GymError('INVALID_EXPERIMENT_ID')
        directory=self.root/'gym-experiments'/experiment
        if {p.name for p in directory.iterdir()}!=set(SEMANTIC_FILES)|{'manifest.json'}:raise GymError('SEMANTIC_FILE_SET')
        raw=read_file(self.root,f'gym-experiments/{experiment}/manifest.json',MAX_BYTES)
        if experiment!='gym-'+sha(raw):raise GymError('SEMANTIC_MANIFEST_HASH')
        manifest=decode(raw);files={}
        if set(manifest['files'])!=set(SEMANTIC_FILES):raise GymError('SEMANTIC_FILE_SET')
        for name,ref in manifest['files'].items():
            data=read_file(self.root,f'gym-experiments/{experiment}/{name}',MAX_BYTES)
            if sha(data)!=ref['sha256'] or len(data)!=ref['bytes']:raise GymError('SEMANTIC_FILE_HASH')
            files[name]=decode(data)
        return {'schema':'polar.gym-report/1','experiment_id':experiment,'manifest':manifest,'files':files}
