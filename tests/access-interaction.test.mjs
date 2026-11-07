import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import {pacing,allowedURL,selectVerification,qualification,privateFields,AccessSession,AccessError,cliExecutor} from '../scripts/access-interaction.mjs';

function directory(t){const root=fs.mkdtempSync('/private/tmp/polar-access-unit-');fs.chmodSync(root,0o700);t.after(()=>fs.rmSync(root,{recursive:true}));return root;}
const fast={actions:[0,0],keys:[0,0],scroll:[0,0],seed:7};
const setup=(t,extra={})=>new AccessSession({session:'owned-fixture',privateDir:directory(t),hosts:['example.com'],profile:fast,pause:async()=>{},...extra});

test('seeded separate jitter bounds and aggregate receipts',()=>{
  const a=pacing({actions:[6,12],keys:[1,4],scroll:[3,9],seed:42});const b=pacing(a.profile);
  for(const kind of ['actions','keys','scroll'])for(let i=0;i<100;i++){
    const x=a.next(kind);assert.equal(x,b.next(kind));assert.ok(x>=a.profile[kind][0]&&x<=a.profile[kind][1]);
  }
  assert.equal(a.aggregate.actions.count,100);assert.throws(()=>pacing({seed:-1}),/INVALID_PACING/);
  assert.throws(()=>pacing({actions:[10,2]}),/INVALID_PACING/);
});

test('exact HTTPS hosts, no lookalikes/userinfo/other ports',()=>{
  assert.equal(allowedURL('https://example.com/verify',['example.com']),'https://example.com/verify');
  for(const u of ['http://example.com/','https://example.com.evil/','https://example.com@evil/','https://evil@example.com/',
                  'https://example.com:444/','https://example.com./','javascript:alert(1)'])assert.throws(()=>allowedURL(u,['example.com']),/UNSAFE_DESTINATION/);
});

test('targeted visible localized verification messages only',()=>{
  const rows=[{visible:false,provider:'example',operation:'verification',label:'Подтвердить',href:'https://evil/'},
    {visible:true,provider:'other',operation:'verification',label:'Подтвердить',href:'https://evil/'},
    {visible:true,provider:'example',operation:'verification',label:' Подтвердить ',href:'https://example.com/verify'}];
  const query={provider:'example',operation:'verification',visibleLabels:['Verify','Подтвердить'],hosts:['example.com']};
  assert.equal(selectVerification(rows,query),'https://example.com/verify');
  assert.throws(()=>selectVerification([...rows,rows[2]],query),/MAILBOX_AMBIGUOUS/);
  assert.throws(()=>selectVerification([{...rows[2],href:'https://evil/'}],query),/UNSAFE_DESTINATION/);
});

test('dashboard/auth never infer entitlement, required data, rights or fitness',()=>{
  const q={account:'PASS',email:'PASS',dashboard:'OBSERVED',api_auth:'PASS',entitlement:'FAIL',required_data:'NOT_RUN',rights:'UNKNOWN',fitness:'NOT_RUN'};
  assert.deepEqual(qualification(q),q);assert.throws(()=>qualification({dashboard:'PASS'}),/INVALID_QUALIFICATION/);
});

test('unknown submit has observation checkpoint and cannot dispatch twice; resume same session',async t=>{
  let clicks=0;const execute=async source=>{if(source.includes('loc.click')){clicks++;throw new Error('timeout');}return {observed:true};};
  const s=setup(t,{execute});await assert.rejects(s.mutate('signup','submit',{role:'button',name:'Continue'}),/UNKNOWN_EFFECT/);
  const resumed=new AccessSession({session:s.session,privateDir:s.directory,hosts:['example.com'],profile:fast,execute});
  await assert.rejects(resumed.mutate('signup','submit',{role:'button',name:'Continue'}),/OBSERVE_BEFORE_RETRY/);
  assert.equal(clicks,1);resumed.observe('signup','confirmed',{'dashboard-observed':true});
  assert.equal((await resumed.mutate('signup','submit',{role:'button',name:'Continue'})).status,'ALREADY_CONFIRMED');
  assert.equal(clicks,1);assert.equal(resumed.receipt().pending_observation,0);
});

test('not ready and deadline do not dispatch or create a mutation checkpoint',async t=>{
  const s=setup(t,{execute:async()=>({observed:false})});
  await assert.rejects(s.mutate('login','login',{selector:'#submit'}),/NOT_READY/);assert.equal(s.states.size,0);
  let now=0;const expired=setup(t,{deadlineMs:100,now:()=>now,execute:async()=>({observed:true})});now=101;
  await assert.rejects(expired.ready({selector:'#submit'}),/ACTION_DEADLINE/);
});

