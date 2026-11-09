"""S1 closed records and token-preserving local decoding, without numeric work."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

MAX_FILE = 32*1024**2
MAX_LINE = 256*1024
FAMILY = 'HYP008_STANDARD_SOURCE_COHORT_FORECAST_S1'
STAGES = ('TREE','LINEAR','HISTORICAL_PASS')
SEMANTIC = ('config.json','source.json','masks.json','transform.json','representations.json',
            'tree.json','linear.json','history.json','forecasts.json','evaluation.json',
            'family.json','limitations.json')
COMMON = {'config.json','source.json','masks.json','family.json','limitations.json'}
GRANT = {'family':1,'tree':1,'linear':1,'historical_pass':1}


class S1ContractError(ValueError):pass


def require(ok,reason):
    if not ok:raise S1ContractError(reason)


def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode('utf-8')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def ref(raw):return {'sha256':sha(raw),'bytes':len(raw)}


@dataclass(frozen=True)
class NumberToken:
    """An opaque source JSON number, not a float/Decimal/Fraction."""
    token: str


def decode(raw, *, opaque=False):
    require(type(raw) is bytes and len(raw)<=MAX_FILE,'JSON_BYTE_BOUND')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'DUPLICATE_JSON_KEY');result[key]=value
        return result
    def number(token):
        require(len(token)<=2048,'NUMBER_TOKEN_BOUND')
        return NumberToken(token)
    try:
        value=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,
            parse_int=number if opaque else int,parse_float=number if opaque else lambda _:require(False,'UNEXPECTED_FLOAT'),
            parse_constant=lambda _:require(False,'NONFINITE_JSON'))
        pending=[(value,0)];count=0
        while pending:
            node,depth=pending.pop();count+=1
            require(depth<=64 and count<=2000000,'JSON_COMPLEXITY')
            if type(node) is dict:pending.extend((v,depth+1) for v in node.values())
            elif type(node) is list:pending.extend((v,depth+1) for v in node)
        return value
    except (UnicodeError,ValueError,RecursionError) as exc:
        if isinstance(exc,S1ContractError):raise
        raise S1ContractError('INVALID_JSON') from None


DEFS=json.loads(Path(__file__).with_name('hyp008_s1_schema.json').read_bytes())['$defs']


def validate(name,value):
    """Execute the finite JSON-schema vocabulary used by the pinned S1 records."""
    def match(rule,v):
        if '$ref' in rule:return match(DEFS[rule['$ref'].removeprefix('#/$defs/')],v)
        if 'oneOf' in rule:
            successes=0
            for sub in rule['oneOf']:
                try:match(sub,v);successes+=1
                except S1ContractError:pass
            require(successes==1,'SCHEMA_ONE_OF');return
        if 'const' in rule:require(type(v) is type(rule['const']) and v==rule['const'],'SCHEMA_CONST')
        if 'enum' in rule:require(any(type(v) is type(x) and v==x for x in rule['enum']),'SCHEMA_ENUM')
        types=rule.get('type');types=[types] if type(types) is str else types
        mapping={'object':dict,'array':list,'string':str,'integer':int,'boolean':bool,'null':type(None)}
        if types:require(any(type(v) is mapping[t] for t in types),'SCHEMA_TYPE')
        if type(v) is dict:
            props=rule.get('properties',{})
            require(set(rule.get('required',[]))<=set(v),'SCHEMA_REQUIRED')
            if rule.get('additionalProperties') is False:require(set(v)<=set(props),'SCHEMA_EXTRA')
            for key,sub in props.items():
                if key in v:match(sub,v[key])
        if type(v) is list:
            require(len(v)>=rule.get('minItems',0) and len(v)<=rule.get('maxItems',10000),'SCHEMA_ARRAY_BOUND')
            prefix=rule.get('prefixItems',[])
            for sub,item in zip(prefix,v):match(sub,item)
            items=rule.get('items',{})
            if items is False:require(len(v)<=len(prefix),'SCHEMA_ARRAY_EXTRA')
            else:
                for item in v[len(prefix):]:match(items,item)
        if type(v) is str:
            require(len(v)>=rule.get('minLength',0) and len(v)<=rule.get('maxLength',MAX_FILE),'SCHEMA_STRING_BOUND')
            if 'pattern' in rule:require(re.search(rule['pattern'],v) is not None,'SCHEMA_PATTERN')
        if type(v) is int:
            require(v>=rule.get('minimum',v) and v<=rule.get('maximum',v),'SCHEMA_INTEGER_BOUND')
    require(name in DEFS,'SCHEMA_NAME');match(DEFS[name],value)
    return value


def identified(value,key):
    body={k:v for k,v in value.items() if k!=key}
    require(value.get(key)==sha(canonical(body)),'RECORD_IDENTITY')
    return value


def closed(value,keys,schema):
    require(type(value) is dict and set(value)==set(keys) and value.get('schema')==schema,'RECORD_SCHEMA')
    return value
