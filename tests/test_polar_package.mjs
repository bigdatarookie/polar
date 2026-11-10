import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import cp from 'node:child_process';
import crypto from 'node:crypto';
import {preparePackage,checkPackage,packageAdapter,pin,mapDiff,runWithPackageDiagnostics,sourceDiagnosticBytes} from '../scripts/polar-package.mjs';
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
function fixture(t,protocol='pr37'){
 const root=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'polar-package-test-'));t.after(()=>{function open(p){for(const n of fs.readdirSync(p)){const f=path.join(p,n);if(fs.lstatSync(f).isDirectory()){fs.chmodSync(f,0o700);open(f);}}}open(root);fs.rmSync(root,{recursive:true,force:true});});
 const repo=path.join(root,'repo');fs.mkdirSync(repo);fs.mkdirSync(path.join(repo,'src/polar'),{recursive:true});fs.writeFileSync(path.join(repo,'src/polar/main.py'),'# synthetic only\n');fs.writeFileSync(path.join(repo,'src/polar/app.js'),'// synthetic asset\n');
 if(protocol==='pr32'){fs.mkdirSync(path.join(repo,'scripts'));fs.writeFileSync(path.join(repo,'scripts/polar_capability_worker.py'),'# inert repository worker\n');fs.chmodSync(path.join(repo,'scripts/polar_capability_worker.py'),0o755);}
 const git=(...a)=>cp.execFileSync('git',['-C',repo,...a],{encoding:'utf8'}).trim();git('init','-q');git('add','.');git('-c','user.name=Fixture','-c','user.email=fixture@localhost','commit','-qm','fixture');const candidate={commit:git('rev-parse','HEAD'),tree:git('rev-parse','HEAD^{tree}')},image='sha256:'+'1'.repeat(64);
 function file(n,o){const p=path.join(root,n);fs.writeFileSync(p,typeof o==='string'?o:JSON.stringify(o));return pin(p);}
 const full={};for(const n of ['main.py','app.js']){const b=fs.readFileSync(path.join(repo,'src/polar',n));full['/app/src/polar/'+n]={bytes:b.length,sha256:sha(b)};}const code={'src/polar/main.py':full['/app/src/polar/main.py'].sha256};
 if(protocol==='pr32')code['scripts/polar_capability_worker.py']=sha(fs.readFileSync(path.join(repo,'scripts/polar_capability_worker.py')));
 const build=file('build.json',{...candidate,image_id:image,source_files:protocol==='pr32'?full:{'/app/src/polar/main.py':full['/app/src/polar/main.py']},code_projection:code,code_projection_count:Object.keys(code).length,source_projection_count:2});const fullRef=file('full.json',full),projection=file('projection.json',{...(protocol==='pr32'?{schema:'polar.capability-source-projection/1'}:{}),files:code});
 const refs={harness:file('harness.py','# inert\n'),tool:file('tool.mjs','// inert\n'),observer:file('actual-v11-adapter.mjs','export function observedLaunch(){return {selected:"v11"}};\n'),review:file('review.md','Review NOT ASSESSED; no PASS claim\n'),input:file('input.json',{synthetic:true}),expectations:file('expectations.json',{marker:'NONE'})};
 const candidateConfig=file('candidate.json',{candidate,image_id:image});let template;
 if(protocol==='pr37')template=file('template.json',{schema:'polar.observed-launch-config/1',refs:{config:candidateConfig},candidate,image_id:image,runtime_image_id:image});
 else template=file('template.json',{schema:'polar.hyp007-capability-config/1',code:{},launch:{expectations_ref:refs.expectations},profile_id:'TEST',mode:'TECHNICAL_FIXTURE',execution_authorization:{},runtime_refs:{}});
 const spec={schema:'polar.review-package-spec/1',protocol,task:'qitem-test',owner:'fixture',repo,input_classification:'INVENTED',build_ref:build,full_package_map_ref:fullRef,config_template:template,refs};
 if(protocol==='pr32'){refs.runner=file('runner.py','# inert\n');spec.code_projection_ref=projection;spec.assignment_template=file('assignment.json',{mode:'TECHNICAL_FIXTURE',input_classification:'INVENTED',family_id:'TEST',bindings:{},qa_refs:[refs.review]});spec.runner_binding_template=file('runner-binding.json',{schema:'polar.pr32-system-runner-binding/1'});}
 const specFile=file('spec.json',spec).path,out=path.join(root,'package');return {root,repo,spec,specFile,out,full,file};
}
test('PR37 derives coherent immutable package, distinct full/eligible maps, no review verdict',t=>{const f=fixture(t);const r=preparePackage(f.specFile,f.out);assert.equal(r.status,'PREPARED_METADATA');const checked=checkPackage(f.out),p=checked.package;assert.equal(p.review_assessment,'NOT_ASSESSED_BY_GENERATOR');const n=JSON.parse(fs.readFileSync(path.join(f.out,'SOURCE-NAMESPACES.json')));assert.equal(n.full_count,2);assert.equal(n.eligible_count,1);assert.equal(fs.statSync(f.out).mode&0o777,0o555);assert(!fs.existsSync(p.output_root));assert.equal(packageAdapter(f.out).path,f.spec.refs.observer.path);});
test('PR32 nested assignment/config/runner SHA and fresh paths derive in one pass',t=>{const f=fixture(t,'pr32');preparePackage(f.specFile,f.out);const p=checkPackage(f.out).package,c=JSON.parse(fs.readFileSync(p.config.path)),a=JSON.parse(fs.readFileSync(p.assignment.path)),rb=JSON.parse(fs.readFileSync(path.join(f.out,'RUNNER-BINDING.json')));assert.equal(c.execution_authorization.sha256,p.assignment.sha256);assert.deepEqual(a.bindings,Object.fromEntries(Object.entries(c).filter(([k])=>k!=='execution_authorization')));assert.equal(rb.candidate_config_sha256,p.config.sha256);assert.equal(rb.assignment_sha256,p.assignment.sha256);assert.equal(rb.output_root,c.family_root);assert(!fs.existsSync(rb.anchor));});
test('sealed package rejects extra file; cleanup selector still resolves original adapter/config',t=>{const f=fixture(t);preparePackage(f.specFile,f.out);fs.chmodSync(f.out,0o700);fs.writeFileSync(path.join(f.out,'extra'),'x');assert.throws(()=>checkPackage(f.out),/PACKAGE_EXTRA_FILE/);assert.equal(packageAdapter(f.out,{cleanup:true}).path,f.spec.refs.observer.path);});
test('changed external adapter fails before load',t=>{const f=fixture(t);preparePackage(f.specFile,f.out);fs.writeFileSync(f.spec.refs.observer.path,'changed');assert.throws(()=>packageAdapter(f.out),/PACKAGE_REFERENCE_HASH/);});
test('source hash/member and symlink changes fail closed',t=>{const f=fixture(t);preparePackage(f.specFile,f.out);const src=path.join(f.out,'source-export/src/polar');fs.chmodSync(src,0o700);fs.unlinkSync(path.join(src,'main.py'));fs.symlinkSync(path.join(f.repo,'src/polar/main.py'),path.join(src,'main.py'));assert.throws(()=>checkPackage(f.out),/PACKAGE_SYMLINK/);});
test('wrong full namespace retains failure without operation or import',t=>{const f=fixture(t);f.spec.full_package_map_ref=f.file('wrong-full.json',{'/app/src/polar/main.py':f.full['/app/src/polar/main.py']});fs.writeFileSync(f.specFile,JSON.stringify(f.spec));let e;try{preparePackage(f.specFile,f.out);}catch(x){e=x;}assert.equal(e.message,'PACKAGE_PREPARATION_FAILED');const r=JSON.parse(fs.readFileSync(path.join(e.evidence,'PREPARATION-FAILURE.json')));assert.equal(r.phase,'SOURCE');assert.equal(r.candidate_calls,0);assert(!fs.existsSync(f.out));});
test('retained class rejected and existing package never overwritten',t=>{const f=fixture(t);preparePackage(f.specFile,f.out);assert.throws(()=>preparePackage(f.specFile,f.out),/PACKAGE_OUTPUT_CONFLICT/);f.spec.input_classification='RETAINED';fs.writeFileSync(f.specFile,JSON.stringify(f.spec));assert.throws(()=>preparePackage(f.specFile,path.join(f.root,'other')),/PACKAGE_INVENTED_ONLY/);});
test('map diff identifies missing, extra and changed without dropping assets',()=>{const v={bytes:1,sha256:'a'.repeat(64)},w={bytes:2,sha256:'b'.repeat(64)};const d=mapDiff({'/app/src/polar/a.py':v,'/app/src/polar/app.js':v},{'/app/src/polar/a.py':w,'/app/src/polar/extra.js':v});assert.deepEqual(d.missing,['/app/src/polar/app.js']);assert.deepEqual(d.extra,['/app/src/polar/extra.js']);assert.equal(d.changed[0].path,'/app/src/polar/a.py');});
test('PR37 refuses eligible subset mismatch instead of dropping assets or code',t=>{const f=fixture(t);const build=JSON.parse(fs.readFileSync(f.spec.build_ref.path));build.source_files['/app/src/polar/app.js']=f.full['/app/src/polar/app.js'];f.spec.build_ref=f.file('wrong-build.json',build);fs.writeFileSync(f.specFile,JSON.stringify(f.spec));assert.throws(()=>preparePackage(f.specFile,f.out),/PACKAGE_ELIGIBLE_MAP_MISMATCH/);});
test('private synthetic capture retains bounded failure body before adapter cleanup and restores hook',t=>{const f=fixture(t);f.spec.diagnostics_capture={mode:'INVENTED_PRIVATE',max_bytes:8};fs.writeFileSync(f.specFile,JSON.stringify(f.spec));preparePackage(f.specFile,f.out);const p=checkPackage(f.out).package;fs.mkdirSync(p.output_root,{mode:0o700});fs.writeFileSync(path.join(p.output_root,'container.json'),JSON.stringify({container_id:'a'.repeat(64),launch_id:p.invocation_id}));const old=cp.spawnSync;cp.spawnSync=()=>({status:1,stdout:'1234567890',stderr:'Traceback: fixture failure',signal:null});const stub=cp.spawnSync;try{const r=runWithPackageDiagnostics(f.out,()=>{cp.spawnSync('docker',['start','--attach','a'.repeat(64)],{});assert.equal(fs.readFileSync(path.join(p.output_root,'private-scenario-0.stderr'),'utf8'),'Tracebac');assert(fs.existsSync(path.join(p.output_root,'private-scenario-0.json')));return {scenario:'FAIL',cleanup:{status:'REMOVED'}};});assert.equal(r.private_diagnostics.status,'RETAINED_BEFORE_CLEANUP');assert.equal(r.private_diagnostics.streams.stderr.truncated,true);assert.equal(r.private_diagnostics.transport_exit,1);assert.equal(cp.spawnSync,stub);}finally{cp.spawnSync=old;}});
test('ordinary path does not capture streams without explicit synthetic policy',t=>{const f=fixture(t);preparePackage(f.specFile,f.out);const before=cp.spawnSync;assert.deepEqual(runWithPackageDiagnostics(f.out,()=>({status:'unchanged'})),{status:'unchanged'});assert.equal(cp.spawnSync,before);});
for(const declaredCount of [1,2])test(`PR32 rejects build subset of full map in SOURCE phase with retained diff (declared count ${declaredCount})`,t=>{
 const f=fixture(t,'pr32'),b=JSON.parse(fs.readFileSync(f.spec.build_ref.path));b.source_files={'/app/src/polar/main.py':f.full['/app/src/polar/main.py']};b.source_projection_count=declaredCount;f.spec.build_ref=f.file('subset-build.json',b);fs.writeFileSync(f.specFile,JSON.stringify(f.spec));let error;
 try{preparePackage(f.specFile,f.out);}catch(e){error=e;}
 assert.equal(error?.message,'PACKAGE_PREPARATION_FAILED');const failure=JSON.parse(fs.readFileSync(path.join(error.evidence,'PREPARATION-FAILURE.json'))),diagnostic=JSON.parse(fs.readFileSync(path.join(error.evidence,'SOURCE-MAP-DIAGNOSTIC.json')));
 assert.equal(failure.phase,'SOURCE');assert.equal(failure.code,'PACKAGE_PR32_BUILD_FULL_MAP_MISMATCH');assert.equal(failure.candidate_calls,0);assert.deepEqual(diagnostic.diff.missing,['/app/src/polar/app.js']);assert.deepEqual(diagnostic.diff.extra,[]);assert.deepEqual(diagnostic.diff.changed,[]);assert.equal(Object.keys(diagnostic.expected).length,2);assert.equal(Object.keys(diagnostic.observed).length,1);assert(!fs.existsSync(f.out));assert(!fs.existsSync(path.join(error.evidence,'source-export')));
});

