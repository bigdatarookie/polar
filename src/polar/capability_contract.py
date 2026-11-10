"""Closed fixed-score capability types/encoding. No retained operand access on import."""
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

PROFILE_ID = 'HYP007_FIXED_SCORE_CAPABILITY_V1'
SCHEMA_SHA = '6e8c8258d6f8d595ec425b4cefd199027186d2fd181516fa9c05582793a7420c'
METHODS = ('RAW_MOM252_21_V1', 'RAW_REV5_V1', 'ridge6', 'ridge21', 'tree')
ACCOUNTS = METHODS + ('REF_EW4_CAP', 'REF_CASH')
SYMBOLS = ('AAPL', 'AMZN', 'TSLA', 'TWTR')
TOKENS = tuple('2022-01-04:'+s for s in SYMBOLS)
MAPPING = tuple({'opportunity_token':t, 'source_symbol':s, 'simulated_instrument_id':s+'.XCAP'}
                for s,t in zip(SYMBOLS,TOKENS))
FILES = tuple(sorted(n+'.json' for n in ('bindings','scores','targets','allocations','events','samples','metrics','status')))
MAX_BYTES = 32*1024**2
D = '2022-01-05T04:59:59.999999Z'
I = '2022-01-05T14:00:00.000000Z'
CLOSE_DATES = ('2022-01-05','2022-01-06','2022-01-07','2022-01-10','2022-01-11')
OPEN_DATES = ('2022-01-05','2022-01-12')
STAGES = ('input_validation','score_restore','mapping','account_creation','entry_allocation_execution',
          'valuation','exit_allocation_execution','exact_evaluation','semantic_payload_validation')


class CapabilityError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(ok, code='SCHEMA_INVALID'):
    if not ok:
        raise CapabilityError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    def safe(v):
        require(type(v) in (dict,list,str,int,bool,type(None)), "SCHEMA_INVALID")
        if type(v) is dict:
            require(all(type(k) is str for k in v), "SCHEMA_INVALID")
            for x in v.values():safe(x)
        elif type(v) is list:
            for x in v:safe(x)
    safe(value)
    return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)+'\n').encode()


def digest(value):
    return sha(canonical(value))


def _pairs(rows):
    result = {}
    for key,value in rows:
        require(key not in result, 'INPUT_INTEGRITY')
        result[key] = value
    return result


class NumberToken(str):
    """An inert JSON floating lexeme, never an input conversion/score object."""


def decode(raw, *, inert_numbers=False):
    require(type(raw) is bytes and len(raw)<=MAX_BYTES, 'INPUT_INTEGRITY')
    try:
        value = json.loads(raw,object_pairs_hook=_pairs,
                          parse_float=NumberToken if inert_numbers else
                              lambda _: (_ for _ in ()).throw(CapabilityError('SCHEMA_INVALID')),
                          parse_constant=lambda _: (_ for _ in ()).throw(CapabilityError('INPUT_INTEGRITY')))
    except (ValueError,UnicodeError,RecursionError):
        raise CapabilityError('INPUT_INTEGRITY') from None
    return value


def exact(value, fields, code='SCHEMA_INVALID'):
    require(type(value) is dict and set(value)==set(fields),code)
    return value


