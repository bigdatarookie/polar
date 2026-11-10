"""Pure bounded exact verification of a supplied full-six quantile certificate."""
from dataclasses import dataclass
import hashlib

Rational = tuple[str, str]
FORMAT = 'polar.exact-certificate/1'
SCOPE = 'SOURCE_POPULATION_MASK_TRANSFORM_NOT_ASSESSED'
CHECKS = ('DUAL_BOUNDS','DUAL_STATIONARITY','PRIMARY_DUAL_GAP','FACE_FEASIBILITY',
          'SECONDARY_MULTIPLIER_SIGN','SECONDARY_STATIONARITY','COMPLEMENTARY_SLACKNESS')


@dataclass(frozen=True, slots=True)
class ExactCertificateLimits:
    max_rows: int
    max_token_bytes: int
    max_rational_bits: int
    max_intermediate_bits: int
    max_exact_operations: int
    max_input_bytes: int


@dataclass(frozen=True, slots=True)
class ExactCertificateRequest:
    row_ids: tuple[str, ...]
    z_bits: tuple[tuple[str, str, str, str, str], ...]
    y_bits: tuple[str, ...]
    theta: tuple[Rational, ...]
    dual: tuple[Rational, ...]
    secondary: tuple[Rational, ...]


@dataclass(frozen=True, slots=True)
class ExactCertificateResult:
    status: str
    theta: tuple[Rational, ...] | None
    primary_objective: Rational | None
    dual_objective: Rational | None
    proof_id: str
    format_version: str
    checks: tuple[tuple[str, str], ...]
    failure_codes: tuple[str, ...]
    scope_status: str
    exact_operations: int


class ExactCertificateError(ValueError):
    __slots__ = ('code','phase')
    def __init__(self,code,phase):
        self.code=code;self.phase=phase
        super().__init__(code)


def _reject(code,phase):
    raise ExactCertificateError(code,phase) from None


@dataclass(frozen=True, slots=True)
class _N:
    value: int
    bits: int


@dataclass(frozen=True, slots=True)
class _R:
    numerator: _N
    denominator: _N


