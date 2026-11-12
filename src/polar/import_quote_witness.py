"""One owner-selected historical quote access/schema witness, no statistics."""
import argparse
import base64
from datetime import datetime,date
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

from .history_bundle import read_file,safe_root
from .gym_contract import read_ref
from .history_store import HistoryStore
from .ci_research_service import root_identity
from .import_contract import canonical,decode,sha,require,exact
from .import_raw_http import CREDENTIAL

BODY_LIMIT=1048576
HARD_SCOPE={'max_provider_GETs':1,'automatic_retries':0,'pagination_followups':0,'body_ceiling_bytes':BODY_LIMIT}


def request(value):
    exact(value,('method','URL','params'));p=value['params']
    require(value['method']=='GET' and type(value['URL']) is str and
            re.fullmatch(r'https://data\.alpaca\.markets/v2/stocks/[A-Z][A-Z0-9.]{0,15}/quotes',value['URL']), 'QUOTE_REQUEST_URL')
    exact(p,('start','end','feed','currency','asof','sort','limit'))
    require(p['feed']=='sip' and p['currency']=='USD' and p['sort']=='asc' and type(p['limit']) is int and p['limit']==10,
            'QUOTE_REQUEST_SCOPE')
    for key in ('start','end'):
        require(type(p[key]) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',p[key]),'QUOTE_REQUEST_TIME')
    first,last=(datetime.fromisoformat(p[k].replace('Z','+00:00')) for k in ('start','end'))
    require((last-first).total_seconds()==1 and first.date()==last.date(),'QUOTE_ONE_SECOND_WINDOW')
    require(type(p['asof']) is str and date.fromisoformat(p['asof']).isoformat()==p['asof'],'QUOTE_REQUEST_ASOF')
    return value


def code_binding():
    names=['import_quote_witness.py','import_quote_http.py','import_contract.py','import_raw_http.py',
           'history_bundle.py','history_store.py','gym_contract.py','ci_research_service.py']
    return {n:sha((Path(__file__).parent/n).read_bytes()) for n in names}


def scope_value(ref):
    raw=read_ref(ref);s=decode(raw)
    require(s.get('schema')=='polar.historical-quote-interface-gap/1','QUOTE_SCOPE_SCHEMA')
    req=request(s['request']);owner=decode(read_ref(s['owner_selection']))
    require(owner.get('schema')=='polar.prospective-historical-quote-schema-witness/1' and owner.get('request')==req,
            'QUOTE_OWNER_SELECTION')
    for k,v in HARD_SCOPE.items():
        require(s['hard_scope'][k]==v and owner['hard_scope'][k]==v,'QUOTE_HARD_SCOPE')
    slots=s['slots'];require(type(slots) is list and len(slots)==36,'QUOTE_SLOT_COUNT')
    require(all(type(x) is dict and set(x)=={'date','symbol','status'} for x in slots),'QUOTE_SLOT_SCHEMA')
    require(len({(x['date'],x['symbol']) for x in slots})==36 and len({x['date'] for x in slots})==12 and
            len({x['symbol'] for x in slots})==3,'QUOTE_SLOT_GRID')
    dates={date.fromisoformat(x['date']).isoformat() for x in slots};symbols={x['symbol'] for x in slots}
    require({(d,z) for d in dates for z in symbols}=={(x['date'],x['symbol']) for x in slots},'QUOTE_SLOT_GRID')
    symbol=req['URL'].split('/')[-2];selected=[x for x in slots if x['status']=='PENDING_INTERFACE']
    require(selected==[{'date':req['params']['start'][:10],'symbol':symbol,'status':'PENDING_INTERFACE'}] and
            sum(x['status']=='NOT_REQUESTED' for x in slots)==35,'QUOTE_ONE_SELECTED_SLOT')
    return s


def prepare(seed,store):
    exact(seed,('schema','mode','scope_ref','code_revision','runtime_image_id','qualification_ref','review_ref'))
    require(seed['schema']=='polar.quote-witness-seed/1' and seed['mode'] in ('INVENTED','RETAINED'),'QUOTE_SEED')
    scope_value(seed['scope_ref'])
    require(re.fullmatch('[a-f0-9]{40}',seed['code_revision']) and re.fullmatch('sha256:[a-f0-9]{64}',seed['runtime_image_id']),
            'QUOTE_SOURCE_RUNTIME')
    if seed['mode']=='RETAINED':
        qualification_raw=read_ref(seed['qualification_ref']);qualification=decode(qualification_raw)
        require(qualification.get('schema')=='polar.ci-result/1' and qualification.get('status')=='PASS' and
                qualification.get('candidate_sha')==seed['code_revision'] and qualification.get('selection')==['tests'],
                'QUOTE_QUALIFICATION_BINDING')
        review=decode(read_ref(seed['review_ref']))
        require(type(review) is dict and set(review)=={'schema','disposition','role','independent','author_id','reviewer_id',
                'candidate_sha','scope_sha256','qualification_sha256','report_ref'},'QUOTE_REVIEW_SCHEMA')
        require(review['schema']=='polar.quote-witness-technical-disposition/1' and review['disposition']=='PASS' and
                review['role']=='INDEPENDENT_TECHNICAL_QA' and review['independent'] is True and
                review['author_id']=='platform-engineer@polar-rig' and type(review['reviewer_id']) is str and
                re.fullmatch(r'[A-Za-z0-9._-]+@[A-Za-z0-9._-]+',review['reviewer_id']) and
                review['reviewer_id']!=review['author_id'],'QUOTE_INDEPENDENT_REVIEW_REQUIRED')
        require(review['candidate_sha']==seed['code_revision'] and review['scope_sha256']==seed['scope_ref']['sha256'] and
                review['qualification_sha256']==sha(qualification_raw),'QUOTE_REVIEW_BINDING')
        read_ref(review['report_ref'])
    return {**seed,'schema':'polar.quote-witness-config/1','code':code_binding(),'artifact_root_identity':root_identity(store.root)}


class HttpTransport:
    synthetic=False
    def get(self,req):
        child=subprocess.Popen([sys.executable,'-m','polar.import_quote_http'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        try:out,_=child.communicate(canonical({'request':req,'credential_reference':str(CREDENTIAL)}),timeout=45)
        except subprocess.TimeoutExpired:
            child.kill();child.communicate(timeout=3)
            return {'status':None,'headers':{},'body':b'','truncated':False,'error':'TIMEOUT_CHILD_OUTPUT_UNAVAILABLE'}
        if child.returncode!=0:
            return {'status':None,'headers':{},'body':b'','truncated':False,'error':'TRANSPORT_CHILD_FAILED_NO_RETRY'}
        require(len(out)<=2*BODY_LIMIT,'QUOTE_CHILD_BOUND');result=decode(out)
        result['body']=base64.b64decode(result['body'],validate=True)
        return result


class Number(str):pass


def observe(response):
    """Observe types/lexemes only. No bid/ask arithmetic or price selection."""
    body=response['body']
    result={'http_status':response['status'],'transport_error':response['error'],
            'body_bytes':len(body),'body_sha256':sha(body),'capture_truncated':response['truncated'],
            'historical_available_at':None,'event_clock':'SOURCE_TIMESTAMP_TOKEN_NOT_CAPTURE_RECEIPT',
            'price_basis':'PROVIDER_QUOTE_SOURCE_UNITS_UNCALIBRATED_NOT_ADJUSTED_REFERENCE_UNITS',
            'schema_observation':'UNAVAILABLE','quotes':None,'cursor':None}
    if response['truncated']:result['status']='BODY_CEILING_COMPLETENESS_UNKNOWN_NO_RETRY';return result
    if response['error']:result['status']='TRANSPORT_ERROR_NO_RETRY';return result
    if response['status']!=200:result['status']='HTTP_ERROR_NO_RETRY';return result
    def pairs(items):
        d={}
        for key,value in items:
            require(key not in d,'QUOTE_DUPLICATE_JSON_KEY');d[key]=value
        return d
    try:
        value=json.loads(body,parse_float=Number,parse_int=Number,parse_constant=lambda x:(_ for _ in ()).throw(ValueError()),object_pairs_hook=pairs)
        require(type(value) is dict and type(value.get('quotes')) is list and len(value['quotes'])<=10,'QUOTE_RESPONSE_SCHEMA')
        cursor=value.get('next_page_token');require(cursor is None or type(cursor) is str,'QUOTE_CURSOR_SCHEMA')
        nodes=0
        def typed(v):
            nonlocal nodes
            nodes+=1;require(nodes<=4096,'QUOTE_SCHEMA_OBSERVATION_BOUND')
            if isinstance(v,Number):return {'type':'number','lexical_token':str(v)}
            if v is None:return {'type':'null','value':None}
            if type(v) is bool:return {'type':'boolean','value':v}
            if type(v) is str:return {'type':'string','value':v}
            if type(v) is list:
                require(len(v)<=64,'QUOTE_SCHEMA_ARRAY_BOUND')
                return {'type':'array','items':[typed(x) for x in v]}
            require(type(v) is dict and len(v)<=64,'QUOTE_ROW_FIELD_BOUND')
            return {'type':'object','fields':{k:typed(x) for k,x in v.items()}}
        quotes=[typed(row) for row in value['quotes']]
        require(all(type(row) is dict for row in value['quotes']),'QUOTE_ROW_SCHEMA')
        result.update(status='PARTIAL_NO_FOLLOWUP' if cursor is not None else 'EMPTY' if not quotes else 'SCHEMA_OBSERVED',
                      schema_observation='OBSERVED_NO_ECONOMIC_VALIDATION',quotes=quotes,cursor=cursor,
                      row_count=len(quotes),envelope_fields={k:typed(v) for k,v in value.items() if k!='quotes'})
    except Exception:
        result.update(status='SCHEMA_UNEXPECTED_NO_RETRY',schema_observation='UNAVAILABLE')
    return result


def execute(config,store,transport=None):
    seed={k:v for k,v in config.items() if k not in ('code','artifact_root_identity')};seed['schema']='polar.quote-witness-seed/1'
    require(config==prepare(seed,store),'QUOTE_CONFIG_BINDING')
    scope=scope_value(config['scope_ref']);req=scope['request'];synthetic=config['mode']=='INVENTED'
    if synthetic:require(transport is not None and getattr(transport,'synthetic',False) is True,'QUOTE_FIXTURE_NO_NETWORK')
    else:
        require(transport is None and platform.system()=='Linux' and platform.python_version()=='3.13.18' and
                os.environ.get('POLAR_RUNTIME_IMAGE_ID')==config['runtime_image_id'] and sys.pycache_prefix is not None and
                os.environ.get('PYTHONDONTWRITEBYTECODE')=='1','QUOTE_ACTUAL_RUNTIME')
        transport=HttpTransport()
    family=sha(canonical({'owner_selection':scope['owner_selection']['sha256'],'request':req}))
    parent=('imports-quote-witness-invented/' if synthetic else 'imports-quote-witness-retained/')+family
    with store.locked():
        require(not (store.root/parent).exists(),'QUOTE_REQUEST_ALREADY_RECORDED_NO_RETRY')
        require(store.used()+8*BODY_LIMIT<=store.limit,'QUOTE_CAPTURE_STORAGE_RESERVE')
        start={'schema':'polar.quote-witness-start/1','config':config,'request':req,'started_ns':str(time.time_ns()),
               'max_GETs':1,'automatic_retries':0,'pagination_followups':0}
        store._publish(parent,'start',{'record.json':canonical(start)})
    # From this point, any interruption is an unknown attempted GET, never a free retry.
    try:response=transport.get(req)
    except Exception:response={'status':None,'headers':{},'body':b'','truncated':False,'error':'TRANSPORT_EXCEPTION_NO_RETRY'}
    received=str(time.time_ns());require(type(response['body']) is bytes and len(response['body'])<=BODY_LIMIT,'QUOTE_BODY_BOUND')
    response['truncated']=bool(response['truncated'] or len(response['body'])>=BODY_LIMIT)
    # Publish raw evidence before optional schema decoding. Keep only bounded private body.
    with store.locked():
        store._publish(parent,'response',{'body.bin':response['body'],'receipt.json':canonical({k:v for k,v in response.items() if k!='body'}|{'received_ns':received})},file_limit=4*BODY_LIMIT)
    observation=observe(response)
    slots=[{**x,'status':observation['status'] if x['status']=='PENDING_INTERFACE' else 'NOT_REQUESTED'} for x in scope['slots']]
    result={'schema':'polar.quote-witness-result/1','family':family,'mode':config['mode'],'status':observation['status'],
            'request':req,'slots':slots,'observation':observation,'started_ns':start['started_ns'],'received_ns':received,
            'provider_GET_attempts_conservative_debit':0 if synthetic else 1,'actual_provider_GETs':0 if synthetic else 1 if response['status'] is not None else None,'transport_attempts':1,'retries':0,'pagination_followups':0,
            'scientific_model_native_calls':0,'cost_calibration':'NOT_ESTIMATED','historical_available_at':None,
            'raw_body_path':parent+'/response/body.bin','scope':'ACCESS_SCHEMA_WITNESS_ONLY_NOT_AUCTION_SPREAD_OR_COST_ESTIMATE'}
    with store.locked():store._publish(parent,'finish',{'record.json':canonical(result)},file_limit=4*BODY_LIMIT)
    return {'status':result['status'],'family':family,'result_path':str(store.root/parent/'finish/record.json'),
            'result_sha256':sha(canonical(result)),'provider_GET_attempts_conservative_debit':result['provider_GET_attempts_conservative_debit'],'actual_provider_GETs':result['actual_provider_GETs']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['prepare','execute']);p.add_argument('file',type=Path)
    p.add_argument('--artifact-root',required=True,type=Path);p.add_argument('--storage-bytes',type=int,default=16*BODY_LIMIT)
    a=p.parse_args();require(a.artifact_root.is_absolute() and a.artifact_root.is_dir(),'QUOTE_ARTIFACT_ROOT')
    store=HistoryStore(safe_root(a.artifact_root),a.storage_bytes);value=decode(read_file(a.file.parent,a.file.name,2*BODY_LIMIT))
    result=prepare(value,store) if a.action=='prepare' else execute(value,store)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
