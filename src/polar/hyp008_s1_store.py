"""S1 immutable storage and trusted deployment-bound scientific accounting.

No authorize/reset API. Trusted deployment is provided by the host Service,
never decoded from experiment configuration or an arbitrary CLI root.
"""
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
import uuid

from .history_store import HistoryStore
from .history_bundle import read_file,safe_root
from .hyp008_s1_contract import (canonical,sha,ref,decode,require,validate,identified,
    FAMILY,STAGES,SEMANTIC,COMMON,GRANT,MAX_FILE)


def now():return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Deployment:
    root: Path
    binding: dict
    root_identity: tuple
    authority_directory: Path
    host_identity: tuple | None = None
    preparation_path: Path | None = None

    def mount(self):
        """Join the qualified launcher host identity, never host/container inodes."""
        require(self.preparation_path==Path('/polar-launch/preparation.json'),'AUTOMATIC_PREPARATION_PATH')
        p=decode(read_file(safe_root(self.preparation_path.parent),self.preparation_path.name,limit=2*1024**2))
        require(p['preparation']=='PREPARED' and p['scenario_started'] is False,'STORE_MOUNT_NOT_PREPARED')
        retained=p['retained_binding'];artifact=retained['artifact_root'];observed=retained['observation']
        require(str(self.root)=='/polar-artifacts' and artifact['container_target']==str(self.root)
            and artifact['path']==self.binding['canonical_root'] and artifact['writable'] is True
            and (artifact['device'],artifact['inode'])==tuple(str(v) for v in self.host_identity),
            'TRUSTED_HOST_ROOT_IDENTITY')
        require(observed['schema']=='polar.observed-retained-mounts/1' and observed['all_mounts_exact'] is True
            and observed['container_id']==p['observed']['container_id'],'STORE_MOUNT_OBSERVATION')
        mounts=[m for m in observed['mounts'] if m['target']==str(self.root)]
        require(mounts==[{'source':self.binding['canonical_root'],'target':str(self.root),
            'writable':True,'type':'bind'}],'STORE_MOUNT_IDENTITY')

    def verify(self):
        validate('StoreBinding',self.binding)
        root=safe_root(self.root);require(root.is_absolute() and root.resolve()==root,'TRUSTED_ROOT')
        info=root.stat();require((info.st_dev,info.st_ino)==self.root_identity,'TRUSTED_ROOT_IDENTITY')
        require(type(self.root_identity) is tuple and len(self.root_identity)==2,'TRUSTED_ROOT_IDENTITY')
        if self.host_identity is not None:self.mount()
        else:require(self.preparation_path is None,'UNBOUND_STORE_MOUNT')
        authorities=safe_root(self.authority_directory)
        require(authorities!=root and root not in authorities.parents,'AUTHORITY_OUTSIDE_CALLER_STORE')
        return root

    @property
    def binding_id(self):return sha(canonical(self.binding))

    @property
    def profile_ref(self):
        return ref(canonical({'binding':self.binding,'runtime_root':str(self.root),
            'root_identity':list(self.host_identity if self.host_identity is not None else self.root_identity),
            'identity_namespace':'HOST_MOUNT' if self.host_identity is not None else 'LOCAL',
            'authority_directory':str(self.authority_directory)}))


