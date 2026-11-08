"""The fixed Gym v1.1 public protocol; no source payload or private oracle."""
import hashlib
import json
from decimal import (Context, Decimal, localcontext, ROUND_HALF_EVEN,
                     InvalidOperation, DivisionByZero, Overflow, FloatOperation)
from fractions import Fraction
from pathlib import Path

PUBLIC_SHA = '82f014919f929160aca150586a2ad9664143d67136a17cf3c525c4c2ae5404b4'
COMPOSITION_SHA = '5d7f0be23af9b5c179645cddb9270cd4e16617d730a1a32a455d659d854c0bd6'
SOURCE_BINDING_SHA = 'e8a178f1680e95831d3bc27a4e010ab574ec3d86b056fe651228f844e1f33c5d'
SYMBOLS = ('AAPL', 'AMZN', 'TSLA')
DATES = ('2019-01-25','2019-01-28','2019-01-29','2019-01-30','2019-01-31','2019-02-01','2019-02-04')
STRATEGIES = ('DEMO-EW-BH-V1','DEMO-EW-MONTHLY-V1')
MEMBERS = {
 'README-v1.1.md':'f5419c5bbdb16f184a4b282b2246809b9d5cf61fe902cc2bc4b15a166286790c',
 'scenario-v1.1.json':'ce158662936f46acfb2fa7d9d15f371dbaf985fb5616b1e6eb5ca55406db1916',
 'strategies-v1.1.json':'c159ac471f1ef0a37f06a2acd4452ce94c94cb59f44d120a70e908f156147cf8',
 'execution-profile-v1.1.json':'9421d178d32a5e6730cce1c02aa5b9384ca5be5a0a419401d6e7af92d6da9c88',
 'metrics-v1.1.json':'4fbf5930473900fcb6957a03c8ffc21bfb5f02cebdc287805c11c2fba2df1494'}
SEMANTIC_FILES = ('converted.json','preflight.json','simulation.json','evaluation.json')
MAX_BYTES = 32*1024**2

class GymError(Exception):
    pass

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()+b'\n'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def decode(raw):
    def pairs(items):
        result = {}
        for key,value in items:
            if key in result:
                raise GymError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_float=lambda _: (_ for _ in ()).throw(GymError('FLOAT_JSON_FORBIDDEN')),
                          parse_constant=lambda _: (_ for _ in ()).throw(GymError('NONFINITE_JSON')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise GymError('INVALID_JSON') from exc

def read_ref(ref):
    from .history_bundle import read_file
    path = Path(ref['path'])
    if not path.is_absolute() or path.is_symlink():
        raise GymError('UNSAFE_REFERENCE')
    # Resolve parent only after checking all components through existing descriptor reader.
    raw = read_file(path.parent, path.name, MAX_BYTES)
    if sha(raw) != ref['sha256'] or ('bytes' in ref and len(raw) != ref['bytes']):
        raise GymError('REFERENCE_INTEGRITY')
    return raw

def fraction(token):
    if not isinstance(token, str) or len(token)>256:
        raise GymError('INVALID_DECIMAL_TOKEN')
    value = Decimal(token)
    if not value.is_finite():
        raise GymError('NONFINITE_DECIMAL')
    return Fraction(value)

def context():
    ctx=Context(prec=50, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                capitals=1, clamp=0, traps=[])
    for signal in (InvalidOperation, DivisionByZero, Overflow, FloatOperation):
        ctx.traps[signal]=True
    return ctx

def decimal_fraction(value):
    return Decimal(value.numerator)/Decimal(value.denominator)

def decimal_string(value):
    if not value.is_finite():
        raise GymError('NUMERIC_OUTPUT_BOUND')
    if value.adjusted()>4095 or -value.as_tuple().exponent>4096:
        raise GymError('NUMERIC_OUTPUT_BOUND')
    s=format(value,'f')
    if '.' in s:
        s=s.rstrip('0').rstrip('.')
    if s in ('-0',''): s='0'
    if sum(c.isdigit() for c in s)>4096: raise GymError('NUMERIC_OUTPUT_BOUND')
    return s

def exact_string(value):
    """Only finite base10 rationals (money/marks) enter this projection."""
    value=Fraction(value)
    d=value.denominator
    for prime in (2,5):
        while d%prime==0: d//=prime
    if d!=1: raise GymError('RECURRING_MONEY')
    with localcontext(Context(prec=4096, traps=[InvalidOperation, DivisionByZero, Overflow])):
        return decimal_string(decimal_fraction(value))

def rational(value):
    return {'numerator':str(value.numerator),'denominator':str(value.denominator)}

def metric(value=None, status='OK', reason=None):
    return {'value':value,'status':status,'reason':reason,
            'evidence_status':'INSUFFICIENT_EVIDENCE_ENGINEERING_MODEL'}
