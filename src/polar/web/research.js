// Saved research transport. Wire-v1.1: display supplied records, never calculate finance.
'use strict';
const RESEARCH_DECIMAL=/^-?(?:0|[1-9][0-9]{0,255})(?:\.[0-9]{1,4096})?$/;
const RESEARCH_ID=/^research-([a-f0-9]{64})$/;
function researchRequire(ok,code='RESEARCH_RESPONSE_INVALID'){if(!ok)throw new Error(code);}
function researchValue(v){return !!v&&['OK','UNAVAILABLE','INVALID','NOT_APPLICABLE','NOT_RUN'].includes(v.status)&&(v.status==='OK'?typeof v.value==='string'&&RESEARCH_DECIMAL.test(v.value)&&v.reason===null:v.value===null&&typeof v.reason==='string'&&v.reason.length>0);}
function researchIdentity(item){researchRequire(RESEARCH_ID.test(item?.result_id)&&item.result_id.slice(9)===item.content_sha256,'RESEARCH_IDENTITY_MISMATCH');}
function researchAssessment(a,resultId,hash){
  researchRequire(a&&['NOT_REVIEWED','PASS','FAIL','HOLD'].includes(a.technical)&&['NOT_REVIEWED','PASS','FAIL','HOLD'].includes(a.product)&&['NOT_REVIEWED','SUPPORTED_WITH_LIMITS','NOT_SUPPORTED','INDETERMINATE'].includes(a.financial)&&Array.isArray(a.reviews),'RESEARCH_ASSESSMENT_INVALID');
  researchRequire(a.financial_evidence&&['NOT_RUN','INVALID','INSUFFICIENT_EVIDENCE','ASSESSED_WITH_LIMITS'].includes(a.financial_evidence.status)&&(a.financial_evidence.reason===null||typeof a.financial_evidence.reason==='string'),'RESEARCH_ASSESSMENT_INVALID');
  for(const review of a.reviews)researchRequire(review.schema_version==='polar.research-review/1'&&review.result_id===resultId&&review.content_sha256===hash,'RESEARCH_REVIEW_IDENTITY_MISMATCH');
}
function validateResearchDetail(body,expected){
  researchRequire(body?.schema_version==='polar.research-detail/1');researchIdentity(body);
  researchRequire(body.result_id===expected.result_id&&body.content_sha256===expected.content_sha256,'RESEARCH_SELECTION_MISMATCH');
  const r=body.record;researchRequire(r?.schema_version==='polar.research-result/1'&&typeof r.question?.label==='string'&&typeof r.question.summary==='string');
  researchRequire(Array.isArray(r.grid)&&r.grid.length>0&&r.grid.length<=10000&&r.grid.every((d,i)=>typeof d==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(d)&&Number.isFinite(Date.parse(d))&&(!i||d>r.grid[i-1])),'RESEARCH_GRID_INVALID');
  researchRequire(Array.isArray(r.series)&&r.series.length>=2&&r.series.length<=5&&new Set(r.series.map(s=>s.id)).size===r.series.length,'RESEARCH_SERIES_INVALID');
  researchRequire(r.series.filter(s=>s.role==='STRATEGY').length===1&&r.series.some(s=>s.id===r.primary_benchmark_id&&s.role==='BENCHMARK'),'RESEARCH_ROLES_INVALID');
  for(const leg of r.series){
    researchRequire(['STRATEGY','BENCHMARK','CONTROL'].includes(leg.role)&&typeof leg.label==='string'&&leg.unit==='USD'&&leg.values?.length===r.grid.length&&leg.values.every(researchValue)&&leg.ledger?.length===r.grid.length,'RESEARCH_SERIES_INVALID');
    for(const point of leg.ledger)researchRequire(researchValue(point.net_return)&&['cash','exposure','cumulative_flat_fees','cumulative_bps_fees'].every(k=>point[k]===null||typeof point[k]==='string'&&RESEARCH_DECIMAL.test(point[k]))&&point.positions&&Object.values(point.positions).every(n=>Number.isInteger(n)&&n>=0),'RESEARCH_LEDGER_INVALID');
  }
  const ids=r.series.map(s=>s.id);
  for(const key of ['metrics','costs']){
    researchRequire(Array.isArray(r[key])&&r[key].length>0);
    for(const row of r[key])researchRequire(typeof row.id==='string'&&typeof row.label==='string'&&typeof row.unit==='string'&&row.values&&ids.every(id=>researchValue(row.values[id]))&&Object.keys(row.values).every(id=>ids.includes(id)),'RESEARCH_METRIC_INVALID');
  }
  researchRequire(Array.isArray(r.comparisons)&&r.comparisons.every(c=>ids.includes(c.left_id)&&ids.includes(c.right_id)&&r.metrics.some(m=>m.id===c.metric_id)&&researchValue(c.result)),'RESEARCH_COMPARISON_INVALID');
  researchRequire(Array.isArray(r.criteria)&&r.criteria.every(c=>['MET','NOT_MET','UNAVAILABLE'].includes(c.status))&&Array.isArray(r.limitations)&&r.limitations.length>0&&Array.isArray(r.provenance)&&r.provenance.length>0&&r.bindings&&r.basis,'RESEARCH_METADATA_INVALID');
  researchAssessment(body.assessment,body.result_id,body.content_sha256);return body;
}
function validateResearchCatalog(body,offset){
  researchRequire(body?.schema_version==='polar.research-catalog/1'&&Array.isArray(body.items)&&body.items.length<=10&&body.offset===offset&&body.limit===10&&Number.isInteger(body.total)&&body.total>=body.items.length&&(!body.items.length||body.total>=offset+body.items.length)&&(body.next_offset===null||body.next_offset===offset+body.items.length&&body.next_offset>offset&&body.next_offset<=4096),'RESEARCH_CATALOG_INVALID');
  const seen=new Set();for(const item of body.items){researchIdentity(item);researchRequire(!seen.has(item.result_id)&&typeof item.question?.label==='string'&&typeof item.question?.summary==='string'&&item.bindings&&item.basis,'RESEARCH_CATALOG_INVALID');seen.add(item.result_id);researchAssessment(item.assessment,item.result_id,item.content_sha256);}return body;
}
function createResearchClient(fetcher){
  let serial=0,controller;
  return {cancel(){serial++;controller?.abort();},async load(offset=0,selection=null,{includeDetails=false}={}){
    researchRequire(Number.isInteger(offset)&&offset>=0&&offset<=4096,'RESEARCH_PAGE_INVALID');
    const ticket=++serial;controller?.abort();const own=new AbortController();controller=own;
    async function read(url){
      let response;try{response=await fetcher(url,{signal:own.signal,cache:'no-store',credentials:'same-origin'});}catch{throw new Error('RESEARCH_API_UNAVAILABLE');}
      let body;try{body=await response.json();}catch{throw new Error('RESEARCH_RESPONSE_INVALID');}
      if(!response.ok){const code=body?.code||body?.detail?.code;throw new Error(typeof code==='string'&&/^[A-Z0-9_]+$/.test(code)?code:'RESEARCH_HTTP_'+response.status);}
      return body;
    }
    try{
      const catalog=validateResearchCatalog(await read('/v1/research/results?limit=10&offset='+offset),offset);if(ticket!==serial)return null;
      const selected=selection?catalog.items.find(i=>i.result_id===selection):catalog.items[0];
      researchRequire(!selection||selected,'RESEARCH_SELECTION_NOT_ON_PAGE');
      const details=includeDetails?await Promise.all(catalog.items.map(async item=>validateResearchDetail(await read('/v1/research/results/'+encodeURIComponent(item.result_id)),item))):null;
      const detail=selected?(details?details.find(d=>d.result_id===selected.result_id):validateResearchDetail(await read('/v1/research/results/'+encodeURIComponent(selected.result_id)),selected)):null;
      if(ticket!==serial)return null;return {catalog,detail,...(includeDetails?{details}:{} )};
    }catch(error){if(ticket!==serial)return null;throw error;}
  }};
}
function researchHistoryCompatibility(detail,context){
  const r=detail.record,revision=context?.revision,instrument=context?.instrument;
  const symbols=[...new Set(r.series.flatMap(s=>s.ledger.flatMap(p=>Object.keys(p.positions))))].sort();
  const period=[r.grid[0].slice(0,10),r.grid.at(-1).slice(0,10)],reasons=[];let attributed=false;
  if(!revision||!instrument)reasons.push('No committed history/instrument is selected; this saved result remains available.');
  else{
    if(r.bindings.data_revision!==revision.dataset_revision||r.bindings.data_sha256!==revision.manifest_sha256)
      reasons.push('Different data binding: result '+r.bindings.data_revision+'; history '+revision.dataset_revision+'.');
    if(r.basis.wealth_basis==='SYNTHETIC_VENDOR_ADJUSTED_REFERENCE_UNIT')
      reasons.push('Synthetic vendor-adjusted reference-unit portfolio NAV is not '+revision.basis.ohlc_basis+' single-instrument OHLC.');
    else reasons.push('Portfolio NAV after '+r.basis.cost_basis+' costs is a wealth series, not an OHLC candle series.');
    if(symbols.length!==1)reasons.push('Portfolio has '+symbols.length+' recorded position symbols: '+symbols.join(', ')+'. Selected history is '+(instrument.source_symbol||instrument.display_symbol||instrument.instrument_id)+'.');
    else if(symbols[0] !== (instrument.source_symbol||instrument.display_symbol))reasons.push('Recorded position symbol '+symbols[0]+' differs from selected source alias '+(instrument.source_symbol||instrument.display_symbol||instrument.instrument_id)+'. No ticker transformation or economic equivalence is inferred.');
    if(r.basis.currency!==instrument.currency)reasons.push('Currency differs: saved '+r.basis.currency+'; history '+(instrument.currency||'not supplied')+'.');
    const sourceBound=r.provenance.some(p=>p.role==='history_instrument'&&p.id===instrument.instrument_id&&p.sha256===revision.manifest_sha256);
    attributed=sourceBound&&r.bindings.data_revision===revision.dataset_revision&&r.bindings.data_sha256===revision.manifest_sha256&&
      symbols.length===1&&symbols[0]===(instrument.source_symbol||instrument.display_symbol)&&r.basis.wealth_basis==='PRICE_ONLY'&&
      r.basis.currency===instrument.currency&&revision.basis.ohlc_basis==='VENDOR_RAW_UNADJUSTED';
    if(!sourceBound)reasons.push('No content-bound instrument source relation attributes this result to the selected history. Matching a ticker alone is insufficient.');
    const bars=context?.visibleDates||[];
    if(bars.length&&(bars[0]<period[0]||bars.at(-1)>period[1]))reasons.push('Selected history period '+bars[0]+' to '+bars.at(-1)+' extends beyond saved result '+period.join(' to ')+'.');
  }
  return {symbols,period,reasons,status:attributed?'ATTRIBUTED_REVISION_SEPARATE_NAV':'NOT_ATTRIBUTED_TO_HISTORY',
    label:attributed?'Bound history revision · portfolio NAV remains separate':
      'Not attributed to '+(instrument?.source_symbol||instrument?.display_symbol||'selected')+' history · saved portfolio available'};
}
function researchPlotValue(point){if(point.status!=='OK')return null;const n=Number(point.value);return Number.isFinite(n)&&(n!==0||!/[1-9]/.test(point.value))?n:null;}
function researchDecimalDisplay(value,places=2){
  // Decimal-string HALF_EVEN formatting only. It never produces a financial metric.
  if(typeof value!=='string'||!RESEARCH_DECIMAL.test(value))return null;
  const negative=value.startsWith('-'),[whole,fraction='']=value.replace(/^-/, '').split('.');
  let scaled=BigInt(whole+fraction.padEnd(places,'0').slice(0,places));
  const tail=fraction.slice(places);if(tail[0]>'5'||tail[0]==='5'&&(/[1-9]/.test(tail.slice(1))||scaled%2n===1n))scaled++;
  const digits=scaled.toString().padStart(places+1,'0');return (negative&&scaled!==0n?'−':'')+digits.slice(0,-places)+'.'+digits.slice(-places);
}
// Supplied full-period strategy metrics: display conversion only, never recompute finance.
const RESEARCH_ROW_METRICS={sharpe:['sharpe_252_rf0','sharpe'],drawdown:['max_drawdown'],annualized:['adjusted_reference_cagr_after_costs','price_cagr_after_costs','net_cagr_act36525','annualized_return','cagr']};
function researchRowMetric(detail,key){
  const leg=detail.record.series.find(s=>s.role==='STRATEGY');
  const metric=RESEARCH_ROW_METRICS[key]?.map(id=>detail.record.metrics.find(m=>m.id===id)).find(Boolean);
  const point=metric?.values[leg?.id],unit=key==='sharpe'?'ratio':'fraction';
  const available=metric?.unit===unit&&point?.status==='OK'&&RESEARCH_DECIMAL.test(point.value);
  let display='Unavailable';
  if(available){let token=point.value;if(unit==='fraction'){
    const negative=token.startsWith('-'),[whole,fraction='']=token.replace(/^-/, '').split('.');
    const digits=whole+fraction.padEnd(2,'0');token=(negative?'-':'')+(digits.slice(0,whole.length+2).replace(/^0+(?=\d)/,'')||'0')+(fraction.length>2?'.'+fraction.slice(2):'');
  }display=researchDecimalDisplay(token,2)+(unit==='fraction'?'%':'');}
  return {available,value:available?point.value:null,display,label:metric?.label||'Not supplied',reason:available?null:point?.reason||(metric?'Unsupported metric unit':'Not supplied'),unit:metric?.unit||null};
}
function researchDecimalCompare(a,b){
  const parts=x=>{const [w,f='']=x.replace(/^-/, '').split('.');return {negative:x.startsWith('-')&&/[1-9]/.test(w+f),w,f};};
  const x=parts(a),y=parts(b);if(x.negative!==y.negative)return x.negative?-1:1;
  const size=Math.max(x.f.length,y.f.length),xf=x.f.padEnd(size,'0'),yf=y.f.padEnd(size,'0');
  const cmp=x.w.length-y.w.length||(x.w<y.w?-1:x.w>y.w?1:0)||(xf<yf?-1:xf>yf?1:0);return x.negative?-cmp:cmp;
}
function researchSortRows(details,key,direction='desc'){
  if(!key)return details.slice();
  return details.map((detail,index)=>({detail,index,metric:researchRowMetric(detail,key)})).sort((a,b)=>{
    if(a.metric.available!==b.metric.available)return a.metric.available?-1:1;
    return (a.metric.available?researchDecimalCompare(a.metric.value,b.metric.value)*(direction==='asc'?1:-1):0)||a.index-b.index;
  }).map(x=>x.detail);
}
// Display-only common-date normalization. Source strings, metrics and ledgers stay intact.
function researchNormalize(value,base){
  const n=typeof value==='string'?researchPlotValue({status:'OK',value}):null;
  if(n===null||!(base>0))return null;const out=n/base*100;
  return Number.isFinite(out)&&(out!==0||n===0)?out:null;
}
function researchComparison(detail,bars){
  const r=detail.record,strategy=r.series.find(s=>s.role==='STRATEGY'),benchmark=r.series.find(s=>s.id===r.primary_benchmark_id),byDate=new Map();
  for(let i=0;i<r.grid.length;i++){const date=r.grid[i].slice(0,10);if(byDate.has(date))return {usable:false,reason:'Multiple supplied samples share a calendar date. No intraday aggregation or clock equivalence is inferred.'};byDate.set(date,i);}
  const indices=bars.map(b=>byDate.get(b.time.slice(0,10))),strategyRaw=indices.map(i=>i===undefined||strategy.values[i].status!=='OK'?null:strategy.values[i].value),benchmarkRaw=indices.map(i=>i===undefined||benchmark.values[i].status!=='OK'?null:benchmark.values[i].value);
  let first=-1,last=-1;
  for(let i=0;i<bars.length;i++)if(indices[i]!==undefined){last=i;if(first<0&&bars[i].price_status==='OBSERVED'&&Number(bars[i].close)>0&&Number.isFinite(Number(bars[i].close))&&researchPlotValue(strategy.values[indices[i]])>0&&researchPlotValue(benchmark.values[indices[i]])>0)first=i;}
  if(first<0)return {usable:false,reason:last<0?'No common calendar dates between the selected asset history and this saved portfolio.':'No common date with positive, renderer-safe observed close, strategy NAV and benchmark NAV. Missing values were not filled.'};
  const priceBase=Number(bars[first].close),strategyBase=Number(strategyRaw[first]),benchmarkBase=Number(benchmarkRaw[first]);
  return {usable:true,first,last,baselineDate:bars[first].time.slice(0,10),priceBase,strategyBase,benchmarkBase,strategy,benchmark,strategyRaw,benchmarkRaw,times:indices.map(i=>i===undefined?null:r.grid[i]),strategyIndex:strategyRaw.map(v=>researchNormalize(v,strategyBase)),benchmarkIndex:benchmarkRaw.map(v=>researchNormalize(v,benchmarkBase)),record:r,resultId:detail.result_id};
}
function researchReadable(value){return String(value||'Not supplied').replaceAll('_',' ').replace(/\s+/g,' ').trim();}
function researchPhase(record){return record.question.label.match(/\b(?:FINAL|VALIDATION|TRAIN|TEST|DEVELOPMENT)\b/)?.[0]||'Saved interval';}
if(typeof module!=='undefined')module.exports={createResearchClient,validateResearchDetail,validateResearchCatalog,researchValue,researchPlotValue,researchDecimalDisplay,researchRowMetric,researchDecimalCompare,researchSortRows,researchHistoryCompatibility,researchNormalize,researchComparison,researchReadable,researchPhase};
