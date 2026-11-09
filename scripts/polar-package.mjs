// Deterministic metadata preparation for the existing PR32/PR37 execution paths.
// This module does not assign review PASS, start a process/container or issue a grant.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
export const VERSION='polar-review-package/1';
const check=(v,c)=>assert(v,c);
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const sort=x=>Array.isArray(x)?x.map(sort):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,sort(x[k])])):x;
export const canonical=x=>Buffer.from(JSON.stringify(sort(x))+'\n');
const equal=(a,b)=>a===undefined||b===undefined?a===b:canonical(a).equals(canonical(b));
const PREFIX='/app/src/polar/';
function safe(p){check(typeof p==='string'&&path.isAbsolute(p)&&path.normalize(p)===p&&!/[\x00-\x1f]/.test(p),'PACKAGE_PATH');return p;}
function read(p,max=64*1024**2){safe(p);check(fs.realpathSync(p)===p,'PACKAGE_SYMLINK');const fd=fs.openSync(p,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);try{const st=fs.fstatSync(fd);check(st.isFile()&&st.size<=max,'PACKAGE_FILE_BOUND');const b=fs.readFileSync(fd);check(b.length===st.size,'PACKAGE_FILE_CHANGED');return b;}finally{fs.closeSync(fd);}}
export function pin(p){const b=read(p);return {path:p,sha256:sha(b)};}
function verified(r){check(r&&/^[0-9a-f]{64}$/.test(r.sha256),'PACKAGE_REFERENCE');const b=read(r.path);check(sha(b)===r.sha256,'PACKAGE_REFERENCE_HASH');return b;}
function parsed(r){return JSON.parse(verified(r));}
function capabilityRef(r,token){return {path:r.path,record_token:token||r.record_token||path.basename(r.path),sha256:r.sha256};}
function launchRef(r){return {path:r.path,sha256:r.sha256};}
function refs(x){if(!x||typeof x!=='object')return [];return [...(typeof x.path==='string'&&typeof x.sha256==='string'?[x]:[]),...Object.values(x).flatMap(refs)];}
export function validateMap(m){check(m&&typeof m==='object'&&!Array.isArray(m)&&Object.keys(m).length>0&&Object.keys(m).length<=512,'PACKAGE_MAP_BOUND');let total=0;for(const [p,v] of Object.entries(m)){check(p.startsWith(PREFIX)&&path.posix.normalize(p)===p&&!/[\x00-\x1f]/.test(p),'PACKAGE_MAP_PATH');check(v&&Object.keys(v).sort().join('|')==='bytes|sha256'&&Number.isSafeInteger(v.bytes)&&v.bytes>=0&&v.bytes<=64*1024**2&&/^[a-f0-9]{64}$/.test(v.sha256),'PACKAGE_MAP_VALUE');total+=v.bytes;}check(total<=256*1024**2,'PACKAGE_MAP_TOTAL');return m;}
export function mapDiff(expected,observed){validateMap(expected);validateMap(observed);return {missing:Object.keys(expected).filter(p=>!Object.hasOwn(observed,p)).sort(),extra:Object.keys(observed).filter(p=>!Object.hasOwn(expected,p)).sort(),changed:Object.keys(expected).filter(p=>Object.hasOwn(observed,p)&&!equal(expected[p],observed[p])).sort().map(p=>({path:p,expected:expected[p],observed:observed[p]}))};}
export function inventory(root){const out={};function walk(dir,rel=''){for(const n of fs.readdirSync(dir).sort()){const p=path.join(dir,n),r=rel?rel+'/'+n:n,st=fs.lstatSync(p);check(!st.isSymbolicLink(),'PACKAGE_SOURCE_SYMLINK');if(st.isDirectory())walk(p,r);else{check(st.isFile(),'PACKAGE_SOURCE_SPECIAL_FILE');const b=read(p);out[PREFIX+r]={bytes:b.length,sha256:sha(b)};}}}walk(root);return validateMap(out);}
function seal(dir){for(const n of fs.readdirSync(dir)){const p=path.join(dir,n);if(fs.lstatSync(p).isDirectory())seal(p);else fs.chmodSync(p,0o444);}fs.chmodSync(dir,0o555);}
function publishDirectory(stage,target){seal(stage);fs.chmodSync(stage,0o700);fs.renameSync(stage,target);fs.chmodSync(target,0o555);}
function ownedParent(out){safe(out);check(!fs.existsSync(out)&&fs.realpathSync(path.dirname(out))===path.dirname(out),'PACKAGE_OUTPUT_CONFLICT');const p=fs.statSync(path.dirname(out));check(p.isDirectory(),'PACKAGE_PARENT');}
// Read exact immutable Git objects, never the mutable checkout or a dirty old export.
function exportMapped(repo,candidate,full,dest){const git=(args,max=64*1024**2)=>cp.execFileSync('git',['-C',repo,...args],{timeout:15000,maxBuffer:max});check(git(['rev-parse',candidate.commit+'^{tree}']).toString().trim()===candidate.tree,'PACKAGE_GIT_TREE');const entries=git(['ls-tree','-rz',candidate.commit]).toString().split('\0').filter(Boolean);const packageFiles={};for(const e of entries){const [meta,name]=e.split('\t');if(!name.startsWith('src/polar/'))continue;const [mode,kind,blob]=meta.split(' ');check(kind==='blob'&&['100644','100755'].includes(mode),'PACKAGE_GIT_MODE');const raw=git(['cat-file','blob',blob]);packageFiles['/app/'+name]={bytes:raw.length,sha256:sha(raw)};const p=path.join(dest,name);fs.mkdirSync(path.dirname(p),{recursive:true,mode:0o700});fs.writeFileSync(p,raw,{flag:'wx',mode:0o444});}const diff=mapDiff(full,packageFiles);if(!equal(full,packageFiles))throw Object.assign(new Error('PACKAGE_GIT_MAP_MISMATCH'),{sourceDiagnostic:{expected:full,observed:packageFiles,diff}});return diff;}
export function preparePackage(specFile,out){
  const specRaw=read(specFile),s=JSON.parse(specRaw);check(s.schema==='polar.review-package-spec/1'&&['pr32','pr37'].includes(s.protocol),'PACKAGE_SPEC_SCHEMA');check(typeof s.task==='string'&&s.task.length>0&&typeof s.owner==='string'&&s.owner.length>0,'PACKAGE_OWNER');check(s.input_classification==='INVENTED','PACKAGE_INVENTED_ONLY');ownedParent(out);
  const capture=s.diagnostics_capture||{mode:'COUNTS_ONLY'};check(capture.mode==='COUNTS_ONLY'||(capture.mode==='INVENTED_PRIVATE'&&Number.isSafeInteger(capture.max_bytes)&&capture.max_bytes>=1&&capture.max_bytes<=1024*1024),'PACKAGE_DIAGNOSTIC_POLICY');
  const build=parsed(s.build_ref),candidate={commit:build.commit,tree:build.tree};check(Object.values(candidate).every(v=>/^[a-f0-9]{40}$/.test(v))&&/^sha256:[a-f0-9]{64}$/.test(build.image_id),'PACKAGE_BUILD_IDENTITY');
  const full=validateMap(s.full_package_map_ref?parsed(s.full_package_map_ref):build.source_files),eligible=Object.fromEntries(Object.entries(full).filter(([p])=>/\.(py|json|sql)$/.test(p)));validateMap(build.source_files);check(Object.entries(build.source_files).every(([p,v])=>equal(v,full[p])),'PACKAGE_BUILD_MAP_DOMAIN');
  const code=s.code_projection_ref?parsed(s.code_projection_ref).files:null;if(s.protocol==='pr32'){check(code&&equal(code,build.code_projection)&&build.code_projection_count===Object.keys(code).length&&build.source_projection_count===Object.keys(full).length,'PACKAGE_CODE_PROJECTION');}
  else{check(equal(eligible,build.source_files),'PACKAGE_ELIGIBLE_MAP_MISMATCH');if(code)check(equal(code,eligible),'PACKAGE_CODE_PROJECTION');}
  for(const r of Object.values(s.refs||{}))verified(r);verified(s.config_template);if(s.assignment_template)verified(s.assignment_template);if(s.runner_binding_template)verified(s.runner_binding_template);
  const id=s.invocation_id||crypto.randomUUID();check(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(id),'PACKAGE_INVOCATION');const output=s.output_root||path.join(path.dirname(out),'operation-'+id),anchor=s.anchor||path.join(path.dirname(out),'anchor-'+id);for(const p of [output,anchor]){safe(p);check(!fs.existsSync(p)&&p!==out&&!p.startsWith(out+'/'),'PACKAGE_OPERATION_EXISTS');}
  const stage=out+'.preparing-'+crypto.randomUUID();fs.mkdirSync(stage,{mode:0o700});let phase='SOURCE';const emitted={};const write=(name,obj)=>{const raw=canonical(obj);fs.writeFileSync(path.join(stage,name),raw,{flag:'wx',mode:0o600});const r={path:path.join(out,name),sha256:sha(raw)};emitted[name]=r;return r;};
  try{
    const exportRoot=path.join(stage,'source-export');fs.mkdirSync(exportRoot,{mode:0o700});exportMapped(s.repo,candidate,full,exportRoot);const actual=inventory(path.join(exportRoot,'src/polar'));write('SOURCE-NAMESPACES.json',{schema:'polar.source-namespaces/1',full_package:full,eligible_code:eligible,code_projection:code,full_count:Object.keys(full).length,eligible_count:Object.keys(eligible).length,projection_count:code?Object.keys(code).length:null,rule:'Full package integrity and executable projection are distinct; no extra-file exclusions',origin:'Exact Git objects + pinned build map, not prior writable export'});check(equal(actual,full),'PACKAGE_SOURCE_MISMATCH');
    phase='CONFIG';let config=parsed(s.config_template),assignment=null;
    let configRef,assignmentRef;
    if(s.protocol==='pr32'){
      check(config.schema==='polar.hyp007-capability-config/1'&&s.assignment_template&&s.runner_binding_template&&s.refs.runner,'PACKAGE_PR32_TEMPLATES');
      config.code={...config.code,accepted_commit:candidate.commit,accepted_tree:candidate.tree,source_projection:capabilityRef(s.code_projection_ref)};config.expected_image_id=build.image_id;config.build_ref=capabilityRef(s.build_ref);config.launch.source_build_ref=capabilityRef(s.build_ref);for(const k of ['tool','observer','harness','review']){check(s.refs[k],'PACKAGE_REQUIRED_REF');config.launch[k+'_ref']=capabilityRef(s.refs[k]);}config.family_root=output;config.technical_case=s.technical_case||'pr32-invented-'+candidate.commit.slice(0,7)+'-'+id;
      assignment=parsed(s.assignment_template);check(assignment.input_classification==='INVENTED'&&assignment.mode==='TECHNICAL_FIXTURE','PACKAGE_ASSIGNMENT_SCOPE');assignment.bindings=Object.fromEntries(Object.entries(config).filter(([k])=>k!=='execution_authorization'));assignment.qa_refs[0]=capabilityRef(s.refs.review);assignmentRef=write('execution-assignment.json',assignment);config.execution_authorization={assignment_id:'pr32qa_'+id.replaceAll('-',''),sha256:assignmentRef.sha256};configRef=write('candidate-config.json',config);
    }else{
      check(config.schema.startsWith('polar.observed-launch-config/'),'PACKAGE_PR37_TEMPLATE');config.launch_id=id;config.candidate=candidate;config.image_id=build.image_id;config.runtime_image_id=build.image_id;config.refs.source_build=launchRef(s.build_ref);for(const [k,r] of Object.entries(s.refs)){if(['tool','observer','runner'].includes(k))continue;config.refs[k]=launchRef(r);}check(s.refs.observer&&s.refs.tool,'PACKAGE_REQUIRED_REF');configRef=write('observed-launch-config.json',config);
      if(config.refs.config){const run=parsed(config.refs.config);check(equal(run.candidate,candidate)&&run.image_id===build.image_id,'PACKAGE_PR37_CANDIDATE_CONFIG_IDENTITY');}
    }
    phase='BINDING';const recoveryRef=write('RECOVERY-BINDING.json',{schema:'polar.package-recovery/1',task:s.task,owner:s.owner,cleanup_owner:s.cleanup_owner||s.owner,invocation_uuid:id,output_root:output,anchor:s.protocol==='pr32'?anchor:null,status:'NOT_STARTED',guard:'NOT_ARMED_BY_GENERATOR',actual_start:null,deadline:null,action:'Use existing exact-owned cleanup with original fullID/image/all labels; preserve UNKNOWN and route named recovery. No retry/reset/prune.',authority:'Supplied by caller native task; package is metadata, not a scientific/review/execution grant'});
    const binding={schema:'polar.pr32-corrected-preparation/1',protocol:s.protocol,task:s.task,owner:s.owner,qa_parent:s.qa_parent||null,invocation_uuid:id,candidate,image_id:build.image_id,build_ref:launchRef(s.build_ref),runtime_file_map:build.runtime_file_map||build.runtime_files||null,source_projection:s.code_projection_ref?capabilityRef(s.code_projection_ref):null,candidate_source_export:path.join(out,'source-export'),candidate_config:configRef,assignment:assignmentRef,input_classification:'INVENTED',technical_case:config.technical_case||null,new_output_root:output,new_anchor:s.protocol==='pr32'?anchor:null,prestate:{output_absent:true,anchor_absent:true},unchanged_oracle:s.protocol==='pr32'?config.launch.expectations_ref:config.refs.expectations,worker_harness_unchanged:s.refs.harness,accepted_launcher:s.refs.tool,accepted_observer:s.refs.observer,recovery:recoveryRef,previous_failure:s.previous_failure||null,operation_authority:'NOT_ASSIGNED_BY_GENERATOR; caller task authority and independent final review remain separate',review_assessment:'NOT_ASSESSED_BY_GENERATOR',unchanged_ref_hashes:refs(config).map(r=>({path:r.path,sha256:r.sha256}))};const bindingRef=write('BINDING.json',binding);
    if(s.protocol==='pr32'){
      const rb=parsed(s.runner_binding_template);Object.assign(rb,{candidate,image_id:build.image_id,technical_case:config.technical_case,preparation_binding:bindingRef,candidate_config:configRef.path,candidate_config_sha256:configRef.sha256,assignment:assignmentRef.path,assignment_sha256:assignmentRef.sha256,build_ref:launchRef(s.build_ref),source_projection:launchRef(s.code_projection_ref),candidate_source_export:path.join(out,'source-export/src'),output_root:output,anchor,recovery_binding:recoveryRef.path,recovery_binding_sha256:recoveryRef.sha256,execution:'Caller native authority only; generator assigns no PASS/grant',failed_prior_family:s.previous_failure||rb.failed_prior_family});write('RUNNER-BINDING.json',rb);
    }
    write('SPEC.json',s);const external=[pin(fileURLToPath(import.meta.url)),...refs(config),...refs(assignment),s.build_ref,...Object.values(s.refs),...(s.code_projection_ref?[s.code_projection_ref]:[]),...(s.full_package_map_ref?[s.full_package_map_ref]:[])].filter(r=>r&&!r.path.startsWith(out+'/'));for(const r of external)verified(r);
    const packageBody={diagnostics_capture:capture,generator_ref:pin(fileURLToPath(import.meta.url)),schema:'polar.review-package/1',version:VERSION,protocol:s.protocol,task:s.task,owner:s.owner,invocation_id:id,candidate,image_id:build.image_id,build_ref:launchRef(s.build_ref),config:configRef,assignment:assignmentRef,binding:bindingRef,runner:s.refs.runner||null,adapter:s.refs.observer,tool:s.refs.tool,output_root:output,anchor:s.protocol==='pr32'?anchor:null,source_root:path.join(out,'source-export/src/polar'),source_map:full,external_refs:external,review_assessment:'NOT_ASSESSED_BY_GENERATOR',authority:'Existing caller task only; no new review/scientific grant',generation:{spec_sha256:sha(specRaw),candidate_calls:0,docker_calls:0}};write('PACKAGE.json',packageBody);
    const all={};function manifestWalk(dir,rel=''){for(const name of fs.readdirSync(dir).sort()){const p=path.join(dir,name),r=rel?rel+'/'+name:name;if(fs.lstatSync(p).isDirectory())manifestWalk(p,r);else{const raw=read(p);all[r]={sha256:sha(raw),bytes:raw.length};}}}manifestWalk(stage);fs.writeFileSync(path.join(stage,'MANIFEST.json'),canonical({schema:'polar.package-manifest/1',files:all}),{flag:'wx',mode:0o600});publishDirectory(stage,out);return {status:'PREPARED_METADATA',package_root:out,manifest:pin(path.join(out,'MANIFEST.json')),package:pin(path.join(out,'PACKAGE.json')),review:'NOT_ASSESSED',candidate_calls:0};
  }catch(e){if(!fs.existsSync(stage))throw Object.assign(new Error('PACKAGE_PUBLICATION_INCOMPLETE'),{evidence:out});fs.chmodSync(stage,0o700);const failed=out+'.failed-'+id;if(e.sourceDiagnostic){const raw=canonical(e.sourceDiagnostic);fs.writeFileSync(path.join(stage,'SOURCE-MAP-DIAGNOSTIC.json'),raw.length<=256*1024?raw:canonical({status:'OVERFLOW',bytes:raw.length,diff:e.sourceDiagnostic.diff}),{flag:'wx',mode:0o600});}fs.writeFileSync(path.join(stage,'PREPARATION-FAILURE.json'),canonical({status:'FAILED_METADATA',phase,code:/^[A-Z_]+$/.test(e.message)?e.message:'PACKAGE_IO_OR_PARSE',candidate_calls:0,task:s.task}),{flag:'wx',mode:0o600});publishDirectory(stage,failed);throw Object.assign(new Error('PACKAGE_PREPARATION_FAILED'),{evidence:failed});}
}
export function checkPackage(root){safe(root);check(fs.realpathSync(root)===root,'PACKAGE_SYMLINK');const m=JSON.parse(read(path.join(root,'MANIFEST.json')));check(m.schema==='polar.package-manifest/1','PACKAGE_MANIFEST');const seen=[];function walk(d,r=''){for(const n of fs.readdirSync(d)){const p=path.join(d,n),k=r?r+'/'+n:n,st=fs.lstatSync(p);check(!st.isSymbolicLink(),'PACKAGE_SYMLINK');if(st.isDirectory())walk(p,k);else if(k!=='MANIFEST.json'){check(st.isFile()&&m.files[k],'PACKAGE_EXTRA_FILE');const b=read(p);check(m.files[k].bytes===b.length&&m.files[k].sha256===sha(b),'PACKAGE_MEMBER_HASH');seen.push(k);}}}walk(root);check(seen.length===Object.keys(m.files).length,'PACKAGE_MISSING_FILE');const p=JSON.parse(read(path.join(root,'PACKAGE.json')));check(p.schema==='polar.review-package/1','PACKAGE_SCHEMA');for(const r of p.external_refs)verified(r);check(equal(inventory(p.source_root),p.source_map),'PACKAGE_SOURCE_MISMATCH');return {status:'REFERENCES_MATCH',package_root:root,manifest:pin(path.join(root,'MANIFEST.json')),review:'NOT_ASSESSED',package:p};}
export function packageAdapter(root,{cleanup=false}={}){
  // Cleanup must remain possible when candidate sources or input references changed.
  // Bind only the original package/config/adapter; the adapter verifies full IDs/labels.
  let p;
  if(cleanup){
    const m=JSON.parse(read(path.join(root,'MANIFEST.json'))),raw=read(path.join(root,'PACKAGE.json'));
    check(m.files?.['PACKAGE.json']?.sha256===sha(raw),'PACKAGE_MEMBER_HASH');p=JSON.parse(raw);
    const config=read(p.config.path);check(sha(config)===p.config.sha256,'PACKAGE_REFERENCE_HASH');
  }else p=checkPackage(root).package;
  verified(p.adapter);return {path:p.adapter.path,config:p.config.path,output:p.output_root};
}

