// Invented contract fixtures only. No private producer data or network.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {createResearchClient,validateResearchDetail,researchValue,researchPlotValue,researchDecimalDisplay,researchComparison,researchNormalize}=require('../src/polar/web/research.js');
const hash='a'.repeat(64),id='research-'+hash;
const ok=value=>({value,status:'OK',reason:null}),missing=(reason='NO_DATA',status='UNAVAILABLE')=>({value:null,status,reason});
function fixture(suffix='a'){
 const content=suffix.repeat(64),result_id='research-'+content,grid=['2024-01-02T21:00:00Z','2024-01-03T21:00:00Z','2024-01-04T21:00:00Z'];
 const assessment={technical:'NOT_REVIEWED',product:'NOT_REVIEWED',financial:'NOT_REVIEWED',financial_evidence:{status:'NOT_RUN',reason:'INDEPENDENT_REVIEW_NOT_RECORDED'},reviews:[]};
 const series=['STRATEGY','BENCHMARK','CONTROL'].map((role,i)=>({id:'leg-'+i,label:role+' invented',role,unit:'USD',values:[ok('100'),i===2?missing():ok('99.5'),ok('0')],ledger:grid.map((_,j)=>({cash:'0',exposure:'100',cumulative_flat_fees:'1',cumulative_bps_fees:'0.1',positions:{invented:1},net_return:j?ok('-0.005'):missing('INITIAL_POINT','NOT_APPLICABLE')}))}));
 const values=Object.fromEntries(series.map(s=>[s.id,ok('-0.005')]));
 const record={schema_version:'polar.research-result/1',question:{id:'invented',label:'Invented UI test',summary:'Not an economic result'},grid,series,primary_benchmark_id:'leg-1',metrics:[{id:'sharpe',label:'Sharpe',unit:'ratio',values}],comparisons:[],costs:[{id:'fee',label:'Fee',kind:'CHARGED_FEES',unit:'USD',values,description:'Invented supplied cost'}],criteria:[],limitations:[{code:'INVENTED_ONLY',text:'UI test only',scope:'All'}],provenance:[{id:'invented',role:'test',sha256:hash}],bindings:{},basis:{}};
 const item={result_id,content_sha256:content,question:record.question,bindings:{},basis:{},assessment};
 return {item,detail:{schema_version:'polar.research-detail/1',result_id,content_sha256:content,record,assessment},catalog:{schema_version:'polar.research-catalog/1',items:[item],limit:10,offset:0,total:1,next_offset:null}};
}
test('detail preserves full grid, actual zero and initial-return unavailability',()=>{
 const f=fixture(),d=validateResearchDetail(f.detail,f.item);
 assert.equal(d.record.series[0].values[2].value,'0');assert.equal(researchPlotValue(d.record.series[0].values[2]),0);
 assert.equal(researchPlotValue(d.record.series[2].values[1]),null);
 assert.deepEqual(d.record.series[0].ledger[0].net_return,missing('INITIAL_POINT','NOT_APPLICABLE'));
 assert.equal(d.assessment.financial,'NOT_REVIEWED');assert.equal(d.assessment.financial_evidence.status,'NOT_RUN');
});
test('negative criteria and undefined cash Sharpe keep the result family available',()=>{
 const f=fixture();f.detail.record.metrics[0].values['leg-2']=missing('ZERO_VARIANCE');
 f.detail.record.criteria=[{id:'invented-point',description:'Invented only',status:'NOT_MET',reason:null}];
 f.detail.assessment.financial='INDETERMINATE';f.detail.assessment.financial_evidence={status:'INSUFFICIENT_EVIDENCE',reason:'INVENTED_ONLY'};
 const result=validateResearchDetail(f.detail,f.item);
 assert.equal(result.record.criteria[0].status,'NOT_MET');assert.equal(result.record.metrics[0].values['leg-2'].reason,'ZERO_VARIANCE');
 assert.equal(result.record.series.length,3);assert.equal(result.assessment.financial,'INDETERMINATE');
 for(const status of ['UNAVAILABLE','INVALID','NOT_APPLICABLE','NOT_RUN'])assert(researchValue(missing('INVENTED_REASON',status)));
});
test('identity, role, grid, ledger and review mismatches reject entire response',()=>{
 for(const change of [f=>f.detail.content_sha256='b'.repeat(64),f=>f.detail.record.series[1].role='STRATEGY',f=>f.detail.record.grid.reverse(),f=>f.detail.record.series[0].ledger.pop(),f=>f.detail.record.series[0].values[0]=missing('ZERO_NOT_DATA','OK'),f=>f.detail.assessment.reviews.push({schema_version:'polar.research-review/1',result_id:'research-'+'b'.repeat(64),content_sha256:'b'.repeat(64)})]){
  const f=fixture();change(f);assert.throws(()=>validateResearchDetail(f.detail,f.item),/RESEARCH_/);
 }
});
test('decimal formatting accepts long precision, rounds HALF_EVEN and never invents underflow zero',()=>{
 assert.equal(researchDecimalDisplay('1.225'),'1.22');assert.equal(researchDecimalDisplay('1.235'),'1.24');assert.equal(researchDecimalDisplay('-0.0001'),'0.00');
 assert.equal(researchDecimalDisplay('1.22'+'0'.repeat(600)+'1'),'1.22');
 const tiny=ok('0.'+'0'.repeat(1000)+'1');assert(researchValue(tiny));assert.equal(researchPlotValue(tiny),null);
 assert.equal(researchPlotValue(ok('-1.5')),-1.5);assert.equal(researchPlotValue(missing()),null);
});
test('latest selection wins when earlier transport ignores abort; errors retain caller state',async()=>{
 const pending=[],client=createResearchClient((url,options)=>new Promise((resolve,reject)=>pending.push({url,options,resolve,reject}))),a=fixture(),b=fixture('b');
 const first=client.load(),second=client.load();assert(pending[0].options.signal.aborted);
 pending[1].resolve({ok:true,json:async()=>b.catalog});await new Promise(setImmediate);
 pending[2].resolve({ok:true,json:async()=>b.detail});const current=await second;assert.equal(current.detail.result_id,b.item.result_id);
 pending[0].resolve({ok:true,json:async()=>a.catalog});assert.equal(await first,null);
 const error=createResearchClient(async()=>({ok:false,status:503,json:async()=>({code:'RESEARCH_STORAGE_UNAVAILABLE',private:'not shown'})}));
 await assert.rejects(error.load(),/^Error: RESEARCH_STORAGE_UNAVAILABLE$/);
 assert.equal(current.detail.result_id,b.item.result_id);
});
test('empty catalog is empty and makes no fallback/detail request',async()=>{
 const urls=[],client=createResearchClient(async url=>{urls.push(url);return {ok:true,json:async()=>({schema_version:'polar.research-catalog/1',items:[],limit:10,offset:0,total:0,next_offset:null})}});
 const result=await client.load();assert.equal(result.detail,null);assert.equal(result.catalog.items.length,0);assert.equal(urls.length,1);
});
module.exports={fixture};