test('overflow source diff retains bounded counts without repeating oversized path arrays',()=>{
 const expected={},observed={};for(let i=0;i<300;i++)expected['/app/src/polar/'+String(i)+'x'.repeat(1024)+'.py']={bytes:1,sha256:'a'.repeat(64)};observed['/app/src/polar/only.py']={bytes:1,sha256:'b'.repeat(64)};const raw=sourceDiagnosticBytes({expected,observed,diff:mapDiff(expected,observed)}),summary=JSON.parse(raw);assert(raw.length<=256*1024);assert.equal(summary.status,'OVERFLOW');assert.equal(summary.diff_counts.missing,300);assert.equal(summary.diff_counts.extra,1);assert(!Object.hasOwn(summary,'diff'));
});

// The real PR32 defect was a repository worker outside src/polar; no Python import/run is needed.
test('PR32 exports the immutable repository worker without mixing full and code namespaces',t=>{
 const f=fixture(t,'pr32');fs.writeFileSync(path.join(f.repo,'scripts/polar_capability_worker.py'),'# dirty checkout must not be exported\n');
 preparePackage(f.specFile,f.out);const p=checkPackage(f.out).package,worker=path.join(p.repository_root,'scripts/polar_capability_worker.py');
 assert.equal(fs.readFileSync(worker,'utf8'),'# inert repository worker\n');assert.equal(fs.statSync(worker).mode&0o777,0o555);
 assert.equal(p.repository_projection['scripts/polar_capability_worker.py'].sha256,sha(fs.readFileSync(worker)));
 assert.deepEqual(Object.keys(p.source_map).sort(),Object.keys(f.full).sort());
 const n=JSON.parse(fs.readFileSync(path.join(f.out,'SOURCE-NAMESPACES.json')));assert.equal(n.full_count,2);assert.equal(n.eligible_count,1);assert.equal(n.projection_count,2);
 assert(!fs.existsSync(p.output_root));assert(!fs.existsSync(p.anchor));
});
for(const problem of ['missing','changed','unsafe'])test(`PR32 repository projection ${problem} fails before config or invocation`,t=>{
 const f=fixture(t,'pr32'),b=JSON.parse(fs.readFileSync(f.spec.build_ref.path));
 if(problem==='missing')b.code_projection['scripts/missing_worker.py']='a'.repeat(64);
 if(problem==='changed')b.code_projection['scripts/polar_capability_worker.py']='b'.repeat(64);
 if(problem==='unsafe')b.code_projection['../outside.py']='c'.repeat(64);
 b.code_projection_count=Object.keys(b.code_projection).length;f.spec.build_ref=f.file('projection-build.json',b);f.spec.code_projection_ref=f.file('projection-new.json',{schema:'polar.capability-source-projection/1',files:b.code_projection});fs.writeFileSync(f.specFile,JSON.stringify(f.spec));
 let error;try{preparePackage(f.specFile,f.out);}catch(e){error=e;}
 assert.equal(error?.message,'PACKAGE_PREPARATION_FAILED');const failure=JSON.parse(fs.readFileSync(path.join(error.evidence,'PREPARATION-FAILURE.json')));
 assert.equal(failure.phase,'SOURCE');assert.equal(failure.candidate_calls,0);assert.equal(failure.code,{missing:'PACKAGE_REPOSITORY_GIT_MISSING',changed:'PACKAGE_REPOSITORY_GIT_HASH',unsafe:'PACKAGE_REPOSITORY_PATH'}[problem]);assert(!fs.existsSync(f.out));assert(!fs.existsSync(path.join(error.evidence,'candidate-config.json')));
});
test('PR32 checks repository worker against build even if a changed member manifest is recomputed',t=>{
 const f=fixture(t,'pr32');preparePackage(f.specFile,f.out);const worker=path.join(f.out,'source-export/scripts/polar_capability_worker.py');fs.chmodSync(worker,0o755);fs.writeFileSync(worker,'# changed after publication\n');fs.chmodSync(worker,0o555);
 const manifest=path.join(f.out,'MANIFEST.json'),m=JSON.parse(fs.readFileSync(manifest)),raw=fs.readFileSync(worker);m.files['source-export/scripts/polar_capability_worker.py']={bytes:raw.length,sha256:sha(raw)};fs.chmodSync(manifest,0o644);fs.writeFileSync(manifest,JSON.stringify(m));
 assert.throws(()=>checkPackage(f.out),/PACKAGE_REPOSITORY_HASH/);
});

