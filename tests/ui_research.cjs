// Invented contract fixtures only. No private producer data or network.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {createResearchClient,validateResearchDetail,researchValue,researchPlotValue,researchDecimalDisplay}=require('../src/polar/web/research.js');
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