class _Meter:
    """The only layer that performs arithmetic on proof integers."""
    def __init__(self,limits):
        self.limit=limits.max_exact_operations;self.B=limits.max_intermediate_bits
        self.R=limits.max_rational_bits;self.used=0;self.phase='NUMERIC'
        # Explicit finite constant representations; no caller bigint enters here.
        self.constants={0:_N(0,0),1:_N(1,1),9:_N(9,4),10:_N(10,4),
                        -9:_N(-9,4),-1074:_N(-1074,11),1075:_N(1075,11),
                        2047:_N(2047,11)}
        self.zero=self.c(0);self.one=self.c(1)

    def charge(self):
        if self.used>=self.limit:_reject('RESOURCE_LIMIT_EXCEEDED',self.phase)
        self.used+=1

    def guard(self,bits,bound=None):
        if bits>self.B or bound is not None and bits>bound:
            _reject('RESOURCE_LIMIT_EXCEEDED',self.phase)

    def c(self,value):
        number=self.constants[value]
        self.guard(number.bits)
        return number

    def finish(self,value,bound):
        self.charge()
        bits=value.bit_length()
        self.guard(bits,bound)
        return _N(value,bits)

    def add(self,a,b,bound=None):
        if a.bits==0:return b
        if b.bits==0:return a
        size=max(a.bits,b.bits)+1
        self.guard(size,bound);self.charge()
        return self.finish(a.value+b.value,size)

    def sub(self,a,b):
        if b.bits==0:return a
        size=max(a.bits,b.bits)+1
        self.guard(size);self.charge()
        return self.finish(a.value-b.value,size)

    def mul(self,a,b,bound=None):
        if a.bits==0 or b.bits==0:return self.zero
        size=a.bits+b.bits
        self.guard(size,bound);self.charge()
        return self.finish(a.value*b.value,size)

    def neg(self,a):
        if a.bits==0:return a
        self.guard(a.bits);self.charge()
        return self.finish(-a.value,a.bits)

    def div(self,a,b):
        if b.bits==0:_reject('RESOURCE_LIMIT_EXCEEDED',self.phase)
        size=max(a.bits,b.bits)
        self.guard(size);self.charge()
        return self.finish(a.value//b.value,size)

    def mod(self,a,b):
        if b.bits==0:_reject('RESOURCE_LIMIT_EXCEEDED',self.phase)
        size=max(a.bits,b.bits)
        self.guard(size);self.charge()
        return self.finish(a.value%b.value,size)

    def shift(self,a,count,left=True):
        # count is fixed or extracted from an already bounded IEEE exponent.
        if type(count) is not int:_reject('RESOURCE_LIMIT_EXCEEDED',self.phase)
        self.charge()
        negative=count<0
        self.charge()
        too_large=count>1075
        if negative or too_large:_reject('RESOURCE_LIMIT_EXCEEDED',self.phase)
        if a.bits==0:return a
        size=a.bits+count if left else a.bits
        self.guard(size);self.charge()
        return self.finish(a.value<<count if left else a.value>>count,size)

    def band(self,a,b):
        size=max(a.bits,b.bits)
        self.guard(size);self.charge()
        return self.finish(a.value&b.value,size)

    def eq(self,a,b):
        self.charge()
        return a.value==b.value

    def lt(self,a,b):
        self.charge()
        return a.value<b.value

    def le(self,a,b):
        self.charge()
        return a.value<=b.value

    def gcd(self,a,b):
        old=self.phase;self.phase='GCD'
        try:
            if self.lt(a,self.zero):a=self.neg(a)
            # Every Euclidean remainder and test is individually charged.
            while not self.eq(b,self.zero):
                a,b=b,self.mod(a,b)
            return a
        finally:self.phase=old

    def ratio(self,n,d,*,supplied=False):
        if self.eq(d,self.zero):_reject('RESOURCE_LIMIT_EXCEEDED',self.phase)
        if self.lt(d,self.zero):n=self.neg(n);d=self.neg(d)
        common=self.gcd(n,d)
        if supplied:
            if not self.eq(common,self.one):_reject('RATIONAL_NOT_REDUCED','NUMERIC')
            return _R(n,d)
        return _R(self.div(n,common),self.div(d,common))

    def parse(self,text,base=10,*,rational=False):
        negative=text.startswith('-')
        digits=text[1:] if negative else text
        acc=self.zero
        # Lexical admission already bounded ASCII and the entire token.
        width=(0,1,2,2,3,3,3,3,4,4,4,4,4,4,4,4)
        multiplier=self.c(10) if base==10 else _N(16,5)
        self.guard(multiplier.bits)
        for char in digits:
            self.charge()  # one bounded digit-decoding update
            value='0123456789abcdef'.index(char)
            digit=_N(value,width[value]);self.guard(digit.bits)
            if rational and digit.bits>self.R:_reject('RATIONAL_BIT_LIMIT_EXCEEDED','NUMERIC')
            if acc.bits==0:acc=digit
            else:
                bound=self.R if rational else None
                acc=self.add(self.mul(acc,multiplier,bound),digit,bound)
        if rational and acc.bits>self.R:_reject('RATIONAL_BIT_LIMIT_EXCEEDED','NUMERIC')
        return self.neg(acc) if negative else acc

    def supplied(self,pair):
        n=self.parse(pair[0],rational=True)
        d=self.parse(pair[1],rational=True)
        return self.ratio(n,d,supplied=True)

    def binary64(self,token):
        word=self.parse(token,16)
        if word.bits==0:return _R(self.zero,self.one)
        sign=self.shift(word,63,False)
        exponent=self.band(self.shift(word,52,False),self.c(2047))
        mask=self.sub(self.shift(self.one,52),self.one)
        mantissa=self.band(word,mask)
        if self.eq(exponent,self.zero):
            if self.eq(mantissa,self.zero):return _R(self.zero,self.one)
            power=self.c(-1074)
        else:
            mantissa=self.add(mantissa,self.shift(self.one,52))
            power=self.sub(exponent,self.c(1075))
        if self.lt(power,self.zero):
            denominator=self.shift(self.one,self.neg(power).value)
            numerator=mantissa
        else:
            numerator=self.shift(mantissa,power.value);denominator=self.one
        if not self.eq(sign,self.zero):numerator=self.neg(numerator)
        return self.ratio(numerator,denominator)

    def radd(self,a,b):
        return self.ratio(self.add(self.mul(a.numerator,b.denominator),
                                   self.mul(b.numerator,a.denominator)),
                          self.mul(a.denominator,b.denominator))

    def rneg(self,a):
        return _R(self.neg(a.numerator),a.denominator)

    def rsub(self,a,b):
        return self.radd(a,self.rneg(b))

    def rmul(self,a,b):
        return self.ratio(self.mul(a.numerator,b.numerator),self.mul(a.denominator,b.denominator))

    def rle(self,a,b):
        return self.le(self.mul(a.numerator,b.denominator),self.mul(b.numerator,a.denominator))

    def req(self,a,b):
        return self.eq(self.mul(a.numerator,b.denominator),self.mul(b.numerator,a.denominator))

    def integer_text(self,n):
        """Bounded metered decimal rendering; never CPython's bigint str conversion."""
        if n.bits==0:return '0'
        negative=self.lt(n,self.zero)
        value=self.neg(n) if negative else n
        digits=[]
        while not self.eq(value,self.zero):
            remainder=self.mod(value,self.c(10))
            digits.append('0123456789'[remainder.value])
            value=self.div(value,self.c(10))
        return ('-' if negative else '')+''.join(reversed(digits))

    def wire(self,r):
        return self.integer_text(r.numerator),self.integer_text(r.denominator)


def _limits(limits):
    if type(limits) is not ExactCertificateLimits:_reject('INVALID_LIMIT_TYPE','LIMITS')
    names=('max_rows','max_token_bytes','max_rational_bits','max_intermediate_bits',
           'max_exact_operations','max_input_bytes')
    ceilings=(10000,2048,4096,65536,2000000,16777216)
    for name,ceiling in zip(names,ceilings):
        try:value=object.__getattribute__(limits,name)
        except AttributeError:_reject('INVALID_LIMIT_TYPE','LIMITS')
        if type(value) is not int:_reject('INVALID_LIMIT_TYPE','LIMITS')
        # Inspect magnitude before any caller integer comparison.
        bits=value.bit_length()
        if bits>ceiling.bit_length():_reject('LIMIT_CEILING_EXCEEDED','LIMITS')
        if value<=0:_reject('INVALID_LIMIT_VALUE','LIMITS')
        if value>ceiling:_reject('LIMIT_CEILING_EXCEEDED','LIMITS')
    if limits.max_intermediate_bits<limits.max_rational_bits:
        _reject('INVALID_LIMIT_RELATION','LIMITS')


def _shape(request,limits):
    if type(request) is not ExactCertificateRequest:_reject('REQUEST_TYPE_REQUIRED','STRUCTURE')
    names=('row_ids','z_bits','y_bits','theta','dual','secondary')
    for name in names:
        try:value=object.__getattribute__(request,name)
        except AttributeError:_reject('REQUEST_TYPE_REQUIRED','STRUCTURE')
        if type(value) is not tuple:_reject('IMMUTABLE_TUPLE_REQUIRED','STRUCTURE')
    n=len(request.row_ids)
    if not 1<=n<=limits.max_rows:_reject('ROW_DOMAIN_EXCEEDED','STRUCTURE')
    for name in names[1:]:
        expected=6 if name=='theta' else n
        if len(getattr(request,name))!=expected:_reject('DIMENSION_MISMATCH','STRUCTURE')
        if name=='z_bits':
            for row in request.z_bits:
                if type(row) is not tuple:_reject('IMMUTABLE_TUPLE_REQUIRED','STRUCTURE')
                if len(row)!=5:_reject('DIMENSION_MISMATCH','STRUCTURE')
        if name in ('theta','dual','secondary'):
            for pair in getattr(request,name):
                if type(pair) is not tuple:_reject('IMMUTABLE_TUPLE_REQUIRED','STRUCTURE')
                if len(pair)!=2:_reject('DIMENSION_MISMATCH','STRUCTURE')
    return n


class _Wire:
    def __init__(self,limits):
        self.limits=limits;self.bytes=0
        self.add(128)
        self.add(144)

    def add(self,count):
        if count>self.limits.max_input_bytes-self.bytes:
            _reject('INPUT_BYTE_LIMIT_EXCEEDED','LEXICAL')
        self.bytes+=count

    def tuple(self):
        self.add(16)

    def token(self,value,kind):
        if type(value) is not str:_reject('NUMERIC_TOKEN_REQUIRED','LEXICAL')
        if len(value)>self.limits.max_token_bytes:_reject('TOKEN_BYTE_LIMIT_EXCEEDED','LEXICAL')
        # ASCII check needs no potentially huge UTF8 allocation.
        if not value.isascii():
            _reject('ROW_ID_ENCODING_INVALID' if kind=='id' else
                    'BINARY64_TOKEN_INVALID' if kind=='bits' else 'RATIONAL_ENCODING_INVALID','LEXICAL')
        self.add(8+len(value))
        if kind=='id':
            if not 1<=len(value)<=128:_reject('ROW_ID_ENCODING_INVALID','LEXICAL')
        elif kind=='bits':
            if len(value)!=16 or any(c not in '0123456789abcdef' for c in value):
                _reject('BINARY64_TOKEN_INVALID','LEXICAL')
            if value[:3] in ('7ff','fff'):_reject('NONFINITE_BINARY64','LEXICAL')
        else:
            digits=value[1:] if value.startswith('-') else value
            if not digits or any(c not in '0123456789' for c in digits) or (
                digits.startswith('0') and (digits!='0' or value.startswith('-'))):
                _reject('RATIONAL_ENCODING_INVALID','LEXICAL')
            if kind=='den' and (value.startswith('-') or value=='0'):
                _reject('RATIONAL_ENCODING_INVALID','LEXICAL')

    def admit(self,request):
        # Exactly the declared tuple/scalar traversal; no arbitrary recursive object walk.
        self.tuple()
        for token in request.row_ids:self.token(token,'id')
        self.tuple()
        for row in request.z_bits:
            self.tuple()
            for token in row:self.token(token,'bits')
        self.tuple()
        for token in request.y_bits:self.token(token,'bits')
        for pairs in (request.theta,request.dual,request.secondary):
            self.tuple()
            for pair in pairs:
                self.tuple();self.token(pair[0],'num');self.token(pair[1],'den')
                if pair[0]=='0' and pair[1]!='1':_reject('RATIONAL_ENCODING_INVALID','LEXICAL')


def _identity(request,n):
    h=hashlib.sha256()
    h.update(FORMAT.encode('ascii')+b'\x00')
    def token(value):
        body=value.encode('ascii')
        h.update(str(len(body)).encode('ascii'));h.update(b':');h.update(body);h.update(b';')
    token(str(n))
    for value in request.row_ids:token(value)
    for row in request.z_bits:
        for value in row:token(value)
    for value in request.y_bits:token(value)
    for rows in (request.theta,request.dual,request.secondary):
        for pair in rows:
            token(pair[0]);token(pair[1])
    return h.hexdigest()


def verify_exact_certificate(request:ExactCertificateRequest, *,
                             limits:ExactCertificateLimits)->ExactCertificateResult:
    _limits(limits)
    n=_shape(request,limits)
    _Wire(limits).admit(request)
    m=_Meter(limits)
    theta=tuple(m.supplied(pair) for pair in request.theta)
    dual=tuple(m.supplied(pair) for pair in request.dual)
    secondary=tuple(m.supplied(pair) for pair in request.secondary)
    one=_R(m.one,m.one);zero=_R(m.zero,m.one)
    A=tuple((one,)+tuple(m.binary64(token) for token in row) for row in request.z_bits)
    y=tuple(m.binary64(token) for token in request.y_bits)
    if len(set(request.row_ids))!=n:_reject('ROW_ID_DUPLICATE','IDENTITY')
    proof_id=_identity(request,n)
    upper=_R(m.one,m.c(10));lower=_R(m.c(-9),m.c(10))
    nine=_R(m.c(9),m.one)
    def dot(row,values):
        value=zero
        for a,b in zip(row,values):value=m.radd(value,m.rmul(a,b))
        return value
    m.phase='PRIMARY'
    bounds=True
    for d in dual:
        valid_low=m.rle(lower,d);valid_high=m.rle(d,upper)
        bounds=valid_low and valid_high and bounds
    stationarity=True
    for column in range(6):
        total=zero
        for row,d in zip(A,dual):total=m.radd(total,m.rmul(row[column],d))
        stationarity=m.req(total,zero) and stationarity
    primary=zero
    for row,target in zip(A,y):
        residual=m.rsub(target,dot(row,theta))
        positive=m.rle(zero,residual)
        loss=residual if positive else m.rmul(nine,m.rneg(residual))
        primary=m.radd(primary,m.rmul(loss,upper))
    objective=dot(y,dual)
    gap=m.req(primary,objective)
    evaluated=[bounds,stationarity,gap]
    if all(evaluated):
        m.phase='SECONDARY'
        feasible=True;signs=True;complement=True;gradient=list(theta)
        for row,target,d,multiplier in zip(A,y,dual,secondary):
            at_upper=m.req(d,upper);at_lower=m.req(d,lower)
            oriented=tuple(m.rneg(a) for a in row) if at_lower else row
            rhs=m.rneg(target) if at_lower else target
            slack=m.rsub(dot(oriented,theta),rhs)
            inequality=at_upper or at_lower
            valid=m.rle(slack,zero) if inequality else m.req(slack,zero)
            feasible=valid and feasible
            if inequality:
                signs=m.rle(zero,multiplier) and signs
                complement=m.req(m.rmul(multiplier,slack),zero) and complement
            for column,a in enumerate(oriented):
                gradient[column]=m.radd(gradient[column],m.rmul(a,multiplier))
        secondary_stationarity=True
        for value in gradient:
            secondary_stationarity=m.req(value,zero) and secondary_stationarity
        evaluated.extend((feasible,signs,secondary_stationarity,complement))
    outcomes=tuple((name,'NOT_RUN' if i>=len(evaluated) else 'PASS' if evaluated[i] else 'FAIL')
                   for i,name in enumerate(CHECKS))
    failures=tuple(name for name,outcome in outcomes if outcome=='FAIL')
    success=not failures
    # Rendering is also metered. Exhaustion never returns an earlier partial success.
    p=m.wire(primary) if success else None
    d=m.wire(objective) if success else None
    return ExactCertificateResult('EXACT_REPRESENTED_INPUT_CERTIFIED' if success else
        'CERTIFICATE_NOT_VERIFIED',request.theta if success else None,p,d,proof_id,FORMAT,
        outcomes,failures,SCOPE,m.used)
