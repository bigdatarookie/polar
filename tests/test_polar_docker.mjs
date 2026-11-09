import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import {observedLaunch,observedCleanup,packagedSourceFromTar,validatePackagedSourceBinding,preparationMountFromTar} from '../scripts/polar-docker.mjs';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const IMAGE='sha256:'+'a'.repeat(64),OTHER='sha256:'+'b'.repeat(64),CID='c'.repeat(64);
function removeFixture(dir){for(const n of fs.readdirSync(dir)){const p=path.join(dir,n);if(fs.lstatSync(p).isDirectory()){fs.chmodSync(p,0o700);removeFixture(p);}}fs.rmSync(dir,{recursive:true,force:true});}
function setup(t) {
  const root=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'polar-observed-component-'));t.after(()=>removeFixture(root));
  const state=path.join(root,'engine.json'),log=path.join(root,'log.jsonl'),out=path.join(root,'launch');
  fs.writeFileSync(state,JSON.stringify({exists:false,actualImage:IMAGE}));
  const fake=`#!${process.execPath}
const fs=require('fs'),path=require('path');const state=process.env.FAKE_DOCKER_STATE,log=process.env.FAKE_DOCKER_LOG;let s=JSON.parse(fs.readFileSync(state));const a=process.argv.slice(2);fs.appendFileSync(log,JSON.stringify(a)+'\\n');const save=()=>fs.writeFileSync(state,JSON.stringify(s));const emit=x=>process.stdout.write(typeof x==='string'?x:JSON.stringify(x));
if(a[0]==='info')emit({ID:'synthetic-engine',ServerVersion:'fixture',OSType:'linux',Architecture:'arm64'});
else if(a[0]==='create'){if(s.exists&&s.rejectDuplicate)process.exit(1);s.exists=true;s.args=a;s.started=false;const observation=path.join(process.env.FAKE_LAUNCH_OUT,'observation');if(fs.existsSync(observation)){s.createDirectoryMode=(fs.statSync(observation).mode&0o7777).toString(8).padStart(4,'0');if(s.visibleConflict){fs.chmodSync(observation,0o755);try{fs.writeFileSync(path.join(observation,'preparation.json'),'foreign');}finally{fs.chmodSync(observation,parseInt(s.createDirectoryMode,8));}}}save();if(s.unknownCreate)process.exit(1);if(s.conflict)fs.writeFileSync(path.join(process.env.FAKE_LAUNCH_OUT,'preparation.json'),'foreign');emit('${CID}');}
else if(a[0]==='inspect'){if(s.failInspect)process.exit(1);const value=k=>s.args[s.args.indexOf(k)+1];const all=k=>s.args.flatMap((x,i)=>x===k?[s.args[i+1]]:[]);const labels=Object.fromEntries(all('--label').map(x=>{let n=x.indexOf('=');return[x.slice(0,n),x.slice(n+1)]}));if(s.wrongOwner)labels['polar.launch.id']='foreign';if(s.wrongLifecycle)labels['polar.lifecycle.sha256']='foreign';const imageAt=s.args.indexOf('--entrypoint')+2;const after=s.args.slice(imageAt);const runtime=after.findIndex(x=>/^sha256:/.test(x));emit([{Id:'${CID}',Image:s.actualImage,Created:'2026-11-08T00:00:00.123456789Z',Config:{Labels:labels,User:value('--user'),Entrypoint:[value('--entrypoint')],Cmd:after.slice(runtime+1),Env:[...all('--env'),'DATABASE_URL=DO_NOT_LEAK_PRIVATE_SENTINEL']},Mounts:all('--mount').map(x=>{const f=Object.fromEntries(x.split(',').map(v=>v.split('=')));return {Type:'bind',Source:f.src,Destination:f.dst,RW:!x.endsWith(',readonly')};}).map(m=>s.forceRetainedRW&&m.Destination==='/retained/original.bin'?{...m,RW:true}:m),State:{Status:s.started?'exited':'created',Running:false,ExitCode:0}}]);}
else if(a[0]==='image')emit([{Id:s.actualImage,Os:'linux',Architecture:'arm64'}]);
else if(a[0]==='cp'){if(s.copyFail)process.exit(1);if(a[1].endsWith(':/polar-launch')){if(s.mountCopyFail)process.exit(1);const data=s.mountAltered?'altered':fs.readFileSync(path.join(process.env.FAKE_LAUNCH_OUT,'observation','preparation.json'));process.stdout.write((${tar.toString()})([{name:'polar-launch/',type:'5',mode:s.mountDirMode||s.createDirectoryMode},{name:'polar-launch/preparation.json',data,mode:s.mountFileMode||'0444'}]));}else process.stdout.write(Buffer.from(s.tar,'base64'));}
else if(a[0]==='start'){const p=path.join(process.env.FAKE_LAUNCH_OUT,'preparation.json');const r=JSON.parse(fs.readFileSync(p));if(r.preparation!=='PREPARED'||r.scenario_started!==false)process.exit(9);if(s.tar){const visible=path.join(process.env.FAKE_LAUNCH_OUT,'observation','preparation.json');if(!fs.readFileSync(p).equals(fs.readFileSync(visible))||(fs.statSync(visible).mode&0o777)!==0o444||(fs.statSync(path.dirname(visible)).mode&0o777)!==0o555)process.exit(10);}s.started=true;s.starts=(s.starts||0)+1;save();fs.writeFileSync(path.join(process.env.FAKE_LAUNCH_OUT,'scenario','marker'),'one');if(s.startTimeout){setTimeout(()=>emit('late'),10000);}else if(s.startFailure)process.exit(1);else emit('scenario marker');}
else if(a[0]==='ps'){if(s.rmAttempted&&s.failAfterRmQuery)process.exit(1);emit(s.exists?'${CID}':'');}
else if(a[0]==='rm'){s.rmAttempted=true;if(!s.retainAfterRm)s.exists=false;save();emit('${CID}');}else process.exit(8);
`;
  fs.writeFileSync(path.join(root,'docker'),fake,{mode:0o755});
  const previous={PATH:process.env.PATH,FAKE_DOCKER_STATE:process.env.FAKE_DOCKER_STATE,FAKE_DOCKER_LOG:process.env.FAKE_DOCKER_LOG,FAKE_LAUNCH_OUT:process.env.FAKE_LAUNCH_OUT};
  Object.assign(process.env,{PATH:root+path.delimiter+process.env.PATH,FAKE_DOCKER_STATE:state,FAKE_DOCKER_LOG:log,FAKE_LAUNCH_OUT:out});t.after(()=>{for(const [k,v] of Object.entries(previous))if(v===undefined)delete process.env[k];else process.env[k]=v;});
  const refs={};for(const k of ['source_build','harness','input','expectations','config','review']){const p=path.join(root,k);const raw=k==='source_build'?JSON.stringify({commit:'d'.repeat(40),tree:'e'.repeat(40),image_id:IMAGE}):'synthetic '+k;fs.writeFileSync(p,raw);refs[k]={path:p,sha256:sha(raw)};}
  const spec={schema:'polar.observed-launch-config/1',launch_id:crypto.randomUUID(),candidate:{commit:'d'.repeat(40),tree:'e'.repeat(40)},image_id:IMAGE,runtime_image_id:IMAGE,platform:'linux/arm64',user:'10001',entrypoint:'/usr/local/bin/python3',environment:{PYTHONDONTWRITEBYTECODE:'1'},refs,build_fields:{commit:['commit'],tree:['tree'],image_id:['image_id']},scenario_timeout_ms:2000};
  const config=path.join(root,'launch-config.json');const write=()=>fs.writeFileSync(config,JSON.stringify(spec));write();
  return {root,out,state,log,spec,config,write,engine:patch=>fs.writeFileSync(state,JSON.stringify({...JSON.parse(fs.readFileSync(state)),...patch})),read:p=>JSON.parse(fs.readFileSync(path.join(out,p))),calls:()=>fs.existsSync(log)?fs.readFileSync(log,'utf8').trim().split('\n').map(JSON.parse):[]};
}
test('same observed container starts only after immutable receipt; reconciliation never repeats',t=>{const f=setup(t);const r=observedLaunch(f.config,f.out);assert.equal(r.scenario,'PASS');assert.equal(r.cleanup.status,'REMOVED');assert.equal(f.read('preparation.json').observed.image_id,IMAGE);assert.equal(f.read('preparation.json').scenario_started,false);const before=f.calls().length;assert.equal(observedLaunch(f.config,f.out).reconciled,true);assert.equal(f.calls().length,before);assert.equal(JSON.parse(fs.readFileSync(f.state)).starts,1);assert(!fs.readFileSync(path.join(f.out,'preparation.json'),'utf8').includes('DO_NOT_LEAK'));});
test('actual image mismatch retains observed image and never starts',t=>{const f=setup(t);f.engine({actualImage:OTHER});const r=observedLaunch(f.config,f.out);assert.equal(r.preparation_status,'NOT_PREPARED');assert.equal(r.scenario,'NOT_RUN');assert.equal(f.read('preparation.json').observed.image_id,OTHER);assert.equal(f.read('preparation.json').observed.matches.image,false);assert(!f.calls().some(a=>a[0]==='start'));assert.equal(r.cleanup.status,'REMOVED');});
test('missing expected identity publishes immutable failure with zero engine work',t=>{const f=setup(t);f.spec.image_id=null;f.write();const r=observedLaunch(f.config,f.out);assert.equal(r.reason,'IMMUTABLE_IMAGE_ID_REQUIRED');assert.equal(f.read('preparation.json').preparation,'NOT_PREPARED');assert.equal(f.calls().length,0);});
test('source/build binding mismatch fails before resource creation',t=>{const f=setup(t);f.spec.candidate.commit='f'.repeat(40);f.write();const r=observedLaunch(f.config,f.out);assert.equal(r.reason,'SOURCE_BUILD_BINDING_MISMATCH');assert.equal(f.calls().length,0);});
test('inspection failure retains resource identity; explicit cleanup is owned and idempotent',t=>{const f=setup(t);f.engine({failInspect:true});const r=observedLaunch(f.config,f.out);assert.equal(r.scenario,'NOT_RUN');assert.equal(r.cleanup.status,'UNVERIFIED_RETAINED');assert.equal(f.read('container.json').container_id,CID);assert(!f.calls().some(a=>a[0]==='start'));f.engine({failInspect:false});assert.equal(observedCleanup(f.config,f.out).cleanup.status,'REMOVED');assert.equal(observedCleanup(f.config,f.out).cleanup.status,'ALREADY_ABSENT');});
test('receipt conflict cannot be overwritten and cannot start scenario',t=>{const f=setup(t);f.engine({conflict:true});const r=observedLaunch(f.config,f.out);assert.equal(r.preparation_status,'NOT_PREPARED');assert.equal(fs.readFileSync(path.join(f.out,'preparation.json'),'utf8'),'foreign');assert(!f.calls().some(a=>a[0]==='start'));});
test('foreign root conflict has no writes or engine calls',t=>{const f=setup(t);fs.mkdirSync(f.out);fs.writeFileSync(path.join(f.out,'foreign'),'keep');assert.equal(observedLaunch(f.config,f.out).preparation_status,'NOT_PREPARED');assert.deepEqual(fs.readdirSync(f.out),['foreign']);assert.equal(f.calls().length,0);});
test('secret environment is rejected without persisting its value or hash',t=>{const f=setup(t);f.spec.environment.DATABASE_URL='SECRET_SENTINEL';f.write();const r=observedLaunch(f.config,f.out);assert.equal(r.reason,'UNSAFE_ENVIRONMENT');const contents=fs.readdirSync(f.out).map(n=>fs.readFileSync(path.join(f.out,n),'utf8')).join('');assert(!contents.includes('SECRET_SENTINEL'));assert(!contents.includes(sha('SECRET_SENTINEL')));assert.equal(f.calls().length,0);});
test('changed reference bytes fail closed and preserve caller inputs',t=>{const f=setup(t);fs.writeFileSync(f.spec.refs.harness.path,'changed');const r=observedLaunch(f.config,f.out);assert.equal(r.reason,'REFERENCE_HASH_MISMATCH');assert.equal(fs.readFileSync(f.spec.refs.harness.path,'utf8'),'changed');assert.equal(f.calls().length,0);});
test('unknown create outcome retains name and is resolved only through owned cleanup',t=>{const f=setup(t);f.engine({unknownCreate:true});const r=observedLaunch(f.config,f.out);assert.equal(r.cleanup.status,'UNKNOWN_CREATE_OUTCOME');assert.equal(r.scenario,'NOT_RUN');assert(!f.calls().some(a=>a[0]==='start'));assert.equal(observedCleanup(f.config,f.out).cleanup.status,'REMOVED');});
test('cleanup does not require original harness to survive',t=>{const f=setup(t);f.engine({failInspect:true});observedLaunch(f.config,f.out);fs.unlinkSync(f.spec.refs.harness.path);f.engine({failInspect:false});assert.equal(observedCleanup(f.config,f.out).cleanup.status,'REMOVED');});
test('same launch ID in a different root cannot adopt or remove the first resource',t=>{const f=setup(t);f.engine({failInspect:true,rejectDuplicate:true});observedLaunch(f.config,f.out);f.engine({failInspect:false});const second=path.join(f.root,'other');const r=observedLaunch(f.config,second);assert.equal(r.cleanup.status,'UNKNOWN_CREATE_OUTCOME');assert.equal(observedCleanup(f.config,second).cleanup.status,'UNVERIFIED_RETAINED');assert.equal(JSON.parse(fs.readFileSync(f.state)).exists,true);assert.equal(observedCleanup(f.config,f.out).cleanup.status,'REMOVED');});

