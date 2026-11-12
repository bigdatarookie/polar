// Controlled Node fixtures. No browser, server, backend request or runtime state.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const web = path.join(__dirname,'../src/polar/web');
const {buildView,indexValue,createLatestLoader,restoredControls,decimalDelta} = require(path.join(web,'data.js'));
function data() {
  const sessions=['2024-01-02','2024-01-03','2024-01-04'].map(session_id=>({session_id,open_at:session_id+'T14:30:00Z',close_at:session_id+'T21:00:00Z'}));
  return {dataset_id:'ds-actual',name:'<img src=x onerror=evil()>',instrument:{instrument_id:'retained-1',currency:'USD',ticker_history:[{ticker:'<svg onload=evil()>'}]},market:{frequency:'daily'},sessions,
    bars:sessions.map((s,i)=>({session_id:s.session_id,open:String(10+i),high:String(12+i),low:String(9+i),close:String(11+i),price_status:'OBSERVED'}))};
}
function report() {return {status:'COMPLETED',financial_verdict:'NOT_RUN',units:{nav:'USD',fee:'USD'},metrics:{total_return:{value:'0',unit:'fraction',status:'OK',evidence_status:'INSUFFICIENT_EVIDENCE'},sharpe_252:{value:null,unit:'ratio',status:'INSUFFICIENT_EVIDENCE'},fees:{value:'0',unit:'USD',status:'OK'}},initial_cash:'1000',nav:data().sessions.map((s,i)=>({session_id:s.session_id,at:s.close_at,nav:String(1000+i),cash:'0',shares:'4',status:'OBSERVED'})),fills:[{fill_at:'2024-01-03T14:30:00Z',receipt_at:'2024-01-03T14:30:01Z',quantity:'4',price:'11',fee:'1'}],orders:[],order_tape:[]};}
test('daily and weekly OHLC use actual rows and preserve exact raw strings',()=>{
  const d=data(),r=report(),daily=buildView(d,r,'1D'),weekly=buildView(d,r,'1W');
  assert.equal(daily.bars.length,3);assert.equal(daily.baseClose,'10');assert.equal(daily.initialCash,'1000');
  assert.equal(weekly.bars.length,1);assert.deepEqual([weekly.bars[0].open,weekly.bars[0].high,weekly.bars[0].low,weekly.bars[0].close],['10','14','9','13']);
  assert.equal(weekly.equity[0].value,'1002');assert.equal(weekly.equity[0].at,'2024-01-04T21:00:00Z');
  assert.equal(weekly.markers[0].plotIndex,0);assert.equal(weekly.markers[0].fill_at,r.fills[0].fill_at);
  assert.equal(weekly.bars[0].coverage.calendar,'NOT_ASSERTED');assert.equal(weekly.sma[0].value,null);
  assert.throws(()=>buildView(d,r,'1m'),/UNSUPPORTED_INTERVAL/);
});
test('exact extrema do not lose sub-Number precision',()=>{
  const d=data();d.bars[0].high='999999999999.999999999998';d.bars[1].high='999999999999.999999999999';
  assert.equal(buildView(d,report(),'1W').bars[0].high,'999999999999.999999999999');
  assert.equal(decimalDelta('999999999999.999999999999','999999999999.999999999998'),'0.000000000001');
  assert.equal(decimalDelta('1.0','2.00'),'-1.00');assert.equal(decimalDelta('1e-12','0'),'0.000000000001');
});
test('missing and settlement rows remain gaps, NAV gaps never forward-fill',()=>{
  const d=data(),r=report();d.bars[1].price_status='SETTLEMENT_ONLY';r.nav.pop();
  const daily=buildView(d,r,'1D'),weekly=buildView(d,r,'1W');
  assert.equal(daily.bars[1].close,null);assert.equal(daily.bars[1].originalStatuses[0],'SETTLEMENT_ONLY');
  assert.equal(weekly.bars[0].close,null);assert.equal(weekly.bars[0].coverage.observed,2);
  assert.equal(weekly.equity[0].value,null);assert.equal(daily.equity[2].value,null);
  assert.equal(indexValue(null,'1000'),null);assert.equal(indexValue('0','1000'),0);assert.equal(indexValue('1000','0'),null);
  const noReport=buildView(d,null,'1D');assert(noReport.equity.every(n=>n.value===null));
  assert.equal(buildView({...d,sessions:[],bars:[]},null,'1D').bars.length,0);
});
test('SMA display requires20 actual gap-free closes and no fabricated volume/benchmark',()=>{
  const d=data();d.sessions=Array.from({length:20},(_,i)=>({session_id:String(i),open_at:new Date(Date.UTC(2024,0,i+1,14)).toISOString(),close_at:new Date(Date.UTC(2024,0,i+1,21)).toISOString()}));
  d.bars=d.sessions.map(s=>({session_id:s.session_id,open:'1',high:'1',low:'1',close:'1',price_status:'OBSERVED'}));
  let v=buildView(d,null,'1D');assert(v.sma.slice(0,19).every(x=>x.value===null));assert.equal(v.sma[19].value,1);
  assert.equal(v.bars[0].volume,undefined);assert.equal(v.benchmarks,undefined);
  d.bars[0].price_status='MISSING';v=buildView(d,null,'1D');assert.equal(v.sma[19].value,null);
});
test('restored controls reject obsolete/untrusted fields and invalid bounds',()=>{
  const c=restoredControls({granularity:'1m',theme:'bad',mode:'Trade',benchmark:true,lo:-1,hi:900,cursorSource:'fake'},3);
  assert.equal(c.granularity,'1D');assert.equal(c.theme,'auto');assert.equal(c.mode,'Orders');assert.equal(c.lo,0);assert.equal(c.hi,2);assert.equal(c.benchmark,true);
  const valid=restoredControls({granularity:'1W',lo:1,hi:2,theme:'dark'},3);assert.equal(valid.granularity,'1W');assert.equal(valid.lo,1);assert.equal(valid.hi,2);
});
test('late success/error ignored even if fetch implementation ignores abort',async()=>{
  const pending=[];const loader=createLatestLoader((url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject})));
  const old=loader.load('/old'),now=loader.load('/new');assert(pending[0].options.signal.aborted);
  pending[1].resolve({ok:true,json:async()=>({id:'new'})});assert.deepEqual(await now,{id:'new'});
  pending[0].resolve({ok:true,json:async()=>({id:'old'})});assert.equal(await old,null);
  const failure=loader.load('/failure');loader.cancel();pending[2].reject(new Error('secret body'));assert.equal(await failure,null);
  const offline=createLatestLoader(async()=>{throw new Error('private host/password');});await assert.rejects(offline.load('/'),/^Error: API_UNAVAILABLE$/);
});
class Node {
  constructor(tag='div'){this.tag=tag;this.classList={toggle(){},add(){},remove(){}};this.children=[];this.style={setProperty(){}};this.dataset={};this.hidden=true;this.offsetWidth=230;this.offsetHeight=140;this.clientWidth=700;this.clientHeight=500;this._text='';}
  set textContent(value){this._text=String(value);this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent||'').join('');}
  set innerHTML(value){throw new Error('Untrusted HTML insertion: '+value);}
  append(...children){this.children.push(...children);}replaceChildren(...children){this._text='';this.children=[...children];}
  querySelector(selector){if(selector==='span')return this.span||(this.span=new Node('span'));return null;}setAttribute(name,value){this[name]=value;}removeAttribute(name){delete this[name];}focus(){}
  getBoundingClientRect(){return {left:0,top:0,width:700,height:500};}
}
function appContext(fetcher) {
  const nodes=new Map();const node=s=>{if(!nodes.has(s))nodes.set(s,new Node());return nodes.get(s);};
  const location=new URL('http://component.invalid/ui/'),history={entries:[],pushState(_,__,url){this.entries.push(String(url));location.href=String(url);},replaceState(_,__,url){location.href=String(url);}};
  const stored=new Map(),context=vm.createContext({module:{exports:{}},console,AbortController,URL,fetch:fetcher,location,history,
    sessionStorage:{getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v)},localStorage:{getItem:()=>null},
    document:{documentElement:new Node('html'),querySelector:node,getElementById:id=>node('#'+id),querySelectorAll:()=>[],createElement:tag=>new Node(tag)},
    matchMedia:()=>({matches:false}),innerWidth:800,innerHeight:900,scrollX:0,scrollY:0,cancelAnimationFrame(){},requestAnimationFrame(){},
    getComputedStyle:()=>({getPropertyValue:()=> '#7132c4'}),window:{scrollTo(){}},setTimeout,clearTimeout});
  for(const file of ['data.js','chart-ui.js','interaction.js','history.js','research.js','app.js'])vm.runInContext(fs.readFileSync(path.join(web,file),'utf8'),context,{filename:file});
  vm.runInContext("state.dataMode='retained-test'",context);
  context.renderAll=()=>{};context.renderChart=()=>{};context.syncToolbar=()=>{};return {context,node,stored,location,history};
}
function projection(d,id='run-1'){return {dataset:d,run:{id,dataset_id:d.dataset_id,strategy_version:'cash-flat-v1',state:'completed',created_at:'2024-01-01T00:00:00Z'},report:report(),report_availability:'AVAILABLE'};}
test('ordinary history compact rows select actual saved comparison and retain a separate research route',()=>{
  const env=appContext(async()=>{throw Error('no request');}),ctx=env.context,id='research-'+'a'.repeat(64);
  ctx.saved={result_id:id,assessment:{financial:'NOT_SUPPORTED',financial_evidence:{status:'ASSESSED_WITH_LIMITS'}},record:{
    question:{id:'model.FINAL',label:'Real <b>label</b>'},bindings:{data_revision:'research-source',data_sha256:'a'.repeat(64)},
    basis:{wealth_basis:'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',cost_basis:'NET',currency:'USD'},grid:['2024-01-02T21:00:00Z'],
    series:[{id:'model',role:'STRATEGY',ledger:[{positions:{AAPL:1,AMZN:0}}]}],metrics:[{id:'sharpe_252_rf0',label:'Sharpe',unit:'ratio',values:{model:{value:'0.8123',status:'OK',reason:null}}}],provenance:[]}};
  ctx.opened=null;ctx.fakeWorkspace={openResult:(...args)=>ctx.opened=args};
  vm.runInContext("state.dataMode='real';researchWorkspace=fakeWorkspace;mainResearch.page={catalog:{items:[saved],total:1,offset:0,next_offset:null},details:[saved],offsets:{[saved.result_id]:0}};historyContext={revision:{dataset_revision:'raw-history',manifest_sha256:'b'.repeat(64),basis:{ohlc_basis:'VENDOR_RAW_UNADJUSTED'}},instrument:{instrument_id:'raw-id',source_symbol:'AAPL'}};renderRows()",ctx);
  const list=env.node('#strategy-list');assert.match(list.textContent,/Real <b>label<\/b>/);assert.match(list.textContent,/NOT SUPPORTED/);
  const compatibility=vm.runInContext('researchHistoryCompatibility(saved,historyContext)',ctx);assert.match(compatibility.label,/Not attributed to AAPL history/);assert.match(compatibility.reasons.join(' '),/Different data binding/);
  assert(!list.textContent.includes('NO_STRATEGY_RESULT'));assert.equal(env.node('.table-head').hidden,true);
  const buttons=list.children.find(n=>n.tag==='article').children.filter(n=>n.tag==='button');buttons[0].onclick();assert.equal(vm.runInContext('mainResearchSelection',ctx),id);assert.equal(ctx.opened,null);buttons.at(-1).onclick();
  assert.deepEqual(Array.from(ctx.opened),[id,0]);assert.equal(vm.runInContext('detail',ctx),null);
  // Same-result research return preserves the actual selected tape event/card page and viewport.
  vm.runInContext("selectedExecutionId='model/2026-11-06/SELL/VTI';executions={resultId:mainResearchSelection,page:{status:'OK',total:148},allItems:[],offset:100,loading:false,error:null};state.rangeId='3M';state.lo=12;state.hi=34;selectMainResearch(mainResearchSelection,true,true)",ctx);
  assert.equal(vm.runInContext('selectedExecutionId',ctx),'model/2026-11-06/SELL/VTI');assert.equal(vm.runInContext('executions.offset',ctx),100);assert.equal(vm.runInContext('state.rangeId',ctx),'3M');assert.deepEqual(Array.from(vm.runInContext('[state.lo,state.hi]',ctx)),[12,34]);

  ctx.nextSaved={...ctx.saved,assessment:{financial:'INDETERMINATE',financial_evidence:{status:'INSUFFICIENT_EVIDENCE'}}};ctx.snapshot={catalog:{items:[ctx.nextSaved],total:1,offset:0,next_offset:null},items:[ctx.nextSaved],details:[ctx.nextSaved],offsets:{[id]:0}};
  ctx.fakeWorkspace.isLoading=()=>false;ctx.fakeWorkspace.applyAutomaticSnapshot=snapshot=>{ctx.autoApplied=snapshot;return true;};
  vm.runInContext("state.measurement={source:'assetClose',start:12,end:34};mainMetricSort={key:'drawdown',direction:'asc'};commitAutomaticResearch(snapshot)",ctx);
  assert.equal(vm.runInContext('selectedExecutionId',ctx),'model/2026-11-06/SELL/VTI');assert.equal(vm.runInContext('executions.offset',ctx),100);assert.equal(vm.runInContext('state.rangeId',ctx),'3M');assert.deepEqual(Array.from(vm.runInContext('[state.lo,state.hi]',ctx)),[12,34]);assert.equal(vm.runInContext('state.measurement.end',ctx),34);assert.equal(vm.runInContext('mainMetricSort.direction',ctx),'asc');assert.equal(vm.runInContext('selectedMainResearch().assessment.financial',ctx),'INDETERMINATE');assert.equal(ctx.autoApplied,ctx.snapshot);
  vm.runInContext("mainResearch.loading=true",ctx);assert.equal(vm.runInContext('commitAutomaticResearch(snapshot)',ctx),false);vm.runInContext("mainResearch.loading=false",ctx);
  vm.runInContext("mainResearch.page={catalog:{items:[],total:0,offset:0,next_offset:null},details:[]};renderRows()",ctx);
  assert.match(list.textContent,/No saved research records/);assert.equal(env.node('#runs-next').disabled,true);
});
test('actual app selection flow retains coherent offline data and navigates explicit retained IDs',async()=>{
  const d=data(),view=projection(d);const calls=[];
  const env=appContext(async url=>{calls.push(url);return {ok:true,json:async()=>url.startsWith('/v1/ui/runs/')?view:url.includes('/runs?')?{items:[{run:view.run}],offset:0}:{items:[d],offset:0}};});
  await env.context.loadSelection(null,null);assert.equal(vm.runInContext('detail.run.id',env.context),'run-1');
  assert.equal(env.location.search,'?mode=retained-test&dataset=ds-actual&run=run-1');assert(env.node('#asset-search').value.includes(d.name));
  const frames=[];env.context.renderAll=()=>frames.push(vm.runInContext('({dataset,detail,loading})',env.context));
  env.context.fetch=async()=>{throw new Error('private DSN');};await env.context.loadSelection('ds-actual','run-1',{catalogPage:0});
  assert.equal(frames.length,0); // Failure updates pending controls without rebuilding committed data.
  assert.equal(vm.runInContext('dataset.dataset_id',env.context),'ds-actual');assert.equal(vm.runInContext('view.bars.length',env.context),3);assert.equal(vm.runInContext('catalog.length',env.context),1);assert.equal(vm.runInContext('loadError',env.context),'API_UNAVAILABLE');
  assert(calls.every(url=>url.startsWith('/v1/ui/')));
});
test('explicit URL dataset without run cannot inherit another saved run',()=>{
  const env=appContext(async()=>{throw Error('not called');});
  env.location.href='http://component.invalid/ui/?mode=retained-test&dataset=new-dataset';
  env.stored.set('polar-retained-workspace-v1',JSON.stringify({dataset_id:'old-dataset',run_id:'old-run',controls:{}}));
  env.context.initUI=()=>{};env.context.loadSelection=(...args)=>env.args=args;
  env.context.boot();assert.equal(env.args[0],'new-dataset');assert.equal(env.args[1],null);
});
test('app run-only URLs resolve their actual dataset; late flow cannot overwrite it',async()=>{
  const old=data(),next={...data(),dataset_id:'ds-next'},pending=[];
  const env=appContext((url)=>new Promise(resolve=>pending.push({url,resolve})));
  const first=env.context.loadSelection('ds-actual',null,{catalogPage:0});
  const second=env.context.loadSelection(null,'run-next',{catalogPage:0});
  pending[1].resolve({ok:true,json:async()=>({items:[old],offset:0})});await new Promise(setImmediate);
  assert(pending[2].url.endsWith('/run-next'));pending[2].resolve({ok:true,json:async()=>projection(next,'run-next')});await new Promise(setImmediate);
  pending[3].resolve({ok:true,json:async()=>({items:[],offset:0})});await second;
  pending[0].resolve({ok:true,json:async()=>({items:[old],offset:0})});await first;
  assert.equal(vm.runInContext('dataset.dataset_id',env.context),'ds-next');assert.equal(vm.runInContext('detail.run.id',env.context),'run-next');
});
test('selected measurement keeps exact values,12px endpoint attachment/flip and text-only labels',()=>{
  const env=appContext(async()=>{throw Error('no request');}),ctx=env.context;
  ctx.fixtureDataset=data();ctx.fixtureDetail=projection(ctx.fixtureDataset);
  vm.runInContext("dataset=fixtureDataset;detail=fixtureDetail;view=buildView(dataset,detail.report,'1D');state.lo=0;state.hi=2;chart={convertToPixel:(axes,value)=>Array.isArray(value)?[view.bars.findIndex(b=>b.time===value[0])*250+100,200]:200};",ctx);
  ctx.activatePoint('assetClose',0);ctx.moveEndpoint(1);
  assert.equal(env.node('#measurement-fields').style.left,'362px');
  ctx.moveEndpoint(2);assert.equal(env.node('#measurement-fields').style.left,'358px');
  assert(env.node('#measurement-fields').textContent.includes('<svg onload=evil()> close'));
  assert(env.node('#measurement-fields').textContent.includes('$13'));
  ctx.clearMeasurement();assert.equal(vm.runInContext('state.measurement',ctx),null);assert.equal(env.node('#measurement-fields').hidden,true);
  vm.runInContext("view.bars[1].close=null",ctx);ctx.activatePoint('assetClose',1);assert.equal(vm.runInContext('state.measurement',ctx),null);
});

