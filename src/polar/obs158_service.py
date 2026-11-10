"""Fixed OBS158 preparation/run/replay; no scheduler, acquisition or financial verdict."""
import json
import multiprocessing
import os
from pathlib import Path
import re
import sys
import time
import traceback
import uuid

from .gym_service import GymService
from .history_bundle import read_file
from .hyp003_source import decode as decode_physical
from .obs158_contract import (PROTOCOL,MAX_BYTES,FILES,ENGINEERING_CHECKS,COMPOSITION_SHA,
    canonical,decode,sha,source_code,semantic_bindings,source_context)
from .obs158_data import (Inputs,load_obs158_inputs,public_profile,read_bound,preflight_obs158,
                         convert_obs158,PUBLIC_SHA,METRIC_SHA)
from .obs158_math import require,Obs158Error
from .obs158_evaluation import evaluate_obs158


def preflight_diagnostic(report):
    """Bounded check metadata only: never echo private inputs or physical bindings."""
    checks = report.get('checks')
    fields = {'code', 'status', 'reason', 'required', 'basis'}
    token = lambda value: type(value) is str and re.fullmatch(r'[A-Z0-9_]{1,128}', value)
    valid = (type(checks) is list and len(checks) <= 64 and all(
        type(c) is dict and set(c) == fields and token(c['code']) and
        c['status'] in ('PASS', 'FAIL', 'NOT_RUN') and type(c['required']) is bool and
        token(c['basis']) and (c['reason'] is None or token(c['reason'])) for c in checks))
    # A malformed diagnostic must not replace the original admission failure or
    # publish arbitrary source strings. The known checker has a fixed small shape.
    return ({'schema':'polar.obs158-preflight-diagnostic/1','checks':decode(canonical(checks)),
             'runner_execution_allowed':False,'scope':'CHECK_METADATA_ONLY'} if valid else
            {'schema':'polar.obs158-preflight-diagnostic/1','status':'UNAVAILABLE',
             'reason':'INVALID_CHECK_METADATA','runner_execution_allowed':False})


def _worker(converted,aliases,code,directory):
    """Child writes a bounded result, not a large potentially blocking IPC message."""
    target=Path(directory)/'native.json'
    try:
        require(source_code()==code,'SOURCE_CHANGED_BEFORE_NATIVE_IMPORT')
        require(not any(k=='nautilus_trader' or k.startswith('nautilus_trader.') for k in sys.modules),
                'NATIVE_IMPORTED_BEFORE_CHILD_BINDING')
        from .obs158_nautilus import simulate_obs158
        value={'status':'SUCCESS','simulation':simulate_obs158(converted,aliases)}
    except BaseException as exc:
        trace=''.join(traceback.format_exception(type(exc),exc,exc.__traceback__,limit=32))
        trace=trace.encode('utf-8',errors='replace')[:16384].decode('utf-8',errors='ignore')
        value={'status':'FAILED','error_type':type(exc).__name__,
               'code':str(exc) if isinstance(exc,Obs158Error) else 'NATIVE_WORKER_FAILED',
               'traceback':trace}
    raw=canonical(value)
    if len(raw)>MAX_BYTES:raw=canonical({'status':'FAILED','code':'NATIVE_OUTPUT_BOUND'})
    with target.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    target.chmod(0o400)


def _simulate(converted,aliases,code,directory,seconds):
    process=multiprocessing.get_context('spawn').Process(
        target=_worker,args=(converted,aliases,code,str(directory)),daemon=True)
    process.start()
    try:
        process.join(seconds)
        require(not process.is_alive(),'OBS158_NATIVE_WALL_TIMEOUT')
        require(process.exitcode==0,'OBS158_NATIVE_PROCESS_FAILED')
        raw=read_file(directory,'native.json',MAX_BYTES)
        value=decode(raw)
        require(value['status']=='SUCCESS',value.get('code','NATIVE_WORKER_FAILED'))
        return value['simulation']
    finally:
        if process.is_alive():process.terminate();process.join(2)
        if process.is_alive():process.kill();process.join(2)
        require(not process.is_alive(),'OBS158_NATIVE_CLEANUP_UNVERIFIED')


