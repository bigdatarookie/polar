// Real-history transport adapter: PR13 237f7d5 / accepted contract f9c706f8.
// Source strings/statuses stay intact. No indicators, adjusted candles or NAV math.
'use strict';
const historyStable = value => JSON.stringify(value && typeof value === 'object' ? Array.isArray(value) ? value.map(v=>JSON.parse(historyStable(v))) : Object.fromEntries(Object.keys(value).sort().map(k=>[k,JSON.parse(historyStable(value[k]))])) : value);
function historyRequire(ok, code='HISTORY_RESPONSE_INVALID') {if(!ok)throw new Error(code);}
function historyDate(value) {
  if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;
  const d=new Date(value+'T00:00:00Z');return Number.isFinite(d.valueOf())&&d.toISOString().slice(0,10)===value;
}
function historyDayAfter(value) {historyRequire(historyDate(value));const d=new Date(value+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+1);return d.toISOString().slice(0,10);}
function historyId(value) {return typeof value==='string'&&/^[A-Za-z0-9_.:-]{1,64}$/.test(value);}
function historyRevision(value) {return typeof value==='string'&&/^histrev-[a-f0-9]{64}$/.test(value);}
// Closed retained SIP display bases. No missing adjusted close is fabricated.
function historySupportsSeries(revision){return revision?.basis?.ohlc_basis==='VENDOR_RAW_UNADJUSTED'&&revision.basis.adjusted_close_basis==='VENDOR_SPLIT_AND_DIVIDEND_ADJUSTED'&&revision.basis.volume_basis==='VENDOR_SPLIT_ADJUSTED';}
function historyOHLCLabel(revision){return revision?.basis?.ohlc_basis==='VENDOR_ALL_ADJUSTED_REFERENCE'?'Vendor all-adjusted OHLC':'Raw vendor OHLC';}
function historyVolumeLabel(revision){return 'Volume · '+(revision?.basis?.volume_unit||'source units not supplied');}
function historyBasisSupported(basis){
 const legacy={ohlc_basis:'VENDOR_RAW_UNADJUSTED',adjusted_close_basis:'VENDOR_SPLIT_AND_DIVIDEND_ADJUSTED',volume_basis:'VENDOR_SPLIT_ADJUSTED',price_unit:'USD/share',volume_unit:'split-adjusted shares'};
 const raw={ohlc_basis:'VENDOR_RAW_UNADJUSTED',adjusted_close_basis:'NOT_SUPPLIED',volume_basis:'VENDOR_RAW_RESPONSE_UNITS',price_unit:'USD/vendor raw reference unit',volume_unit:'vendor raw response units'};
 const adjusted={ohlc_basis:'VENDOR_ALL_ADJUSTED_REFERENCE',adjusted_close_basis:'NOT_SUPPLIED',volume_basis:'VENDOR_RESPONSE_UNITS_ADJUSTMENT_ALL_NOT_RAW_SHARES',price_unit:'USD/vendor all-adjusted reference unit',volume_unit:'vendor all-adjusted response units'};
 return historySupportsSeries({basis})||[raw,adjusted].some(known=>historyStable(known)===historyStable(basis));
}
function historyPin(value) {
  historyRequire(historyId(value?.dataset_id)&&historyRevision(value?.dataset_revision)&&/^[a-f0-9]{64}$/.test(value?.import_receipt_id)&&/^[a-f0-9]{64}$/.test(value?.manifest_sha256));
  historyRequire(historyBasisSupported(value.basis));
  return historyStable(Object.fromEntries(['dataset_id','dataset_revision','import_receipt_id','manifest_sha256','basis'].map(k=>[k,value[k]])));
}
// Qualified08117a1 serving + independent System e55cb0c; UI journey remains separate.
const HISTORY_SERIES_RUNTIME={enabled:true,candidate:'8fb07afe831a70673e04df28ab14a1c9e64bb7b6',servingSource:'08117a1cd03daba5b9616cadbd3164ffbaff9353'};
const HISTORY_SERIES_KEYS=['sma','ema','bb_middle','bb_upper','bb_lower','rsi','asset_reference','benchmark_reference'];
function historyControls(source) {return {sma:!!source.sma,ema:!!source.ema,bollinger:!!source.bollinger,rsi:!!source.rsi,benchmark:!!source.benchmark,indicators:JSON.parse(JSON.stringify(source.indicators)),referenceFamily:source.referenceFamily||'RAW_PRICE_RELATIVE'};}
function historyNeedsSeries(controls) {return ['sma','ema','bollinger','rsi','benchmark'].some(k=>controls?.[k]);}
function historyDecimalEqual(a,b) {const difference=decimalDelta(a,b);return difference!==null&&!/[1-9]/.test(difference);}
function historySeriesValue(point,key) {return point?.statuses?.[key]?.status==='VALUE'?point.values[key]:null;}
// Cache identity covers immutable input and all backend calculation parameters.
function historySeriesCacheKey(context,controls){return historyStable({pin:historyPin(context.revision),instrument:context.instrument.instrument_id,interval:'1D',basis:'RAW_CLOSE',controls:historyControls(controls),benchmark:'hist-us-0004',calculation:'polar.history-calculation/1',numeric:'decimal50-v1',definition:'467df7e251db727ecc35ae413b5416d2a61dea36a7f717850a06b1b03807f424'});}
function historyWindowContains(outer,inner){return !!outer&&!!inner&&outer.start<=inner.start&&outer.end_exclusive>=inner.end_exclusive;}
// Bounds describe transport only; no exchange-calendar qualification is inferred.
function historyInitialWindow(instrument,rangeId='3M',explicit=null){
  const full={start:instrument.first_date,end_exclusive:historyDayAfter(instrument.last_date)};
  let visible=explicit;if(!visible){let d=new Date(instrument.last_date+'T00:00:00Z');if(rangeId==='All')visible=full;else {if(rangeId==='1W')d.setUTCDate(d.getUTCDate()-7);else d.setUTCMonth(d.getUTCMonth()-({'1M':1,'3M':3,'6M':6,'12M':12}[rangeId]||3));visible={start:d.toISOString().slice(0,10),end_exclusive:full.end_exclusive};}}
  visible={start:visible.start<full.start?full.start:visible.start,end_exclusive:visible.end_exclusive>full.end_exclusive?full.end_exclusive:visible.end_exclusive};
  historyRequire(historyDate(visible.start)&&historyDate(visible.end_exclusive)&&visible.start<visible.end_exclusive,'HISTORY_WINDOW_INVALID');
  const span=(Date.parse(visible.end_exclusive)-Date.parse(visible.start))/86400000,margin=Math.max(180,Math.ceil(span));
  const shift=(date,days)=>new Date(Date.parse(date+'T00:00:00Z')+days*86400000).toISOString().slice(0,10);
  return {visible,buffer:{start:shift(visible.start,-margin)<full.start?full.start:shift(visible.start,-margin),end_exclusive:shift(visible.end_exclusive,margin)>full.end_exclusive?full.end_exclusive:shift(visible.end_exclusive,margin)}};
}
function historyBufferedWindow(context,visible){
  const rows=context.rows,first=context.instrument.first_date,last=context.instrument.last_date;
  if(context.loadedWindow)return {...context.loadedWindow};
  if(rows.length<=5000)return {start:first,end_exclusive:historyDayAfter(last)};
  const lo=Math.max(0,rows.findIndex(r=>r.session_date>=visible.start));let hi=rows.findIndex(r=>r.session_date>=visible.end_exclusive);if(hi<0)hi=rows.length;
  const margin=Math.max(128,hi-lo),start=Math.max(0,lo-margin),end=Math.min(rows.length-1,hi+margin);
  return {start:rows[start].session_date,end_exclusive:historyDayAfter(rows[end].session_date)};
}
// Keep a visible-span reserve near a partial buffer edge. A full admitted
// daily history has no missing edge and never schedules viewport I/O.
function historyBufferNeedsPrefetch(context,buffer,visible){
  if(!historyWindowContains(buffer,visible))return true;
  const rows=context.rows,at=date=>{const i=rows.findIndex(r=>r.session_date>=date);return i<0?rows.length:i;};
  const lo=at(visible.start),hi=at(visible.end_exclusive),left=at(buffer.start),right=at(buffer.end_exclusive),reserve=Math.max(32,hi-lo);
  return left>0&&lo-left<reserve||right<rows.length&&right-hi<reserve;
}
// Independent full-resolution interval read; never reseeds backend indicators.
async function readHistoryRange(fetcher,context,window,signal){
  historyRequire(historyDate(window.start)&&historyDate(window.end_exclusive)&&window.start<window.end_exclusive,'HISTORY_WINDOW_INVALID');
  const pin=historyPin(context.revision),instrument=context.instrument.instrument_id,prefix='/v1/history/datasets/'+encodeURIComponent(context.revision.dataset_id)+'/revisions/'+encodeURIComponent(context.revision.dataset_revision),query=new URLSearchParams({instrument_id:instrument,start:window.start,end:window.end_exclusive,limit:'1000',warmup_sessions:'0'});
  let cursor=null,request=null,metadata=null;const rows=[],cursors=new Set();
  do{const response=await fetcher(prefix+'/bars?'+query+(cursor?'&cursor='+encodeURIComponent(cursor):''),{signal,cache:'no-store',credentials:'same-origin'}),text=await response.text();historyRequire(new TextEncoder().encode(text).byteLength<=1048576,'HISTORY_RESPONSE_TOO_LARGE');let page;try{page=JSON.parse(text);}catch{throw Error('HISTORY_RESPONSE_INVALID');}
    if(!response.ok)throw Error(page?.code||page?.detail?.code||'HISTORY_HTTP_'+response.status);
    historyRequire(page.schema_version==='polar.history-bars/1'&&historyPin(page)===pin&&page.instrument_id===instrument,'HISTORY_BARS_IDENTITY_MISMATCH');
    historyRequire(page.window?.start===window.start&&page.window?.end_exclusive===window.end_exclusive&&typeof page.request_identity==='string'&&(!request||request===page.request_identity),'HISTORY_REQUEST_MISMATCH');request=page.request_identity;
    historyRequire(Array.isArray(page.rows)&&page.rows.length===page.row_count&&page.row_count<=1000,'HISTORY_PAGE_INVALID');
    if(metadata)historyRequire(historyStable([page.coverage,page.fitness,page.data_status])===historyStable([metadata.coverage,metadata.fitness,metadata.data_status]),'HISTORY_PAGE_STATUS_MISMATCH');
    for(const row of page.rows){historyRequire(historyDate(row.session_date)&&row.row_role==='VISIBLE'&&row.session_date>=window.start&&row.session_date<window.end_exclusive&&(!rows.length||rows.at(-1).session_date<row.session_date),'HISTORY_ROW_ORDER_MISMATCH');historyRequire(['open','high','low','close','adjusted_close','volume'].every(k=>row[k]===null||typeof row[k]==='string'),'HISTORY_NUMERIC_TOKEN_INVALID');rows.push(row);}
    historyRequire(rows.length<=5000,'HISTORY_ASSET_PROFILE_EXCEEDED');metadata=page;cursor=page.next_cursor;historyRequire(cursor===null||typeof cursor==='string'&&!cursors.has(cursor)&&cursor.length<=2048,'HISTORY_CURSOR_INVALID');historyRequire(page.window_complete===(cursor===null),'HISTORY_PAGE_INCOMPLETE');if(cursor)cursors.add(cursor);
  }while(cursor);
  historyRequire(metadata.window_complete&&rows.length===metadata.coverage.observed_in_window,'HISTORY_WINDOW_INCOMPLETE');return {rows,bars:metadata,loadedWindow:{...window}};
}
function createHistoryClient(fetcher) {
  let controller=null;const seriesCache=new Map(),seriesPending=new Map(),rangeCache=new Map();
  return {
    range(context,window,{signal}={}){const key=historyPin(context.revision)+'|'+context.instrument.instrument_id;for(const [cacheKey,entry]of rangeCache)if(entry.key===key&&historyWindowContains(entry.result.loadedWindow,window))return Promise.resolve(entry.result);return readHistoryRange(fetcher,context,window,signal).then(result=>{rangeCache.set(key+'|'+window.start+'|'+window.end_exclusive,{key,result});while(rangeCache.size>16)rangeCache.delete(rangeCache.keys().next().value);return result;});},
    cancel(){controller?.abort();for(const p of seriesPending.values())p.controller.abort();seriesPending.clear();},
    async load(selection={}) {
      controller?.abort();for(const p of seriesPending.values())p.controller.abort();seriesPending.clear();const own=new AbortController();controller=own;
      let pinnedSelection=selection;
      async function read(path) {
        const response=await fetcher(path,{signal:own.signal,cache:'no-store',credentials:'same-origin'});
        const text=await response.text();historyRequire(new TextEncoder().encode(text).byteLength<=1048576,'HISTORY_RESPONSE_TOO_LARGE');
        let body;try{body=JSON.parse(text);}catch{throw new Error('HISTORY_RESPONSE_INVALID');}
        if(!response.ok){const code=body?.code||body?.detail?.code;const error=new Error(typeof code==='string'&&/^[A-Z0-9_]+$/.test(code)?code:'HISTORY_HTTP_'+response.status);error.pinnedSelection=pinnedSelection;throw error;}
        return body;
      }
      const catalogURL='/v1/history/datasets?limit=50'+(selection.catalogCursor?'&cursor='+encodeURIComponent(selection.catalogCursor):'');
      const catalog=await read(catalogURL);
      historyRequire(catalog.schema_version==='polar.history-catalog/1'&&Array.isArray(catalog.items)&&catalog.items.length<=50);
      for(const item of catalog.items)historyPin(item);
      let item=catalog.items.find(d=>d.dataset_id===selection.datasetId&&(!selection.revision||d.dataset_revision===selection.revision));
      if(!item&&!selection.datasetId)item=catalog.items[0];
      const datasetId=selection.datasetId||item?.dataset_id,revision=selection.revision||item?.dataset_revision;
      if(!datasetId)return {catalog,revision:null,assets:[],instrument:null,rows:[],bars:null};
      historyRequire(historyId(datasetId)&&historyRevision(revision),'HISTORY_SELECTION_INVALID');
      pinnedSelection={...selection,datasetId,revision};
      const prefix='/v1/history/datasets/'+encodeURIComponent(datasetId)+'/revisions/'+encodeURIComponent(revision);
      const summary=await read(prefix);
      historyRequire(summary.schema_version==='polar.history-revision/1'&&summary.dataset_id===datasetId&&summary.dataset_revision===revision,'HISTORY_REVISION_MISMATCH');
      const pin=historyPin(summary);if(item)historyRequire(historyPin(item)===pin,'HISTORY_IDENTITY_MISMATCH');
      let assets=[],cursor=null,request=null;const assetCursors=new Set();
      do {
        const page=await read(prefix+'/assets?limit=50'+(cursor?'&cursor='+encodeURIComponent(cursor):''));
        historyRequire(page.schema_version==='polar.history-assets/1'&&historyPin(page)===pin&&Array.isArray(page.items)&&page.items.length===page.item_count&&page.item_count<=50,'HISTORY_ASSET_PAGE_MISMATCH');
        historyRequire(typeof page.request_identity==='string'&&(!request||request===page.request_identity),'HISTORY_REQUEST_MISMATCH');request=page.request_identity;
        for(const asset of page.items){historyRequire(historyId(asset.instrument_id)&&!assets.some(a=>a.instrument_id===asset.instrument_id),'HISTORY_ASSET_ID_MISMATCH');assets.push(asset);}
        cursor=page.next_cursor;historyRequire(cursor===null||(typeof cursor==='string'&&cursor.length<=2048&&!assetCursors.has(cursor)),'HISTORY_CURSOR_INVALID');
        if(cursor)assetCursors.add(cursor);
      }while(cursor);
      const instrument=selection.instrumentId?assets.find(a=>a.instrument_id===selection.instrumentId):assets.find(a=>a.chart_fitness!=='NOT_READY'&&a.row_count>0)||assets[0];
      historyRequire(!!instrument,'HISTORY_ASSET_NOT_FOUND');
      pinnedSelection={...pinnedSelection,instrumentId:instrument.instrument_id};
      if(!instrument.row_count)return {catalog,revision:summary,assets,instrument,rows:[],bars:null};
      historyRequire(historyDate(instrument.first_date)&&historyDate(instrument.last_date),'HISTORY_BOUNDS_INVALID');
      const initial=historyInitialWindow(instrument,selection.rangeId||'All',selection.window);
      const result=await readHistoryRange(fetcher,{revision:summary,instrument},initial.buffer,own.signal);
      rangeCache.set(pin+'|'+instrument.instrument_id+'|'+initial.buffer.start+'|'+initial.buffer.end_exclusive,{key:pin+'|'+instrument.instrument_id,result});
      return {catalog,revision:summary,assets,instrument,...result,requestedWindow:initial.visible};
    },
    series(context,controls,window) {
      historyRequire(HISTORY_SERIES_RUNTIME.enabled,'C_RUNTIME_NOT_QUALIFIED');
      historyRequire(historySupportsSeries(context.revision),'CALCULATIONS_NOT_QUALIFIED_FOR_THIS_SOURCE_BASIS');
      const base=historySeriesCacheKey(context,controls),key=base+'|'+window.start+'|'+window.end_exclusive;
      for(const [k,p] of seriesPending)if(k!==key){p.controller.abort();seriesPending.delete(k);}
      for(const [k,cached] of seriesCache)if(cached.base===base&&historyWindowContains(cached.result.window,window)){seriesCache.delete(k);seriesCache.set(k,cached);return Promise.resolve(cached.result);}
      if(seriesPending.has(key))return seriesPending.get(key).promise;
      const own=new AbortController(),entry={controller:own,promise:null};
      const work=(async()=>{
      const pin=historyPin(context.revision),asset=context.instrument.instrument_id;
      historyRequire(historyDate(window.start)&&historyDate(window.end_exclusive)&&window.start<window.end_exclusive,'HISTORY_WINDOW_INVALID');
      const benchmark=context.assets.find(a=>a.instrument_id==='hist-us-0004');historyRequire(!!benchmark,'HISTORY_BENCHMARK_NOT_AVAILABLE');
      const expected={sma_period:controls.sma?controls.indicators.sma.period:null,ema_period:controls.ema?controls.indicators.ema.period:null,bb_period:controls.bollinger?controls.indicators.bollinger.period:null,rsi_period:controls.rsi?controls.indicators.rsi.period:null};
      const query=new URLSearchParams({instrument_id:asset,start:window.start,end:window.end_exclusive,limit:'1000',warmup_sessions:'0',basis:'RAW_CLOSE',reference_family:controls.referenceFamily,benchmark_instrument_id:benchmark.instrument_id});
      for(const [key,n] of Object.entries(expected))if(n!==null){historyRequire(Number.isInteger(n)&&n>=2&&n<=500,'HISTORY_PARAMETER_INVALID');query.set(key,String(n));}
      if(controls.bollinger)query.set('bb_deviation',controls.indicators.bollinger.deviation);
      const prefix='/v1/history/datasets/'+encodeURIComponent(context.revision.dataset_id)+'/revisions/'+encodeURIComponent(context.revision.dataset_revision)+'/series?';
      let cursor=null,request=null,metadata=null,rows=[];const cursors=new Set();
      do {
        historyRequire(!own.signal.aborted,'HISTORY_REQUEST_CANCELLED');
        const response=await fetcher(prefix+query+(cursor?'&cursor='+encodeURIComponent(cursor):''),{signal:own.signal,cache:'no-store',credentials:'same-origin'});
        const text=await response.text();historyRequire(new TextEncoder().encode(text).byteLength<=1048576,'HISTORY_RESPONSE_TOO_LARGE');
        historyRequire(!own.signal.aborted,'HISTORY_REQUEST_CANCELLED');
        let page;try{page=JSON.parse(text);}catch{throw new Error('HISTORY_SERIES_RESPONSE_INVALID');}
        if(!response.ok){const code=page?.code||page?.detail?.code;throw new Error(typeof code==='string'&&/^[A-Z0-9_]+$/.test(code)?code:'HISTORY_HTTP_'+response.status);}
        historyRequire(page.schema_version==='polar.history-series/1'&&historyPin(page)===pin&&page.instrument_id===asset,'HISTORY_SERIES_IDENTITY_MISMATCH');
        historyRequire(page.calculation_version==='polar.history-calculation/1'&&page.numeric_version==='decimal50-v1'&&page.definition_sha256==='467df7e251db727ecc35ae413b5416d2a61dea36a7f717850a06b1b03807f424','HISTORY_CALCULATION_VERSION_MISMATCH');
        historyRequire(page.window?.start===window.start&&page.window?.end_exclusive===window.end_exclusive&&typeof page.request_identity==='string'&&(!request||request===page.request_identity),'HISTORY_SERIES_REQUEST_MISMATCH');request=page.request_identity;
        historyRequire(Object.entries(expected).every(([k,n])=>page.parameters?.[k]===n)&&page.parameters?.basis==='RAW_CLOSE'&&page.parameters.reference_family===controls.referenceFamily&&page.parameters.benchmark_instrument_id===benchmark.instrument_id,'HISTORY_SERIES_PARAMETER_MISMATCH');
        historyRequire(controls.bollinger?historyDecimalEqual(page.parameters.bb_deviation,controls.indicators.bollinger.deviation):page.parameters.bb_deviation===null,'HISTORY_SERIES_PARAMETER_MISMATCH');
        historyRequire(page.reference_metadata?.family===controls.referenceFamily&&page.reference_metadata.instrument_id===asset&&page.reference_metadata.benchmark_instrument_id===benchmark.instrument_id,'HISTORY_REFERENCE_MISMATCH');
        historyRequire(HISTORY_SERIES_KEYS.slice(0,6).every(key=>{const m=page.series_metadata?.[key];return m&&typeof m.status==='string'&&m.period===expected[(key.startsWith('bb_')?'bb':key)+'_period']&&Number.isInteger(m.available_history)&&m.available_history>=0&&(m.first_valid_session===null||historyDate(m.first_valid_session));}),'HISTORY_SERIES_METADATA_INVALID');
        historyRequire(Array.isArray(page.rows)&&page.rows.length===page.row_count&&page.row_count<=1000&&page.warmup?.requested===0,'HISTORY_SERIES_PAGE_INVALID');
        const stable=p=>historyStable([p.coverage,p.fitness,p.data_status,p.parameters,p.series_metadata,p.reference_metadata,p.resets,p.warmup.status]);
        if(metadata)historyRequire(stable(page)===stable(metadata),'HISTORY_SERIES_PAGE_MISMATCH');
        for(const row of page.rows){
          historyRequire(historyDate(row.session_date)&&row.row_role==='VISIBLE'&&row.session_date>=window.start&&row.session_date<window.end_exclusive&&(!rows.length||rows.at(-1).session_date<row.session_date),'HISTORY_SERIES_ORDER_MISMATCH');
          historyRequire(HISTORY_SERIES_KEYS.every(k=>{
            const value=row.values?.[k],status=row.statuses?.[k];
            return status&&['VALUE','UNAVAILABLE','DISABLED'].includes(status.status)&&(status.reason===null||typeof status.reason==='string')&&(status.status==='VALUE'?typeof value==='string'&&/^-?\d+(?:\.\d+)?(?:E[+-]?\d+)?$/.test(value)&&Number.isFinite(Number(value)):value===null);
          }),'HISTORY_SERIES_VALUE_INVALID');rows.push(row);
        }
        metadata=page;cursor=page.next_cursor;
        historyRequire(cursor===null||(typeof cursor==='string'&&cursor.length<=2048&&!cursors.has(cursor)),'HISTORY_CURSOR_INVALID');
        historyRequire(page.window_complete===(cursor===null),'HISTORY_SERIES_INCOMPLETE');if(cursor)cursors.add(cursor);
      }while(cursor);
      const observed=context.rows.filter(r=>r.session_date>=window.start&&r.session_date<window.end_exclusive).length;
      historyRequire(metadata.window_complete&&metadata.coverage.observed_in_window===observed,'HISTORY_SERIES_COVERAGE_MISMATCH');
      if(metadata.coverage.expected_sessions!==null)historyRequire(rows.length===metadata.coverage.expected_sessions,'HISTORY_SERIES_COVERAGE_MISMATCH');
      historyRequire(!own.signal.aborted,'HISTORY_REQUEST_CANCELLED');
      return {rows,metadata,window:{...window},controls};
      })();
      entry.promise=work.then(result=>{historyRequire(!own.signal.aborted,'HISTORY_REQUEST_CANCELLED');seriesCache.set(key,{base,result});while(seriesCache.size>4)seriesCache.delete(seriesCache.keys().next().value);return result;}).finally(()=>{if(seriesPending.get(key)===entry)seriesPending.delete(key);});
      seriesPending.set(key,entry);return entry.promise;
    }
  };
}
function buildHistoryView(context) {
  const originals=new Map(context.rows.map(row=>[row.session_date,row]));
  const points=new Map((context.series?.rows||[]).map(row=>[row.session_date,row]));
  const dates=[...new Set([...originals.keys(),...points.keys()])].sort();
  // A series-only reference date is an empty axis slot, never an OHLCV row.
  const bars=dates.map(date=>{const row=originals.get(date);return row?{...row,sourceRow:row,time:date,endTime:date,originalStatuses:[row.price_status],coverage:{observed:row.price_status==='OBSERVED'?1:0,supplied:1,calendar:context.bars?.coverage.calendar_status||'UNVERIFIED'}}:{time:date,endTime:date,session_date:date,sourceRow:null,missingBar:true,originalStatuses:[],coverage:{observed:0,supplied:0,calendar:'COMMON_REFERENCE_DATE_ONLY'}};});
  return {history:true,bars,cPoints:dates.map(date=>points.get(date)||null),equity:bars.map(b=>({time:b.time,value:null,at:null,status:'NO_STRATEGY_RESULT'})),markers:[],sma:[],baseClose:null,initialCash:null};
}

if(typeof module!=='undefined')module.exports={historyVolumeLabel,historyBasisSupported,historySupportsSeries,historyOHLCLabel,historyInitialWindow,readHistoryRange,createHistoryClient,historySeriesCacheKey,historyWindowContains,historyBufferedWindow,historyBufferNeedsPrefetch,buildHistoryView};
