import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {DTB3_RETURN_KEY,dtb3ReturnContext,readDtb3Return,saveDtb3Return,dtb3BackURL,dtb3SameViewURL}=require('../src/polar/web/dtb3-return.js');
const base='http://polar.test/ui/?dataset=saved&revision=pinned&workspace=research&start=2026-01-01&end=2026-02-01';
const context=()=>({schema:'polar.dtb3-research-return/1',pending:true,result_id:'research-'+'a'.repeat(64),offset:10,theme:'dark',main_scroll:320,catalog_scroll:48,root_scroll:0,disclosures:[true,false,true],url:base});
function storage(){const values=new Map();return {getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)};}
test('note return preserves exact research identity/page/scroll/disclosures/theme with no financial payload',()=>{
 const saved=storage(),input={...context(),measurements:[{cleared_order:'never restore'}],record:{grid:['fake']}};
 assert.equal(saveDtb3Return(input,saved,base),true);
 assert.deepEqual(readDtb3Return(saved,base),context());
 const parsed=JSON.parse(saved.getItem(DTB3_RETURN_KEY));assert.equal('measurements' in parsed,false);assert.equal('record' in parsed,false);
 const back=new URL(dtb3BackURL(parsed,base),base);assert.equal(back.searchParams.get('dataset'),'saved');assert.equal(back.searchParams.get('revision'),'pinned');assert.equal(back.searchParams.get('dtb3_return'),'1');
});
test('direct entry has a Research fallback and cannot redirect to another origin',()=>{
 assert.equal(dtb3BackURL(null,base),'/ui/?workspace=research');
 assert.equal(dtb3ReturnContext({...context(),url:'https://other.example/ui/'},base),null);
 assert.equal(dtb3ReturnContext({...context(),url:'http://polar.test/v1/private'},base),null);
});
test('history return ignores only navigation marker ordering, not dataset/range identity',()=>{
 assert.equal(dtb3SameViewURL(base,'http://polar.test/ui/?end=2026-02-01&revision=pinned&dataset=saved&start=2026-01-01&dtb3_return=1'),true);
 assert.equal(dtb3SameViewURL(base,base.replace('revision=pinned','revision=other')),false);
 assert.equal(dtb3SameViewURL(base,base.replace('2026-02-01','2026-03-01')),false);
});
test('malformed or unavailable state is not restored',()=>{
 assert.equal(dtb3ReturnContext({...context(),offset:-1},base),null);
 assert.equal(dtb3ReturnContext({...context(),main_scroll:NaN},base),null);
 assert.equal(dtb3ReturnContext({...context(),disclosures:[1]},base),null);
 assert.equal(readDtb3Return({getItem:()=>'{broken'},base),null);
 assert.equal(saveDtb3Return(context(),{setItem:()=>{throw new Error('unavailable');}},base),false);
});
