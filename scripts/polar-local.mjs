#!/usr/bin/env node
// Polar local tooling: independent QA acceptance is recorded outside this CLI.
// No compute-slot/CPU/RAM quota checks, package download or owner browser reuse.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import cp from 'node:child_process';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';

export const VERSION='polar-local/1.4.2';
const PW=process.env.POLAR_PLAYWRIGHT_MODULE||'/Users/garry/.npm/_npx/31e32ef8478fbf80/node_modules/playwright/index.js';
const CHROME=process.env.POLAR_BROWSER_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function command(argv,timeout=5000) {
  const r=cp.spawnSync(argv[0],argv.slice(1),{encoding:'utf8',timeout,maxBuffer:1024*1024});
  return {code:r.status,signal:r.signal,error:r.error?'BOUNDED_COMMAND_ERROR':null,stdout:r.stdout||'',stderrBytes:Buffer.byteLength(r.stderr||'')};
}
function required(argv,timeout=5000) {const r=command(argv,timeout);assert.equal(r.code,0,'COMMAND_FAILED');return r.stdout;}
function receipt(file,body) {fs.writeFileSync(file,JSON.stringify(body,null,2)+'\n',{flag:'wx',mode:0o600});}
function privateDir(dir) {fs.mkdirSync(dir,{mode:0o700});assert.equal(fs.realpathSync(dir),path.resolve(dir));return dir;}
export function timestampNs(value) {
  const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  assert(m,'INVALID_TIMESTAMP');
  const [y,mo,d,h,mi,s]=m.slice(1,7).map(Number);
  const leap=y%4===0&&(y%100!==0||y%400===0);
  assert(y>=1&&mo>=1&&mo<=12&&d>=1&&d<=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31][mo-1]);
  assert(h<=23&&mi<=59&&s<=59);
  if(m[8]!=='Z')assert(Number(m[8].slice(1,3))<=23&&Number(m[8].slice(4))<=59);
  if(y===1&&mo===1&&d===1&&h===0&&mi===0&&s===0&&!(m[7]||'').replaceAll('0','')&&['Z','+00:00'].includes(m[8]))return null;
  const ms=Date.parse(value.slice(0,19)+m[8]);assert(Number.isFinite(ms));
  return BigInt(ms)*1000000n+BigInt((m[7]||'').padEnd(9,'0'));
}
export function timestampCases() {
  const t='2026-11-07T12:31:31';
  assert.equal(timestampNs(t+'.123456789Z')-timestampNs(t+'.123456788Z'),1n);
  assert.equal(timestampNs(t+'.123456789Z'),timestampNs(t+'.123456789+00:00'));
  assert.equal(timestampNs('2026-11-07T14:31:31.123456789+02:00'),timestampNs(t+'.123456789Z'));
  assert.equal(timestampNs(t+'Z'),timestampNs(t+'.000000000Z'));
  assert.equal(timestampNs('0001-01-01T00:00:00Z'),null);
  for(const bad of [t+'.1234567890Z','2026-02-30T00:00:00Z',t,t+'+24:00','2026-11-07T24:00:00Z','2026-11-07T12:60:00Z'])assert.throws(()=>timestampNs(bad));
  return {status:'PASS',cases:11,precision:'integer nanoseconds; zero Docker timestamp=null'};
}
export function host() {
  return {utc:new Date().toISOString(),totalMemory:os.totalmem(),freeMemory:os.freemem(),logicalCPUs:os.cpus().length,load:os.loadavg(),
    memoryPressure:command(['memory_pressure','-Q']).stdout,filesystem:command(['df','-k',os.tmpdir()]).stdout,
    note:'Observed availability, no project CPU/RAM/browser cap or exact global attribution.'};
}
function processes() {
  const result=command(['ps','-axo','pid=,ppid=,rss=,comm=']);
  assert.equal(result.code,0,'OWNED_PROCESS_OBSERVATION_UNAVAILABLE');
  return result.stdout.split('\n').flatMap(line=>{const m=/^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.+)$/.exec(line);return m?[{pid:+m[1],ppid:+m[2],rss:+m[3]*1024,comm:m[4]}]:[];});
}
function descendants(rows) {
  const pids=new Set([process.pid]);let changed=true;
  while(changed){changed=false;for(const r of rows)if(pids.has(r.ppid)&&!pids.has(r.pid)){pids.add(r.pid);changed=true;}}
  return rows.filter(r=>pids.has(r.pid));
}
export async function doctor(containers=[]) {
  const module=await import(pathToFileURL(PW).href);
  assert.equal(typeof module.default?.chromium?.launchPersistentContext,'function','PLAYWRIGHT_DEFAULT_IMPORT_FAILED');
  const info={version:VERSION,host:host(),node:{path:process.execPath,version:process.version},playwright:{path:PW,version:JSON.parse(fs.readFileSync(path.join(path.dirname(PW),'package.json'))).version,entrySha256:sha(fs.readFileSync(PW))},browser:{path:CHROME,size:fs.statSync(CHROME).size,mtime:fs.statSync(CHROME).mtime.toISOString()},timestamps:timestampCases(),docker:[]};
  for(const id of containers) {
    assert(/^(?:[a-f0-9]{64}|polar-[a-zA-Z0-9_-]{1,100})$/.test(id),'INVALID_CONTAINER');
    const row=JSON.parse(required(['docker','inspect',id]))[0];
    assert.equal(row.Config.Labels?.['com.docker.compose.project'],'polar','UNOWNED_DOCKER_TARGET');
    const item={id:row.Id,image:row.Image,state:row.State.Status,startedNs:String(timestampNs(row.State.StartedAt)),finishedNs:String(timestampNs(row.State.FinishedAt))};
    if(row.State.Running) {
      const truth=command(['docker','exec',row.Id,'timeout','-s','TERM','-k','1','1','true'],4000);
      const started=Date.now();const expiry=command(['docker','exec',row.Id,'timeout','-s','TERM','-k','1','1','sleep','5'],4000);
      item.timeout={trueExit:truth.code,expiryExit:expiry.code,expiryWallMs:Date.now()-started,flags:'-s TERM -k 1 1'};
      assert.equal(truth.code,0,'TIMEOUT_SHORTFLAGS_FAILED');
      assert([124,143].includes(expiry.code)&&item.timeout.expiryWallMs<3500,'TIMEOUT_EXPIRY_FAILED');
    } else item.timeout={status:'NOT_RUN',reason:'INTENTIONALLY_STOPPED_TARGET'};
    info.docker.push(item);
  }
  info.environmentFingerprint=sha(JSON.stringify({node:info.node,playwright:info.playwright,browser:info.browser,docker:info.docker.map(x=>x.image)}));
  return info;
}
export function exportSource(repo,commit,tree,out) {
  assert(/^[a-f0-9]{40}$/.test(commit)&&/^[a-f0-9]{40}$/.test(tree));
  assert.equal(required(['git','-C',repo,'rev-parse',commit+'^{tree}']).trim(),tree);
  const entries=required(['git','-C',repo,'ls-tree','-rz',commit]).split('\0').filter(Boolean);
  privateDir(out);let bytes=0;const files=[];
  for(const entry of entries) {
    const [meta,name]=entry.split('\t');if(!(name.startsWith('src/')||['Dockerfile','pyproject.toml','requirements.lock','compose.yaml'].includes(name)))continue;
    const [mode,kind,blob]=meta.split(' ');
    assert(['100644','100755'].includes(mode)&&kind==='blob'&&!name.includes('..')&&!name.includes('__pycache__')&&!/\.py[co]$/.test(name));
    const raw=cp.execFileSync('git',['-C',repo,'cat-file','blob',blob],{timeout:5000,maxBuffer:16*1024*1024});
    assert.equal(crypto.createHash('sha1').update(Buffer.concat([Buffer.from('blob '+raw.length+'\0'),raw])).digest('hex'),blob);
    bytes+=raw.length;assert(bytes<16*1024*1024,'SOURCE_OPERATION_SIZE_BOUND');
    const dest=path.join(out,name);fs.mkdirSync(path.dirname(dest),{recursive:true,mode:0o700});fs.writeFileSync(dest,raw,{flag:'wx',mode:0o444});
    files.push({path:name,blob,bytes:raw.length,sha256:sha(raw)});
  }
  const manifest={commit,tree,files,bytes};const raw=JSON.stringify(manifest);fs.writeFileSync(path.join(out,'SOURCE-MANIFEST.json'),raw,{flag:'wx',mode:0o444});
  function seal(dir){for(const n of fs.readdirSync(dir)){const p=path.join(dir,n);if(fs.lstatSync(p).isDirectory())seal(p);}fs.chmodSync(dir,0o555);}seal(out);
  return {path:out,bytes:bytes+Buffer.byteLength(raw),manifestSha256:sha(raw),commit,tree};
}
export async function withPage(out,url,actions,{actionTimeoutMs=120000}={}) {
  assert(Number.isInteger(actionTimeoutMs)&&actionTimeoutMs>=1000&&actionTimeoutMs<=600000);
  assert(actions===undefined||typeof actions==='function');
  if(url){const u=new URL(url);assert(u.protocol==='file:'||(['http:','https:'].includes(u.protocol)&&['127.0.0.1','localhost','[::1]'].includes(u.hostname)),'LOCAL_PAGE_ONLY');}
  privateDir(out);const start=Date.now(),cpuStart=process.cpuUsage();let context,peak=process.memoryUsage().rss,seen=new Map(),timer,closePromise,result={version:VERSION,start:new Date().toISOString(),host:host(),status:'FAIL'};
  const closeContext=()=>closePromise||(closePromise=context.close());
  const profile=path.join(out,'owned-profile');fs.mkdirSync(profile,{mode:0o700});
  const fixture=path.join(out,'smoke.html');
  fs.writeFileSync(fixture,'<!doctype html><title>Polar launcher smoke</title><button onclick="document.documentElement.dataset.verified=\'true\'">Check launcher</button>',{mode:0o600});
  const target=url||pathToFileURL(fixture).href;const parsed=new URL(target);
  assert(parsed.protocol==='file:'||(['http:','https:'].includes(parsed.protocol)&&['127.0.0.1','localhost','[::1]'].includes(parsed.hostname)),'LOCAL_PAGE_ONLY');
  timer=setInterval(()=>{try{const own=descendants(processes());peak=Math.max(peak,own.reduce((s,r)=>s+r.rss,0));for(const r of own)if(/Chrome|Chromium/.test(r.comm))seen.set(r.pid,r);}catch{}},250);
  try {
    const pw=(await import(pathToFileURL(PW).href)).default;
    context=await pw.chromium.launchPersistentContext(profile,{headless:true,executablePath:CHROME,args:['--disable-background-networking'],viewport:{width:1440,height:900},reducedMotion:'reduce',timeout:30000});
    const page=context.pages()[0]||await context.newPage();assert.equal(context.pages().length,1);
    await page.goto(target,{waitUntil:'domcontentloaded',timeout:15000});
    if(!url&&!actions){await page.getByRole('button',{name:'Check launcher'}).click({timeout:5000});await page.waitForFunction(()=>document.documentElement.dataset.verified==='true',null,{timeout:5000});}
    if(actions){
      const cancellation=new AbortController();let deadline;
      const stateFile=path.join(out,'action-state.json');
      const actionState=state=>fs.writeFileSync(stateFile,JSON.stringify({state,utc:new Date().toISOString(),contract:'COOPERATIVE_JOINED',hardTermination:false}),{mode:0o600});
      result.actionContract='COOPERATIVE_JOINED';result.callbackHardTermination=false;
      result.actionDeadlineExceeded=false;result.actionSettled=false;
      actionState('RUNNING');
      deadline=setTimeout(()=>{
        result.actionDeadlineExceeded=true;
        actionState('CANCELLATION_REQUESTED_WAITING_FOR_CALLBACK');
        cancellation.abort(new Error('ACTION_DEADLINE'));
        // Close the browser to interrupt Playwright work, but join the callback.
        // A timer race cannot terminate arbitrary JavaScript or its side effects.
        void closeContext().catch(()=>{});
      },actionTimeoutMs);
      try {await actions(page,{out,context,signal:cancellation.signal});}
      finally {
        clearTimeout(deadline);result.actionSettled=true;actionState('SETTLED');
      }
      if(result.actionDeadlineExceeded)throw new Error('ACTION_DEADLINE');
      result.actionStatus='PASS';
    }
    result.title=await page.title();result.browserVersion=context.browser().version();result.urlKind=parsed.protocol;
    await page.screenshot({path:path.join(out,'smoke.png'),timeout:5000});fs.chmodSync(path.join(out,'smoke.png'),0o600);
    result.status='PASS';
  } catch(e) {result.errorType=e.name;result.error='HEADLESS_SMOKE_FAILED';}
  finally {
    if(context)try{let t;try{await Promise.race([closeContext(),new Promise((_,reject)=>{t=setTimeout(()=>reject(new Error('CLOSE_DEADLINE')),8000);})]);}finally{clearTimeout(t);}}catch{result.cleanupError='CONTEXT_CLOSE_FAILED';result.status='FAIL';}
    clearInterval(timer);
    let survivors=[];
    for(let i=0;i<20;i++){const rows=processes();survivors=rows.filter(r=>seen.has(r.pid)&&seen.get(r.pid).comm===r.comm);if(!survivors.length)break;await wait(100);}
    result.ownedBrowserPids=[...seen.keys()];result.survivors=survivors;result.peakOwnedTreeRss=peak;
    result.profileRemoved=false;if(!survivors.length){assert.equal(fs.realpathSync(profile),path.join(fs.realpathSync(out),'owned-profile'));fs.rmSync(profile,{recursive:true});result.profileRemoved=!fs.existsSync(profile);}else result.status='FAIL';
    result.wallMs=Date.now()-start;result.nodeCpuMicroseconds=process.cpuUsage(cpuStart);result.measurementGap='250ms samples may miss short children; browser CPU not fully attributed, no global enforcement.';
    receipt(path.join(out,'result.json'),result);
  }
  return result;
}
export async function smoke(out,url){return withPage(out,url);}
async function main(){
  const [mode,...args]=process.argv.slice(2);
  if(mode==='docker'||mode==='docker-cleanup'){
    const {observedLaunch,observedCleanup}=await import('./polar-docker.mjs');
    const result=(mode==='docker'?observedLaunch:observedCleanup)(path.resolve(args[0]),path.resolve(args[1]));
    console.log(JSON.stringify(result));if(mode==='docker'&&(result.preparation_status!=='PREPARED'||result.scenario!=='PASS'))process.exitCode=1;
    if(mode==='docker-cleanup'&&!['REMOVED','ALREADY_ABSENT','NO_RESOURCES'].includes(result.cleanup?.status))process.exitCode=1;
  }
  else if(mode==='doctor')console.log(JSON.stringify(await doctor(args)));
  else if(mode==='smoke'){const result=await smoke(path.resolve(args[0]),args[1]);console.log(JSON.stringify(result));if(result.status!=='PASS')process.exitCode=1;}
  else if(mode==='journey'){
    const modulePath=path.resolve(args[2]);const actions=(await import(pathToFileURL(modulePath).href)).default;
    const result=await withPage(path.resolve(args[0]),args[1],actions);console.log(JSON.stringify(result));if(result.status!=='PASS')process.exitCode=1;
  }
  else if(mode==='export')console.log(JSON.stringify(exportSource(...args)));
  else if(mode==='timestamps')console.log(JSON.stringify(timestampCases()));
  else throw Error('Usage: polar-local.mjs docker CONFIG NEW_PRIVATE_DIR | docker-cleanup CONFIG PRIVATE_DIR | doctor [owned-container...] | smoke NEW_PRIVATE_DIR [localURL] | journey NEW_PRIVATE_DIR localURL ACTIONS_MODULE | export REPO COMMIT TREE NEW_DIR | timestamps');
}
if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url)main().catch(e=>{console.error(JSON.stringify({status:'FAIL',errorType:e.name,code:e.message}));process.exitCode=1;});
