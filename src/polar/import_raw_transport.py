"""Raw adapter transports; fixtures cannot fall through to the network."""
import base64
import subprocess
import sys

from .import_contract import canonical,decode,require
from .import_raw_sip import POLICY


class RawFixtureTransport:
    def __init__(self,fixture,clock):
        require(type(fixture) is dict and set(fixture)=={'schema','start_seconds','responses'}
                and fixture['schema']=='polar.raw-sip-fixture/1' and type(fixture['responses']) is list)
        self.fixture=fixture;self.clock=clock

    def get(self,start,index,timeout):
        require(index<len(self.fixture['responses']),'IMPORT_FIXTURE_EXHAUSTED')
        value=self.fixture['responses'][index]
        duration=value.get('duration_seconds',0)
        require(type(duration) in (int,float) and duration>=0,'IMPORT_FIXTURE_INVALID')
        self.clock.sleep(min(duration,timeout))
        if duration>timeout:return {'status':None,'headers':{},'body':b'','truncated':False,'error':'TIMEOUT'}
        body=value.get('body',{'bars':{},'next_page_token':None})
        raw=body.encode() if type(body) is str else canonical(body)
        return {'status':value.get('status',200),'headers':{'content-type':'application/json',**value.get('headers',{})},
                'body':raw[:POLICY['body_bytes']+1],'truncated':len(raw)>POLICY['body_bytes'],
                'error':value.get('error')}


class RawHttpTransport:
    def __init__(self,credential_reference,profile='first-unit'):
        self.credential_reference=credential_reference;self.profile=profile

    def get(self,start,index,timeout):
        child=subprocess.Popen([sys.executable,'-m','polar.import_raw_http'],stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        try:
            output,_=child.communicate(canonical({'request':start['request'],
                'cursor':start['request_cursor'],'timeout_seconds':timeout,
                'credential_reference':self.credential_reference,
                **({'adapter':'alpaca-all-adjusted-sip-broad100/1'} if self.profile=='all-adjusted100' else {})}),timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            try:child.communicate(timeout=2)
            except subprocess.TimeoutExpired:require(False,'IMPORT_TRANSPORT_CLEANUP_UNVERIFIED')
            return {'status':None,'headers':{},'body':b'','truncated':False,'error':'TIMEOUT'}
        require(child.returncode==0 and len(output)<=2*1024**2,'IMPORT_TRANSPORT_CHILD_FAILED')
        value=decode(output);value['body']=base64.b64decode(value['body'],validate=True)
        require(len(value['body'])<=POLICY['body_bytes']+1,'IMPORT_TRANSPORT_LIMIT')
        return value