def ns(value):
    require(type(value) is str and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z',value), 'CLOCK_ORDER')
    try:
        dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:
        raise CapabilityError('CLOCK_ORDER') from None
    delta=dt-datetime(1970,1,1,tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*10**9+delta.microseconds*1000


def microtime(timestamp):
    require(type(timestamp) is int and timestamp>=0 and timestamp%1000==0, 'CLOCK_ORDER')
    seconds, nanos=divmod(timestamp,10**9)
    return datetime.fromtimestamp(seconds,timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')+f'.{nanos//1000:06d}Z'


def cents(value, *, positive=False):
    require(type(value) is str and len(value)<=128 and re.fullmatch(r'(0|[1-9][0-9]*)\.[0-9]{2}',value), 'NATIVE_REPRESENTATION')
    result=int(value.replace('.',''))
    require(not positive or result>0,'NATIVE_REPRESENTATION')
    return result


def money(value):
    require(type(value) is int and value>=0, 'NATIVE_REPRESENTATION')
    return str(value//100)+'.'+str(value%100).zfill(2)


def decimal_money(value):
    require(type(value) is Decimal and value.is_finite(),'NATIVE_REPRESENTATION')
    amount=Fraction(value)*100
    require(amount.denominator==1 and amount>=0,'NATIVE_REPRESENTATION')
    return money(amount.numerator)


def rational(value):
    require(type(value) in (int,Fraction), 'METRIC_MISMATCH')
    value=Fraction(value)
    return {'numerator':str(value.numerator),'denominator':str(value.denominator)}


def fraction(value):
    exact(value,('numerator','denominator'),'METRIC_MISMATCH')
    require(all(type(value[k]) is str and len(value[k])<=512 for k in value), 'METRIC_MISMATCH')
    require(re.fullmatch(r'0|-?[1-9][0-9]*',value['numerator']) and
            re.fullmatch(r'[1-9][0-9]*',value['denominator']), 'METRIC_MISMATCH')
    result=Fraction(int(value['numerator']),int(value['denominator']))
    require(rational(result)==value,'METRIC_MISMATCH')
    return result


def weight(value):
    require(type(value) is Decimal and value.is_finite(), 'MAPPER_RESULT_INVALID')
    sign,digits,exponent=value.as_tuple()
    require(not sign and exponent>=-12 and len(digits)<=40,'MAPPER_RESULT_INVALID')
    coefficient=0
    for digit in digits:
        coefficient=coefficient*10+digit
    require(-12<=exponent<=0,'MAPPER_RESULT_INVALID')
    units=coefficient*10**(exponent+12)
    require(units<=10**12,'MAPPER_RESULT_INVALID')
    return str(units//10**12)+'.'+str(units%10**12).zfill(12)


def _schema():
    raw=Path(__file__).with_name('capability_schema.json').read_bytes()
    require(sha(raw)==SCHEMA_SHA,'BINDING_MISMATCH')
    return json.loads(raw)


# The single immutable protocol, not an arbitrary external JSON Schema engine.
SCHEMA=_schema()
REASONS=frozenset(SCHEMA['$defs']['reason']['enum'])


def _equal(a,b):
    return canonical(a)==canonical(b)


def _matches(value,node,depth=0):
    require(depth<=96,'SCHEMA_INVALID')
    if type(node) is bool:
        return node
    if '$ref' in node:
        ref=node['$ref']
        require(ref.startswith('#/$defs/') and ref[8:] in SCHEMA['$defs'])
        if not _matches(value,SCHEMA['$defs'][ref[8:]],depth+1):
            return False
    if 'const' in node and not _equal(value,node['const']):
        return False
    if 'enum' in node and not any(_equal(value,v) for v in node['enum']):
        return False
    types={'object':dict,'array':list,'string':str,'integer':int,'boolean':bool,'null':type(None)}
    if 'type' in node and type(value) is not types[node['type']]:
        return False
    if type(value) is dict:
        if not set(node.get('required',())).issubset(value):
            return False
        props=node.get('properties',{})
        if node.get('additionalProperties') is False and set(value)-set(props):
            return False
        if any(not _matches(value[k],v,depth+1) for k,v in props.items() if k in value):
            return False
    if type(value) is list:
        if not node.get('minItems',0)<=len(value)<=node.get('maxItems',len(value)):
            return False
        if node.get('uniqueItems') and len({canonical(v) for v in value})!=len(value):
            return False
        prefix=node.get('prefixItems',[])
        if any(not _matches(v,prefix[i] if i<len(prefix) else node.get('items',True),depth+1)
               for i,v in enumerate(value)):
            return False
    if type(value) is str:
        if len(value)>node.get('maxLength',len(value)):
            return False
        if 'pattern' in node and re.search(node['pattern'],value) is None:
            return False
    if type(value) is int and not node.get('minimum',value)<=value<=node.get('maximum',value):
        return False
    for kind,test in (('allOf',all),('anyOf',any)):
        if kind in node and not test(_matches(value,v,depth+1) for v in node[kind]):
            return False
    if 'oneOf' in node and sum(_matches(value,v,depth+1) for v in node['oneOf'])!=1:
        return False
    if 'if' in node:
        branch='then' if _matches(value,node['if'],depth+1) else 'else'
        if branch in node and not _matches(value,node[branch],depth+1):
            return False
    return True


def validate(value, definition):
    """Validate this hash-bound schema subset, never claim Draft meta-validation."""
    require(_matches(value,SCHEMA['$defs'][definition]),'SCHEMA_INVALID')
    canonical(value)  # no binary floating JSON numbers/NaN or custom objects
    return value


def fixed(definition):
    """Static profile constants only; never synthesize a successful data payload."""
    def item(node):
        if '$ref' in node:
            return item(SCHEMA['$defs'][node['$ref'][8:]])
        if 'const' in node:
            return node['const']
        if node.get('type')=='null':
            return None
        if node.get('type')=='object':
            return {k:item(v) for k,v in node['properties'].items()}
        if node.get('type')=='array' and 'prefixItems' in node:
            return [item(v) for v in node['prefixItems']]
        raise CapabilityError('SCHEMA_INVALID')
    return item(SCHEMA['$defs'][definition])


PROFILE=fixed('shared_1336691637d6c9ff')
ROSTER=fixed('shared_e35cc5794495084e')
BASIS=fixed('basis')


def envelope(name,payload,status='COMPLETE',reasons=()):
    require(name in FILES and status in ('COMPLETE','NOT_RUN','FAILED','INTERRUPTED','PARTIAL'))
    reasons=sorted(set(reasons))
    require(set(reasons)<=REASONS and (not reasons)==(status=='COMPLETE'))
    value={'schema':'polar.hyp007-fixed-score.'+name[:-5]+'/1','profile_id':PROFILE_ID,
           'stage_status':status,'reason_codes':reasons,'payload':payload}
    return validate(value,name[:-5]+'_file')
