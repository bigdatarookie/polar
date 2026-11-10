const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chartGeometry,overlayStroke,strokeBackground}=require('../src/polar/web/chart-ui.js');
const {restoredControls}=require('../src/polar/web/data.js');
test('volume space goes to candles and restores without changing RSI or reference axes',()=>{
 for(const narrow of [false,true])for(const rsi of [false,true]){
  const input={height:440,width:narrow?390:1190,narrow,rsi,reference:true};
  const on=chartGeometry({...input,volume:true}),off=chartGeometry({...input,volume:false});
  assert(off.priceBox.height>on.priceBox.height);
  assert.equal(off.grid[1].height,0);assert.equal(off.grid[0].top,on.grid[0].top);
  assert.equal(off.right,on.right);assert.equal(off.priceBox.width,on.priceBox.width);
  if(rsi){assert.deepEqual(off.grid[2],on.grid[2]);assert.equal(off.priceBox.height-on.priceBox.height,on.grid[1].height+24);}
  else assert.equal(off.priceBox.height-on.priceBox.height,79);
  assert.deepEqual(chartGeometry({...input,volume:true}),on);
 }
});
test('samples and chart share precise stroke and dash definitions, including each band/reference',()=>{
 const c={sma:'#111111',action:'#222222',muted:'#333333',equity:'#444444',benchmark:'#555555'};
 const sma=overlayStroke('sma',c),ema=overlayStroke('ema',c);
 assert.deepEqual(sma,{color:c.sma,width:1.8,type:[2,3]});
 assert.deepEqual(ema,{color:c.action,width:1.8,type:[7,4]});
 assert.equal(strokeBackground(ema),'repeating-linear-gradient(to right, #222222 0 7px, transparent 7px 11px)');
 assert.equal(overlayStroke('bb_middle',c).color,c.muted);
 assert.deepEqual(overlayStroke('bb_upper',c),overlayStroke('bb_lower',c));
 assert.equal(overlayStroke('asset_reference',c).width,2.2);
 assert.deepEqual(overlayStroke('benchmark_reference',c).type,[8,4]);
 assert.equal(strokeBackground(overlayStroke('rsi',c)),c.action);
});
test('volume and disclosure persistence validates types and reset defaults',()=>{
 assert.equal(restoredControls(null,0).volume,true);
 assert.deepEqual(restoredControls(null,0).diagnostics,{});
 const c=restoredControls({volume:false,diagnostics:{raw:true,sma:false,evil:true}},3);
 assert.equal(c.volume,false);assert.deepEqual(c.diagnostics,{raw:true,sma:false});
 assert.equal(restoredControls({volume:'false',diagnostics:{raw:'true'}},3).volume,true);
 assert.deepEqual(restoredControls({diagnostics:{raw:'true'}},3).diagnostics,{});
});