function tar(entries) {
  const parts=[];
  for(const {name,data='',type='0',mode='0644'} of entries){const b=Buffer.from(data),h=Buffer.alloc(512);h.write(name,0,100);h.write(mode.padStart(7,'0')+'\0',100);h.write('0000000\0',108);h.write('0000000\0',116);h.write(b.length.toString(8).padStart(11,'0')+'\0',124);h.write('00000000000\0',136);h.fill(32,148,156);h.write(type,156);h.write('ustar\0',257);let sum=0;for(const x of h)sum+=x;h.write(sum.toString(8).padStart(6,'0')+'\0 ',148);parts.push(h,b,Buffer.alloc((512-b.length%512)%512));}parts.push(Buffer.alloc(1024));return Buffer.concat(parts);
}
const code='invented source\n',sourceName='/app/src/polar/example.py';
const sourceFiles=()=>({[sourceName]:{sha256:sha(code),bytes:Buffer.byteLength(code)}});
function sourceFixture(t,entries=[{name:'polar/example.py',data:code}]) {
  const f=setup(t);f.spec.schema='polar.observed-launch-config/2';
  const build=JSON.parse(fs.readFileSync(f.spec.refs.source_build.path));build.source_files=sourceFiles();const raw=JSON.stringify(build);fs.writeFileSync(f.spec.refs.source_build.path,raw);f.spec.refs.source_build.sha256=sha(raw);f.write();f.engine({tar:tar(entries).toString('base64')});return f;
}
function retainedFixture(t) {
  const f=sourceFixture(t);f.spec.schema='polar.observed-launch-config/3';
  const artifacts=path.join(f.root,'artifacts');fs.mkdirSync(artifacts);fs.chmodSync(artifacts,0o777);
  fs.writeFileSync(path.join(artifacts,'family-ledger'),'preserve across launches');
  const st=fs.statSync(artifacts,{bigint:true}),input=path.join(f.root,'retained-input');fs.writeFileSync(input,'invented retained bytes');
  f.spec.retained={artifact_root:{path:artifacts,device:st.dev.toString(),inode:st.ino.toString()},read_only:[
    {path:input,target:'/retained/original.bin',sha256:sha('invented retained bytes'),bytes:23},
    {path:f.spec.refs.input.path,target:f.spec.refs.input.path,sha256:f.spec.refs.input.sha256,bytes:fs.statSync(f.spec.refs.input.path).size}
  ]};f.write();return {...f,artifacts,input};
}
test('config3 binds retained files and persistent ledger in the same observed container',t=>{
  const f=retainedFixture(t),result=observedLaunch(f.config,f.out);assert.equal(result.scenario,'PASS');
  const prep=f.read('preparation.json');assert.equal(prep.retained_binding.observation.all_mounts_exact,true);
  assert.equal(prep.retained_binding.read_only_files.length,2);
  const mounts=f.calls().find(a=>a[0]==='create').filter(a=>a.startsWith('type=bind'));
  assert.equal(mounts.filter(m=>m.includes('dst='+f.spec.refs.input.path+',')).length,1);
  assert(mounts.some(m=>m.endsWith('dst=/retained/original.bin,readonly')));
  assert(mounts.some(m=>m.endsWith('dst=/polar-artifacts')));
  assert.equal(fs.readFileSync(path.join(f.artifacts,'family-ledger'),'utf8'),'preserve across launches');
  const prior=f.calls().length;assert.equal(observedLaunch(f.config,f.out).reconciled,true);assert.equal(f.calls().length,prior);
  assert.equal(observedCleanup(f.config,f.out).cleanup.status,'ALREADY_ABSENT');
  assert.equal(fs.readFileSync(path.join(f.artifacts,'family-ledger'),'utf8'),'preserve across launches');
});
test('fresh physical launch reuses exactly the same persistent root without resetting it',t=>{
  const f=retainedFixture(t);assert.equal(observedLaunch(f.config,f.out).scenario,'PASS');
  const other=path.join(f.root,'second-launch');f.spec.launch_id=crypto.randomUUID();f.write();process.env.FAKE_LAUNCH_OUT=other;
  assert.equal(observedLaunch(f.config,other).scenario,'PASS');
  assert.equal(JSON.parse(fs.readFileSync(f.state)).starts,2);
  assert.equal(fs.readFileSync(path.join(f.artifacts,'family-ledger'),'utf8'),'preserve across launches');
});
test('changed retained bytes fail before engine work and preserve the family ledger',t=>{
  const f=retainedFixture(t);fs.writeFileSync(f.input,'wrong but same-size txt');
  const result=observedLaunch(f.config,f.out);assert.equal(result.preparation_status,'NOT_PREPARED');
  assert.equal(result.scenario,'NOT_RUN');assert.equal(f.calls().length,0);
  assert.equal(fs.readFileSync(path.join(f.artifacts,'family-ledger'),'utf8'),'preserve across launches');
});
test('observed writable retained input fails before start and only exact container is cleaned',t=>{
  const f=retainedFixture(t);f.engine({forceRetainedRW:true});const result=observedLaunch(f.config,f.out);
  assert.equal(result.reason,'RETAINED_MOUNT_MISMATCH');assert.equal(result.scenario,'NOT_RUN');
  assert(!f.calls().some(a=>a[0]==='start'));assert.equal(result.cleanup.status,'REMOVED');
  assert(fs.existsSync(path.join(f.artifacts,'family-ledger')));
});
test('config3 seals all reference files readably even under a restrictive umask',t=>{
  const f=retainedFixture(t),previous=process.umask(0o077);let result;
  try{result=observedLaunch(f.config,f.out);}finally{process.umask(previous);}
  assert.equal(result.scenario,'PASS');
  for(const name of Object.keys(f.spec.refs))assert.equal(fs.statSync(path.join(f.out,'bindings',name)).mode&0o777,0o444);
});
test('packaged source from same stopped container and identical readable receipt precede start',t=>{const f=sourceFixture(t);const result=observedLaunch(f.config,f.out);assert.equal(result.scenario,'PASS');const p=f.read('preparation.json');assert.equal(p.source_binding.packaged_source_independently_observed,true);assert.equal(p.source_binding.observed_container_id,CID);assert.deepEqual(p.source_binding.observed_files,sourceFiles());const calls=f.calls();assert.deepEqual(calls.find(x=>x[0]==='cp'),['cp',CID+':/app/src/polar','-']);assert(calls.findIndex(x=>x[0]==='cp')<calls.findIndex(x=>x[0]==='start'));assert(calls.find(x=>x[0]==='create').some(x=>x.endsWith('dst=/polar-launch,readonly')));assert.equal(observedLaunch(f.config,f.out).reconciled,true);assert.equal(observedCleanup(f.config,f.out).cleanup.status,'ALREADY_ABSENT');});
for(const [label,entries,reason] of [
 ['changed',[{name:'polar/example.py',data:'changed'}],'SOURCE_HASH_MISMATCH'],
 ['extra',[{name:'polar/example.py',data:code},{name:'polar/extra.sql',data:'x'}],'SOURCE_FILE_SET_MISMATCH'],
 ['missing',[],'SOURCE_FILE_SET_MISMATCH'],
 ['symlink',[{name:'polar/example.py',type:'2'}],'SOURCE_NONREGULAR'],
 ['hardlink',[{name:'polar/example.py',type:'1'}],'SOURCE_NONREGULAR'],
 ['fifo',[{name:'polar/example.py',type:'6'}],'SOURCE_NONREGULAR'],
 ['traversal',[{name:'polar/../example.py',data:code}],'SOURCE_PATH_INVALID'],
 ['absolute',[{name:'/polar/example.py',data:code}],'SOURCE_PATH_INVALID'],
 ['duplicate',[{name:'polar/example.py',data:code},{name:'polar/example.py',data:code}],'SOURCE_PATH_INVALID'],
])test('source '+label+' fails before start with exact cleanup',t=>{const f=sourceFixture(t,entries);const r=observedLaunch(f.config,f.out);assert.equal(r.reason,reason);assert.equal(r.scenario,'NOT_RUN');assert(!f.calls().some(a=>a[0]==='start'));assert.equal(r.cleanup.status,'REMOVED');});
test('copy failure cannot start and source observation remains false',t=>{const f=sourceFixture(t);f.engine({copyFail:true});const r=observedLaunch(f.config,f.out);assert.equal(r.reason,'SOURCE_COPY_FAILED');assert.equal(f.read('preparation.json').source_binding.packaged_source_independently_observed,false);assert(!f.calls().some(a=>a[0]==='start'));});
for(const dest of ['/app','/app/src/polar/injected.py','/polar-launch/preparation.json','/polar-output'])test('reference overlap rejected: '+dest,()=>{assert.throws(()=>validatePackagedSourceBinding(sourceFiles(),{input:{path:dest}},'/usr/local/bin/python'),/SOURCE_REFERENCE_OVERLAP/);});
test('source map count/size limits and source entrypoint fail closed',()=>{assert.throws(()=>validatePackagedSourceBinding({}, {}, '/bin/python'),/SOURCE_MAP_BOUND/);const many=Object.fromEntries(Array.from({length:501},(_,i)=>['/app/src/polar/x'+i+'.py',{sha256:sha(''),bytes:0}]));assert.throws(()=>validatePackagedSourceBinding(many,{},'/bin/python'),/SOURCE_MAP_BOUND/);assert.throws(()=>validatePackagedSourceBinding({[sourceName]:{sha256:sha(''),bytes:1048577}},{},'/bin/python'),/SOURCE_FILE_BOUND/);assert.throws(()=>validatePackagedSourceBinding(sourceFiles(),{},sourceName),/SOURCE_ENTRYPOINT_OVERLAP/);});
test('PAX path preserves exact identity and cannot escape source root',()=>{function paxPath(value){const body='path='+value+'\n';let count=Buffer.byteLength(body)+3;while(count!==Buffer.byteLength(body)+String(count).length+1)count=Buffer.byteLength(body)+String(count).length+1;return count+' '+body;}const archive=tar([{name:'PaxHeaders/path',type:'x',data:paxPath('polar/example.py')},{name:'polar/placeholder',data:code}]);assert.deepEqual(packagedSourceFromTar(archive,sourceFiles()),sourceFiles());assert.throws(()=>packagedSourceFromTar(tar([{name:'PaxHeaders/path',type:'x',data:paxPath('../bad.py')},{name:'polar/example.py',data:code}]),sourceFiles()),/SOURCE_PATH_INVALID/);});
test('source map bounds and unsafe paths reject without engine calls',t=>{const f=sourceFixture(t);const raw=JSON.stringify({commit:f.spec.candidate.commit,tree:f.spec.candidate.tree,image_id:IMAGE,source_files:{'/app/src/polar/../bad.py':{sha256:sha(code),bytes:1}}});fs.writeFileSync(f.spec.refs.source_build.path,raw);f.spec.refs.source_build.sha256=sha(raw);f.write();assert.equal(observedLaunch(f.config,f.out).reason,'SOURCE_PATH_INVALID');assert.equal(f.calls().length,0);});
test('tar checksum and truncation reject rather than hash ambiguous bytes',()=>{const raw=tar([{name:'polar/example.py',data:code}]);raw[0]^=1;assert.throws(()=>packagedSourceFromTar(raw,sourceFiles()),/SOURCE_ARCHIVE_INVALID/);assert.throws(()=>packagedSourceFromTar(Buffer.alloc(7),sourceFiles()),/SOURCE_FILE_SET_MISMATCH/);});

