"""Finite real transport or explicit invented fixtures; no credential fallback."""
import base64
import subprocess
import sys
import time

from .import_contract import MAX_RESPONSE, canonical, decode, require, sha


class Clock:
    synthetic = False
    def now(self): return time.time()
    def monotonic(self): return time.monotonic()
    def sleep(self,seconds): time.sleep(seconds)


class FixtureClock:
    synthetic = True
    def __init__(self,start): self.value = float(start)
    def now(self): return self.value
    def monotonic(self): return self.value
    def sleep(self,seconds): self.value += seconds


class HttpTransport:
    synthetic = False
    def post(self,requests,index,timeout):
        try:
            child = subprocess.run([sys.executable,"-m","polar.import_http"],input=canonical(requests),
                                   capture_output=True,timeout=timeout,check=False)
        except subprocess.TimeoutExpired:
            return {"status":None,"headers":{},"body":b"","truncated":False,"error":"TIMEOUT"}
        if child.returncode:
            return {"status":None,"headers":{},"body":b"","truncated":False,"error":"TRANSPORT_CHILD_FAILED"}
        require(len(child.stdout)<=4*1024**2,"IMPORT_TRANSPORT_LIMIT")
        result = decode(child.stdout)
        result["body"] = base64.b64decode(result["body"],validate=True)
        require(len(result["body"])<=MAX_RESPONSE,"IMPORT_RESPONSE_LIMIT")
        return result


class FixtureTransport:
    synthetic = True
    def __init__(self,fixture,clock):
        require(type(fixture) is dict and set(fixture)=={"schema","start_seconds","responses"} and
                fixture["schema"]=="polar.import-fixture/1" and type(fixture["responses"]) is list)
        self.fixture,self.clock = fixture,clock
    def post(self,requests,index,timeout):
        require(index<len(self.fixture["responses"]),"IMPORT_FIXTURE_EXHAUSTED")
        item = self.fixture["responses"][index]
        require(type(item) is dict and set(item)<={"status","headers","body","error","duration_seconds"})
        duration = item.get("duration_seconds",0)
        require(type(duration) in (int,float) and duration>=0)
        self.clock.sleep(min(duration,timeout))
        if duration>timeout:
            return {"status":None,"headers":{},"body":b"","truncated":False,"error":"TIMEOUT"}
        body = item.get("body",[])
        raw = body.encode() if isinstance(body,str) else canonical(body)
        return {"status":item.get("status",200),"headers":{"content-type":"application/json",**item.get("headers",{})},"body":raw[:MAX_RESPONSE],
                "truncated":len(raw)>MAX_RESPONSE,"error":item.get("error")}
