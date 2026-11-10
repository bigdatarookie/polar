import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import cp from 'node:child_process';
import {retainedPlan,stageRetained,verifyRetained,artifactIdentity,observedMounts} from '../scripts/polar-retained-mounts.mjs';
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
function fixture(t) {
  const root=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'polar-retained-test-'));fs.chmodSync(root,0o700);
  t.after(()=>{for(const p of [root,path.join(root,'launch'),path.join(root,'launch','retained')])if(fs.existsSync(p))fs.chmodSync(p,0o700);fs.rmSync(root,{recursive:true,force:true});});
  const artifacts=path.join(root,'artifacts');fs.mkdirSync(artifacts,{mode:0o777});fs.chmodSync(artifacts,0o777);
  fs.writeFileSync(path.join(artifacts,'ledger'),'must persist');const stat=fs.statSync(artifacts,{bigint:true});
  const input=path.join(root,'data.bin');const raw=Buffer.alloc(2*1024**2+37,0x41);fs.writeFileSync(input,raw);
  const out=path.join(root,'launch');fs.mkdirSync(out,{mode:0o700});const bindings=path.join(out,'bindings');fs.mkdirSync(bindings);
  return {root,artifacts,input,raw,out,bindings,value:{artifact_root:{path:artifacts,device:stat.dev.toString(),inode:stat.ino.toString()},read_only:[{path:input,target:'/retained/original.bin',sha256:hash(raw),bytes:raw.length}]}};
}
test('streams a multi-MiB retained file into sealed staging and preserves input and ledger',t=>{
  const f=fixture(t),plan=retainedPlan(f.value,{},'/bin/python',f.out),staged=stageRetained(plan,f.out,f.bindings);
  verifyRetained(staged);assert(fs.readFileSync(staged.files[0].staged).equals(f.raw));
  assert.equal(fs.statSync(staged.files[0].staged).mode&0o777,0o444);
  assert.equal(fs.statSync(path.dirname(staged.files[0].staged)).mode&0o777,0o555);
  assert(fs.readFileSync(f.input).equals(f.raw));assert.equal(fs.readFileSync(path.join(f.artifacts,'ledger'),'utf8'),'must persist');
});
test('persistent root replacement is refused even at the same canonical path',t=>{
  const f=fixture(t);fs.renameSync(f.artifacts,f.artifacts+'-old');fs.mkdirSync(f.artifacts,{mode:0o777});fs.chmodSync(f.artifacts,0o777);
  assert.throws(()=>artifactIdentity(f.value.artifact_root),/ARTIFACT_ROOT_IDENTITY/);
});
test('private-parent and writable-root permissions are checked without changing them',t=>{
  const f=fixture(t);fs.chmodSync(f.artifacts,0o700);assert.throws(()=>artifactIdentity(f.value.artifact_root),/ARTIFACT_ROOT_PERMISSIONS/);
  assert.equal(fs.statSync(f.artifacts).mode&0o777,0o700);
});
test('bad retained hash fails closed',t=>{
  const f=fixture(t),plan=retainedPlan(f.value,{},'/bin/python',f.out);plan.files[0].sha256='0'.repeat(64);
  assert.throws(()=>stageRetained(plan,f.out,f.bindings),/RETAINED_HASH_MISMATCH/);
});
test('the container filesystem root cannot be a file target',t=>{
  const f=fixture(t);f.value.read_only[0].target='/';
  assert.throws(()=>retainedPlan(f.value,{},'/bin/python',f.out),/RETAINED_PATH/);
});
test('staged tampering is detected at consumption',t=>{
  const f=fixture(t),staged=stageRetained(retainedPlan(f.value,{},'/bin/python',f.out),f.out,f.bindings);
  fs.chmodSync(staged.files[0].staged,0o644);fs.writeFileSync(staged.files[0].staged,Buffer.alloc(f.raw.length,0x42));
  assert.throws(()=>verifyRetained(staged),/RETAINED_HASH_MISMATCH/);
});
test('a staged FIFO replacement is refused without blocking the launcher',t=>{
  const f=fixture(t),staged=stageRetained(retainedPlan(f.value,{},'/bin/python',f.out),f.out,f.bindings);
  fs.chmodSync(path.dirname(staged.files[0].staged),0o700);fs.unlinkSync(staged.files[0].staged);
  assert.equal(cp.spawnSync('mkfifo',[staged.files[0].staged],{timeout:2000}).status,0);
  assert.throws(()=>verifyRetained(staged),/RETAINED_FILE_BOUND/);
});
test('existing reference alias must match bytes/hash and is not mounted twice',t=>{
  const f=fixture(t),ref=f.value.read_only[0];ref.target='/input-bound.json';
  const refs={input:{path:ref.target,sha256:ref.sha256,bytes:ref.bytes}};
  fs.copyFileSync(f.input,path.join(f.bindings,'input'));
  const staged=stageRetained(retainedPlan(f.value,refs,'/bin/python',f.out),f.out,f.bindings);
  assert.equal(staged.files[0].existing_reference,'input');assert.equal(staged.files[0].staged,path.join(f.bindings,'input'));
  refs.input.sha256='0'.repeat(64);assert.throws(()=>retainedPlan(f.value,refs,'/bin/python',f.out),/RETAINED_REFERENCE_OVERLAP/);
});
test('duplicate, source, entrypoint and persistent-output target overlays are refused',t=>{
  const f=fixture(t),initial={...f.value.read_only[0]};
  for(const target of ['/app','/polar-launch/preparation.json','/polar-output','/polar-artifacts/x','/bin/python']) {
    f.value.read_only=[{...initial,target}];assert.throws(()=>retainedPlan(f.value,{},'/bin/python',f.out),/RETAINED_TARGET_OVERLAP/);
  }
  f.value.read_only=[initial,{...initial}];assert.throws(()=>retainedPlan(f.value,{},'/bin/python',f.out),/RETAINED_TARGET_OVERLAP/);
});
test('symlinks and declared oversize inputs are refused without reading or mutating them',t=>{
  const f=fixture(t);fs.symlinkSync(f.input,path.join(f.root,'alias'));f.value.read_only[0].path=path.join(f.root,'alias');
  assert.throws(()=>retainedPlan(f.value,{},'/bin/python',f.out),/RETAINED_PATH/);
  f.value.read_only[0].path=f.input;f.value.read_only[0].bytes=256*1024**2+1;
  assert.throws(()=>retainedPlan(f.value,{},'/bin/python',f.out),/RETAINED_FILE_BOUND/);
});
test('actual mount graph must exactly match declared directions and identities',()=>{
  const expected=[{source:'/private/tmp/fixture',target:'/retained/input',writable:false},{source:'/private/tmp/artifacts',target:'/polar-artifacts',writable:true}];
  const c={Id:'c'.repeat(64),Mounts:expected.map(m=>({Type:'bind',Source:m.source,Destination:m.target,RW:m.writable}))};
  assert.equal(observedMounts(c,expected).all_mounts_exact,true);
  c.Mounts[0].RW=true;assert.throws(()=>observedMounts(c,expected),/RETAINED_MOUNT_MISMATCH/);
  c.Mounts[0].RW=false;c.Mounts.push({Type:'volume',Source:'/extra',Destination:'/extra',RW:true});
  assert.throws(()=>observedMounts(c,expected),/RETAINED_MOUNT_MISMATCH/);
});
