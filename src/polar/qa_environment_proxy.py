"""Task-owned liveness relay: fixed internal upstream, two read-only routes."""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import re

LIMIT=1024*1024
ROUTES=('/livez','/openapi.json')


def fetch(upstream,path):
    if not re.fullmatch(r'polar-qa-[a-f0-9]{32}-api',upstream):raise ValueError('INVALID_UPSTREAM')
    if path not in ROUTES:raise ValueError('ROUTE_NOT_PREPARED')
    connection=http.client.HTTPConnection(upstream,8000,timeout=2)
    try:
        connection.request('GET',path,headers={'Accept':'application/json','Connection':'close'})
        response=connection.getresponse()
        body=response.read(LIMIT+1)
        if len(body)>LIMIT:raise ValueError('BODY_BOUND')
        content_type=response.getheader('Content-Type','application/json')
        if '\r' in content_type or '\n' in content_type:raise ValueError('INVALID_CONTENT_TYPE')
        return response.status,body,content_type
    finally:connection.close()


class Handler(BaseHTTPRequestHandler):
    timeout=2

    def log_message(self,*args):pass

    def do_GET(self):
        if self.path not in ROUTES:
            self.send_error(404,'ROUTE_NOT_PREPARED');return
        try:status,body,content_type=fetch(self.server.upstream,self.path)
        except (OSError,ValueError,http.client.HTTPException):
            self.send_error(502,'UPSTREAM_UNAVAILABLE');return
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream',required=True);args=parser.parse_args()
    if not re.fullmatch(r'polar-qa-[a-f0-9]{32}-api',args.upstream):raise SystemExit('INVALID_UPSTREAM')
    server=HTTPServer(('0.0.0.0',8000),Handler);server.timeout=2
    server.upstream=args.upstream
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':main()
