// Minimal helpers for the existing named headed playwright-cli path. No provider automation policy.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';

export const VERSION='polar-access-interaction/1';
export class AccessError extends Error {constructor(code){super(code);this.code=code;}}
const check=(ok,code)=>{if(!ok)throw new AccessError(code);};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const code=v=>typeof v==='string'&&/^[a-z][a-z0-9-]{0,63}$/.test(v);

export function pacing({actions=[600,1200],keys=[40,100],scroll=[100,250],seed=1}={}) {
  check(Number.isInteger(seed)&&seed>=0&&seed<=0xffffffff,'INVALID_PACING');
  const ranges={actions,keys,scroll};
  for(const range of Object.values(ranges))check(Array.isArray(range)&&range.length===2&&range.every(Number.isInteger)&&range[0]>=0&&range[0]<=range[1]&&range[1]<=5000,'INVALID_PACING');
  let state=seed>>>0;const aggregate=Object.fromEntries(Object.keys(ranges).map(k=>[k,{count:0,total_ms:0}]));
  return {profile:{...structuredClone(ranges),seed},aggregate,next(kind){
    check(Object.hasOwn(ranges,kind),'INVALID_PACING_KIND');
    state=(Math.imul(1664525,state)+1013904223)>>>0;
    const [min,max]=ranges[kind],ms=min+Math.floor(state/4294967296*(max-min+1));
    aggregate[kind].count++;aggregate[kind].total_ms+=ms;return ms;
  }};
}

export function allowedURL(value,hosts,{localFixture=false}={}) {
  check(Array.isArray(hosts)&&hosts.length>0&&hosts.length<=8&&hosts.every(h=>typeof h==='string'&&/^[a-z0-9.-]+$/.test(h)&&!h.endsWith('.')),'INVALID_HOST_POLICY');
  let u;try{u=new URL(value);}catch{throw new AccessError('UNSAFE_DESTINATION');}
  const local=localFixture&&u.protocol==='http:'&&u.hostname==='127.0.0.1';
  check((u.protocol==='https:'||local)&&!u.username&&!u.password&&hosts.includes(u.hostname)&&
        (!u.port||local)&&!u.hostname.endsWith('.'),'UNSAFE_DESTINATION');
  return u.href; // sensitive URL stays in caller memory/private script, never a receipt
}

export function selectVerification(rows,{provider,operation,visibleLabels,hosts}) {
  check(code(provider)&&code(operation)&&Array.isArray(rows)&&rows.length<=100&&Array.isArray(visibleLabels)&&visibleLabels.length<=12,'INVALID_MAILBOX_QUERY');
  const norm=s=>typeof s==='string'?s.normalize('NFKC').trim().toLocaleLowerCase():'';
  const labels=visibleLabels.map(norm);
  const found=rows.filter(r=>r.visible===true&&norm(r.provider)===provider&&r.operation===operation&&labels.includes(norm(r.label)));
  check(found.length===1,found.length?'MAILBOX_AMBIGUOUS':'MAILBOX_NOT_OBSERVED');
  return allowedURL(found[0].href,hosts);
}

export function qualification(input) {
  const keys=['account','email','dashboard','api_auth','entitlement','required_data','rights','fitness'];
  check(input&&Object.keys(input).sort().join()===keys.sort().join()&&Object.values(input).every(v=>['NOT_RUN','OBSERVED','PASS','FAIL','UNKNOWN'].includes(v)),'INVALID_QUALIFICATION');
  return {...input}; // No inference from dashboard, auth or HTTP success to any other state.
}

function locator(target) {
  check(target&&typeof target==='object'&&Object.keys(target).every(k=>['selector','role','name'].includes(k)),'INVALID_TARGET');
  if(typeof target.selector==='string'&&target.selector.length<=256&&!target.role&&!target.name)return `page.locator(${JSON.stringify(target.selector)})`;
  check(typeof target.role==='string'&&/^[a-z]+$/.test(target.role)&&typeof target.name==='string'&&target.name.length<=128,'INVALID_TARGET');
  return `page.getByRole(${JSON.stringify(target.role)},{name:${JSON.stringify(target.name)},exact:true})`;
}

function safeDir(directory) {
  try {
    const absolute=path.resolve(directory);
    check(fs.realpathSync(absolute)===absolute&&fs.statSync(absolute).isDirectory()&&
          (fs.statSync(absolute).mode&0o077)===0,'UNSAFE_PRIVATE_DIRECTORY');
    return absolute;
  }catch{throw new AccessError('UNSAFE_PRIVATE_DIRECTORY');}
}

// Only explicit existing JSON references from DE's admitted schemas. No discovery or prototype import.
const FIELDS={'alpaca-account.json':['email','password'],
  'alpaca-api-credentials.json':['endpoint','key_id','secret_key','scope'],
  'alphavantage-api-credentials.json':['provider','api_key','purpose']};
