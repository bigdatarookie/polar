const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createHistoryClient,historySeriesCacheKey,historyBufferedWindow,historyWindowContains,historyBufferNeedsPrefetch}=require('../src/polar/web/history.js');
const definition='467df7e251db727ecc35ae413b5416d2a61dea36a7f717850a06b1b03807f424';
const controls=()=>({sma:true,ema:false,bollinger:false,rsi:false,benchmark:false,indicators:{sma:{period:20},ema:{period:20},bollinger:{period:20,deviation:'2'},rsi:{period:14}},referenceFamily:'RAW_PRICE_RELATIVE'});
const context=()=>({revision:{dataset_id:'invented',dataset_revision:'histrev-'+'1'.repeat(64),import_receipt_id:'2'.repeat(64),manifest_sha256:'3'.repeat(64),basis:{ohlc_basis:'VENDOR_RAW_UNADJUSTED',adjusted_close_basis:'VENDOR_SPLIT_AND_DIVIDEND_ADJUSTED',volume_basis:'VENDOR_SPLIT_ADJUSTED'}},instrument:{instrument_id:'invented-a',first_date:'2024-01-01',last_date:'2024-01-02'},assets:[{instrument_id:'hist-us-0004'}],rows:[{session_date:'2024-01-01'},{session_date:'2024-01-02'}]});
const window={start:'2024-01-01',end_exclusive:'2024-01-03'};
function page(c,params,w=window){
 const keys=['sma','ema','bb_middle','bb_upper','bb_lower','rsi','asset_reference','benchmark_reference'];
 const values=Object.fromEntries(keys.map(k=>[k,k==='sma'?'101.25':null]));
 const statuses=Object.fromEntries(keys.map(k=>[k,{status:k==='sma'?'VALUE':'DISABLED',reason:null}]));
 const metadata=Object.fromEntries(keys.slice(0,6).map(k=>[k,{status:k==='sma'?'READY':'DISABLED',period:k==='sma'?params.indicators.sma.period:null,available_history:2,first_valid_session:k==='sma'?'2024-01-01':null}]));
 return {...c.revision,schema_version:'polar.history-series/1',instrument_id:c.instrument.instrument_id,calculation_version:'polar.history-calculation/1',numeric_version:'decimal50-v1',definition_sha256:definition,window:w,request_identity:'synthetic-request',parameters:{sma_period:params.indicators.sma.period,ema_period:null,bb_period:null,rsi_period:null,bb_deviation:null,basis:'RAW_CLOSE',reference_family:params.referenceFamily,benchmark_instrument_id:'hist-us-0004'},reference_metadata:{family:params.referenceFamily,instrument_id:c.instrument.instrument_id,benchmark_instrument_id:'hist-us-0004'},series_metadata:metadata,coverage:{observed_in_window:2,expected_sessions:2},fitness:{},data_status:'SYNTHETIC',resets:[],warmup:{requested:0,status:'FULL_PREFIX'},rows:c.rows.map(r=>({...r,row_role:'VISIBLE',values:{...values},statuses:{...statuses}})),row_count:2,next_cursor:null,window_complete:true};
}
const response=body=>({ok:true,text:async()=>JSON.stringify(body)});
test('complete validated series buffer is reused without a new request; window/params/asset/revision isolate cache',async()=>{
 const c=context(),p=controls();let calls=0;
 const client=createHistoryClient(async()=>{calls++;return response(page(c,p));});
 const first=await client.series(c,p,window);
 assert.strictEqual(await client.series(c,p,{start:'2024-01-02',end_exclusive:'2024-01-03'}),first);assert.equal(calls,1);
 const base=historySeriesCacheKey(c,p);
 for(const changed of [{...p,indicators:{...p.indicators,sma:{period:50}}},{...p,referenceFamily:'PROVIDER_ADJUSTED_CLOSE_PROXY'},{...p,ema:true}])assert.notEqual(historySeriesCacheKey(c,changed),base);
 assert.notEqual(historySeriesCacheKey({...c,instrument:{...c.instrument,instrument_id:'invented-b'}},p),base);
 assert.notEqual(historySeriesCacheKey({...c,revision:{...c.revision,dataset_revision:'histrev-'+'4'.repeat(64)}},p),base);
 assert.equal(historyWindowContains(window,{start:'2023-12-31',end_exclusive:'2024-01-02'}),false);
});
test('identical in-flight requests coalesce; obsolete response ignoring abort cannot populate cache',async()=>{
 const c=context(),p=controls(),calls=[];
 const client=createHistoryClient((url,options)=>new Promise(resolve=>calls.push({url,options,resolve})));
 const old=client.series(c,p,window);const rejected=assert.rejects(old,/HISTORY_REQUEST_CANCELLED/);
 assert.strictEqual(client.series(c,p,window),old);assert.equal(calls.length,1);
 const changed={...p,indicators:{...p.indicators,sma:{period:50}}};const next=client.series(c,changed,window);
 assert.equal(calls[0].options.signal.aborted,true);calls[1].resolve(response(page(c,changed)));await next;
 calls[0].resolve(response(page(c,p)));await rejected;
 const retry=client.series(c,p,window);assert.equal(calls.length,3);calls[2].resolve(response(page(c,p)));await retry;
});
test('cancel during a paged response never commits partial pages or caches stale success',async()=>{
 const c=context(),p=controls(),calls=[];const client=createHistoryClient((url,options)=>new Promise(resolve=>calls.push({url,options,resolve})));
 const load=client.series(c,p,window),rejected=assert.rejects(load,/HISTORY_REQUEST_CANCELLED/);
 const first=page(c,p);first.rows=first.rows.slice(0,1);first.row_count=1;first.next_cursor='page2';first.window_complete=false;calls[0].resolve(response(first));
 await new Promise(resolve=>setImmediate(resolve));assert.equal(calls.length,2);
 client.cancel();const last=page(c,p);last.rows=last.rows.slice(1);last.row_count=1;calls[1].resolve(response(last));await rejected;
 const retry=client.series(c,p,window);assert.equal(calls.length,3);calls[2].resolve(response(page(c,p)));await retry;
});
test('invalid complete response is rejected and cannot poison retry cache',async()=>{
 const c=context(),p=controls();let calls=0;const invalid=page(c,p);invalid.definition_sha256='0'.repeat(64);
 const client=createHistoryClient(async()=>response(++calls===1?invalid:page(c,p)));
 await assert.rejects(client.series(c,p,window),/HISTORY_CALCULATION_VERSION_MISMATCH/);await client.series(c,p,window);assert.equal(calls,2);
});
test('small admitted daily history uses full window; larger supplied context gets bounded symmetric margin',()=>{
 const c=context();assert.deepEqual(historyBufferedWindow(c,{start:'2024-01-02',end_exclusive:'2024-01-03'}),window);
 // Technical helper case only: accepted transport still rejects >5000 total rows.
 const rows=Array.from({length:6000},(_,i)=>({session_date:new Date(Date.UTC(2000,0,1+i)).toISOString().slice(0,10)}));
 const large={...c,rows,instrument:{...c.instrument,first_date:rows[0].session_date,last_date:rows.at(-1).session_date}};
 const visible={start:rows[3000].session_date,end_exclusive:rows[3024].session_date};const b=historyBufferedWindow(large,visible);
 assert.equal(b.start,rows[2872].session_date);assert.equal(b.end_exclusive,rows[3153].session_date);assert(historyWindowContains(b,visible));
 assert.equal(historyBufferNeedsPrefetch(large,b,visible),false);
 assert.equal(historyBufferNeedsPrefetch(large,b,{start:rows[3130].session_date,end_exclusive:rows[3150].session_date}),true);
 assert.equal(historyBufferNeedsPrefetch(c,window,window),false);
});
