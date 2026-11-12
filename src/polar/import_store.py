"""Atomic immutable evidence and checkpoints inside existing private artifact storage."""
import fcntl
import os
from pathlib import Path
import uuid
from contextlib import contextmanager

from .history_bundle import read_file, safe_root, relative
from .history_store import HistoryStore, fsync_directory
from .import_contract import (MAX_FILE, require, canonical, decode, digest, sha, hash_value,
                              scope_id, job_id, result_kind)


class ImportStore(HistoryStore):
    def __init__(self, root, limit, fixture=False, raw_sip=False, raw_profile='first-unit', selected_scope_sha256=None):
        super().__init__(root, limit)
        self.raw_sip=raw_sip
        require(raw_profile in ('first-unit','remaining3490','all-adjusted100','all-adjusted-selected'),'IMPORT_POLICY_MISMATCH')
        self.raw_profile=raw_profile
        self.selected_scope_sha256=selected_scope_sha256
        if raw_profile=='all-adjusted-selected':
            require(raw_sip,'IMPORT_POLICY_MISMATCH');hash_value(selected_scope_sha256)
        self._read_cache=None
        self._lock_held=False
        self._terminal_finalization=False
        self.base = ("imports-fixture-v1/" if fixture else "imports-v1/")+scope_id()
        if raw_sip:
            from .import_raw_sip import UNIT_SHA
            self.base=("imports-rawsip-fixture-v1/" if fixture else "imports-rawsip-v1/")+UNIT_SHA
            if raw_profile=='remaining3490':
                from .import_raw_profile import AGGREGATE_SHA
                self.base=('imports-rawsip-aggregate-fixture-v1/' if fixture else
                           'imports-rawsip-aggregate-v1/')+AGGREGATE_SHA
            if raw_profile=='all-adjusted100':
                from .import_adjusted_sip import SCOPE_SHA
                self.base=('imports-adjustedsip100-fixture-v1/' if fixture else
                           'imports-adjustedsip100-v1/')+SCOPE_SHA

            if raw_profile=='all-adjusted-selected':
                self.base=('imports-adjustedsip-selected-fixture-v1/' if fixture else
                           'imports-adjustedsip-selected-v1/')+selected_scope_sha256

    @contextmanager
    def locked(self):
        directory = self._directory(self.base)
        fd = os.open(directory/"executor.lock", os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: require(False,"IMPORT_EXECUTOR_BUSY")
            self._scope_bytes=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())
            self._lock_held=True
            self._terminal_finalization=False
            yield
        finally:
            self._read_cache=None
            self._lock_held=False
            self._raw_execution_commits=None
            self._raw_execution_rows=None
            os.close(fd)  # actual kernel lock, never blindly delete a stale PID file

    def path(self,name):
        return self.base+"/"+relative(name)

    def exists(self,name):
        path = self.root/self.path(name)
        require(not path.is_symlink(),"IMPORT_UNSAFE_PATH")
        return path.exists()

    def raw(self,name):
        return read_file(safe_root(self.root), self.path(name), limit=MAX_FILE)

    def read(self,name):
        cached=name.startswith(('requests/','responses/','outcomes/','successes/','cache-imports/','plans/'))
        if cached and self._read_cache is not None and name in self._read_cache:return self._read_cache[name]
        value = decode(self.raw(name))
        require(canonical(value) == self.raw(name),"IMPORT_NONCANONICAL_RECORD")
        if cached and self._read_cache is not None:self._read_cache[name]=value
        return value

    def write(self,name,value,*,replace=False):
        raw = canonical(value)
        require(len(raw) <= MAX_FILE,"IMPORT_RECORD_SIZE")
        self.write_raw(name,raw,replace=replace)

    def write_raw(self,name,raw,*,replace=False):
        require(len(raw) <= MAX_FILE,"IMPORT_RECORD_SIZE")
        relative_name = Path(self.path(name))
        directory = self._directory(str(relative_name.parent))
        target = directory/relative_name.name
        require(not target.is_symlink(),"IMPORT_UNSAFE_PATH")
        if target.exists() and not replace:
            require(self.raw(name) == raw,"IMPORT_IMMUTABLE_CONFLICT")
            return
        previous=target.stat().st_size if target.exists() else 0
        if self.raw_sip and self.raw_profile in ('remaining3490','all-adjusted100','all-adjusted-selected'):
            from .import_raw_profile import AGGREGATE_POLICY
            if self.raw_profile=='all-adjusted100':
                from .import_adjusted_sip import POLICY as AGGREGATE_POLICY
            if self.raw_profile=='all-adjusted-selected':
                require(hasattr(self,'scope_policy'),'IMPORT_POLICY_MISMATCH')
                AGGREGATE_POLICY=self.scope_policy
            if not self._lock_held:
                # The existing control channel intentionally remains writable
                # from another process while the executor holds its lock.
                require(name=='control.json' or name.startswith('controls/'),'IMPORT_EXECUTOR_LOCK_REQUIRED')
                directory_root=self.root/self.base
                self._scope_bytes=sum(p.stat().st_size for p in directory_root.rglob('*') if p.is_file())
            ceiling=AGGREGATE_POLICY['additional_bytes']
            if self._lock_held and not self._terminal_finalization:
                ceiling-=AGGREGATE_POLICY['terminal_reserve_bytes']
            require(hasattr(self,'_scope_bytes') and self._scope_bytes+len(raw)-previous
                    <=ceiling,'IMPORT_SCOPE_STORAGE_LIMIT')
        temporary = directory/(".partial-"+str(uuid.uuid4()))
        try:
            with temporary.open("xb") as output:
                output.write(raw);output.flush();os.fsync(output.fileno())
            temporary.chmod(0o400)
            if replace:
                os.replace(temporary,target)
            else:
                os.link(temporary,target,follow_symlinks=False)
            fsync_directory(directory)
            if hasattr(self,'_scope_bytes'):self._scope_bytes+=len(raw)-previous
            if self._read_cache is not None:self._read_cache.pop(name,None)
        finally:
            if temporary.exists(): temporary.unlink()

    def list(self,directory):
        path = self.root/self.path(directory)
        if not path.exists(): return []
        require(not path.is_symlink(),"IMPORT_UNSAFE_PATH")
        values = []
        for p in path.iterdir():
            if p.name.startswith(".partial-"): continue
            require(p.is_file() and not p.is_symlink() and p.name.endswith(".json"),"IMPORT_FILE_SET")
            values.append(directory+"/"+p.name)
        require(len(values)<=100000,"IMPORT_RECORD_LIMIT")
        return sorted(values)

    def object(self,raw):
        key = sha(raw)
        self.write_raw("objects/"+key+".json",raw)
        return {"sha256":key,"bytes":len(raw),"path":"objects/"+key+".json"}

    def object_read(self,ref):
        hash_value(ref["sha256"])
        require(ref["path"] == "objects/"+ref["sha256"]+".json","IMPORT_OBJECT_IDENTITY")
        raw = self.raw(ref["path"])
        require(sha(raw)==ref["sha256"] and len(raw)==ref["bytes"],"IMPORT_OBJECT_HASH")
        return raw

    def commits(self):
        """A committed result is authoritative even if the checkpoint update was interrupted."""
        if self.raw_sip:
            from .import_raw_sip import commits
            return commits(self)
        cache = {}
        for name in self.list("successes")+self.list("cache-imports"):
            record = self.read(name)
            require(record["schema"] == "polar.import-cache-commit/1" and
                    Path(name).stem == digest(record), "IMPORT_CACHE_SCHEMA")
            for jid,versions in record["jobs"].items():
                hash_value(jid)
                for result in versions:
                    require(result["job_id"]==jid and result["response_sha256"]==digest(result["response"]),
                            "IMPORT_CACHE_INTEGRITY")
                    require(job_id(result["request"]) == jid and result["kind"] == result_kind(result["response"]) and
                            result["kind"] in ("CANDIDATES","WARNING_NO_MATCH"),"IMPORT_CACHE_INTEGRITY")
                    versions_by_hash = cache.setdefault(jid,{})
                    old = versions_by_hash.get(result["response_sha256"])
                    if old:
                        sources = {digest(p):p for p in old["sources"]+result["sources"]}
                        result = {**result,"sources":[sources[k] for k in sorted(sources)]}
                    versions_by_hash[result["response_sha256"]] = result
        return {jid:list(versions.values()) for jid,versions in cache.items()}

    def checkpoint(self,plan_id,value):
        from .import_service import plan_hash
        self.write("checkpoints/"+plan_hash(plan_id)+".json",
                   {"schema":"polar.import-checkpoint/1","value":value,"sha256":digest(value)},replace=True)

    def admit_storage(self,extra=512*1024**2):
        require(self.used()+extra <= self.limit,"IMPORT_STORAGE_ADMISSION")
