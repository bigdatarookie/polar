"""Installed, fixed packet harness for the qualified observed launcher; no standalone grants."""
from pathlib import Path
import json
import os
import resource
import sys
import threading
import time

from .capability_contract import ACCOUNTS, require, canonical, decode, digest, sha, MAX_BYTES, CapabilityError
from .capability_store import immutable, record
from .capability_native import one_account


def cpu_us():
    own=resource.getrusage(resource.RUSAGE_SELF);children=resource.getrusage(resource.RUSAGE_CHILDREN)
    return int((own.ru_utime+own.ru_stime+children.ru_utime+children.ru_stime)*1000000)


def worker(input_path,expectations_path,config_path,output):
    out=Path(output);config=record(config_path);packet=record(input_path)
    require(config['schema']=='polar.capability-worker/1' and
            config['prepared_input_sha256']==digest(packet)
            and packet['schema']=='polar.capability-prepared-native/1','BINDING_MISMATCH')
    # Expectations are pinned by the launcher, never used as candidate arithmetic inputs.
    require(sha(Path(expectations_path).read_bytes())==config['expectations_sha256'],'BINDING_MISMATCH')
    require(out.is_dir() and out==out.resolve(),'BINDING_MISMATCH')
    require([a['account_id'] for a in packet['targets']['accounts']]==list(ACCOUNTS),'METHOD_JOIN_MISMATCH')
    native_ns=0;raw_count=0;results=[];stop=threading.Event()
    resource_start=0  # Include process startup/import CPU, not only the simulation body.
    def resource_record():
        immutable(out/('usage-'+str(time.monotonic_ns())+'.json'),
                  {'cpu_us':cpu_us()-resource_start,'native_wall_ns':native_ns})
    def monitor():
        while not stop.wait(.1):
            resource_record()
    watcher=threading.Thread(target=monitor,daemon=True);watcher.start()
    def callback(value):
        nonlocal native_ns,raw_count
        # Raw callbacks are physical, not semantic JSON. Retain exact native to_dict fields.
        body=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
        require(raw_count<2000 and len(body)<=1024*1024,'NATIVE_ACCOUNT_FAILURE')
        path=out/f'raw-{raw_count:06d}.json';raw_count+=1
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
        if value['callback']=='native_interval':
            native_ns+=value['elapsed_ns']
            immutable(out/('account-done-'+str(len(results))+'.json'),
                {'account_id':value['account_id'],'native_wall_ns':native_ns})
    def charge(account):
        i=len(results)
        request={'schema':'polar.capability-account-request/1','attempt_id':config['attempt_id'],
                 'account_id':account,'packet_ordinal':i,'prepared_input_sha256':digest(packet)}
        immutable(out/f'account-request-{i}.json',request)
        deadline=time.monotonic()+10
        path=out/f'account-ack-{i}.json'
        while not path.exists():
            require(time.monotonic()<deadline,'OBSERVATION_MISSING');time.sleep(.01)
        ack=record(path)
        require(ack['attempt_id']==config['attempt_id'] and ack['account_id']==account
                and ack['request_sha256']==digest(request),'BINDING_MISMATCH')
    try:
        for account,target in zip(ACCOUNTS,packet['targets']['accounts']):
            result=one_account(account,target['targets'],packet['observations'],
                               charge=charge,raw_callback=callback)
            results.append(result)
        immutable(out/'packet-result.json',{'schema':'polar.capability-native-result/1',
            'accounts':results,
            'runtime':{'nautilus_trader':__import__('importlib.metadata',fromlist=['version']).version('nautilus_trader'),
                       'python':__import__('platform').python_version(),'system':__import__('platform').system(),
                       'machine':__import__('platform').machine()},
            'forbidden_calls':{'fits':0,'predict':0,'transform':0,'feature_rebuild':0,'label_rebuild':0}})
        return 0
    except BaseException as exc:
        code=exc.code if isinstance(exc,CapabilityError) else 'NATIVE_ACCOUNT_FAILURE'
        immutable(out/'packet-failure.json',{'reason':code,'completed_accounts':len(results)})
        return 1
    finally:
        stop.set();watcher.join()
        immutable(out/'worker-resources.json',{'cpu_us':cpu_us()-resource_start,
                  'native_wall_ns':native_ns,'completed_accounts':len(results),'raw_callbacks':raw_count})


def main():
    # PR30 invokes: python HARNESS INPUT EXPECTATIONS CONFIG OUTPUT
    if len(sys.argv)==4 and sys.argv[1]=='--prepare':
        from .capability_inputs import AdmittedInputs
        from .capability_profile import targets
        config=record(sys.argv[2]);out=Path(sys.argv[3])
        admitted=AdmittedInputs(config).load()
        result={'schema':'polar.capability-prepared-native/1',
            'targets':targets(admitted['score_rows']),'scores_payload':admitted['scores_payload'],
            'observations':admitted['observations'],'lineage_refs':admitted['lineage_refs']}
        immutable(out/'prepared-native.json',result)
        return 0
    require(len(sys.argv)==5,'BINDING_MISMATCH')
    return worker(*sys.argv[1:])
