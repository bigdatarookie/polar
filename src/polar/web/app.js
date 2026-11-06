// Adapted selected workspace: retained backend records, no fixture/demo fallback.
'use strict';
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const element = (tag, text, className) => {const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node;};
const usd = n => numberOrNull(n) === null ? 'Unavailable' : (Number(n) < 0 ? '−' : '') + '$' + String(n).replace(/^-/, '');
const percent = n => numberOrNull(n) === null ? 'Unavailable' : (n > 0 ? '+' : '') + Number(n).toFixed(2) + '%';
const signedUSD = n => (Number(n) > 0 ? '+' : '') + usd(n), cn = n => numberOrNull(n) === null ? '' : n < 0 ? 'negative' : n > 0 ? 'positive' : '';
const fmtDate = t => t && Number.isFinite(Date.parse(t)) ? new Date(t).toLocaleString('en-GB', {day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit', hour12:false, timeZone:'UTC'}) + ' UTC' : 'Unavailable';
const shortDate = t => fmtDate(t).slice(0, 11);
const themeKey = 'polar-retained-theme-v1', sessionKey = 'polar-retained-workspace-v1';
let state = {...restoredControls(null, 0), assetId:null, strategyId:null, cursor:0, inspect:0, measurement:null, infoId:null};
let dataset = null, detail = null, view = emptyView(), catalog = [], runRows = [], datasetOffset = 0, runOffset = 0;
let chart, loading = false, loadError = null, flow = 0, assetQuery = '', assetOptionIndex = 0, rendering = false, restoreFrame = 0;
const loader = createLatestLoader((...args) => fetch(...args));
function emptyView() {return {bars:[], equity:[], markers:[], sma:[], baseClose:null, initialCash:null};}
function getAsset() {return {bars:view.bars, baseClose:view.baseClose, symbol:dataset?.instrument.ticker_history[0]?.ticker || dataset?.instrument.instrument_id || 'No instrument', name:dataset?.name || 'No dataset'};}
function getStrategy() {return {name:detail?.run.strategy_version || 'No retained run', id:detail?.run.id || null};}
function getResult() {return view;}
function sourceAvailable(source, index) {return index >= 0 && index < view.bars.length && indexValue(source === 'assetClose' ? view.bars[index].close : view.equity[index].value, source === 'assetClose' ? view.baseClose : view.initialCash) !== null;}
function anySource(source) {return view.bars.some((_, i) => sourceAvailable(source, i));}
function palette() {const c = getComputedStyle(document.documentElement); return Object.fromEntries(['surface','soft','ink','muted','rule','action','equity','benchmark','sma','up','down','positive','negative'].map(k => [k, c.getPropertyValue('--'+k).trim()]));}
function resolvedTheme() {if (state.theme !== 'auto') return state.theme; return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';}
function tell(text) {$('#status').textContent = text;}
function keepScroll(fn) {const x=scrollX,y=scrollY; fn(); window.scrollTo(x,y); cancelAnimationFrame(restoreFrame); restoreFrame=requestAnimationFrame(()=>window.scrollTo(x,y));}
function syncModes() {$$('[data-mode]').forEach(b=>b.setAttribute('aria-pressed', String(b.dataset.mode === state.mode)));}
function saveWorkspace() {try {sessionStorage.setItem(sessionKey, JSON.stringify({dataset_id:dataset?.dataset_id,run_id:detail?.run.id,controls:state}));} catch {}}
function writeURL(push) {const url=new URL(location.href); url.searchParams.delete('dataset'); url.searchParams.delete('run'); if(dataset)url.searchParams.set('dataset',dataset.dataset_id); if(detail)url.searchParams.set('run',detail.run.id); history[push?'pushState':'replaceState'](null,'',url); saveWorkspace();}
function urlSelection() {const params=new URL(location.href).searchParams; return [params.get('dataset'),params.get('run')];}
async function loadSelection(datasetId, runId, {push=false, catalogPage=null, runsPage=0, restore=null}={}) {
  const token=++flow; loader.cancel(); loading=true; loadError=null; dataset=null; detail=null; runRows=[]; view=emptyView(); state.measurement=null; state.infoId=null; state.cursor=state.inspect=0; cancelGesture(); $('#asset-search').value=''; renderAll(); tell('Loading retained records…');
  const current=()=>token===flow;
  try {
    if(catalogPage!==null || !catalog.length) {
      const page=await loader.load('/v1/ui/datasets?limit=10&offset='+(catalogPage??datasetOffset)); if(!current()||page===null)return;
      catalog=page.items; datasetOffset=page.offset;
    }
    let selected = null, selectedRun = null;
    // A run-only URL resolves its real dataset, never the first catalog dataset.
    if(!datasetId && runId) {
      selectedRun=await loader.load('/v1/ui/runs/'+encodeURIComponent(runId)); if(!current()||selectedRun===null)return; selected=selectedRun.dataset; datasetId=selected.dataset_id;
    }
    datasetId=datasetId||catalog[0]?.dataset_id;
    if(datasetId) {
      selected=selected||catalog.find(d=>d.dataset_id===datasetId)||await loader.load('/v1/ui/datasets/'+encodeURIComponent(datasetId)); if(!current()||selected===null)return;
      if(selected.market.frequency!=='daily')throw new Error('UNSUPPORTED_FREQUENCY');
      const page=await loader.load('/v1/ui/datasets/'+encodeURIComponent(datasetId)+'/runs?limit=10&offset='+runsPage); if(!current()||page===null)return;
      runRows=page.items; runOffset=page.offset;
      runId=runId||runRows[0]?.run.id;
      if(runId && !selectedRun) {selectedRun=await loader.load('/v1/ui/runs/'+encodeURIComponent(runId)+'?dataset_id='+encodeURIComponent(datasetId)); if(!current()||selectedRun===null)return;}
      if(selectedRun && selectedRun.dataset.dataset_id!==datasetId)throw new Error('RUN_DATASET_MISMATCH');
      dataset=selectedRun?.dataset||selected; detail=selectedRun;
      view=buildView(dataset, detail?.report, state.granularity);
      state.assetId=dataset.dataset_id+':'+dataset.instrument.instrument_id; state.strategyId=detail?.run.id||null;
      state.lo=0; state.hi=Math.max(0,view.bars.length-1);
      if(restore && restore.dataset_id===dataset.dataset_id && (restore.run_id||null)===(detail?.run.id||null)) Object.assign(state,restoredControls(restore.controls,view.bars.length));
      if(!anySource(state.cursorSource))state.cursorSource=anySource('assetClose')?'assetClose':'strategyEquity';
      clampCursor();
    } else {runOffset=0; state.assetId=state.strategyId=null;}
    loading=false; closeAssets(); renderAll(); writeURL(push); tell(dataset ? (detail ? 'Retained '+detail.run.state+' job · report '+(detail.report?.status||detail.report_availability) : 'Dataset has no runs on this page.') : 'No retained datasets. Nothing was created.');
  } catch(error) {
    if(!current())return; loading=false; loadError=/^[A-Z0-9_]+$/.test(error.message)?error.message:'API_UNAVAILABLE'; catalog=[]; dataset=null; detail=null; view=emptyView(); runRows=[]; state.assetId=state.strategyId=null; closeAssets(); renderAll(); tell('Unable to load retained records · '+loadError+'. Refresh to retry.');
  }
}
function selectAsset(id) {closeAssets(); loadSelection(id,null,{push:true});}
function selectStrategy(id) {if(id!==detail?.run.id)loadSelection(dataset?.dataset_id,id,{push:true,runsPage:runOffset});}
function filteredAssets() {return catalog.filter(d=>(d.name+' '+d.dataset_id+' '+d.instrument.instrument_id+' '+(d.instrument.ticker_history[0]?.ticker||'')).toLowerCase().includes(assetQuery));}
function renderAssets() {
  const list=filteredAssets(), box=$('#asset-options'); box.replaceChildren(); box.hidden=false; $('#asset-search').setAttribute('aria-expanded','true');
  list.forEach((d,i)=>{const button=element('button');button.type='button';button.role='option';button.id='catalog-option-'+i;button.tabIndex=-1;button.setAttribute('aria-selected',String(i===assetOptionIndex));button.append(element('b',d.instrument.ticker_history[0]?.ticker||d.instrument.instrument_id),element('span',d.name+' · '+d.dataset_id));button.onmousedown=e=>e.preventDefault();button.onclick=()=>selectAsset(d.dataset_id);box.append(button);});
  if(!list.length)box.append(element('p','No matching dataset on this page.','panel-note'));
  $('#asset-search').setAttribute('aria-activedescendant',list[assetOptionIndex]?'catalog-option-'+assetOptionIndex:'');
}
function closeAssets() {$('#asset-options').hidden=true;$('#asset-search').setAttribute('aria-expanded','false');$('#asset-search').removeAttribute('aria-activedescendant');$('#asset-search').value=dataset?getAsset().symbol+' · '+dataset.name:'';}
function setGranularity(interval) {
  if(!dataset||!GRANULARITIES.includes(interval))return;
  state.granularity=interval;state.measurement=null;state.infoId=null;view=buildView(dataset,detail?.report,interval);state.lo=0;state.hi=Math.max(0,view.bars.length-1);state.cursor=state.inspect=0;state.rangeId='All';cancelGesture();renderAll();saveWorkspace();tell(interval+' · supplied daily rows only; incomplete buckets stay unavailable.');
}
function setPreset(id) {
  if(!view.bars.length)return;
  const last=new Date(view.bars.at(-1).endTime), lower=new Date(last); lower.setUTCHours(0,0,0,0);
  if(id==='1W')lower.setUTCDate(lower.getUTCDate()-7);else if(id==='All')lower.setTime(Date.parse(view.bars[0].time));else lower.setUTCMonth(lower.getUTCMonth()-({'1M':1,'3M':3,'6M':6,'12M':12}[id]||1));
  state.rangeId=id;state.lo=Math.max(0,view.bars.findIndex(b=>Date.parse(b.endTime)>=lower));state.hi=view.bars.length-1;clampCursor();invalidateRange();renderChart();syncToolbar();drawMeasurement();saveWorkspace();tell('Showing available observations; requested range is not additional history.');
}
function clampCursor() {state.cursor=Math.max(state.lo,Math.min(state.hi,state.cursor));state.inspect=Math.max(state.lo,Math.min(state.hi,state.inspect));}
function setTheme(theme) {state.theme=theme;try{localStorage.setItem(themeKey,theme);}catch{}renderAll();document.getElementById('theme-'+theme)?.focus({preventScroll:true});saveWorkspace();tell('Theme changed; compatible measurement retained.');}
function openTools() {$('#rail-inner').classList.add('mobile-open');if(innerWidth<701)$('#close-tools').focus({preventScroll:true});}
function panelNote(parent,text) {parent.append(element('p',text,'panel-note'));}
function metricValue(metric, percentage=false) {if(!metric||metric.value===null||metric.value===undefined)return 'Unavailable';return percentage?percent(Number(metric.value)*100):metric.value;}
function metricDescription(metric) {return metric ? [metric.status,metric.evidence_status,metric.reason].filter(Boolean).join(' · ') : 'UNAVAILABLE';}
function addDefinition(dl,label,value) {dl.append(element('dt',label),element('dd',value));}
function checkbox(parent,id,title,note,key,disabled) {const label=element('label',undefined,'overlay-choice'),input=element('input');input.type='checkbox';input.id=id;input.checked=state[key]===true;input.disabled=disabled;const span=element('span');span.append(element('b',title),element('small',note));label.append(input,span);parent.append(label);input.onchange=()=>{state[key]=input.checked;renderAll();saveWorkspace();};}
function renderRail() {
  const body=$('#rail-body');body.replaceChildren(element('h3',state.mode));
  if(state.mode==='Settings') {
    panelNote(body,'Appearance changes preserve your retained-record context.');const group=element('div',undefined,'theme-options');
    ['auto','light','dark'].forEach(mode=>{const b=element('button',mode[0].toUpperCase()+mode.slice(1));b.id='theme-'+mode;b.setAttribute('aria-pressed',String(state.theme===mode));b.onclick=()=>setTheme(mode);group.append(b);});body.append(group);
    checkbox(body,'marker-toggle','Execution markers','Actual signed fills; no inferred round trips.','markers',!view.markers.length);
    panelNote(body,'Price index: actual first usable open. NAV index: retained initial cash '+(view.initialCash??'unavailable')+'. Separate bases; no range rebasing.');
    panelNote(body,'Volume and passive benchmark unavailable: they are not retained.');return;
  }
  if(state.mode==='Overlays') {
    const supported=view.sma.some(x=>x.value!==null);
    checkbox(body,'sma-toggle','SMA20 · display transform','20 valid gap-free selected-interval closes. '+(supported?'':'Insufficient observations.'),'sma',!supported);
    checkbox(body,'benchmark-toggle','Passive benchmark','Unavailable: no retained benchmark.','benchmark',true);
    panelNote(body,'No strategy, exposure or financial metrics are computed by these controls.');return;
  }
  panelNote(body,dataset?getAsset().symbol+' · '+getStrategy().name:'Choose an available retained dataset and run.');
  if(!detail?.report) {panelNote(body,detail?'Report unavailable · '+detail.run.state:loading?'Loading retained records…':loadError?'Unavailable · '+loadError:'No retained run selected.');return;}
  const report=detail.report;
  report.fills.forEach((f,index)=>{const article=element('article',undefined,'order-entry');article.append(element('b',(Number(f.quantity)<0?'SELL':'BUY')+' · '+f.quantity+' shares'),element('p',usd(f.price)+' · fee '+f.fee+' '+(f.currency||report.units.fee)),element('small','Fill '+fmtDate(f.fill_at)),element('p','Receipt '+fmtDate(f.receipt_at)),element('p','Decision session '+f.decision_session_id),element('small','Fill row '+(index+1)+' · presentation reference'));body.append(article);});
  if(!report.fills.length)panelNote(body,'No actual fills in this retained report.');
  report.orders.forEach(o=>{const row=element('article',undefined,'order-entry');row.append(element('b','Instruction · '+o.status),element('small','Decision '+o.decision_session_id),element('p',o.reason||'No additional reason'));const tape=report.order_tape.find(t=>t.decision_session_id===o.decision_session_id);if(tape)row.append(element('p',tape.quantity+' shares · '+fmtDate(tape.decision_at)));body.append(row);});
  panelNote(body,'Signed fills and instructions are separate; no closed-trade count or per-trade P&L is inferred.');
}
function renderRows() {
  const list=$('#strategy-list');list.replaceChildren();
  const sorted=[...runRows].sort((a,b)=>{
    let x,y;if(state.sortBy==='createdAt'){x=a.run.created_at;y=b.run.created_at;}else{const key=state.sortBy==='returnPct'?'total_return':'sharpe_252';x=numberOrNull(a.metrics?.[key]?.value);y=numberOrNull(b.metrics?.[key]?.value);if(x===null||y===null)return x===y?String(a.run.id).localeCompare(String(b.run.id)):x===null?1:-1;}
    return (x<y?-1:x>y?1:0)*(state.sortDir==='asc'?1:-1)||String(a.run.id).localeCompare(String(b.run.id));
  });
  sorted.forEach(item=>{
    const r=item.run,row=element('div',undefined,'strategy-row');row.tabIndex=0;row.role='option';row.dataset.strategy=r.id;row.setAttribute('aria-selected',String(r.id===detail?.run.id));
    const name=element('span',r.strategy_version,'row-name');name.append(element('small',r.id));
    const status=element('span',r.id===detail?.run.id?'Active':r.state,'row-state');status.append(element('small',item.report_status||item.report_availability||r.state));
    row.append(status,name,element('span',fmtDate(r.created_at),'row-created'),element('span',metricValue(item.metrics?.total_return,true),'row-number row-return '+cn(item.metrics?.total_return?.value)),element('span',metricValue(item.metrics?.sharpe_252),'row-number row-sharpe'));
    const info=element('button',undefined,'row-info');info.dataset.info=r.id;info.title='Record details';info.setAttribute('aria-label','Information about '+r.strategy_version);const icon=element('i',undefined,'ti ti-info-circle');icon.setAttribute('aria-hidden','true');info.append(icon);info.onclick=e=>{e.stopPropagation();state.infoId=state.infoId===r.id?null:r.id;renderRecord();};row.append(info);
    row.onclick=e=>{if(!e.target.closest('button'))selectStrategy(r.id);};row.onkeydown=e=>{if(e.target===row&&['Enter',' '].includes(e.key)){e.preventDefault();selectStrategy(r.id);}};list.append(row);
  });
  if(!sorted.length)list.append(element('p',loading?'Loading records…':loadError?'Records unavailable.':dataset?'No runs on this page.':'No retained datasets.','panel-note'));
  $$('.list-heading h2 span').forEach(el=>el.textContent=runRows.length+' records on page');
  $('.list-heading p').textContent='Actual retained runs · page sorting only';
  $$('[data-sort]').forEach(b=>{const match=state.sortBy===b.dataset.sort;b.setAttribute('aria-sort',match?(state.sortDir==='desc'?'descending':'ascending'):'none');b.textContent=({createdAt:'Created',returnPct:'Return',sharpe:'Sharpe'}[b.dataset.sort]||'')+' '+(match?(state.sortDir==='desc'?'↓':'↑'):'↕');});
  $('#sort-label').textContent=state.sortBy+' · '+state.sortDir+' · this page';
  $('#runs-page').textContent=runRows.length?'Runs '+(runOffset+1)+'–'+(runOffset+runRows.length):'No runs on page';$('#runs-prev').disabled=loading||!dataset||runOffset===0;$('#runs-next').disabled=loading||!dataset||runRows.length<10;positionInfo();
}
function closeInfo(returnFocus=false) {const id=state.infoId;state.infoId=null;$('#record-detail').hidden=true;if(returnFocus)[...$('#strategy-list').querySelectorAll('[data-info]')].find(b=>b.dataset.info===id)?.focus({preventScroll:true});}
function renderRecord() {
  const item=runRows.find(x=>x.run.id===state.infoId), pop=$('#record-detail');$$('[data-info]').forEach(b=>{b.setAttribute('aria-expanded',String(b.dataset.info===state.infoId));b.setAttribute('aria-controls','record-detail');});
  if(!item){pop.hidden=true;return;}
  pop.replaceChildren(element('b',item.run.strategy_version),element('small',item.run.id),element('p','Created '+fmtDate(item.run.created_at)));
  const dl=element('dl');addDefinition(dl,'Job / report',item.run.state+' / '+(item.report_status||item.report_availability||'UNAVAILABLE'));for(const [key,label] of [['total_return','Return'],['sharpe_252','Sharpe'],['max_drawdown','Max drawdown'],['fees','Fees']]) {const m=item.metrics?.[key];addDefinition(dl,label,metricValue(m,['total_return','max_drawdown'].includes(key))+' · '+(m?.unit||'')+' · '+metricDescription(m));if(m?.value!==null&&m?.value!==undefined)addDefinition(dl,label+' retained value',m.value);}
  if(detail?.run.id===item.run.id) {
    const report=detail.report,last=report?.nav.at(-1);addDefinition(dl,'Ending NAV',last?usd(last.nav):'Unavailable');
    addDefinition(dl,'Last NAV − initial cash',last?usd(decimalDelta(last.nav,report.initial_cash)):'Unavailable');
    addDefinition(dl,'Report',report?.status||detail.report_availability);addDefinition(dl,'Calculation revision',detail.calculation_revision);addDefinition(dl,'API revision (separate)',detail.api_revision);
    addDefinition(dl,'Report hash',detail.evidence?.report_hash||'Unavailable');addDefinition(dl,'Coverage',report?.coverage?.status||'Unavailable');
  }else panelNote(pop,'Select this run to inspect its report identities, values and fills.');
  pop.append(dl);panelNote(pop,'Synthetic retained report · infrastructure fixture only · financial evaluation NOT_RUN. Availability is not acceptance.');pop.hidden=false;positionInfo();
}
function positionInfo() {if(!state.infoId)return;const button=$$('[data-info]').find(b=>b.dataset.info===state.infoId),pop=$('#record-detail');if(!button){closeInfo();return;}const r=button.getBoundingClientRect(),list=$('#strategy-list').getBoundingClientRect();if(r.bottom<list.top||r.top>list.bottom){closeInfo();return;}const width=pop.offsetWidth,height=pop.offsetHeight,left=Math.max(8,Math.min(innerWidth-width-8,r.right-width));let top=r.top-height-9;if(top<62)top=r.bottom+9;top=Math.max(62,Math.min(innerHeight-38-height,top));Object.assign(pop.style,{left:left+'px',top:top+'px'});pop.style.setProperty('--anchor-x',Math.max(12,Math.min(width-12,r.left+r.width/2-left))+'px');}
function syncToolbar() {
  if(document.activeElement!==$('#asset-search'))$('#asset-search').value=dataset?getAsset().symbol+' · '+dataset.name:'';
  $('#asset-search').placeholder=loading?'Loading retained datasets…':'Choose retained dataset';
  $('#theme-indicator').textContent=(state.theme==='auto'?'Auto · ':'')+resolvedTheme();$('#granularity').value=state.granularity;
  $('#source').value=state.cursorSource;for(const option of $('#source').options)option.disabled=!anySource(option.value);$('#source').disabled=!anySource('assetClose')&&!anySource('strategyEquity');$('#chart-stage').setAttribute('aria-disabled',String($('#source').disabled));$('#chart-stage').tabIndex=$('#source').disabled?-1:0;
  $('#granularity').disabled=!view.bars.length;$$('[data-range]').forEach(b=>{b.disabled=!view.bars.length;b.setAttribute('aria-pressed',String(b.dataset.range===state.rangeId));});
  const first=view.bars[state.lo],last=view.bars[state.hi];$('#range-caption').textContent=first&&last?(state.hi-state.lo+1)+' supplied buckets · '+fmtDate(first.time)+'–'+fmtDate(last.endTime):'No available observations';
  $('.index-title').textContent='Separate index bases · price open '+(view.baseClose??'unavailable')+' / retained initial cash '+(view.initialCash??'unavailable');
  $('#strategy-legend').textContent=getStrategy().name+' NAV'+(anySource('strategyEquity')?'':' · unavailable');$('#sma-legend').hidden=!state.sma||!view.sma.some(x=>x.value!==null);$('#benchmark-legend').hidden=true;
  $('.volume-title').textContent='Volume unavailable · not supplied';
  $('#footer-context').textContent=dataset?getAsset().symbol+' · '+dataset.dataset_id.slice(0,15)+'… · '+(detail?.run.state||'No run')+' / '+(detail?.report?.status||'No report'):'Retained workspace';
  $('#datasets-page').textContent=catalog.length?'Datasets '+(datasetOffset+1)+'–'+(datasetOffset+catalog.length):'No datasets on page';$('#datasets-prev').disabled=loading||datasetOffset===0;$('#datasets-next').disabled=loading||catalog.length<10;
}
function renderAll() {document.documentElement.dataset.theme=resolvedTheme();syncModes();renderRail();renderRows();renderRecord();syncToolbar();renderChart();drawMeasurement();showRaw(state.inspect);}
function renderChart() {
  if(!chart)return;hideCandleBoundary();const c=palette(),bars=view.bars,h=$('#chart').clientHeight,narrow=innerWidth<701;
  const available=anySource('assetClose')||anySource('strategyEquity');
  const message=$('#view-message');message.hidden=!loading&&!loadError&&available;
  message.textContent=loading?'Loading retained records…':loadError?'Backend unavailable · '+loadError:!dataset?'No retained datasets':detail?.report?.status==='NO_DATA'?'Retained report: NO_DATA':detail&&!detail.report?'Report unavailable · '+detail.run.state:'No plottable observations; source values are unavailable.';
  const series=[{id:'asset',name:'Retained asset OHLC',type:'candlestick',data:bars.map(b=>['open','close','low','high'].map(k=>indexValue(b[k],view.baseClose))),itemStyle:{color:c.up,color0:c.down,borderColor:c.up,borderColor0:c.down},emphasis:{disabled:true},barMaxWidth:15,z:2},
    {id:'strategy',name:'Retained NAV',type:'line',data:view.equity.map(e=>indexValue(e.value,view.initialCash)),connectNulls:false,showSymbol:true,showAllSymbol:true,symbol:'circle',symbolSize:5.5,lineStyle:{color:c.equity,width:2.5},itemStyle:{color:c.surface,borderColor:c.equity,borderWidth:1.6},emphasis:{disabled:true},smooth:.2,smoothMonotone:'x',z:5}];
  if(state.sma)series.push({id:'sma',name:'SMA20 display',type:'line',data:view.sma.map(x=>indexValue(x.value,view.baseClose)),connectNulls:false,showSymbol:false,smooth:false,lineStyle:{color:c.sma,type:'dotted',width:1.8},z:3});
  if(state.markers && numberOrNull(view.baseClose)>0)series.push({id:'fills',name:'Actual signed fills',type:'scatter',symbol:'triangle',symbolSize:7,data:view.markers.filter(f=>f.plotIndex>=0).map(f=>({value:[bars[f.plotIndex].time,indexValue(f.price,view.baseClose)],fill:f})),itemStyle:{color:c.equity},z:6});
  const x={type:'category',data:bars.map(b=>b.time),boundaryGap:true,axisTick:{show:false},axisLine:{lineStyle:{color:c.rule}},axisLabel:{color:c.muted,fontSize:narrow?9:10,formatter:shortDate}};
  rendering=true;chart.setOption({animation:false,backgroundColor:c.surface,textStyle:{fontFamily:'Golos Text',color:c.ink},grid:[{left:narrow?43:57,right:narrow?15:22,top:24,height:Math.max(1,h-147)},{left:narrow?43:57,right:narrow?15:22,top:h-87,height:43}],xAxis:[{...x,gridIndex:0,axisLabel:{show:false}},{...x,gridIndex:1}],yAxis:[{type:'value',scale:true,splitNumber:5,axisLabel:{color:c.muted,fontSize:narrow?9:10},splitLine:{lineStyle:{color:c.rule,opacity:.55}}},{type:'value',gridIndex:1,show:false}],dataZoom:[{id:'inside',type:'inside',xAxisIndex:[0,1],startValue:state.lo,endValue:state.hi,filterMode:'none',rangeMode:['value','value'],zoomOnMouseWheel:false,moveOnMouseWheel:false,moveOnMouseMove:true,disabled:!available},{id:'slider',type:'slider',xAxisIndex:[0,1],startValue:state.lo,endValue:state.hi,filterMode:'none',rangeMode:['value','value'],left:narrow?43:57,right:narrow?15:22,bottom:4,height:15,moveHandleSize:0,showDataShadow:false,showDetail:false,borderColor:c.rule,backgroundColor:c.surface,fillerColor:resolvedTheme()==='dark'?'#bb9ae720':'#7145a315',handleStyle:{color:c.surface,borderColor:c.action},brushSelect:false,disabled:!available}],tooltip:{show:true,trigger:'item',confine:true,backgroundColor:c.surface,borderColor:c.rule,textStyle:{color:c.ink,fontSize:10,fontFamily:'Golos Text'},formatter:p=>{if(state.measurement||!p.data?.fill)return '';const f=p.data.fill;return element('div',(Number(f.quantity)<0?'SELL ':'BUY ')+f.quantity+' shares · '+usd(f.price)+' · fee '+f.fee+' · '+fmtDate(f.fill_at)+' · receipt '+fmtDate(f.receipt_at));}},series},{notMerge:true});rendering=false;requestAnimationFrame(drawMeasurement);
}
function showRaw(i) {
  const b=view.bars[i], n=view.equity[i];if(!b){$('#raw-readout').textContent=loading?'Loading…':loadError?'Values unavailable · '+loadError:'No retained source observations.';return;}state.inspect=i;
  $('#raw-readout').textContent=fmtDate(b.time)+' – '+fmtDate(b.endTime)+' · '+getAsset().symbol+' · '+b.price_status+' ['+b.originalStatuses.join(', ')+'] · '+b.coverage.observed+'/'+b.coverage.supplied+' supplied sessions; calendar completeness not asserted\nO '+usd(b.open)+' · H '+usd(b.high)+' · L '+usd(b.low)+' · C '+usd(b.close)+' · volume unavailable\nNAV '+usd(n.value)+' at '+fmtDate(n.at)+' · cash '+usd(n.cash)+' · shares '+(n.shares??'Unavailable')+' · '+n.status;
}
function windowGeometry() {const box=plotBox(),r=$('#chart').getBoundingClientRect();return {lo:state.lo,hi:state.hi,count:view.bars.length?state.hi-state.lo+1:0,first:view.bars[state.lo]?.time,last:view.bars[state.hi]?.time,canvas:{left:r.left,top:r.top,width:r.width,height:r.height},grid:box};}
function initUI() {
  $$('[data-mode]').forEach(b=>b.onclick=()=>{state.mode=b.dataset.mode;renderRail();syncModes();if(innerWidth<701)openTools();saveWorkspace();});
  $$('[data-sort]').forEach(b=>b.onclick=()=>{if(state.sortBy===b.dataset.sort)state.sortDir=state.sortDir==='desc'?'asc':'desc';else{state.sortBy=b.dataset.sort;state.sortDir='desc';}renderRows();saveWorkspace();});
  $('#granularity').onchange=e=>setGranularity(e.target.value);for(const option of $('#granularity').options)if(!GRANULARITIES.includes(option.value)){option.disabled=true;option.textContent=option.value+' · unavailable (daily source)';}
  $$('[data-range]').forEach(b=>b.onclick=()=>setPreset(b.dataset.range));
  $('#source').onchange=e=>{state.cursorSource=state.measurement?.source||e.target.value;e.target.value=state.cursorSource;showCursor(state.cursorSource,state.cursor);drawMeasurement();saveWorkspace();};
  $('#tools-button').onclick=openTools;$('#close-tools').onclick=()=>{$('#rail-inner').classList.remove('mobile-open');$('#tools-button').focus({preventScroll:true});};
  $('#refresh').onclick=()=>loadSelection(dataset?.dataset_id||urlSelection()[0],detail?.run.id||urlSelection()[1],{catalogPage:datasetOffset,runsPage:runOffset});
  $('#reset').onclick=()=>{state={...restoredControls(null,0),assetId:null,strategyId:null,cursor:0,inspect:0,measurement:null,infoId:null};try{localStorage.removeItem(themeKey);sessionStorage.removeItem(sessionKey);}catch{}$('#rail-inner').classList.remove('mobile-open');loadSelection(null,null,{catalogPage:0});};
  $('#datasets-prev').onclick=()=>loadSelection(null,null,{push:true,catalogPage:Math.max(0,datasetOffset-10)});$('#datasets-next').onclick=()=>loadSelection(null,null,{push:true,catalogPage:datasetOffset+10});
  $('#runs-prev').onclick=()=>loadSelection(dataset?.dataset_id,null,{push:true,runsPage:Math.max(0,runOffset-10)});$('#runs-next').onclick=()=>loadSelection(dataset?.dataset_id,null,{push:true,runsPage:runOffset+10});
  const input=$('#asset-search');input.onfocus=()=>{assetQuery='';assetOptionIndex=0;renderAssets();input.select();};input.oninput=()=>{assetQuery=input.value.toLowerCase();assetOptionIndex=0;renderAssets();};input.onkeydown=e=>{const list=filteredAssets();if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();assetOptionIndex=Math.max(0,Math.min(list.length-1,assetOptionIndex+(e.key==='ArrowDown'?1:-1)));renderAssets();}else if(e.key==='Enter'&&!$('#asset-options').hidden&&list[assetOptionIndex]){e.preventDefault();selectAsset(list[assetOptionIndex].dataset_id);}else if(e.key==='Escape')closeAssets();};input.onblur=()=>setTimeout(closeAssets,100);
  chart=echarts.init($('#chart'),null,{renderer:'canvas'});chart.on('datazoom',()=>{if(rendering||!view.bars.length)return;const d=chart.getOption().dataZoom[0],n=view.bars.length;const index=v=>typeof v==='string'?view.bars.findIndex(b=>b.time===v):Number(v);state.lo=Math.max(0,Math.min(n-1,Number.isFinite(index(d.startValue))?index(d.startValue):Math.ceil(d.start/100*(n-1))));state.hi=Math.max(state.lo,Math.min(n-1,Number.isFinite(index(d.endValue))?index(d.endValue):Math.floor(d.end/100*(n-1))));state.rangeId='Custom';clampCursor();invalidateRange();syncToolbar();drawMeasurement();saveWorkspace();});
  let lastSize='';new ResizeObserver(()=>{const size=$('#chart').clientWidth+'x'+$('#chart').clientHeight;if(size===lastSize)return;lastSize=size;chart.resize();renderChart();positionInfo();requestAnimationFrame(drawMeasurement);}).observe($('#chart'));
  initGestures();$('#strategy-list').addEventListener('scroll',positionInfo,{passive:true});
  document.addEventListener('pointerdown',e=>{if(state.infoId&&!e.target.closest('#record-detail,[data-info]'))closeInfo();},true);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&state.infoId){e.preventDefault();closeInfo(true);}});
  $('#rail-inner').addEventListener('keydown',e=>{if(innerWidth>=701||!$('#rail-inner').classList.contains('mobile-open'))return;if(e.key==='Escape'){$('#rail-inner').classList.remove('mobile-open');$('#tools-button').focus({preventScroll:true});}if(e.key==='Tab'){const items=[...$('#rail-inner').querySelectorAll('button,input,select')].filter(el=>!el.disabled&&el.getClientRects().length),i=items.indexOf(document.activeElement);if(e.shiftKey&&i===0){e.preventDefault();items.at(-1)?.focus();}else if(!e.shiftKey&&i===items.length-1){e.preventDefault();items[0]?.focus();}}});
  const fit=()=>requestAnimationFrame(()=>{if(document.hidden)return;chart.resize();renderChart();positionInfo();});window.addEventListener('pageshow',fit);window.addEventListener('focus',fit);window.addEventListener('resize',positionInfo);document.addEventListener('visibilitychange',()=>{if(document.hidden)saveWorkspace();else fit();});window.addEventListener('pagehide',saveWorkspace);window.addEventListener('popstate',()=>loadSelection(...urlSelection()));
  matchMedia('(prefers-color-scheme: light)').addEventListener('change',()=>{if(state.theme==='auto')renderAll();});
  document.fonts?.ready?.then(()=>{chart.resize();renderChart();drawMeasurement();});
}
function boot() {
  let restored=null;
  try {restored=JSON.parse(sessionStorage.getItem(sessionKey)||'null');Object.assign(state,restoredControls(restored?.controls,0));const theme=localStorage.getItem(themeKey);if(['auto','light','dark'].includes(theme))state.theme=theme;} catch {}
  initUI();const initial=urlSelection(),explicitURL=initial.some(Boolean);
  loadSelection(explicitURL?initial[0]:restored?.dataset_id,explicitURL?initial[1]:restored?.run_id,{restore:explicitURL?null:restored});
}
if(typeof module==='undefined')boot();
else module.exports={loadSelection,boot};
