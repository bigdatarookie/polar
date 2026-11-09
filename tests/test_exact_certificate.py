"""Fixed hand-literal certificate families; no solver, random generator or real inputs."""
from dataclasses import replace
from decimal import localcontext, getcontext
import json
import os
from pathlib import Path
import random

import pytest
from polar.exact_certificate import (
    ExactCertificateLimits as Limits, ExactCertificateRequest as Request,
    ExactCertificateError as Error, verify_exact_certificate as verify)

ZERO='0000000000000000'
ONE='3ff0000000000000'
THREE='4008000000000000'
R0=('0','1');R1=('1','1')
BASE=Limits(16,2048,4096,65536,2000000,16777216)
CALLS=[]


def request(n=1):
    return Request(tuple('r'+str(i) for i in range(n)),((ZERO,)*5,)*n,(ZERO,)*n,
                   (R0,)*6,(R0,)*n,(R0,)*n)


def interval(b='1',multiplier='1'):
    return replace(request(10),y_bits=(ONE,)+(THREE,)*9,
        theta=((b,'1'),)+(R0,)*5,dual=(('-9','10'),)+(('1','10'),)*9,
        secondary=((multiplier,'1'),)+(R0,)*9)


def call(req=None,limits=BASE):
    req=request() if req is None else req
    CALLS.append(1)
    # Durable per-call admissions survive a failed assertion or interrupted pytest.
    log=os.environ.get('POLAR_CERTIFICATE_CALL_LOG')
    if log:
        with open(log,'a') as f:
            f.write(json.dumps({'ordinal':len(CALLS),'kind':'invented-verifier-call'})+'\n')
            f.flush();os.fsync(f.fileno())
    assert len(CALLS)<=64
    return verify(req,limits=limits)


def certified(result,objective=R0):
    assert result.status=='EXACT_REPRESENTED_INPUT_CERTIFIED'
    assert result.primary_objective==result.dual_objective==objective
    assert result.failure_codes==() and all(v=='PASS' for _,v in result.checks)
    assert result.scope_status=='SOURCE_POPULATION_MASK_TRANSFORM_NOT_ASSESSED'


def rejected(result,failures):
    assert result.status=='CERTIFICATE_NOT_VERIFIED'
    assert result.failure_codes==failures
    assert result.theta is result.primary_objective is result.dual_objective is None


def error(code,req=None,limits=BASE,phase=None):
    with pytest.raises(Error) as found:call(req,limits)
    assert found.value.code==code
    if phase is not None:assert found.value.phase==phase
    assert str(found.value)==code and found.value.__cause__ is None


def test_01_zero_exact_equality():
    certified(call())


def test_02_intercept_interval_minimum_norm_endpoint():
    certified(call(interval()),('9','5'))


def test_03_noncomplementary_stationary_interior():
    result=call(interval('2','2'))
    rejected(result,('COMPLEMENTARY_SLACKNESS',))
    assert result.checks[3:6]==(('FACE_FEASIBILITY','PASS'),
        ('SECONDARY_MULTIPLIER_SIGN','PASS'),('SECONDARY_STATIONARITY','PASS'))


def test_04_interior_equality():
    req=replace(request(),y_bits=(ONE,),theta=(R1,)+(R0,)*5,secondary=(('-1','1'),))
    certified(call(req))


def test_05_full_six_coordinates_including_intercept():
    req=replace(request(),z_bits=((ONE,)*5,),y_bits=(ONE,),
                theta=(('1','6'),)*6,secondary=(('-1','6'),))
    certified(call(req))


def test_06_redundant_numerical_rows():
    certified(call(request(2)))


def test_07_dual_bounds_and_stationarity():
    result=call(replace(request(),dual=(('1','5'),)))
    rejected(result,('DUAL_BOUNDS','DUAL_STATIONARITY'))
    assert all(v=='NOT_RUN' for _,v in result.checks[3:])


def test_08_dual_stationarity_only():
    rejected(call(replace(request(),dual=(('1','10'),))),('DUAL_STATIONARITY',))


def test_09_primary_gap():
    rejected(call(replace(request(),y_bits=(ONE,))),('PRIMARY_DUAL_GAP',))


def test_10_secondary_stationarity():
    req=replace(request(),y_bits=(ONE,),theta=(R1,)+(R0,)*5)
    rejected(call(req),('SECONDARY_STATIONARITY',))


def test_11_negative_inequality_multiplier_joint_failures():
    rejected(call(interval('1','-1')),('SECONDARY_MULTIPLIER_SIGN','SECONDARY_STATIONARITY'))


def test_12_false_face_request_fails_primary_first():
    req=replace(request(),y_bits=(ONE,),theta=(('2','1'),)+(R0,)*5,secondary=(('-2','1'),))
    result=call(req)
    rejected(result,('PRIMARY_DUAL_GAP',))
    assert all(v=='NOT_RUN' for _,v in result.checks[3:])


def test_13_signed_zero_identity_preserved():
    positive=call()
    negative=call(replace(request(),z_bits=(('8000000000000000',)+(ZERO,)*4,)))
    certified(positive);certified(negative)
    assert positive.proof_id!=negative.proof_id


def test_14_adjacent_finite_value_exact():
    value=('4503599627370497','4503599627370496')
    req=replace(request(),y_bits=('3ff0000000000001',),
                theta=(value,)+(R0,)*5,secondary=(('-4503599627370497','4503599627370496'),))
    certified(call(req))


