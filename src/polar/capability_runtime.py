"""Host supervisor composes the accepted observed launcher; owns no Docker lifecycle."""
from pathlib import Path
import os
import resource
import signal
import selectors
import subprocess
import time
import uuid

from .capability_contract import require, exact, canonical, decode, digest, sha, ACCOUNTS, CapabilityError
from .capability_store import immutable, record
from .capability_inputs import read_ref

NODE=Path('/Users/garry/.local/node-v24.22.1-darwin-arm64/bin/node')


def prepared_input_ref(directory,prepared):
    """Reference the preprocessor's sole publication; never republish it."""
    path=directory/'prepared-native.json'
    raw=canonical(record(path))  # record rejects unsafe paths/noncanonical bytes.
    require(raw==canonical(prepared),'INPUT_INTEGRITY')
    return {'path':str(path),'sha256':sha(raw),'bytes':len(raw)}


def host_cpu_us():
    own=resource.getrusage(resource.RUSAGE_SELF);children=resource.getrusage(resource.RUSAGE_CHILDREN)
    return int((own.ru_utime+own.ru_stime+children.ru_utime+children.ru_stime)*1000000)



# These intervals are RESERVED inside the existing cumulative 900-second ceiling.
FINAL_ACCOUNTING_NS=2000000000
OWNED_REAP_NS=2000000000
CLEANUP_COMMAND_NS=30000000000
CLEANUP_RESERVE_NS=2*OWNED_REAP_NS+CLEANUP_COMMAND_NS+FINAL_ACCOUNTING_NS


class _WallBudget:
    def __init__(self,started_ns,prior_wall_ns,clock=None):
        require(type(started_ns) is int and type(prior_wall_ns) is int
                and 0<=prior_wall_ns<900000000000,'RESOURCE_WALL_LIMIT')
        self.clock=clock or time.monotonic_ns
        self.deadline=started_ns+900000000000-prior_wall_ns

    def remaining_ns(self,reserve_ns=0):
        return self.deadline-self.clock()-reserve_ns

    def timeout(self,*,reserve_ns=0,cap_ns=None):
        left=self.remaining_ns(reserve_ns)
        if cap_ns is not None:left=min(left,cap_ns)
        # Round DOWN to a millisecond, never offer a fresh relative deadline.
        milliseconds=left//1000000
        require(milliseconds>0,'RESOURCE_WALL_LIMIT')
        return milliseconds/1000

    def work_timeout(self,cap_ns=None):
        return self.timeout(reserve_ns=CLEANUP_RESERVE_NS,cap_ns=cap_ns)

    def scenario_ms(self):
        milliseconds=int(self.work_timeout(300000000000)*1000)
        require(milliseconds>=100,'RESOURCE_WALL_LIMIT')
        return milliseconds


def _stop_owned(process,wall,*,reserve_ns):
    """Never wait indefinitely after kill, including an uninterruptible child."""
    if process.poll() is not None:return True
    try:os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    try:
        timeout=wall.timeout(reserve_ns=reserve_ns,cap_ns=OWNED_REAP_NS)
        process.wait(timeout=timeout)
        return True
    except (subprocess.TimeoutExpired,CapabilityError):
        return False


def _cleanup_owned(process,argv,wall):
    launch_reaped=_stop_owned(process,wall,reserve_ns=(
        CLEANUP_COMMAND_NS+OWNED_REAP_NS+FINAL_ACCOUNTING_NS))
    # subprocess.run(timeout=...) has an unbounded reap on its timeout path.
    # Own the process explicitly so BOTH command wait and kill/reap are bounded.
    cleanup=None;cleanup_reaped=False;exit_code=None
    try:
        timeout=wall.timeout(reserve_ns=OWNED_REAP_NS+FINAL_ACCOUNTING_NS,
                             cap_ns=CLEANUP_COMMAND_NS)
        cleanup=subprocess.Popen(argv,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                 start_new_session=True)
        # Popen itself may have consumed time: recompute before waiting.
        timeout=min(timeout,wall.timeout(reserve_ns=OWNED_REAP_NS+FINAL_ACCOUNTING_NS,
                                         cap_ns=CLEANUP_COMMAND_NS))
        exit_code=cleanup.wait(timeout=timeout)
        cleanup_reaped=True
    except (OSError,subprocess.TimeoutExpired,CapabilityError):
        pass
    finally:
        if cleanup is not None and not cleanup_reaped:
            cleanup_reaped=_stop_owned(cleanup,wall,reserve_ns=FINAL_ACCOUNTING_NS)
            if cleanup_reaped:exit_code=cleanup.returncode
    return {'launcher_reaped':launch_reaped,'cleanup_reaped':cleanup_reaped,
            'exit_code':exit_code,
            'verified':launch_reaped and cleanup_reaped and exit_code==0}


