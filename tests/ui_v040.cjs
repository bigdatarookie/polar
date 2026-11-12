// Invented v040 descriptive interval/theme controls; no retained report recomputation.
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {intervalMaxDrawdown}=require('../src/polar/web/data.js');
const points=values=>values.map(value=>({value:String(value),status:'OK'}));
test('drawdown uses interior peak/trough even with equal endpoint values',()=>{
 const result=intervalMaxDrawdown(points([100,150,90,100]));assert.equal(result.value,'40.00');assert.equal(result.count,4);
 assert.equal(intervalMaxDrawdown(points([100,100])).value,'0.00'); // endpoints alone would miss40%
});
test('rising complete positives return0; one point, incomplete, gaps and invalid peaks remain N/A',()=>{
 assert.equal(intervalMaxDrawdown(points([1,2,3])).value,'0.00');
 for(const input of [[],points([100]),points([0,1]),points([-1,2]),[{value:'100',status:'OK'},{value:null,status:'UNAVAILABLE'}],[{value:'NaN',status:'OK'},...points([100])]])assert.equal(intervalMaxDrawdown(input).status,'UNAVAILABLE');
 assert.equal(intervalMaxDrawdown(points([100,90]),{complete:false}).reason,'INCOMPLETE_INTERVAL');
});
test('interval arithmetic keeps decimal precision, large denominators and negative NAV truth',()=>{
 assert.equal(intervalMaxDrawdown(points(['100000000000000000000000000000000000000','60000000000000000000000000000000000000'])).value,'40.00');
 assert.equal(intervalMaxDrawdown(points(['0.000000000000001','0.0000000000000005'])).value,'50.00');
 assert.equal(intervalMaxDrawdown(points(['100','-20'])).value,'120.00');
});
test('theme bootstrap executes before styles/vendor/data and honors persisted/system/default safely',()=>{
 const html=fs.readFileSync(require.resolve('../src/polar/web/index.html'),'utf8'),script=html.match(/<script>([\s\S]*?)<\/script>/)[1];assert(html.indexOf(script)<html.indexOf('rel="stylesheet"'));assert(html.indexOf(script)<html.indexOf('echarts-6.0.0'));
 for(const [saved,light,expected]of [['dark',true,'dark'],['light',false,'light'],['auto',true,'light'],['auto',false,'dark'],['invalid',false,'dark']]){const document={documentElement:{dataset:{}}};vm.runInNewContext(script,{document,localStorage:{getItem:()=>saved},matchMedia:()=>({matches:light})});assert.equal(document.documentElement.dataset.theme,expected);}
 const document={documentElement:{dataset:{}}};vm.runInNewContext(script,{document,localStorage:{getItem(){throw Error('blocked');}}});assert.equal(document.documentElement.dataset.theme,'dark');
 assert(!html.includes('id="open-test-mode"'));
});
const {historyInitialWindow,historyBufferedWindow}=require('../src/polar/web/history.js');
test('fresh initial history is bounded, explicit All and saved interval are respected',()=>{
 const instrument={first_date:'2015-11-02',last_date:'2026-11-06'};
 const fresh=historyInitialWindow(instrument,'3M');assert.equal(fresh.visible.start,'2026-08-06');assert(fresh.buffer.start>'2015-11-02');assert.equal(fresh.buffer.end_exclusive,'2026-11-07');
 const all=historyInitialWindow(instrument,'All');assert.equal(all.buffer.start,instrument.first_date);
 const saved={start:'2021-02-01',end_exclusive:'2021-03-01'};assert.deepEqual(historyInitialWindow(instrument,'3M',saved).visible,saved);
 assert.deepEqual(historyBufferedWindow({instrument,rows:[{session_date:'2026-08-06'}],loadedWindow:fresh.buffer},fresh.visible),fresh.buffer);
 assert.throws(()=>historyInitialWindow(instrument,'3M',{start:'2030-01-01',end_exclusive:'2030-02-01'}),/HISTORY_WINDOW_INVALID/);
});
const {researchLoadProgressive}=require('../src/polar/web/research.js');
test('discovery is complete before serial details and cancellation prevents late progress',async()=>{
 const items=[{result_id:'a'},{result_id:'b'}],calls=[];
 const client={load:async(offset,_,options)=>{assert.equal(options.catalogOnly,true);calls.push('catalog'+offset);return {catalog:{total:2,items:[items[offset]],next_offset:offset?null:1}};},detail:async item=>{calls.push('detail'+item.result_id);return item;}};
 const result=await researchLoadProgressive(client,()=>true,s=>{calls.push('discovery');assert.equal(s.items.length,2);assert.equal(s.details.length,0);},s=>calls.push('progress'+s.details.length));
 assert.deepEqual(calls,['catalog0','catalog1','discovery','detaila','progress1','detailb','progress2']);assert.equal(result.details.length,2);
 let current=true,progress=0;client.detail=async item=>{current=false;return item;};assert.equal(await researchLoadProgressive(client,()=>current,()=>{},()=>progress++),null);assert.equal(progress,0);
});
