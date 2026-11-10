"""New exact literals: no existing two-toy solver controls or private data."""
from fractions import Fraction as F
import random
import struct
from decimal import Decimal,localcontext
import pytest
from polar.hyp008_s1_numeric import (round_binary64,round_sqrt,dyadic,ProjectedValue,
    decimal_projection,fit_transform,transform_score,S1NumericError,ratio)


@pytest.mark.parametrize('value,bits',[
    (F(0),'0000000000000000'),(F(1),'3ff0000000000000'),
    (1+F(1,2**53),'3ff0000000000000'),(1+F(3,2**53),'3ff0000000000002'),
    (F(1,2**1075),'0000000000000000'),(F(3,2**1075),'0000000000000002'),
    (-F(1,2**1075),'0000000000000000'),
    (F(2**53-1,2**1075),'0010000000000000'),
    (F(2**53-1)*2**971,'7fefffffffffffff')])
def test_exact_rounding_literals(value,bits):
    result=round_binary64(value)
    assert result['bits']==bits
    assert ratio(result['residual'])==value-dyadic(bits)


def test_overflow_midpoint_and_signed_normal():
    with pytest.raises(S1NumericError,match='OVERFLOW'):
        round_binary64(F(2**1024-2**970))
    assert round_binary64(F(-3,2))['bits']=='bff8000000000000'


def test_seeded_rational_cast_matches_separate_python_fraction_conversion():
    rng=random.Random(271828)
    for _ in range(200):
        value=F(rng.randrange(-2**100,2**100),rng.randrange(1,2**100))
        assert round_binary64(value)['bits']==struct.pack('>d',float(value)).hex()


@pytest.mark.parametrize('bits',['0000000000000001','000fffffffffffff',
    '0010000000000000','3ff0000000000001','7fefffffffffffff','8000000000000001'])
def test_finite_bit_round_trip(bits):assert round_binary64(dyadic(bits))['bits']==bits


def test_sqrt_midpoint_and_proof():
    assert round_sqrt(F(4))['bits']=='4000000000000000'
    assert round_sqrt(F(2))['bits']=='3ff6a09e667f3bcd'
    lower=dyadic('3ff0000000000000');upper=dyadic('3ff0000000000001')
    proof=round_sqrt(((lower+upper)/2)**2)
    assert proof['bits']=='3ff0000000000000' and proof['midpoint_comparison']==0
    assert ratio(proof['midpoint_squared'])==((lower+upper)/2)**2
    assert round_sqrt(F(1,2**2150))['bits']=='0000000000000000'


def test_decimal_parsing_ignores_ambient_context_and_preserves_input_sign():
    with localcontext() as c:
        c.prec=2
        assert decimal_projection('1.234567890123456789')==F(1234567890123456789,10**18)
    assert round_binary64(decimal_projection('-0.0'))['bits']=='0000000000000000'
    with pytest.raises(S1NumericError):decimal_projection('NaN')


def column_rows(values):return tuple(tuple(ProjectedValue(str(v),'fraction',F(v)) for _ in range(5)) for v in values)


def test_train_only_transform_and_exact_variance():
    model=fit_transform(column_rows([1,3]));column=model['columns'][0]
    assert ratio(column['mean']['dyadic'])==2 and ratio(column['variance'])==1
    assert [ratio(row[0]['dyadic']) for row in model['training_z']]==[-1,1]
    score=transform_score(tuple(ProjectedValue('5','fraction',F(5)) for _ in range(5)),model)
    assert all(ratio(r['z']['dyadic'])==3 for r in score)


def test_proven_constant_maps_scoring_payload_to_zero_but_retains_it():
    model=fit_transform(column_rows([2,2]))
    score=transform_score(tuple(ProjectedValue('99','fraction',F(99)) for _ in range(5)),model)
    assert score[0]['source']['decimal80_projection']=='99'
    assert score[0]['z']['bits']=='0000000000000000'


def test_rational_sqrt_certificate_proves_same_exact_constant():
    rows=(tuple(ProjectedValue('2','fraction',F(2)) for _ in range(5)),
          tuple(ProjectedValue('2','sqrt',F(4)) for _ in range(5)))
    assert all(c['constant'] for c in fit_transform(rows)['columns'])


def test_distinct_exact_objects_same_projection_fail():
    rows=(tuple(ProjectedValue('1','fraction',F(1)) for _ in range(5)),
          tuple(ProjectedValue('1','fraction',1+F(1,10**100)) for _ in range(5)))
    with pytest.raises(S1NumericError,match='UPSTREAM_PROJECTION_COLLAPSE'):fit_transform(rows)


def test_distinct_projection_cast_collapse_fails():
    rows=column_rows([1,F(100000000000000001,100000000000000000)])
    # Lexical decimal projection, not a fraction token.
    rows=(rows[0],tuple(ProjectedValue('1.00000000000000001','fraction',
          F(100000000000000001,100000000000000000)) for _ in range(5)))
    with pytest.raises(S1NumericError,match='CONVERSION_COLLAPSE'):fit_transform(rows)


def test_incomparable_constant_provenance_is_unavailable():
    rows=tuple(tuple(ProjectedValue('2','unknown',F(2)) for _ in range(5)) for _ in range(2))
    with pytest.raises(S1NumericError,match='CONSTANT_PROVENANCE_UNAVAILABLE'):fit_transform(rows)


def test_source_payload_residual_and_original_method_are_retained():
    from polar.hyp008_s1_numeric import projected_payload,wire
    payload={'decimal80_projection':'1.25','exact_fraction':wire(F(5,4)),
             'projection_minus_exact':wire(F(0)),'method':'DECIMAL80_DIVIDE_ROUND_HALF_EVEN'}
    value=projected_payload(payload,'RET1')
    assert value.record()['source_payload']==payload
    bad={**payload,'projection_minus_exact':wire(F(1))}
    with pytest.raises(S1NumericError,match='SOURCE_PROJECTION_RESIDUAL'):projected_payload(bad,'RET1')
    with pytest.raises(S1NumericError,match='PAYLOAD_SCHEMA'):projected_payload(payload,'VOL20')


def test_smallest_positive_training_variance_scale_can_round_to_zero():
    rows=(tuple(ProjectedValue('0','fraction',F(0)) for _ in range(5)),
          tuple(ProjectedValue('4.9406564584124654e-324','fraction',F(1,2**1074)) for _ in range(5)))
    with pytest.raises(S1NumericError,match='POSITIVE_VARIANCE_ZERO_SCALE'):fit_transform(rows)
