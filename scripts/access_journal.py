#!/usr/bin/env python3
"""Bounded append-only access notes helper. No credential lookup or network access."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

MAX_JOURNAL = 2 * 1024**2
MAX_EVENT = 8192
MAX_OUTPUT = 32768
MARKER = b'<!-- polar-access-event/'
LEGACY_SCHEMA = 'polar.access-event/1'
SCHEMA = 'polar.access-event/2'
CLASSIFICATION_FIELDS = {'episode_kind','access_problem','route_change'}
EPISODES = ('registration','login','session-recovery','credential-change','new-rights','access-problem','ordinary-operation')
ORDINARY = {'read','push','pr','review','merge','git-read','git-fetch','git-push','pr-read','pr-create','pr-review',
            'pr-merge','api-call','api-repeat','repeat-api','same-key-api-call'}
FIELDS = {'schema','event_id','utc','actor','qitem','provider','operation','purpose','alias','outcome',
          'observable_basis','attribution','new','unusual','blocking','blocker_class','method_environment',
          'session_continuity','pacing_profile','missing_tools','user_action','safe_evidence','next_checkpoint',
          'correction_ref','safe_author_assertion'}
CODES = {'actor','provider','operation','purpose','alias','observable_basis','method_environment',
         'session_continuity','pacing_profile','missing_tools','user_action','next_checkpoint'}


class JournalError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise JournalError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',',':')).encode()


def pairs(items):
    result = {}
    for key,value in items:
        require(key not in result, 'INVALID_EVENT')
        result[key]=value
    return result


def decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(JournalError('INVALID_EVENT')))
    except (ValueError, UnicodeError, RecursionError):
        raise JournalError('INVALID_EVENT') from None


def event_id(value):
    return type(value) is str and bool(re.fullmatch(r'ACCESS-[A-Z0-9][A-Z0-9-]{0,90}', value)) and not re.search(r'PASSWORD|SECRET|COOKIE|TOKEN|SENTINEL',value)


def safe_code(value):
    # Deliberately codes, not arbitrary prose or "redacted" payloads. Author still owns meaning.
    return (type(value) is str and bool(re.fullmatch(r'[a-z][a-z0-9_-]{0,95}',value)) and
            not re.search(r'password|secret|cookie|token|credential|sentinel|api_key',value,re.I))


def validate(event):
    require(type(event) is dict, 'INVALID_EVENT')
    schema=event.get('schema')
    require(schema in (LEGACY_SCHEMA,SCHEMA), 'INVALID_EVENT')
    require(set(event)==(FIELDS|CLASSIFICATION_FIELDS if schema==SCHEMA else FIELDS), 'INVALID_EVENT')
    require(event_id(event['event_id']), 'INVALID_EVENT')
    if schema==SCHEMA:
        require(event['episode_kind'] in EPISODES and event['access_problem'] in ('none','auth','permission','session') and
                event['route_change'] in ('none','verified-new-method','verified-clarification'), 'INVALID_EVENT')
    require(type(event['utc']) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',event['utc']), 'INVALID_EVENT')
    try:
        datetime.strptime(event['utc'],'%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        raise JournalError('INVALID_EVENT') from None
    require(all(safe_code(event[k]) for k in CODES), 'UNSAFE_EVENT_FIELD')
    require(type(event['qitem']) is str and re.fullmatch(r'qitem-[0-9]{14}-[a-f0-9]{8,32}',event['qitem']), 'INVALID_EVENT')
    require(event['outcome'] in ('success','partial','blocked','failed','unknown_effect') and
            event['attribution'] in ('observed','reported','independently_verified') and
            event['blocker_class'] in ('none','control','form','session','access','entitlement','rights','human','unknown'), 'INVALID_EVENT')
    require(all(type(event[k]) is bool for k in ('new','unusual','blocking')) and event['safe_author_assertion'] is True,
            'INVALID_EVENT')
    require(event['blocking'] == (event['blocker_class']!='none'), 'INVALID_EVENT')
    require(event['correction_ref'] is None or event_id(event['correction_ref']), 'INVALID_EVENT')
    refs=event['safe_evidence']
    require(type(refs) is list and 1<=len(refs)<=8, 'INVALID_EVENT')
    for ref in refs:
        require(type(ref) is str and len(ref)<=256 and all(safe_code(part) for part in ref.split('/')),
                'UNSAFE_EVENT_FIELD')
    payload=canonical(event)
    require(len(payload)<=MAX_EVENT,'EVENT_LIMIT')
    return payload


def episode_class(event):
    """Read-only classification; historical structural validity never depends on new-write policy."""
    if event['schema']==SCHEMA:
        if event['access_problem']!='none':
            return 'ACCESS_EPISODE'
        if event['operation'] in ORDINARY or event['episode_kind']=='ordinary-operation':
            return 'ORDINARY_OPERATION'
        return 'ACCESS_EPISODE' if event['episode_kind']!='access-problem' else 'UNCLASSIFIED_LEGACY'
    cues=' '.join(event[k] for k in ('operation','purpose','observable_basis','session_continuity'))
    if re.search(r'login|reauth|registration|session[-_]recover|auth[-_](?:expir|recover)|permission[-_]denied|new[-_]rights|key[-_](?:create|update)',cues):
        return 'ACCESS_EPISODE'
    if event['operation'] in ORDINARY and event['outcome']=='success' and event['blocker_class']=='none':
        return 'ORDINARY_OPERATION'
    return 'UNCLASSIFIED_LEGACY'


def write_policy(event):
    kind=episode_class(event)
    if kind=='ORDINARY_OPERATION':
        return False
    require(event['schema']==SCHEMA, 'EPISODE_CLASSIFICATION_REQUIRED')
    require(event['episode_kind']!='access-problem' or event['access_problem']!='none',
            'INVALID_EPISODE_CLASSIFICATION')
    if event['operation'] in ('route-revision','route-update'):
        require(event['route_change']!='none','UNVERIFIED_ROUTE_CHANGE')
    return True


def manual_class(part):
    """Conservative legacy heuristic, not a retrospective access verdict or a rewritten record."""
    operation=next((line for line in part.splitlines() if re.search(r'provider.*operation',line,re.I)), '')
    # Positive evidence of a genuine episode wins; merely naming a working helper does not.
    text=re.sub(r'(?i)\b(?:no|without) (?:auth|permission|session) (?:failure|problem)[^.;\n]*','',part)
    if re.search(r'(?i)\b(?:registration|signup|login|reauth)\b|session[-_ ]recovery|credential[-_ ](?:creation|update)|new[-_ ]rights|'
                 r'(?:auth(?:entication|orization)?|permission|session)[-_ ](?:failure|denied|expired|problem)|'
                 r'expired[-_ ](?:auth|authorization|session)|token[-_ ]expir',text):
        return 'ACCESS_EPISODE'
    if re.search(r'(?i)blocking\s*[=:]\s*(?:yes|true)|outcome[^\n]*\b(?:failed|denied|unknown_effect)\b',text):
        return 'UNCLASSIFIED_LEGACY'
    github='github' in operation.lower() or 'GITHUB' in part.split('\n',1)[0]
    if github and re.search(r'(?i)read|fetch|push|merge|review|\bpr[0-9]*\b',operation):
        return 'ORDINARY_OPERATION'
    return 'UNCLASSIFIED_LEGACY'


@contextmanager
def locked(path, exclusive, wait):
    require(type(wait) in (int,float) and math.isfinite(wait) and 0<=wait<=5, 'INVALID_LOCK_WAIT')
    path=Path(path).absolute()
    opened=[]
    try:
        opened.append(os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY))
        for part in path.parts[1:-1]:
            opened.append(os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=opened[-1]))
        fd=os.open(path.name,(os.O_RDWR|os.O_APPEND if exclusive else os.O_RDONLY)|os.O_NOFOLLOW|os.O_NONBLOCK,
                   dir_fd=opened[-1])
        opened.append(fd)
        info=os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'UNSAFE_JOURNAL')
        deadline=time.monotonic()+wait
        while True:
            try:
                fcntl.flock(fd,(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic()<deadline,'LOCK_TIMEOUT')
                time.sleep(min(.02,max(0,deadline-time.monotonic())))
        yield fd
    except OSError:
        raise JournalError('JOURNAL_IO_ERROR') from None
    finally:
        for fd in reversed(opened):
            os.close(fd)


def snapshot(fd):
    require(os.fstat(fd).st_size<=MAX_JOURNAL,'JOURNAL_LIMIT')
    os.lseek(fd,0,os.SEEK_SET)
    raw=b''
    while len(raw)<=MAX_JOURNAL:
        chunk=os.read(fd,min(65536,MAX_JOURNAL+1-len(raw)))
        if not chunk:break
        raw+=chunk
    require(len(raw)<=MAX_JOURNAL,'JOURNAL_LIMIT')
    try:
        raw.decode('utf-8')
    except UnicodeError:
        raise JournalError('INVALID_JOURNAL') from None
    return raw


def frame(payload):
    event=decode(payload);identity=event['event_id'].encode()
    digest=hashlib.sha256(payload).hexdigest().encode()
    return (b'\n<!-- polar-access-event/1 BEGIN '+identity+b' '+digest+b' -->\n### '+identity+
            b'\n```json\n'+payload+b'\n```\n<!-- polar-access-event/1 END '+identity+b' '+digest+b' -->\n')


def records(raw):
    pattern=rb'\n<!-- polar-access-event/1 BEGIN (ACCESS-[A-Z0-9-]+) ([a-f0-9]{64}) -->\n### \1\n```json\n([^\n]+)\n```\n<!-- polar-access-event/1 END \1 \2 -->\n'
    found={};spans=[]
    for match in re.finditer(pattern,raw):
        identity=match[1].decode();payload=match[3]
        require(hashlib.sha256(payload).hexdigest().encode()==match[2],'PARTIAL_OR_INVALID_JOURNAL')
        event=decode(payload)
        require(validate(event)==payload and event['event_id']==identity and identity not in found,
                'PARTIAL_OR_INVALID_JOURNAL')
        found[identity]=payload;spans.append(match.span())
    remainder=raw
    for start,end in reversed(spans):remainder=remainder[:start]+remainder[end:]
    # Also reject truncated marker headers; never append through a crashed own write.
    header=b'\n<!-- polar-access-event/1 BEGIN '
    require(b'<!-- polar-access' not in remainder and
            not any(remainder.endswith(header[:n]) for n in range(2,len(header))),
            'PARTIAL_OR_INVALID_JOURNAL')
    return found


def append(path,event,wait=1):
    payload=validate(event);entry=frame(payload);identity=event['event_id']
    with locked(path,True,wait) as fd:
        raw=snapshot(fd);existing=records(raw)
        headings=re.findall(rb'^### '+re.escape(identity.encode())+rb'[ \t]*\r?$',raw,re.M)
        require(len(headings)==(1 if identity in existing else 0),'EVENT_ID_CONFLICT')
        if identity in existing:
            require(existing[identity]==payload,'EVENT_ID_CONFLICT')
            return {'status':'ALREADY_PRESENT','event_id':identity}
        if not write_policy(event):
            return {'status':'SKIPPED_NON_EPISODE','event_id':identity}
        require(len(raw)+len(entry)<=MAX_JOURNAL,'JOURNAL_LIMIT')
        try:
            written=os.write(fd,entry)
            require(written==len(entry),'UNKNOWN_WRITE_EFFECT')
            os.fsync(fd)
        except OSError:
            raise JournalError('UNKNOWN_WRITE_EFFECT') from None
        return {'status':'APPENDED','event_id':identity}


def read(path,provider,recent=5,max_bytes=16384,wait=1,include_ordinary=False):
    require(type(include_ordinary) is bool and safe_code(provider) and type(recent) is int and 0<=recent<=20 and
            type(max_bytes) is int and 256<=max_bytes<=MAX_OUTPUT,'INVALID_READ_QUERY')
    with locked(path,False,wait) as fd:
        raw=snapshot(fd);own_records=records(raw)
    # Match complete ### sections, including manually authored routes. Never edit/compact them.
    text=raw.decode();sections=re.split(r'(?m)(?=^### )',text)[1:]
    matching=[];ordinary=unclassified=0
    for part in sections:
        title=part.split('\n',1)[0][4:]
        if title in own_records:
            payload=own_records[title]
            event=decode(payload)
            if event['provider']==provider:
                classification=episode_class(event)
                if classification=='ORDINARY_OPERATION':
                    ordinary+=1
                    if not include_ordinary:continue
                elif classification=='UNCLASSIFIED_LEGACY':unclassified+=1
                matching.append('### '+title+'\n```json\n'+payload.decode()+'\n```\n')
        else:
            part=re.sub(r'(?m)^<!-- polar-access-event/.* -->\n?','',part)
            if re.search(r'(?i)(?<![a-z0-9])'+re.escape(provider)+r'(?![a-z0-9])',part):
                if not part.startswith('### ROUTE-'):
                    classification=manual_class(part)
                    if classification=='ORDINARY_OPERATION':
                        ordinary+=1
                        if not include_ordinary:continue
                    elif classification=='UNCLASSIFIED_LEGACY':unclassified+=1
                matching.append(part)
    routes=[part for part in matching if part.startswith('### ROUTE-')]
    events=[part for part in matching if not part.startswith('### ROUTE-')]
    selected=routes+events[-recent:] if recent else routes
    output=[];used=0
    for part in selected:
        size=len(part.encode())
        if used+size>max_bytes:break
        output.append(part);used+=size
    return {'status':'OK','provider':provider,'journal_bytes':len(raw),'matching_routes':len(routes),
            'matching_events':len(events),'returned_sections':len(output),
            'incomplete':len(output)<len(selected) or len(events)>recent,
            'selection':'MATCHING_ROUTES_AND_LATEST_ACCESS_EPISODES' if not include_ordinary else 'MATCHING_ROUTES_AND_ALL_EVENT_KINDS',
            'include_ordinary':include_ordinary,'filtered_ordinary_events':0 if include_ordinary else ordinary,
            'unclassified_legacy_events':unclassified,'text':''.join(output)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal',required=True)
    sub=parser.add_subparsers(dest='operation',required=True)
    add=sub.add_parser('append');add.add_argument('--event-file',required=True)
    view=sub.add_parser('read');view.add_argument('--provider',required=True)
    view.add_argument('--include-ordinary',action='store_true');view.add_argument('--recent',type=int,default=5);view.add_argument('--max-bytes',type=int,default=16384)
    args=parser.parse_args()
    try:
        if args.operation=='append':
            if args.event_file=='-':raw=sys.stdin.buffer.read(MAX_EVENT+1)
            else:
                with open(args.event_file,'rb') as stream:raw=stream.read(MAX_EVENT+1)
            require(len(raw)<=MAX_EVENT,'EVENT_LIMIT')
            result=append(args.journal,decode(raw))
        else:result=read(args.journal,args.provider,args.recent,args.max_bytes,include_ordinary=args.include_ordinary)
        print(json.dumps(result,ensure_ascii=True))
        return 0
    except (JournalError,OSError) as exc:
        print(json.dumps({'code':exc.code if isinstance(exc,JournalError) else 'INPUT_IO_ERROR'}))
        return 1


if __name__=='__main__':
    sys.exit(main())
