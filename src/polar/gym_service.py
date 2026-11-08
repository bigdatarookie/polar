"""Installed fixed-run/replay operations; no scheduler, DB, dynamic strategy or financial PASS."""
import importlib.metadata
import multiprocessing
import os
import platform
import time
from pathlib import Path
from .gym_contract import GymError, canonical, sha, read_ref, decode, MAX_BYTES, COMPOSITION_SHA
from .gym_data import load_inputs
from .gym_evaluation import evaluate


def code_binding():
    root=Path(__file__).parent
    names=sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.sql'))
    return {n:sha((root/n).read_bytes()) for n in names}

def native_worker(connection,converted):
    try:
        from .gym_nautilus import simulate
        result=simulate(converted);connection.send(('SUCCESS',result))
    except BaseException as exc:
        connection.send(('FAILED',str(exc) if isinstance(exc,GymError) else type(exc).__name__))
    finally:connection.close()

def bounded_simulation(converted):
    ctx=multiprocessing.get_context('spawn');parent,child=ctx.Pipe(False)
    process=ctx.Process(target=native_worker,args=(child,converted),daemon=True);process.start();child.close()
    try:
        if not parent.poll(300):raise GymError('NATIVE_WALL_TIMEOUT')
        status,value=parent.recv();process.join(10)
        if process.is_alive() or process.exitcode!=0 or status!='SUCCESS':raise GymError('NATIVE_FAILED_'+str(value))
        return value
    finally:
        parent.close()
        if process.is_alive():process.terminate();process.join(2)
        if process.is_alive():process.kill();process.join()

class GymService:
    def __init__(self,store):self.store=store
    def preflight(self,config):
        converted,report,pins,physical=load_inputs(config)
        return {'schema':'polar.gym-preparation/1','preflight':report,'converted':converted,
                'code':code_binding(),'input_bindings':pins,'physical_refs':physical,
                'strategy_execution':'NOT_RUN'}
    def runtime(self,ref):
        raw=read_ref(ref)
        if sha(raw)!=COMPOSITION_SHA:raise GymError('COMPOSITION_LOCK_MISMATCH')
        lock=decode(raw)
        import sys
        if not sys.version.startswith('3.13.') or platform.machine()!='aarch64' or platform.system()!='Linux':raise GymError('NATIVE_PLATFORM_MISMATCH')
        for name,version in lock['packages'].items():
            if importlib.metadata.version(name)!=version:raise GymError('NATIVE_PACKAGE_MISMATCH')
        for filename,expected in lock['runtime_files'].items():
            path=Path(filename)
            if not path.is_absolute() or not path.is_file() or sha(path.read_bytes())!=expected:raise GymError('NATIVE_RUNTIME_HASH')
        return {'sha256':sha(raw),'bytes':len(raw),'python':platform.python_version(),'machine':platform.machine(),'system':platform.system()}
    def run(self,config,*,replay_of=None):
        # Snapshot the source/config identity; every real numerical invocation must be explicitly bound.
        source=code_binding()
        if config.get('code')!=source:raise GymError('APPLICATION_CODE_MISMATCH')
        runtime=self.runtime(config['build'])
        prepared=self.preflight(config)
        if not prepared['preflight']['execution_allowed']:raise GymError('PREFLIGHT_DISALLOWED')
        bindings={'schema':'polar.gym-run-bindings/1','namespace':config['namespace'],
                  'input_bindings':prepared['input_bindings'],'code':source,'runtime':runtime}
        if config['namespace']=='retained':
            auth=decode(read_ref(config['execution_authorization']))
            if auth.get('schema')!='polar.gym-execution-authorization/1' or auth.get('bindings_sha256')!=sha(canonical(bindings)) or auth.get('max_full_packet_invocations')!=2 or auth.get('purpose')!='FIXED_PAIR_AND_REPLAY':
                raise GymError('RETAINED_EXECUTION_NOT_BOUND')
        previous=None
        if replay_of:
            previous=self.store.report(replay_of)
            if previous['manifest']['bindings']!=bindings:raise GymError('REPLAY_BINDING_MISMATCH')
        start=self.store.begin(config,bindings);aid=start['attempt_id'];began=time.monotonic()
        try:
            with self.store.locked():
                self.store.record('gym-attempts/'+aid,'input-receipt',{'refs':prepared['physical_refs'],'config':config,
                    'replay_of':replay_of,'pid':os.getpid(),'environment':{'platform':platform.platform()},'read_at_ns':time.time_ns()})
            # Re-read actual bytes immediately before simulation, not a cached free-form PASS.
            immediate=self.preflight(config)
            if canonical(immediate)!=canonical(prepared) or code_binding()!=source:raise GymError('INPUT_CHANGED_BEFORE_SIMULATION')
            with self.store.locked():self.store.record('gym-attempts/'+aid,'preflight',prepared)
            simulation=bounded_simulation(prepared['converted'])
            with self.store.locked():self.store.record('gym-attempts/'+aid,'simulation',simulation)
            evaluation=evaluate(simulation)
            files={'converted.json':prepared['converted'],'preflight.json':prepared['preflight'],
                   'simulation.json':simulation,'evaluation.json':evaluation}
            experiment=self.store.publish(files,bindings)
            if replay_of and experiment!=replay_of:raise GymError('REPLAY_SEMANTIC_MISMATCH')
            self.store.finish(aid,{'schema':'polar.gym-attempt-finish/1','status':'SUCCESS','experiment_id':experiment,
                  'replay_of':replay_of,'finished_ns':time.time_ns(),'wall_seconds':str(time.monotonic()-began),
                  'physical_full_packet_invocations':1,'financial_verdict':'INSUFFICIENT_EVIDENCE_ENGINEERING_DEMONSTRATION'})
            return self.store.attempt(aid)
        except BaseException as exc:
            self.store.finish(aid,{'schema':'polar.gym-attempt-finish/1','status':'FAILED',
                  'code':str(exc) if isinstance(exc,GymError) else type(exc).__name__,
                  'finished_ns':time.time_ns(),'wall_seconds':str(time.monotonic()-began)})
            raise
    def replay(self,config,experiment):return self.run(config,replay_of=experiment)
    def attempt(self,aid):return self.store.attempt(aid)
    def report(self,experiment):return self.store.report(experiment)
