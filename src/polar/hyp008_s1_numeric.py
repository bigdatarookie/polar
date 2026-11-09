"""S1 represented arithmetic. Integer/rational operations; no numerical library imports."""
from dataclasses import dataclass
from fractions import Fraction
import re
import json

SLOTS=('RET1','RET5','VOL20','DOWN20','MEDIAN_DV20')
MAX_ROWS=10000
MAX_BITS=16384
MAX_FINITE=0x7fefffffffffffff


class S1NumericError(ValueError):
    """NUMERIC_UNVERIFIED with a specific local reason; never a missing-as-zero result."""


def require(ok,reason):
    if not ok:raise S1NumericError(reason)


def bounded(value):
    require(type(value) is Fraction and max(value.numerator.bit_length(),value.denominator.bit_length())<=MAX_BITS,
            'RATIONAL_COMPLEXITY')
    return value


def ratio(value):
    require(type(value) is dict and set(value)=={'numerator','denominator'},'RATIO_SCHEMA')
    n,d=value['numerator'],value['denominator']
    require(type(n) is str and type(d) is str and len(n)<=2048 and len(d)<=2048
            and re.fullmatch(r'0|-?[1-9][0-9]*',n) and re.fullmatch(r'[1-9][0-9]*',d),'RATIO_TOKEN')
    result=bounded(Fraction(int(n),int(d)))
    require(str(result.numerator)==n and str(result.denominator)==d,'RATIO_NOT_NORMALIZED')
    return result


def wire(value):
    value=bounded(value)
    return {'numerator':str(value.numerator),'denominator':str(value.denominator)}


def decimal_projection(lexeme):
    require(type(lexeme) is str and len(lexeme)<=256,'DECIMAL_TOKEN')
    m=re.fullmatch(r'([+-]?)([0-9]+)(?:\.([0-9]+))?(?:[eE]([+-]?[0-9]{1,5}))?',lexeme)
    require(m is not None,'DECIMAL_TOKEN')
    sign,integer,tail,exp=m.groups();tail=tail or '';power=int(exp or '0')-len(tail)
    require(abs(power)<=4096,'DECIMAL_EXPONENT_BOUND')
    number=int(integer+tail)*(-1 if sign=='-' else 1)
    return bounded(Fraction(number*10**max(power,0),10**max(-power,0)))


def power2(exponent):
    return Fraction(1<<exponent) if exponent>=0 else Fraction(1,1<<-exponent)


def dyadic(bits):
    require(type(bits) is str and re.fullmatch('[0-9a-f]{16}',bits),'BINARY64_TOKEN')
    raw=int(bits,16);negative=bool(raw>>63);exponent=(raw>>52)&2047;mantissa=raw&((1<<52)-1)
    require(exponent!=2047,'NONFINITE_BINARY64')
    value=Fraction(mantissa if exponent==0 else mantissa+(1<<52))*power2(-1074 if exponent==0 else exponent-1023-52)
    return -value if negative else value


def round_binary64(value):
    value=bounded(value);negative=value<0;x=abs(value)
    if not x:return {'bits':'0000000000000000','dyadic':wire(Fraction(0)),'residual':wire(value)}
    exponent=x.numerator.bit_length()-x.denominator.bit_length()
    if x<power2(exponent):exponent-=1
    require(exponent<=1023,'BINARY64_OVERFLOW')
    quantum=max(exponent-52,-1074)
    scaled=x/power2(quantum);q,r=divmod(scaled.numerator,scaled.denominator)
    if 2*r>scaled.denominator or (2*r==scaled.denominator and q%2):q+=1
    if quantum==-1074 and q<=(1<<52):raw=q
    else:
        if q==(1<<53):q>>=1;exponent+=1
        require(exponent<=1023,'BINARY64_OVERFLOW')
        raw=((exponent+1023)<<52)|(q-(1<<52))
    if raw and negative:raw|=1<<63
    bits=f'{raw:016x}';represented=dyadic(bits)
    return {'bits':bits,'dyadic':wire(represented),'residual':wire(value-represented)}


def round_sqrt(radicand):
    radicand=bounded(radicand);require(radicand>=0,'SQRT_DOMAIN')
    lo,hi=0,MAX_FINITE
    while lo<hi:
        mid=(lo+hi+1)//2;v=dyadic(f'{mid:016x}')
        if v*v<=radicand:lo=mid
        else:hi=mid-1
    lower=dyadic(f'{lo:016x}')
    upper=dyadic(f'{lo+1:016x}') if lo<MAX_FINITE else power2(1024)
    midpoint=(lower+upper)/2;comparison=(radicand>midpoint*midpoint)-(radicand<midpoint*midpoint)
    choose_upper=comparison>0 or (comparison==0 and lo%2==1)
    raw=lo+int(choose_upper);require(raw<=MAX_FINITE,'BINARY64_OVERFLOW')
    bits=f'{raw:016x}';rounded=dyadic(bits)
    return {'bits':bits,'dyadic':wire(rounded),'radicand':wire(radicand),
            'lower_bits':f'{lo:016x}','upper_boundary':wire(upper),
            'midpoint_squared':wire(midpoint*midpoint),'midpoint_comparison':comparison,
            'rounded_squared_comparison':(rounded*rounded>radicand)-(rounded*rounded<radicand)}


