"""Fixed anonymous read-only mapping POST child, bounded/killed by the caller deadline."""
import base64
import http.client
import json
import ssl
import sys

from .import_contract import MAX_RESPONSE, canonical, decode, require, validate_request


def main():
    requests = decode(sys.stdin.buffer.read(16385))
    require(type(requests) is list and 1<=len(requests)<=10)
    for item in requests: validate_request(item)
    connection = http.client.HTTPSConnection("api.openfigi.com",timeout=45,context=ssl.create_default_context())
    try:
        connection.request("POST","/v3/mapping",body=canonical(requests),
                           headers={"Content-Type":"application/json","Accept":"application/json",
                                    "User-Agent":"Polar-resumable-import/1"})
        response = connection.getresponse()
        body = response.read(MAX_RESPONSE+1)
        headers = {k.lower():v for k,v in response.getheaders() if k.lower().startswith("ratelimit-") or
                   k.lower() in ("retry-after","content-type")}
        result = {"status":response.status,"headers":headers,"body":base64.b64encode(body[:MAX_RESPONSE]).decode(),
                  "truncated":len(body)>MAX_RESPONSE,"error":None}
    except (OSError,http.client.HTTPException):
        result = {"status":None,"headers":{},"body":"","truncated":False,"error":"CONNECTION_ERROR"}
    finally:
        connection.close()
    sys.stdout.buffer.write(canonical(result))


if __name__ == "__main__":
    main()
