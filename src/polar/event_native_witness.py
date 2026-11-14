"""Private component witness bytes using existing canonical/immutable primitives.

No market source, portfolio reconstruction, native invocation or financial verdict.
"""
from dataclasses import fields, is_dataclass
from fractions import Fraction
import math
import re
from pathlib import Path

from .ci_research import require
from .gym_contract import canonical, decode, sha, MAX_BYTES
from .history_bundle import read_file
from .scheduled_event_controller import Context, State, Request, Intent, Anchor, PositionMark, RouteReceipt, SymbolEvaluation, TerminalOrder
from .event_native import verify_saved_event_witnesses

TYPES={c.__name__:c for c in (Context,State,Request,Intent,Anchor,PositionMark,RouteReceipt,SymbolEvaluation,TerminalOrder)}


def encode(value):
    if is_dataclass(value):
        require(type(value) in TYPES.values(),'EVENT_WITNESS_TYPE')
        return {'$type':type(value).__name__,'fields':{f.name:encode(getattr(value,f.name)) for f in fields(value)}}
    if type(value) is Fraction:return {'$fraction':[value.numerator,value.denominator]}
    if type(value) is tuple:return {'$tuple':[encode(v) for v in value]}
    if type(value) is list:return [encode(v) for v in value]
    if type(value) is dict:
        require(all(type(k) is str and not k.startswith('$') for k in value),'EVENT_WITNESS_KEYS')
        return {k:encode(v) for k,v in value.items()}
    require(value is None or type(value) in (str,int,bool),'EVENT_WITNESS_SCALAR')
    return value


def restore(value, depth=0):
    require(depth<40,'EVENT_WITNESS_DEPTH')
    if type(value) is list:
        require(len(value)<=200000,'EVENT_WITNESS_ARRAY');return [restore(v,depth+1) for v in value]
    if type(value) is dict:
        if set(value)=={'$fraction'}:
            p=value['$fraction'];require(type(p) is list and len(p)==2 and all(type(v) is int for v in p) and
                p[1]>0 and math.gcd(*p)==1,'EVENT_WITNESS_FRACTION');return Fraction(*p)
        if set(value)=={'$tuple'}:
            require(type(value['$tuple']) is list,'EVENT_WITNESS_TUPLE');return tuple(restore(value['$tuple'],depth+1))
        if set(value)=={'$type','fields'}:
            cls=TYPES.get(value['$type']) if type(value['$type']) is str else None
            require(cls is not None and type(value['fields']) is dict and
                    set(value['fields'])=={f.name for f in fields(cls)},'EVENT_WITNESS_CLOSED_TYPE')
            return cls(**{k:restore(v,depth+1) for k,v in value['fields'].items()})
        require(all(type(k) is str and not k.startswith('$') for k in value),'EVENT_WITNESS_KEYS')
        return {k:restore(v,depth+1) for k,v in value.items()}
    require(value is None or type(value) in (str,int,bool),'EVENT_WITNESS_SCALAR');return value


def witness_bytes(account):
    verify_saved_event_witnesses(account)
    raw=canonical({'schema':'polar.event-native-component-witnesses/1','account':encode(account)})
    require(len(raw)<=MAX_BYTES,'EVENT_WITNESS_BYTES');return raw


def verify_witness_bytes(raw, expected_context):
    require(type(raw) is bytes and len(raw)<=MAX_BYTES and type(expected_context) is Context,'EVENT_WITNESS_INPUT')
    value=decode(raw);require(type(value) is dict and set(value)=={'schema','account'} and
        value['schema']=='polar.event-native-component-witnesses/1' and canonical(value)==raw,'EVENT_WITNESS_SCHEMA')
    account=restore(value['account']);require(account['context']==expected_context,'EVENT_WITNESS_EXTERNAL_CONTEXT')
    return account,verify_saved_event_witnesses(account)


def publish_witnesses(store,account):
    """Caller-owned existing GymStore, private content-addressed component only.

    Uses the shared immutable publisher; never begins a research attempt/budget.
    """
    raw=witness_bytes(account)
    manifest={'schema':'polar.event-native-witness-manifest/1','context':encode(account['context']),
              'file':{'name':'witnesses.json','sha256':sha(raw),'bytes':len(raw)}}
    encoded=canonical(manifest);name='event-witness-'+sha(encoded)
    with store.locked():store._publish('event-component-witnesses',name,
        {'witnesses.json':raw,'manifest.json':encoded},file_limit=MAX_BYTES)
    return {'id':name,'manifest_sha256':sha(encoded),'context':account['context'],'payload_sha256':sha(raw),'bytes':len(raw)}


def verify_stored_witnesses(root,name,expected_context):
    require(type(name) is str and re.fullmatch(r'event-witness-[a-f0-9]{64}',name) is not None,'EVENT_WITNESS_ID')
    parent='event-component-witnesses/'+name
    manifest_raw=read_file(root,parent+'/manifest.json',65536);manifest=decode(manifest_raw)
    require(canonical(manifest)==manifest_raw and name=='event-witness-'+sha(manifest_raw) and
            set(manifest)=={'schema','context','file'} and manifest['schema']=='polar.event-native-witness-manifest/1' and
            restore(manifest['context'])==expected_context,'EVENT_WITNESS_MANIFEST')
    directory=Path(root)/parent
    require({p.name for p in directory.iterdir()}=={'manifest.json','witnesses.json'} and
            not any(p.is_symlink() for p in directory.iterdir()),'EVENT_WITNESS_MEMBER_SET')
    member=manifest['file'];require(set(member)=={'name','sha256','bytes'} and member['name']=='witnesses.json','EVENT_WITNESS_MEMBER')
    raw=read_file(root,parent+'/witnesses.json',MAX_BYTES)
    require(sha(raw)==member['sha256'] and len(raw)==member['bytes'],'EVENT_WITNESS_MEMBER_HASH')
    account,result=verify_witness_bytes(raw,expected_context)
    return {**result,'id':name,'saved_member_reads':2,'immutable_payload_sha256':sha(raw),'account':account}
