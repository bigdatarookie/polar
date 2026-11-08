"""Fixed no-refit capability admission/orchestration, not a scheduler or financial verdict."""
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .capability_contract import (CapabilityError, require, exact, canonical, decode, sha, digest,
    PROFILE_ID, SCHEMA_SHA, MAPPING, PROFILE, ROSTER, BASIS, ACCOUNTS, STAGES, FILES,
    fixed, validate, envelope, MAX_BYTES, REASONS)
from .capability_inputs import checked_ref, read_ref, semantic_ref
from .capability_profile import evaluate
from .capability_store import FamilyStore, PacketStore, DEFAULT_ANCHOR, immutable, record, attempt_id
from .capability_runtime import (ObservedRuntime, host_cpu_us, _WallBudget, _stop_owned,
    CLEANUP_COMMAND_NS, OWNED_REAP_NS, FINAL_ACCOUNTING_NS)

CONFIG_FIELDS=('schema','profile_id','mode','technical_case','family_root','execution_authorization',
    'protocol_refs','input_refs','auxiliary_refs','code','build_ref','runtime_refs','expected_image_id','launch')
SOURCE_FILES=('src/polar/capability_contract.py','src/polar/capability_profile.py',
    'src/polar/capability_inputs.py','src/polar/capability_store.py','src/polar/capability_runtime.py',
    'src/polar/capability_service.py','src/polar/capability_native.py','src/polar/capability_worker.py',
    'src/polar/capability_schema.json','scripts/polar_capability_worker.py',
    'src/polar/allocation.py','src/polar/rank_weights.py','src/polar/service.py')
PROTOCOL_HASHES={
    'proposal_v1':'ebeeb3439d24eac4c463ed253bfa556975582717c1c07a7f51f2e103172388ca',
    'disposition_v2':'7a57742235745157e433c86d97ffbe4aea68af17f24eb76e2dfbedf76860348c',
    'implementation_contract':'ee19ed80b88e35105aba945a3ea2189b25ed28180214cf054239adf86e4eb577',
    'semantic_schema':SCHEMA_SHA}


