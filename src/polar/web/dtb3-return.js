// UI identifiers/control state only; no result payload, prices, orders or chart state.
'use strict';
const DTB3_RETURN_KEY='polar-dtb3-research-return-v1';
function dtb3ReturnContext(value,base){
  if(!value||value.schema!=='polar.dtb3-research-return/1'||typeof value.pending!=='boolean')return null;
  if(value.result_id!==null&&(typeof value.result_id!=='string'||!/^research-[a-f0-9]{64}$/.test(value.result_id)))return null;
  if(!Number.isInteger(value.offset)||value.offset<0||value.offset>4096)return null;
  if(!['auto','light','dark'].includes(value.theme)||!Array.isArray(value.disclosures)||!value.disclosures.every(v=>typeof v==='boolean'))return null;
  if(!['main_scroll','catalog_scroll','root_scroll'].every(k=>Number.isFinite(value[k])&&value[k]>=0))return null;
  let url;try{url=new URL(value.url,base);const origin=new URL(base).origin;if(url.origin!==origin||url.pathname!=='/ui/')return null;}catch{return null;}
  url.searchParams.set('workspace','research');url.searchParams.delete('view');url.searchParams.delete('dtb3_return');
  return {schema:value.schema,pending:value.pending,result_id:value.result_id,offset:value.offset,theme:value.theme,
    main_scroll:value.main_scroll,catalog_scroll:value.catalog_scroll,root_scroll:value.root_scroll,disclosures:[...value.disclosures],url:url.href};
}
function readDtb3Return(storage,base){try{return dtb3ReturnContext(JSON.parse(storage.getItem(DTB3_RETURN_KEY)||'null'),base);}catch{return null;}}
function saveDtb3Return(value,storage,base){const context=dtb3ReturnContext(value,base);if(!context)return false;try{storage.setItem(DTB3_RETURN_KEY,JSON.stringify(context));return true;}catch{return false;}}
function dtb3BackURL(context,base){const valid=dtb3ReturnContext(context,base);if(!valid)return '/ui/?workspace=research';const url=new URL(valid.url);url.searchParams.set('dtb3_return','1');return url.pathname+url.search+url.hash;}
function dtb3SameViewURL(left,right){try{const a=new URL(left),b=new URL(right);if(a.origin!==b.origin||a.pathname!==b.pathname||a.hash!==b.hash)return false;for(const u of [a,b])for(const k of ['workspace','view','dtb3_return'])u.searchParams.delete(k);return JSON.stringify([...a.searchParams].sort())===JSON.stringify([...b.searchParams].sort());}catch{return false;}}
if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',()=>{
  if(document.body?.dataset.dtb3Note!=='true')return;
  let context=null;try{context=readDtb3Return(sessionStorage,location.href);}catch{}const href=dtb3BackURL(context?.pending?context:null,location.href);
  document.querySelectorAll('[data-dtb3-return]').forEach(link=>{link.href=href;});
});
if(typeof module!=='undefined')module.exports={DTB3_RETURN_KEY,dtb3ReturnContext,readDtb3Return,saveDtb3Return,dtb3BackURL,dtb3SameViewURL};