def engine_capacity(wall):
    """Bounded metadata observation using the SAME attempt deadline."""
    wall.work_timeout()
    process=subprocess.Popen(['docker','info','--format','{{json .}}'],
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
    data=bytearray();selector=selectors.DefaultSelector()
    end=time.monotonic_ns()+5000000000
    try:
        selector.register(process.stdout,selectors.EVENT_READ)
        while True:
            timeout=min(wall.work_timeout(),(end-time.monotonic_ns())/1000000000)
            require(timeout>0,'OBSERVATION_MISSING')
            if not selector.select(min(.05,timeout)):continue
            chunk=os.read(process.stdout.fileno(),min(4096,1048576-len(data)+1))
            if not chunk:break
            require(len(data)+len(chunk)<=1048576,'OBSERVATION_MISSING');data.extend(chunk)
        timeout=min(wall.work_timeout(),(end-time.monotonic_ns())/1000000000)
        require(timeout>0,'OBSERVATION_MISSING')
        process.wait(timeout=timeout)
        require(process.returncode==0,'OBSERVATION_MISSING')
        info=decode(bytes(data),inert_numbers=True)
        require(type(info.get('NCPU')) is int and 1<=info['NCPU']<=1024
                and type(info.get('ID')) is str and info['ID'],'OBSERVATION_MISSING')
        return {'engine_id':info['ID'],'logical_cpus':info['NCPU']}
    finally:
        selector.close();process.stdout.close()
        require(_stop_owned(process,wall,reserve_ns=(
            CLEANUP_COMMAND_NS+OWNED_REAP_NS+FINAL_ACCOUNTING_NS)),'OBSERVATION_MISSING')


class ObservedRuntime:
    def __init__(self,config,store,aid,directory,started_ns,host_cpu_origin):
        self.config=config;self.store=store;self.aid=aid;self.directory=directory
        self.started=started_ns;self.cpu_origin=host_cpu_origin
        self.worker_cpu=0;self.native_ns=0;self.measured_cpu=0
        self.active_since=None;self.charged=0;self.receipt=None;self.physical=[]
        self.launched=False;self.last_usage=0;self.resource_finalized=False
        state=self.store.state()
        current=state['attempts'][-1]['resource'] or {'cpu_us':0,'wall_ns':0}
        self.prior={k:state['spent'][k]-current[k] for k in ('cpu_us','wall_ns')}
        self.host_capacity=os.cpu_count()
        require(type(self.host_capacity) is int and 1<=self.host_capacity<=1024,'OBSERVATION_MISSING')
        self.engine=None;self.guest_origin=None;self.charge_cpu=current['cpu_us']
        self.wall=_WallBudget(self.started,self.prior['wall_ns'])

    def usage(self,force=False):
        now=time.monotonic_ns()
        if not force and now-self.last_usage<1000000000:return
        self.last_usage=now
        wall=time.monotonic_ns()-self.started
        cpu=host_cpu_us()-self.cpu_origin+self.worker_cpu
        self.measured_cpu=max(self.measured_cpu,cpu)
        guest=0 if self.guest_origin is None else (
            (now-self.guest_origin)*self.engine['logical_cpus']+999)//1000
        upper=(wall*self.host_capacity+999)//1000+guest
        self.charge_cpu=max(self.charge_cpu,self.measured_cpu,upper)
        self.store.resources(self.aid,self.charge_cpu,wall,self.native_ns)

    def observe(self,launch_root,binding):
        path=launch_root/'preparation.json'
        if not path.exists():return
        receipt=record(path)
        require(receipt.get('schema')=='polar.observed-preparation/1'
                and receipt.get('preparation')=='PREPARED','OBSERVATION_MISSING')
        expected=receipt['expected'];actual=receipt['observed']
        require(expected['launch_id']==binding['launch_id']
                and expected['binding_sha256']==sha(canonical({'config':binding,'output_root':str(launch_root)})[:-1])
                and expected['candidate']==binding['candidate']
                and expected['image_id']==self.config['expected_image_id']
                and actual['image_id']==self.config['expected_image_id']
                and actual['container_id']==receipt['owned_resources']['container_id']
                and actual['os']=='linux' and actual['architecture']=='arm64'
                and set(actual['matches'])=={'image','platform','user','entrypoint','command','environment','not_started'}
                and all(actual['matches'].values())
                and receipt['producer']['sha256']==self.config['launch']['observer_ref']['sha256']
                and self.engine is not None and receipt['engine']['id']==self.engine['engine_id'],
                'EXPECTED_IMAGE_MISMATCH')
        require(expected['refs'].keys()==binding['refs'].keys(),'BINDING_MISMATCH')
        for name,ref in binding['refs'].items():
            require(all(expected['refs'][name][k]==ref[k] for k in ('path','sha256')),'BINDING_MISMATCH')
        ref={'path':str(path),'sha256':sha(path.read_bytes())}
        if self.receipt is None:
            self.store.runtime(self.aid,ref,actual['image_id']);self.receipt=ref
        else:require(self.receipt==ref,'BINDING_MISMATCH')

    def run(self,prepared):
        self.wall.work_timeout()
        cfg=self.config;launch=cfg['launch'];root=self.directory/'observed-launch'
        # Full actual packaged application is separately bound by source_build/review refs.
        for name in ('tool_ref','observer_ref','harness_ref','review_ref','expectations_ref','source_build_ref'):
            read_ref(launch[name])
        require(NODE.is_file(),'OBSERVATION_MISSING')
        input_ref=prepared_input_ref(self.directory,prepared)
        control=immutable(self.directory/'worker-config.json',{'schema':'polar.capability-worker/1',
            'attempt_id':self.aid,'prepared_input_sha256':digest(prepared),
            'expectations_sha256':launch['expectations_ref']['sha256']})
        refs={name:{k:ref[k] for k in ('path','sha256')} for name,ref in {
            'source_build':launch['source_build_ref'],'harness':launch['harness_ref'],
            'input':input_ref,'expectations':launch['expectations_ref'],'config':control,
            'review':launch['review_ref']}.items()}
        binding={'schema':'polar.observed-launch-config/1','launch_id':str(uuid.uuid4()),
            'candidate':{k:cfg['code']['accepted_'+k] for k in ('commit','tree')},
            'image_id':cfg['expected_image_id'],'runtime_image_id':cfg['expected_image_id'],
            'platform':'linux/arm64','user':'10001:10001','entrypoint':'/usr/local/bin/python',
            'environment':{'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'},
            'refs':refs,'build_fields':launch['build_fields'],'scenario_timeout_ms':300000}
        require(sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file())<32*1024**2,
                'INPUT_INTEGRITY')
        self.engine=engine_capacity(self.wall)
        immutable(self.directory/'engine-capacity.json',self.engine)
        binding['scenario_timeout_ms']=self.wall.scenario_ms()
        config_path=self.directory/'observed-config.json';immutable(config_path,binding)
        self.wall.work_timeout()
        origin=time.monotonic_ns();guard_cpu_origin=host_cpu_us()
        self.guest_origin=origin
        # Bounded stdout is not a receipt; all actual tool evidence is immutable on disk.
        process=subprocess.Popen([str(NODE),launch['tool_ref']['path'],'docker',str(config_path),str(root)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        self.launched=True
        scenario=root/'scenario'
        failure=None
        try:
            while True:
                self.wall.work_timeout()
                self.observe(root,binding)
                if scenario.exists():
                    usages=sorted(scenario.glob('usage-*.json'))
                    require(len(usages)<=10000,'RESOURCE_WALL_LIMIT')
                    if usages:
                        usage=record(usages[-1])
                        require(type(usage['cpu_us']) is int and usage['cpu_us']>=self.worker_cpu,
                                'INTERNAL_EXECUTION_ERROR')
                        self.worker_cpu=usage['cpu_us'];self.native_ns=max(self.native_ns,usage['native_wall_ns'])
                    for index in range(self.charged):
                        done=scenario/f'account-done-{index}.json'
                        if done.exists():
                            interval=record(done)
                            require(interval['account_id']==ACCOUNTS[index],'ACCOUNT_ORDER_MISMATCH')
                            self.native_ns=max(self.native_ns,interval['native_wall_ns'])
                            if index==self.charged-1:self.active_since=None
                    request=scenario/f'account-request-{self.charged}.json'
                    if self.charged<7 and request.exists():
                        require(self.receipt is not None and self.active_since is None,'OBSERVATION_MISSING')
                        value=record(request)
                        exact(value,('schema','attempt_id','account_id','packet_ordinal','prepared_input_sha256'))
                        require(value=={'schema':'polar.capability-account-request/1','attempt_id':self.aid,
                            'account_id':ACCOUNTS[self.charged],'packet_ordinal':self.charged,
                            'prepared_input_sha256':digest(prepared)},'ACCOUNT_ORDER_MISMATCH')
                        self.wall.work_timeout()
                        charge=self.store.account(self.aid,value['account_id'])
                        immutable(scenario/f'account-ack-{self.charged}.json',{'attempt_id':self.aid,
                            'account_id':value['account_id'],'request_sha256':digest(value),
                            'charge_sha256':digest(charge)})
                        (scenario/f'account-ack-{self.charged}.json').chmod(0o444)
                        self.charged+=1;self.active_since=time.monotonic_ns()
                    final=scenario/'worker-resources.json'
                    if final.exists():
                        usage=record(final)
                        self.worker_cpu=max(self.worker_cpu,usage['cpu_us'])
                        self.native_ns=max(self.native_ns,usage['native_wall_ns'])
                self.usage()
                elapsed=time.monotonic_ns()-origin
                # Conservative upper bound while worker/launcher CPU cannot yet be reaped.
                # It may stop early; it never treats a missing observation as free CPU.
                wall=time.monotonic_ns()-self.started
                upper=(wall*self.host_capacity+elapsed*self.engine['logical_cpus']+999)//1000
                require(self.prior['cpu_us']+upper<=600000000,'RESOURCE_CPU_LIMIT')
                self.wall.work_timeout()
                if self.active_since is not None:
                    require(self.native_ns+time.monotonic_ns()-self.active_since<=300000000000,
                            'NATIVE_WALL_LIMIT')
                if process.poll() is not None:break
                time.sleep(min(.05,self.wall.work_timeout()))
            # poll() already reaped the completed launcher; no extra wait.
            require(self.receipt is not None,'OBSERVATION_MISSING')
            execution=record(root/'result.json')
            require(execution['preparation']==self.receipt and execution['scenario']=='PASS'
                    and execution['scenario_started'] is True,'NATIVE_ACCOUNT_FAILURE')
            require(record(scenario/'worker-resources.json')['completed_accounts']==7
                    and self.charged==7,'NATIVE_ACCOUNT_FAILURE')
            result=record(scenario/'packet-result.json')
            require(result['schema']=='polar.capability-native-result/1'
                    and [r['account_id'] for r in result['accounts']]==list(ACCOUNTS),'NATIVE_ACCOUNT_FAILURE')
            return result
        except BaseException as exc:
            failure=exc
            raise
        finally:
            # The launcher owns its labelled container. Request its exact cleanup after
            # stopping only our own launcher process group; never prune/name-delete.
            cleanup=_cleanup_owned(process,[str(NODE),launch['tool_ref']['path'],'docker-cleanup',
                                    str(config_path),str(root)],self.wall)
            # Failure here keeps resource_finalized=False. Service retains FAILED/
            # INCOMPLETE and unknown remaining budget, with no replacement start.
            self.wall.timeout()
            self.usage(force=True)
            cleanup_files=sorted(root.glob('cleanup-*.json'))
            require(cleanup['verified'] and cleanup_files,'OBSERVATION_MISSING')
            cleanup_receipt=record(cleanup_files[-1])
            require(cleanup_receipt['launch_id']==binding['launch_id']
                    and cleanup_receipt['cleanup']['status'] in ('REMOVED','ALREADY_ABSENT'),
                    'OBSERVATION_MISSING')
            immutable(self.directory/'resource-bound.json',{'schema':'polar.capability-resource-bound/1',
                'cpu_accounting':'CONSERVATIVE_VERIFIED_CAPACITY_UPPER_BOUND',
                'charged_cpu_us':self.charge_cpu,'measured_cpu_lower_bound_us':self.measured_cpu,
                'host_logical_cpus':self.host_capacity,'engine':self.engine,
                'scope':'SUPERVISOR_ALL_HOST_DESCENDANTS_AND_ALL_CONTAINER_DESCENDANTS',
                'native_wall_ns':self.native_ns,'cleanup_receipt_sha256':sha(cleanup_files[-1].read_bytes())})
            self.wall.timeout()
            self.resource_finalized=True