for(const protocol of ['pr32','pr37'])test(`${protocol} rejects relocated source export even after the member manifest is recomputed`,t=>{
 const f=fixture(t,protocol);preparePackage(f.specFile,f.out);
 const packageFile=path.join(f.out,'PACKAGE.json'),p=JSON.parse(fs.readFileSync(packageFile));
 const outside=path.join(f.root,'outside-export');fs.chmodSync(f.out,0o700);fs.chmodSync(path.join(f.out,'source-export'),0o700);fs.renameSync(path.join(f.out,'source-export'),outside);
 p.source_root=path.join(outside,'src/polar');if(protocol==='pr32')p.repository_root=outside;
 fs.chmodSync(packageFile,0o644);fs.writeFileSync(packageFile,JSON.stringify(p));
 const files={};function walk(dir,rel=''){for(const name of fs.readdirSync(dir)){const file=path.join(dir,name),key=rel?rel+'/'+name:name;if(fs.statSync(file).isDirectory())walk(file,key);else if(key!=='MANIFEST.json'){const raw=fs.readFileSync(file);files[key]={bytes:raw.length,sha256:sha(raw)};}}}walk(f.out);
 const manifest=path.join(f.out,'MANIFEST.json');fs.chmodSync(manifest,0o644);fs.writeFileSync(manifest,JSON.stringify({schema:'polar.package-manifest/1',files}));
 assert.throws(()=>checkPackage(f.out),/PACKAGE_SOURCE_ROOT/);
 assert(!fs.existsSync(p.output_root));if(p.anchor)assert(!fs.existsSync(p.anchor));
});
test('PR32 rejects an external repository root while its source root remains in-package',t=>{
 const f=fixture(t,'pr32');preparePackage(f.specFile,f.out);
 const packageFile=path.join(f.out,'PACKAGE.json'),p=JSON.parse(fs.readFileSync(packageFile));
 p.repository_root=f.repo;fs.chmodSync(packageFile,0o644);fs.writeFileSync(packageFile,JSON.stringify(p));
 const manifest=path.join(f.out,'MANIFEST.json'),m=JSON.parse(fs.readFileSync(manifest)),raw=fs.readFileSync(packageFile);m.files['PACKAGE.json']={bytes:raw.length,sha256:sha(raw)};fs.chmodSync(manifest,0o644);fs.writeFileSync(manifest,JSON.stringify(m));
 assert.throws(()=>checkPackage(f.out),/PACKAGE_REPOSITORY_ROOT/);assert(!fs.existsSync(p.output_root));assert(!fs.existsSync(p.anchor));
});