test('receipt mount records directory and file modes separately from archive metadata',()=>{
  const data='invented receipt';const value=preparationMountFromTar(tar([
    {name:'polar-launch/',type:'5',mode:'0555'},
    {name:'polar-launch/preparation.json',data,mode:'0444'}]),sha(data));
  assert.deepEqual(value.matches,{directory_mode:true,file_mode:true,content:true});
  assert.equal(value.directory.mode,'0555');assert.equal(value.file.mode,'0444');
  assert.equal(value.observation,'STOPPED_CONTAINER_ARCHIVE_METADATA');
});
for(const [field,value,reason,failed] of [
  ['mountDirMode','0755','PREPARATION_DIRECTORY_MODE_MISMATCH','directory_mode'],
  ['mountFileMode','0644','PREPARATION_FILE_MODE_MISMATCH','file_mode'],
  ['mountAltered',true,'PREPARATION_MOUNT_CONTENT_MISMATCH','content']
])test('container receipt '+failed+' mismatch is retained and blocks start',t=>{
  const f=sourceFixture(t);f.engine({[field]:value});const result=observedLaunch(f.config,f.out);
  assert.equal(result.reason,reason);assert.equal(result.preparation_status,'NOT_PREPARED');
  assert.equal(result.scenario,'NOT_RUN');assert.equal(result.scenario_started,false);
  assert.equal(result.prestart_receipt_mount.matches[failed],false);
  assert.equal(result.prestart_receipt_mount.observed_container_id,CID);
  assert(!f.calls().some(a=>a[0]==='start'));assert.equal(result.cleanup.status,'REMOVED');
});
test('mount root is sealed before create even under restrictive umask',t=>{
  const f=sourceFixture(t),previous=process.umask(0o077);
  let result;try{result=observedLaunch(f.config,f.out);}finally{process.umask(previous);}
  const state=JSON.parse(fs.readFileSync(f.state));
  assert.equal(state.createDirectoryMode,'0555');
  assert.equal(result.prestart_receipt_mount.directory.mode,'0555');
  assert.equal(result.scenario,'PASS');assert.equal(state.starts,1);
  assert.equal(fs.statSync(path.join(f.out,'observation')).mode&0o7777,0o555);
});
test('publication conflict restores sealed mount root and cannot start',t=>{
  const f=sourceFixture(t);f.engine({visibleConflict:true});
  const result=observedLaunch(f.config,f.out);
  assert.equal(result.preparation_status,'NOT_PREPARED');assert.equal(result.scenario,'NOT_RUN');
  assert.equal(fs.statSync(path.join(f.out,'observation')).mode&0o7777,0o555);
  assert.equal(fs.readFileSync(path.join(f.out,'observation','preparation.json'),'utf8'),'foreign');
  assert(!f.calls().some(a=>a[0]==='start'));assert.equal(result.cleanup.status,'REMOVED');
});
test('receipt copy failure cannot start a consumer',t=>{
  const f=sourceFixture(t);f.engine({mountCopyFail:true});const result=observedLaunch(f.config,f.out);
  assert.equal(result.reason,'PREPARATION_MOUNT_COPY_FAILED');assert.equal(result.scenario,'NOT_RUN');
  assert(!f.calls().some(a=>a[0]==='start'));assert.equal(result.cleanup.status,'REMOVED');
});
test('receipt mount links and extra members are rejected',()=>{
  assert.throws(()=>preparationMountFromTar(tar([{name:'polar-launch/',type:'5',mode:'0555'},
    {name:'polar-launch/preparation.json',type:'2',mode:'0444'}]),sha('')),/PREPARATION_MOUNT_ARCHIVE_INVALID/);
  assert.throws(()=>preparationMountFromTar(tar([{name:'polar-launch/',type:'5',mode:'0555'},
    {name:'polar-launch/preparation.json',data:'{}',mode:'0444'},
    {name:'polar-launch/extra',data:'x'}]),sha('{}')),/PREPARATION_MOUNT_FILE_SET/);
});

