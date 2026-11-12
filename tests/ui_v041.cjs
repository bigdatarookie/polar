// Invented exact-ID/date-lane controls. No economic execution qualification.
const {test}=require('node:test'),assert=require('node:assert/strict');
const {executionDateGroups}=require('../src/polar/web/research.js'),{chartGeometry}=require('../src/polar/web/chart-ui.js');
test('date grouping retains every exact overlapping order ID and nanosecond ordering',()=>{
 const events=[{order_id:'second',session_date:'2025-01-02',timestamp_ns:'1735851600000000103',symbol:'TEST',side:'SELL',price_micro:'999000000'},{order_id:'first',session_date:'2025-01-02',timestamp_ns:'1735851600000000102',symbol:'TEST',side:'SELL',price_micro:'999000000'},{order_id:'other-date',session_date:'2025-01-03',timestamp_ns:'1735938000000000000',symbol:'TEST',side:'BUY',price_micro:'1000000'}];
 const groups=executionDateGroups(events);assert.equal(groups.length,2);assert.deepEqual(groups[0].events.map(e=>e.order_id),['first','second']);assert.equal(groups.flatMap(g=>g.events).length,3);assert.equal(events[0].order_id,'second');
 // The neutral date-lane location does not imply either micro-price equals a raw candle price.
 assert.equal(groups[0].date,'2025-01-02');assert(!('price' in groups[0]));
});
test('execution lane is spatially separate while sharing price-grid horizontal extent across layouts',()=>{
 for(const narrow of [false,true])for(const volume of [false,true])for(const rsi of [false,true]){
  const layout=chartGeometry({width:narrow?390:1100,height:400,narrow,volume,rsi,reference:false,executions:true});const lane=layout.grid[layout.executionGrid];assert.equal(lane.id,'execution-grid');assert.equal(lane.left,layout.grid[0].left);assert.equal(lane.right,layout.grid[0].right);assert(layout.priceBox.y+layout.priceBox.height<lane.top);assert(lane.height>0);
 }
});
