// Adapted selected workspace: retained backend records, no fixture/demo fallback.
'use strict';
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const element = (tag, text, className) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node;};
const usd = n => numberOrNull(n) === null ? 'Unavailable' : (Number(n) < 0 ? '−' : '') + '$' + String(n).replace(/^-/, '');
const percent = n => numberOrNull(n) === null ? 'Unavailable' : (n > 0 ? '+' : '') + Number(n).toFixed(2) + '%';
const signedUSD = n => (Number(n) > 0 ? '+' : '') + usd(n), cn = n => numberOrNull(n) === null ? '' : n < 0 ? 'negative' : n > 0 ? 'positive' : '';
const fmtDate = t => historyDate(t) ? new Date(t+'T00:00:00Z').toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric',timeZone:'UTC'})+' · session date' : t && Number.isFinite(Date.parse(t)) ? new Date(t).toLocaleString('en-GB', {day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit', hour12:false, timeZone:'UTC'}) + ' UTC' : 'Unavailable';
const shortDate = t => fmtDate(t).slice(0, 11);
const themeKey = 'polar-retained-theme-v1', sessionKey = 'polar-retained-workspace-v1';
let state = {...restoredControls(null, 0), dataMode:'real',assetId:null, strategyId:null, cursor:0, inspect:0, measurement:null, infoId:null};
let dataset = null, detail = null, view = emptyView(), catalog = [], runRows = [], datasetOffset = 0, runOffset = 0;
let researchWorkspace=null;
let mainResearchClient=null,mainResearch={page:null,loading:false,error:null,offset:0},mainResearchSelection=null;
let comparisonCache=null,comparisonBenchmark=true,mainResearchReturnFocus=null;
let chart, loading = false, loadError = null, flow = 0, assetQuery = '', assetOptionIndex = 0, rendering = false, restoreFrame = 0;
let pendingSelection=null, failedSelection=null;
let historyContext=null,historyCatalogCursor=null,pendingHistoryRequest=null,pendingPlotRange=null;
let viewportVersion=0,historyViewportTimer=null,pendingSeriesBuffer=null;
const historyClient=createHistoryClient((...args)=>fetch(...args));
const historyDisplayed=()=>dataset?.kind==='history'||(!dataset&&state.dataMode==='real');
const loader = createLatestLoader((...args) => fetch(...args));
function emptyView() {return {bars:[], equity:[], markers:[], sma:[], baseClose:null, initialCash:null};}
function getAsset() {return {bars:view.bars, baseClose:view.baseClose, symbol:dataset?.instrument.ticker_history[0]?.ticker || dataset?.instrument.instrument_id || 'No instrument', name:dataset?.name || 'No dataset'};}
function getStrategy() {if(historyDisplayed()&&selectedMainResearch())return {name:selectedMainResearch().record.question.label,id:mainResearchSelection};return {name:detail?.run.strategy_version || (historyDisplayed()?'No attributed NAV overlay':'No retained run'), id:detail?.run.id || null};}
function getResult() {return view;}
function sourceAvailable(source, index) {if(historyDisplayed()){if(source==='strategyEquity')return !!getMainComparison()?.usable&&getMainComparison().strategyIndex[index]!==null&&getMainComparison().strategyIndex[index]!==undefined;return index>=0&&index<view.bars.length&&view.bars[index].price_status==='OBSERVED'&&numberOrNull(view.bars[index].close)!==null;}return index >= 0 && index < view.bars.length && indexValue(source === 'assetClose' ? view.bars[index].close : view.equity[index].value, source === 'assetClose' ? view.baseClose : view.initialCash) !== null;}
function anySource(source) {return view.bars.some((_,i)=>(!historyDisplayed()||(i>=state.lo&&i<=state.hi))&&sourceAvailable(source,i));}
function palette() {const c = getComputedStyle(document.documentElement); return Object.fromEntries(['surface','soft','ink','muted','rule','action','equity','benchmark','sma','up','down','positive','negative'].map(k => [k, c.getPropertyValue('--'+k).trim()]));}
function resolvedTheme() {if (state.theme !== 'auto') return state.theme; return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';}
function tell(text) {$('#status').textContent = text;}
function keepScroll(fn) {const x=scrollX,y=scrollY,saved=['#rail-body','#strategy-list','#raw-readout'].map(s=>[$(s),$(s)?.scrollTop||0]),id=document.activeElement?.id;fn();const active=id?document.getElementById(id):null;if(active&&active!==document.activeElement)active.focus({preventScroll:true});const restore=()=>{window.scrollTo(x,y);saved.forEach(([el,top])=>{if(el)el.scrollTop=top})};restore();cancelAnimationFrame(restoreFrame);restoreFrame=requestAnimationFrame(restore);}
function syncModes() {$$('[data-mode]').forEach(b=>b.setAttribute('aria-pressed', String(b.dataset.mode === state.mode)));}
function saveWorkspace() {try {sessionStorage.setItem(sessionKey, JSON.stringify({dataset_id:dataset?.dataset_id,run_id:detail?.run.id,controls:state,history_revision:historyContext?.revision?.dataset_revision,instrument_id:historyContext?.instrument?.instrument_id,history_window:historyDisplayed()?visibleHistoryWindow():null,research_result_id:mainResearchSelection,research_benchmark:comparisonBenchmark}));} catch {}}
function writeURL(push) {const url=new URL(location.href);url.searchParams.set('mode',historyDisplayed()?'real':'retained-test');for(const key of ['dataset','run','revision','instrument'])url.searchParams.delete(key);if(dataset)url.searchParams.set('dataset',dataset.dataset_id);if(historyDisplayed()){if(historyContext?.revision)url.searchParams.set('revision',historyContext.revision.dataset_revision);if(historyContext?.instrument)url.searchParams.set('instrument',historyContext.instrument.instrument_id);}else if(detail)url.searchParams.set('run',detail.run.id);history[push?'pushState':'replaceState'](null,'',url);saveWorkspace();}
function urlSelection() {const params=new URL(location.href).searchParams; return [params.get('dataset'),params.get('run')];}
function selectionLabel(datasetId,runId) {
  const asset=catalog.find(d=>d.dataset_id===datasetId),run=runRows.find(r=>r.run.id===runId);
  return [asset?.name||datasetId||'dataset page',run?.run.strategy_version||runId].filter(Boolean).join(' · ');
}
function renderPending() {
  const box=$('#selection-state');if(!box)return;
  const displayed=dataset?(historyDisplayed()?getAsset().symbol+' price context'+(selectedMainResearch()?' · separate saved portfolio':''):getAsset().symbol+' · '+getStrategy().name):'No committed dataset';
  box.dataset.mode=state.dataMode;$('#open-test-mode').hidden=state.dataMode==='retained-test';
  $('#selection-context').textContent=(historyDisplayed()?'Stored real history · ':'Retained synthetic test · ')+'Displayed: '+displayed;
  $('#selection-pending').textContent=loading?'Updating: '+(pendingSelection?.label||selectionLabel(pendingSelection?.datasetId,pendingSelection?.runId))+(dataset?'. Current display is retained.':'. Waiting for the first complete context.'):loadError?'Update failed · '+loadError+'. '+(dataset?'Last valid display retained.':'No valid display available.'):dataset?'Context ready':state.dataMode==='real'?'No registered chart-ready history in the catalog.':'No retained test dataset.';
  box.classList.toggle('updating',loading);box.classList.toggle('failed',!!loadError);
  $('#retry-selection').hidden=!failedSelection||loading;
  $('#workspace').setAttribute('aria-busy',String(loading));
}
function boundsForSelection(nextView,controls,previousWindow) {
  const bars=nextView.bars;if(!bars.length)return {lo:0,hi:0};
  if(controls.rangeId==='Custom'&&previousWindow?.first&&previousWindow?.last){
    const lo=bars.findIndex(b=>Date.parse(b.endTime)>=Date.parse(previousWindow.first));
    let hi=-1;for(let i=0;i<bars.length;i++)if(Date.parse(b.time)<=Date.parse(previousWindow.last))hi=i;
    if(lo>=0&&hi>=lo)return {lo,hi};
    return {lo:0,hi:bars.length-1,rangeId:'All'};
  }
  if(controls.rangeId==='All')return {lo:0,hi:bars.length-1};
  const last=new Date(bars.at(-1).endTime),lower=new Date(last);lower.setUTCHours(0,0,0,0);
  if(controls.rangeId==='1W')lower.setUTCDate(lower.getUTCDate()-7);
  else lower.setUTCMonth(lower.getUTCMonth()-({'1M':1,'3M':3,'6M':6,'12M':12}[controls.rangeId]||1));
  const first=bars.findIndex(b=>Date.parse(b.endTime)>=lower);
  return {lo:first<0?0:first,hi:bars.length-1};
}
function displayedHistoryControls(){return historyContext?.seriesControls||{sma:false,ema:false,bollinger:false,rsi:false,benchmark:false,indicators:indicatorDefaults(),referenceFamily:'RAW_PRICE_RELATIVE'};}
function historyWindow(context,rangeId,previous,explicit){
  const first=context.instrument?.first_date,last=context.instrument?.last_date;if(!historyDate(first)||!historyDate(last))return null;
  const end=historyDayAfter(last);let start=first,finish=end;
  if(explicit){start=explicit.start;finish=explicit.end_exclusive;}
  else if(rangeId==='Custom'&&previous.first&&previous.last){start=previous.first;finish=historyDayAfter(previous.last);}
  else if(rangeId!=='All'){
    const d=new Date(last+'T00:00:00Z');if(rangeId==='1W')d.setUTCDate(d.getUTCDate()-7);else d.setUTCMonth(d.getUTCMonth()-({'1M':1,'3M':3,'6M':6,'12M':12}[rangeId]||1));start=d.toISOString().slice(0,10);
  }
  start=start<first?first:start;finish=finish>end?end:finish;
  return start<finish?{start,end_exclusive:finish}:{start:first,end_exclusive:end};
}
function canReuseHistoryContext(){return !!historyContext?.revision&&(!pendingHistoryRequest||pendingHistoryRequest.seriesOnly===true);}
function currentHistoryRequest(){return pendingHistoryRequest||{datasetId:historyContext?.revision?.dataset_id,revision:historyContext?.revision?.dataset_revision,instrumentId:historyContext?.instrument?.instrument_id};}
function refreshHistoryOverlays(){
  saveWorkspace();if(state.dataMode!=='real'){keepScroll(renderAll);return;}
  const request={...currentHistoryRequest(),seriesOnly:canReuseHistoryContext(),rangeId:state.rangeId,window:null};
  keepScroll(renderRail);loadHistorySelection(request);
}
async function loadHistorySelection(request={}) {
  const token=++flow;loader.cancel();if(!request.seriesOnly)historyClient.cancel();clearTimeout(historyViewportTimer);pendingSeriesBuffer=null;const requestedViewportVersion=viewportVersion;loading=true;loadError=null;failedSelection=null;pendingHistoryRequest=request;
  const controls=historyControls(state),requestedRange=request.rangeId||state.rangeId;
  state.dataMode='real';pendingSelection={label:request.seriesOnly?'series / '+requestedRange:[request.datasetId,request.instrumentId].filter(Boolean).join(' · ')||'registered history catalog'};renderPending();
  const current=()=>token===flow;
  try {
    let next;
    if(request.seriesOnly&&historyContext?.revision)next={...historyContext};
    else try{next=await historyClient.load({...request,catalogCursor:request.catalogCursor??historyCatalogCursor});}
    catch(error){if(error.message!=='HISTORY_INVALID_CURSOR'||!current())throw error;next=await historyClient.load({...error.pinnedSelection,catalogCursor:null});}
    if(!current())return;
    const previousWindow={first:view.bars[state.lo]?.time,last:view.bars[state.hi]?.endTime};
    const window=historyWindow(next,requestedRange,previousWindow,request.window);
    if(window&&historyNeedsSeries(controls)&&HISTORY_SERIES_RUNTIME.enabled){
      const buffer=historyBufferedWindow(next,window);pendingSeriesBuffer={key:historySeriesCacheKey(next,controls),window:buffer};renderSeriesState();
      try{next.series=await historyClient.series(next,controls,buffer);}
      catch(error){if(error.message!=='HISTORY_INVALID_CURSOR'||!current())throw error;next.series=await historyClient.series(next,controls,buffer);}
      if(!current())return;
    }else next.series=null;
    next.seriesControls=next.series?controls:{...controls,sma:false,ema:false,bollinger:false,rsi:false,benchmark:false};
    next.seriesUnavailable=historyNeedsSeries(controls)&&!HISTORY_SERIES_RUNTIME.enabled?'C_RUNTIME_NOT_QUALIFIED':null;
    const nextView=buildHistoryView(next),same=dataset?.kind==='history'&&dataset.dataset_id===next.revision?.dataset_id&&dataset.dataset_revision===next.revision?.dataset_revision&&dataset.instrument.instrument_id===next.instrument?.instrument_id;
    const preserveViewport=same&&request.seriesOnly||viewportVersion!==requestedViewportVersion,latestWindow={start:view.bars[state.lo]?.time,end_exclusive:view.bars[state.hi]?historyDayAfter(view.bars[state.hi].time):null};
    const displayWindow=preserveViewport&&latestWindow.start&&latestWindow.end_exclusive?latestWindow:window;
    const nextState={...state,dataMode:'real',rangeId:preserveViewport?state.rangeId:requestedRange,granularity:'1D',assetId:next.instrument?.instrument_id||null,strategyId:null};
    if(displayWindow&&nextView.bars.length){const first=nextView.bars.findIndex(b=>b.time>=displayWindow.start),indices=nextView.bars.map((b,i)=>b.time<displayWindow.end_exclusive?i:-1);nextState.lo=Math.max(0,first);nextState.hi=Math.max(nextState.lo,...indices);}
    else Object.assign(nextState,boundsForSelection(nextView,nextState,previousWindow));
    const remap=i=>nextView.bars.findIndex(b=>b.time===view.bars[i]?.time);
    if(same){nextState.cursor=remap(state.cursor);nextState.inspect=remap(state.inspect);if(nextState.measurement){const start=remap(state.measurement.start),end=remap(state.measurement.end);nextState.measurement=start>=0&&end>=0?{...state.measurement,start,end}:null;}}
    else{nextState.measurement=null;nextState.infoId=null;nextState.cursor=nextState.inspect=nextState.lo;}
    const nextDataset=next.revision?{kind:'history',dataset_id:next.revision.dataset_id,dataset_revision:next.revision.dataset_revision,name:next.instrument?.source_symbol||next.instrument?.display_symbol||next.revision.dataset_id,instrument:{...next.instrument,ticker_history:next.instrument?[{ticker:next.instrument.display_symbol||next.instrument.source_symbol||next.instrument.instrument_id}]:[]}}:null;
    // Bars, all series pages, their parameters and visible range commit together.
    historyContext=next;historyCatalogCursor=request.catalogCursor??null;
    dataset=nextDataset;detail=null;view=nextView;runRows=[];runOffset=datasetOffset=0;
    catalog=next.assets.map(a=>({kind:'history',dataset_id:a.instrument_id,name:a.display_symbol||a.source_symbol||a.instrument_id,instrument:{...a,ticker_history:[{ticker:a.display_symbol||a.source_symbol||a.instrument_id}]}}));state=nextState;
    state.cursorSource='assetClose';clampCursor();invalidateRange();if(!same)cancelGesture();
    loading=false;pendingSelection=pendingHistoryRequest=pendingPlotRange=pendingSeriesBuffer=null;closeAssets();keepScroll(renderAll);writeURL(!!request.push);scheduleViewportSeries();
    tell(next.revision?'Stored immutable history · '+(next.bars?.data_status||'EMPTY_WINDOW')+' · saved portfolio research is listed below.':'No registered chart-ready history. Saved portfolio research remains separately available.');
  }catch(error){if(!current())return;loading=false;loadError=/^[A-Z0-9_]+$/.test(error.message)?error.message:'HISTORY_UNAVAILABLE';failedSelection={history:true,request};pendingSelection=pendingHistoryRequest=pendingPlotRange=pendingSeriesBuffer=null;renderPending();syncToolbar();keepScroll(renderRail);renderSeriesState();if(!view.bars.length)renderChart();tell('History update failed · '+loadError+'. '+(dataset?'Last valid displayed context retained.':'No valid history display available.')+' Retry is available.');}
}
async function loadSelection(datasetId, runId, {push=false, catalogPage=null, runsPage=0, restore=null}={}) {
  if(state.dataMode!=='retained-test')return loadHistorySelection({datasetId:datasetId||historyContext?.revision?.dataset_id,revision:historyContext?.revision?.dataset_revision,instrumentId:historyContext?.instrument?.instrument_id,push});
  const token=++flow;loader.cancel();historyClient.cancel();clearTimeout(historyViewportTimer);pendingSeriesBuffer=null;pendingHistoryRequest=pendingPlotRange=null;loading=true;loadError=null;failedSelection=null;
  const intent={datasetId,runId,options:{push,catalogPage,runsPage,restore}};
  pendingSelection={datasetId,runId};renderPending();
  const current=()=>token===flow;
  try {
    let nextCatalog=catalog,nextDatasetOffset=datasetOffset,nextRunRows=[],nextRunOffset=0,nextDataset=null,nextDetail=null,nextView=emptyView();
    if(catalogPage!==null||!catalog.length){
      const page=await loader.load('/v1/ui/datasets?limit=10&offset='+(catalogPage??datasetOffset));if(!current()||page===null)return;
      nextCatalog=page.items;nextDatasetOffset=page.offset;
    }
    let selected=null,selectedRun=null;
    // Run-only links resolve their bound dataset; never infer it from catalog order.
    if(!datasetId&&runId){
      selectedRun=await loader.load('/v1/ui/runs/'+encodeURIComponent(runId));if(!current()||selectedRun===null)return;
      selected=selectedRun.dataset;datasetId=selected.dataset_id;
    }
    datasetId=datasetId||nextCatalog[0]?.dataset_id;
    if(datasetId){
      selected=selected||nextCatalog.find(d=>d.dataset_id===datasetId)||await loader.load('/v1/ui/datasets/'+encodeURIComponent(datasetId));if(!current()||selected===null)return;
      if(selected.dataset_id!==datasetId)throw new Error('DATASET_RESPONSE_MISMATCH');
      if(selected.market.frequency!=='daily')throw new Error('UNSUPPORTED_FREQUENCY');
      const page=await loader.load('/v1/ui/datasets/'+encodeURIComponent(datasetId)+'/runs?limit=10&offset='+runsPage);if(!current()||page===null)return;
      nextRunRows=page.items;nextRunOffset=page.offset;
      runId=runId||nextRunRows.find(r=>r.run.strategy_version===detail?.run.strategy_version)?.run.id||nextRunRows[0]?.run.id;
      pendingSelection={datasetId,runId};renderPending();
      if(runId&&!selectedRun){selectedRun=await loader.load('/v1/ui/runs/'+encodeURIComponent(runId)+'?dataset_id='+encodeURIComponent(datasetId));if(!current()||selectedRun===null)return;}
      if(selectedRun&&selectedRun.dataset.dataset_id!==datasetId)throw new Error('RUN_DATASET_MISMATCH');
      if(selectedRun&&selectedRun.run.id!==runId)throw new Error('RUN_RESPONSE_MISMATCH');
      nextDataset=selectedRun?.dataset||selected;nextDetail=selectedRun;
      nextView=buildView(nextDataset,nextDetail?.report,state.granularity);
    }
    if(!current())return;
    const previousWindow={first:view.bars[state.lo]?.time,last:view.bars[state.hi]?.endTime};
    const nextState={...state,assetId:nextDataset?nextDataset.dataset_id+':'+nextDataset.instrument.instrument_id:null,strategyId:nextDetail?.run.id||null};
    const sameContext=nextDataset?.dataset_id===dataset?.dataset_id&&(nextDetail?.run.id||null)===(detail?.run.id||null);
    if(restore&&restore.dataset_id===nextDataset?.dataset_id&&(restore.run_id||null)===(nextDetail?.run.id||null))Object.assign(nextState,restoredControls(restore.controls,nextView.bars.length));
    else Object.assign(nextState,boundsForSelection(nextView,nextState,previousWindow));
    if(!sameContext){nextState.measurement=null;nextState.infoId=null;nextState.cursor=nextState.inspect=nextState.lo;}
    // Atomic commit: no displayed catalog, Orders, list or bars changed before this point.
    catalog=nextCatalog;datasetOffset=nextDatasetOffset;runRows=nextRunRows;runOffset=nextRunOffset;
    dataset=nextDataset;detail=nextDetail;view=nextView;state=nextState;
    if(!anySource(state.cursorSource))state.cursorSource=anySource('assetClose')?'assetClose':'strategyEquity';
    clampCursor();invalidateRange();if(!sameContext)cancelGesture();
    loading=false;pendingSelection=null;closeAssets();keepScroll(renderAll);writeURL(push);
    tell(dataset?(detail?'Retained '+detail.run.state+' job · report '+(detail.report?.status||detail.report_availability):'Dataset has no runs on this page.'):'No retained datasets. Nothing was created.');
  }catch(error){
    if(!current())return;
    loading=false;loadError=/^[A-Z0-9_]+$/.test(error.message)?error.message:'API_UNAVAILABLE';failedSelection=intent;pendingSelection=null;
    closeAssets();renderPending();syncToolbar();
    // Keep all committed observations/result/list/context and compatible measurement on failure.
    if(!view.bars.length)renderChart();
    tell('Unable to update · '+loadError+'. '+(dataset?'Last valid retained context is still displayed.':'No valid retained context is available.')+' Retry is available.');
  }
}
function selectAsset(id) {closeAssets();if(state.dataMode==='real')loadHistorySelection({datasetId:historyContext?.revision?.dataset_id,revision:historyContext?.revision?.dataset_revision,instrumentId:id,push:true});else loadSelection(id,null,{push:true});}
function selectStrategy(id) {if(loading||id!==detail?.run.id)loadSelection(dataset?.dataset_id,id,{push:true,runsPage:runOffset});}
function filteredAssets() {return catalog.filter(d=>(d.name+' '+d.dataset_id+' '+d.instrument.instrument_id+' '+(d.instrument.ticker_history[0]?.ticker||'')).toLowerCase().includes(assetQuery));}
function renderAssets() {
  const list=filteredAssets(), box=$('#asset-options'); box.replaceChildren();box.hidden=false;$('#asset-popover').hidden=false; $('#asset-search').setAttribute('aria-expanded','true');
  list.forEach((d,i)=>{const button=element('button');button.type='button';button.role='option';button.id='catalog-option-'+i;button.tabIndex=-1;button.setAttribute('aria-selected',String(i===assetOptionIndex));button.append(element('b',d.instrument.ticker_history[0]?.ticker||d.instrument.instrument_id),element('span',d.name+' · '+d.dataset_id));button.onmousedown=e=>e.preventDefault();button.onclick=()=>selectAsset(d.dataset_id);box.append(button);});
  if(!list.length)box.append(element('p','No matching dataset on this page.','panel-note'));
  $('#asset-search').setAttribute('aria-activedescendant',list[assetOptionIndex]?'catalog-option-'+assetOptionIndex:'');
}
function closeAssets() {$('#asset-popover').hidden=true;$('#asset-options').hidden=true;$('#asset-search').setAttribute('aria-expanded','false');$('#asset-search').removeAttribute('aria-activedescendant');$('#asset-search').value=dataset?getAsset().symbol+' · '+dataset.name:'';}
function setGranularity(interval) {
  if(!dataset||!GRANULARITIES.includes(interval)||(historyDisplayed()&&interval!=='1D'))return;
  state.granularity=interval;state.measurement=null;state.infoId=null;view=buildView(dataset,detail?.report,interval);state.lo=0;state.hi=Math.max(0,view.bars.length-1);state.cursor=state.inspect=0;state.rangeId='All';cancelGesture();renderAll();saveWorkspace();tell(interval+' · supplied daily rows only; incomplete buckets stay unavailable.');
}
function visibleHistoryWindow(){return view.bars[state.lo]&&view.bars[state.hi]?{start:view.bars[state.lo].time,end_exclusive:historyDayAfter(view.bars[state.hi].time)}:null;}
function renderSeriesState(){
  const label=$('#series-state');if(!label)return;
  const needed=historyDisplayed()&&historyNeedsSeries(state),window=visibleHistoryWindow();
  const requested=needed&&historyContext?historySeriesCacheKey(historyContext,historyControls(state)):null;
  const displayed=historyContext?.series?historySeriesCacheKey(historyContext,historyContext.series.controls):null;
  const covered=needed&&!!historyContext?.series&&requested===displayed&&historyWindowContains(historyContext.series.window,window);
  const failed=needed&&loadError&&failedSelection?.request?.seriesOnly;
  label.hidden=!needed||covered&&!loading;
  label.textContent=failed?'Indicator update unavailable · candles remain interactive':pendingSeriesBuffer?'Indicators loading · candles remain interactive':covered?'Requested indicators updating · candles remain interactive':'Indicator data not loaded here · candles remain interactive';
}
function scheduleViewportSeries(){
  clearTimeout(historyViewportTimer);renderSeriesState();
  if(!historyDisplayed()||!historyContext?.revision||!historyNeedsSeries(state)||!HISTORY_SERIES_RUNTIME.enabled||loading&&!pendingHistoryRequest?.seriesOnly)return;
  const window=visibleHistoryWindow();if(!window)return;
  const key=historySeriesCacheKey(historyContext,historyControls(state));
  if(historyContext.series&&key===historySeriesCacheKey(historyContext,historyContext.series.controls)&&!historyBufferNeedsPrefetch(historyContext,historyContext.series.window,window))return;
  if(pendingSeriesBuffer?.key===key&&historyWindowContains(pendingSeriesBuffer.window,window))return;
  // Coalesce a burst before requesting a new backend buffer. Panning never waits.
  const intent=flow;historyViewportTimer=setTimeout(()=>{if(intent!==flow||!historyDisplayed())return;loadHistorySelection({...currentHistoryRequest(),seriesOnly:true,rangeId:state.rangeId,window:visibleHistoryWindow()});},80);
}
function commitViewport(lo,hi,rangeId='Custom',dispatch=false){
  viewportVersion++;state.lo=lo;state.hi=hi;state.rangeId=rangeId;pendingPlotRange=null;
  if(dispatch&&chart){rendering=true;chart.dispatchAction({type:'dataZoom',startValue:lo,endValue:hi});rendering=false;}
  clampCursor();invalidateRange();syncToolbar();drawMeasurement();showRaw(state.inspect);saveWorkspace();scheduleViewportSeries();
}
function setPreset(id) {
  if(!view.bars.length)return;
  const last=new Date(view.bars.at(-1).endTime), lower=new Date(last); lower.setUTCHours(0,0,0,0);
  if(id==='1W')lower.setUTCDate(lower.getUTCDate()-7);else if(id==='All')lower.setTime(Date.parse(view.bars[0].time));else lower.setUTCMonth(lower.getUTCMonth()-({'1M':1,'3M':3,'6M':6,'12M':12}[id]||1));
  commitViewport(Math.max(0,view.bars.findIndex(b=>Date.parse(b.endTime)>=lower)),view.bars.length-1,id,true);tell('Showing available observations; requested range is not additional history.');
}
function clampCursor() {state.cursor=Math.max(state.lo,Math.min(state.hi,state.cursor));state.inspect=Math.max(state.lo,Math.min(state.hi,state.inspect));}
function setTheme(theme) {state.theme=theme;try{localStorage.setItem(themeKey,theme);}catch{}keepScroll(renderAll);document.getElementById('theme-'+theme)?.focus({preventScroll:true});saveWorkspace();tell('Theme changed; compatible measurement retained.');}
function openTools() {$('#rail-inner').classList.add('mobile-open');if(innerWidth<701)$('#close-tools').focus({preventScroll:true});}
function panelNote(parent,text) {parent.append(element('p',text,'panel-note'));}
function metricValue(metric, percentage=false) {if(!metric||metric.value===null||metric.value===undefined)return 'Unavailable';return percentage?percent(Number(metric.value)*100):metric.value;}
function metricDescription(metric) {return metric ? [metric.status,metric.evidence_status,metric.reason].filter(Boolean).join(' · ') : 'UNAVAILABLE';}
function addDefinition(dl,label,value) {dl.append(element('dt',label),element('dd',value));}
function checkbox(parent,id,title,note,key,disabled) {const label=element('label',undefined,'overlay-choice'),input=element('input');input.type='checkbox';input.id=id;input.checked=state[key]===true;input.disabled=disabled;const span=element('span');span.append(element('b',title),element('small',note));label.append(input,span);parent.append(label);input.onchange=()=>{state[key]=input.checked;if(['sma','ema','bollinger','rsi','benchmark'].includes(key))refreshHistoryOverlays();else{keepScroll(renderAll);saveWorkspace();}};}
function legacySmaAvailable(){return !historyDisplayed()&&state.indicators.sma.period===20&&view.sma.some(x=>x.value!==null);}
function historyIndicatorNote(key){
  if(!state[key])return 'Not requested. Enabling uses backend full-revision computation; no viewport seed.';
  if(historyContext?.seriesUnavailable)return 'Not rendered · '+historyContext.seriesUnavailable+'. Requested settings are retained.';
  const names=key==='bollinger'?['bb_middle','bb_upper','bb_lower']:[key],series=historyContext?.series;
  if(!series||!displayedHistoryControls()[key])return loading?'Updating · previous coherent display retained.':'Backend result unavailable. No client calculation is substituted.';
  const metadata=names.map(n=>series.metadata.series_metadata[n]),first=metadata[0];
  const states=[...new Set(metadata.map(m=>m?.status||'UNAVAILABLE'))].join('/');
  return states+' · displayed period '+first.period+(key==='bollinger'?' / k '+series.controls.indicators.bollinger.deviation:'')+' · requires '+first.required_history+', available '+first.available_history+' ('+first.available_history_scope+'). Computed from '+first.computed_from+'; first valid '+(first.first_valid_session||'none')+'. Transport warmup '+series.metadata.warmup.status+'. Per-date WARMUP/GAP reasons remain in the readout.'+(loading?' Updating requested settings; displayed values retained.':'');
}
function historyReferenceNote(){
  if(!state.benchmark)return 'Not requested. Reference indexes are separate from raw price and funded NAV.';
  const ref=historyContext?.series?.metadata.reference_metadata;
  if(!ref||!displayedHistoryControls().benchmark)return historyContext?.seriesUnavailable||'Backend reference unavailable; no client normalization is substituted.';
  return ref.status+' · '+ref.family+' · fixed full-revision anchor '+(ref.anchor_session||'none')+' · '+ref.common_valid_sessions+' common valid sessions. '+(ref.family==='RAW_PRICE_RELATIVE'?'Raw price-only; no action-correct wealth.':'Provider-adjusted close proxy; not independently reconstructed total return.')+' No funded NAV or Sharpe.';
}
function diagnosticPanel(parent,key,label,text){
  const box=element('details',undefined,'diagnostic-disclosure');box.id='diagnostics-'+key;box.open=state.diagnostics?.[key]===true;
  box.append(element('summary',label));panelNote(box,text);box.ontoggle=()=>{state.diagnostics[key]=box.open;saveWorkspace();};parent.append(box);
}
function overlaySamples(parent,keys){
  const group=element('div',undefined,'overlay-samples');
  for(const [key,label] of keys){const style=overlayStroke(key,palette()),item=element('span',undefined,'overlay-sample'),line=element('i');
    line.setAttribute('aria-hidden','true');line.style.height=style.width+'px';line.style.background=strokeBackground(style);
    item.dataset.series=key;item.append(line,document.createTextNode(label));group.append(item);}
  parent.append(group);
}
function compactOverlayStatus(key){
  if(!state[key])return 'Off';if(loading)return 'Updating · previous display retained';
  if(!historyDisplayed())return key==='sma'&&legacySmaAvailable()?'Retained test only':'Unavailable';
  if(historyContext?.seriesUnavailable)return 'Unavailable · see calculation details';
  const name=key==='bollinger'?'bb_middle':key;
  return historyContext?.series?.metadata.series_metadata[name]?.status||'Unavailable';
}
function indicatorCard(parent,key,title,shortName,period){
  const card=element('section',undefined,'indicator-card');
  const usable=key==='sma'&&legacySmaAvailable();
  checkbox(card,key+'-toggle',title,'Requested '+shortName+period+(key==='rsi'?' · separate oscillator area':''),key,false);
  const settings=element('div',undefined,'indicator-settings'),buttons=element('div',undefined,'period-buttons');buttons.setAttribute('role','group');buttons.setAttribute('aria-label',shortName+' period');
  const periods=key==='rsi'?[5,14,20,50,200]:[5,20,50,200];
  for(const n of periods){const b=element('button',String(n));b.id=key+'-period-'+n;b.setAttribute('aria-pressed',String(period===n));b.onclick=()=>{state.indicators[key].period=n;refreshHistoryOverlays();};buttons.append(b);}settings.append(buttons);
  if(key==='bollinger'){
    const label=element('label','Deviation multiplier','indicator-deviation'),input=element('input');input.id='bollinger-deviation';input.inputMode='decimal';input.value=state.indicators.bollinger.deviation;input.setAttribute('aria-describedby','bollinger-error');label.append(input);settings.append(label);
    const error=element('p','','indicator-error');error.id='bollinger-error';error.role='status';settings.append(error);
    input.onchange=()=>{const raw=input.value.trim().replace(',','.').replace(/^0+(?=\d)/,'');const cap=decimalDelta(raw,'10');if(raw.length>40||!/^\d+(?:\.\d{1,18})?$/.test(raw)||!/[1-9]/.test(raw)||cap===null||(cap[0]!=='-'&&/[1-9]/.test(cap))){input.setAttribute('aria-invalid','true');error.textContent='Enter a positive multiplier up to 10, with at most18 decimal places. Input retained.';return;}state.indicators.bollinger.deviation=raw;input.setAttribute('aria-invalid','false');error.textContent='Requested multiplier '+raw;refreshHistoryOverlays();};
  }
  const note=historyDisplayed()?historyIndicatorNote(key):usable?'Legacy test-only SMA20 display transform. Not a qualified real-history indicator.':key==='sma'&&state.dataMode==='retained-test'&&period===20?'Insufficient gap-free retained test observations for SMA20.':'Not rendered: accepted backend calculation/warmup result unavailable.';
  overlaySamples(settings,key==='bollinger'?[['bb_upper','Upper'],['bb_middle','Middle'],['bb_lower','Lower']]:[[key,shortName]]);
  panelNote(settings,compactOverlayStatus(key));diagnosticPanel(settings,key,'Calculation details',note);card.append(settings);parent.append(card);
}
function setDataMode(mode){
  if(mode===state.dataMode)return;clearTimeout(historyViewportTimer);pendingSeriesBuffer=null;
  state.dataMode=mode;loadError=null;
  if(mode==='retained-test'){keepScroll(renderRail);const [asset,run]=urlSelection();loadSelection(run?asset:null,run||null,{catalogPage:0});}
  else loadHistorySelection({});
}
function renderRail() {
  const body=$('#rail-body');body.replaceChildren(element('h3',state.mode));
  if(state.mode==='Settings') {
    body.append(element('p','Appearance changes preserve your research context.','panel-intro'));
    const settings=element('div',undefined,'settings-group');settings.append(element('h4','Color theme'));const group=element('div',undefined,'theme-options');
    ['auto','light','dark'].forEach(mode=>{const b=element('button',mode[0].toUpperCase()+mode.slice(1));b.id='theme-'+mode;b.setAttribute('aria-pressed',String(state.theme===mode));b.onclick=()=>setTheme(mode);group.append(b);});settings.append(group);
    panelNote(settings,state.theme==='auto'?'Auto · system resolves '+resolvedTheme()+'.':'Manual '+state.theme+' · overrides OS changes.');body.append(settings);
    checkbox(body,'marker-toggle','Execution markers','Show attributed actual signed fills; no inferred round trips.','markers',!view.markers.length);
    const convention=element('div',undefined,'context-note');convention.append(element('b','Display convention'),element('p',historyDisplayed()?'Raw unadjusted OHLC in '+(historyContext?.revision?.basis.price_unit||'source units')+'. Provider-adjusted close and split-adjusted volume remain separate. Price candles remain separate from saved portfolio NAV.':'Price ÷ first usable open × 100. Retained NAV ÷ report initial cash × 100. Separate bases; no range rebasing.'));body.append(convention);
    panelNote(body,'Auto follows the OS. Unresolved preference uses Dark. Manual Light/Dark takes precedence until Auto or Reset.');
    const source=element('div',undefined,'settings-group');source.append(element('h4','Data source'));const choices=element('div',undefined,'theme-options');
    for(const [mode,label] of [['real','Stored history'],['retained-test','Retained test']]){const b=element('button',label);b.id='mode-'+mode;b.setAttribute('aria-pressed',String(state.dataMode===mode));b.onclick=()=>setDataMode(mode);choices.append(b);}source.append(choices);panelNote(source,'Stored history uses registered immutable revisions. Retained test records are explicitly separated synthetic fixtures, never a real-data fallback.');body.append(source);return;
  }
  if(state.mode==='Overlays') {
    body.append(element('p','One research result; independent price context.','panel-intro'));
    indicatorCard(body,'sma','Moving average · SMA','SMA',state.indicators.sma.period);
    indicatorCard(body,'ema','Exponential average · EMA','EMA',state.indicators.ema.period);
    indicatorCard(body,'bollinger','Bollinger Bands','BB',state.indicators.bollinger.period);
    indicatorCard(body,'rsi','Relative strength · RSI','RSI',state.indicators.rsi.period);
    const benchmark=element('div',undefined,'indicator-card');checkbox(benchmark,'benchmark-toggle','Buy-and-hold · price reference','Requested raw price-relative context only; not funded NAV or certified total return.','benchmark',false);if(historyDisplayed()){
      const label=element('label','Reference basis','indicator-deviation'),select=element('select');select.id='reference-family';
      for(const [value,text] of [['RAW_PRICE_RELATIVE','Raw price relative'],['PROVIDER_ADJUSTED_CLOSE_INDEX','Provider-adjusted close proxy']]){const option=element('option',text);option.value=value;select.append(option);}select.value=state.referenceFamily||'RAW_PRICE_RELATIVE';select.onchange=()=>{state.referenceFamily=select.value;refreshHistoryOverlays();};label.append(select);benchmark.append(label);
    }overlaySamples(benchmark,[['asset_reference','Asset'],['benchmark_reference','VTI']]);diagnosticPanel(benchmark,'reference','Reference details',historyDisplayed()?historyReferenceNote():'Not rendered: accepted backend reference values/basis are unavailable. No client replacement is calculated.');body.append(benchmark);
    const context=element('div',undefined,'context-note');context.append(element('b','Settings are retained'),element('p','Periods change requested backend parameters, not the active asset or range. All pages/values/statuses commit together; previous coherent display is retained while updating.'));body.append(context);return;
  }
  if(historyDisplayed()) {
    panelNote(body,historyContext?.instrument?(getAsset().symbol+' · stored history'):'Choose registered stored history.');
    panelNote(body,'NO_ATTRIBUTED_ORDERS · no order tape is bound to this price history. Open a saved portfolio from the main strategy list to inspect its supplied ledger.');
    if(historyContext?.revision)diagnosticPanel(body,'source','Pinned source details',historyContext.revision.dataset_revision+' · Calendar '+(historyContext.bars?.coverage.calendar_status||historyContext.revision.calendar_status||'UNVERIFIED')+' · PIT '+(historyContext.revision.fitness?.causal_PIT_fitness||'INSUFFICIENT_EVIDENCE'));return;
  }
  panelNote(body,dataset?getAsset().symbol+' · '+getStrategy().name:'Choose an available retained dataset and run.');
  if(!detail?.report) {panelNote(body,detail?'Report unavailable · '+detail.run.state:loading?'Loading retained records…':loadError?'Unavailable · '+loadError:'No retained run selected.');return;}
  const report=detail.report;
  if(report.status==='INVALID')panelNote(body,'INVALID retained calculation · '+(report.diagnostic||'Diagnostic unavailable')+'. Portfolio values are unavailable.');
  report.fills.forEach((f,index)=>{const article=element('article',undefined,'order-entry');article.append(element('b',(Number(f.quantity)<0?'SELL':'BUY')+' · '+f.quantity+' shares'),element('p',usd(f.price)+' · fee '+f.fee+' '+(f.currency||report.units.fee)),element('small','Fill '+fmtDate(f.fill_at)),element('p','Receipt '+fmtDate(f.receipt_at)),element('p','Decision session '+f.decision_session_id),element('small','Fill row '+(index+1)+' · presentation reference'));body.append(article);});
  if(!report.fills.length)panelNote(body,'No actual fills in this retained report.');
  report.orders.forEach(o=>{const row=element('article',undefined,'order-entry');row.append(element('b','Instruction · '+o.status),element('small','Decision '+o.decision_session_id),element('p',o.reason||'No additional reason'));const tape=report.order_tape.find(t=>t.decision_session_id===o.decision_session_id);if(tape)row.append(element('p',tape.quantity+' shares · '+fmtDate(tape.decision_at)));body.append(row);});
  panelNote(body,'Signed fills and instructions are separate; no closed-trade count or per-trade P&L is inferred.');
}
async function loadMainResearch(offset=mainResearch.offset){
  if(!mainResearchClient)return;
  mainResearch.loading=true;mainResearch.error=null;mainResearch.offset=offset;if(historyDisplayed())keepScroll(renderRows);
  try{
    const page=await mainResearchClient.load(offset,null,{includeDetails:true});if(!page)return;
    mainResearch.page=page;mainResearch.loading=false;mainResearch.error=null;if(!page.catalog.total){mainResearchSelection=null;mainResearch.chosen=null;comparisonCache=null;state.measurement=null;state.cursorSource='assetClose';}
  }catch(error){mainResearch.loading=false;mainResearch.error=/^[A-Z0-9_]+$/.test(error.message)?error.message:'RESEARCH_API_UNAVAILABLE';}
  if(historyDisplayed())keepScroll(()=>{renderRows();syncToolbar();renderChart();drawMeasurement();});
}
function selectedMainResearch(){return mainResearch.page?.details?.find(d=>d.result_id===mainResearchSelection)||(mainResearch.chosen?.result_id===mainResearchSelection?mainResearch.chosen:null);}
function getMainComparison(){
  const saved=selectedMainResearch();if(!historyDisplayed()||!saved)return null;
  if(comparisonCache?.bars!==view.bars||comparisonCache?.saved!==saved){const model=researchComparison(saved,view.bars);model.historySummary=researchHistoryCompatibility(saved,historyContext);comparisonCache={bars:view.bars,saved,model};}
  return comparisonCache.model;
}
function priceDisplayValue(value){const model=getMainComparison();return model?.usable?researchNormalize(value,model.priceBase):numberOrNull(value);}
function selectMainResearch(id,fit=true){
  mainResearch.chosen=mainResearch.page?.details?.find(d=>d.result_id===id)||mainResearch.chosen;mainResearchSelection=id;comparisonCache=null;state.measurement=null;state.cursorSource='assetClose';cancelGesture();
  const model=getMainComparison();if(fit&&model?.usable){viewportVersion++;state.lo=model.first;state.hi=model.last;state.rangeId='Custom';state.cursor=state.inspect=state.lo;}
  keepScroll(renderAll);saveWorkspace();tell(model?.usable?'Saved strategy and benchmark compared on Index100. Portfolio is not attributed to this asset.':model?.reason||'Select stored history to compare.');
}
function comparisonReadout(i){const model=getMainComparison();if(!model?.usable)return '';return '\nSaved portfolio sample '+(model.times[i]||'not supplied on this calendar date')+' · strategy '+(model.strategyRaw[i]??'Unavailable')+' USD · benchmark '+(model.benchmarkRaw[i]??'Unavailable')+' USD · Index100 baseline '+model.baselineDate+'; no fills inferred.';}
function renderComparisonContext(){
  const host=$('#comparison-context');if(!host)return;host.replaceChildren();const saved=selectedMainResearch();host.hidden=!historyDisplayed()||!saved;if(host.hidden)return;
  const model=getMainComparison(),r=saved.record,head=element('div',undefined,'comparison-heading');head.append(element('b',researchReadable(model?.strategy?.label||r.question.label)),element('span',researchPhase(r)+' · '+r.grid[0].slice(0,10)+' → '+r.grid.at(-1).slice(0,10)));
  const fit=element('button','Fit research dates');fit.id='fit-research';fit.disabled=!model?.usable;fit.onclick=()=>selectMainResearch(saved.result_id,true);
  const clear=element('button','Price only');clear.id='clear-comparison';clear.onclick=()=>selectMainResearch(null,false);
  const open=element('button','Read research');open.id='comparison-read-research';open.onclick=()=>{mainResearchReturnFocus=open.id;researchWorkspace?.openResult(saved.result_id,mainResearch.page.catalog.offset);};
  const controls=element('div',undefined,'comparison-actions');const label=element('label'),check=element('input');check.type='checkbox';check.checked=comparisonBenchmark;check.id='saved-benchmark-toggle';check.onchange=()=>{comparisonBenchmark=check.checked;keepScroll(()=>{syncToolbar();renderChart();});saveWorkspace();};label.append(check,document.createTextNode('Saved benchmark'));controls.append(label,fit,open,clear);
  host.append(head,controls);
  const note=element('p',model?.usable?'Index100 at '+model.baselineDate+' · '+getAsset().symbol+' raw candles / saved strategy / '+researchReadable(model.benchmark.label)+'. Calendar-date display alignment only; source clocks and wealth bases differ.':model?.reason||'No common comparison available.');note.id='comparison-scale';
  const facts=element('details'),summary=element('summary','Portfolio basis & comparison limits');facts.append(summary,note,element('p',r.basis.wealth_basis+' · '+r.basis.cost_basis+' · '+r.basis.currency+' · source clock '+r.basis.timezone+'; grid timestamps are UTC. No currency conversion, portfolio attribution or causal comparison is asserted.'));
  const compatibility=model.historySummary;for(const reason of compatibility.reasons)facts.append(element('p',reason));facts.append(element('p',r.financial_claim));host.append(facts);const visible=model?.usable?model.strategyIndex.slice(state.lo,state.hi+1).filter((v,j)=>v!==null&&model.benchmarkIndex[state.lo+j]!==null).length:0;if(model?.usable&&!visible){const warning=element('p','No saved samples in this visible range. Use Fit research dates to see the actual comparison.','comparison-gap');warning.setAttribute('role','status');host.append(warning);}
}
function renderMainResearch(list){
  list.setAttribute('role','list');list.setAttribute('aria-label','Choose saved strategy for main chart');$('.table-head').hidden=true;$('#sort-label').textContent='Actual saved results';
  const page=mainResearch.page;$$('.list-heading h2 span').forEach(el=>el.textContent=page?page.catalog.total+' saved results':'Saved research');$('.list-heading p').textContent='Select a strategy to compare its portfolio and benchmark with price context';
  const status=element('p',mainResearch.loading?'Updating saved strategies · current comparison retained.':mainResearch.error?'Saved strategy update failed · '+mainResearch.error:page?.catalog.total?'Choose a strategy · rows select the main chart':'No saved research records available.','panel-note');status.id='main-research-status';status.hidden=!mainResearch.loading&&!mainResearch.error&&!!page?.catalog.total;status.setAttribute('role','status');list.append(status);
  const refresh=element('button',mainResearch.error?'Retry saved strategies':'Refresh saved strategies');refresh.id='main-research-refresh';refresh.onclick=()=>loadMainResearch();$('#sort-label').replaceChildren(refresh);
  for(const saved of page?.details||[]){
    const r=saved.record,row=element('article',undefined,'main-strategy-row');row.dataset.resultId=saved.result_id;row.setAttribute('role','listitem');row.dataset.selected=String(saved.result_id===mainResearchSelection);
    const choose=element('button',undefined,'main-strategy-select');choose.dataset.compareResult=saved.result_id;choose.id='main-compare-'+saved.result_id;choose.setAttribute('aria-pressed',String(saved.result_id===mainResearchSelection));choose.append(element('b',r.question.label),element('small',researchPhase(r)+' · '+r.grid[0].slice(0,10)+' – '+r.grid.at(-1).slice(0,10)+' · '+r.grid.length+' samples'));choose.onclick=()=>selectMainResearch(saved.result_id);
    const verdict=element('span',researchReadable(saved.assessment.financial),'main-strategy-verdict');
    const open=element('button','Research','main-strategy-info');open.dataset.openResearch=saved.result_id;open.id='main-research-open-'+saved.result_id;open.setAttribute('aria-label','Read research: '+r.question.label);open.onclick=()=>{mainResearchReturnFocus=open.id;researchWorkspace?.openResult(saved.result_id,page.catalog.offset);};row.append(choose,verdict,open);list.append(row);
  }
  $('#runs-page').textContent=page?.catalog.items.length?'Results '+(page.catalog.offset+1)+'–'+(page.catalog.offset+page.catalog.items.length)+' of '+page.catalog.total:'No saved results';$('#runs-prev').disabled=mainResearch.loading||!page||page.catalog.offset===0;$('#runs-next').disabled=mainResearch.loading||page?.catalog.next_offset==null;
}

function renderRows() {
  const list=$('#strategy-list');list.replaceChildren();
  if(historyDisplayed()){renderMainResearch(list);return;}
  list.setAttribute('role','listbox');list.setAttribute('aria-label','Choose an actual retained run');$('.table-head').hidden=false;
  const sorted=[...runRows].sort((a,b)=>{
    let x,y;if(state.sortBy==='createdAt'){x=a.run.created_at;y=b.run.created_at;}else{const key=state.sortBy==='returnPct'?'total_return':'sharpe_252';x=numberOrNull(a.metrics?.[key]?.value);y=numberOrNull(b.metrics?.[key]?.value);if(x===null||y===null)return x===y?String(a.run.id).localeCompare(String(b.run.id)):x===null?1:-1;}
    return (x<y?-1:x>y?1:0)*(state.sortDir==='asc'?1:-1)||String(a.run.id).localeCompare(String(b.run.id));
  });
  sorted.forEach(item=>{
    const r=item.run,row=element('div',undefined,'strategy-row');row.tabIndex=0;row.role='option';row.dataset.strategy=r.id;row.setAttribute('aria-selected',String(r.id===detail?.run.id));
    const name=element('span',r.strategy_version,'row-name');name.append(element('small',r.id));
    const reportState=item.report_status||item.report_availability||r.state,status=element('span',r.id===detail?.run.id?'Active':r.state,'row-state');status.title='Job: '+r.state+' · Report: '+reportState;status.setAttribute('aria-label','Job state '+r.state+'; report state '+reportState);status.append(element('small',reportState));
    row.append(status,name,element('span',fmtDate(r.created_at),'row-created'),element('span',metricValue(item.metrics?.total_return,true),'row-number row-return '+cn(item.metrics?.total_return?.value)),element('span',sharpeText(item.metrics?.sharpe_252),'row-number row-sharpe'));
    const info=element('button',undefined,'row-info');info.dataset.info=r.id;info.title='Record details';info.setAttribute('aria-label','Information about '+r.strategy_version);const icon=element('i',undefined,'ti ti-info-circle');icon.setAttribute('aria-hidden','true');info.append(icon);info.onclick=e=>{e.stopPropagation();state.infoId=state.infoId===r.id?null:r.id;renderRecord();};row.append(info);
    row.onclick=e=>{if(!e.target.closest('button'))selectStrategy(r.id);};row.onkeydown=e=>{if(e.target===row&&['Enter',' '].includes(e.key)){e.preventDefault();selectStrategy(r.id);}};list.append(row);
  });
  if(!sorted.length)list.append(element('p',historyDisplayed()?'NO_STRATEGY_RESULT · no strategy report is registered for this history.':loading?'Loading records…':loadError?'Records unavailable.':dataset?'No runs on this page.':'No retained datasets.','panel-note'));
  $$('.list-heading h2 span').forEach(el=>el.textContent=historyDisplayed()?'No strategy result':runRows.length+' records on page');
  $('.list-heading p').textContent=historyDisplayed()?'Stored price history does not imply a portfolio, trade or Sharpe result.':'Actual retained runs · page sorting only';
  $$('[data-sort]').forEach(b=>{const match=state.sortBy===b.dataset.sort;b.setAttribute('aria-sort',match?(state.sortDir==='desc'?'descending':'ascending'):'none');b.textContent=({createdAt:'Created',returnPct:'Return',sharpe:'Sharpe'}[b.dataset.sort]||'')+' '+(match?(state.sortDir==='desc'?'↓':'↑'):'↕');});
  $('#sort-label').textContent=state.sortBy+' · '+state.sortDir+' · this page';
  $('#runs-page').textContent=runRows.length?'Runs '+(runOffset+1)+'–'+(runOffset+runRows.length):'No runs on page';$('#runs-prev').disabled=loading||!dataset||runOffset===0;$('#runs-next').disabled=loading||!dataset||runRows.length<10;positionInfo();
}
function closeInfo(returnFocus=false) {const id=state.infoId;state.infoId=null;$('#record-detail').hidden=true;if(returnFocus)[...$('#strategy-list').querySelectorAll('[data-info]')].find(b=>b.dataset.info===id)?.focus({preventScroll:true});}
function renderRecord() {
  const item=runRows.find(x=>x.run.id===state.infoId), pop=$('#record-detail');$$('[data-info]').forEach(b=>{b.setAttribute('aria-expanded',String(b.dataset.info===state.infoId));b.setAttribute('aria-controls','record-detail');});
  if(!item){pop.hidden=true;return;}
  pop.replaceChildren(element('b',item.run.strategy_version),element('small',item.run.id),element('p','Created '+fmtDate(item.run.created_at)));
  const dl=element('dl');addDefinition(dl,'Job / report',item.run.state+' / '+(item.report_status||item.report_availability||'UNAVAILABLE'));for(const [key,label] of [['total_return','Return'],['sharpe_252','Sharpe'],['max_drawdown','Max drawdown'],['fees','Fees']]) {const m=item.metrics?.[key];addDefinition(dl,label,(key==='sharpe_252'?sharpeText(m):metricValue(m,['total_return','max_drawdown'].includes(key)))+' · '+(m?.unit||'')+' · '+metricDescription(m));if(key==='sharpe_252')addDefinition(dl,'Sharpe precision','Two-decimal display only; API/report precision retained.');else if(m?.value!==null&&m?.value!==undefined)addDefinition(dl,label+' retained value',m.value);}
  if(detail?.run.id===item.run.id) {
    const report=detail.report,last=report?.nav.at(-1);addDefinition(dl,'Ending NAV',last?usd(last.nav):'Unavailable');
    addDefinition(dl,'Last NAV − initial cash',last?usd(decimalDelta(last.nav,report.initial_cash)):'Unavailable');
    addDefinition(dl,'Report',report?.status||detail.report_availability);addDefinition(dl,'Calculation revision',detail.calculation_revision);addDefinition(dl,'API revision (separate)',detail.api_revision);
    addDefinition(dl,'Report hash',detail.evidence?.report_hash||'Unavailable');addDefinition(dl,'Coverage',report?.coverage?.status||'Unavailable');
  }else panelNote(pop,'Select this run to inspect its report identities, values and fills.');
  const diagnostic=detail?.run.id===item.run.id?detail.report?.diagnostic:item.diagnostic;
  if(diagnostic)addDefinition(dl,'Diagnostic',diagnostic);
  const performance=item.metrics?.performance;if(performance)addDefinition(dl,'Performance',metricValue(performance)+' · '+metricDescription(performance));
  const verdict=detail?.run.id===item.run.id?detail.report?.financial_verdict:item.financial_verdict;
  pop.append(dl);panelNote(pop,'Synthetic retained report · infrastructure fixture only · financial verdict '+(verdict||'UNAVAILABLE')+'. Availability is not acceptance.');pop.hidden=false;positionInfo();
}
function positionInfo() {if(!state.infoId)return;const button=$$('[data-info]').find(b=>b.dataset.info===state.infoId),pop=$('#record-detail');if(!button){closeInfo();return;}const r=button.getBoundingClientRect(),list=$('#strategy-list').getBoundingClientRect();if(r.bottom<list.top||r.top>list.bottom){closeInfo();return;}const width=pop.offsetWidth,height=pop.offsetHeight,left=Math.max(8,Math.min(innerWidth-width-8,r.right-width));let top=r.top-height-9;if(top<62)top=r.bottom+9;top=Math.max(62,Math.min(innerHeight-38-height,top));Object.assign(pop.style,{left:left+'px',top:top+'px'});pop.style.setProperty('--anchor-x',Math.max(12,Math.min(width-12,r.left+r.width/2-left))+'px');}
function setLineLegend(id,enabled,text,key){const label=document.getElementById(id);if(!label)return;label.hidden=!enabled;if(enabled){const line=element('i',undefined,'line-key '+key);line.setAttribute('aria-hidden','true');label.replaceChildren(line,document.createTextNode(text));}}
function syncToolbar() {
  if(document.activeElement!==$('#asset-search'))$('#asset-search').value=dataset?getAsset().symbol+' · '+dataset.name:'';
  $('#asset-search').placeholder=historyDisplayed()?(loading?'Updating stored history…':'Choose registered history asset'):loading?'Updating retained dataset…':'Choose retained test dataset';
  $('#theme-indicator').textContent=(state.theme==='auto'?'Auto · ':'')+resolvedTheme();$('#granularity').value=state.granularity;
  $('#source').options[1].textContent=historyDisplayed()?'Selected portfolio NAV · USD':'Retained NAV';$('#source').value=state.cursorSource;for(const option of $('#source').options)option.disabled=!anySource(option.value);$('#source').disabled=!anySource('assetClose')&&!anySource('strategyEquity');$('#chart-stage').setAttribute('aria-disabled',String($('#source').disabled));$('#chart-stage').tabIndex=$('#source').disabled?-1:0;
  for(const option of $('#granularity').options){option.disabled=!GRANULARITIES.includes(option.value)||(historyDisplayed()&&option.value!=='1D');if(['1W','1M'].includes(option.value))option.textContent=option.value+(historyDisplayed()?' · daily history only':'');}$('#granularity').disabled=!view.bars.length;$$('[data-range]').forEach(b=>{b.disabled=!view.bars.length;b.setAttribute('aria-pressed',String(b.dataset.range===state.rangeId));});
  const first=view.bars[state.lo],last=view.bars[state.hi],visible=view.bars.slice(state.lo,state.hi+1),observed=visible.filter(b=>b.price_status==='OBSERVED').length;
  $('#range-caption').textContent=first&&last?(historyDisplayed()?observed+' observed provider dates'+(visible.length>observed?' / '+(visible.length-observed)+' reference-only gaps':''):(state.hi-state.lo+1)+' supplied buckets')+' · '+fmtDate(first.time)+'–'+fmtDate(last.endTime):'No available observations';
  const controls=displayedHistoryControls(),series=historyContext?.series,params=series?.metadata.parameters,reference=series?.metadata.reference_metadata;
  $('#workspace').dataset.rsi=String(historyDisplayed()&&controls.rsi&&!!series);
  $('.index-title').textContent=historyDisplayed()?'Raw vendor OHLC · '+(historyContext?.revision?.basis.price_unit||'source units')+(controls.benchmark&&reference?' (left) · '+(reference.family==='RAW_PRICE_RELATIVE'?'raw-price':'provider-adjusted close')+' index100 at '+(reference.anchor_session||'unavailable')+' (right)':' · provider session dates'):'Separate index bases · price open '+(view.baseClose??'unavailable')+' / retained initial cash '+(view.initialCash??'unavailable');
  $('#strategy-legend').parentElement.hidden=historyDisplayed()&&!getMainComparison()?.usable;$('#strategy-legend').textContent=(historyDisplayed()?researchReadable(getMainComparison()?.strategy?.label):getStrategy().name)+' NAV'+(anySource('strategyEquity')?'':' · unavailable');
  setLineLegend('sma-legend',historyDisplayed()?controls.sma&&!!series:state.sma&&legacySmaAvailable(),'SMA'+(params?.sma_period||20)+' · price','sma-key');
  setLineLegend('ema-legend',historyDisplayed()&&controls.ema&&!!series,'EMA'+params?.ema_period+' · price','ema-key');
  setLineLegend('bb-legend',historyDisplayed()&&controls.bollinger&&!!series,'BB'+params?.bb_period+' / k '+historyContext?.series?.controls.indicators.bollinger.deviation,'bb-key');
  setLineLegend('rsi-legend',historyDisplayed()&&controls.rsi&&!!series,'RSI'+params?.rsi_period+' · 0–100','rsi-key');
  setLineLegend('asset-ref-legend',historyDisplayed()&&controls.benchmark&&!!series,getAsset().symbol+' · index100','equity-key');
  const benchmark=historyContext?.assets.find(a=>a.instrument_id===reference?.benchmark_instrument_id);
  setLineLegend('benchmark-legend',historyDisplayed()&&controls.benchmark&&!!series,(benchmark?.display_symbol||'Benchmark')+' · index100','benchmark-key');
  if(getMainComparison()?.usable){$('.index-title').textContent='Index100 · baseline '+getMainComparison().baselineDate+' · independent price / portfolio wealth';}renderComparisonContext();
  setLineLegend('saved-benchmark-legend',!!getMainComparison()?.usable&&comparisonBenchmark,researchReadable(getMainComparison()?.benchmark?.label)+' · saved benchmark','benchmark-key');
  $('#volume-toggle').setAttribute('aria-pressed',String(state.volume));$('#data-diagnostics').open=state.diagnostics?.raw===true;
  $('.volume-title').textContent=historyDisplayed()?'Volume · '+(historyContext?.revision?.basis.volume_unit||'split-adjusted shares'):'Volume unavailable · not supplied';
  $('#footer-context').textContent=historyDisplayed()?(dataset?getAsset().symbol+' · '+dataset.dataset_revision.slice(0,20)+'… · '+(historyContext?.instrument?.chart_fitness||historyContext?.revision?.fitness.chart_fitness||'NOT_READY'):'Stored history workspace'):dataset?getAsset().symbol+' · '+dataset.dataset_id.slice(0,15)+'… · '+(detail?.run.state||'No run')+' / '+(detail?.report?.status||'No report'):'Retained test workspace';
  $('#datasets-page').textContent=historyDisplayed()?(catalog.length+' mapped assets · pinned revision'):(catalog.length?'Datasets '+(datasetOffset+1)+'–'+(datasetOffset+catalog.length):'No datasets on page');
  $('#datasets-prev').disabled=loading||historyDisplayed()||datasetOffset===0;$('#datasets-next').disabled=loading||historyDisplayed()||catalog.length<10;

}
function renderAll() {document.documentElement.dataset.theme=resolvedTheme();renderPending();syncModes();renderRail();renderRows();renderRecord();syncToolbar();renderChart();drawMeasurement();showRaw(state.inspect);renderSeriesState();}
function chartLayout(){
  const control=displayedHistoryControls();
  return chartGeometry({height:$('#chart').clientHeight,width:$('#chart').clientWidth,narrow:innerWidth<701,
    rsi:historyDisplayed()&&!!historyContext?.series&&control.rsi,
    reference:historyDisplayed()&&!!historyContext?.series&&control.benchmark,volume:state.volume});
}
function renderChart() {
  if(!chart||$('#workspace').hidden)return;hideCandleBoundary();const c=palette(),bars=view.bars,narrow=innerWidth<701,layout=chartLayout(),control=displayedHistoryControls(),real=historyDisplayed();
  const available=anySource('assetClose')||anySource('strategyEquity'),message=$('#view-message');message.hidden=available;
  message.textContent=real?(loading?'Loading registered history…':loadError?'History unavailable · '+loadError:dataset?'No observed OHLCV in the selected window. No values were padded.':'No registered chart-ready stored history. No synthetic data was substituted.'):loading?'Loading retained records…':loadError?'Backend unavailable · '+loadError:!dataset?'No retained datasets':['NO_DATA','INVALID'].includes(detail?.report?.status)?'Retained report: '+detail.report.status+(detail.report.diagnostic?' · '+detail.report.diagnostic:''):detail&&!detail.report?'Report unavailable · '+detail.run.state:'No plottable observations; source values are unavailable.';
  const series=[{id:'asset',name:real?'Raw vendor OHLC':'Retained asset OHLC',type:'candlestick',data:bars.map(b=>['open','close','low','high'].map(k=>real?(b.price_status==='OBSERVED'?priceDisplayValue(b[k]):null):indexValue(b[k],view.baseClose))),itemStyle:{color:c.up,color0:c.down,borderColor:c.up,borderColor0:c.down},emphasis:{disabled:true},barMaxWidth:15,z:2}];
  if(real){
    if(state.volume)series.push({id:'volume',name:'Split-adjusted volume',type:'bar',xAxisIndex:1,yAxisIndex:1,data:bars.map(b=>b.volume_status==='OBSERVED'?numberOrNull(b.volume):null),itemStyle:{color:c.muted,opacity:.55},barMaxWidth:15,z:1});
    const add=(key,name,color,width=1.7,type='solid',xAxisIndex=0,yAxisIndex=0)=>series.push({id:key,name,type:'line',xAxisIndex,yAxisIndex,data:(view.cPoints||[]).map(point=>['sma','ema','bb_middle','bb_upper','bb_lower'].includes(key)?priceDisplayValue(historySeriesValue(point,key)):numberOrNull(historySeriesValue(point,key))),connectNulls:false,showSymbol:false,smooth:false,lineStyle:overlayStroke(key,c),emphasis:{disabled:true},z:4});
    const comparison=getMainComparison();if(comparison?.usable){series.push({id:'saved-strategy',name:researchReadable(comparison.strategy.label)+' · portfolio',type:'line',data:comparison.strategyIndex,showSymbol:false,connectNulls:false,lineStyle:{color:c.equity,width:2.5},emphasis:{disabled:true},z:6});if(comparisonBenchmark)series.push({id:'saved-benchmark',name:researchReadable(comparison.benchmark.label)+' · saved benchmark',type:'line',data:comparison.benchmarkIndex,showSymbol:false,connectNulls:false,lineStyle:{color:c.benchmark,width:2,type:[8,4]},emphasis:{disabled:true},z:5});}
    const params=historyContext?.series?.metadata.parameters;
    if(control.sma&&params)add('sma','SMA'+params.sma_period,c.sma,1.8,'dotted');
    if(control.ema&&params)add('ema','EMA'+params.ema_period,c.action,1.8,'dashed');
    if(control.bollinger&&params){add('bb_middle','BB'+params.bb_period+' middle',c.muted,1.1,'dotted');add('bb_upper','BB upper',c.equity,1.1,'dotted');add('bb_lower','BB lower',c.equity,1.1,'dotted');}
    if(layout.reference){add('asset_reference',getAsset().symbol+' index100',c.equity,2.2,'solid',0,2);add('benchmark_reference','VTI index100',c.benchmark,2,'dashed',0,2);}
    if(layout.rsi)add('rsi','RSI'+params.rsi_period,c.action,1.8,'solid',2,3);
  }else{
    series.push({id:'strategy',name:'Retained NAV',type:'line',data:view.equity.map(e=>indexValue(e.value,view.initialCash)),connectNulls:false,showSymbol:true,showAllSymbol:true,symbol:'circle',symbolSize:5.5,lineStyle:{color:c.equity,width:2.5},itemStyle:{color:c.surface,borderColor:c.equity,borderWidth:1.6},emphasis:{disabled:true},smooth:.2,smoothMonotone:'x',z:5});
    if(state.sma&&legacySmaAvailable())series.push({id:'sma',name:'SMA20 display',type:'line',data:view.sma.map(x=>indexValue(x.value,view.baseClose)),connectNulls:false,showSymbol:false,smooth:false,lineStyle:{color:c.sma,type:'dotted',width:1.8},z:3});
    if(state.markers&&numberOrNull(view.baseClose)>0)series.push({id:'fills',name:'Actual signed fills',type:'scatter',symbol:'triangle',symbolSize:7,data:view.markers.filter(f=>f.plotIndex>=0).map(f=>({value:[bars[f.plotIndex].time,indexValue(f.price,view.baseClose)],fill:f})),itemStyle:{color:c.equity},z:6});
  }
  const x={type:'category',data:bars.map(b=>b.time),boundaryGap:true,axisTick:{show:false},axisLine:{lineStyle:{color:c.rule}},axisLabel:{color:c.muted,fontSize:narrow?9:10,formatter:shortDate}};
  const xAxis=[{...x,gridIndex:0,axisLabel:!layout.rsi&&!layout.volume?x.axisLabel:{show:false}},{...x,gridIndex:1,show:layout.volume,axisLabel:layout.rsi||!layout.volume?{show:false}:x.axisLabel}];if(layout.rsi)xAxis.push({...x,gridIndex:2});
  const yAxis=[{type:'value',gridIndex:0,scale:true,splitNumber:narrow?3:5,axisLabel:{color:c.muted,fontSize:narrow?8:10},splitLine:{lineStyle:{color:c.rule,opacity:.55}}},{type:'value',gridIndex:1,show:real&&layout.volume,splitNumber:2,axisLabel:{hideOverlap:true,color:c.muted,fontSize:8,formatter:n=>n>=1e6?(n/1e6).toFixed(1)+'m':n>=1e3?(n/1e3).toFixed(0)+'k':String(n)},splitLine:{show:false}},{type:'value',gridIndex:0,position:'right',scale:true,show:layout.reference,splitNumber:3,axisLabel:{color:c.benchmark,fontSize:8,formatter:n=>Math.abs(n)>=1000?(n/1000).toFixed(1)+'k':String(Number(n.toFixed(1)))},splitLine:{show:false}}];
  if(layout.rsi)yAxis.push({type:'value',gridIndex:2,min:0,max:100,interval:50,axisLabel:{color:c.muted,fontSize:8},splitLine:{lineStyle:{color:c.rule,opacity:.55}}});
  const axes=layout.rsi?[0,1,2]:[0,1];
  rendering=true;chart.setOption({animation:false,backgroundColor:c.surface,textStyle:{fontFamily:'Golos Text',color:c.ink},grid:layout.grid,xAxis,yAxis,dataZoom:[{id:'inside',type:'inside',xAxisIndex:axes,startValue:state.lo,endValue:state.hi,filterMode:real?'filter':'none',rangeMode:['value','value'],zoomOnMouseWheel:false,moveOnMouseWheel:false,moveOnMouseMove:true,disabled:!available},{id:'slider',type:'slider',xAxisIndex:axes,startValue:state.lo,endValue:state.hi,filterMode:real?'filter':'none',rangeMode:['value','value'],left:layout.left,right:layout.right,bottom:4,height:15,moveHandleSize:0,showDataShadow:false,showDetail:false,borderColor:c.rule,backgroundColor:c.surface,fillerColor:resolvedTheme()==='dark'?'#bb9ae720':'#7145a315',handleStyle:{color:c.surface,borderColor:c.action},brushSelect:false,disabled:!available}],tooltip:{show:true,trigger:'item',confine:true,backgroundColor:c.surface,borderColor:c.rule,textStyle:{color:c.ink,fontSize:10,fontFamily:'Golos Text'},formatter:p=>{if(state.measurement||!p.data?.fill)return '';const f=p.data.fill;return element('div',(Number(f.quantity)<0?'SELL ':'BUY ')+f.quantity+' shares · '+usd(f.price)+' · fee '+f.fee+' · '+fmtDate(f.fill_at)+' · receipt '+fmtDate(f.receipt_at));}},series},{notMerge:true});rendering=false;
  const volume=$('.volume-title');volume.hidden=!layout.volume;Object.assign(volume.style,{left:(layout.left+2)+'px',top:(layout.grid[1].top-18)+'px',bottom:'auto'});
  const caption=$('#rsi-caption');if(caption){caption.hidden=!layout.rsi;caption.textContent='RSI'+(historyContext?.series?.metadata.parameters.rsi_period||'')+' · 0–100';if(layout.rsi)Object.assign(caption.style,{left:(layout.left+2)+'px',top:(layout.grid[2].top-14)+'px'});}
  requestAnimationFrame(drawMeasurement);
}
function derivedReadout(i){
  if(!historyContext?.series)return '';
  const control=displayedHistoryControls(),point=view.cPoints?.[i],params=historyContext.series.metadata.parameters;
  const fields=[];for(const [flag,keys] of [['sma',['sma']],['ema',['ema']],['bollinger',['bb_lower','bb_middle','bb_upper']],['rsi',['rsi']],['benchmark',['asset_reference','benchmark_reference']]])if(control[flag])for(const key of keys){const item=point?.statuses?.[key],value=historySeriesValue(point,key);fields.push(key+(key==='sma'||key==='ema'||key==='rsi'?'('+params[key+'_period']+')':'')+' '+(value!==null?value:'Unavailable · '+(item?.reason||item?.status||'NO_POINT')));}
  return fields.length?'\nBackend · '+fields.join(' · '):'';
}
function setRawReadout(text){$('#raw-readout').textContent=text;$('#diagnostic-summary').textContent=text.split('\n')[0];}
function showRaw(i) {
  const b=view.bars[i], n=view.equity[i];if(b?.missingBar){setRawReadout('Reference date '+b.session_date+' · no source OHLCV row. No candle/volume was fabricated.'+derivedReadout(i));state.inspect=i;return;}if(b&&historyDisplayed()){setRawReadout('Session '+b.session_date+' · '+getAsset().symbol+' · '+b.price_status+' · calendar '+(historyContext?.bars?.coverage.calendar_status||'UNVERIFIED')+'\nO '+usd(b.open)+' · H '+usd(b.high)+' · L '+usd(b.low)+' · C '+usd(b.close)+'\nAdjusted close '+usd(b.adjusted_close)+' · volume '+(b.volume??'Unavailable')+' '+(historyContext?.revision?.basis.volume_unit||'split-adjusted shares')+'\nEvent clock '+(b.event_at?fmtDate(b.event_at):'not supplied')+' · price observations only; saved portfolios remain separate'+comparisonReadout(i)+derivedReadout(i));state.inspect=i;return;}if(!b){setRawReadout(loading?'Loading…':loadError?'Values unavailable · '+loadError:'No retained source observations.');return;}state.inspect=i;
  setRawReadout(fmtDate(b.time)+' – '+fmtDate(b.endTime)+' · '+getAsset().symbol+' · '+b.price_status+' ['+b.originalStatuses.join(', ')+'] · '+b.coverage.observed+'/'+b.coverage.supplied+' supplied sessions; calendar completeness not asserted\nO '+usd(b.open)+' · H '+usd(b.high)+' · L '+usd(b.low)+' · C '+usd(b.close)+' · volume unavailable\nNAV '+usd(n.value)+' at '+fmtDate(n.at)+' · cash '+usd(n.cash)+' · shares '+(n.shares??'Unavailable')+' · '+n.status);
}
function windowGeometry() {const box=plotBox(),r=$('#chart').getBoundingClientRect();return {lo:state.lo,hi:state.hi,count:view.bars.length?state.hi-state.lo+1:0,first:view.bars[state.lo]?.time,last:view.bars[state.hi]?.time,canvas:{left:r.left,top:r.top,width:r.width,height:r.height},grid:box};}
function initUI() {
  $('#data-diagnostics').ontoggle=()=>{state.diagnostics.raw=$('#data-diagnostics').open;saveWorkspace();};
  $('#volume-toggle').onclick=()=>{state.volume=!state.volume;keepScroll(()=>{syncToolbar();renderChart();drawMeasurement();});saveWorkspace();tell(state.volume?'Volume shown':'Volume hidden · space returned to candles');};
  const rsiCaption=element('span','','rsi-title');rsiCaption.id='rsi-caption';rsiCaption.hidden=true;$('#chart-stage').append(rsiCaption);$('#raw-readout').tabIndex=0;$('#raw-readout').setAttribute('aria-label','Raw source and calculated indicator values');
  $$('[data-mode]').forEach(b=>b.onclick=()=>{state.mode=b.dataset.mode;renderRail();syncModes();if(innerWidth<701)openTools();saveWorkspace();});
  $$('[data-sort]').forEach(b=>b.onclick=()=>{if(state.sortBy===b.dataset.sort)state.sortDir=state.sortDir==='desc'?'asc':'desc';else{state.sortBy=b.dataset.sort;state.sortDir='desc';}keepScroll(renderRows);saveWorkspace();});
  $('#granularity').onchange=e=>setGranularity(e.target.value);for(const option of $('#granularity').options)if(!GRANULARITIES.includes(option.value)){option.disabled=true;option.textContent=option.value+' · unavailable (daily source)';}
  $$('[data-range]').forEach(b=>b.onclick=()=>setPreset(b.dataset.range));
  $('#source').onchange=e=>{state.cursorSource=state.measurement?.source||e.target.value;e.target.value=state.cursorSource;showCursor(state.cursorSource,state.cursor);drawMeasurement();saveWorkspace();};
  $('#tools-button').onclick=openTools;$('#close-tools').onclick=()=>{$('#rail-inner').classList.remove('mobile-open');$('#tools-button').focus({preventScroll:true});};
  $('#retry-selection').onclick=()=>{if(failedSelection){const f=failedSelection;f.history?loadHistorySelection(f.request):loadSelection(f.datasetId,f.runId,f.options)}};
  $('#open-test-mode').onclick=()=>setDataMode('retained-test');
  $('#refresh').onclick=()=>{if(researchWorkspace?.isActive())return researchWorkspace.refresh();if(state.dataMode==='real'){loadMainResearch();return loadHistorySelection({datasetId:historyContext?.revision?.dataset_id,revision:historyContext?.revision?.dataset_revision,instrumentId:historyContext?.instrument?.instrument_id});}return loadSelection(dataset?.dataset_id||urlSelection()[0],detail?.run.id||urlSelection()[1],{catalogPage:datasetOffset,runsPage:runOffset});};
  $('#reset').onclick=()=>{mainResearchSelection=null;comparisonCache=null;comparisonBenchmark=true;mainResearchClient?.cancel();mainResearch={page:null,loading:false,error:null,offset:0};researchWorkspace?.reset();loadMainResearch(0);state={...restoredControls(null,0),dataMode:state.dataMode,assetId:null,strategyId:null,cursor:0,inspect:0,measurement:null,infoId:null};try{localStorage.removeItem(themeKey);sessionStorage.removeItem(sessionKey);}catch{}$('#rail-inner').classList.remove('mobile-open');state.dataMode==='real'?loadHistorySelection({}):loadSelection(null,null,{catalogPage:0});};
  $('#datasets-prev').onclick=()=>loadSelection(null,null,{push:true,catalogPage:Math.max(0,datasetOffset-10)});$('#datasets-next').onclick=()=>loadSelection(null,null,{push:true,catalogPage:datasetOffset+10});
  $('#runs-prev').onclick=()=>historyDisplayed()?loadMainResearch(Math.max(0,(mainResearch.page?.catalog.offset||0)-10)):loadSelection(dataset?.dataset_id,null,{push:true,runsPage:Math.max(0,runOffset-10)});$('#runs-next').onclick=()=>historyDisplayed()?loadMainResearch(mainResearch.page?.catalog.next_offset):loadSelection(dataset?.dataset_id,null,{push:true,runsPage:runOffset+10});
  const input=$('#asset-search');input.onfocus=()=>{assetQuery='';assetOptionIndex=0;renderAssets();input.select();};input.oninput=()=>{assetQuery=input.value.toLowerCase();assetOptionIndex=0;renderAssets();};input.onkeydown=e=>{const list=filteredAssets();if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();assetOptionIndex=Math.max(0,Math.min(list.length-1,assetOptionIndex+(e.key==='ArrowDown'?1:-1)));renderAssets();}else if(e.key==='Enter'&&!$('#asset-options').hidden&&list[assetOptionIndex]){e.preventDefault();selectAsset(list[assetOptionIndex].dataset_id);}else if(e.key==='Escape')closeAssets();};input.onblur=()=>setTimeout(closeAssets,100);
  chart=echarts.init($('#chart'),null,{renderer:'canvas'});chart.on('datazoom',()=>{
    if(rendering||!view.bars.length)return;const d=chart.getOption().dataZoom[0],n=view.bars.length,index=v=>typeof v==='string'?view.bars.findIndex(b=>b.time===v):Number(v);
    const lo=Math.max(0,Math.min(n-1,Number.isFinite(index(d.startValue))?index(d.startValue):Math.ceil(d.start/100*(n-1)))),hi=Math.max(lo,Math.min(n-1,Number.isFinite(index(d.endValue))?index(d.endValue):Math.floor(d.end/100*(n-1))));
    commitViewport(lo,hi);
  });
  let lastSize='';new ResizeObserver(()=>{const w=$('#chart').clientWidth,h=$('#chart').clientHeight;if(document.hidden||w<40||h<40)return;const size=w+'x'+h;if(size===lastSize)return;lastSize=size;chart.resize();renderChart();positionInfo();requestAnimationFrame(drawMeasurement);}).observe($('#chart'));
  initGestures();$('#strategy-list').addEventListener('scroll',positionInfo,{passive:true});
  document.addEventListener('pointerdown',e=>{if(state.infoId&&!e.target.closest('#record-detail,[data-info]'))closeInfo();},true);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&state.infoId){e.preventDefault();closeInfo(true);}});
  $('#rail-inner').addEventListener('keydown',e=>{if(innerWidth>=701||!$('#rail-inner').classList.contains('mobile-open'))return;if(e.key==='Escape'){$('#rail-inner').classList.remove('mobile-open');$('#tools-button').focus({preventScroll:true});}if(e.key==='Tab'){const items=[...$('#rail-inner').querySelectorAll('button,input,select')].filter(el=>!el.disabled&&el.getClientRects().length),i=items.indexOf(document.activeElement);if(e.shiftKey&&i===0){e.preventDefault();items.at(-1)?.focus();}else if(!e.shiftKey&&i===items.length-1){e.preventDefault();items[0]?.focus();}}});
  const fit=()=>requestAnimationFrame(()=>{if(document.hidden)return;chart.resize();renderChart();positionInfo();});window.addEventListener('pageshow',fit);window.addEventListener('focus',fit);window.addEventListener('resize',positionInfo);document.addEventListener('visibilitychange',()=>{if(document.hidden)saveWorkspace();else fit();});window.addEventListener('pagehide',saveWorkspace);window.addEventListener('popstate',()=>{const p=new URL(location.href).searchParams;state.dataMode=p.get('mode')==='retained-test'?'retained-test':'real';if(state.dataMode==='real')loadHistorySelection({datasetId:p.get('dataset'),revision:p.get('revision'),instrumentId:p.get('instrument')});else loadSelection(...urlSelection());});
  matchMedia('(prefers-color-scheme: light)').addEventListener('change',()=>{if(state.theme==='auto')renderAll();});
  document.fonts?.ready?.then(()=>{chart.resize();renderChart();drawMeasurement();});
}
function initResearchWorkspace(){
  const root=element('main');root.id='research-workspace';$('#workspace').after(root);
  const foot=element('span');foot.id='research-footer';$('footer').prepend(foot);
  researchWorkspace=createResearchWorkspace({root,historyWorkspace:$('#workspace'),fetcher:fetch,onCompare:saved=>{mainResearch.chosen=saved;researchWorkspace.open(false);selectMainResearch(saved.result_id,true);requestAnimationFrame(()=>$('#chart-stage').focus({preventScroll:true}));},
    theme:()=>state.theme,setTheme,
    onToggle:active=>{document.body.dataset.workspace=active?'research':'price';foot.hidden=!active;if(!active)requestAnimationFrame(()=>{chart.resize();renderChart();drawMeasurement();syncToolbar();if(mainResearchReturnFocus)document.getElementById(mainResearchReturnFocus)?.focus({preventScroll:true});});},
    onContext:text=>{foot.textContent=text;foot.title=text;}});
  $('.topbar').insertBefore(researchWorkspace.navigation,$('.top-actions'));
  mainResearchClient=createResearchClient(fetch);loadMainResearch(0);
}
function boot() {
  let restored=null;
  try {restored=JSON.parse(sessionStorage.getItem(sessionKey)||'null');Object.assign(state,restoredControls(restored?.controls,0));if(typeof restored?.research_result_id==='string'&&/^research-[a-f0-9]{64}$/.test(restored.research_result_id))mainResearchSelection=restored.research_result_id;if(typeof restored?.research_benchmark==='boolean')comparisonBenchmark=restored.research_benchmark;const theme=localStorage.getItem(themeKey);if(['auto','light','dark'].includes(theme))state.theme=theme;} catch {}
  state.dataMode=new URL(location.href).searchParams.get('mode')==='retained-test'?'retained-test':'real';
  initUI();if(typeof createResearchWorkspace==='function')initResearchWorkspace();const initial=urlSelection(),explicitURL=initial.some(Boolean);
  if(state.dataMode==='retained-test')loadSelection(explicitURL?initial[0]:restored?.dataset_id,explicitURL?initial[1]:restored?.run_id,{restore:explicitURL?null:restored});else{const p=new URL(location.href).searchParams;if(p.get('run')){renderAll();tell('Retained run link preserved. Open explicit retained test mode to use its synthetic report.');}else {const sameStored=restored?.history_revision===p.get('revision')&&restored?.instrument_id===p.get('instrument'),w=restored?.history_window;loadHistorySelection({datasetId:p.get('dataset'),revision:p.get('revision'),instrumentId:p.get('instrument'),window:sameStored&&historyDate(w?.start)&&historyDate(w?.end_exclusive)&&w.start<w.end_exclusive?w:null});}}
}
if(typeof module==='undefined')boot();
else module.exports={loadSelection,boot};
