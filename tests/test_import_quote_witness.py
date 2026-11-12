"""Invented one-shot quote schema/access receipts; never live credentials/provider."""
import io,json
from pathlib import Path
import pytest
from polar.import_quote_witness import prepare,execute,observe,request,HttpTransport,BODY_LIMIT
from polar.import_contract import canonical,ImportError,sha
from polar.history_store import HistoryStore


def ref(path,value):
    raw=canonical(value);path.write_bytes(raw)
    return {'path':str(path),'sha256':sha(raw),'bytes':len(raw)}


def fixture(tmp_path):
    root=tmp_path/'store';root.mkdir();store=HistoryStore(root,16*BODY_LIMIT)
    req={'method':'GET','URL':'https://data.alpaca.markets/v2/stocks/AAA/quotes',
         'params':{'start':'2000-01-01T20:59:59Z','end':'2000-01-01T21:00:00Z','feed':'sip','currency':'USD','asof':'2001-01-01','sort':'asc','limit':10}}
    hard={'max_provider_GETs':1,'automatic_retries':0,'pagination_followups':0,'body_ceiling_bytes':BODY_LIMIT}
    owner=ref(tmp_path/'owner.json',{'schema':'polar.prospective-historical-quote-schema-witness/1','request':req,'hard_scope':hard})
    slots=[{'date':f'2000-{i+1:02d}-01','symbol':s,'status':'PENDING_INTERFACE' if i==0 and s=='AAA' else 'NOT_REQUESTED'} for i in range(12) for s in ['AAA','BBB','CCC']]
    scope=ref(tmp_path/'scope.json',{'schema':'polar.historical-quote-interface-gap/1','owner_selection':owner,'request':req,'hard_scope':hard,'slots':slots})
    seed={'schema':'polar.quote-witness-seed/1','mode':'INVENTED','scope_ref':scope,'code_revision':'a'*40,
          'runtime_image_id':'sha256:'+'b'*64,'qualification_ref':None,'review_ref':None}
    return store,prepare(seed,store),req


class Mock:
    synthetic=True
    def __init__(self,body=b'{"quotes":[],"next_page_token":null}',status=200,error=None,truncated=False):
        self.reply={'status':status,'headers':{'content-type':'application/json'},'body':body,'error':error,'truncated':truncated};self.calls=[]
    def get(self,req):self.calls.append(req);return self.reply


@pytest.mark.parametrize('body,status,error,expected',[
    (b'{"quotes":[],"next_page_token":null}',200,None,'EMPTY'),
    (b'{"quotes":[],"next_page_token":"next"}',200,None,'PARTIAL_NO_FOLLOWUP'),
    (b'{"message":"no historical SIP access"}',403,None,'HTTP_ERROR_NO_RETRY'),
    (b'{"quotes":',200,None,'SCHEMA_UNEXPECTED_NO_RETRY'),
    (b'',None,'TIMEOUT','TRANSPORT_ERROR_NO_RETRY'),
    (b'{"quotes":[],"quotes":[]}',200,None,'SCHEMA_UNEXPECTED_NO_RETRY'),
])
def test_all_terminal_outcomes_preserve_raw_one_attempt_and_35_unrequested(tmp_path,body,status,error,expected):
    store,cfg,req=fixture(tmp_path);transport=Mock(body,status,error)
    result=execute(cfg,store,transport);assert len(transport.calls)==1 and transport.calls[0]==req
    saved=json.loads(Path(result['result_path']).read_bytes());assert saved['status']==expected
    assert sum(x['status']=='NOT_REQUESTED' for x in saved['slots'])==35
    assert saved['provider_GET_attempts_conservative_debit']==saved['actual_provider_GETs']==0
    assert saved['historical_available_at'] is None and saved['cost_calibration']=='NOT_ESTIMATED'
    assert (store.root/saved['raw_body_path']).read_bytes()==body
    assert int(saved['received_ns'])>=int(saved['started_ns'])
    with pytest.raises(ImportError,match='ALREADY_RECORDED'):execute(cfg,store,transport)
    assert len(transport.calls)==1


