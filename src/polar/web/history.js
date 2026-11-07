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
function historyPin(value) {
  historyRequire(historyId(value?.dataset_id)&&historyRevision(value?.dataset_revision)&&/^[a-f0-9]{64}$/.test(value?.import_receipt_id)&&/^[a-f0-9]{64}$/.test(value?.manifest_sha256));
  historyRequire(value.basis?.ohlc_basis==='VENDOR_RAW_UNADJUSTED'&&value.basis.adjusted_close_basis==='VENDOR_SPLIT_AND_DIVIDEND_ADJUSTED'&&value.basis.volume_basis==='VENDOR_SPLIT_ADJUSTED');
  return historyStable(Object.fromEntries(['dataset_id','dataset_revision','import_receipt_id','manifest_sha256','basis'].map(k=>[k,value[k]])));
}
function createHistoryClient(fetcher) {
  let controller=null;
  return {
    cancel(){controller?.abort();},
    async load(selection={}) {
      controller?.abort();const own=new AbortController();controller=own;
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
      // Fetch the bounded admitted asset once; range selection uses these exact
      // observations. No market calendar padding or recursive-state reseeding.
      const start=instrument.first_date,end=historyDayAfter(instrument.last_date);
      const query=new URLSearchParams({instrument_id:instrument.instrument_id,start,end,limit:'1000',warmup_sessions:'0'});
      let rows=[],metadata=null;cursor=null;request=null;const cursors=new Set();
      do {
        const page=await read(prefix+'/bars?'+query+(cursor?'&cursor='+encodeURIComponent(cursor):''));
        historyRequire(page.schema_version==='polar.history-bars/1'&&historyPin(page)===pin&&page.instrument_id===instrument.instrument_id,'HISTORY_BARS_IDENTITY_MISMATCH');
        historyRequire(page.window?.start===start&&page.window?.end_exclusive===end&&typeof page.request_identity==='string'&&(!request||request===page.request_identity),'HISTORY_REQUEST_MISMATCH');request=page.request_identity;
        historyRequire(Array.isArray(page.rows)&&page.rows.length===page.row_count&&page.row_count<=1000,'HISTORY_PAGE_INVALID');
        if(metadata)historyRequire(historyStable([page.coverage,page.fitness,page.data_status,page.warmup?.status])===historyStable([metadata.coverage,metadata.fitness,metadata.data_status,metadata.warmup?.status]),'HISTORY_PAGE_STATUS_MISMATCH');
        for(const row of page.rows){
          historyRequire(historyDate(row.session_date)&&row.row_role==='VISIBLE'&&row.session_date>=start&&row.session_date<end&&(!rows.length||rows.at(-1).session_date<row.session_date),'HISTORY_ROW_ORDER_MISMATCH');
          historyRequire(['open','high','low','close','adjusted_close','volume'].every(k=>row[k]===null||typeof row[k]==='string'),'HISTORY_NUMERIC_TOKEN_INVALID');rows.push(row);
        }
        historyRequire(rows.length<=5000,'HISTORY_ASSET_PROFILE_EXCEEDED');
        metadata=page;cursor=page.next_cursor;
        historyRequire(cursor===null||(typeof cursor==='string'&&cursor.length<=2048&&!cursors.has(cursor)),'HISTORY_CURSOR_INVALID');
        historyRequire(page.window_complete===(cursor===null),'HISTORY_PAGE_INCOMPLETE');
        if(cursor)cursors.add(cursor);
      }while(cursor);
      historyRequire(metadata.window_complete===true&&rows.length===metadata.coverage.observed_in_window,'HISTORY_WINDOW_INCOMPLETE');
      return {catalog,revision:summary,assets,instrument,rows,bars:metadata};
    }
  };
}
function buildHistoryView(context) {
  const bars=context.rows.map(row=>({...row,time:row.session_date,endTime:row.session_date,
    originalStatuses:[row.price_status],coverage:{observed:row.price_status==='OBSERVED'?1:0,supplied:1,calendar:context.bars?.coverage.calendar_status||'UNVERIFIED'}}));
  return {history:true,bars,equity:bars.map(b=>({time:b.time,value:null,at:null,status:'NO_STRATEGY_RESULT'})),markers:[],sma:[],baseClose:null,initialCash:null};
}