export function privateFields(root,reference) {
  const directory=safeDir(root);
  check(reference&&Object.hasOwn(FIELDS,reference.file)&&Array.isArray(reference.fields)&&reference.fields.length>0&&
        reference.fields.every(f=>FIELDS[reference.file].includes(f)),'INVALID_PRIVATE_REFERENCE');
  let fd;
  try {
    const file=path.join(directory,reference.file);fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
    const info=fs.fstatSync(fd);check(info.isFile()&&info.nlink===1&&info.uid===process.getuid()&&(info.mode&0o077)===0&&info.size<=16384,'UNSAFE_PRIVATE_REFERENCE');
    const parsed=JSON.parse(fs.readFileSync(fd,'utf8')),result={};
    for(const name of reference.fields){check(typeof parsed[name]==='string'&&parsed[name].length<=4096,'INVALID_PRIVATE_REFERENCE');result[name]=parsed[name];}
    return result;
  }catch{throw new AccessError('PRIVATE_INPUT_UNAVAILABLE');}finally{if(fd!==undefined)fs.closeSync(fd);}
}

export function cliExecutor({session,privateDir,executable='playwright-cli'}) {
  check(typeof session==='string'&&/^[a-z0-9-]{1,64}$/.test(session),'INVALID_SESSION');
  const directory=safeDir(privateDir);
  return async(source,timeoutMs)=>{
    const file=path.join(directory,`action-${crypto.randomUUID()}.js`);
    fs.writeFileSync(file,source,{flag:'wx',mode:0o600});
    try {
      return await new Promise((resolve,reject)=>{
        let output='',bytes=0,timedOut=false,force;
        const child=spawn(executable,[`--session=${session}`,'run-code','--filename',file],{cwd:directory,stdio:['ignore','pipe','pipe']});
        const stop=()=>{child.kill('SIGTERM');force??=setTimeout(()=>child.kill('SIGKILL'),500);};
        const timer=setTimeout(()=>{timedOut=true;stop();},timeoutMs);
        child.stdout.on('data',chunk=>{bytes+=chunk.length;if(bytes<=131072)output+=chunk.toString();else stop();});
        child.stderr.on('data',chunk=>{bytes+=chunk.length;if(bytes>131072)stop();}); // never forward raw output
        child.on('error',()=>{clearTimeout(timer);clearTimeout(force);reject(new AccessError('CLI_UNAVAILABLE'));});
        child.on('close',status=>{
          clearTimeout(timer);clearTimeout(force);
          if(timedOut||status!==0||bytes>131072)return reject(new AccessError(timedOut?'CLI_TIMEOUT':'CLI_ACTION_FAILED'));
          try {
            const match=output.match(/### Result\r?\n([\s\S]*?)(?=\r?\n###|$)/);
            const result=JSON.parse(match?.[1]||'null');
            check(result&&result.polar_access&&Object.values(result.polar_access).every(v=>typeof v==='boolean'),'UNSAFE_CLI_RESULT');
            resolve(result.polar_access);
          }catch{reject(new AccessError('CLI_RESULT_UNAVAILABLE'));}
        });
      });
    }finally{fs.unlinkSync(file);}
  };
}

export class AccessSession {
  constructor({session,privateDir,hosts,localFixture=false,deadlineMs=60000,profile={},execute,now=()=>Date.now(),pause=sleep}) {
    check(typeof session==='string'&&/^[a-z0-9-]{1,64}$/.test(session)&&Number.isInteger(deadlineMs)&&deadlineMs>=100&&deadlineMs<=600000,'INVALID_SESSION');
    check(typeof localFixture==='boolean'&&Array.isArray(hosts)&&hosts.length>0,'INVALID_HOST_POLICY');
    allowedURL(`https://${hosts[0]}/`,hosts);
    this.directory=safeDir(privateDir);this.session=session;this.hosts=hosts;this.localFixture=localFixture;
    this.now=now;this.end=now()+deadlineMs;this.pause=pause;this.pacing=pacing(profile);
    this.execute=execute||cliExecutor({session,privateDir:this.directory});
    this.file=path.join(this.directory,'access-checkpoints.jsonl');this.states=new Map();
    if(fs.existsSync(this.file)){
      check(!fs.lstatSync(this.file).isSymbolicLink()&&fs.statSync(this.file).nlink===1&&fs.statSync(this.file).size<=65536,'UNSAFE_CHECKPOINT');
      const raw=fs.readFileSync(this.file,'utf8');check(raw.endsWith('\n'),'PARTIAL_CHECKPOINT');
      try{for(const line of raw.trimEnd().split('\n')){
        const record=JSON.parse(line);
        check(record.version===VERSION&&record.session===session&&code(record.id)&&
              ['PENDING','CONFIRMED','NOT_APPLIED','UNKNOWN_EFFECT'].includes(record.state),'INVALID_CHECKPOINT');
        this.states.set(record.id,record.state);
      }}catch{throw new AccessError('INVALID_CHECKPOINT');}
    }
  }
  remaining(){const left=this.end-this.now();check(left>0,'ACTION_DEADLINE');return Math.min(left,60000);}
  record(id,state){
    check(code(id),'INVALID_OPERATION_ID');
    const raw=JSON.stringify({version:VERSION,session:this.session,id,state,utc:new Date().toISOString()})+'\n';
    const fd=fs.openSync(this.file,fs.constants.O_WRONLY|fs.constants.O_APPEND|fs.constants.O_CREAT|fs.constants.O_NOFOLLOW,0o600);
    try{check(fs.fstatSync(fd).isFile()&&fs.fstatSync(fd).nlink===1&&fs.fstatSync(fd).size+raw.length<=65536,'CHECKPOINT_LIMIT');
      check(fs.writeSync(fd,raw)===Buffer.byteLength(raw),'UNKNOWN_CHECKPOINT_EFFECT');fs.fsyncSync(fd);
    }finally{fs.closeSync(fd);}
    this.states.set(id,state);
  }
  async wait(kind){const ms=this.pacing.next(kind);check(ms<this.remaining(),'ACTION_DEADLINE');await this.pause(ms);this.remaining();}
  async run(body){this.remaining();return this.execute(`async page => {try {${body}} catch {return {polar_access:{observed:false}};}}`,this.remaining());}
  async ready(target){
    const loc=locator(target),timeout=this.remaining();
    return this.run(`const loc=${loc};await loc.waitFor({state:'visible',timeout:${timeout}});const observed=await loc.count()===1&&await loc.isEnabled()&&await loc.evaluate(e=>!e.form||e.form.checkValidity());return {polar_access:{observed}};`);
  }
  async mutate(id,operation,target){
    check(['submit','login','verification','key-creation','api-probe'].includes(operation),'INVALID_OPERATION');
    const previous=this.states.get(id);
    check(previous!=='PENDING'&&previous!=='UNKNOWN_EFFECT','OBSERVE_BEFORE_RETRY');
    if(previous==='CONFIRMED')return {status:'ALREADY_CONFIRMED'};
    const ready=await this.ready(target);check(ready.observed,'NOT_READY');
    await this.wait('actions');this.record(id,'PENDING');
    try {
      const result=await this.run(`const loc=${locator(target)};await loc.click({timeout:${this.remaining()}});return {polar_access:{dispatched:true}};`);
      // Click return is not account/login/submit completion. Require a separate observation.
      this.record(id,'UNKNOWN_EFFECT');return {status:'UNKNOWN_EFFECT',dispatched:result.dispatched===true,next:'observe-state'};
    }catch{this.record(id,'UNKNOWN_EFFECT');throw new AccessError('UNKNOWN_EFFECT');}
  }
  observe(id,effect,flags){
    check(['confirmed','not-applied','unresolved'].includes(effect)&&flags&&Object.keys(flags).length>0&&
          Object.keys(flags).every(code)&&Object.values(flags).every(v=>typeof v==='boolean'),'INVALID_OBSERVATION');
    check(effect==='unresolved'||Object.values(flags).some(Boolean),'OBSERVATION_REQUIRED');
    check(['PENDING','UNKNOWN_EFFECT'].includes(this.states.get(id)),'NO_PENDING_EFFECT');
    this.record(id,effect==='confirmed'?'CONFIRMED':effect==='not-applied'?'NOT_APPLIED':'UNKNOWN_EFFECT');
    return {status:this.states.get(id),next:effect==='unresolved'?'observe-state':'continue'};
  }
  humanAction(id,action){
    check(code(id)&&['complete-visible-verification','select-country','provide-entitlement','restore-driver-control'].includes(action),'INVALID_HUMAN_ACTION');
    return {status:'HUMAN_ACTION_REQUIRED',action,session:this.session,checkpoint:id,prior_state:this.states.get(id)||'NOT_STARTED',next:'resume-same-session'};
  }
  async choose(target,value){
    check(typeof value==='string'&&value.length<=64,'INVALID_OPTION');await this.wait('actions');
    return this.run(`const loc=${locator(target)};await loc.selectOption(${JSON.stringify(value)},{timeout:${this.remaining()}});return {polar_access:{observed:true}};`);
  }
  async scroll(pixels){
    check(Number.isInteger(pixels)&&Math.abs(pixels)<=2000,'INVALID_SCROLL');await this.wait('scroll');
    return this.run(`await page.mouse.wheel(0,${pixels});return {polar_access:{observed:true}};`);
  }
  async fillPrivate(root,reference,targets){
    const values=privateFields(root,reference);
    check(Object.keys(targets).sort().join()===Object.keys(values).sort().join(),'INVALID_PRIVATE_TARGET');
    for(const target of Object.values(targets))locator(target);
    // Endpoint token and private data never enter argv, public logs or receipts.
    const endpoint='/'+crypto.randomBytes(24).toString('hex');let consumed=false;
    const server=http.createServer((req,res)=>{
      if(req.method!=='GET'||req.url!==endpoint||consumed){res.writeHead(404);res.end();return;}
      consumed=true;res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store','Connection':'close'});res.end(JSON.stringify(values));
    });
    try{
      await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
      const url=`http://127.0.0.1:${server.address().port}${endpoint}`,delays={};
      for(const [field,value] of Object.entries(values))delays[field]=Array.from(value,()=>this.pacing.next('keys'));
      const browserBudget=Math.max(1,this.remaining()-100);
      const assignments=Object.entries(targets).map(([field,target])=>`{const loc=${locator(target)};await loc.waitFor({state:'visible',timeout:${this.remaining()}});if(await loc.count()!==1||!await loc.isEnabled())return {polar_access:{observed:false}};await loc.fill('',{timeout:Math.max(1,end-Date.now())});for(const [i,char] of Array.from(data[${JSON.stringify(field)}]).entries()){if(Date.now()+delays[${JSON.stringify(field)}][i]>=end)return {polar_access:{observed:false}};await loc.pressSequentially(char,{timeout:Math.max(1,end-Date.now())});await new Promise(r=>setTimeout(r,delays[${JSON.stringify(field)}][i]));}}`).join('');
      const policy=JSON.stringify({hosts:this.hosts,localFixture:this.localFixture});
      return await this.run(`const policy=${policy},u=new URL(page.url());if(!policy.hosts.includes(u.hostname)||u.username||u.password||(u.port&&!policy.localFixture)||!(u.protocol==='https:'||(policy.localFixture&&u.protocol==='http:'&&u.hostname==='127.0.0.1')))return {polar_access:{observed:false}};const end=Date.now()+${browserBudget};const response=await page.request.get(${JSON.stringify(url)},{timeout:${this.remaining()}});const data=await response.json(),delays=${JSON.stringify(delays)};${assignments}return {polar_access:{observed:true}};`);
    }catch{throw new AccessError('PRIVATE_FILL_FAILED');}finally{
      server.closeAllConnections();if(server.listening)await new Promise(resolve=>server.close(resolve));for(const field of Object.keys(values))values[field]='';
    }
  }
  async followVerification(id,url){
    const destination=allowedURL(url,this.hosts,{localFixture:this.localFixture});
    check(!['PENDING','UNKNOWN_EFFECT'].includes(this.states.get(id)),'OBSERVE_BEFORE_RETRY');
    if(this.states.get(id)==='CONFIRMED')return {status:'ALREADY_CONFIRMED'};
    await this.wait('actions');this.record(id,'PENDING');
    try{
      const policy=JSON.stringify({hosts:this.hosts,localFixture:this.localFixture});
      const result=await this.run(`const policy=${policy};let blocked=false;const cdp=await page.context().newCDPSession(page),pending=new Set();try{const tree=await cdp.send('Page.getFrameTree');cdp.on('Fetch.requestPaused',event=>{const work=(async()=>{let permitted=true;if(event.frameId===tree.frameTree.frame.id){const u=new URL(event.request.url);permitted=!u.username&&!u.password&&(!u.port||policy.localFixture)&&policy.hosts.includes(u.hostname)&&(u.protocol==='https:'||(policy.localFixture&&u.protocol==='http:'&&u.hostname==='127.0.0.1'));}if(!permitted)blocked=true;await cdp.send(permitted?'Fetch.continueRequest':'Fetch.failRequest',permitted?{requestId:event.requestId}:{requestId:event.requestId,errorReason:'BlockedByClient'});})().catch(()=>{blocked=true;});pending.add(work);work.finally(()=>pending.delete(work));});await cdp.send('Fetch.enable',{patterns:[{resourceType:'Document',requestStage:'Request'}]});await page.goto(${JSON.stringify(destination)},{timeout:${this.remaining()}});return {polar_access:{observed:!blocked}};}finally{await Promise.allSettled([...pending]);try{await cdp.send('Fetch.disable');}finally{await cdp.detach();}}`);
      this.record(id,'UNKNOWN_EFFECT');return {status:'UNKNOWN_EFFECT',observed:result.observed===true,next:'observe-state'};
    }catch{this.record(id,'UNKNOWN_EFFECT');throw new AccessError('UNKNOWN_EFFECT');}
  }
  receipt(){return {version:VERSION,session:this.session,profile:this.pacing.profile,aggregate:this.pacing.aggregate,
    pending_observation:[...this.states.values()].filter(v=>v==='PENDING'||v==='UNKNOWN_EFFECT').length};}
}