const {researchTableScrollTarget}=require('../src/polar/web/research-ui.js');
test('focused table keys reveal hidden columns with bounded, reversible navigation',()=>{
 const max=625-366;
 assert.equal(researchTableScrollTarget(0,max,'ArrowRight',366),max);
 assert.equal(researchTableScrollTarget(max,max,'ArrowLeft',366),0);
 assert.equal(researchTableScrollTarget(30,max,'End',366),max);
 assert.equal(researchTableScrollTarget(30,max,'Home',366),0);
 assert.equal(researchTableScrollTarget(max,max,'ArrowRight',366),max);
 assert.equal(researchTableScrollTarget(0,0,'ArrowRight',900),0);
 assert.equal(researchTableScrollTarget(0,max,'Tab',366),null);
});

test('main strategy discovery obtains one coherent real-detail page and no economic computation',async()=>{
 const a=fixture(),b=fixture('b'),urls=[];const catalog={...a.catalog,items:[a.item,b.item],total:2};
 const client=createResearchClient(async url=>{urls.push(url);return {ok:true,json:async()=>url.includes('?')?catalog:url.endsWith(a.item.result_id)?a.detail:b.detail};});
 const page=await client.load(0,null,{includeDetails:true});
 assert.equal(page.details.length,2);assert.equal(page.details[1].result_id,b.item.result_id);assert.equal(urls.length,3);
 assert.deepEqual(page.details[0].record.metrics,a.detail.record.metrics);
 assert(urls.every(url=>url.startsWith('/v1/research/results')));
});

test('same ticker does not attribute synthetic or differently bound portfolios to raw history',()=>{
 const {researchHistoryCompatibility}=require('../src/polar/web/research.js');const f=fixture();
 f.detail.record.bindings={data_revision:'private-research-input',data_sha256:'a'.repeat(64)};
 f.detail.record.basis={wealth_basis:'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',cost_basis:'NET',currency:'USD'};
 const context={revision:{dataset_revision:'raw-history-revision',manifest_sha256:'b'.repeat(64),basis:{ohlc_basis:'VENDOR_RAW_UNADJUSTED'}},instrument:{instrument_id:'hist-id',source_symbol:'invented',currency:'USD'},visibleDates:['2023-01-01','2026-01-01']};
 const info=researchHistoryCompatibility(f.detail,context);
 assert.equal(info.status,'NOT_ATTRIBUTED_TO_HISTORY');assert.match(info.reasons.join(' '),/Different data binding/);
 assert.match(info.reasons.join(' '),/Synthetic vendor-adjusted/);assert.match(info.reasons.join(' '),/Matching a ticker alone is insufficient/);
 assert.deepEqual(info.period,['2024-01-02','2024-01-04']);
});