// Narrow collection hook for the existing synchronous adapter, not a runner.
// It never issues a command. Only an exact task-owned start that the adapter
// already performs is captured; finally/ownership/deletion remain the adapter's.
export function runWithPackageDiagnostics(root,invoke){
  const p=checkPackage(root).package,policy=p.diagnostics_capture||{mode:'COUNTS_ONLY'};
  if(policy.mode!=='INVENTED_PRIVATE')return invoke();
  const original=cp.spawnSync;let calls=0,diagnostics={status:'NO_SCENARIO_START',capture_scope:'EXPLICIT_INVENTED_TASK_ONLY'};
  cp.spawnSync=function(command,args,options){
    const start=command==='docker'&&Array.isArray(args)&&args.length===3&&args[0]==='start'&&args[1]==='--attach';
    if(!start)return original.call(cp,command,args,options);
    let owned=false;
    try{const c=JSON.parse(read(path.join(p.output_root,'container.json')));owned=c.container_id===args[2]&&c.launch_id===p.invocation_id;}catch{}
    const r=original.call(cp,command,args,options);
    if(!owned){diagnostics={status:'UNVERIFIED_START_NOT_CAPTURED'};return r;}
    try{
      check(fs.realpathSync(p.output_root)===p.output_root,'PACKAGE_OUTPUT_SYMLINK');const st=fs.lstatSync(p.output_root);check(st.isDirectory()&&st.uid===process.getuid()&&(st.mode&0o077)===0,'PACKAGE_DIAGNOSTIC_OWNER');
      const streams={};for(const name of ['stdout','stderr']){const b=Buffer.from(r[name]||''),body=b.subarray(0,policy.max_bytes);const file=path.join(p.output_root,`private-scenario-${calls}.${name}`);fs.writeFileSync(file,body,{flag:'wx',mode:0o600});streams[name]={path:file,original_bytes:b.length,retained_bytes:body.length,truncated:b.length>body.length};}
      diagnostics={schema:'polar.package-private-diagnostics/1',status:'RETAINED_BEFORE_CLEANUP',capture_scope:'EXPLICIT_INVENTED_TASK_ONLY',task:p.task,launch_id:p.invocation_id,container_id:args[2],phase:'SCENARIO_RETURN',transport_exit:r.status,signal:r.signal||null,timeout:r.error?.code==='ETIMEDOUT',command_error:r.error?'BOUNDED_COMMAND_ERROR':null,streams};
      fs.writeFileSync(path.join(p.output_root,`private-scenario-${calls}.json`),canonical(diagnostics),{flag:'wx',mode:0o600});calls++;
    }catch{diagnostics={status:'PUBLICATION_FAILED',capture_scope:'EXPLICIT_INVENTED_TASK_ONLY'};}
    return r;
  };
  try{const result=invoke();return {...result,private_diagnostics:diagnostics};}
  finally{cp.spawnSync=original;}
}
