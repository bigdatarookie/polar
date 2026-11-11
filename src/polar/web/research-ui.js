// Existing-workspace saved-result view. No economic calculations or synthetic fallback.
'use strict';
function researchTableScrollTarget(left,max,key,width){
  const step=Math.max(120,Math.floor(width*.75));
  const target=key==='ArrowRight'?left+step:key==='ArrowLeft'?left-step:key==='Home'?0:key==='End'?max:null;
  return target===null?null:Math.max(0,Math.min(max,target));
}
function createResearchWorkspace({root,historyWorkspace,fetcher,theme=()=> 'auto',setTheme,onToggle,onContext=()=>{},onCompare=()=>{}}){
  const client=createResearchClient(fetcher);
  let active=false,committed=null,loading=false,error=null,request={offset:0,selection:null},chart=null,inspect=0,renderFrame=0,chartResult=null,metricChoice=null;
  const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
  const button=(label,action,id)=>{const node=el('button',label);node.type='button';if(id)node.id=id;node.onclick=action;return node;};
  const details=(label,body,id)=>{const d=el('details',undefined,'research-disclosure');if(id)d.id=id;d.append(el('summary',label),body);return d;};
  const definition=(parent,key,value)=>parent.append(el('dt',key),el('dd',value??'Unavailable'));
  const style=()=>{const css=getComputedStyle(document.documentElement),get=k=>css.getPropertyValue('--'+k).trim();return {surface:get('surface'),ink:get('ink'),muted:get('muted'),rule:get('rule'),action:get('action'),benchmark:get('benchmark'),sma:get('sma'),up:get('up')};};
  const legStyle=(leg,index)=>{const c=style();return {color:leg.role==='STRATEGY'?c.action:leg.role==='BENCHMARK'?c.benchmark:[c.sma,c.up,c.muted][index%3],width:leg.role==='STRATEGY'?2.5:1.8,type:leg.role==='STRATEGY'?'solid':leg.role==='BENCHMARK'?[8,4]:[2+index,3]};};
  const valueLabel=(value,metricId)=>{if(value?.status!=='OK')return [value?.status||'UNAVAILABLE',value?.reason].filter(Boolean).join(' · ');const rounded=researchDecimalDisplay(value.value,2);return rounded==='0.00'&&/[1-9]/.test(value.value)&&!String(metricId||'').toLowerCase().includes('sharpe')?'≈0.00 (see exact)':rounded;};
  const assessmentText=a=>'Technical '+a.technical+' · Product '+a.product+' · Financial '+a.financial+' · Evidence '+a.financial_evidence.status+(a.financial_evidence.reason?' / '+a.financial_evidence.reason:'');
  const nav=el('nav',undefined,'research-navigation');nav.setAttribute('aria-label','Workspace view');
  const priceButton=button('Price history',()=>open(false),'price-workspace'),savedButton=button('Saved research',()=>open(true),'saved-workspace');nav.append(priceButton,savedButton);
  root.className='research-workspace';root.hidden=true;root.setAttribute('aria-label','Saved research results');
  const aside=el('aside',undefined,'research-catalog'),head=el('div',undefined,'research-catalog-head');
  head.append(el('h2','Research library'),el('p','Questions, evidence and limitations','research-muted'));
  const catalogStatus=el('p','','research-load-status');catalogStatus.id='research-status';catalogStatus.setAttribute('role','status');catalogStatus.setAttribute('aria-live','polite');
  const reload=button('Refresh results',()=>load(request.offset,request.selection),'research-refresh');
  const pickerLabel=el('label','Saved question','research-picker-label'),picker=el('select');picker.id='research-picker';pickerLabel.htmlFor=picker.id;pickerLabel.append(picker);picker.onchange=()=>load(committed.catalog.offset,picker.value);
  const list=el('div',undefined,'research-result-list');list.id='research-result-list';list.setAttribute('role','group');list.setAttribute('aria-label','Choose saved research result');
  const pagination=el('div',undefined,'research-pagination'),prev=button('Previous',()=>load(Math.max(0,(committed?.catalog.offset||0)-10)), 'research-prev'),next=button('Next',()=>load(committed?.catalog.next_offset),'research-next'),pageLabel=el('small');pagination.append(prev,pageLabel,next);
  const appearance=el('div',undefined,'research-appearance');appearance.append(el('small','Theme'));
  for(const mode of ['auto','light','dark'])appearance.append(button(mode[0].toUpperCase()+mode.slice(1),()=>{setTheme(mode);renderChart();},'research-theme-'+mode));
  aside.append(head,catalogStatus,reload,pickerLabel,list,pagination,appearance);
  const main=el('div',undefined,'research-main'),intro=el('header',undefined,'research-intro'),plot=el('section',undefined,'research-plot');plot.setAttribute('aria-label','Supplied outcome comparison by strategy and baseline');
  const legend=el('div',undefined,'research-legends'),canvas=el('div');canvas.id='research-chart';const metricLabel=el('label','Supplied comparison metric','research-metric-label'),metricPicker=el('select');metricPicker.id='research-metric';metricLabel.htmlFor=metricPicker.id;metricLabel.append(metricPicker);metricPicker.onchange=()=>{metricChoice=metricPicker.value;renderChart();};
  const chartNote=el('p','','research-chart-note'),pointLabel=el('label','Inspect supplied UTC sample','research-point-label'),pointInput=el('input');pointInput.id='research-point';pointInput.type='range';pointInput.min='0';pointInput.step='1';pointInput.setAttribute('aria-describedby','research-point-summary');pointLabel.htmlFor=pointInput.id;
  const pointSummary=el('p','','research-point-summary');pointSummary.id='research-point-summary';pointSummary.setAttribute('role','status');
  const pointBody=el('div'),pointDetails=details('Exact NAV and ledger at this sample',pointBody,'research-point-details');
  pointInput.oninput=()=>{inspect=Number(pointInput.value);renderPoint();};
  const inspector=el('div',undefined,'research-inspector');inspector.append(pointLabel,pointInput,pointSummary,pointDetails);
  const content=el('section',undefined,'research-content');content.id='research-content';content.setAttribute('aria-label','Result metrics, costs, limitations and provenance');
  plot.append(metricLabel,legend,canvas,chartNote);const exactSamples=details('Inspect exact supplied NAV & ledger samples',inspector);content.append(exactSamples);main.append(intro,content);root.append(aside,main);
  function open(show,selection=null,offset=0){active=show;root.hidden=!show;historyWorkspace.hidden=show;priceButton.setAttribute('aria-pressed',String(!show));savedButton.setAttribute('aria-pressed',String(show));onToggle(show);if(show){if(selection)load(offset,selection);else if(!committed&&!loading)load(0);else{render();requestAnimationFrame(renderChart);}}else{client.cancel();loading=false;}}
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
      const same=committed?.detail?.result_id===next.detail?.result_id;committed=next;if(!same){inspect=0;metricChoice=null;main.scrollTop=0;root.scrollTop=0;}
      loading=false;error=null;render();
    }catch(e){loading=false;error=/^[A-Z0-9_]+$/.test(e.message)?e.message:'RESEARCH_API_UNAVAILABLE';if(!committed)render();else renderPending();}
  }
  function render(){
    for(const mode of ['auto','light','dark'])document.getElementById('research-theme-'+mode)?.setAttribute('aria-pressed',String(theme()===mode));
    const previous=committed?.detail?.result_id===root.dataset.renderedResult?[...root.querySelectorAll('details')].map(d=>d.open):[];
    renderPending();list.replaceChildren();picker.replaceChildren();const detail=committed?.detail;onContext(detail?'Saved research · '+detail.record.question.label+' · '+researchPhase(detail.record):'Saved research · '+(loading?'Updating':error||'No result'));
    for(const item of committed?.catalog.items||[]){
      const option=el('option',item.question.label);option.value=item.result_id;option.selected=item.result_id===detail?.result_id;picker.append(option);
      const b=button('',()=>load(committed.catalog.offset,item.result_id));b.className='research-result';b.dataset.resultId=item.result_id;b.setAttribute('aria-pressed',String(item.result_id===detail?.result_id));
      b.append(el('b',item.question.label),el('small',researchReadable(item.assessment.financial)));list.append(b);
    }
    if(committed&&!committed.catalog.items.length)list.append(el('p','No persisted results are available. No demonstration result is substituted.','research-muted'));
    picker.disabled=!committed?.catalog.items.length;pagination.hidden=!committed||committed.catalog.total<=10;
    pageLabel.textContent=committed?.catalog.items.length?'Results '+(committed.catalog.offset+1)+'–'+(committed.catalog.offset+committed.catalog.items.length)+' of '+committed.catalog.total:'No results';
    intro.replaceChildren();content.replaceChildren();legend.replaceChildren();
    if(!detail){intro.append(el('h1','Saved research'),el('p',error?'The result service is unavailable. Use Retry results to try again.':loading?'Loading a complete saved result. No demonstration values are substituted.':committed?'No saved research results. Persisted results will appear here when available.':'Choose a persisted research question to inspect supplied strategy and benchmark results.'));plot.hidden=true;return;}
    plot.hidden=false;const r=detail.record;
    const phase=researchPhase(r),primary=r.series.find(s=>s.role==='STRATEGY'),benchmark=r.series.find(s=>s.id===r.primary_benchmark_id);
    const conclusion=detail.assessment.financial==='NOT_SUPPORTED'?'Point claim not supported':detail.assessment.financial==='INDETERMINATE'?'Diagnostic evidence · no final point conclusion':detail.assessment.financial==='SUPPORTED_WITH_LIMITS'?'Supported within stated limits':'Awaiting independent financial review';
    intro.append(el('p',phase+' / '+r.grid[0].slice(0,10)+' — '+r.grid.at(-1).slice(0,10),'research-eyebrow'),el('h1',r.question.label),el('p',r.question.summary),el('p',conclusion,'research-conclusion'),el('p',assessmentText(detail.assessment),'research-assessment'));
    const compare=button('Compare on main chart',()=>onCompare(detail),'research-compare-main');intro.append(compare);
    const identity=el('details',undefined,'research-identity');identity.append(el('summary','Result identity · '+r.question.id),el('code',detail.result_id),el('code','Content SHA-256 '+detail.content_sha256));const jsonLink=el('a','Open the exact saved record JSON');jsonLink.href='/v1/research/results/'+encodeURIComponent(detail.result_id);jsonLink.target='_blank';jsonLink.rel='noopener';identity.append(jsonLink);intro.append(identity);
    intro.append(el('p',r.basis.currency+' nominal NAV · '+r.basis.frequency+' · UTC sample grid · '+r.basis.wealth_basis+' · '+r.basis.cost_basis,'research-basis'));
    r.series.forEach((leg,i)=>{const label=el('span',undefined,'research-leg'),line=el('i'),stroke=legStyle(leg,i);line.style.background=strokeBackground(stroke);line.style.height=stroke.width+'px';line.setAttribute('aria-hidden','true');label.append(line,el('b',leg.label),el('small',leg.role+(leg.id===r.primary_benchmark_id?' · PRIMARY':'')));legend.append(label);});
    const statement=el('section',undefined,'research-interpretation');statement.append(el('p','01 / THE QUESTION','research-eyebrow'),el('h2','What was tested'),el('p',r.question.summary));
    const mechanism=el('div',undefined,'research-mechanism');for(const [heading,text] of [['Strategy',researchReadable(primary.label)],['Primary baseline',researchReadable(benchmark.label)],['Evaluation',phase+' · '+r.grid.length+' supplied observations']]){const cell=el('div');cell.append(el('small',heading),el('b',text));mechanism.append(cell);}statement.append(mechanism);content.append(statement);
    const findings=el('section',undefined,'research-findings');findings.append(el('p','02 / THE RESULT','research-eyebrow'),el('h2',conclusion),el('p',r.financial_claim));
    const highlights=el('div',undefined,'research-highlights');const keyMetrics=r.metrics.filter(m=>/return.*after.cost|net_total_return|sharpe|max_drawdown|total_cost_usd/i.test(m.id)).slice(0,4);
    for(const m of keyMetrics){const block=el('div');block.append(el('small',m.label),el('strong',valueLabel(m.values[primary.id],m.id)),el('span',m.unit+' · '+researchReadable(primary.label)),el('small','Baseline '+valueLabel(m.values[benchmark.id],m.id)+' '+m.unit));highlights.append(block);}findings.append(highlights);content.append(findings,plot);
    const data=el('section',undefined,'research-data-story');data.append(el('p','03 / DATA & DESIGN','research-eyebrow'),el('h2','What these numbers represent'),el('p',researchReadable(r.basis.wealth_basis)+' · '+r.basis.cost_basis+' costs · '+r.basis.currency+' portfolio wealth. The selected price-history ticker is independent context, not this portfolio.'));
    const symbols=[...new Set(r.series.flatMap(s=>s.ledger.flatMap(p=>Object.keys(p.positions))))].sort();data.append(el('p',symbols.length+' recorded position aliases · '+r.grid[0].slice(0,10)+' to '+r.grid.at(-1).slice(0,10)+' · source clock '+r.basis.timezone+' / UTC sample grid.'));
    const symbolBody=el('p',symbols.join(', ')||'No positions recorded');data.append(details('Full recorded alias list · not a security identity claim',symbolBody));
    const modelLimits=r.limitations.filter(x=>/PHASE|TRAIN|TIMING|VINTAGE|ADJUSTED|SURVIVOR|UNIVERSE|RISK_AND_POLICY/.test(x.code));for(const l of modelLimits)data.append(el('p',l.text));content.append(data);
    const exactMetrics=el('div');renderValuesTable(exactMetrics,'Supplied metrics',r.metrics,r.series,true);content.append(details('All supplied metrics and exact values',exactMetrics));

    const comparisons=el('section');comparisons.append(el('h2','Supplied comparisons'));
    if(!r.comparisons.length)comparisons.append(el('p','No comparisons supplied.','research-muted'));
    for(const c of r.comparisons){const p=el('p');p.append(el('b',(r.metrics.find(m=>m.id===c.metric_id)?.label||c.metric_id)+' · '+r.series.find(s=>s.id===c.left_id).label+' vs '+r.series.find(s=>s.id===c.right_id).label+': '+valueLabel(c.result,c.metric_id)+' '+c.unit),el('span',' · '+c.interpretation));comparisons.append(p);}content.append(details('All supplied pairwise comparisons',comparisons));
    const criteria=el('section',undefined,'research-criteria');criteria.append(el('p','04 / DECISION & NEXT QUESTION','research-eyebrow'),el('h2','Did the frozen conditions hold?'),el('p',researchReadable(r.point_interpretation)));
    if(!r.criteria.length)criteria.append(el('p','No point criteria supplied.','research-muted'));
    for(const c of r.criteria){const p=el('p');p.append(el('b',researchReadable(c.status)+(c.reason?' · '+researchReadable(c.reason):'')),document.createTextNode(' — '+researchReadable(c.description)));criteria.append(p);}criteria.append(el('p','Next: interpret the supplied limits before treating this as an investable advantage. A new prospective comparison is needed for a broader adoption claim.','research-muted'));content.append(criteria);
    const costs=el('div');renderValuesTable(costs,'Costs as supplied',r.costs,r.series,false);for(const cost of r.costs)costs.append(el('p',cost.kind+' · '+cost.label+' — '+cost.description,'research-cost-description'));content.append(details('Modeled costs · amounts and assumptions',costs));
    const limits=el('section',undefined,'research-limits');limits.append(el('h2','Limitations'));
    for(const limit of r.limitations){const p=el('p');p.append(el('b',limit.code+' · '+limit.scope),el('span',limit.text));limits.append(p);}content.append(limits);
    const basis=el('dl');for(const key of ['currency','frequency','timezone','wealth_basis','cost_basis','cash_basis','risk_free_basis'])definition(basis,key.replaceAll('_',' '),r.basis[key]);content.append(details('Basis and assumptions',basis));
    const bindings=el('dl');for(const key of ['protocol_id','protocol_sha256','data_revision','data_sha256','code_revision','evaluator_revision','runtime_id','producer_id','candidate_id','experiment_id'])definition(bindings,key.replaceAll('_',' '),r.bindings[key]);for(const source of r.provenance)definition(bindings,'Provenance · '+source.role,source.id+' · '+source.sha256);content.append(details('Protocol, data and code bindings',bindings));
    const reviews=el('div');reviews.append(el('p',assessmentText(detail.assessment)));
    for(const review of detail.assessment.reviews){const dl=el('dl');for(const key of ['scope','verdict','evidence_status','reason','scope_description','reviewer_id','recorded_at','result_id','content_sha256'])definition(dl,key,review[key]);definition(dl,'Reference',review.reference?.role+' · '+review.reference?.id+' · '+review.reference?.sha256);reviews.append(dl);}
    if(!detail.assessment.reviews.length)reviews.append(el('p','No independent review has been recorded for this exact result.'));content.append(details('Independent assessments · exact content',reviews));
    content.append(exactSamples);const metricOptions=r.metrics.filter(m=>/return.*after.cost|net_total_return|sharpe|max_drawdown|annual_vol|total_cost_usd/i.test(m.id));metricPicker.replaceChildren();for(const m of metricOptions.length?metricOptions:[r.metrics[0]]){const option=el('option',m.label+' · '+m.unit);option.value=m.id;metricPicker.append(option);}if(![...metricPicker.options].some(o=>o.value===metricChoice))metricChoice=metricPicker.options[0]?.value;metricPicker.value=metricChoice;
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
    pointBody.replaceChildren();for(const leg of r.series){const group=el('section');group.append(el('h3',leg.label+' · '+leg.role));const dl=el('dl');definition(dl,'UTC grid sample',r.grid[inspect]);definition(dl,'NAV · USD',leg.values[inspect].status==='OK'?leg.values[inspect].value:valueLabel(leg.values[inspect]));
      const ledger=leg.ledger[inspect];for(const key of ['cash','exposure','cumulative_flat_fees','cumulative_bps_fees'])definition(dl,key.replaceAll('_',' ')+' · '+leg.unit,ledger[key]??'Unavailable');
      definition(dl,'Positions',Object.entries(ledger.positions).map(([id,n])=>id+': '+n).join(' · ')||'None');definition(dl,'Supplied net return',valueLabel(ledger.net_return));group.append(dl);pointBody.append(group);}
  }
  function renderChart(){
    if(!active||!committed?.detail||!canvas.clientWidth||!canvas.clientHeight)return;
    if(!chart)chart=echarts.init(canvas,null,{renderer:'canvas'});
    root.querySelectorAll('.research-table-scroll').forEach(s=>s.updateColumnNavigation?.());
    const r=committed.detail.record,c=style(),narrow=innerWidth<701,metric=r.metrics.find(m=>m.id===metricChoice)||r.metrics[0];
    chartNote.textContent='Producer-supplied '+metric.label+' · '+metric.unit+'. This infographic does not recalculate a financial metric. Exact values and statuses remain in details; time-series comparison is on main. '+r.series.filter(leg=>researchPlotValue(metric.values[leg.id])===null).map(leg=>researchReadable(leg.label)+': '+(metric.values[leg.id].status==='OK'?'outside renderer precision; see exact value':valueLabel(metric.values[leg.id],metric.id))).join(' · ');
    const values=r.series.map(leg=>researchPlotValue(metric.values[leg.id]));
    chart.resize();chart.setOption({animation:false,backgroundColor:c.surface,textStyle:{color:c.ink,fontFamily:'Golos Text'},grid:{left:narrow?118:185,right:50,top:15,bottom:32},xAxis:{type:'value',name:metric.unit,axisLabel:{color:c.muted,fontSize:10},splitLine:{lineStyle:{color:c.rule}}},yAxis:{type:'category',inverse:true,data:r.series.map(leg=>researchReadable(leg.label)),axisLabel:{color:c.ink,fontSize:narrow?9:11,width:narrow?105:165,overflow:'truncate'},axisTick:{show:false},axisLine:{show:false}},tooltip:{trigger:'item',confine:true,renderMode:'richText',formatter:p=>researchReadable(r.series[p.dataIndex].label)+'\n'+valueLabel(metric.values[r.series[p.dataIndex].id],metric.id)+' '+metric.unit},series:[{id:'supplied-outcome',type:'bar',barMaxWidth:24,data:values.map((value,i)=>({value,itemStyle:{color:legStyle(r.series[i],i).color}})),label:{show:true,position:'right',color:c.ink,fontSize:10,formatter:p=>p.value===null?'Unavailable':valueLabel(metric.values[r.series[p.dataIndex].id],metric.id)},emphasis:{disabled:true}}]},{notMerge:true});
  }
  const observer=new ResizeObserver(()=>{cancelAnimationFrame(renderFrame);renderFrame=requestAnimationFrame(renderChart);});observer.observe(root);
  const themeObserver=new MutationObserver(()=>{if(active)render();});themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  open(false);return {navigation:nav,open,openResult:(id,offset=0)=>open(true,id,offset),refresh:()=>load(request.offset,request.selection),isActive:()=>active,reset(){client.cancel();committed=null;loading=false;error=null;request={offset:0,selection:null};inspect=0;chartResult=null;chart?.clear();open(false);}};
}

if(typeof module!=='undefined')module.exports={researchTableScrollTarget};