@dataclass(frozen=True)
class ProjectedValue:
    lexeme: str
    exact_kind: str
    exact_value: Fraction
    source_payload_json: str | None = None

    def projection(self):return decimal_projection(self.lexeme)

    def exact_signature(self):
        bounded(self.exact_value)
        require(self.exact_kind in ('fraction','sqrt'),'CONSTANT_PROVENANCE_UNAVAILABLE')
        if self.exact_kind=='fraction':
            return ('signed_square',-1 if self.exact_value<0 else 1,self.exact_value**2)
        require(self.exact_value>=0,'SQRT_DOMAIN')
        return ('signed_square',1,self.exact_value)

    def record(self):
        return {'decimal80_projection':self.lexeme,'exact_kind':self.exact_kind,
                'exact_value':wire(self.exact_value),
                'source_payload':None if self.source_payload_json is None else json.loads(self.source_payload_json)}


def fit_transform(rows):
    require(type(rows) is tuple and 1<=len(rows)<=MAX_ROWS
            and all(type(row) is tuple and len(row)==5 and all(type(v) is ProjectedValue for v in row)
                    for row in rows),'TRANSFORM_INPUT')
    columns=[];converted=[[None]*5 for _ in rows];z=[[None]*5 for _ in rows]
    for j,slot in enumerate(SLOTS):
        values=[row[j] for row in rows];projections=[v.projection() for v in values]
        signatures=[v.exact_signature() for v in values]
        constant=len(set(projections))==1
        if constant:require(len(set(signatures))==1,'UPSTREAM_PROJECTION_COLLAPSE')
        records=[round_binary64(p) for p in projections];xs=[ratio(r['dyadic']) for r in records]
        if not constant:require(len(set(xs))>1,'CONVERSION_COLLAPSE')
        for i,(v,record) in enumerate(zip(values,records)):converted[i][j]={'source':v.record(),**record}
        if constant:
            columns.append({'slot':slot,'constant':True,'exact_provenance':values[0].record(),
                            'limitation':'REPRESENTED_SOURCE_PROJECTION_ONLY','mean':None,'variance':None,'scale':None})
            for i in range(len(rows)):z[i][j]=round_binary64(Fraction(0))
            continue
        mean=bounded(sum(xs,Fraction(0))/len(xs));variance=bounded(sum(((x-mean)**2 for x in xs),Fraction(0))/len(xs))
        m=round_binary64(mean);s=round_sqrt(variance);scale=ratio(s['dyadic'])
        require(variance>0 and scale>0,'POSITIVE_VARIANCE_ZERO_SCALE')
        column=[round_binary64(bounded((x-ratio(m['dyadic']))/scale)) for x in xs]
        require(len({r['bits'] for r in column})>1,'TRANSFORM_COLLAPSE')
        columns.append({'slot':slot,'constant':False,'mean':m,'variance':wire(variance),'scale':s})
        for i,record in enumerate(column):z[i][j]=record
    return {'schema':'polar.hyp008-s1-transform/1','slots':list(SLOTS),'training_count':len(rows),
            'columns':columns,'training_conversion':converted,'training_z':z}


def transform_score(values,transform):
    require(type(values) is tuple and len(values)==5 and all(type(v) is ProjectedValue for v in values)
            and transform['schema']=='polar.hyp008-s1-transform/1' and transform['slots']==list(SLOTS),
            'SCORE_TRANSFORM_INPUT')
    result=[]
    for value,column in zip(values,transform['columns']):
        converted=round_binary64(value.projection())
        if column['constant']:z=round_binary64(Fraction(0))
        else:z=round_binary64(bounded((ratio(converted['dyadic'])-ratio(column['mean']['dyadic']))/ratio(column['scale']['dyadic'])))
        result.append({'source':value.record(),'conversion':converted,'z':z})
    return result


def projected_payload(payload,slot):
    """Interpret only an admitted numeric payload, preserving original proof fields."""
    require(slot in SLOTS and type(payload) is dict,'PAYLOAD_SCHEMA')
    sqrt=slot in ('VOL20','DOWN20')
    key='exact_radicand' if sqrt else 'exact_fraction'
    residual='projection_squared_minus_exact_radicand' if sqrt else 'projection_minus_exact'
    method='DECIMAL80_DIVIDE_THEN_SQRT_ROUND_HALF_EVEN' if sqrt else 'DECIMAL80_DIVIDE_ROUND_HALF_EVEN'
    require(set(payload)=={'decimal80_projection',key,residual,'method'} and payload['method']==method,
            'PAYLOAD_SCHEMA')
    projection=decimal_projection(payload['decimal80_projection']);exact=ratio(payload[key])
    if sqrt:require(projection>=0 and exact>=0,'SQRT_DOMAIN')
    require(ratio(payload[residual])==(projection*projection-exact if sqrt else projection-exact),
            'SOURCE_PROJECTION_RESIDUAL')
    return ProjectedValue(payload['decimal80_projection'],'sqrt' if sqrt else 'fraction',exact,
                          json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False))