def test_15_malformed_bit_case_and_width():
    error('BINARY64_TOKEN_INVALID',replace(request(),y_bits=('3FF0000000000000',)))
    error('BINARY64_TOKEN_INVALID',replace(request(),y_bits=('0',)))


def test_16_nonfinite_bits():
    error('NONFINITE_BINARY64',replace(request(),y_bits=('7ff0000000000000',)))
    error('NONFINITE_BINARY64',replace(request(),y_bits=('7ff8000000000001',)))


def test_17_rational_sign_leadingzero_negativezero():
    for numerator in ('+1','01','-0'):
        error('RATIONAL_ENCODING_INVALID',replace(request(),theta=((numerator,'1'),)+(R0,)*5))


def test_18_invalid_denominator():
    for denominator in ('0','-1'):
        error('RATIONAL_ENCODING_INVALID',replace(request(),theta=(('1',denominator),)+(R0,)*5))


def test_19_unreduced_ratio():
    error('RATIONAL_NOT_REDUCED',replace(request(),theta=(('2','2'),)+(R0,)*5))


def test_20_zero_requires_denominator_one():
    error('RATIONAL_ENCODING_INVALID',replace(request(),theta=(('0','2'),)+(R0,)*5))


def test_21_exact_type_bool_and_subclasses():
    class Text(str):pass
    class SubRequest(Request):pass
    error('NUMERIC_TOKEN_REQUIRED',replace(request(),y_bits=(True,)))
    error('NUMERIC_TOKEN_REQUIRED',replace(request(),theta=((Text('0'),'1'),)+(R0,)*5))
    error('INVALID_LIMIT_TYPE',limits=replace(BASE,max_rows=True))
    req=request()
    error('REQUEST_TYPE_REQUIRED',SubRequest(req.row_ids,req.z_bits,req.y_bits,req.theta,req.dual,req.secondary))


def test_22_mutable_and_extra_metadata():
    error('IMMUTABLE_TUPLE_REQUIRED',replace(request(),z_bits=[[ZERO]*5]))
    error('REQUEST_TYPE_REQUIRED',{'row_ids':('r0',),'extra':'metadata'})


def test_23_wrong_count_and_dimensions():
    error('ROW_DOMAIN_EXCEEDED',request(0))
    error('DIMENSION_MISMATCH',replace(request(),z_bits=((ZERO,)*4,)))
    error('DIMENSION_MISMATCH',replace(request(),theta=(R0,)*5))


def test_24_duplicate_and_nonascii_ids():
    error('ROW_ID_DUPLICATE',replace(request(2),row_ids=('r0','r0')))
    error('ROW_ID_ENCODING_INVALID',replace(request(),row_ids=('é',)))


def test_25_invalid_and_overceiling_limits():
    error('INVALID_LIMIT_VALUE',limits=replace(BASE,max_rows=0))
    error('LIMIT_CEILING_EXCEEDED',limits=replace(BASE,max_rows=10001))
    error('INVALID_LIMIT_RELATION',limits=replace(BASE,max_rational_bits=64,max_intermediate_bits=63))


def test_26_early_token_and_structural_byte_bounds():
    error('TOKEN_BYTE_LIMIT_EXCEEDED',limits=replace(BASE,max_token_bytes=1))
    error('INPUT_BYTE_LIMIT_EXCEEDED',limits=replace(BASE,max_input_bytes=128))


def test_27_rational_bit_bound_before_gcd():
    req=replace(request(),theta=(('8','1'),)+(R0,)*5)
    error('RATIONAL_BIT_LIMIT_EXCEEDED',req,replace(BASE,max_rational_bits=2),phase='NUMERIC')


def test_28_product_preflight():
    req=replace(request(),theta=(('128','1'),)+(R0,)*5)
    error('RESOURCE_LIMIT_EXCEEDED',req,replace(BASE,max_rational_bits=8,max_intermediate_bits=8),phase='PRIMARY')


def test_29_budget_stops_inside_euclidean_loop():
    req=replace(request(),theta=(('144','233'),)+(R0,)*5)
    error('RESOURCE_LIMIT_EXCEEDED',req,replace(BASE,max_exact_operations=35),phase='GCD')


def test_30_primary_failure_has_no_secondary_or_coefficients():
    result=call(replace(request(),y_bits=(ONE,)))
    rejected(result,('PRIMARY_DUAL_GAP',))
    assert all(v=='NOT_RUN' for _,v in result.checks[3:])


def test_31_immutability_success_and_failure():
    for req in (request(),interval('2','2')):
        original=(req.row_ids,req.z_bits,req.y_bits,req.theta,req.dual,req.secondary)
        call(req)
        assert (req.row_ids,req.z_bits,req.y_bits,req.theta,req.dual,req.secondary)==original


def test_32_ambient_decimal_random_unchanged():
    baseline=call()
    with localcontext() as ctx:
        ctx.prec=2
        for signal in ctx.traps:ctx.traps[signal]=True
        saved=ctx.copy();random_state=random.getstate()
        result=call()
        assert result==baseline
        assert ctx.prec==saved.prec and ctx.traps==saved.traps and ctx.flags==saved.flags
        assert random.getstate()==random_state
