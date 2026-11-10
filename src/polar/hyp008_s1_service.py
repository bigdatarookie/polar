"""S1 facade in the existing Service: immutable preparation, admission and reports.

Deployment/locators/runtime factory are trusted host inputs, not request fields.
No registration/authority creation or reset operation is exposed.
"""
from pathlib import Path
import json

from .hyp008_s1_contract import (canonical,sha,ref,decode,require,validate,closed,identified,
    FAMILY,STAGES,S1ContractError)
from .hyp008_s1_store import S1Store,Deployment
from .hyp008_s1_loader import SourceGraph,prepare_source
from .hyp008_s1_semantic import project,verify_stored_values

INTERPRETATIONS=('163062e5ee25140526e6027351d46cc42e64ba0a16cb8ee4b7a82b9d985452e6',
 'ab8168b0a547c0dfc10de9c1605034b9447b7dadeee41692c0f60f3610377b17')


def not_bound(reason):
    return {'schema':'polar.hyp008-s1-admission/1','status':'NOT_BOUND','reason':reason,
            'family_charged':False,'scientific_starts':0}


class S1Service:
    def __init__(self,store,locators,runtime_factory=None):
        require(type(store) is S1Store,'S1_STORE_REQUIRED')
        self.store=store;self.locators=dict(locators);self.runtime_factory=runtime_factory

    def prepare(self,config):
        try:
            validate('Config',config)
            require(tuple(v['sha256'] for v in config['interpretation_refs'])==INTERPRETATIONS,'INTERPRETATION_BINDING')
            require(config['source_binding']['source_class']==self.store.trusted()['mode'],'SOURCE_DEPLOYMENT_MODE')
            metadata_graph=SourceGraph(self.locators)
            for pin in list(config['defaults'].values())+[config['source_projection']]+config['interpretation_refs']:
                self.store.raw_object(metadata_graph.raw(pin))
            masks,source,_=prepare_source(config,self.locators)
            config_ref=self.store.object(config);source_ref=self.store.object(source);masks_ref=self.store.object(masks)
            readiness='READY_FOR_SEAL' if masks['I'] else 'NO_ISSUE_COMPARISON'
            value={'schema':'polar.hyp008-s1-prepare/1','config_ref':config_ref,'source_graph_ref':source_ref,
                'masks_ref':masks_ref,'readiness':readiness,'reasons':[] if masks['I'] else ['NO_ISSUE_COMPARISON'],
                'lineage_status':'NOT_STARTED','numeric_work_performed':False}
            value['prepare_id']=sha(canonical(value));validate('Prepare',value);self.store.object(value)
            if not masks['I']:
                files=project(config,source,masks,{}, {'status':'NOT_STARTED','reason':'NO_ISSUE_COMPARISON'})
                manifest=self.store.publish(files)
                with self.store.locked():
                    self.store.trusted();self.store._record('s1-assessments',value['prepare_id'],
                        {'prepared_ref':ref(canonical(value)),'manifest_ref':ref(canonical(manifest)),
                         'experiment_id':manifest['experiment_id'],'family_charged':False})
            return value
        except (ValueError,KeyError,TypeError,OSError) as exc:
            return not_bound(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)

    def seal(self,prepared_ref,registration_ref,code_ref,build_ref,qa_ref,execution_assignment_ref,runtime_plan_ref):
        try:
            prepared=self.store.get(prepared_ref);validate('Prepare',prepared);identified(prepared,'prepare_id')
            require(prepared['readiness']=='READY_FOR_SEAL','NO_EXECUTION_SEAL_FOR_NO_ISSUE')
            cfg=self.store.get(prepared['config_ref']);validate('Config',cfg)
            registration=self.store.get(registration_ref);validate('Registration',registration)
            require(cfg['source_projection']==code_ref,'SOURCE_PROJECTION_REF')
            value={'schema':'polar.hyp008-s1-seal/1','prepared_ref':prepared_ref,'registration_ref':registration_ref,
                'store_binding_ref':self.store.object(self.store.deployment.binding),'code_ref':code_ref,
                'build_ref':build_ref,'qa_ref':qa_ref,'execution_assignment_ref':execution_assignment_ref,
                'runtime_plan_ref':runtime_plan_ref}
            value['seal_id']=sha(canonical(value));validate('Seal',value)
            self._qualification(value,prepared)
            self.store.object(value)  # No authority/grant is created here.
            return value
        except (ValueError,KeyError,TypeError,OSError) as exc:
            return not_bound(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)

    def _json(self,pin):return decode(self.store.raw_get(pin))

    def _qualification(self,seal,prepared):
        code=self._json(seal['code_ref']);build=self._json(seal['build_ref']);qa=self._json(seal['qa_ref'])
        plan=self._json(seal['runtime_plan_ref']);assignment=self._json(seal['execution_assignment_ref'])
        closed(code,('schema','candidate','files'),'polar.hyp008-s1-code-projection/1')
        require(type(code['candidate']) is dict and set(code['candidate'])=={'commit','tree'},'CODE_CANDIDATE')
        require(build['commit']==code['candidate']['commit'] and build['tree']==code['candidate']['tree']
                and code['files']==build['source_files'],'CODE_BUILD_MAP')
        require(type(qa) is dict,'RECORD_SCHEMA')
        if qa.get('schema')=='polar.hyp008-s1-pre-admission/1':
            closed(qa,('schema','code_ref','build_ref','verdicts','proof_refs','system_status'),
                'polar.hyp008-s1-pre-admission/1')
            require(qa['system_status']=='NOT_RUN','PRE_ADMISSION_SYSTEM_STATUS')
            verdicts={'code':'PASS','numeric':'PASS','admission':'PASS'}
        else:
            # Retain the old fully-qualified record contract without treating it
            # as a prerequisite for independently testing the first positive run.
            closed(qa,('schema','code_ref','build_ref','verdicts','proof_refs'),'polar.hyp008-s1-qualification/1')
            verdicts={'code':'PASS','numeric':'PASS','system':'PASS'}
        require(qa['code_ref']==seal['code_ref'] and qa['build_ref']==seal['build_ref'] and
                qa['verdicts']==verdicts and type(qa['proof_refs']) is list and qa['proof_refs'],
                'QUALIFICATION_NOT_BOUND')
        for pin in qa['proof_refs']:self.store.raw_get(pin)
        closed(assignment,('schema','prepared_ref','registration_ref','native_qitem','scope'),
               'polar.hyp008-s1-execution-assignment/1')
        require(assignment['prepared_ref']==seal['prepared_ref'] and assignment['registration_ref']==seal['registration_ref']
            and type(assignment['native_qitem']) is str and assignment['native_qitem'].startswith('qitem-')
            and assignment['scope']==self.store.trusted()['mode'],'EXECUTION_ASSIGNMENT')
        closed(plan,('schema','candidate','image_id','source_build_ref','launcher_refs','store_profile_ref'),
               'polar.hyp008-s1-runtime-plan/1')
        require(plan['candidate']==code['candidate'] and plan['image_id']==build['image_id']
            and plan['source_build_ref']==seal['build_ref'] and plan['store_profile_ref']==self.store.deployment.profile_ref,
            'RUNTIME_STORE_PROFILE')
        require(type(plan['launcher_refs']) is list and len(plan['launcher_refs'])>=1,'LAUNCHER_BINDING')
        for pin in plan['launcher_refs']:self.store.raw_get(pin)
        return code,plan

    def run(self,seal):
        aid=None;components={};result=None;masks=None;config=None;source=None;runtime_ref=None
        admission_attempted=False
        try:
            validate('Seal',seal);identified(seal,'seal_id')
            prepared=self.store.get(seal['prepared_ref']);validate('Prepare',prepared);identified(prepared,'prepare_id')
            require(prepared['readiness']=='READY_FOR_SEAL','PREPARED_NOT_READY')
            config=self.store.get(prepared['config_ref']);validate('Config',config)
            if self.store.authority(seal) is None:return not_bound('EXECUTION_NOT_AUTHORIZED')
            if (self.store.root/self.store.family()).exists():return not_bound('FAMILY_ALREADY_STARTED')
            code,plan=self._qualification(seal,prepared)
            if self.runtime_factory is None:return not_bound('TRUSTED_RUNTIME_NOT_CONFIGURED')
            # The constructor supplies the factory, never the request/config.
            binding=self.runtime_factory(code,plan)
            require(binding.candidate==code['candidate'] and binding.image_id==plan['image_id'],'RUNTIME_FACTORY_BINDING')
            binding.verify()  # Actual source/image/default/native checks before family admission.
            runtime_ref=self.store.raw_object(Path(binding.preparation_path).read_bytes())
            masks,source,rows=prepare_source(config,self.locators)
            require(ref(canonical(masks))==prepared['masks_ref'] and ref(canonical(source))==prepared['source_graph_ref'],
                    'PREPARATION_SOURCE_CHANGED')
            require(masks['I'],'NO_ISSUE_COMPARISON')
            # All input bytes are now a verified read-only in-memory snapshot.
            admission_attempted=True
            aid=self.store.begin(seal)  # Before any payload/ratio/conversion/moment.
            training_ids,training_z,training_y,score_z,history,targets,components=self._represent(rows,masks,components,aid)
            from .hyp008_s1_models import fixed_family
            def start(name):
                require(name in ('TREE_START','LINEAR_START','HISTORICAL_PASS_START'),'STAGE_CALLBACK')
                self.store.stage_intent(aid,name.removesuffix('_START'))
            def observe(stage,state,evidence):self.store.witness(aid,stage,state,evidence)
            result=fixed_family(training_ids,training_z,training_y,score_z,history,targets,masks,binding,start,observe=observe)
            actual=self.store.stages(aid)
            matched=all('completed' in actual[s] for s in STAGES)
            if matched and result['status']=='COMPLETE':
                tree_evidence=self.store.get(actual['TREE']['completed']['evidence_ref'])
                linear_evidence=self.store.get(actual['LINEAR']['completed']['evidence_ref'])
                require(tree_evidence['model_text_sha256']==sha(result['artifacts']['tree']['model_text'].encode())
                    and linear_evidence['proof_id']==result['artifacts']['linear']['proof']['proof_id'],'NATIVE_RESULT_MATCH')
                history_evidence=self.store.get(actual['HISTORICAL_PASS']['completed']['evidence_ref'])
                require(history_evidence['history_sha256']==sha(json.dumps(result['artifacts']['history'],sort_keys=True,separators=(',',':')).encode()),'NATIVE_HISTORY_MATCH')
            files=project(config,source,masks,components,result,unresolved_native=not matched)
            manifest=self.store.publish(files)
            status='SUCCESS' if result['status']=='COMPLETE' and matched else 'PLANNED_FAMILY_UNAVAILABLE'
            terminal=self.store.finish(aid,status,None if status=='SUCCESS' else result.get('reason'),
                manifest_ref=ref(canonical(manifest)),runtime_ref=runtime_ref)
            self._publication(manifest,aid,terminal)
            return {'schema':'polar.hyp008-s1-run-result/1','attempt_id':aid,'experiment_id':manifest['experiment_id'],
                    'status':status,'financial':'NOT_ASSESSED'}
        except (Exception,KeyboardInterrupt) as exc:
            if aid is None:
                if admission_attempted and (self.store.root/self.store.family()).exists():
                    # Family-first durability may survive a lost attempt link/return.
                    # Never label this zero charge or manufacture resumption authority.
                    try:orphan=self.store._read(self.store.family(),'start')
                    except Exception:orphan=None
                    return {'schema':'polar.hyp008-s1-admission/1','status':'UNFINALIZED',
                        'reason':'ADMISSION_PUBLICATION_INTERRUPTED','family_charged':True if orphan else 'UNKNOWN',
                        'scientific_starts':1 if orphan else None,'attempt_id':orphan['attempt_id'] if orphan else None,
                        'resumption_allowed':False}
                return not_bound(str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
            # No restart/refund, including failures before fixed_family enters its try.
            actual=self.store.stages(aid)
            for stage,facts in actual.items():
                if 'intent' in facts and not any(k in facts for k in ('boundary','completed','not-reached')):
                    self.store.witness(aid,stage,'NOT_REACHED',{'reason':type(exc).__name__,
                        'positive_control_flow':'caught_before_trusted_native_boundary_hook'})
            from .hyp008_s1_numeric import S1NumericError
            reason='NUMERIC_UNVERIFIED' if isinstance(exc,S1NumericError) else type(exc).__name__
            result={'status':'PLANNED_FAMILY_UNAVAILABLE','reason':reason,
                'detail':str(exc)[:256],'stage':None,'stages':{
                    s:'SUCCESS' if 'completed' in facts else 'FAILED' if 'intent' in facts else 'NOT_RUN'
                    for s,facts in actual.items()}}
            files=project(config,source,masks,components,result)
            manifest=self.store.publish(files)
            terminal=self.store.finish(aid,'PLANNED_FAMILY_UNAVAILABLE',reason,
                manifest_ref=ref(canonical(manifest)),runtime_ref=runtime_ref)
            self._publication(manifest,aid,terminal)
            return {'schema':'polar.hyp008-s1-run-result/1','attempt_id':aid,'experiment_id':manifest['experiment_id'],
                    'status':'PLANNED_FAMILY_UNAVAILABLE','reason':reason,'financial':'NOT_ASSESSED'}

    def _represent(self,rows,masks,components,aid):
        from .hyp008_s1_numeric import SLOTS,projected_payload,fit_transform,transform_score,ratio,round_binary64
        by_id={r['opportunity_id']:r for r in rows}
        training_ids=tuple(r['opportunity_id'] for r in masks['training'] if r['admitted'])
        require(training_ids,'NO_ADMITTED_TRAINING')
        values=lambda rid:tuple(projected_payload(by_id[rid]['X'][slot]['represented_source_payload'],slot) for slot in SLOTS)
        transform=fit_transform(tuple(values(rid) for rid in training_ids))
        components['transform.json']=transform
        self._partial(aid,'transform','training',transform)
        cache={}
        def b_record(rid):
            if rid not in cache:
                row=by_id[rid]['B'];cache[rid]={'opportunity_id':rid,'source_ref':row['numeric_source_ref'],
                    'represented_fraction':row['represented_fraction'],'rounding':round_binary64(ratio(row['represented_fraction']))}
                self._partial(aid,'target',rid,cache[rid])
            return cache[rid]
        training_targets=[b_record(rid) for rid in training_ids]
        scoring=[]
        for rid in masks['I']:
            record={'opportunity_id':rid,'values':transform_score(values(rid),transform)}
            self._partial(aid,'score',rid,record);scoring.append(record)
        target_rows=[b_record(rid) for rid in masks['P']]
        census={r['opportunity_id']:r for r in masks['C']};history={};history_records=[]
        for rid in masks['I']:
            ids=census[rid]['history_window'];records=[b_record(key) for key in ids]
            history_records.append({'opportunity_id':rid,'window_ids':ids,'values':records})
            history[rid]={'ids':ids,'bits':[r['rounding']['bits'] for r in records]}
        representations={'schema':'polar.hyp008-s1-representations/1','training_ids':list(training_ids),
            'training_targets':training_targets,'scoring':scoring,'targets':target_rows,'history':history_records}
        components['representations.json']=representations
        z=tuple(tuple(cell['bits'] for cell in row) for row in transform['training_z'])
        score={r['opportunity_id']:tuple(cell['z']['bits'] for cell in r['values']) for r in scoring}
        return (training_ids,z,tuple(r['rounding']['bits'] for r in training_targets),score,history,
            {r['opportunity_id']:r['rounding']['bits'] for r in target_rows},components)

    def _partial(self,aid,kind,key,value):
        with self.store.locked():
            self.store.trusted();self.store._record('s1-attempts/'+aid+'/partial-'+kind,sha(key.encode()),value)

    def _publication(self,manifest,aid,terminal):
        with self.store.locked():
            self.store.trusted();self.store._record('s1-publications',manifest['experiment_id'],
                {'attempt_id':aid,'terminal_ref':ref(canonical(terminal)),'manifest_ref':ref(canonical(manifest))})

    def attempt(self,attempt_id):return self.store.attempt(attempt_id)

    def report(self,experiment_id):
        result=self.store.report(experiment_id);values=result['files']
        from .hyp008_s1_semantic import validate_producers
        validate_producers(values)
        if values['family.json']['status']!='NOT_STARTED':
            publication=self.store._read('s1-publications',experiment_id)
            terminal=self.store.attempt(publication['attempt_id'])
            require(publication['manifest_ref']==ref(canonical(result['manifest'])) and
                publication['terminal_ref']==ref(canonical(terminal)) and
                terminal['manifest_ref']==publication['manifest_ref'],'PUBLICATION_TERMINAL_BINDING')
            if values['family.json']['status']=='COMPLETE':
                require(terminal['terminal_status']=='SUCCESS' and
                        all('completed' in terminal['stage_records'][s] for s in STAGES),'UNVERIFIED_COMPLETION')
        result['cleanup_status']='UNKNOWN_UNLESS_BOUND_BY_SEPARATE_OPERATION_RECEIPT'
        result['qualified_score']=values.get('evaluation.json') if values['family.json']['status']=='COMPLETE' else None
        return result

    def verify_stored(self,experiment_id):
        result=self.report(experiment_id)
        return {'experiment_id':experiment_id,**verify_stored_values(result['files'])}


PROFILE=Path('/run/polar/s1-deployment.json')


def configured_operation(operation,*args):
    """Fixed trusted host deployment location. No caller-selectable profile/root."""
    require(operation in ('prepare','seal','run','attempt','report','verify_stored'),'S1_OPERATION')
    if not PROFILE.is_file():return not_bound('TRUSTED_S1_DEPLOYMENT_NOT_CONFIGURED')
    from .history_bundle import read_file,safe_root
    profile=decode(read_file(safe_root(PROFILE.parent),PROFILE.name,limit=1024**2))
    closed(profile,('schema','binding','runtime_root','root_identity','authority_directory',
                   'locators','defaults_directory','storage_limit'),'polar.hyp008-s1-deployment/1')
    require(type(profile['root_identity']) is list and len(profile['root_identity'])==2
        and all(type(v) is int and v>=0 for v in profile['root_identity']),'TRUSTED_ROOT_IDENTITY')
    require(type(profile['storage_limit']) is int and 0<profile['storage_limit']<=64*1024**3,'STORE_TOTAL_STORAGE')
    root=Path(profile['runtime_root'])
    require(str(root)=='/polar-artifacts','CANONICAL_CONTAINER_STORE')
    st=root.stat()
    # Host identity is supplied by the trusted profile and attested by config3.
    # Local identity guards replacement within this process/namespace only.
    deployment=Deployment(root,profile['binding'],(st.st_dev,st.st_ino),
        Path(profile['authority_directory']),tuple(profile['root_identity']),Path('/polar-launch/preparation.json'))
    store=S1Store(deployment,profile['storage_limit'])
    def runtime_factory(code,plan):
        from .hyp008_s1_models import NativeBinding
        return NativeBinding(code['candidate'],plan['image_id'],'/polar-launch/preparation.json',profile['defaults_directory'])
    service=S1Service(store,profile['locators'],runtime_factory)
    if operation=='seal':
        require(len(args)==1 and type(args[0]) is dict,'SEAL_ARGUMENTS')
        return service.seal(**args[0])
    return getattr(service,operation)(*args)
