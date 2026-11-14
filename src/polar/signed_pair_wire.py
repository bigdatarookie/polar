"""Lossless bounded B11 private wire for exact large rational report operands.

No process-wide integer-limit change. Legacy signed packet codec remains intact.
"""
from .signed_event_saved import encode,restore
from .gym_contract import canonical,decode,MAX_BYTES
from .signed_native_bridge import require

SCHEMA='polar.private-pair-exact-wire/1'


def _pack(value):
    if type(value) is int and value.bit_length()>512:return {'$int_hex':hex(value)}
    if type(value) is list:return [_pack(v) for v in value]
    if type(value) is dict:return {k:_pack(v) for k,v in value.items()}
    return value


def _unpack(value):
    if type(value) is list:return [_unpack(v) for v in value]
    if type(value) is dict:
        if set(value)=={'$int_hex'}:
            text=value['$int_hex'];require(type(text) is str and len(text)<=MAX_BYTES//4 and
                text.startswith(('0x','-0x')),'PAIR_EXACT_INTEGER_TOKEN')
            try:number=int(text,16)
            except ValueError:raise ValueError('PAIR_EXACT_INTEGER_TOKEN') from None
            require(number.bit_length()>512 and hex(number)==text,'PAIR_EXACT_INTEGER_CANONICAL')
            return number
        return {k:_unpack(v) for k,v in value.items()}
    return value


def wire_bytes(value):
    raw=canonical({'schema':SCHEMA,'value':_pack(encode(value))})
    require(len(raw)<=MAX_BYTES,'PAIR_EXACT_WIRE_BYTES')
    return raw


def wire_plain(raw):
    require(type(raw) is bytes and len(raw)<=MAX_BYTES,'PAIR_EXACT_WIRE_BYTES')
    value=decode(raw);require(type(value) is dict and set(value)=={'schema','value'} and value['schema']==SCHEMA,
        'PAIR_EXACT_WIRE_SCHEMA')
    return value['value']


def wire_read(raw):return restore(_unpack(wire_plain(raw)))