class Obs158Service:
    def __init__(self,store):self.store=store
    def binding(self,config):
        require(type(config) is dict and set(config)=={'schema','source_class','input_config',
                'source_code','candidate','image_id','composition_ref','controls_ref',
                'authorization_ref','preparation_path'} and config['schema']=='polar.obs158-run-config/1',
                'OBS158_CONFIG_SCHEMA')
        require(config['source_class'] in ('RETAINED','INVENTED')
                and (config['preparation_path']=='/polar-launch/preparation.json' or
                     config['source_class']=='INVENTED' and config['preparation_path']=='CI_MANAGED'),'OBS158_CONFIG_DOMAIN')
        code=source_code();require(config['source_code']==code,'OBS158_APPLICATION_CODE_MISMATCH')
        require(type(config['candidate']) is dict and set(config['candidate'])=={'commit','tree'}
                and all(type(v) is str and re.fullmatch(r'[a-f0-9]{40}',v)
                        for v in config['candidate'].values())
                and type(config['image_id']) is str
                and re.fullmatch(r'sha256:[a-f0-9]{64}',config['image_id']),'OBS158_IMAGE_IDENTITY')
        for name in ('composition_ref','controls_ref','authorization_ref'):
            ref=config[name]
            require(type(ref) is dict and {'path','sha256'}<=set(ref)<={'path','sha256','bytes'}
                    and type(ref['path']) is str and type(ref['sha256']) is str
                    and re.fullmatch(r'[a-f0-9]{64}',ref['sha256']),'OBS158_REFERENCE_SCHEMA')
        return {'schema':'polar.obs158-execution-bindings/1','protocol':PROTOCOL,
                'source_class':config['source_class'],'public_sha256':PUBLIC_SHA,
                'metric_sha256':METRIC_SHA,'source_code':code,'candidate':config['candidate'],
                'image_id':config['image_id'],'composition_sha256':COMPOSITION_SHA,
                'input_config_sha256':sha(canonical(config['input_config'])),
                'controls_sha256':config['controls_ref']['sha256'],
                'artifact_root':str(self.store.root.resolve()),'storage_bytes':self.store.limit}
    def authorization(self,config,bindings,operation):
        auth=decode(read_bound(config['authorization_ref'],1024**2))
        require(type(auth) is dict and set(auth)=={'schema','bindings_sha256','artifact_root',
                'operations','purpose','family','max_full_packet_starts','limits'}
                and auth.get('schema')=='polar.obs158-execution-authorization/1'
                and auth.get('bindings_sha256')==sha(canonical(bindings))
                and auth.get('artifact_root')==str(self.store.root.resolve())
                and type(auth['operations']) is list and bool(auth['operations'])
                and all(type(v) is str for v in auth['operations'])
                and len(auth['operations'])==len(set(auth['operations']))
                and set(auth['operations'])<={'PREFLIGHT','RUN','REPLAY'}
                and operation in auth['operations'],
                'OBS158_EXECUTION_NOT_BOUND')
        expected='FIXED_PAIR_AND_REPLAY' if config['source_class']=='RETAINED' else 'INVENTED_FIXED_PAIR'
        require(auth.get('purpose')==expected,'OBS158_EXECUTION_PURPOSE')
        # v27: INVENTED keeps legacy count metadata, not a technical call pool.
        # Actual retained authority remains exactly two starts.
        require(type(auth['family']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',auth['family'])
                and type(auth['max_full_packet_starts']) is int
                and 1<=auth['max_full_packet_starts']
                and (config['source_class']!='RETAINED' or auth['max_full_packet_starts']==2),
                'OBS158_PACKET_BUDGET')
        limits=auth.get('limits',{})
        require(type(limits) is dict and set(limits)=={'total_wall_seconds','native_wall_seconds','cleanup_reserve_seconds'}
                and all(type(v) is int for v in limits.values())
                and 5<=limits['cleanup_reserve_seconds']<limits['total_wall_seconds']<=86400
                and 0<limits['native_wall_seconds']<=limits['total_wall_seconds']-limits['cleanup_reserve_seconds'],
                'OBS158_FINITE_JOB_LIMITS')
        return auth
    def runtime(self,config,code):
        if config['preparation_path']=='CI_MANAGED':
            from .obs158_ci import runtime
            return runtime(config,code)
        # Observed launcher creates this immutable receipt before the command.
        path=Path(config['preparation_path']);raw=path.read_bytes()
        require(len(raw)<=1024**2,'OBS158_RUNTIME_RECEIPT_BOUND');prep=decode(raw)
        require(prep['schema']=='polar.observed-preparation/1' and prep['preparation']=='PREPARED'
                and prep['observed']['image_id']==config['image_id']
                and prep['observed']['os']=='linux' and prep['observed']['architecture']=='arm64'
                and all(prep['observed']['matches'].values())
                and os.geteuid()==10001 and sys.platform=='linux','OBS158_RUNTIME_IDENTITY')
        require(prep['expected']['candidate']==config['candidate']
                and decode(read_bound(prep['expected']['refs']['config'],1024**2))==config,
                'OBS158_RUNTIME_CONFIG_BINDING')
        observed=prep['source_binding']
        expected={'/app/src/polar/'+p:v for p,v in code.items()}
        require(observed['packaged_source_independently_observed'] is True
                and observed['observed_files']==expected
                and observed['observed_container_id']==prep['observed']['container_id']
                and observed['overlays']=='UNSUPPORTED_NO_OVERLAYS_MOUNTED','OBS158_RUNTIME_SOURCE_BINDING')
        # SRE measurements are physical provenance, not financial float inputs.
        # Preserve their numeric tokens as strings while checking identity fields.
        build=decode_physical(read_bound(prep['expected']['refs']['source_build'],1024**2))
        require(build['commit']==config['candidate']['commit'] and build['tree']==config['candidate']['tree']
                and build['image_id']==config['image_id'] and build['source_files']==expected,
                'OBS158_RUNTIME_BUILD_BINDING')
        native=GymService(None).runtime(config['composition_ref'])
        return {'schema':'polar.obs158-observed-runtime/1','preparation_sha256':sha(raw),
                'container_id':prep['observed']['container_id'],'image_id':config['image_id'],
                'candidate':config['candidate'],'native_runtime':native,'actual_uid':os.geteuid()}
    def controls(self,config,code):
        value=decode(read_bound(config['controls_ref'],1024**2))
        require(type(value) is dict and value.get('schema')=='polar.obs158-controls-binding/1'
                and value.get('public_sha256')==PUBLIC_SHA and value.get('metric_sha256')==METRIC_SHA
                and value.get('source_code_sha256')==sha(canonical(code))
                and value.get('output_contract_sha256')==code['obs158_output_schema.json']['sha256']
                and value.get('composition_sha256')==COMPOSITION_SHA
                and type(value.get('checks')) is dict
                and set(value['checks'])==set(ENGINEERING_CHECKS),'OBS158_CONTROLS_IDENTITY')
        for reference in value['checks'].values():read_bound(reference,MAX_BYTES)
        # This verifies selected evidence identities; it does not re-run a review
        # or grant a financial verdict. Independent admission belongs to OpenRig.
        return value
    def inputs(self,config):
        if config['preparation_path']=='CI_MANAGED':
            from .obs158_ci import inputs
            return inputs(config)
        c=config['input_config']
        if config['source_class']=='RETAINED':return load_obs158_inputs(c)
        require(type(c) is dict and set(c)=={'schema','public_ref','metric_ref','fixture_ref',
                                            'calendar_ref','timezone_ref'}
                and c['schema']=='polar.obs158-invented-input-config/1','OBS158_INVENTED_CONFIG')
        profile=public_profile(c['public_ref'],c['metric_ref']);p=decode(profile)
        protocol=p['members']['protocol-v1.json']
        raw=read_bound(c['fixture_ref'],MAX_BYTES);fixture=decode(raw)
        require(set(fixture)=={'schema','rows','context'}
                and fixture['schema']=='polar.obs158-invented-input/1','OBS158_INVENTED_SCHEMA')
        for field,original in (('calendar_ref','calendar'),('timezone_ref','timezone')):
            require(c[field]['sha256']==protocol[original]['sha256'],
                    'INVENTED_METADATA_CONTENT_MISMATCH')
        calendar_raw=read_bound(c['calendar_ref'],1024**2)
        timezone=read_bound(c['timezone_ref'],1024**2)
        require(len(calendar_raw)==protocol['calendar']['bytes']
                and len(timezone)==protocol['timezone']['bytes'],'INVENTED_METADATA_CONTENT_MISMATCH')
        bindings={'fixture':{'sha256':sha(raw),'bytes':len(raw)},
                  'profile':{'sha256':sha(profile),'bytes':len(profile)},
                  'calendar':{'sha256':sha(calendar_raw),'bytes':len(calendar_raw)},
                  'timezone':{'sha256':sha(timezone),'bytes':len(timezone)}}
        return Inputs(profile,tuple(canonical(row) for row in fixture['rows']),
                      tuple(decode(calendar_raw)['sessions']),timezone,canonical(fixture['context']),
                      canonical(bindings),'INVENTED')
    def prepare(self,config,bindings):
        runtime=self.runtime(config,bindings['source_code'])
        controls=self.controls(config,bindings['source_code'])
        inputs=self.inputs(config);converted=convert_obs158(inputs)
        report=preflight_obs158(inputs,converted)
        data_checks=[c for c in report['checks'] if c['code'] not in ENGINEERING_CHECKS]
        diagnostic=preflight_diagnostic(report)
        try:
            require(all(c['status']=='PASS' for c in data_checks if c['required']),
                    'OBS158_DATA_PREFLIGHT_DISALLOWED')
        except Obs158Error as exc:
            exc.preflight_diagnostic=diagnostic
            raise
        aliases=decode(inputs.profile)['members']['cohort-order-v1.json']['symbols_in_route_order']
        semantic_preflight={'schema':'polar.obs158-runner-preflight/1','data_checks':data_checks,
             'engineering_evidence_identity_bound':True,'runtime_source_identity_matched':True,
             'runner_execution_allowed':True,'source_class':inputs.source_class,
             'financial_status':'INSUFFICIENT_EVIDENCE',
             'financial_scope':'PRICE_ONLY_PARTIAL_ACTION_EXECUTION_MODEL'}
        return inputs,converted,aliases,report,semantic_preflight,runtime,controls
    def preflight(self,config):
        config=decode(canonical(config))
        bindings=self.binding(config);self.authorization(config,bindings,'PREFLIGHT')
        inputs,converted,aliases,data,report,runtime,controls=self.prepare(config,bindings)
        return {'schema':'polar.obs158-preparation/1','preflight':report,
                'part_a':data,'semantic_bindings':semantic_bindings(bindings['source_code'],inputs),
                'converted_sha256':sha(canonical(converted)),'actual_runtime':runtime,
                'controls_ref':config['controls_ref'],'native_execution':'NOT_RUN'}
    def run(self,config,*,replay_of=None):
        config=decode(canonical(config))
        bindings=self.binding(config)
        auth=self.authorization(config,bindings,'REPLAY' if replay_of else 'RUN')
        start=self.store.begin_packet(config['source_class'],bindings,auth,replay_of)
        aid=start['attempt_id'];began=time.monotonic();deadline=began+auth['limits']['total_wall_seconds']
        try:
            with self.store.locked():
                self.store.record('obs158-attempts/'+aid,'physical-input',{
                    'schema':'polar.obs158-physical-input/1','config':config,
                    'authorization':auth,'pid':os.getpid(),'read_at_ns':time.time_ns()})
            inputs,converted,aliases,data,preflight,runtime,controls=self.prepare(config,bindings)
            semantic=semantic_bindings(bindings['source_code'],inputs)
            if replay_of:
                prior=self.store.report_packet(replay_of)
                require(prior['manifest']['bindings']==semantic,'REPLAY_SEMANTIC_BINDING_MISMATCH')
            with self.store.locked():
                self.store.record('obs158-attempts/'+aid,'preparation',{
                    'part_a':data,'runner':preflight,'runtime':runtime,'controls':controls,
                    'source_receipts':decode(inputs.bindings)})
            require(source_code()==bindings['source_code'],'SOURCE_CHANGED_BEFORE_NATIVE_IMPORT')
            remaining=deadline-time.monotonic()-auth['limits']['cleanup_reserve_seconds']
            require(remaining>0,'OBS158_NO_NATIVE_CLEANUP_RESERVE')
            directory=self.store.root/'obs158-attempts'/aid/('native-'+uuid.uuid4().hex)
            directory.mkdir(mode=0o700)
            simulation=_simulate(converted,aliases,bindings['source_code'],directory,
                                 min(remaining,auth['limits']['native_wall_seconds']))
            physical=simulation.pop('physical')
            with self.store.locked():self.store.record('obs158-attempts/'+aid,'native-physical',{
                'native_issuers':physical,'finished_ns':time.time_ns(),'output_directory':str(directory)})
            evaluation=evaluate_obs158(simulation,converted,aliases)
            require(time.monotonic()<deadline,'OBS158_TOTAL_WALL_EXHAUSTED')
            files={'converted.json':converted,'preflight.json':preflight,
                   'source-context.json':source_context(inputs,aliases),
                   'simulation.json':simulation,'evaluation.json':evaluation}
            identity=self.store.publish_packet(files,semantic)
            require(not replay_of or identity==replay_of,'REPLAY_SEMANTIC_MISMATCH')
            self.store.finish_packet(aid,{'schema':'polar.obs158-attempt-finish/1','status':'SUCCESS',
                'experiment_id':identity,'replay_of':replay_of,'finished_ns':time.time_ns(),
                'wall_seconds':str(time.monotonic()-began),'full_packet_starts':1,
                'engine_runs':2,'financial_status':'INSUFFICIENT_EVIDENCE'})
            return self.store.packet(aid)
        except BaseException as exc:
            failure={'schema':'polar.obs158-attempt-finish/1','status':'FAILED',
                'code':str(exc) if isinstance(exc,Obs158Error) else type(exc).__name__,
                'finished_ns':time.time_ns(),'wall_seconds':str(time.monotonic()-began),
                'native_output_directory':str(directory) if 'directory' in locals() else None,
                'financial_status':'INSUFFICIENT_EVIDENCE'}
            if hasattr(exc,'preflight_diagnostic'):
                failure['preflight_diagnostic']=exc.preflight_diagnostic
            self.store.finish_packet(aid,failure)
            raise
    def replay(self,config,identity):return self.run(config,replay_of=identity)
    def attempt(self,aid):return self.store.packet(aid)
    def report(self,identity):return self.store.report_packet(identity)