for(const problem of ['build-namespace','missing-schema','extra-field'])test(`PR32 refuses ${problem} source projection before config or consumer use`,t=>{
 const f=fixture(t,'pr32'),projection=JSON.parse(fs.readFileSync(f.spec.code_projection_ref.path));
 if(problem==='build-namespace')projection.schema='polar.capability-code-projection/1';
 if(problem==='missing-schema')delete projection.schema;
 if(problem==='extra-field')projection.note='not in the closed candidate contract';
 f.spec.code_projection_ref=f.file('wrong-namespace.json',projection);fs.writeFileSync(f.specFile,JSON.stringify(f.spec));let error;
 try{preparePackage(f.specFile,f.out);}catch(e){error=e;}
 assert.equal(error?.message,'PACKAGE_PREPARATION_FAILED');const failure=JSON.parse(fs.readFileSync(path.join(error.evidence,'PREPARATION-FAILURE.json')));
 assert.equal(failure.phase,'SOURCE');assert.equal(failure.code,'PACKAGE_PR32_SOURCE_PROJECTION_SCHEMA');assert.equal(failure.candidate_calls,0);assert(!fs.existsSync(f.out));assert(!fs.existsSync(path.join(error.evidence,'candidate-config.json')));
});
test('PR32 checker rejects a rehashed candidate projection with the build namespace',t=>{
 const f=fixture(t,'pr32');preparePackage(f.specFile,f.out);const packageFile=path.join(f.out,'PACKAGE.json'),p=JSON.parse(fs.readFileSync(packageFile));
 const config=JSON.parse(fs.readFileSync(p.config.path)),projection=JSON.parse(fs.readFileSync(config.code.source_projection.path));projection.schema='polar.capability-code-projection/1';
 fs.writeFileSync(config.code.source_projection.path,JSON.stringify(projection));config.code.source_projection.sha256=sha(fs.readFileSync(config.code.source_projection.path));
 fs.chmodSync(p.config.path,0o644);fs.writeFileSync(p.config.path,JSON.stringify(config));p.config.sha256=sha(fs.readFileSync(p.config.path));fs.chmodSync(packageFile,0o644);fs.writeFileSync(packageFile,JSON.stringify(p));
 const manifest=path.join(f.out,'MANIFEST.json'),m=JSON.parse(fs.readFileSync(manifest));for(const name of ['PACKAGE.json','candidate-config.json']){const raw=fs.readFileSync(path.join(f.out,name));m.files[name]={bytes:raw.length,sha256:sha(raw)};}fs.chmodSync(manifest,0o644);fs.writeFileSync(manifest,JSON.stringify(m));
 assert.throws(()=>checkPackage(f.out),/PACKAGE_PR32_SOURCE_PROJECTION_SCHEMA/);assert(!fs.existsSync(p.output_root));assert(!fs.existsSync(p.anchor));
});
