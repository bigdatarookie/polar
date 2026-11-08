// Runtime-observed Docker boundary used by polar-local; no scenarios during create.
import fs from 'node:fs';
import path from 'node:path';
import cp from 'node:child_process';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

export const VERSION='polar-observed-launch/1';
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
const now=()=>new Date().toISOString();
const check=(v,code)=>assert(v,code);
const canonical=v=>JSON.stringify(sort(v));
function sort(v) {
  if(Array.isArray(v))return v.map(sort);
  if(v&&typeof v==='object')return Object.fromEntries(Object.keys(v).sort().map(k=>[k,sort(v[k])]));
  check(v===null||['string','boolean'].includes(typeof v)||(typeof v==='number'&&Number.isFinite(v)),'INVALID_JSON');return v;
}
function exact(v,keys) {check(v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join('|')===keys.sort().join('|'),'INVALID_FIELDS');}
function regular(file,limit=1024*1024) {
  check(typeof file==='string'&&file.length<=4096&&!/[,\x00-\x1f]/.test(file)&&path.isAbsolute(file)&&fs.realpathSync(file)===file,'UNSAFE_PATH');
  const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
  try {const st=fs.fstatSync(fd);check(st.isFile()&&st.size<=limit,'FILE_BOUND');const b=Buffer.alloc(st.size+1);const n=fs.readSync(fd,b,0,b.length,0);check(n===st.size,'FILE_CHANGED');return b.subarray(0,n);}finally{fs.closeSync(fd);}
}
function publish(file,value) {
  const raw=Buffer.from(canonical(value)+'\n');check(raw.length<=1024*1024,'RECEIPT_BOUND');
  const tmp=file+'.'+crypto.randomUUID()+'.tmp';const fd=fs.openSync(tmp,'wx',0o600);
  try{fs.writeFileSync(fd,raw);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
  try{fs.linkSync(tmp,file);}finally{fs.unlinkSync(tmp);}
  const d=fs.openSync(path.dirname(file),'r');try{fs.fsyncSync(d);}finally{fs.closeSync(d);}
  return {path:file,sha256:hash(raw)};
}
function docker(args,timeout=15000) {
  const r=cp.spawnSync('docker',args,{encoding:'utf8',timeout,maxBuffer:1024*1024});
  check(!r.error&&r.status===0,'ENGINE_COMMAND_FAILED');return r.stdout;
}
const jsonDocker=args=>JSON.parse(docker(args));
const same=(a,b)=>canonical(a)===canonical(b);
function validate(s) {
  exact(s,['schema','launch_id','candidate','image_id','runtime_image_id','platform','user','entrypoint','environment','refs','build_fields','scenario_timeout_ms']);
  check(s.schema==='polar.observed-launch-config/1'&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(s.launch_id),'INVALID_LAUNCH');
  exact(s.candidate,['commit','tree']);check(Object.values(s.candidate).every(x=>/^[a-f0-9]{40}$/.test(x)),'INVALID_CANDIDATE');
  check(/^sha256:[a-f0-9]{64}$/.test(s.image_id),'IMMUTABLE_IMAGE_ID_REQUIRED');
  check(/^sha256:[a-f0-9]{64}$/.test(s.runtime_image_id),'IMMUTABLE_RUNTIME_IMAGE_ID_REQUIRED');
  check(/^linux\/(arm64|amd64)$/.test(s.platform),'INVALID_PLATFORM');
  check(typeof s.user==='string'&&/^[a-zA-Z0-9_-]{1,32}(?::[a-zA-Z0-9_-]{1,32})?$/.test(s.user),'INVALID_CONFIGURED_USER');
  check(typeof s.entrypoint==='string'&&/^\/[a-zA-Z0-9_./-]+$/.test(s.entrypoint)&&!s.entrypoint.includes('..'),'INVALID_ENTRYPOINT');
  check(Number.isInteger(s.scenario_timeout_ms)&&s.scenario_timeout_ms>=100&&s.scenario_timeout_ms<=600000,'INVALID_DEADLINE');
  check(s.environment&&typeof s.environment==='object'&&!Array.isArray(s.environment),'INVALID_ENVIRONMENT');
  const allowed={TZ:/^[A-Za-z_/+-]{1,64}$/,LANG:/^[A-Za-z0-9_.-]{1,32}$/,PYTHONDONTWRITEBYTECODE:/^1$/,PYTHONUNBUFFERED:/^1$/,POLAR_CODE_REVISION:/^[a-f0-9]{40}$/};
  for(const [k,v] of Object.entries(s.environment))check(allowed[k]&&typeof v==='string'&&allowed[k].test(v),'UNSAFE_ENVIRONMENT');
  exact(s.refs,['source_build','harness','input','expectations','config','review']);
  const refs={};
  for(const [k,v] of Object.entries(s.refs)) {
    exact(v,['path','sha256']);check(typeof v.path==='string'&&/^[a-f0-9]{64}$/.test(v.sha256),'INVALID_REFERENCE');
    const raw=regular(v.path);check(hash(raw)===v.sha256,'REFERENCE_HASH_MISMATCH');refs[k]={...v,bytes:raw.length,raw};
  }
  check(new Set(Object.values(refs).map(x=>x.path)).size===6,'REFERENCE_PATH_COLLISION');
  exact(s.build_fields,['commit','tree','image_id']);
  const build=JSON.parse(refs.source_build.raw);
  for(const [k,keys] of Object.entries(s.build_fields)) {
    check(Array.isArray(keys)&&keys.length>0&&keys.length<=8&&keys.every(x=>typeof x==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(x)),'INVALID_BUILD_FIELDS');
    let value=build;for(const key of keys)value=value?.[key];
    check(value===(k==='image_id'?s.image_id:s.candidate[k]),'SOURCE_BUILD_BINDING_MISMATCH');
  }
  return refs;
}
function ownedContainer(id,s,bindingHash) {
  check(/^[a-f0-9]{64}$/.test(id),'INVALID_CONTAINER_ID');
  const c=jsonDocker(['inspect','--type','container',id])[0];
  check(c.Id===id&&c.Config.Labels?.['polar.launch.id']===s.launch_id&&c.Config.Labels?.['polar.launch.binding']===bindingHash,'CONTAINER_OWNERSHIP_CONFLICT');return c;
}
function cleanup(id,s,bindingHash,creationAttempted) {
  if(!id)return {status:creationAttempted?'UNKNOWN_CREATE_OUTCOME':'NO_RESOURCES',container_name:creationAttempted?'polar-observed-'+s.launch_id:null};
  try{const ids=docker(['ps','--all','--quiet','--no-trunc','--filter','id='+id]).trim();if(!ids)return {status:'ALREADY_ABSENT',container_id:id};check(ids===id,'CONTAINER_OWNERSHIP_CONFLICT');ownedContainer(id,s,bindingHash);docker(['rm','--force',id]);return {status:'REMOVED',container_id:id};}
  catch{return {status:'UNVERIFIED_RETAINED',container_id:id};}
}
function observation(c,image,s) {
  const env={};for(const item of c.Config.Env||[]){const at=item.indexOf('=');const key=item.slice(0,at);if(Object.hasOwn(s.environment,key))env[key]=item.slice(at+1);}
  const expectedCommand=[s.refs.harness.path,s.refs.input.path,s.refs.expectations.path,s.refs.config.path,'/polar-output'];
  const safeEnv=same(env,s.environment);
  // Never retain an unexpected command/environment string from engine output.
  const entrypointMatches=same(c.Config.Entrypoint,[s.entrypoint]);const commandMatches=same(c.Config.Cmd,expectedCommand);
  return {container_id:c.Id,image_id:c.Image,image_identity_type:'docker-local-image-id',os:image.Os,architecture:image.Architecture,
    configured_user:c.Config.User===s.user?c.Config.User:null,process_uid:null,
    entrypoint:entrypointMatches?c.Config.Entrypoint:null,command:commandMatches?c.Config.Cmd:null,
    safe_environment:safeEnv?env:null,safe_environment_sha256:safeEnv?hash(canonical(env)):null,unexpected_configuration_redacted:!safeEnv||!entrypointMatches||!commandMatches,
    created_at:c.Created,observed_at:now(),state:c.State.Status,
    matches:{image:c.Image===s.image_id,platform:image.Os+'/'+image.Architecture===s.platform,user:c.Config.User===s.user,
      entrypoint:entrypointMatches,command:commandMatches,environment:safeEnv,not_started:c.State.Status==='created'}};
}

export function observedLaunch(configFile,out) {
  const started=now();let s,refs,bindingHash=null,id=null,prepRef=null,root=false,creationAttempted=false;
  let preparation={schema:'polar.observed-preparation/1',producer:{version:VERSION,sha256:hash(fs.readFileSync(fileURLToPath(import.meta.url)))},
    created_at:started,scenario_started:false,preparation:'NOT_PREPARED',reason:null,expected:null,observed:null,engine:null};
  let result={schema:'polar.observed-execution/1',scenario:'NOT_RUN',scenario_started:false,cleanup:{status:'NO_RESOURCES'}};
  try {
    check(path.isAbsolute(out)&&path.resolve(out)===out&&fs.realpathSync(path.dirname(out))===path.dirname(out),'UNSAFE_OUTPUT_ROOT');
    if(fs.existsSync(out)) {
      check(fs.realpathSync(out)===out&&fs.lstatSync(out).isDirectory(),'OUTPUT_CONFLICT');
      s=JSON.parse(regular(configFile).toString());
      const owner=JSON.parse(regular(path.join(out,'owner.json')));
      check(owner.launch_id===s.launch_id,'OUTPUT_IDENTITY_CONFLICT');
      refs=validate(s);bindingHash=hash(canonical({config:s,output_root:out}));
      check(JSON.parse(regular(path.join(out,'binding.json'))).binding_sha256===bindingHash,'OUTPUT_IDENTITY_CONFLICT');
      const final=JSON.parse(regular(path.join(out,'result.json')));
      check(final.preparation?.sha256===hash(regular(path.join(out,'preparation.json'))),'RECEIPT_CONFLICT');
      return {...final,reconciled:true}; // Reading never starts/retries a scenario.
    }
    fs.mkdirSync(out,{mode:0o700});root=true;
    s=JSON.parse(regular(configFile).toString());
    publish(path.join(out,'owner.json'),{schema:'polar.launch-owner/1',launch_id:typeof s.launch_id==='string'&&/^[a-f0-9-]{36}$/.test(s.launch_id)?s.launch_id:null});
    refs=validate(s);bindingHash=hash(canonical({config:s,output_root:out}));
    publish(path.join(out,'binding.json'),{binding_sha256:bindingHash});
    const staged=path.join(out,'bindings');fs.mkdirSync(staged,{mode:0o700});
    for(const [k,v] of Object.entries(refs)){fs.writeFileSync(path.join(staged,k),v.raw,{flag:'wx',mode:0o444});delete v.raw;}
    fs.chmodSync(staged,0o555);
    const output=path.join(out,'scenario');fs.mkdirSync(output,{mode:0o777});fs.chmodSync(output,0o777);
    preparation.expected={launch_id:s.launch_id,binding_sha256:bindingHash,candidate:s.candidate,image_id:s.image_id,image_identity_type:'docker-local-image-id',platform:s.platform,
      configured_user:s.user,entrypoint:[s.entrypoint],command:[s.refs.harness.path,s.refs.input.path,s.refs.expectations.path,s.refs.config.path,'/polar-output'],safe_environment:s.environment,refs};
    preparation.source_binding={kind:'reviewed-reference-bytes-and-declared-fields',verified_build_fields:s.build_fields,packaged_source_independently_observed:false,overlays:'UNSUPPORTED_NO_OVERLAYS_MOUNTED',review_scope:'Reference bytes/hash only; applicable independent review authority belongs to caller/QA, not this tool.'};
    const info=jsonDocker(['info','--format','{{json .}}']);
    preparation.engine={id:info.ID,server_version:info.ServerVersion,os:info.OSType,architecture:info.Architecture};
    check(typeof info.ID==='string'&&info.ID.length>0,'ENGINE_IDENTITY_MISSING');
    const args=['create','--pull=never','--name','polar-observed-'+s.launch_id,'--label','polar.launch.id='+s.launch_id,'--label','polar.launch.binding='+bindingHash,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user',s.user,'--platform',s.platform,'--entrypoint',s.entrypoint];
    for(const [k,v] of Object.entries(s.environment))args.push('--env',k+'='+v);
    for(const [k,v] of Object.entries(refs))args.push('--mount','type=bind,src='+path.join(staged,k)+',dst='+v.path+',readonly');
    args.push('--mount','type=bind,src='+output+',dst=/polar-output',s.runtime_image_id,...preparation.expected.command);
    publish(path.join(out,'resources.json'),{container_name:'polar-observed-'+s.launch_id,launch_id:s.launch_id,binding_sha256:bindingHash});
    creationAttempted=true;
    id=docker(args).trim();check(/^[a-f0-9]{64}$/.test(id),'INVALID_CONTAINER_ID');
    publish(path.join(out,'container.json'),{container_id:id,launch_id:s.launch_id,binding_sha256:bindingHash});
    preparation.owned_resources={container_id:id,container_name:'polar-observed-'+s.launch_id};
    const c=ownedContainer(id,s,bindingHash);
    preparation.observed={container_id:c.Id,image_id:c.Image,image_identity_type:'docker-local-image-id',os:null,architecture:null,observed_at:now()};
    const image=jsonDocker(['image','inspect',c.Image])[0];check(image.Id===c.Image,'IMAGE_OBSERVATION_MISSING');
    preparation.observed=observation(c,image,s);preparation.compared_at=now();
    check(Object.values(preparation.observed.matches).every(Boolean),'RUNTIME_BINDING_MISMATCH');
    for(const [k,v] of Object.entries(refs))check(hash(regular(path.join(staged,k)))===v.sha256,'STAGED_REFERENCE_CHANGED');
    preparation.preparation='PREPARED';preparation.reason='EXPECTED_OBSERVED_MATCH';preparation.published_at=now();
    prepRef=publish(path.join(out,'preparation.json'),preparation);
    // A receipt is committed before starting the SAME observed full container ID.
    result.preparation=prepRef;result.scenario_started=true;result.started_at=now();
    const run=cp.spawnSync('docker',['start','--attach',id],{encoding:'utf8',timeout:s.scenario_timeout_ms,maxBuffer:1024*1024});
    result.finished_at=now();result.scenario=(!run.error&&run.status===0)?'PASS':'FAIL';
    result.transport_exit=run.status;result.command_error=run.error?'BOUNDED_SCENARIO_COMMAND_ERROR':null;
    result.stdout_bytes=Buffer.byteLength(run.stdout||'');result.stderr_bytes=Buffer.byteLength(run.stderr||'');
    const done=ownedContainer(id,s,bindingHash);result.container_exit=done.State.ExitCode;
    if(done.State.Running||done.State.ExitCode!==0)result.scenario='FAIL';
  } catch(e) {
    const codes=new Set(['INVALID_FIELDS','INVALID_LAUNCH','INVALID_CANDIDATE','IMMUTABLE_IMAGE_ID_REQUIRED','IMMUTABLE_RUNTIME_IMAGE_ID_REQUIRED','INVALID_PLATFORM','INVALID_CONFIGURED_USER','INVALID_ENTRYPOINT','INVALID_DEADLINE','INVALID_ENVIRONMENT','UNSAFE_ENVIRONMENT','INVALID_REFERENCE','REFERENCE_HASH_MISMATCH','REFERENCE_PATH_COLLISION','INVALID_BUILD_FIELDS','SOURCE_BUILD_BINDING_MISMATCH','UNSAFE_OUTPUT_ROOT','OUTPUT_CONFLICT','OUTPUT_IDENTITY_CONFLICT','RECEIPT_CONFLICT','ENGINE_IDENTITY_MISSING','ENGINE_COMMAND_FAILED','INVALID_CONTAINER_ID','CONTAINER_OWNERSHIP_CONFLICT','IMAGE_OBSERVATION_MISSING','RUNTIME_BINDING_MISMATCH','STAGED_REFERENCE_CHANGED']);
    const code=codes.has(e.message)?e.message:'PREPARATION_IO_OR_RECORD_ERROR';
    if(!root)return {schema:'polar.observed-execution/1',preparation_status:'NOT_PREPARED',reason:code,scenario:'NOT_RUN',scenario_started:false,cleanup:{status:'NO_RESOURCES_CREATED'}};
    if(!prepRef){preparation.preparation='NOT_PREPARED';preparation.reason=code;preparation.published_at=now();try{prepRef=publish(path.join(out,'preparation.json'),preparation);}catch{result.receipt_error='IMMUTABLE_RECEIPT_PUBLICATION_FAILED';}}
    else result.scenario='FAIL';
    result.reason=code;
  } finally {
    if(root){result.cleanup=cleanup(id,s,bindingHash,creationAttempted);result.preparation=prepRef;result.finished_at=now();result.preparation_status=preparation.preparation;
      try{publish(path.join(out,'result.json'),result);}catch{result.result_publication_error='IMMUTABLE_RESULT_CONFLICT';}}
  }
  return result;
}

function cleanupObserved(configFile,out) {
  check(path.isAbsolute(out)&&path.resolve(out)===out&&fs.realpathSync(out)===out,'UNSAFE_OUTPUT_ROOT');
  // Cleanup relies on the original exact binding, not continued input availability.
  const s=JSON.parse(regular(configFile));const bindingHash=hash(canonical({config:s,output_root:out}));
  check(JSON.parse(regular(path.join(out,'owner.json'))).launch_id===s.launch_id&&JSON.parse(regular(path.join(out,'binding.json'))).binding_sha256===bindingHash,'OUTPUT_IDENTITY_CONFLICT');
  const resources=JSON.parse(regular(path.join(out,'resources.json')));
  check(resources.launch_id===s.launch_id&&resources.binding_sha256===bindingHash,'OUTPUT_IDENTITY_CONFLICT');
  let id=null;
  if(fs.existsSync(path.join(out,'container.json')))id=JSON.parse(regular(path.join(out,'container.json'))).container_id;
  else {
    const ids=docker(['ps','--all','--quiet','--no-trunc','--filter','name=^/'+resources.container_name+'$']).trim().split('\n').filter(Boolean);
    check(ids.length<=1,'CONTAINER_OWNERSHIP_CONFLICT');id=ids[0]||null;
    if(id)ownedContainer(id,s,bindingHash);
  }
  const value={schema:'polar.observed-cleanup/1',launch_id:s.launch_id,observed_at:now(),cleanup:id?cleanup(id,s,bindingHash,true):{status:'ALREADY_ABSENT'}};
  const ref=publish(path.join(out,'cleanup-'+crypto.randomUUID()+'.json'),value);return {...value,receipt:ref};
}
export function observedCleanup(configFile,out) {
  try{return cleanupObserved(configFile,out);}
  catch{return {schema:'polar.observed-cleanup/1',cleanup:{status:'UNVERIFIED_RETAINED'},reason:'CLEANUP_IDENTITY_OR_ENGINE_ERROR'};}
}