test('private JSON refs are explicit, owner-only, no discovery or symlink',t=>{
  const root=directory(t);fs.writeFileSync(path.join(root,'alpaca-account.json'),JSON.stringify({email:'synthetic',password:'SYNTHETIC_SENTINEL'}),{mode:0o600});
  assert.equal(privateFields(root,{file:'alpaca-account.json',fields:['email']}).email,'synthetic');
  assert.throws(()=>privateFields(root,{file:'../other',fields:['password']}),/INVALID_PRIVATE_REFERENCE/);
  fs.symlinkSync('alpaca-account.json',path.join(root,'alpaca-api-credentials.json'));
  assert.throws(()=>privateFields(root,{file:'alpaca-api-credentials.json',fields:['endpoint']}),/PRIVATE_INPUT_UNAVAILABLE/);
});

test('private fill transports sentinel in memory, code/receipts contain no value',async t=>{
  const root=directory(t),secret='SYNTHETIC_SENTINEL';
  fs.writeFileSync(path.join(root,'alpaca-account.json'),JSON.stringify({password:secret}),{mode:0o600});
  let value='',sourceSeen='';const target={waitFor:async()=>{},count:async()=>1,isEnabled:async()=>true,
    fill:async()=>{value='';},pressSequentially:async char=>{value+=char;}};
  const execute=async source=>{sourceSeen=source;const fn=vm.runInNewContext('('+source+')',{URL,Date,setTimeout});
    return (await fn({url:()=> 'https://example.com/',locator:()=>target,request:{get:async url=>({json:async()=>await (await fetch(url)).json()})}})).polar_access;};
  const s=setup(t,{execute});const result=await s.fillPrivate(root,{file:'alpaca-account.json',fields:['password']},{password:{selector:'#password'}});
  assert.equal(result.observed,true);assert.equal(value,secret);assert.ok(!sourceSeen.includes(secret));assert.ok(!JSON.stringify(s.receipt()).includes(secret));
  assert.equal(fs.readdirSync(s.directory).length,0);
});

test('redirect guard aborts unapproved destination before continue',async t=>{
  let handler,aborted=0,continued=0,detached=false;
  const cdp={on:(_,fn)=>{handler=fn;},detach:async()=>{detached=true;},send:async(method)=>{
    if(method==='Page.getFrameTree')return {frameTree:{frame:{id:'main'}}};
    if(method==='Fetch.failRequest')aborted++;
    if(method==='Fetch.continueRequest')continued++;
  }};
  const page={context:()=>({newCDPSession:async()=>cdp}),goto:async()=>{
    handler({frameId:'main',requestId:'redirect',request:{url:'https://evil/'}});
    await new Promise(r=>setTimeout(r,0));throw Error('blocked');
  }};
  const s=setup(t,{execute:async source=>(await vm.runInNewContext('('+source+')',{URL,Promise})(page)).polar_access});
  const result=await s.followVerification('verify','https://example.com/verify');
  assert.equal(result.status,'UNKNOWN_EFFECT');assert.equal(result.observed,false);assert.equal(aborted,1);assert.equal(continued,0);assert.equal(detached,true);
});

test('partial checkpoint refuses resume',t=>{
  const root=directory(t);fs.writeFileSync(path.join(root,'access-checkpoints.jsonl'),'{',{mode:0o600});
  assert.throws(()=>new AccessSession({session:'owned-fixture',privateDir:root,hosts:['example.com']}),/PARTIAL_CHECKPOINT/);
});

test('human handoff is one specific action and same-session checkpoint',async t=>{
  const s=setup(t,{execute:async()=>({observed:true})});
  const handoff=s.humanAction('verification','complete-visible-verification');
  assert.equal(handoff.action,'complete-visible-verification');assert.equal(handoff.session,'owned-fixture');assert.equal(handoff.checkpoint,'verification');
  assert.throws(()=>s.humanAction('verification','approve-again'),/INVALID_HUMAN_ACTION/);
  s.record('verification','UNKNOWN_EFFECT');
  assert.throws(()=>s.observe('verification','not-applied',{'not-submitted':false}),/OBSERVATION_REQUIRED/);
});

test('missing private directory uses a stable safe error',()=>{
  assert.throws(()=>new AccessSession({session:'owned-fixture',privateDir:'/private/tmp/polar-fixture-no-such-directory',hosts:['example.com']}),e=>e.code==='UNSAFE_PRIVATE_DIRECTORY'&&!e.message.includes('/private'));
});
