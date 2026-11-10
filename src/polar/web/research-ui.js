// Existing-workspace saved-result view. No economic calculations or synthetic fallback.
'use strict';
function researchTableScrollTarget(left,max,key,width){
  const step=Math.max(120,Math.floor(width*.75));
  const target=key==='ArrowRight'?left+step:key==='ArrowLeft'?left-step:key==='Home'?0:key==='End'?max:null;
  return target===null?null:Math.max(0,Math.min(max,target));
}
function createResearchWorkspace({root,historyWorkspace,fetcher,theme=()=> 'auto',setTheme,onToggle,onContext=()=>{}}){
  const client=createResearchClient(fetcher);
  let active=false,committed=null,loading=false,error=null,request={offset:0,selection:null},chart=null,inspect=0,renderFrame=0,chartResult=null;
  const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
  const button=(label,action,id)=>{const node=el('button',label);node.type='button';if(id)node.id=id;node.onclick=action;return node;};
  const details=(label,body,id)=>{const d=el('details',undefined,'research-disclosure');if(id)d.id=id;d.append(el('summary',label),body);return d;};
  const definition=(parent,key,value)=>parent.append(el('dt',key),el('dd',value??'Unavailable'));
  const style=()=>{const css=getComputedStyle(document.documentElement),get=k=>css.getPropertyValue('--'+k).trim();return {surface:get('surface'),ink:get('ink'),muted:get('muted'),rule:get('rule'),action:get('action'),benchmark:get('benchmark'),sma:get('sma'),up:get('up')};};
  const legStyle=(leg,index)=>{const c=style();return {color:leg.role==='STRATEGY'?c.action:leg.role==='BENCHMARK'?c.benchmark:[c.sma,c.up,c.muted][index%3],width:leg.role==='STRATEGY'?2.5:1.8,type:leg.role==='STRATEGY'?'solid':leg.role==='BENCHMARK'?[8,4]:[2+index,3]};};
  const valueLabel=(value,metricId)=>value?.status==='OK'?(String(metricId||'').toLowerCase().includes('sharpe')?researchDecimalDisplay(value.value):value.value):[value?.status||'UNAVAILABLE',value?.reason].filter(Boolean).join(' · ');
  const assessmentText=a=>'Technical '+a.technical+' · Product '+a.product+' · Financial '+a.financial+' · Evidence '+a.financial_evidence.status+(a.financial_evidence.reason?' / '+a.financial_evidence.reason:'');
  const nav=el('nav',undefined,'research-navigation');nav.setAttribute('aria-label','Workspace view');
  const priceButton=button('Price history',()=>open(false),'price-workspace'),savedButton=button('Saved research',()=>open(true),'saved-workspace');nav.append(priceButton,savedButton);
  root.className='research-workspace';root.hidden=true;root.setAttribute('aria-label','Saved research results');
  const aside=el('aside',undefined,'research-catalog'),head=el('div',undefined,'research-catalog-head');
  head.append(el('h2','Saved research'),el('p','Persisted questions · content-ID order','research-muted'));
  const catalogStatus=el('p','','research-load-status');catalogStatus.id='research-status';catalogStatus.setAttribute('role','status');catalogStatus.setAttribute('aria-live','polite');
  const reload=button('Refresh results',()=>load(request.offset,request.selection),'research-refresh');
  const pickerLabel=el('label','Saved question','research-picker-label'),picker=el('select');picker.id='research-picker';pickerLabel.htmlFor=picker.id;pickerLabel.append(picker);picker.onchange=()=>load(committed.catalog.offset,picker.value);
  const list=el('div',undefined,'research-result-list');list.id='research-result-list';list.setAttribute('role','group');list.setAttribute('aria-label','Choose saved research result');
  const pagination=el('div',undefined,'research-pagination'),prev=button('Previous',()=>load(Math.max(0,(committed?.catalog.offset||0)-10)), 'research-prev'),next=button('Next',()=>load(committed?.catalog.next_offset),'research-next'),pageLabel=el('small');pagination.append(prev,pageLabel,next);
  const appearance=el('div',undefined,'research-appearance');appearance.append(el('small','Theme'));
  for(const mode of ['auto','light','dark'])appearance.append(button(mode[0].toUpperCase()+mode.slice(1),()=>{setTheme(mode);renderChart();},'research-theme-'+mode));
  aside.append(head,catalogStatus,reload,pickerLabel,list,pagination,appearance);
  const main=el('div',undefined,'research-main'),intro=el('header',undefined,'research-intro'),plot=el('section',undefined,'research-plot');plot.setAttribute('aria-label','Supplied nominal NAV by named leg');
  const legend=el('div',undefined,'research-legends'),canvas=el('div');canvas.id='research-chart';
  const chartNote=el('p','','research-chart-note'),pointLabel=el('label','Inspect supplied UTC sample','research-point-label'),pointInput=el('input');pointInput.id='research-point';pointInput.type='range';pointInput.min='0';pointInput.step='1';pointInput.setAttribute('aria-describedby','research-point-summary');pointLabel.htmlFor=pointInput.id;
  const pointSummary=el('p','','research-point-summary');pointSummary.id='research-point-summary';pointSummary.setAttribute('role','status');
  const pointBody=el('div'),pointDetails=details('Exact NAV and ledger at this sample',pointBody,'research-point-details');
  pointInput.oninput=()=>{inspect=Number(pointInput.value);renderPoint();};
  const inspector=el('div',undefined,'research-inspector');inspector.append(pointLabel,pointInput,pointSummary,pointDetails);
  const content=el('section',undefined,'research-content');content.id='research-content';content.setAttribute('aria-label','Result metrics, costs, limitations and provenance');
  plot.append(legend,canvas,chartNote,inspector);main.append(intro,plot,content);root.append(aside,main);
  function open(show){active=show;root.hidden=!show;historyWorkspace.hidden=show;priceButton.setAttribute('aria-pressed',String(!show));savedButton.setAttribute('aria-pressed',String(show));onToggle(show);if(show){if(!committed&&!loading)load(0);else{render();requestAnimationFrame(renderChart);}}else{client.cancel();loading=false;}}
  function renderPending(){
    const target=committed?.catalog.items.find(i=>i.result_id===request.selection)?.question.label;
    const label=loading?'Updating '+(target||'saved research')+(committed?' · current result retained.':'. Waiting for a complete result.'):error?'Update failed · '+error+(committed?'. Last coherent result retained.':'. No result available.'):committed?.detail?'Research ready':committed?'No saved research results.':'Open saved research to load persisted results.';
    catalogStatus.textContent=label;catalogStatus.className='research-load-status'+(error?' research-error':'');root.setAttribute('aria-busy',String(loading));reload.textContent=error?'Retry results':'Refresh results';
    prev.disabled=loading||!committed||committed.catalog.offset===0;next.disabled=loading||committed?.catalog.next_offset==null;
    for(const b of list.querySelectorAll('button'))b.disabled=false;
  }
  async function load(offset=0,selection=null){
    if(!Number.isInteger(offset))return;request={offset,selection};loading=true;error=null;if(!committed)render();else renderPending();
    try{const next=await client.load(offset,selection);if(!next)return;
      const same=committed?.detail?.result_id===next.detail?.result_id;committed=next;if(!same){inspect=0;main.scrollTop=0;root.scrollTop=0;}
      loading=false;error=null;render();
    }catch(e){loading=false;error=/^[A-Z0-9_]+$/.test(e.message)?e.message:'RESEARCH_API_UNAVAILABLE';if(!committed)render();else renderPending();}
  }
  function render(){
    for(const mode of ['auto','light','dark'])document.getElementById('research-theme-'+mode)?.setAttribute('aria-pressed',String(theme()===mode));
    const previous=committed?.detail?.result_id===root.dataset.renderedResult?[...root.querySelectorAll('details')].map(d=>d.open):[];
    renderPending();list.replaceChildren();picker.replaceChildren();const detail=committed?.detail;onContext(detail?'Saved research · '+detail.record.question.id+' · '+detail.result_id:'Saved research · '+(loading?'Updating':error||'No result'));
    for(const item of committed?.catalog.items||[]){
      const option=el('option',item.question.label);option.value=item.result_id;option.selected=item.result_id===detail?.result_id;picker.append(option);
      const b=button('',()=>load(committed.catalog.offset,item.result_id));b.className='research-result';b.dataset.resultId=item.result_id;b.setAttribute('aria-pressed',String(item.result_id===detail?.result_id));
      b.append(el('b',item.question.label),el('span',item.question.summary),el('small',item.evidence_level+' · Financial '+item.assessment.financial),el('code',item.result_id));list.append(b);
    }
    if(committed&&!committed.catalog.items.length)list.append(el('p','No persisted results are available. No demonstration result is substituted.','research-muted'));
    picker.disabled=!committed?.catalog.items.length;pagination.hidden=!committed||committed.catalog.total<=10;
    pageLabel.textContent=committed?.catalog.items.length?'Results '+(committed.catalog.offset+1)+'–'+(committed.catalog.offset+committed.catalog.items.length)+' of '+committed.catalog.total:'No results';
    intro.replaceChildren();content.replaceChildren();legend.replaceChildren();
    if(!detail){intro.append(el('h1','Saved research'),el('p',error?'The result service is unavailable. Use Retry results to try again.':loading?'Loading a complete saved result. No demonstration values are substituted.':committed?'No saved research results. Persisted results will appear here when available.':'Choose a persisted research question to inspect supplied strategy and benchmark results.'));plot.hidden=true;return;}
    plot.hidden=false;const r=detail.record;
    intro.append(el('p',r.evidence_level,'research-eyebrow'),el('h1',r.question.label),el('p',r.question.summary),el('p',assessmentText(detail.assessment),'research-assessment'));
    const identity=el('details',undefined,'research-identity');identity.append(el('summary','Result identity · '+r.question.id),el('code',detail.result_id),el('code','Content SHA-256 '+detail.content_sha256));intro.append(identity);
    intro.append(el('p',r.basis.currency+' nominal NAV · '+r.basis.frequency+' · UTC sample grid · '+r.basis.wealth_basis+' · '+r.basis.cost_basis,'research-basis'));
    r.series.forEach((leg,i)=>{const label=el('span',undefined,'research-leg'),line=el('i'),stroke=legStyle(leg,i);line.style.background=strokeBackground(stroke);line.style.height=stroke.width+'px';line.setAttribute('aria-hidden','true');label.append(line,el('b',leg.label),el('small',leg.role+(leg.id===r.primary_benchmark_id?' · PRIMARY':'')));legend.append(label);});
    const statement=el('section',undefined,'research-interpretation');statement.append(el('h2','Point result'),el('p',r.point_interpretation),el('p',r.financial_claim,'research-muted'));content.append(statement);
    renderValuesTable(content,'Supplied metrics',r.metrics,r.series,true);
    const comparisons=el('section');comparisons.append(el('h2','Producer comparisons'));
    if(!r.comparisons.length)comparisons.append(el('p','No comparisons supplied.','research-muted'));
    for(const c of r.comparisons){const p=el('p');p.append(el('b',(r.metrics.find(m=>m.id===c.metric_id)?.label||c.metric_id)+' · '+r.series.find(s=>s.id===c.left_id).label+' vs '+r.series.find(s=>s.id===c.right_id).label+': '+valueLabel(c.result,c.metric_id)+' '+c.unit),el('span',' · '+c.interpretation));comparisons.append(p);}content.append(comparisons);
    const criteria=el('section');criteria.append(el('h2','Preregistered point conditions'));
    if(!r.criteria.length)criteria.append(el('p','No point criteria supplied.','research-muted'));
    for(const c of r.criteria){const p=el('p');p.append(el('b',c.status+(c.reason?' · '+c.reason:'')),document.createTextNode(' — '+c.description));criteria.append(p);}content.append(criteria);
    renderValuesTable(content,'Costs as supplied',r.costs,r.series,false);
    for(const cost of r.costs)content.append(el('p',cost.kind+' · '+cost.label+' — '+cost.description,'research-cost-description'));
    const limits=el('section',undefined,'research-limits');limits.append(el('h2','Limitations'));
    for(const limit of r.limitations){const p=el('p');p.append(el('b',limit.code+' · '+limit.scope),el('span',limit.text));limits.append(p);}content.append(limits);
    const basis=el('dl');for(const key of ['currency','frequency','timezone','wealth_basis','cost_basis','cash_basis','risk_free_basis'])definition(basis,key.replaceAll('_',' '),r.basis[key]);content.append(details('Basis and assumptions',basis));
    const bindings=el('dl');for(const key of ['protocol_id','protocol_sha256','data_revision','data_sha256','code_revision','evaluator_revision','runtime_id','producer_id','candidate_id','experiment_id'])definition(bindings,key.replaceAll('_',' '),r.bindings[key]);for(const source of r.provenance)definition(bindings,'Provenance · '+source.role,source.id+' · '+source.sha256);content.append(details('Protocol, data and code bindings',bindings));
    const reviews=el('div');reviews.append(el('p',assessmentText(detail.assessment)));
    for(const review of detail.assessment.reviews){const dl=el('dl');for(const key of ['scope','verdict','evidence_status','reason','scope_description','reviewer_id','recorded_at','result_id','content_sha256'])definition(dl,key,review[key]);definition(dl,'Reference',review.reference?.role+' · '+review.reference?.id+' · '+review.reference?.sha256);reviews.append(dl);}
    if(!detail.assessment.reviews.length)reviews.append(el('p','No independent review has been recorded for this exact result.'));content.append(details('Independent assessments · exact content',reviews));
    root.dataset.renderedResult=detail.result_id;[...root.querySelectorAll('details')].forEach((d,i)=>{d.open=previous[i]===true;});
    pointInput.max=String(r.grid.length-1);inspect=Math.min(inspect,r.grid.length-1);pointInput.value=String(inspect);renderPoint();requestAnimationFrame(renderChart);
  }
  function renderValuesTable(parent,title,rows,legs,metrics){
    const section=el('section');section.append(el('h2',title));
    const scroll=el('div',undefined,'research-table-scroll');scroll.tabIndex=0;scroll.id='research-table-'+title.toLowerCase().replace(/[^a-z]+/g,'-');
    scroll.setAttribute('aria-label',title+' table. Left and Right move across columns; Home and End reach the first and last columns.');
    scroll.setAttribute('aria-keyshortcuts','ArrowLeft ArrowRight Home End');
    const controls=el('div',undefined,'research-table-controls'),previous=button('Previous columns',()=>navigate('ArrowLeft')),next=button('Next columns',()=>navigate('ArrowRight'));
    controls.hidden=true;controls.append(el('small','Portfolio columns'),previous,next);for(const b of [previous,next])b.setAttribute('aria-controls',scroll.id);
    function update(){const max=Math.max(0,scroll.scrollWidth-scroll.clientWidth);controls.hidden=max<1;previous.disabled=scroll.scrollLeft<=1;next.disabled=scroll.scrollLeft>=max-1;}
    function navigate(key){
      const left=researchTableScrollTarget(scroll.scrollLeft,Math.max(0,scroll.scrollWidth-scroll.clientWidth),key,scroll.clientWidth);if(left===null)return false;
      const origin=document.activeElement;scroll.scrollLeft=left;update();
      if(origin===previous&&previous.disabled)(next.disabled?scroll:next).focus({preventScroll:true});
      else if(origin===next&&next.disabled)(previous.disabled?scroll:previous).focus({preventScroll:true});
      return true;
    }
    scroll.onkeydown=e=>{if(e.target!==scroll||e.altKey||e.ctrlKey||e.metaKey)return;if(navigate(e.key))e.preventDefault();};
    scroll.onscroll=update;scroll.updateColumnNavigation=update;section.append(controls);
    const table=el('table'),caption=el('caption',title+' · producer values; no frontend calculation');table.append(caption);
    const tr=el('tr');tr.append(el('th','Metric / unit'));for(const leg of legs)tr.append(el('th',leg.label+' · '+leg.role));const thead=el('thead');thead.append(tr);table.append(thead);const tbody=el('tbody');
    for(const row of rows){const line=el('tr'),name=el('th',row.label);name.scope='row';name.append(el('small',row.unit));line.append(name);
      for(const leg of legs){const value=row.values[leg.id],cell=el('td'),summary=el('span',valueLabel(value,metrics?row.id:null),'research-number');cell.append(summary);
        if(value.status==='OK'){const exact=el('details',undefined,'research-exact-value');exact.append(el('summary','Exact value'),el('code',value.value));cell.append(exact);}line.append(cell);}tbody.append(line);}
    table.append(tbody);scroll.append(table);section.append(scroll);parent.append(section);
  }
  function renderPoint(){
    const r=committed?.detail?.record;if(!r)return;inspect=Math.max(0,Math.min(inspect,r.grid.length-1));pointInput.value=String(inspect);pointInput.setAttribute('aria-valuetext',r.grid[inspect]+' · sample '+(inspect+1)+' of '+r.grid.length);
    pointSummary.textContent=r.grid[inspect]+' · '+r.series.map(leg=>leg.label+' '+valueLabel(leg.values[inspect])+' '+leg.unit).join(' · ');
    pointBody.replaceChildren();for(const leg of r.series){const group=el('section');group.append(el('h3',leg.label+' · '+leg.role));const dl=el('dl');definition(dl,'UTC grid sample',r.grid[inspect]);definition(dl,'NAV · USD',valueLabel(leg.values[inspect]));
      const ledger=leg.ledger[inspect];for(const key of ['cash','exposure','cumulative_flat_fees','cumulative_bps_fees'])definition(dl,key.replaceAll('_',' '),ledger[key]??'Unavailable');
      definition(dl,'Positions',Object.entries(ledger.positions).map(([id,n])=>id+': '+n).join(' · ')||'None');definition(dl,'Supplied net return',valueLabel(ledger.net_return));group.append(dl);pointBody.append(group);}
  }
  function renderChart(){
    if(!active||!committed?.detail||!canvas.clientWidth||!canvas.clientHeight)return;
    if(!chart){chart=echarts.init(canvas,null,{renderer:'canvas'});chart.on('click',p=>{if(Number.isInteger(p.dataIndex)){inspect=p.dataIndex;renderPoint();}});}
    root.querySelectorAll('.research-table-scroll').forEach(s=>s.updateColumnNavigation?.());
    const r=committed.detail.record,c=style(),narrow=innerWidth<701;
    const previousZoom=chartResult===committed.detail.result_id?chart.getOption().dataZoom?.[0]:null,zoom=previousZoom?{start:previousZoom.start,end:previousZoom.end}:{start:0,end:100};chartResult=committed.detail.result_id;
    let precision=0;const series=r.series.map((leg,i)=>({id:leg.id,name:leg.label+' · '+leg.role,type:'line',data:leg.values.map(v=>{const n=researchPlotValue(v);if(n===null&&v.status==='OK')precision++;return n;}),connectNulls:false,showSymbol:false,smooth:false,lineStyle:legStyle(leg,i),emphasis:{disabled:true}}));
    chartNote.textContent='Supplied nominal NAV · '+r.basis.currency+' · complete UTC grid; gaps remain gaps. '+(precision?precision+' values exceed renderer precision; exact tokens remain below.':'Ledger and exact decimal tokens are available below.');
    chart.resize();chart.setOption({animation:false,backgroundColor:c.surface,textStyle:{color:c.ink,fontFamily:'Golos Text'},grid:{left:narrow?58:78,right:22,top:20,bottom:65},xAxis:{type:'category',data:r.grid,boundaryGap:false,axisLabel:{color:c.muted,fontSize:10,formatter:d=>d.slice(0,10)},axisLine:{lineStyle:{color:c.rule}}},yAxis:{type:'value',scale:true,name:r.basis.currency,axisLabel:{color:c.muted,fontSize:10},splitLine:{lineStyle:{color:c.rule}}},dataZoom:[{type:'inside',filterMode:'none',...zoom},{type:'slider',...zoom,bottom:5,height:15,showDataShadow:false,showDetail:false,borderColor:c.rule,fillerColor:c.action+'20'}],tooltip:{trigger:'axis',confine:true,renderMode:'richText',backgroundColor:c.surface,borderColor:c.rule,textStyle:{color:c.ink,fontSize:11},formatter:items=>{const index=items[0]?.dataIndex;if(!Number.isInteger(index))return '';return r.grid[index]+'\n'+r.series.map(leg=>leg.label+' · '+leg.role+': '+valueLabel(leg.values[index])+' '+leg.unit).join('\n');}},series},{notMerge:true});
  }
  const observer=new ResizeObserver(()=>{cancelAnimationFrame(renderFrame);renderFrame=requestAnimationFrame(renderChart);});observer.observe(root);
  const themeObserver=new MutationObserver(()=>{if(active)render();});themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  open(false);return {navigation:nav,open,refresh:()=>load(request.offset,request.selection),isActive:()=>active,reset(){client.cancel();committed=null;loading=false;error=null;request={offset:0,selection:null};inspect=0;chartResult=null;chart?.clear();open(false);}};
}

if(typeof module!=='undefined')module.exports={researchTableScrollTarget};