class S1Store(HistoryStore):
    def __init__(self,deployment,limit):
        require(type(deployment) is Deployment,'TRUSTED_DEPLOYMENT_REQUIRED')
        self.deployment=deployment
        super().__init__(deployment.verify(),limit)

    def trusted(self):
        require(self.root==self.deployment.verify(),'TRUSTED_ROOT_CHANGED')
        return self.deployment.binding

    def object(self,value):
        return self.raw_object(canonical(value))

    def raw_object(self,raw):
        require(type(raw) is bytes and len(raw)<=MAX_FILE,'OBJECT_BOUND')
        pin=ref(raw)
        with self.locked():
            self.trusted();self._publish('s1-objects',pin['sha256'],{'record.json':raw},file_limit=MAX_FILE)
        return pin

    def raw_get(self,pin):
        validate('Ref',pin);self.trusted()
        raw=read_file(self.root,'s1-objects/'+pin['sha256']+'/record.json',limit=MAX_FILE)
        require(ref(raw)==pin,'OBJECT_HASH');return raw

    def get(self,pin):
        raw=self.raw_get(pin);value=decode(raw)
        require(canonical(value)==raw,'OBJECT_CANONICAL');return value

    def _record(self,parent,name,value):
        self._publish(parent,name,{'record.json':canonical(value)},file_limit=MAX_FILE)

    def _read(self,parent,name):
        raw=read_file(self.root,parent+'/'+name+'/record.json',limit=MAX_FILE)
        value=decode(raw);require(canonical(value)==raw,'RECORD_CANONICAL')
        directory=self.root/parent/name
        require({p.name for p in directory.iterdir()}=={'record.json'},'RECORD_MEMBERS')
        return value

    def authority(self,seal):
        validate('Seal',seal);identified(seal,'seal_id');self.trusted()
        path=self.deployment.authority_directory/(seal['seal_id']+'.json')
        if not path.exists():return None
        raw=read_file(safe_root(self.deployment.authority_directory),path.name,limit=65536)
        authority=decode(raw);validate('Authority',authority)
        registration=self.get(seal['registration_ref']);validate('Registration',registration)
        require(authority=={'schema':'polar.hyp008-s1-authority/1','seal_id':seal['seal_id'],
            'registration_id':sha(canonical(registration)),'store_binding_id':self.deployment.binding_id,
            'family_key':FAMILY,'execution_assignment_ref':seal['execution_assignment_ref'],'grant':GRANT},
            'AUTHORITY_BINDING')
        require(seal['store_binding_ref']==ref(canonical(self.deployment.binding)),'STORE_BINDING_REF')
        return authority

    def family(self):return 's1-families/'+FAMILY

    def begin(self,seal):
        """Irreversible family first. A crash before the attempt link still debits."""
        require(self.authority(seal) is not None,'EXECUTION_NOT_AUTHORIZED')
        seal_ref=self.object(seal)
        aid=str(uuid.uuid4())
        with self.locked():
            self.trusted();require(self.authority(seal) is not None,'EXECUTION_NOT_AUTHORIZED')
            family=self.root/self.family()
            require(not family.exists() and not family.is_symlink(),'FAMILY_ALREADY_STARTED')
            start={'schema':'polar.hyp008-s1-family-start/1','attempt_id':aid,'family_key':FAMILY,
                'seal_id':seal['seal_id'],'seal_ref':seal_ref,'store_binding_id':self.deployment.binding_id,
                'started_at':now(),'scientific_family_charged':True}
            self._record(self.family(),'start',start)
            self._record('s1-attempts/'+aid,'start',start)
        return aid

    def _active(self,aid):
        require(type(aid) is str and str(uuid.UUID(aid))==aid,'ATTEMPT_ID')
        start=self._read(self.family(),'start')
        require(start['attempt_id']==aid and start['store_binding_id']==self.deployment.binding_id,'FAMILY_ATTEMPT')
        require(not (self.root/'s1-attempts'/aid/'finish').exists(),'ATTEMPT_FINISHED')
        return start

    def stage_intent(self,aid,stage):
        require(stage in STAGES,'STAGE_NAME')
        with self.locked():
            self.trusted();active=self._active(aid)
            require(self.authority(self.get(active['seal_ref'])) is not None,'EXECUTION_NOT_AUTHORIZED')
            ordinal=STAGES.index(stage)
            for prior in STAGES[:ordinal]:
                done=self._read(self.family()+'/stages/'+prior,'completed')
                require(done['actual_native_call_state']=='COMPLETED','PREVIOUS_STAGE_NOT_COMPLETE')
            parent=self.family()+'/stages/'+stage
            require(not (self.root/parent).exists(),'STAGE_ALREADY_CHARGED')
            value={'schema':'polar.hyp008-s1-native-call-evidence/1','stage':stage,'stage_intent_at':now(),
                'scientific_stage_attempt_charged':True,'actual_native_call_state':'UNKNOWN',
                'evidence_ref':None,'actual_time':None}
            validate('NativeCallEvidence',value);self._record(parent,'intent',value)
            return value

    def witness(self,aid,stage,state,evidence):
        require(stage in STAGES and state in ('CALL_BOUNDARY_OBSERVED','COMPLETED','NOT_REACHED'),'NATIVE_WITNESS')
        pin=self.object(evidence)
        with self.locked():
            self.trusted();self._active(aid);parent=self.family()+'/stages/'+stage
            intent=self._read(parent,'intent')
            name={'CALL_BOUNDARY_OBSERVED':'boundary','COMPLETED':'completed','NOT_REACHED':'not-reached'}[state]
            require(not (self.root/parent/name).exists(),'DUPLICATE_WITNESS')
            if state=='COMPLETED':self._read(parent,'boundary')
            if state=='NOT_REACHED':require(not (self.root/parent/'boundary').exists(),'CALL_ALREADY_REACHED')
            value={**intent,'actual_native_call_state':state,'evidence_ref':pin,'actual_time':now()}
            validate('NativeCallEvidence',value);self._record(parent,name,value)
            return value

    def stages(self,aid):
        self.trusted();start=self._read('s1-attempts/'+aid,'start')
        require(start['attempt_id']==aid,'ATTEMPT_IDENTITY');result={}
        for stage in STAGES:
            parent=self.root/self.family()/'stages'/stage
            result[stage]={}
            for name in ('intent','boundary','completed','not-reached'):
                if (parent/name).exists():result[stage][name]=self._read(self.family()+'/stages/'+stage,name)
        return result

    def finish(self,aid,status,reason,manifest_ref=None,runtime_ref=None,cleanup_ref=None):
        with self.locked():
            self.trusted();start=self._active(aid)
            value={'schema':'polar.hyp008-s1-attempt/1','attempt_id':aid,'seal_id':start['seal_id'],
                'store_binding_id':self.deployment.binding_id,'family_key':FAMILY,
                'start_ref':ref(canonical(start)),'stage_records':self.stages(aid),
                'terminal_status':status,'reason':reason,'manifest_ref':manifest_ref,
                'resources':{'finished_at':now()},'runtime_ref':runtime_ref,'cleanup_ref':cleanup_ref}
            self._record('s1-attempts/'+aid,'finish',value)
            return value

    def attempt(self,aid):
        self.trusted();require(type(aid) is str and str(uuid.UUID(aid))==aid,'ATTEMPT_ID')
        start=self._read('s1-attempts/'+aid,'start')
        parent=self.root/'s1-attempts'/aid
        if (parent/'finish').exists():return self._read('s1-attempts/'+aid,'finish')
        return {'schema':'polar.hyp008-s1-unfinalized/1','start':start,'terminal_status':'UNFINALIZED',
                'stages':self.stages(aid),'resumption_allowed':False}

    @staticmethod
    def _components(files,family):
        require(set(family['components'])==set(SEMANTIC)-COMMON,'COMPONENT_NAMES')
        for name,component in family['components'].items():
            if name in files:
                require(component['status']=='PRODUCED' and component['ref']==ref(files[name]),'COMPONENT_REF')
            else:
                require(component['ref'] is None and component['status'] in
                        ('NOT_RUN','UNAVAILABLE','ARTIFACT_NOT_RETURNED'),'COMPONENT_ABSENCE')
        if family['status']=='COMPLETE':
            require(family['component_status']=='COMPLETE' and set(files)==set(SEMANTIC),'COMPLETE_FILE_SET')
        if family['status']=='NOT_STARTED':
            require(set(files)==COMMON and all(v=='NOT_RUN' for v in family['stages'].values()),'NO_ISSUE_FILES')

    def publish(self,files):
        require(type(files) is dict and COMMON<=set(files)<=set(SEMANTIC),'SEMANTIC_FILE_SET')
        family=decode(files['family.json']);validate('Family',family)
        self._components(files,family)
        if family['status']=='COMPLETE':require(set(files)==set(SEMANTIC),'COMPLETE_FILE_SET')
        for name,raw in files.items():
            require(type(raw) is bytes and len(raw)<=MAX_FILE and canonical(decode(raw))==raw,'SEMANTIC_CANONICAL')
        core={'schema':'polar.hyp008-s1-manifest/1','files':{n:ref(raw) for n,raw in sorted(files.items())}}
        eid='s1-'+sha(canonical(core));manifest={**core,'experiment_id':eid};validate('Manifest',manifest)
        with self.locked():
            self.trusted();self._publish('s1-experiments',eid,{**files,'manifest.json':canonical(manifest)},file_limit=MAX_FILE)
        return manifest

    def report(self,eid):
        self.trusted();require(type(eid) is str and __import__('re').fullmatch('s1-[a-f0-9]{64}',eid),'EXPERIMENT_ID')
        parent='s1-experiments/'+eid;raw=read_file(self.root,parent+'/manifest.json',limit=MAX_FILE)
        manifest=decode(raw);validate('Manifest',manifest)
        core={k:v for k,v in manifest.items() if k!='experiment_id'}
        require(canonical(manifest)==raw and 's1-'+sha(canonical(core))==eid==manifest['experiment_id'],'MANIFEST_IDENTITY')
        require({p.name for p in (self.root/parent).iterdir()}==set(manifest['files'])|{'manifest.json'},'EXPERIMENT_MEMBERS')
        files={}
        for name,expected in manifest['files'].items():
            raw=read_file(self.root,parent+'/'+name,limit=MAX_FILE)
            require(ref(raw)==expected and canonical(decode(raw))==raw,'SEMANTIC_HASH')
            files[name]=decode(raw)
        validate('Family',files['family.json']);self._components({n:canonical(v) for n,v in files.items()},files['family.json'])
        require(files['family.json']['status']!='COMPLETE' or set(files)==set(SEMANTIC),'COMPLETE_FILE_SET')
        return {'manifest':manifest,'files':files}
