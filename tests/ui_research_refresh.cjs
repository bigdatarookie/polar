// Invented lifecycle and revision controls only. No network, producer or retained data.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {validateResearchRevision,createResearchRevisionWatcher,researchSnapshotSignature,researchSnapshotPage}=require('../src/polar/web/research.js');
const revision=(token='a',count=1,assessments=0)=>({schema_version:'polar.research-revision/1',revision:token.repeat(64),result_count:count,assessment_count:assessments});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function target(){const listeners=new Map();return {hidden:false,addEventListener(k,fn){if(!listeners.has(k))listeners.set(k,new Set());listeners.get(k).add(fn);},removeEventListener(k,fn){listeners.get(k)?.delete(fn);},emit(k){for(const fn of [...listeners.get(k)||[]])fn();},size(){return [...listeners.values()].reduce((n,s)=>n+s.size,0);}};}
function harness(options={}){
 const doc=target(),win=target(),timers=new Map(),calls=[],commits=[],errors=[];let token=0,state=revision(),available=true;
 const watcher=createResearchRevisionWatcher({document:doc,window:win,setTimer:(fn,delay)=>{const id=++token;timers.set(id,{fn,delay});return id;},clearTimer:id=>timers.delete(id),fetcher:async(url,opts)=>{calls.push({url,opts});return {ok:available,status:available?200:503,json:async()=>state};},prepare:async()=>({catalog:{total:state.result_count},value:state.revision}),commit:prepared=>commits.push(prepared),onStatus:e=>errors.push(e),...options});
 return {doc,win,timers,calls,commits,errors,watcher,setRevision:r=>state=r,setAvailable:v=>available=v,runTimer(){const [id,timer]=timers.entries().next().value||[];assert(timer,'No pending lifecycle timer');timers.delete(id);timer.fn();}};
}
test('revision identity rejects invalid shape, case, unsafe/noninteger counts and schema',()=>{
 assert.equal(validateResearchRevision(revision()).result_count,1);
 for(const bad of [null,{}, {...revision(),revision:['a'.repeat(64)]}, {...revision(),revision:'A'.repeat(64)},{...revision(),revision:'a'.repeat(63)},{...revision(),result_count:'1'},{...revision(),result_count:-1},{...revision(),assessment_count:1.5},{...revision(),result_count:Number.MAX_SAFE_INTEGER+1},{...revision(),schema_version:'other'}])assert.throws(()=>validateResearchRevision(bad),/RESEARCH_REVISION_INVALID/);
});
test('no-change and duplicate lifecycle checks use only the small GET and do not rebuild',async()=>{
 const h=harness();h.watcher.start();await settle();assert.equal(h.commits.length,1);assert.equal(h.calls.length,2);
 await h.watcher.check();await h.watcher.check();assert.equal(h.calls.length,4);assert.equal(h.commits.length,1);assert.equal(h.timers.size,1);assert.equal([...h.timers.values()][0].delay,5000);
 h.setRevision(revision('b',2,1));await h.watcher.check();assert.equal(h.commits.length,2);
 assert(h.calls.every(c=>c.url==='/v1/research/revision'&&c.opts.method==='GET'&&c.opts.cache==='no-store'));h.watcher.destroy();assert.equal(h.timers.size,0);
});
test('revision changing during a delayed snapshot discards it and serially coalesces the latest update',async()=>{
 let release,prepares=0,current=revision('a');const commits=[];
 const h=harness({fetcher:async()=>({ok:true,json:async()=>current}),prepare:async()=>{prepares++;const value=current.revision;if(prepares===1)await new Promise(resolve=>release=resolve);return {catalog:{total:1},value};},commit:p=>commits.push(p.value)});
 h.watcher.start();await settle();h.win.emit('focus');h.win.emit('focus');assert.equal(prepares,1);current=revision('b');release();await settle();assert.deepEqual(commits,[]);assert.equal(h.timers.size,1);h.runTimer();await settle();assert.deepEqual(commits,['b'.repeat(64)]);assert.equal(prepares,2);h.watcher.destroy();
});
test('hidden and unload cancel old work; visibility and pageshow resume without stale commits',async()=>{
 let release,first=true,signal;const h=harness({fetcher:async(_,opts)=>{signal=opts.signal;if(first){first=false;await new Promise(resolve=>release=resolve);}return {ok:true,json:async()=>revision()};}});
 h.watcher.start();await settle();h.doc.hidden=true;h.doc.emit('visibilitychange');assert(signal.aborted);assert.equal(h.timers.size,0);release();await settle();assert.equal(h.commits.length,0);
 h.doc.hidden=false;h.doc.emit('visibilitychange');await settle();assert.equal(h.commits.length,1);h.win.emit('pagehide');assert.equal(h.timers.size,0);h.win.emit('pageshow');await settle();assert.equal(h.commits.length,1);h.win.emit('unload');assert.equal(h.doc.size()+h.win.size(),0);assert.equal(h.timers.size,0);
});
test('endpoint unavailable/invalid stays explicit and recovers without empty or changed financial data',async()=>{
 const h=harness();h.setAvailable(false);h.watcher.start();await settle();assert.deepEqual(h.errors,['RESEARCH_REVISION_HTTP_503']);assert.equal(h.commits.length,0);await h.watcher.check();assert.equal(h.errors.length,1);
 h.setAvailable(true);h.setRevision({schema_version:'wrong'});await h.watcher.check();assert.equal(h.errors.at(-1),'RESEARCH_REVISION_INVALID');assert.equal(h.commits.length,0);
 h.setRevision(revision());await h.watcher.check();assert.equal(h.errors.at(-1),null);assert.equal(h.commits.length,1);h.watcher.destroy();
});
test('manual pending state defers background commit; newer selection is preserved at application',async()=>{
 let loading=true,selected='new-selection',applied;const h=harness({commit:()=>{if(loading)return false;applied=selected;return true;}});h.watcher.start();await settle();assert.equal(applied,undefined);loading=false;selected='latest-selection';await h.watcher.check();assert.equal(applied,'latest-selection');h.watcher.destroy();
});
test('same revision with inconsistent counts and stable revision/catalog mismatch reject explicitly',async()=>{
 const h=harness();h.watcher.start();await settle();h.setRevision(revision('a',2));await h.watcher.check();assert.equal(h.errors.at(-1),'RESEARCH_REVISION_IDENTITY_MISMATCH');h.watcher.destroy();
 const other=harness({prepare:async()=>({catalog:{total:2}})});other.watcher.start();await settle();assert.equal(other.errors.at(-1),'RESEARCH_REVISION_CATALOG_MISMATCH');assert.equal(other.commits.length,0);other.watcher.destroy();
});
test('snapshot signatures include independent assessments and source page keeps selected off-page record',()=>{
 const items=Array.from({length:12},(_,i)=>({result_id:'result-'+i,content_sha256:String(i),assessment:{financial:'NOT_REVIEWED'}})),snapshot={catalog:{total:12,limit:10,offset:0},items,details:items.map(item=>({...item,record:{}}))};
 assert.equal(researchSnapshotSignature(snapshot),researchSnapshotSignature(structuredClone(snapshot)));const next=structuredClone(snapshot);next.items[11].assessment.financial='NOT_SUPPORTED';assert.notEqual(researchSnapshotSignature(snapshot),researchSnapshotSignature(next));
 const page=researchSnapshotPage(snapshot,10,'result-0');assert.equal(page.catalog.offset,10);assert.equal(page.catalog.items.length,2);assert.equal(page.detail.result_id,'result-0');
});