test('actual DOM renderers show observed zero/unavailable/status and put hostile labels in text only',()=>{
  const env=appContext(async()=>{throw Error('no request');}),ctx=env.context;
  ctx.fixtureDataset=data();ctx.fixtureDetail=projection(ctx.fixtureDataset);
  ctx.document.querySelectorAll=selector=>{
    if(selector!== '[data-info]')return [];
    const found=[];function walk(node){if(node.dataset?.info)found.push(node);for(const child of node.children||[])walk(child);}walk(env.node('#strategy-list'));return found;
  };
  vm.runInContext("dataset=fixtureDataset;detail=fixtureDetail;view=buildView(dataset,detail.report,'1D');runRows=[{run:detail.run,metrics:detail.report.metrics}];state.strategyId=detail.run.id;state.lo=0;state.hi=2;",ctx);
  ctx.renderRows();assert(env.node('#strategy-list').textContent.includes('0.00%'));assert(env.node('#strategy-list').textContent.includes('Unavailable'));
  ctx.renderRail();assert(env.node('#rail-body').textContent.includes('<svg onload=evil()>'));assert(env.node('#rail-body').textContent.includes('BUY · 4 shares'));assert(!env.node('#rail-body').textContent.includes('Entry'));
  vm.runInContext("state.infoId='run-1'",ctx);ctx.renderRecord();
  assert(env.node('#record-detail').textContent.includes('INSUFFICIENT_EVIDENCE'));assert(env.node('#record-detail').textContent.includes('NOT_RUN'));assert(env.node('#record-detail').textContent.includes('Ending NAV$1002'));
});