def test_lexical_numbers_conditions_and_nanos_preserved_without_statistics(tmp_path):
    store,cfg,_=fixture(tmp_path)
    raw=b'{"symbol":"AAA","quotes":[{"t":"2000-01-01T20:59:59.123456789Z","bp":100.0100,"ap":1.0002e2,"bs":1,"as":0,"c":["R"]}],"next_page_token":null}'
    answer=execute(cfg,store,Mock(raw));saved=json.loads(Path(answer['result_path']).read_bytes());o=saved['observation']
    fields=o['quotes'][0]['fields'];assert fields['bp']=={'type':'number','lexical_token':'100.0100'}
    assert fields['ap']['lexical_token']=='1.0002e2' and fields['t']['value'].endswith('.123456789Z')
    assert fields['c']['items']==[{'type':'string','value':'R'}] and o['row_count']==1
    assert not {'spread','mid','median','cost_estimate'}&set(o)


def test_bound_body_retains_ceiling_and_unknown_completeness(tmp_path):
    store,cfg,_=fixture(tmp_path);raw=b' '*BODY_LIMIT
    answer=execute(cfg,store,Mock(raw));assert answer['status']=='BODY_CEILING_COMPLETENESS_UNKNOWN_NO_RETRY'
    saved=json.loads(Path(answer['result_path']).read_bytes());assert (store.root/saved['raw_body_path']).stat().st_size==BODY_LIMIT


def test_fixture_cannot_fall_through_or_widen_owner_request(tmp_path):
    store,cfg,req=fixture(tmp_path)
    with pytest.raises(ImportError,match='FIXTURE_NO_NETWORK'):execute(cfg,store)
    with pytest.raises(ImportError,match='FIXTURE_NO_NETWORK'):execute(cfg,store,HttpTransport())
    assert not list(store.root.glob('imports-quote-witness-*'))
    for key,value in [('limit',11),('feed','iex'),('end','2000-01-01T21:00:01Z')]:
        bad={**req,'params':{**req['params'],key:value}}
        with pytest.raises(ImportError):request(bad)


def test_interruption_keeps_started_unknown_attempt_and_never_retries(tmp_path):
    store,cfg,_=fixture(tmp_path)
    class Interrupted(Mock):
        def get(self,req):raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):execute(cfg,store,Interrupted())
    assert len(list(store.root.rglob('start/record.json')))==1
    with pytest.raises(ImportError,match='ALREADY_RECORDED'):execute(cfg,store,Mock())


def test_http_child_one_get_fixed_path_no_redirect_or_pagination(monkeypatch):
    import polar.import_quote_http as child
    req={'method':'GET','URL':'https://data.alpaca.markets/v2/stocks/AAA/quotes','params':{'start':'2000-01-01T20:59:59Z','end':'2000-01-01T21:00:00Z','feed':'sip','currency':'USD','asof':'2001-01-01','sort':'asc','limit':10}}
    wire=canonical({'request':req,'credential_reference':str(child.CREDENTIAL)});out=io.BytesIO();calls=[]
    class Stream:
        status=403
        def getheaders(self):return [('content-type','application/json'),('location','https://elsewhere.invalid')]
        def read(self,n):return b''
    class Connection:
        def __init__(self,host,**kw):assert host=='data.alpaca.markets'
        def request(self,*a,**k):calls.append((a,k))
        def getresponse(self):return Stream()
        def close(self):calls.append('CLOSED')
    monkeypatch.setattr(child.http.client,'HTTPSConnection',Connection)
    monkeypatch.setattr(child,'read_file',lambda *a:canonical({'key_id':'INVENTED_KEY','secret_key':'INVENTED_SECRET'}))
    monkeypatch.setattr(child,'safe_root',lambda p:p)
    monkeypatch.setattr(child.sys,'stdin',type('Input',(),{'buffer':io.BytesIO(wire)})())
    monkeypatch.setattr(child.sys,'stdout',type('Output',(),{'buffer':out})())
    child.main();response=json.loads(out.getvalue())
    assert response['status']==403 and 'location' not in response['headers']
    assert len(calls)==2 and calls[-1]=='CLOSED'
    assert calls[0][0][0]=='GET' and calls[0][0][1].startswith('/v2/stocks/AAA/quotes?') and 'page_token' not in calls[0][0][1]
