"""Bounded native-qitem + Gym metadata joins; never performs lifecycle actions."""
import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .history_bundle import HistoryError, read_file, safe_root, decode as metadata_decode
from .gym_contract import canonical, decode, GymError, SEMANTIC_FILES

QITEM=re.compile(r'qitem-[0-9]{14}-[a-f0-9]{8,32}')
SEAT=re.compile(r'[a-z0-9][a-z0-9._-]{0,63}@[a-z0-9][a-z0-9._-]{0,63}')
EXPERIMENT=re.compile(r'gym-[a-f0-9]{64}')
STATES={'pending','in-progress','blocked','done','failed','denied','canceled','handed-off'}
FACTS=('queue_state','owner','queue_custody','source_custody','worker_liveness',
       'checkpoint','terminal_result','semantic_result','consumer_ack','next_step')

class StateError(Exception):
    def __init__(self,code):self.code=code;super().__init__(code)

def require(ok,code):
    if not ok:raise StateError(code)

def utc(ns):
    return datetime.fromtimestamp(ns//10**9,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+f'.{ns%10**9:09d}Z'

def clock_ns(value):
    if type(value) is int and 0<value<10**20:return value
    if not isinstance(value,str) or len(value)>40:return None
    try:
        value=datetime.fromisoformat(value.replace('Z','+00:00'))
        if value.tzinfo is None:return None
        delta=value.astimezone(timezone.utc)-datetime(1970,1,1,tzinfo=timezone.utc)
        return (delta.days*86400+delta.seconds)*10**9+delta.microseconds*1000
    except (ValueError,OverflowError):return None

def native_queue(qid):
    """Only this read verb is available. Bound stdout before buffering it."""
    proc=subprocess.Popen(['rig','queue','show',qid,'--full','--json'],stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,start_new_session=True)
    selector=selectors.DefaultSelector();selector.register(proc.stdout,selectors.EVENT_READ)
    chunks=[];size=0;end=time.monotonic()+10
    try:
        while True:
            remaining=end-time.monotonic()
            require(remaining>0,'NATIVE_QUERY_TIMEOUT')
            ready=selector.select(remaining)
            require(bool(ready),'NATIVE_QUERY_TIMEOUT')
            block=os.read(proc.stdout.fileno(),4096)
            if not block:break
            size+=len(block);require(size<=256*1024,'NATIVE_QUERY_LIMIT');chunks.append(block)
        require(proc.wait(timeout=max(.01,end-time.monotonic()))==0,'NATIVE_QUERY_FAILED')
        return b''.join(chunks)
    finally:
        selector.close();proc.stdout.close()
        # Kill only this invocation's process group; includes a wrapper's surviving child.
        try:os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:proc.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            proc.wait()

class Snapshot:
    def __init__(self,root,now_ns,max_age,max_file,max_total,live_clock=False):
        self.root=safe_root(root) if root is not None else None
        self.now=now_ns;self.live_clock=live_clock;self.max_age=max_age*10**9;self.max_file=max_file;self.max_total=max_total
        self.used=0;self.reads=0;self.issues=[]
        self.policy=[{'source':'reader-policy','reference':'polar.state/1','observed_at':utc(self.observed()),'event_at':utc(self.now),'sha256':None}]
        self.facts={name:self.fact(None,self.policy,reason='NOT_APPLICABLE_OR_NOT_SELECTED') for name in FACTS}
    def observed(self):
        return time.time_ns() if self.live_clock else self.now
    def fact(self,value,evidence,*,reason=None,event=None):
        current=self.observed()
        freshness='UNKNOWN' if event is None else ('FUTURE' if event>current else 'STALE' if current-event>self.max_age else 'FRESH')
        result={'status':'UNKNOWN' if reason else 'KNOWN','value':None if reason else value,
                'reason':reason,'freshness':freshness,'evidence':evidence}
        if not reason and freshness in ('STALE','FUTURE'):
            result.update(status='UNKNOWN',value=None,reason='STALE_EVIDENCE' if freshness=='STALE' else 'FUTURE_EVIDENCE',last_recorded=value)
        return result
    def unknown(self,names,reason,evidence):
        self.issues.append(reason)
        for name in names:self.facts[name]=self.fact(None,evidence,reason=reason)
    def read(self,name):
        require(self.root is not None,'ARTIFACT_ROOT_REQUIRED')
        self.reads+=1;require(self.reads<=12,'READ_COUNT_LIMIT')
        remaining=self.max_total-self.used;require(remaining>0,'TOTAL_BYTE_LIMIT')
        try:raw=read_file(self.root,name,limit=min(self.max_file,remaining))
        except HistoryError as exc:
            code='ARTIFACT_BYTE_LIMIT' if exc.code=='HISTORY_FILE_LIMIT' else 'ARTIFACT_UNAVAILABLE_OR_UNSAFE'
            raise StateError(code) from None
        self.used+=len(raw)
        evidence={'source':'polar-artifact','reference':name,'sha256':hashlib.sha256(raw).hexdigest(),
                  'observed_at':utc(self.observed()),'event_at':None}
        return raw,evidence
    def file_set(self,name,expected):
        opened=[]
        try:
            opened.append(os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW))
            for part in name.split('/'):
                opened.append(os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=opened[-1]))
            actual=set()
            with os.scandir(opened[-1]) as entries:
                for entry in entries:
                    require(entry.name in expected and entry.is_file(follow_symlinks=False),'UNEXPECTED_ARTIFACT_FILE')
                    actual.add(entry.name)
            require(actual==expected,'MISSING_ARTIFACT_FILE')
        except OSError:raise StateError('ARTIFACT_UNAVAILABLE_OR_UNSAFE') from None
        finally:
            for fd in reversed(opened):os.close(fd)
    def record(self,aid,kind):
        path=f'gym-attempts/{aid}/{kind}/record.json'
        self.file_set(f'gym-attempts/{aid}/{kind}',{'record.json'})
        raw,evidence=self.read(path)
        try:value=decode(raw)
        except (GymError,ValueError):raise StateError('INVALID_RECORD_JSON') from None
        require(type(value) is dict and canonical(value)==raw,'INVALID_RECORD_CANONICAL')
        return value,evidence
    def queue(self,qid,fetch):
        evidence={'source':'openrig-native','reference':qid,'observed_at':utc(self.observed()),'event_at':None,'sha256':None}
        try:
            raw=fetch(qid);require(type(raw) is bytes and len(raw)<=256*1024,'NATIVE_QUERY_LIMIT')
            value=metadata_decode(raw);require(type(value) is dict and value.get('qitemId')==qid,'NATIVE_IDENTITY_MISMATCH')
            observed=self.observed();evidence['observed_at']=utc(observed)
            evidence['sha256']=hashlib.sha256(raw).hexdigest()
            state=value.get('state');require(state in STATES,'UNSUPPORTED_NATIVE_STATE')
            waiting=value.get('waiting')
            if waiting is None:waiting={}  # Optional/legacy projection, never coerce other falsey types.
            require(type(waiting) is dict,'INVALID_NATIVE_WAITING')
            require(waiting.get('obligation',qid)==qid and waiting.get('state',state)==state,'CONTRADICTORY_NATIVE_STATE')
            self.facts['queue_state']=self.fact(state,[evidence],event=observed)
            owner=value.get('destinationSession');require(type(owner) is str and SEAT.fullmatch(owner),'INVALID_NATIVE_OWNER')
            if waiting.get('owner',owner)!=owner:
                self.unknown(('owner','queue_custody'),'CONTRADICTORY_NATIVE_OWNER',[evidence])
            else:
                self.facts['owner']=self.fact(owner,[evidence],event=observed)
                self.facts['queue_custody']=self.fact({'owner':owner,'scope':'NATIVE_QITEM_ONLY'},[evidence],event=observed)
            blocker=value.get('blockedOn')
            if blocker is not None:
                safe=type(blocker) is str and (QITEM.fullmatch(blocker) or SEAT.fullmatch(blocker) or re.fullmatch(r'(?:external|fold|auth):[a-z0-9][a-z0-9._:-]{0,100}',blocker))
                require(bool(safe),'UNSUPPORTED_NATIVE_BLOCKER')
            # Blocker is native work metadata, never a worker-state inference.
            self.blocker=self.fact(blocker,[evidence],event=observed)
            self.facts['source_custody']=self.fact(None,[evidence],reason='SOURCE_WRITER_LEASE_NOT_REPRESENTED')
        except (StateError,GymError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
            reason=exc.code if isinstance(exc,StateError) else 'NATIVE_QUERY_UNAVAILABLE'
            self.unknown(('queue_state','owner','queue_custody'),reason,[evidence])
            self.blocker=self.fact(None,[evidence],reason=reason)
    def experiment(self,eid):
        evidence=[]
        try:
            raw,ref=self.read(f'gym-experiments/{eid}/manifest.json');evidence.append(ref)
            require(eid=='gym-'+hashlib.sha256(raw).hexdigest(),'SEMANTIC_MANIFEST_IDENTITY')
            manifest=decode(raw)
            self.file_set(f'gym-experiments/{eid}',set(SEMANTIC_FILES)|{'manifest.json'})
            require(type(manifest) is dict and manifest.get('schema')=='polar.gym-semantic-manifest/1' and
                    type(manifest.get('files')) is dict and set(manifest['files'])==set(SEMANTIC_FILES),'UNSUPPORTED_SEMANTIC_SCHEMA')
            require(canonical(manifest)==raw,'INVALID_MANIFEST_CANONICAL')
            for name in SEMANTIC_FILES:
                info=manifest['files'][name]
                require(type(info) is dict and type(info.get('bytes')) is int and 0<=info['bytes']<=self.max_file and
                        type(info.get('sha256')) is str and re.fullmatch(r'[a-f0-9]{64}',info['sha256']),'INVALID_MEMBER_REFERENCE')
                member,mref=self.read(f'gym-experiments/{eid}/{name}');evidence.append(mref)
                require(len(member)==info['bytes'] and mref['sha256']==info['sha256'],'SEMANTIC_MEMBER_HASH')
                # Content bytes are checked, never decoded or emitted by the reader.
            self.facts['semantic_result']=self.fact({'experiment_id':eid,'verified_members':len(SEMANTIC_FILES)},evidence,event=self.observed())
            return True
        except (StateError,GymError,ValueError,KeyError,TypeError) as exc:
            reason=exc.code if isinstance(exc,StateError) else 'INVALID_SEMANTIC_RECORD'
            self.unknown(('semantic_result',),reason,evidence or [{'source':'polar-artifact','reference':f'gym-experiments/{eid}/manifest.json','observed_at':utc(self.observed()),'sha256':None,'event_at':None}])
            return False
    def attempt(self,aid,explicit_experiment):
        expected={'source':'polar-artifact','reference':f'gym-attempts/{aid}/start/record.json','observed_at':utc(self.observed()),'sha256':None,'event_at':None}
        evidence=[]
        try:
            start,sref=self.record(aid,'start');evidence.append(sref)
            require(start.get('schema')=='polar.gym-attempt-start/1' and start.get('attempt_id')==aid and start.get('status')=='UNFINALIZED','ATTEMPT_IDENTITY_OR_SCHEMA')
            began=clock_ns(start.get('started_ns'));require(began is not None,'MISSING_START_CLOCK')
            sref['event_at']=utc(began)
            self.facts['worker_liveness']=self.fact(None,evidence,reason='NO_SUPPORTED_WORKER_HEARTBEAT',event=began)
            self.facts['checkpoint']=self.fact(None,evidence,reason='NO_SUPPORTED_PROGRESS_CHECKPOINT',event=began)
            self.facts['consumer_ack']=self.fact(None,evidence,reason='NO_SUPPORTED_GYM_CONSUMER_RECEIPT',event=began)
            finishpath=f'gym-attempts/{aid}/finish/record.json'
            try:finish,fref=self.record(aid,'finish')
            except StateError as exc:
                # Absence/corruption are unknown, never infer a live worker from the start/PID.
                missing={'source':'polar-artifact','reference':finishpath,'observed_at':utc(self.observed()),'event_at':None,'sha256':None}
                self.facts['terminal_result']=self.fact(None,evidence+[missing],reason='NO_VERIFIED_TERMINAL_RECORD',event=began)
                self.issues.append('NO_VERIFIED_TERMINAL_RECORD')
                if explicit_experiment:self.experiment(explicit_experiment)
                return
            evidence.append(fref)
            require(finish.get('schema')=='polar.gym-attempt-finish/1' and finish.get('status') in ('SUCCESS','FAILED'),'UNSUPPORTED_TERMINAL_SCHEMA')
            ended=clock_ns(finish.get('finished_ns'));require(ended is not None,'MISSING_TERMINAL_CLOCK');fref['event_at']=utc(ended)
            require(ended>=began,'CONTRADICTORY_ATTEMPT_CLOCKS')
            status=finish['status'];eid=finish.get('experiment_id')
            if status=='SUCCESS':
                require(type(eid) is str and EXPERIMENT.fullmatch(eid),'INVALID_RESULT_REFERENCE')
                require(explicit_experiment is None or explicit_experiment==eid,'CONTRADICTORY_RESULT_REFERENCE')
                if not self.experiment(eid):
                    self.unknown(('terminal_result',),'NO_VERIFIED_SUCCESS_RESULT',evidence);return
            elif explicit_experiment:
                self.unknown(('terminal_result','semantic_result'),'CONTRADICTORY_RESULT_REFERENCE',evidence);return
            self.facts['terminal_result']=self.fact(status,evidence,event=ended)
        except (StateError,GymError,ValueError,KeyError,TypeError) as exc:
            reason=exc.code if isinstance(exc,StateError) else 'INVALID_ATTEMPT_RECORD'
            self.unknown(('terminal_result','semantic_result'),reason,evidence or [expected])
    def result(self):
        if any('CONTRADICTORY' in issue for issue in self.issues):step='RECONCILE_CONTRADICTORY_EVIDENCE_WITH_OWNER'
        elif self.facts['terminal_result']['status']=='KNOWN':step='CHECK_CONSUMER_ACKNOWLEDGMENT_WITH_OWNER'
        elif self.facts['queue_state']['value']=='blocked':step='FOLLOW_EXISTING_NATIVE_BLOCKER'
        else:step='OBTAIN_MISSING_OR_FRESH_OWNER_EVIDENCE'
        refs=[{'source':'reader-policy','reference':'polar.state/1','observed_at':utc(self.observed()),'event_at':utc(self.now),'sha256':None}]
        self.facts['next_step']=self.fact(step,refs,event=self.observed())
        # Unsupported facts remain explicitly present; UNKNOWN is not a failure/incident diagnosis.
        return {'schema':'polar.state/1','query_started_at':utc(self.now),'observed_at':utc(self.observed()),'facts':self.facts,
                'blocker':getattr(self,'blocker',self.fact(None,self.policy,reason='QITEM_NOT_SELECTED')),
                'limits':{'files_read':self.reads,'bytes_read':self.used,'max_file_bytes':self.max_file,'max_total_bytes':self.max_total},
                'actions_performed':[],'worker_liveness_inferred':False}

def read_state(*,root=None,qitem=None,attempt=None,experiment=None,max_age_seconds=300,
               max_file_bytes=1024**2,max_total_bytes=8*1024**2,now_ns=None,queue_reader=None):
    require(qitem is not None or attempt is not None or experiment is not None,'SELECTOR_REQUIRED')
    require(qitem is None or type(qitem) is str and QITEM.fullmatch(qitem),'INVALID_QITEM_ID')
    if attempt is not None:
        try:require(str(uuid.UUID(attempt))==attempt,'INVALID_ATTEMPT_ID')
        except (ValueError,TypeError,AttributeError):raise StateError('INVALID_ATTEMPT_ID') from None
    require(experiment is None or type(experiment) is str and EXPERIMENT.fullmatch(experiment),'INVALID_EXPERIMENT_ID')
    require(type(max_age_seconds) is int and 1<=max_age_seconds<=86400 and type(max_file_bytes) is int and
            1<=max_file_bytes<=4*1024**2 and type(max_total_bytes) is int and 1<=max_total_bytes<=16*1024**2,'INVALID_LIMIT')
    require(root is not None or attempt is None and experiment is None,'ARTIFACT_ROOT_REQUIRED')
    snap=Snapshot(root,time.time_ns() if now_ns is None else now_ns,max_age_seconds,max_file_bytes,max_total_bytes,live_clock=now_ns is None)
    if qitem:snap.queue(qitem,native_queue if queue_reader is None else queue_reader)
    if attempt:snap.attempt(attempt,experiment)
    elif experiment:snap.experiment(experiment)
    value=snap.result();require(len(canonical(value))<=64*1024,'OUTPUT_LIMIT');return value