test('minimal accepted INVALID report keeps unavailable portfolio and actual diagnostic/verdict',()=>{
  const env=appContext(async()=>{throw Error('no request');}),ctx=env.context;
  const d=data();d.bars=[];
  const invalid={schema_version:'polar.report/1',status:'INVALID',diagnostic:'NO_DATA',financial_verdict:'INVALID',qualification:'INFRASTRUCTURE_FIXTURE_ONLY',dataset_id:d.dataset_id,protocol_version:'fixture-protocol-v2',fills:[],nav:[],metrics:{performance:{value:null,status:'INVALID',reason:'NO_DATA'}}};
  ctx.fixtureDataset=d;ctx.fixtureDetail={...projection(d),report:{...invalid,orders:[],order_tape:[],units:{},coverage:{}}};
  vm.runInContext("dataset=fixtureDataset;detail=fixtureDetail;view=buildView(dataset,detail.report,'1D');runRows=[{run:detail.run,metrics:detail.report.metrics,report_status:'INVALID',diagnostic:'NO_DATA',financial_verdict:'INVALID'}];state.strategyId=detail.run.id;state.lo=0;state.hi=2;",ctx);
  assert.equal(vm.runInContext('view.initialCash',ctx),null);assert.equal(vm.runInContext("anySource('strategyEquity')",ctx),false);
  assert.equal(vm.runInContext('view.equity.every(n=>n.value===null)',ctx),true);
  ctx.renderRows();assert(env.node('#strategy-list').textContent.includes('INVALID'));assert(env.node('#strategy-list').textContent.includes('Unavailable'));
  ctx.renderRail();assert(env.node('#rail-body').textContent.includes('NO_DATA'));assert(env.node('#rail-body').textContent.includes('Portfolio values are unavailable'));
  ctx.document.querySelectorAll=()=>[];vm.runInContext("state.infoId='run-1'",ctx);ctx.renderRecord();
  assert(env.node('#record-detail').textContent.includes('financial verdict INVALID'));assert(!env.node('#record-detail').textContent.includes('financial evaluation NOT_RUN'));
});

