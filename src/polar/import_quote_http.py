"""One bounded quote GET child, fixed host/path, no retries or redirects."""
import base64
import http.client
import ssl
import sys
from urllib.parse import urlencode,urlsplit
from .import_contract import decode,canonical,exact,require
from .history_bundle import read_file,safe_root
from .import_raw_http import CREDENTIAL
from .import_quote_witness import request,BODY_LIMIT


def main():
    value=decode(sys.stdin.buffer.read(16385));exact(value,('request','credential_reference'))
    req=request(value['request']);require(value['credential_reference']==str(CREDENTIAL),'QUOTE_CREDENTIAL_REFERENCE')
    credential=decode(read_file(safe_root(CREDENTIAL.parent),CREDENTIAL.name,16384))
    headers={'Accept':'application/json','User-Agent':'Polar-quote-schema-witness/1'}
    for key,field in [('APCA-API-KEY-ID','key_id'),('APCA-API-SECRET-KEY','secret_key')]:
        token=credential[field];require(type(token) is str and 0<len(token)<=4096 and all(32<ord(c)<127 for c in token),'QUOTE_CREDENTIAL_SHAPE')
        headers[key]=token
    conn=http.client.HTTPSConnection('data.alpaca.markets',timeout=40,context=ssl.create_default_context())
    body=b'';status=None;kept={};error=None
    try:
        conn.request('GET',urlsplit(req['URL']).path+'?'+urlencode(req['params']),headers=headers)
        response=conn.getresponse();status=response.status
        kept={k.lower():v for k,v in response.getheaders() if k.lower() in
              ('content-type','retry-after','x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset')}
        while len(body)<BODY_LIMIT:
            chunk=response.read(min(65536,BODY_LIMIT-len(body)))
            if not chunk:break
            body+=chunk
    except http.client.IncompleteRead as exc:
        body+=(exc.partial or b'')[:BODY_LIMIT-len(body)];error='INCOMPLETE_RESPONSE_NO_RETRY'
    except (OSError,http.client.HTTPException):error='CONNECTION_ERROR_NO_RETRY'
    finally:conn.close()
    sys.stdout.buffer.write(canonical({'status':status,'headers':kept,'body':base64.b64encode(body).decode(),
        'truncated':len(body)>=BODY_LIMIT,'error':error}))


if __name__=='__main__':
    try:main()
    except BaseException:raise SystemExit(1) from None