def config(value,root):
    exact(value,CONFIG_FIELDS,'BINDING_MISMATCH')
    require(value['schema']=='polar.hyp007-capability-config/1' and value['profile_id']==PROFILE_ID,
            'BINDING_MISMATCH')
    require(value['mode'] in ('RETAINED','TECHNICAL_FIXTURE'),'UNBOUND_EXECUTION_AUTHORIZATION')
    require(value['family_root']==str(Path(root).resolve()),'FAMILY_ROOT_MISMATCH')
    require(value['technical_case'] is None if value['mode']=='RETAINED' else
            type(value['technical_case']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value['technical_case']),
            'BINDING_MISMATCH')
    exact(value['protocol_refs'],PROTOCOL_HASHES,'BINDING_MISMATCH')
    for name,ref in value['protocol_refs'].items():
        checked_ref(ref);require(ref['sha256']==PROTOCOL_HASHES[name],'BINDING_MISMATCH')
    exact(value['input_refs'],('score_seal','score_manifest','capsule_manifest','capsule_readiness',
                               'raw_manifest','actions_manifest','calendar','tzdata'),'BINDING_MISMATCH')
    exact(value['code'],('accepted_commit','accepted_tree','source_projection'),'BINDING_MISMATCH')
    require(all(type(value['code'][k]) is str and re.fullmatch(r'[a-f0-9]{40}',value['code'][k])
                for k in ('accepted_commit','accepted_tree')),'BINDING_MISMATCH')
    require(type(value['expected_image_id']) is str
            and re.fullmatch(r'sha256:[a-f0-9]{64}',value['expected_image_id']),'BINDING_MISMATCH')
    exact(value['runtime_refs'],('packages_ref','api_lock_ref'),'BINDING_MISMATCH')
    launch=value['launch']
    exact(launch,('tool_ref','observer_ref','harness_ref','review_ref','expectations_ref','source_build_ref','build_fields'),
          'BINDING_MISMATCH')
    require(launch['source_build_ref']==value['build_ref'],'BINDING_MISMATCH')
    exact(launch['build_fields'],('commit','tree','image_id'),'BINDING_MISMATCH')
    for fields in launch['build_fields'].values():
        require(type(fields) is list and 1<=len(fields)<=8 and all(type(k) is str
            and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',k) for k in fields),'BINDING_MISMATCH')
    require(type(value['auxiliary_refs']) is list and len(value['auxiliary_refs'])<=128,'BINDING_MISMATCH')
    refs=list(value['input_refs'].values())+value['auxiliary_refs']+[value['build_ref'],
        value['code']['source_projection']]+list(value['runtime_refs'].values())+[
            launch[name] for name in ('tool_ref','observer_ref','harness_ref','review_ref','expectations_ref')]
    for ref in refs:
        path=checked_ref(ref)
        require(path.is_file() and path.stat().st_size<=MAX_BYTES,'INPUT_INTEGRITY')
        require(str(path).isascii(),'BINDING_MISMATCH')  # Same JSON preimage as accepted JS publisher.
    canonical(value)
    return value


class _UnreapedPreprocess(CapabilityError):
    """Partial resource evidence cannot be upgraded after an unverified reap."""


class CapabilityService:
    def __init__(self,root,limit,anchor=DEFAULT_ANCHOR):
        self.root=Path(root);self.limit=limit;self.anchor=Path(anchor)
        self.packets=PacketStore(self.root,limit)

    def family(self,cfg):
        return FamilyStore(self.root,self.anchor,technical=cfg['mode']=='TECHNICAL_FIXTURE',
                           case_id=cfg['technical_case'])

    def static(self,cfg):
        cfg=config(cfg,self.root)
        for ref in cfg['protocol_refs'].values():read_ref(ref)
        # Only static metadata/code is read here; seal/capsule numerical members are untouched.
        projection=decode(read_ref(cfg['code']['source_projection']))
        exact(projection,('schema','files'),'BINDING_MISMATCH')
        require(projection['schema']=='polar.capability-source-projection/1'
                and type(projection['files']) is dict and set(projection['files'])==set(SOURCE_FILES),
                'BINDING_MISMATCH')
        repository=Path(__file__).resolve().parents[2]
        for name,expected in projection['files'].items():
            require(type(expected) is str and re.fullmatch(r'[a-f0-9]{64}',expected)
                    and sha((repository/name).read_bytes())==expected,'BINDING_MISMATCH')
        build=decode(read_ref(cfg['build_ref']),inert_numbers=True)
        for field,keys in cfg['launch']['build_fields'].items():
            value=build
            for key in keys:
                require(type(value) is dict and key in value,'BINDING_MISMATCH')
                value=value[key]
            require(value==(cfg['expected_image_id'] if field=='image_id'
                            else cfg['code']['accepted_'+field]),'BINDING_MISMATCH')
        for ref in cfg['runtime_refs'].values():read_ref(ref)
        for name in ('tool_ref','observer_ref','harness_ref','review_ref','expectations_ref'):
            read_ref(cfg['launch'][name])
        family=self.family(cfg);family.header(cfg)
        # Authorization and registry inspection only: no registration/reservations.
        return cfg,family

    def prepare(self,cfg):
        try:
            cfg,family=self.static(cfg)
            state=family.state()
            return {'schema':'polar.hyp007-capability-preparation/1','status':'STATIC_ONLY',
                'configuration_sha256':digest(cfg),'family_id':PROFILE_ID,
                'prior_starts':len(state['attempts']),'remaining_known':state['remaining_known'],
                'score_restore':'NOT_RUN','mapper':'NOT_RUN','allocator':'NOT_RUN',
                'native':'NOT_RUN','financial_evidence':'NOT_ASSESSED'}
        except (CapabilityError,OSError,ValueError,KeyError,TypeError,AttributeError):
            return {'schema':'polar.hyp007-capability-preparation/1','status':'NOT_PREPARED',
                    'reason':'BINDING_MISMATCH','execution':'NOT_RUN'}

    def _preprocess(self,cfg,family,aid,directory,started,cpu_origin):
        immutable(directory/'sealed-config.json',cfg)
        prior=family.state()['spent']
        wall_budget=_WallBudget(started,prior['wall_ns'])
        wall_budget.work_timeout()
        process=subprocess.Popen([sys.executable,'-m','polar.capability_worker','--prepare',
            str(directory/'sealed-config.json'),str(directory)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        last=0
        try:
            while True:
                wall_budget.work_timeout()
                wall=time.monotonic_ns()-started
                # Host child is unreaped: logical-CPU capacity is a conservative CPU guard.
                upper=(wall*(os.cpu_count() or 1)+999)//1000
                require(prior['cpu_us']+upper<=600000000,'RESOURCE_CPU_LIMIT')
                wall_budget.work_timeout()
                if wall-last>=1000000000:
                    family.resources(aid,max(host_cpu_us()-cpu_origin,upper),wall,0);last=wall
                if process.poll() is not None:break
                time.sleep(min(.02,wall_budget.work_timeout()))
            # poll() reaped the child; there is no unbounded extra wait.
            require(process.returncode==0,'INPUT_INTEGRITY')
            return record(directory/'prepared-native.json')
        finally:
            if not _stop_owned(process,wall_budget,reserve_ns=(
                    CLEANUP_COMMAND_NS+OWNED_REAP_NS+FINAL_ACCOUNTING_NS)):
                raise _UnreapedPreprocess('OBSERVATION_MISSING') from None
            wall_budget.timeout()
            family.resources(aid,max(host_cpu_us()-cpu_origin,
                ((time.monotonic_ns()-started)*(os.cpu_count() or 1)+999)//1000),
                time.monotonic_ns()-started,0)

    def _execute(self,cfg,kind,replay_of=None):
        # Config/source/build/auth metadata may be admitted without packet input reads.
        cfg,family=self.static(cfg)
        reservation=family.reserve(cfg,kind,replay_of)
        aid=reservation['payload']['attempt_id'];started=time.monotonic_ns();cpu_origin=host_cpu_us()
        # A directory failure AFTER reserve is still a spent UNFINALIZED start.
        directory=self.root/'capability-attempts'/aid
        directory.parent.mkdir(exist_ok=True)
        directory.mkdir(mode=0o700)
        immutable(directory/'reservation.json',reservation)
        runtime=None;packet_id=None
        try:
            prepared=self._preprocess(cfg,family,aid,directory,started,cpu_origin)
            runtime=ObservedRuntime(cfg,family,aid,directory,started,cpu_origin)
            native=runtime.run(prepared)
            accounts=native['accounts']
            for account in accounts:
                require(account['account_id'] in ACCOUNTS,'METHOD_JOIN_MISMATCH')
                require(len(account['allocations'])==2,'ALLOCATION_DOMAIN')
                entry,exit=account['allocations']
                require(entry['phase']=='entry' and exit['phase']=='exit','ALLOCATION_DOMAIN')
                # Raw allocator output is the actual order oracle, with no resizing.
                for phase,result in (('entry',entry),('exit',exit)):
                    intended=[r for r in result['allocation']['rows'] if r['delta']]
                    submitted=[r for r in account['events'] if r['kind']=='ORDER_SUBMITTED' and r['phase']==phase]
                    require(len(intended)==len(submitted) and all(
                        a['instrument_id']==b['opportunity_token'] and abs(a['delta'])==b['quantity']
                        for a,b in zip(intended,submitted)),'NATIVE_FILL_MISMATCH')
            metrics=[evaluate(a['account_id'],a['samples'],a['events']) for a in accounts]
            require(native['forbidden_calls']=={'fits':0,'predict':0,'transform':0,
                'feature_rebuild':0,'label_rebuild':0},'FORBIDDEN_ML_CALL')
            payloads={
                'bindings.json':self.bindings(cfg,prepared,native,runtime),
                'scores.json':prepared['scores_payload'],'targets.json':prepared['targets'],
                'allocations.json':{'accounts':[{'account_id':a['account_id'],
                    'phases':a['allocations']} for a in accounts]},
                'events.json':{'accounts':[{'account_id':a['account_id'],'events':a['events']} for a in accounts]},
                'samples.json':{'accounts':[{'account_id':a['account_id'],'samples':a['samples']} for a in accounts]},
                'metrics.json':{'accounts':metrics},
                'status.json':{'packet_status':'COMPLETE','required_accounts':list(ACCOUNTS),
                    'accounts':[{'account_id':a['account_id'],'status':'COMPLETE','samples':7,
                        'outstanding_orders':0,'terminal_positions_zero':True,'all_required_checks_passed':True}
                        for a in accounts],
                    'stages':[{'stage':stage,'status':'COMPLETE','reason_codes':[]} for stage in STAGES],
                    'mapper_calls':1,'allocator_calls':14,'fresh_native_accounts':7,
                    'forbidden_calls':native['forbidden_calls'],
                    'financial_evidence':'INSUFFICIENT_EVIDENCE_ENGINEERING_CAPABILITY',
                    'original_hyp007_adoption':'NOT_ASSESSED'}}
            files={name:envelope(name,payloads[name]) for name in FILES}
            packet_id=self.packets.publish(files,cfg['protocol_refs']['implementation_contract']['sha256'])
            self.packets.report(packet_id)  # Whole-file integrity BEFORE family success.
            if kind=='REPLAY':require(packet_id==replay_of,'REPLAY_MISMATCH')
            runtime.usage(force=True)
            physical=self.physical_refs(directory)
            family.finish(aid,'SUCCESS',None,packet_id,7,physical)
            return self.attempt(aid,cfg)
        except BaseException as exc:
            reason=exc.code if isinstance(exc,CapabilityError) and exc.code in REASONS else (
                'INTERRUPTED' if isinstance(exc,(KeyboardInterrupt,SystemExit)) else 'INTERNAL_EXECUTION_ERROR')
            evidence='INCOMPLETE' if isinstance(exc,_UnreapedPreprocess) else 'VERIFIED'
            try:
                if runtime:runtime.usage(force=True)
                else:family.resources(aid,max(host_cpu_us()-cpu_origin,
                ((time.monotonic_ns()-started)*(os.cpu_count() or 1)+999)//1000),
                time.monotonic_ns()-started,0)
            except BaseException:evidence='INCOMPLETE'
            if runtime is not None and not runtime.resource_finalized:evidence='INCOMPLETE'
            completed=0 if runtime is None else None
            if runtime:
                try:completed=record(directory/'observed-launch/scenario/worker-resources.json')['completed_accounts']
                except (OSError,ValueError,KeyError,TypeError):evidence='INCOMPLETE'
            # Physical failure may lack valid semantic operands; preserve raw facts without fabricated zeros.
            family.finish(aid,'INTERRUPTED' if reason=='INTERRUPTED' else 'FAILED',
                          reason,None,completed,self.physical_refs(directory),resource_evidence=evidence)
            if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
            return self.attempt(aid,cfg)

    def run(self,cfg):
        return self._execute(cfg,'ORIGINAL')

    def replay(self,cfg,packet_id):
        self.packets.report(packet_id)  # No candidate invocation on reconciliation.
        return self._execute(cfg,'REPLAY',packet_id)

    def bindings(self,cfg,prepared,native,runtime):
        actual=record(Path(runtime.receipt['path']))['observed']['image_id']
        return {'protocol_refs':{k:semantic_ref(v) for k,v in cfg['protocol_refs'].items()},
            'input_refs':{k:semantic_ref(v) for k,v in cfg['input_refs'].items()},
            'profile':PROFILE,'roster':ROSTER,'mapping':list(MAPPING),'mapping_sha256':digest(list(MAPPING)),
            'lineage_refs':prepared['lineage_refs'],
            'code':{**{k:cfg['code'][k] for k in ('accepted_commit','accepted_tree')},
                    'source_projection':semantic_ref(cfg['code']['source_projection'])},
            'build_ref':semantic_ref(cfg['build_ref']),'expected_image_id':cfg['expected_image_id'],
            'observed_image_id':actual,'runtime':{**native['runtime'],
                **{k:semantic_ref(v) for k,v in cfg['runtime_refs'].items()}},
            'assurance':fixed('shared_42b1e8cfe7f0c779'),'basis':BASIS}

    def physical_refs(self,directory):
        rows=[];total=0
        for path in sorted(directory.rglob('*')):
            require(not path.is_symlink(),'INPUT_INTEGRITY')
            if path.is_file():
                require(path.stat().st_size<=MAX_BYTES and len(rows)<20000,'INPUT_INTEGRITY')
                body=path.read_bytes();total+=len(body)
                require(total<=128*1024**2,'INPUT_INTEGRITY')
                rows.append({'path':str(path.relative_to(directory)),'sha256':sha(body),'bytes':len(body)})
        return rows

    def attempt(self,aid,cfg=None):
        attempt_id(aid)
        directory=self.root/'capability-attempts'/aid
        if cfg is None and (directory/'sealed-config.json').exists():
            cfg=record(directory/'sealed-config.json')
        if cfg is not None:
            family=self.family(config(cfg,self.root));family.header(cfg);state=family.state()
        else:
            candidates=[]
            for header in (self.anchor/'families').glob('*/header.json'):
                key=header.parent.name
                family=FamilyStore(self.root,self.anchor,technical=key.startswith('technical-'),
                                   case_id=key[10:] if key.startswith('technical-') else None)
                try:
                    state=family.state()
                    if any(a['start']['attempt_id']==aid for a in state['attempts']):candidates.append((family,state))
                except (OSError,CapabilityError):continue
            require(len(candidates)==1,'BINDING_MISMATCH');family,state=candidates[0]
        matches=[a for a in state['attempts'] if a['start']['attempt_id']==aid]
        require(len(matches)==1,'BINDING_MISMATCH')
        value=matches[0]
        if value['runtime']:
            runtime=value['runtime']
            ref=runtime['receipt_ref'];body=Path(ref['path']).read_bytes()
            require(sha(body)==ref['sha256'],'INPUT_INTEGRITY')
            receipt=decode(body)
            require(receipt['preparation']=='PREPARED'
                    and receipt['observed']['image_id']==runtime['observed_image_id']
                    and runtime['observed_image_id']==family.header()['expected_image_id']
                    and all(receipt['observed']['matches'].values()),'EXPECTED_IMAGE_MISMATCH')
        if value['finish']:
            for ref in value['finish']['physical_refs']:
                path=directory/ref['path']
                require(path==path.resolve() and path.is_relative_to(directory),'INPUT_INTEGRITY')
                body=path.read_bytes()
                require(len(body)==ref['bytes'] and sha(body)==ref['sha256'],'INPUT_INTEGRITY')
            if value['finish']['state']=='SUCCESS':self.packets.report(value['finish']['packet_id'])
        return {'schema':'polar.hyp007-capability-attempt/1','attempt_id':aid,
            'state':value['finish']['state'] if value['finish'] else 'UNFINALIZED',
            'known_facts':value,'family_spent':state['spent'],'remaining_known':state['remaining_known'],
            'financial_evidence':'INSUFFICIENT_EVIDENCE_ENGINEERING_CAPABILITY'}

    def report(self,packet_id):
        report=self.packets.report(packet_id)
        # Every successful packet requires its separate authoritative physical finish graph.
        matches=[]
        for path in (self.root/'capability-attempts').glob('*/sealed-config.json'):
            aid=path.parent.name
            value=self.attempt(aid)
            finish=value['known_facts']['finish']
            if finish and finish['state']=='SUCCESS' and finish['packet_id']==packet_id:matches.append(aid)
        require(matches,'SEMANTIC_INTEGRITY')
        return {**report,'physical_attempts':matches}