test('explicit exact data and instrument relation can attribute history while NAV stays separate',()=>{
 const {researchHistoryCompatibility}=require('../src/polar/web/research.js');const f=fixture();
 f.detail.record.bindings={data_revision:'history-revision',data_sha256:hash};
 f.detail.record.basis={wealth_basis:'PRICE_ONLY',cost_basis:'NET',currency:'USD'};
 f.detail.record.provenance=[{role:'history_instrument',id:'hist-id',sha256:hash}];
 const context={revision:{dataset_revision:'history-revision',manifest_sha256:hash,basis:{ohlc_basis:'VENDOR_RAW_UNADJUSTED'}},instrument:{instrument_id:'hist-id',source_symbol:'invented',currency:'USD'}};
 const info=researchHistoryCompatibility(f.detail,context);assert.equal(info.status,'ATTRIBUTED_REVISION_SEPARATE_NAV');assert.match(info.label,/NAV remains separate/);
 f.detail.record.series[0].ledger[0].positions.extra=0;
 assert.equal(researchHistoryCompatibility(f.detail,context).status,'NOT_ATTRIBUTED_TO_HISTORY');
});

test('display comparison uses first common valid calendar date, separate positive bases and explicit gaps',()=>{
 const f=fixture(),bars=[{time:'2024-01-01',close:'50',price_status:'OBSERVED'},{time:'2024-01-02',close:'200',price_status:'OBSERVED'},{time:'2024-01-03',close:'220',price_status:'OBSERVED'},{time:'2024-01-04',close:'180',price_status:'OBSERVED'},{time:'2024-01-05',close:'190',price_status:'OBSERVED'}];
 f.detail.record.series[1].values[0]=ok('1000');f.detail.record.series[1].values[1]=missing('REAL_GAP');
 const before=JSON.stringify(f.detail),m=researchComparison(f.detail,bars);assert(m.usable);assert.equal(m.baselineDate,'2024-01-02');assert.equal(m.first,1);assert.equal(m.last,3);assert.equal(m.strategyIndex[1],100);assert.equal(m.benchmarkIndex[1],100);assert.equal(m.benchmarkIndex[2],null);assert.equal(m.strategyIndex[0],null);assert.equal(m.strategyIndex[4],null);assert.equal(m.strategyIndex[3],0);assert.equal(researchNormalize('220',m.priceBase),110.00000000000001);assert.equal(JSON.stringify(f.detail),before);
});
test('no overlap, ambiguous date samples and renderer unsafe baselines explain unsupported comparison without padding',()=>{
 const f=fixture();assert.equal(researchComparison(f.detail,[{time:'2020-01-01',close:'20',price_status:'OBSERVED'}]).usable,false);
 f.detail.record.grid[1]='2024-01-02T22:00:00Z';assert.match(researchComparison(f.detail,[]).reason,/Multiple supplied samples/);
 assert.equal(researchNormalize('0.'+'0'.repeat(1000)+'1',100),null);assert.equal(researchNormalize('10',0),null);assert.equal(researchNormalize('0',100),0);
});
test('row metrics use only strategy full-period producer fields, decimal HALF_EVEN and percent units',()=>{
 const {researchRowMetric}=require('../src/polar/web/research.js'),f=fixture().detail;
 f.record.metrics=[{id:'sharpe_252_rf0',label:'Supplied Sharpe',unit:'ratio',values:{'leg-0':ok('1.225'),'leg-1':ok('99')}},{id:'max_drawdown',label:'Supplied drawdown',unit:'fraction',values:{'leg-0':ok('0.00125')}},{id:'net_cagr_act36525',label:'Supplied CAGR',unit:'fraction',values:{'leg-0':ok('-0.10005')}}];
 assert.equal(researchRowMetric(f,'sharpe').display,'1.22');assert.equal(researchRowMetric(f,'drawdown').display,'0.12%');assert.equal(researchRowMetric(f,'annualized').display,'−10.00%');
 f.record.metrics[0].values['leg-0']=missing('UNDEFINED');assert.equal(researchRowMetric(f,'sharpe').available,false);
});
test('exact metric sorting keeps unavailable last both ways, stable ties and sub-double precision',()=>{
 const {researchSortRows}=require('../src/polar/web/research.js');
 const rows=['1.000000000000000000002','1.000000000000000000001','1.000000000000000000001',null].map((v,i)=>{const f=fixture().detail;f.result_id=String(i);f.record.metrics=[{id:'sharpe',label:'Sharpe',unit:'ratio',values:{'leg-0':v===null?missing():ok(v)}}];return f;});
 assert.deepEqual(researchSortRows(rows,'sharpe','asc').map(x=>x.result_id),['1','2','0','3']);assert.deepEqual(researchSortRows(rows,'sharpe','desc').map(x=>x.result_id),['0','1','2','3']);
});
test('execution projection preserves exact nanos, distinguishes unknown/empty and rejects wrong security identity fields',()=>{
 const {validateResearchExecutions,executionScaledToken}=require('../src/polar/web/research.js'),f=fixture().detail;
 const base={schema_version:'polar.research-executions/1',result_id:f.result_id,content_sha256:f.content_sha256,series_id:'leg-0',offset:0,limit:100,next_offset:null,items:[],status:'UNAVAILABLE',total:null,reason:'TAPE_NOT_BOUND',price_unit:'USD_PER_SYNTHETIC_REFERENCE_UNIT',quote_basis:'SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT',quantity_unit:'REFERENCE_UNIT',raw_ohlc_overlay_compatible:false};
 assert.equal(validateResearchExecutions(base,f).total,null);assert.equal(validateResearchExecutions({...base,status:'OK',total:0,reason:null},f).total,0);
 const event={order_id:'leg-0/2024-01-02/BUY/TEST',symbol:'TEST',side:'BUY',timestamp_ns:'1704229200000000001',timestamp:'2024-01-02T21:00:00.000000001Z',session_date:'2024-01-02',timestamp_semantics:'NATIVE_ORDER_SUBMISSION_AND_MATCHED_FILL',intended_quantity:'2',routed_quantity:'2',filled_quantity:'2',price_micro:'100000001',fee_cents:'1',settled_notional_cents:'20000',status:'FILLED',reason:null,instrument:{status:'UNRESOLVED',reason:'SOURCE_INSTRUMENT_MAPPING_NOT_BOUND',instrument_id:null}};
 const page={...base,status:'OK',total:1,reason:null,items:[event]};assert.equal(validateResearchExecutions(page,f).items[0].timestamp_ns,'1704229200000000001');assert.equal(executionScaledToken(event.price_micro,6),'100.000001');
 assert.throws(()=>validateResearchExecutions({...page,content_sha256:'b'.repeat(64)},f),/EXECUTION_IDENTITY/);assert.throws(()=>validateResearchExecutions({...page,items:[{...event,price_micro:null}]},f),/EXECUTION_FILL/);
 assert.throws(()=>validateResearchExecutions({...page,items:[{...event,instrument:{status:'BOUND',instrument_id:'alias-only'}}]},f),/EXECUTION_INSTRUMENT/);
});

