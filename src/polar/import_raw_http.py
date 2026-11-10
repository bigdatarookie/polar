"""Operation-only fixed HTTPS GET child. Never imported to resolve credentials."""
import base64
import http.client
from pathlib import Path
import ssl
import sys
from urllib.parse import urlencode

from .history_bundle import read_file,safe_root
from .import_contract import canonical,decode,require,exact
from .import_raw_sip import request,POLICY

CREDENTIAL=Path('/Users/garry/Documents/git/polar/.artifacts/alpaca-api-credentials.json')


def main():
    value=decode(sys.stdin.buffer.read(16385))
    exact(value,('request','cursor','timeout_seconds','credential_reference'))
    req=request(value['request'])
    require(value['credential_reference']==str(CREDENTIAL),'IMPORT_CREDENTIAL_REFERENCE')
    require(type(value['timeout_seconds']) in (int,float) and 0<value['timeout_seconds']<=45)
    cursor=value['cursor']
    require(cursor is None or type(cursor) is str and 0<len(cursor)<=4096 and all(ord(c)>=32 for c in cursor))
    credential=decode(read_file(safe_root(CREDENTIAL.parent),CREDENTIAL.name,16384))
    headers={'Accept':'application/json','User-Agent':'Polar-raw-sip-import/1'}
    for key,field in (('APCA-API-KEY-ID','key_id'),('APCA-API-SECRET-KEY','secret_key')):
        token=credential[field]
        require(type(token) is str and 0<len(token)<=4096 and all(32<ord(c)<127 for c in token),
                'IMPORT_CREDENTIAL_SHAPE')
        headers[key]=token
    params={k:v for k,v in req.items() if k!='endpoint'}
    if cursor is not None:params['page_token']=cursor
    connection=http.client.HTTPSConnection('data.alpaca.markets',timeout=value['timeout_seconds'],
                                           context=ssl.create_default_context())
    try:
        connection.request('GET','/v2/stocks/bars?'+urlencode(params),headers=headers)
        response=connection.getresponse()  # redirects are retained failures, never followed
        body=response.read(POLICY['body_bytes']+1)
        kept={k.lower():v for k,v in response.getheaders()
              if k.lower() in ('content-type','retry-after','x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset')}
        result={'status':response.status,'headers':kept,'body':base64.b64encode(body).decode(),
                'truncated':len(body)>POLICY['body_bytes'],'error':None}
    except (OSError,http.client.HTTPException):
        result={'status':None,'headers':{},'body':'','truncated':False,'error':'CONNECTION_ERROR'}
    finally:connection.close()
    sys.stdout.buffer.write(canonical(result))


if __name__=='__main__':
    # No exception messages/tracebacks containing private request context or credentials.
    try:main()
    except BaseException:raise SystemExit(1) from None
