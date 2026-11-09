"""OBS158 immutable experiments/attempts reuse HistoryStore publication, never agent tasks."""
import re
import time
import uuid
from .gym_store import GymStore
from .history_bundle import read_file
from .obs158_contract import FILES,MAX_BYTES,PROTOCOL,canonical,decode,sha
from .obs158_math import require


class Obs158Store(GymStore):
    def record(self,parent,name,value):
        raw=canonical(value);require(len(raw)<=MAX_BYTES,'OBS158_FILE_BOUND')
        self._publish(parent,name,{'record.json':raw},file_limit=MAX_BYTES)
    def read_record(self,parent,name):
        raw=read_file(self.root,f'{parent}/{name}/record.json',MAX_BYTES)
        require({p.name for p in (self.root/parent/name).iterdir()}=={'record.json'},'RECORD_FILE_SET')
        value=decode(raw);require(canonical(value)==raw,'NONCANONICAL_RECORD')
        return value
    def begin_packet(self,namespace,bindings,authorization,replay_of):
        require(namespace in ('RETAINED','INVENTED'),'SOURCE_CLASS')
        aid=str(uuid.uuid4())
        family=PROTOCOL if namespace=='RETAINED' else authorization['family']
        require(type(family) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',family),
                'INVALID_BUDGET_FAMILY')
        maximum=authorization['max_full_packet_starts']
        require(type(maximum) is int and 1<=maximum<=2
                and (namespace!='RETAINED' or maximum==2),'INVALID_PACKET_BUDGET')
        with self.locked():
            parent=f'obs158-budgets/{namespace}/{family}';directory=self.root/parent
            existing=sorted(directory.iterdir()) if directory.exists() else []
            require(len(existing)<maximum,'OBS158_PACKET_BUDGET_EXHAUSTED')
            if replay_of is not None:
                require(bool(existing),'REPLAY_REQUIRES_PRIOR_PACKET')
                prior=self.packet(self.read_record(parent,existing[-1].name)['attempt_id'])
                require(prior['status']=='SUCCESS' and prior['start']['bindings']==bindings
                        and prior['finish']['experiment_id']==replay_of,'REPLAY_BINDING_MISMATCH')
            elif namespace=='RETAINED':require(not existing,'RETAINED_SECOND_START_REPLAY_ONLY')
            row={'schema':'polar.obs158-attempt-start/1','attempt_id':aid,'namespace':namespace,
                 'family':family,'ordinal':len(existing),'bindings':bindings,
                 'replay_of':replay_of,'started_ns':time.time_ns(),'status':'UNFINALIZED'}
            # Debit before all data-preflight/native work; failures never refund.
            self.record(parent,f'{len(existing):03d}-{aid}',row)
            self.record('obs158-attempts/'+aid,'start',row)
        return row
    def finish_packet(self,aid,value):
        self.validate_attempt(aid)
        with self.locked():self.record('obs158-attempts/'+aid,'finish',value)
    def packet(self,aid):
        self.validate_attempt(aid);parent='obs158-attempts/'+aid
        start=self.read_record(parent,'start');finish_path=self.root/parent/'finish'
        require(not finish_path.is_symlink(),'UNSAFE_RECORD')
        finish=self.read_record(parent,'finish') if finish_path.exists() else None
        return {'schema':'polar.obs158-attempt/1','attempt_id':aid,'start':start,'finish':finish,
                'status':finish['status'] if finish else 'UNFINALIZED'}
    def publish_packet(self,files,bindings):
        require(set(files)==set(FILES),'OBS158_SEMANTIC_FILE_SET')
        raws={name:canonical(files[name]) for name in FILES}
        require(all(len(v)<=MAX_BYTES for v in raws.values()),'OBS158_FILE_BOUND')
        manifest={'schema':'polar.obs158-semantic-manifest/1','bindings':bindings,
                  'files':{name:{'sha256':sha(raws[name]),'bytes':len(raws[name])} for name in FILES}}
        raw=canonical(manifest);identity='obs158-'+sha(raw);raws['manifest.json']=raw
        with self.locked():self._publish('obs158-experiments',identity,raws,file_limit=MAX_BYTES)
        return identity
    def report_packet(self,identity):
        require(type(identity) is str and re.fullmatch(r'obs158-[a-f0-9]{64}',identity),
                'INVALID_OBS158_EXPERIMENT_ID')
        parent='obs158-experiments/'+identity;directory=self.root/parent
        require(not directory.is_symlink() and directory.is_dir()
                and {p.name for p in directory.iterdir()}==set(FILES)|{'manifest.json'},
                'OBS158_SEMANTIC_FILE_SET')
        raw=read_file(self.root,parent+'/manifest.json',MAX_BYTES)
        require(identity=='obs158-'+sha(raw),'OBS158_MANIFEST_HASH')
        manifest=decode(raw)
        require(set(manifest)=={'schema','bindings','files'}
                and manifest['schema']=='polar.obs158-semantic-manifest/1'
                and set(manifest['files'])==set(FILES),'OBS158_SEMANTIC_FILE_SET')
        files={}
        for name in FILES:
            content=read_file(self.root,parent+'/'+name,MAX_BYTES);expected=manifest['files'][name]
            require(len(content)==expected['bytes'] and sha(content)==expected['sha256'],
                    'OBS158_SEMANTIC_FILE_HASH')
            value=decode(content);require(canonical(value)==content,'NONCANONICAL_OBS158_FILE')
            files[name]=value
        require(canonical(manifest)==raw,'NONCANONICAL_OBS158_MANIFEST')
        return {'schema':'polar.obs158-report/1','experiment_id':identity,
                'manifest':manifest,'files':files}