test('deferred DOM restoration never undoes a newer user list or workspace scroll',()=>{
 const {context:ctx,node}=appContext(async()=>{throw Error('no request');});let frame;ctx.requestAnimationFrame=fn=>{frame=fn;return 1;};
 node('#strategy-list').scrollTop=12;node('#workspace').scrollTop=0;
 vm.runInContext("keepScroll(()=>{document.querySelector('#strategy-list').scrollTop=0;})",ctx);assert.equal(node('#strategy-list').scrollTop,12);
 node('#strategy-list').scrollTop=144;node('#workspace').scrollTop=63;frame();assert.equal(node('#strategy-list').scrollTop,144);assert.equal(node('#workspace').scrollTop,63);
 vm.runInContext("keepScroll(()=>{document.querySelector('#strategy-list').scrollTop=0;})",ctx);frame();assert.equal(node('#strategy-list').scrollTop,144);
});
test('named price references remain independent, preserve saved benchmark, and share only transport demand',()=>{
 const {context:ctx,stored}=appContext(async()=>{throw Error('no request');});let refreshes=0;ctx.refreshHistoryOverlays=()=>refreshes++;
 vm.runInContext("comparisonBenchmark=false;toggleHistoryReference('asset',true)",ctx);assert.equal(refreshes,1);assert.deepEqual(Array.from(vm.runInContext('[referenceSelection.asset,referenceSelection.benchmark,state.benchmark,comparisonBenchmark]',ctx)),[true,false,true,false]);
 const saved=JSON.parse(stored.get('polar-retained-workspace-v1'));assert.deepEqual(saved.history_reference_selection,{asset:true,benchmark:false});assert.equal(saved.research_benchmark,false);
 vm.runInContext("toggleHistoryReference('benchmark',true);toggleHistoryReference('asset',false)",ctx);assert.equal(refreshes,1);assert.deepEqual(Array.from(vm.runInContext('[referenceSelection.asset,referenceSelection.benchmark,state.benchmark]',ctx)),[false,true,true]);
 vm.runInContext("toggleHistoryReference('benchmark',false)",ctx);assert.equal(refreshes,2);assert.equal(vm.runInContext('state.benchmark',ctx),false);
});