test('cleanup refuses rm success when exact ID remains',t=>{
  const f=setup(t);f.engine({retainAfterRm:true});const r=observedLaunch(f.config,f.out);
  assert.equal(r.scenario,'PASS');assert.equal(r.cleanup.status,'UNVERIFIED_RETAINED');
  assert.equal(r.cleanup.reason,'CONTAINER_STILL_PRESENT_AFTER_REMOVE');
  assert.equal(r.cleanup.recovery.owner,'CALLER_OR_NAMED_RECOVERY');
  assert.equal(JSON.parse(fs.readFileSync(f.state)).exists,true);
  assert.equal(observedCleanup(f.config,f.out).cleanup.status,'UNVERIFIED_RETAINED');
});
test('cleanup does not claim absence when post-rm query fails',t=>{
  const f=setup(t);f.engine({failAfterRmQuery:true});const r=observedLaunch(f.config,f.out);
  assert.equal(r.cleanup.status,'UNVERIFIED_RETAINED');
  assert.equal(r.cleanup.reason,'CLEANUP_IDENTITY_OR_ENGINE_ERROR');
});
test('cleanup refuses foreign owner or lifecycle labels before deletion',t=>{
  const f=setup(t);f.engine({wrongOwner:true});const r=observedLaunch(f.config,f.out);
  assert.equal(r.cleanup.status,'UNVERIFIED_RETAINED');assert(!f.calls().some(a=>a[0]==='rm'));
  f.engine({wrongOwner:false,wrongLifecycle:true});
  assert.equal(observedCleanup(f.config,f.out).cleanup.status,'UNVERIFIED_RETAINED');
  assert(!f.calls().some(a=>a[0]==='rm'));
});
function explicitLifecycle(f,retained=false) {
  f.spec.lifecycle={project:'polar',task:'qitem-invented-lifecycle',attempt:f.spec.launch_id,
    owner:'platform-qa@polar-rig',cleanup_owner:'platform-sre@polar-rig',
    terminal:retained?'RETAINED_EXCEPTION':'TRANSIENT',intended_lifetime_ms:60000,
    retention:retained?{reason:'invented rollback control',release_condition:'owner releases fixture',expires_at:null}:null};
  f.write();
}
test('lifecycle metadata is config-bound and observed in created labels and receipt',t=>{
  const f=setup(t);explicitLifecycle(f);const r=observedLaunch(f.config,f.out);
  assert.equal(r.cleanup.status,'REMOVED');
  const resources=f.read('resources.json'),prep=f.read('preparation.json');
  assert.equal(resources.lifecycle.task,'qitem-invented-lifecycle');
  assert.equal(prep.lifecycle.cleanup_owner,'platform-sre@polar-rig');
  assert(Number.isFinite(Date.parse(resources.intended_cleanup_by)));
  const create=f.calls().find(a=>a[0]==='create');
  assert(create.includes('polar.resource.owner=platform-qa@polar-rig'));
  assert(create.includes('polar.resource.cleanup_owner=platform-sre@polar-rig'));
  assert(r.cleanup.absence_observed_at);
});
test('lifecycle malformed metadata creates no resource and retains validation failure',t=>{
  const f=setup(t);explicitLifecycle(f);f.spec.lifecycle.owner='bad\nowner';f.write();
  const r=observedLaunch(f.config,f.out);
  assert.equal(r.reason,'INVALID_LIFECYCLE');assert(!f.calls().some(a=>a[0]==='create'));
});
test('retention exception names owner/reason/release and is never claimed removed',t=>{
  const f=setup(t);explicitLifecycle(f,true);const r=observedLaunch(f.config,f.out);
  assert.equal(r.cleanup.status,'RETAINED_EXCEPTION');
  assert.equal(r.cleanup.recovery.owner,'platform-sre@polar-rig');
  assert.equal(r.cleanup.lifecycle.retention.release_condition,'owner releases fixture');
  assert(!f.calls().some(a=>a[0]==='rm'));
  assert.equal(observedCleanup(f.config,f.out).cleanup.status,'RETAINED_EXCEPTION');
});
test('retention without release condition or expiry fails before create',t=>{
  const f=setup(t);explicitLifecycle(f,true);f.spec.lifecycle.retention.release_condition=null;f.write();
  const r=observedLaunch(f.config,f.out);assert.equal(r.reason,'INVALID_LIFECYCLE');
  assert(!f.calls().some(a=>a[0]==='create'));
});
test('scenario failure still reaches exact absence verification',t=>{
  const f=setup(t);f.engine({startFailure:true});
  const r=observedLaunch(f.config,f.out);
  assert.equal(r.scenario,'FAIL');assert.equal(r.cleanup.status,'REMOVED');
});
test('bounded scenario command timeout reaches exact owned cleanup',t=>{
  const f=setup(t);f.spec.scenario_timeout_ms=100;f.write();f.engine({startTimeout:true});
  const r=observedLaunch(f.config,f.out);
  assert.equal(r.scenario,'FAIL');assert.equal(r.command_error,'BOUNDED_SCENARIO_COMMAND_ERROR');
  assert.equal(r.cleanup.status,'REMOVED');
});
test('new lifecycle marker cannot be silently downgraded to legacy recovery',t=>{
  const f=setup(t);f.engine({failInspect:true});observedLaunch(f.config,f.out);
  const resources=f.read('resources.json');delete resources.lifecycle;
  fs.writeFileSync(path.join(f.out,'resources.json'),JSON.stringify(resources));f.engine({failInspect:false});
  const before=f.calls().filter(a=>a[0]==='rm').length;
  assert.equal(observedCleanup(f.config,f.out).cleanup.status,'UNVERIFIED_RETAINED');
  assert.equal(f.calls().filter(a=>a[0]==='rm').length,before);
});