test('execution reader suppresses obsolete result even when transport ignores abort',async()=>{
 const {createResearchExecutionClient}=require('../src/polar/web/research.js'),a=fixture('a').detail,b=fixture('b').detail;let resolveOld;
 const envelope=saved=>({schema_version:'polar.research-executions/1',result_id:saved.result_id,content_sha256:saved.content_sha256,series_id:'leg-0',offset:0,limit:100,next_offset:null,items:[],status:'UNAVAILABLE',total:null,reason:'NOT_BOUND'});
 const client=createResearchExecutionClient(url=>url.includes(a.result_id)?new Promise(resolve=>resolveOld=resolve):Promise.resolve({ok:true,json:async()=>envelope(b)}));
 const old=client.load(a),latest=await client.load(b);resolveOld({ok:true,json:async()=>envelope(a)});assert.equal(latest.result_id,b.result_id);assert.equal(await old,null);
});
test('global row sorting reads every ten-item API page and retains research source page mapping',async()=>{
 const {researchLoadAll,researchSortRows,researchRowMetric}=require('../src/polar/web/research.js');
 const a=fixture('a').detail,b=fixture('b').detail;a.record.metrics=[{id:'net_sharpe',label:'Supplied net Sharpe',unit:'ratio',values:{'leg-0':ok('1.234')}}];b.record.metrics=[{id:'sharpe',label:'Supplied Sharpe',unit:'ratio',values:{'leg-0':ok('2')}}];
 const offsets=[],client={load:async offset=>{offsets.push(offset);return {catalog:{total:2,offset,items:[{}],next_offset:offset===0?1:null},details:[offset===0?a:b]};}};
 const all=await researchLoadAll(client);assert.deepEqual(offsets,[0,1]);assert.equal(all.offsets[b.result_id],1);assert.equal(researchSortRows(all.details,'sharpe')[0].result_id,b.result_id);assert.equal(researchRowMetric(a,'sharpe').display,'1.23');
 assert.equal(await researchLoadAll(client,()=>false),null);
 await assert.rejects(()=>researchLoadAll({load:async offset=>({catalog:{total:offset===0?2:3,next_offset:offset===0?1:null},details:[offset===0?a:b]})}),/RESEARCH_CATALOG_CHANGED/);
});
