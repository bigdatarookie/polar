"""Service-owned fixed-family irreversible records. No implicit root/counter reset."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import time
import uuid

from .history_bundle import read_file, safe_root
from .history_store import HistoryStore, fsync_directory
from .capability_contract import (CapabilityError, require, exact, canonical, decode, digest, sha,
                                 MAX_BYTES, PROFILE_ID, ACCOUNTS, FILES, validate, REASONS)

DEFAULT_ANCHOR = Path('/var/lib/polar/hyp007-capability-registry')


def descriptor(root):
    root=safe_root(Path(root))
    st=root.stat()
    return {'path':str(root),'device':str(st.st_dev),'inode':str(st.st_ino)}


def immutable(path,value):
    path=Path(path);raw=canonical(value)
    require(len(raw)<=MAX_BYTES,'SCHEMA_INVALID')
    require(path.parent.is_dir() and path.parent==path.parent.resolve(),'FAMILY_ROOT_MISMATCH')
    temp=path.parent/('.partial-'+str(uuid.uuid4()))
    try:
        with temp.open('xb') as out:
            out.write(raw);out.flush();os.fsync(out.fileno())
        temp.chmod(0o400)
        os.link(temp,path,follow_symlinks=False);fsync_directory(path.parent)
    finally:
        if temp.exists():temp.unlink()
    return {'path':str(path),'sha256':sha(raw),'bytes':len(raw)}


def record(path):
    path=Path(path)
    raw=read_file(safe_root(path.parent),path.name,MAX_BYTES)
    value=decode(raw)
    require(canonical(value)==raw,'INPUT_INTEGRITY')
    return value


def _replace(path,value):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(),'FAMILY_ROOT_MISMATCH')
    temp=path.parent/('.partial-'+str(uuid.uuid4()))
    try:
        with temp.open('xb') as out:
            out.write(canonical(value));out.flush();os.fsync(out.fileno())
        temp.chmod(0o400);os.replace(temp,path);fsync_directory(path.parent)
    finally:
        if temp.exists():temp.unlink()


def attempt_id(value):
    try:parsed=uuid.UUID(value)
    except (TypeError,ValueError,AttributeError):raise CapabilityError('BINDING_MISMATCH') from None
    require(str(parsed)==value and parsed.version==4,'BINDING_MISMATCH')
    return value


class FamilyStore:
    """Anchor is provisioned separately; public Service never chooses its path."""
    def __init__(self,artifact_root,anchor=DEFAULT_ANCHOR,*,technical=False,case_id=None):
        self.root=Path(artifact_root)
        self.anchor=Path(anchor)
        self.technical=technical
        require(type(technical) is bool and (case_id is None if not technical else
                type(case_id) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',case_id)),'UNBOUND_EXECUTION_AUTHORIZATION')
        self.key=PROFILE_ID if not technical else 'technical-'+case_id
        self.directory=self.anchor/'families'/self.key

    def anchor_check(self):
        root=safe_root(self.anchor)
        require(root==self.anchor and not self.anchor.is_relative_to(self.root)
                and root.stat().st_mode&0o077==0,'FAMILY_ROOT_MISMATCH')
        marker=record(root/'anchor.json')
        exact(marker,('schema','descriptor'),'FAMILY_ROOT_MISMATCH')
        require(marker['schema']=='polar.capability-anchor/1' and marker['descriptor']==descriptor(root),'FAMILY_ROOT_MISMATCH')
        return root

    @contextmanager
    def locked(self):
        root=self.anchor_check()
        fd=os.open(root/'family.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise CapabilityError('FAMILY_ALREADY_FAILED') from None
            yield
        finally:os.close(fd)

    def authorization(self,config):
        ref=config['execution_authorization']
        exact(ref,('assignment_id','sha256'),'UNBOUND_EXECUTION_AUTHORIZATION')
        require(type(ref['assignment_id']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ref['assignment_id']),'UNBOUND_EXECUTION_AUTHORIZATION')
        path=self.anchor/'assignments'/(ref['assignment_id']+'.json')
        value=record(path)
        require(sha(canonical(value))==ref['sha256'],'UNBOUND_EXECUTION_AUTHORIZATION')
        exact(value,('schema','family_id','mode','bindings','qa_refs','granted_at_ns',
                     'input_classification','approved_input_hashes'),'UNBOUND_EXECUTION_AUTHORIZATION')
        require(value['schema']=='polar.capability-execution-assignment/1' and value['family_id']==PROFILE_ID
                and value['mode']==config['mode'] and type(value['qa_refs']) is list and value['qa_refs'],
                'UNBOUND_EXECUTION_AUTHORIZATION')
        require(value['bindings']=={k:v for k,v in config.items() if k!='execution_authorization'},'BINDING_MISMATCH')
        require(self.technical==(config['mode']=='TECHNICAL_FIXTURE'),'UNBOUND_EXECUTION_AUTHORIZATION')
        from .capability_inputs import read_ref
        require(value['input_classification']==('INVENTED' if self.technical else 'RETAINED'),
                'UNBOUND_EXECUTION_AUTHORIZATION')
        for ref in value['qa_refs']:read_ref(ref)
        require(config['launch']['review_ref'] in value['qa_refs'],'UNBOUND_EXECUTION_AUTHORIZATION')
        inputs=list(config['input_refs'].values())+config['auxiliary_refs']
        require(type(value['approved_input_hashes']) is list and
                sorted(value['approved_input_hashes'])==sorted(r['sha256'] for r in inputs),
                'UNBOUND_EXECUTION_AUTHORIZATION')
        if self.technical:
            require(config['technical_case']==self.key[len('technical-'):],'BINDING_MISMATCH')
        return value

    def qualification(self,kind,payload):
        """Preserve legacy technical charge history; v0.27 removes its quotas."""
        if not self.technical:
            return
        directory=self.anchor/'qualification'
        header=record(directory/'header.json')
        exact(header,('schema','family_id','authorization_sha256','ceilings'),'UNBOUND_EXECUTION_AUTHORIZATION')
        require(header['schema']=='polar.capability-qualification/1'
                and header['family_id']==PROFILE_ID
                and header['ceilings']=={'starts':6,'accounts':20,'cpu_us':600000000,
                                        'wall_ns':900000000000,'native_wall_ns':300000000000},
                'UNBOUND_EXECUTION_AUTHORIZATION')
        files=sorted(directory.glob('charge-*.json'))
        require(len(files)<=10000,'FAMILY_ROOT_MISMATCH')
        rows=[];tail=digest(header);prefix={0:tail}
        projection=record(directory/'projection.json')
        require(type(projection.get('count')) is int and 0<=projection['count']<=len(files),
                'FAMILY_ROOT_MISMATCH')
        for i,path in enumerate(files):
            require(path.name==f'charge-{i:06d}.json','FAMILY_ROOT_MISMATCH')
            row=record(path)
            require(row['sequence']==i and row['previous']==tail,'FAMILY_ROOT_MISMATCH')
            rows.append(row);tail=digest(row);prefix[i+1]=tail
        require(prefix[projection['count']]==projection.get('tail'),'FAMILY_ROOT_MISMATCH')
        # Global-before-family crash windows remain spent and cannot silently retry.
        if kind in ('START','ACCOUNT'):
            family_rows,_=self.records()
            key=lambda p:p['attempt_id'] if kind=='START' else (p['attempt_id'],p['packet_ordinal'])
            committed=[key(r['payload']) for r in rows if r['case']==self.key and r['kind']==kind]
            local=[key(r['payload']) for r in family_rows if r['kind']==kind]
            require(committed==local,'FAMILY_ALREADY_FAILED')
        candidate={'sequence':len(rows),'previous':tail,'kind':kind,'payload':payload,'case':self.key}
        all_rows=rows+[candidate]
        latest={}
        for row in all_rows:
            if row['kind']=='RESOURCE':
                p=row['payload'];key=(row['case'],p['attempt_id'])
                prior=latest.get(key,{'cpu_us':0,'wall_ns':0,'native_wall_ns':0})
                require(all(type(p[k]) is int and p[k]>=prior[k]
                            for k in ('cpu_us','wall_ns','native_wall_ns')),'FAMILY_ROOT_MISMATCH')
                latest[key]=p
        immutable(directory/f'charge-{len(rows):06d}.json',candidate)
        _replace(directory/'projection.json',{'count':len(rows)+1,'tail':digest(candidate)})

    def provision(self,config):
        """Explicit separately authorized administrative metadata operation, never prepare."""
        with self.locked():
            authority=self.authorization(config)
            # The immutable registration tombstone lives outside family storage.
            # Losing a family/header can never turn its budget into a fresh family.
            slot=self.anchor/(self.key+'.registration.json')
            require(not slot.exists() and not slot.is_symlink()
                    and not self.directory.exists(),'FAMILY_ROOT_MISMATCH')
            registration={'schema':'polar.capability-registration/1','family_key':self.key,
                'root_binding':descriptor(self.root),'configuration_sha256':digest(config)}
            immutable(slot,registration)  # A failed publication also consumes this registration.
            header={'schema':'polar.capability-family/1','family_id':PROFILE_ID,'mode':config['mode'],
                    'configuration_sha256':digest(config),'root_binding':descriptor(self.root),
                    'authorization_ref':config['execution_authorization'],'created_at_ns':authority['granted_at_ns'],
                    'expected_image_id':config['expected_image_id'],
                    'protocol_bundle':config['protocol_refs'],
                    'ceilings':{'starts':2,'accounts':14,'accounts_per_packet':7,'fits':0,
                                'cpu_us':600000000,'wall_ns':900000000000,'native_wall_ns':300000000000}}
            # Atomic directory publication: missing/corrupt existing family is never initialized.
            HistoryStore(self.anchor,64*1024**3)._publish('families',self.key,
                {'header.json':canonical(header),'projection.json':canonical({'count':0,'tail':digest(header)})},
                file_limit=MAX_BYTES)
            self.header(config)
            return header

    def header(self,config=None):
        self.anchor_check()
        require(self.directory.is_dir() and not self.directory.is_symlink(),'FAMILY_ROOT_MISMATCH')
        registration=record(self.anchor/(self.key+'.registration.json'))
        exact(registration,('schema','family_key','root_binding','configuration_sha256'),'FAMILY_ROOT_MISMATCH')
        require(registration['schema']=='polar.capability-registration/1'
                and registration['family_key']==self.key,'FAMILY_ROOT_MISMATCH')
        header=record(self.directory/'header.json')
        require(registration['root_binding']==header['root_binding']
                and registration['configuration_sha256']==header['configuration_sha256'],'FAMILY_ROOT_MISMATCH')
        exact(header,('schema','family_id','mode','configuration_sha256','root_binding','authorization_ref',
                      'created_at_ns','expected_image_id','protocol_bundle','ceilings'),'FAMILY_ROOT_MISMATCH')
        require(header['schema']=='polar.capability-family/1' and header['family_id']==PROFILE_ID
                and header['root_binding']==descriptor(self.root),'FAMILY_ROOT_MISMATCH')
        if config is not None:
            require(header['configuration_sha256']==digest(config),'BINDING_MISMATCH')
            self.authorization(config)
        return header

    def records(self):
        header=self.header()
        projection=record(self.directory/'projection.json')
        exact(projection,('count','tail'),'FAMILY_ROOT_MISMATCH')
        names=sorted(p for p in self.directory.iterdir() if p.name.startswith('journal-'))
        require(len(names)<=10000 and type(projection['count']) is int and 0<=projection['count']<=len(names),'FAMILY_ROOT_MISMATCH')
        rows=[];tail=digest(header)
        prefix={0:tail}
        for i,path in enumerate(names):
            require(not path.is_symlink() and path.name==f'journal-{i:06d}.json','FAMILY_ROOT_MISMATCH')
            row=record(path)
            exact(row,('schema','sequence','previous','kind','payload','at_ns'),'FAMILY_ROOT_MISMATCH')
            require(row['schema']=='polar.capability-journal/1' and type(row['sequence']) is int
                    and row['sequence']==i and row['previous']==tail
                    and row['kind'] in ('START','ACCOUNT','RESOURCE','RUNTIME','FINISH'),'FAMILY_ROOT_MISMATCH')
            tail=digest(row);rows.append(row);prefix[i+1]=tail
        require(prefix[projection['count']]==projection['tail'],'FAMILY_ROOT_MISMATCH')
        return rows,tail

    def append(self,kind,payload):
        rows,tail=self.records()
        row={'schema':'polar.capability-journal/1','sequence':len(rows),'previous':tail,'kind':kind,
             'payload':payload,'at_ns':str(time.time_ns())}
        immutable(self.directory/f'journal-{len(rows):06d}.json',row)
        _replace(self.directory/'projection.json',{'count':len(rows)+1,'tail':digest(row)})
        return row

    def state(self):
        rows,tail=self.records();attempts=[]
        for row in rows:
            p=row['payload'];kind=row['kind']
            if kind=='START':
                exact(p,('attempt_id','kind','ordinal','replay_of'),'FAMILY_ROOT_MISMATCH')
                attempt_id(p['attempt_id'])
                require(type(p['ordinal']) is int and p['ordinal']==len(attempts) and p['kind']==('ORIGINAL' if not attempts else 'REPLAY'),'FAMILY_ROOT_MISMATCH')
                require((not attempts and p['replay_of'] is None) or
                        (len(attempts)==1 and attempts[0]['finish'] is not None
                         and attempts[0]['finish']['state']=='SUCCESS'
                         and attempts[0]['finish']['resource_evidence']=='VERIFIED'
                         and p['replay_of']==attempts[0]['finish']['packet_id']),'REPLAY_NOT_ADMISSIBLE')
                require(p['attempt_id'] not in [a['start']['attempt_id'] for a in attempts],'FAMILY_ROOT_MISMATCH')
                attempts.append({'start':p,'accounts':[],'resource':None,'runtime':None,'finish':None})
                require(len(attempts)<=2,'START_LIMIT')
                continue
            require(attempts and p.get('attempt_id')==attempts[-1]['start']['attempt_id']
                    and attempts[-1]['finish'] is None,'FAMILY_ROOT_MISMATCH')
            a=attempts[-1]
            if kind=='ACCOUNT':
                exact(p,('attempt_id','account_id','packet_ordinal','family_ordinal'),'FAMILY_ROOT_MISMATCH')
                require(type(p['packet_ordinal']) is int and type(p['family_ordinal']) is int
                        and a['runtime'] is not None and len(a['accounts'])<7 and p['packet_ordinal']==len(a['accounts'])
                        and p['account_id']==ACCOUNTS[len(a['accounts'])]
                        and p['family_ordinal']==sum(len(x['accounts']) for x in attempts),'ACCOUNT_ORDER_MISMATCH')
                a['accounts'].append(p)
            elif kind=='RESOURCE':
                exact(p,('attempt_id','cpu_us','wall_ns','native_wall_ns'),'FAMILY_ROOT_MISMATCH')
                prior=a['resource'] or {'cpu_us':0,'wall_ns':0,'native_wall_ns':0}
                require(all(type(p[k]) is int and p[k]>=prior[k]
                            for k in ('cpu_us','wall_ns','native_wall_ns')),'FAMILY_ROOT_MISMATCH')
                a['resource']=p
            elif kind=='RUNTIME':
                exact(p,('attempt_id','receipt_ref','observed_image_id'),'FAMILY_ROOT_MISMATCH')
                require(a['runtime'] is None and not a['accounts']
                        and p['observed_image_id']==self.header()['expected_image_id'],'EXPECTED_IMAGE_MISMATCH')
                a['runtime']=p
            else:
                exact(p,('attempt_id','state','reason','packet_id','completed_accounts','resource_evidence','physical_refs'),'FAMILY_ROOT_MISMATCH')
                require(p['state'] in ('SUCCESS','FAILED','INTERRUPTED')
                        and p['resource_evidence'] in ('VERIFIED','INCOMPLETE'),'FAMILY_ROOT_MISMATCH')
                require((p['reason'] is None if p['state']=='SUCCESS' else p['reason'] in REASONS),
                        'FAMILY_ROOT_MISMATCH')
                require(p['completed_accounts'] is None or type(p['completed_accounts']) is int
                        and 0<=p['completed_accounts']<=7,'FAMILY_ROOT_MISMATCH')
                if p['state']=='SUCCESS':
                    require(type(p['packet_id']) is str and re.fullmatch(r'[0-9a-f]{64}',p['packet_id']),
                            'FAMILY_ROOT_MISMATCH')
                    require(len(a['accounts'])==7 and p['completed_accounts']==7 and a['runtime'] is not None
                            and a['resource'] is not None and p['resource_evidence']=='VERIFIED','FAMILY_ROOT_MISMATCH')
                    if len(attempts)==2:
                        require(p['packet_id']==attempts[0]['finish']['packet_id'],'REPLAY_MISMATCH')
                a['finish']=p
        spent={key:sum((a['resource'] or {}).get(key,0) for a in attempts)
               for key in ('cpu_us','wall_ns','native_wall_ns')}
        return {'attempts':attempts,'spent':spent,'tail':tail,
                'remaining_known':all(a['finish'] is not None and a['finish']['resource_evidence']=='VERIFIED' for a in attempts)}

    def reserve(self,config,kind,replay_of=None):
        with self.locked():
            self.header(config);state=self.state();previous=state['attempts']
            require(len(previous)<2,'START_LIMIT')
            require(not previous or previous[-1]['finish'] is not None
                    and previous[-1]['finish']['state']=='SUCCESS','FAMILY_ALREADY_FAILED')
            require((not previous and kind=='ORIGINAL' and replay_of is None) or
                    (len(previous)==1 and kind=='REPLAY' and replay_of==previous[0]['finish']['packet_id']),'REPLAY_NOT_ADMISSIBLE')
            require(state['remaining_known'],'FAMILY_ALREADY_FAILED')
            if not self.technical:
                require(state['spent']['cpu_us']<600000000,'RESOURCE_CPU_LIMIT')
                require(state['spent']['wall_ns']<900000000000,'RESOURCE_WALL_LIMIT')
                require(state['spent']['native_wall_ns']<300000000000,'NATIVE_WALL_LIMIT')
            aid=str(uuid.uuid4())
            payload={'attempt_id':aid,'kind':kind,'ordinal':len(previous),'replay_of':replay_of}
            self.qualification('START',payload)
            return self.append('START',payload)

    def account(self,aid,account):
        with self.locked():
            state=self.state();a=state['attempts'][-1]
            require(a['start']['attempt_id']==aid and a['finish'] is None and a['runtime'] is not None,'FAMILY_ALREADY_FAILED')
            count=len(a['accounts'])
            require(count<7 and account==ACCOUNTS[count],'ACCOUNT_ORDER_MISMATCH')
            payload={'attempt_id':aid,'account_id':account,'packet_ordinal':count,
                     'family_ordinal':sum(len(x['accounts']) for x in state['attempts'])}
            self.qualification('ACCOUNT',payload)
            return self.append('ACCOUNT',payload)

    def resources(self,aid,cpu_us,wall_ns,native_wall_ns):
        with self.locked():
            state=self.state();a=state['attempts'][-1]
            require(a['start']['attempt_id']==aid and a['finish'] is None,'FAMILY_ALREADY_FAILED')
            previous=a['resource'] or {'cpu_us':0,'wall_ns':0,'native_wall_ns':0}
            values={'cpu_us':cpu_us,'wall_ns':wall_ns,'native_wall_ns':native_wall_ns}
            require(all(type(v) is int and v>=previous[k] for k,v in values.items()),'INTERNAL_EXECUTION_ERROR')
            payload={'attempt_id':aid,**values}
            result=self.append('RESOURCE',payload)
            self.qualification('RESOURCE',payload)
            total_cpu=state['spent']['cpu_us']-previous['cpu_us']+cpu_us
            total_wall=state['spent']['wall_ns']-previous['wall_ns']+wall_ns
            total_native=state['spent']['native_wall_ns']-previous['native_wall_ns']+native_wall_ns
            if not self.technical:
                require(total_cpu<=600000000,'RESOURCE_CPU_LIMIT')
                require(total_wall<=900000000000,'RESOURCE_WALL_LIMIT')
                require(total_native<=300000000000,'NATIVE_WALL_LIMIT')
            return result

    def runtime(self,aid,receipt_ref,observed_image):
        with self.locked():
            state=self.state();a=state['attempts'][-1]
            require(a['start']['attempt_id']==aid and a['runtime'] is None and not a['accounts'],'FAMILY_ALREADY_FAILED')
            require(observed_image==self.header()['expected_image_id'],'EXPECTED_IMAGE_MISMATCH')
            return self.append('RUNTIME',{'attempt_id':aid,'receipt_ref':receipt_ref,'observed_image_id':observed_image})

    def finish(self,aid,state,reason,packet_id,completed_accounts,physical_refs,*,resource_evidence='VERIFIED'):
        with self.locked():
            data=self.state();a=data['attempts'][-1]
            require(state in ('SUCCESS','FAILED','INTERRUPTED') and
                    (reason is None if state=='SUCCESS' else reason in REASONS),'FAMILY_ROOT_MISMATCH')
            require(a['start']['attempt_id']==aid and a['finish'] is None,'FAMILY_ALREADY_FAILED')
            if state=='SUCCESS':
                if not self.technical:
                    require(data['spent']['cpu_us']<=600000000,'RESOURCE_CPU_LIMIT')
                    require(data['spent']['wall_ns']<=900000000000,'RESOURCE_WALL_LIMIT')
                    require(data['spent']['native_wall_ns']<=300000000000,'NATIVE_WALL_LIMIT')
                    require((a['resource'] or {}).get('native_wall_ns',300000000001)<=300000000000,'NATIVE_WALL_LIMIT')
                require(type(packet_id) is str and re.fullmatch(r'[0-9a-f]{64}',packet_id),'SEMANTIC_INTEGRITY')
                require(resource_evidence=='VERIFIED' and completed_accounts==7 and len(a['accounts'])==7
                        and a['runtime'] is not None and a['resource'] is not None,'FAMILY_ALREADY_FAILED')
                if len(data['attempts'])==2:
                    require(packet_id==data['attempts'][0]['finish']['packet_id'],'REPLAY_MISMATCH')
            return self.append('FINISH',{'attempt_id':aid,'state':state,'reason':reason,'packet_id':packet_id,
                 'completed_accounts':completed_accounts,'resource_evidence':resource_evidence,'physical_refs':physical_refs})


class PacketStore(HistoryStore):
    def publish(self,files,protocol_sha256):
        require(set(files)==set(FILES),'SEMANTIC_FILE_SET')
        raw={}
        for name,value in files.items():
            validate(value,name[:-5]+'_file')
            require(value['stage_status']=='COMPLETE','SEMANTIC_INTEGRITY')
            raw[name]=canonical(value)
        manifest={'schema':'polar.hyp007-fixed-score-semantic-manifest/1','profile_id':PROFILE_ID,
                  'protocol_sha256':protocol_sha256,
                  'files':[{'filename':n,'bytes':len(raw[n]),'sha256':sha(raw[n])} for n in FILES]}
        validate(manifest,'semantic_manifest')
        body=canonical(manifest);pid=sha(body)
        self._publish('capability-packets',pid,{**raw,'semantic-manifest.json':body},file_limit=MAX_BYTES)
        return pid

    def report(self,pid):
        require(type(pid) is str and re.fullmatch(r'[0-9a-f]{64}',pid),'SEMANTIC_INTEGRITY')
        directory=self.root/'capability-packets'/pid
        require(directory.is_dir() and not directory.is_symlink()
                and {p.name for p in directory.iterdir()}==set(FILES)|{'semantic-manifest.json'},'SEMANTIC_FILE_SET')
        body=read_file(safe_root(self.root),f'capability-packets/{pid}/semantic-manifest.json',MAX_BYTES)
        require(sha(body)==pid,'SEMANTIC_INTEGRITY')
        manifest=decode(body);validate(manifest,'semantic_manifest')
        require(canonical(manifest)==body and [r['filename'] for r in manifest['files']]==list(FILES),'SEMANTIC_INTEGRITY')
        result={}
        for ref in manifest['files']:
            raw=read_file(self.root,f'capability-packets/{pid}/'+ref['filename'],MAX_BYTES)
            require(sha(raw)==ref['sha256'] and len(raw)==ref['bytes'],'SEMANTIC_INTEGRITY')
            value=decode(raw);validate(value,ref['filename'][:-5]+'_file')
            require(canonical(value)==raw and value['stage_status']=='COMPLETE','SEMANTIC_INTEGRITY')
            result[ref['filename']]=value
        return {'packet_id':pid,'manifest':manifest,'files':result}