test('legacy two-label resources remain recoverable without lifecycle reinterpretation',t=>{
  const f=setup(t);f.engine({failInspect:true});observedLaunch(f.config,f.out);
  const binding=f.read('binding.json'),resources=f.read('resources.json');
  delete binding.lifecycle_required;delete resources.lifecycle;delete resources.intended_cleanup_by;
  fs.writeFileSync(path.join(f.out,'binding.json'),JSON.stringify(binding));
  fs.writeFileSync(path.join(f.out,'resources.json'),JSON.stringify(resources));
  const state=JSON.parse(fs.readFileSync(f.state));state.failInspect=false;
  state.args=state.args.filter((arg,i,args)=>!(arg==='--label'&&args[i+1]?.startsWith('polar.resource.'))
    &&!(arg==='--label'&&args[i+1]?.startsWith('polar.lifecycle.'))
    &&!arg.startsWith('polar.resource.')&&!arg.startsWith('polar.lifecycle.'));
  fs.writeFileSync(f.state,JSON.stringify(state));
  assert.equal(observedCleanup(f.config,f.out).cleanup.status,'REMOVED');
});
test('CLI operation cannot return success when cleanup residual remains',t=>{
  const f=setup(t);f.engine({retainAfterRm:true});
  const run=cp.spawnSync(process.execPath,[new URL('../scripts/polar-local.mjs',import.meta.url).pathname,
    'docker',f.config,f.out],{encoding:'utf8',timeout:15000});
  assert.equal(run.status,1);const result=JSON.parse(run.stdout);
  assert.equal(result.scenario,'PASS');assert.equal(result.cleanup.status,'UNVERIFIED_RETAINED');
});
