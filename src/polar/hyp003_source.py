"""Finite descriptor-safe local producer reads; no transport or acquisition."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .codec import canonical,digest
from .history_bundle import relative,safe_root

CONFIG_LIMIT=64*1024
MANIFEST_LIMIT=1024**2
JSON_LIMIT=32*1024**2
NDJSON_LIMIT=128*1024**2
LINE_LIMIT=256*1024
TOTAL_LIMIT=512*1024**2
RAW='polar.partial-raw-pv-source-content/1'
MULTIYEAR='polar.multiyear-source-content/1'
METADATA='polar.current-class-roster-content/1'
SAMPLE='polar.current-class-sample-content/1'

class PreparationError(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)

def check(ok,code='HYP003_INVALID_CONFIG'):
    if not ok:raise PreparationError(code)

def hash_value(v):
    check(type(v) is str and re.fullmatch('[a-f0-9]{64}',v),'HYP003_INVALID_HASH');return v

def decode(raw):
    def pairs(items):
        result={}
        for key,value in items:
            check(key not in result,'HYP003_DUPLICATE_JSON_KEY');result[key]=value
        return result
    def token(s):
        check(len(s)<=256,'HYP003_NUMERIC_TOKEN_LIMIT');return s
    try:
        value=json.loads(raw,object_pairs_hook=pairs,parse_float=token,
                         parse_constant=lambda _:check(False,'HYP003_NONFINITE_JSON'))
        stack=[(value,0)]
        while stack:
            node,depth=stack.pop();check(depth<=64,'HYP003_JSON_DEPTH')
            if isinstance(node,dict):stack.extend((v,depth+1) for v in node.values())
            elif isinstance(node,list):stack.extend((v,depth+1) for v in node)
        return value
    except (ValueError,UnicodeError,RecursionError) as exc:
        if isinstance(exc,PreparationError):raise
        raise PreparationError('HYP003_INVALID_JSON') from None

@contextmanager
def member_stream(root,name,limit):
    opened=[]
    try:
        root=safe_root(root);parts=relative(name).split('/')
        opened.append(os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW))
        for part in parts[:-1]:opened.append(os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=opened[-1]))
        fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=opened[-1])
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno());check(stat.S_ISREG(info.st_mode) and info.st_size<=limit,'HYP003_MEMBER_LIMIT_OR_TYPE')
            yield stream
    except OSError:raise PreparationError('HYP003_UNSAFE_OR_MISSING_FILE') from None
    finally:
        for fd in reversed(opened):os.close(fd)

class Sources:
    def __init__(self):self.total=0;self.physical_bytes=0;self.infos=[];self.physical=[]
    def read(self,root,name,limit,expected=None):
        ndjson=name.endswith('.ndjson');hasher=hashlib.sha256();size=0;chunks=[];rows=[]
        with member_stream(root,name,limit) as stream:
            if ndjson:
                while True:
                    raw=stream.readline(LINE_LIMIT+1)
                    if not raw:break
                    check(len(raw)<=LINE_LIMIT,'HYP003_LINE_LIMIT');hasher.update(raw);size+=len(raw)
                    check(size<=limit and size+self.total<=TOTAL_LIMIT and len(rows)<1000000,'HYP003_MEMBER_LIMIT_OR_ROWS')
                    row=decode(raw);check(type(row) is dict,'HYP003_NDJSON_ROW_SCHEMA');rows.append(row)
            else:
                while True:
                    raw=stream.read(1024**2)
                    if not raw:break
                    size+=len(raw);check(size<=limit and size+self.total<=TOTAL_LIMIT,'HYP003_MEMBER_LIMIT_OR_TYPE');hasher.update(raw);chunks.append(raw)
        self.total+=size;check(self.total<=TOTAL_LIMIT,'HYP003_TOTAL_INPUT_LIMIT')
        h=hasher.hexdigest()
        if expected is not None:
            check(h==hash_value(expected['sha256']) and ('bytes' not in expected or type(expected['bytes']) is int and size==expected['bytes']),'HYP003_MEMBER_HASH_OR_LENGTH')
        content=rows if ndjson else b''.join(chunks)
        if not ndjson and name.endswith('.json'):decode(content)
        return content,{'sha256':h,'bytes':size}
    def add(self,entry,primary,*,allow_multiyear=False):
        check(type(entry) is dict and set(entry)<={'adapter','directory','manifest','manifest_sha256','receipt'} and
              {'adapter','directory','manifest_sha256'}<=set(entry),'HYP003_INVALID_INPUT_REFERENCE')
        schema=entry['adapter'];allowed=(RAW,METADATA)+((MULTIYEAR,) if allow_multiyear else ()) if primary else (METADATA,SAMPLE)
        check(schema in allowed,'HYP003_UNSUPPORTED_ADAPTER')
        directory=Path(entry['directory']);check(directory.is_absolute(),'HYP003_ABSOLUTE_ROOT_REQUIRED')
        name=relative(entry.get('manifest','content-manifest.json'))
        raw,ref=self.read(directory,name,MANIFEST_LIMIT,{'sha256':entry['manifest_sha256']});manifest=decode(raw)
        check(type(manifest) is dict and manifest.get('schema')==schema and type(manifest.get('objects')) is dict,'HYP003_PRODUCER_SCHEMA')
        check(1<=len(manifest['objects'])<=4096,'HYP003_MEMBER_COUNT')
        for old in self.infos:
            if old['directory']==str(directory):
                check(old['ref']==ref and old['manifest_name']==name,'HYP003_ROOT_BINDING_CONFLICT');old['primary']|=primary;return old
        prefix=Path(name).parent;files={};inventory={}
        for member,info in sorted(manifest['objects'].items()):
            check(type(info) is dict and set(info)=={'bytes','sha256'} and type(info['bytes']) is int and info['bytes']>=0,'HYP003_MEMBER_REFERENCE')
            key=str(prefix/relative(member));limit=NDJSON_LIMIT if member.endswith('.ndjson') else JSON_LIMIT
            check(info['bytes']<=limit,'HYP003_DECLARED_MEMBER_LIMIT')
            value,verified=self.read(directory,key,limit,info);files[key]=value;inventory[member]=verified
        info={'directory':str(directory),'manifest_name':name,'manifest':manifest,'ref':ref,'files':files,
              'inventory':inventory,'prefix':prefix,'primary':primary}
        self.infos.append(info)
        physical={'directory':str(directory),'manifest':name,'manifest_sha256':ref['sha256']}
        if 'receipt' in entry:
            receipt=entry['receipt'];check(type(receipt) is dict and set(receipt)=={'path','sha256'},'HYP003_RECEIPT_REFERENCE')
            body,receipt_ref=self.read(directory,relative(receipt['path']),MANIFEST_LIMIT,receipt)
            decode(body);self.physical_bytes+=receipt_ref['bytes'];physical['receipt']={**receipt_ref,'path':receipt['path']}
        self.physical.append(physical);return info

def object_value(info,name):
    key=str(info['prefix']/name);check(key in info['files'],'HYP003_REQUIRED_MEMBER_MISSING')
    value=info['files'][key];return decode(value) if isinstance(value,bytes) else value

def valid_clock(value):
    if not isinstance(value,str) or len(value)>64:return False
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).tzinfo is not None
    except ValueError:return False
