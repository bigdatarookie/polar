// Optional retained-file/persistent-output seam for the existing observed launcher.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';

const check=(v,c)=>assert(v,c);
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const overlaps=(a,b)=>a===b||a.startsWith(b+'/')||b.startsWith(a+'/');
const exact=(v,keys)=>check(v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join('|')===keys.sort().join('|'),'RETAINED_FIELDS');
function absolute(p) {
  check(typeof p==='string'&&p!=='/'&&p.length<=4096&&path.posix.isAbsolute(p)&&path.posix.normalize(p)===p&&!/[\x00-\x1f,]/.test(p),'RETAINED_PATH');return p;
}
export function artifactIdentity(ref) {
  exact(ref,['path','device','inode']);absolute(ref.path);
  check(fs.realpathSync(ref.path)===ref.path,'ARTIFACT_ROOT_IDENTITY');
  const st=fs.lstatSync(ref.path,{bigint:true}),parent=fs.lstatSync(path.dirname(ref.path));
  check(st.isDirectory()&&st.uid===BigInt(process.getuid())&&st.dev.toString()===ref.device&&st.ino.toString()===ref.inode,'ARTIFACT_ROOT_IDENTITY');
  check((st.mode&0o002n)!==0n&&parent.isDirectory()&&parent.uid===process.getuid()&&(parent.mode&0o077)===0,'ARTIFACT_ROOT_PERMISSIONS');
  return {...ref,uid:Number(st.uid),mode:Number(st.mode&0o777n).toString(8).padStart(4,'0'),container_target:'/polar-artifacts',writable:true};
}
export function retainedPlan(value,refs,entrypoint,out) {
  exact(value,['read_only','artifact_root']);
  check(Array.isArray(value.read_only)&&value.read_only.length>0&&value.read_only.length<=512,'RETAINED_FILE_BOUND');
  const artifact=artifactIdentity(value.artifact_root);
  check(!overlaps(artifact.path,out),'ARTIFACT_OUTPUT_OVERLAP');
  const destinations=[],files=[];let total=0;
  for(const ref of value.read_only) {
    exact(ref,['path','target','sha256','bytes']);absolute(ref.path);absolute(ref.target);
    check(/^[a-f0-9]{64}$/.test(ref.sha256)&&Number.isSafeInteger(ref.bytes)&&ref.bytes>=0&&ref.bytes<=256*1024**2,'RETAINED_FILE_BOUND');
    total+=ref.bytes;check(total<=1024**3,'RETAINED_TOTAL_BOUND');
    check(fs.realpathSync(ref.path)===ref.path&&!overlaps(ref.path,artifact.path)&&!overlaps(ref.path,out),'RETAINED_PATH');
    const st=fs.lstatSync(ref.path);check(st.isFile()&&st.size===ref.bytes,'RETAINED_FILE_BOUND');
    check(!['/app','/polar-launch','/polar-output','/polar-artifacts',entrypoint].some(p=>overlaps(ref.target,p)),'RETAINED_TARGET_OVERLAP');
    check(!destinations.some(p=>overlaps(p,ref.target)),'RETAINED_TARGET_OVERLAP');destinations.push(ref.target);
    let existing=null;
    for(const [key,r] of Object.entries(refs))if(overlaps(r.path,ref.target)) {
      check(r.path===ref.target&&r.sha256===ref.sha256&&r.bytes===ref.bytes,'RETAINED_REFERENCE_OVERLAP');existing=key;
    }
    files.push({...ref,existing_reference:existing});
  }
  return {files,total_bytes:total,artifact};
}
function fileDigest(file,expected,destination=null) {
  const input=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);let output=null;
  try {
    const st=fs.fstatSync(input);check(st.isFile()&&st.size===expected.bytes,'RETAINED_FILE_BOUND');
    if(destination)output=fs.openSync(destination,'wx',0o444);
    const digest=crypto.createHash('sha256'),buffer=Buffer.alloc(64*1024);let total=0,n;
    while((n=fs.readSync(input,buffer,0,buffer.length,null))) {
      total+=n;check(total<=expected.bytes,'RETAINED_FILE_CHANGED');digest.update(buffer.subarray(0,n));
      if(output!==null){let offset=0;while(offset<n)offset+=fs.writeSync(output,buffer,offset,n-offset);}
    }
    check(total===expected.bytes&&digest.digest('hex')===expected.sha256,'RETAINED_HASH_MISMATCH');
    if(output!==null){fs.fchmodSync(output,0o444);fs.fsyncSync(output);}
  } finally {fs.closeSync(input);if(output!==null)fs.closeSync(output);}
}
export function stageRetained(plan,out,bindings) {
  const dir=path.join(out,'retained');fs.mkdirSync(dir,{mode:0o700});const files=[];
  for(const [i,ref] of plan.files.entries()) {
    const staged=ref.existing_reference?path.join(bindings,ref.existing_reference):path.join(dir,String(i));
    if(ref.existing_reference)fileDigest(staged,ref);else fileDigest(ref.path,ref,staged);
    files.push({...ref,staged});
  }
  fs.chmodSync(dir,0o555);return {...plan,files};
}
export function verifyRetained(plan) {
  artifactIdentity({path:plan.artifact.path,device:plan.artifact.device,inode:plan.artifact.inode});
  for(const ref of plan.files)fileDigest(ref.staged,ref);
}
export function observedMounts(container,expected) {
  check(Array.isArray(container.Mounts),'RETAINED_MOUNT_MISMATCH');
  const clean=m=>({source:m.Source,target:m.Destination,writable:m.RW,type:m.Type});
  const actual=container.Mounts.map(clean).sort((a,b)=>a.target.localeCompare(b.target));
  const wanted=expected.map(m=>({...m,type:'bind'})).sort((a,b)=>a.target.localeCompare(b.target));
  check(sha(JSON.stringify(actual))===sha(JSON.stringify(wanted)),'RETAINED_MOUNT_MISMATCH');
  return {schema:'polar.observed-retained-mounts/1',container_id:container.Id,all_mounts_exact:true,mounts:wanted};
}
