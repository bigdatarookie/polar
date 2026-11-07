// Explicit local fixture journey for existing named headed CLI. No provider or actual credential files.
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {AccessSession,cliExecutor,AccessError} from '../scripts/access-interaction.mjs';

const out=path.resolve(process.argv[2]);fs.mkdirSync(out,{mode:0o700});
const session=`polar-access-fixture-${process.pid}`,secret='SYNTHETIC_PRIVATE_SENTINEL';
let submits=0,evil=0,verified=0,opened=false,stage='open';const commands=[];
const check=(ok,code)=>{if(!ok)throw new AccessError(code);};
function command(args){
  commands.push(args);
  return new Promise((resolve,reject)=>{
    const child=spawn('playwright-cli',[`--session=${session}`,...args],{cwd:out,stdio:['ignore','pipe','pipe']});
    let bytes=0,leaked=false;child.stdout.on('data',b=>{bytes+=b.length;if(b.includes(secret))leaked=true;});child.stderr.on('data',b=>{bytes+=b.length;if(b.includes(secret))leaked=true;});
    const timer=setTimeout(()=>{child.kill('SIGTERM');setTimeout(()=>child.kill('SIGKILL'),500).unref();},30000);
    child.on('error',()=>{clearTimeout(timer);reject(new AccessError('FIXTURE_CLI_UNAVAILABLE'));});
    child.on('close',code=>{clearTimeout(timer);code===0&&!leaked?resolve({bytes}):reject(new AccessError(leaked?'SENTINEL_OUTPUT':'FIXTURE_CLI_FAILED'));});
  });
}
const html=`<!doctype html><html lang="ru"><meta charset="utf-8"><title>Controlled access fixture</title><form onsubmit="event.preventDefault();fetch('/submit',{method:'POST'});setTimeout(()=>document.getElementById('done').hidden=false,200)">
<label>Email<input id="email" required></label><label>Password<input id="password" type="password" required></label>
<label>Country<select id="country" required onchange="document.getElementById('city').hidden=this.value!=='TH';document.getElementById('city').required=this.value==='TH'"><option value="">Choose</option><option value="TH">Thailand</option></select></label>
<input id="city" hidden><button hidden>Продолжить</button><button type="submit" id="continue" disabled>Продолжить</button></form><div id="done" hidden>Observed dashboard fixture</div>
<script>setTimeout(()=>document.getElementById('continue').disabled=false,150);document.getElementById('city').value='fixture-city';</script></html>`;
const server=http.createServer((req,res)=>{
  if(req.url==='/submit'){submits++;res.end('ok');}
  else if(req.url==='/redirect'){res.writeHead(302,{Location:`http://localhost:${server.address().port}/evil`});res.end();}
  else if(req.url==='/allowed-redirect'){res.writeHead(302,{Location:`http://127.0.0.1:${server.address().port}/verified`});res.end();}
  else if(req.url==='/verified'){verified++;res.end('<!doctype html><title>Verified fixture</title>');}
  else if(req.url==='/evil'){evil++;res.end('unexpected');}
  else{res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});res.end(html);}
});
try{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const url=`http://127.0.0.1:${server.address().port}/`;
  await command(['open',url,'--headed','--browser','chrome']);opened=true;
  const execute=cliExecutor({session,privateDir:out});
  const s=new AccessSession({session,privateDir:out,hosts:['127.0.0.1'],localFixture:true,deadlineMs:60000,
    profile:{actions:[5,10],keys:[1,3],scroll:[5,10],seed:4},execute});
  fs.writeFileSync(path.join(out,'alpaca-account.json'),JSON.stringify({email:'fixture@example.invalid',password:secret}),{mode:0o600});
  stage='private-fill';const fill=await s.fillPrivate(out,{file:'alpaca-account.json',fields:['email','password']},{email:{selector:'#email'},password:{selector:'#password'}});
  check(fill.observed,'PRIVATE_FILL_NOT_OBSERVED');
  stage='country';await s.choose({selector:'#country'},'TH');
  const target={role:'button',name:'Продолжить'};
  stage='ready';check((await s.ready(target)).observed,'LOCALIZED_CONDITIONAL_NOT_READY');
  stage='submit';check((await s.mutate('signup','submit',target)).status==='UNKNOWN_EFFECT','SUBMIT_CHECKPOINT_MISSING');
  stage='dashboard';check((await s.ready({selector:'#done'})).observed,'DELAYED_DASHBOARD_NOT_OBSERVED');
  s.observe('signup','confirmed',{'dashboard-observed':true});
  const resumed=new AccessSession({session,privateDir:out,hosts:['127.0.0.1'],localFixture:true,deadlineMs:60000,execute});
  check((await resumed.mutate('signup','submit',target)).status==='ALREADY_CONFIRMED'&&submits===1,'DUPLICATE_MUTATION');
  stage='redirect';const redirect=await s.followVerification('verify',url+'redirect');
  check(!redirect.observed&&evil===0,'UNAPPROVED_REDIRECT_FOLLOWED');
  const permitted=await s.followVerification('allowed-verification',url+'allowed-redirect');
  check(permitted.observed&&verified===1,'PERMITTED_REDIRECT_NOT_OBSERVED');
  check(!JSON.stringify(s.receipt()).includes(secret)&&!JSON.stringify(commands).includes(secret),'SENTINEL_RECEIPT_OR_ARGV');
  check(!fs.readFileSync(path.join(out,'access-checkpoints.jsonl')).includes(secret),'SENTINEL_CHECKPOINT');
  const result={status:'AUTHOR_CONTROLLED_CLI_PASS',version:s.receipt().version,submits,unapproved_requests:evil,
    permitted_redirects:verified,same_named_session:true,private_input_observed:true,localized_conditional_ready:true,delayed_observation:true,
    raw_cli_output_published:false,provider_requests:0,real_credentials:false,owned_browser_closed:false};
  await command(['close']);opened=false;result.owned_browser_closed=true;
  fs.writeFileSync(path.join(out,'RESULT.json'),JSON.stringify(result,null,2)+'\n',{mode:0o600});console.log(JSON.stringify(result));
}catch(e){console.log(JSON.stringify({status:'FAIL',code:e instanceof AccessError?e.code:'FIXTURE_ERROR',stage}));process.exitCode=1;}
finally{if(opened)try{await command(['close']);}catch{}server.closeAllConnections();await new Promise(r=>server.close(r));}