test('retained-test return restores pinned real dates and never treats synthetic timestamps as history dates',()=>{
 const {context:ctx}=appContext(async()=>{throw Error('no request');});ctx.renderRail=()=>{};ctx.loadSelection=()=>{};ctx.loadHistorySelection=request=>{ctx.returnRequest=request;};
 vm.runInContext("state.dataMode='real';state.rangeId='Custom';state.lo=0;state.hi=1;dataset={kind:'history'};historyContext={revision:{dataset_id:'pinned-data',dataset_revision:'pinned-revision'},instrument:{instrument_id:'actual-instrument'}};view.bars=[{time:'2026-08-06'},{time:'2026-09-07'}];setDataMode('retained-test');view.bars=[{time:'2024-01-02T21:00:00Z'},{time:'2024-01-03T21:00:00Z'}];setDataMode('real')",ctx);
 assert.deepEqual(JSON.parse(JSON.stringify(ctx.returnRequest)),{datasetId:'pinned-data',revision:'pinned-revision',instrumentId:'actual-instrument',rangeId:'Custom',window:{start:'2026-08-06',end_exclusive:'2026-09-08'}});
 const result=vm.runInContext("historyWindow({instrument:{first_date:'2020-01-01',last_date:'2026-11-06'}},'Custom',{first:'2024-01-02T21:00:00Z',last:'2024-01-03T21:00:00Z'},null)",ctx);assert.match(result.start,/^\d{4}-\d{2}-\d{2}$/);assert(result.start>='2020-01-01'&&result.start<result.end_exclusive);assert.equal(result.end_exclusive,'2026-11-07');
});
