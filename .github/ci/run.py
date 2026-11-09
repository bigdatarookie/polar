"""The shared public/invented author and QA test entry, inside the locked image."""
import argparse,datetime,hashlib,signal,importlib.metadata,json,os,pathlib,platform,subprocess,sys,time,xml.etree.ElementTree as ET
p=argparse.ArgumentParser();p.add_argument('--test',action='append',default=[]);a=p.parse_args()
for x in a.test:
    if not x.startswith('tests/') or '..' in pathlib.PurePosixPath(x.split('::')[0]).parts or any(c in x for c in '\n\r\x00'):
        p.error('--test must be a repository tests/ path or node ID')
reports=pathlib.Path('/reports');reports.mkdir(exist_ok=True);start=time.monotonic();steps=[];limit=4*1024*1024
os.environ.update(PYTHONPATH='/workspace/src',POLAR_GYM_NATIVE_TEST='1')
subprocess.run(['git','-C','/tmp','config','--global','--add','safe.directory','/workspace'],check=True)
sha=subprocess.check_output(['git','-C','/workspace','rev-parse','HEAD'],text=True).strip()
versions={n:importlib.metadata.version(n) for n in ['nautilus-trader','numpy','scipy','lightgbm','pyarrow','pytest']}
def run(name,argv,timeout=1200):
    t=time.monotonic();out=reports/(name+'.log');proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    # Drain directly to a file so tracebacks survive failure. A separate file size
    # bound is enforced while draining; no test-input or artifact directories upload.
    import threading
    state={'bytes':0,'retained':0}
    def drain():
        with out.open('wb') as f:
            while True:
                b=proc.stdout.read(65536)
                if not b:break
                state['bytes']+=len(b);take=b[:max(0,limit-state['retained'])];f.write(take);state['retained']+=len(take)
    thread=threading.Thread(target=drain);thread.start();timed_out=False
    try:code=proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out=True;os.killpg(proc.pid,signal.SIGKILL);code=proc.wait()
    thread.join();step={'name':name,'argv':argv,'exit':code,'timeout':timed_out,'elapsed_seconds':round(time.monotonic()-t,3),'log_bytes':state['bytes'],'log_truncated':state['bytes']>state['retained']};steps.append(step);print(json.dumps(step),flush=True)
    if code:print(out.read_text(errors='replace')[-12000:],flush=True)
    return 1 if code else 0
status=1
try:
    assert versions['nautilus-trader']=='1.231.0'
    # Install the real project entry point against its mounted source. Dependencies
    # are already hash-locked; no resolver or network runs here.
    code=run('project-install',[sys.executable,'-m','pip','install','--no-deps','--no-build-isolation','--no-cache-dir','-e','/workspace'],120)
    if code:raise RuntimeError('PROJECT_INSTALL_FAILED')
    selected=a.test or ['tests']
    code=run('pytest',[sys.executable,'-m','pytest','-ra','-q','-p','no:cacheprovider','--basetemp=/tmp/polar-ci-tests','--junitxml=/reports/pytest.xml',*selected])
    # Selected adapter tests never silently replace the native-engine control.
    if a.test and not any(x in ['tests','tests/test_gym.py'] or x.startswith('tests/test_gym.py::test_native_invented_pair') for x in a.test):
        code=max(code,run('native',[sys.executable,'-m','pytest','-ra','-q','-p','no:cacheprovider','--junitxml=/reports/native.xml','tests/test_gym.py::test_native_invented_pair_and_fresh_replay']))
    js=sorted({str(x) for pattern in ['test_*.mjs','*.test.mjs'] for x in pathlib.Path('tests').glob(pattern)})
    if js:code=max(code,run('node',['node','--test',*js],600))
    status=code
except Exception as e:
    (reports/'entrypoint-error.log').write_text(type(e).__name__+': '+str(e)+'\n');print(type(e).__name__,str(e),flush=True)
finally:
    skipped=[]
    for x in reports.glob('*.xml'):
        try:
            for case in ET.parse(x).iter('testcase'):
                child=case.find('skipped')
                if child is not None:skipped.append({'test':case.attrib.get('classname','')+'::'+case.attrib.get('name',''),'reason':child.attrib.get('message','')})
        except ET.ParseError:pass
    result={'schema':'polar.ci-result/1','candidate_sha':sha,'platform':platform.platform(),'python':platform.python_version(),'dependencies':versions,'selection':a.test or ['tests'],'native_requested':True,'postgres_configured':bool(os.environ.get('POLAR_TEST_DATABASE_URL')),'status':'PASS' if status==0 else 'FAIL','exit':status,'steps':steps,'skipped':skipped,'duration_seconds':round(time.monotonic()-start,3),'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Public/invented technical checks; no financial or retained-data qualification'}
    (reports/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
sys.exit(status)
