"""Literal order-statistic/missingness boundaries; no real data or forecasts."""
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
import itertools
import math
import struct
import sys

import pytest
from polar.empirical_tenth import (EmpiricalTenthError, EmpiricalTenthResult,
                                  lower_empirical_tenth)


def run(values, count, maximum=20):
    return lower_empirical_tenth(values, expected_count=count, max_rows=maximum)


@pytest.mark.parametrize('values,count,q,rank', [
    ((1.5,),1,1.5,1), ((0.,1.),2,0.,1),
    ((-.1,)+(0.,)*9,10,-.1,1), (tuple(float(x) for x in range(11)),11,1.,2),
])
def test_literal_rank_and_lower_endpoint(values,count,q,rank):
    r=run(values,count)
    assert r==EmpiricalTenthResult('STATISTIC_DEFINED',q,rank,count,count,())


def test_rank_not_interpolated_and_adjacent_values_preserved():
    values=(0.,math.nextafter(0.,1.))
    assert run(values,2).q==0.
    q=math.nextafter(1.,2.)
    assert struct.pack('!d',run((q,),1).q)==struct.pack('!d',q)


def test_constant_duplicates_no_mutation_and_frozen_result():
    values=(3.,)*11;before=tuple(struct.pack('!d',v) for v in values)
    r=run(values,11)
    assert r.q==3. and r.selected_rank==2
    assert tuple(struct.pack('!d',v) for v in values)==before
    with pytest.raises(FrozenInstanceError):r.q=0.


def test_permutation_signed_zero_exactbits_no_input_change():
    values=(-0.,0.,0.,-0.,1.)
    for p in itertools.permutations(values):
        before=tuple(struct.pack('!d',v) for v in p)
        r=run(p,5)
        assert struct.pack('!d',r.q)==b'\0'*8
        assert tuple(struct.pack('!d',v) for v in p)==before
    assert run((0.,),1).status=='STATISTIC_DEFINED'
    assert run((None,),1).status=='WINDOW_UNAVAILABLE'


@pytest.mark.parametrize('values,count,reasons', [
    (None,2,('WINDOW_NOT_SUPPLIED',)),
    ((),2,('COUNT_SHORT','EMPTY_WINDOW')),
    ((1.,),2,('COUNT_SHORT',)),
    ((None,1.),2,('MISSING_VALUE',)),
    ((float('nan'),),1,('NONFINITE_VALUE',)),
    ((float('inf'),),1,('NONFINITE_VALUE',)),
    ((float('-inf'),),1,('NONFINITE_VALUE',)),
    ((None,float('nan')),3,('COUNT_SHORT','MISSING_VALUE','NONFINITE_VALUE')),
])
def test_complete_unavailable_reason_sets_no_effective_n_salvage(values,count,reasons):
    r=run(values,count)
    assert r.status=='WINDOW_UNAVAILABLE' and r.q is r.selected_rank is None
    assert r.supplied_count==(None if values is None else len(values))
    assert r.required_count==count and r.reasons==reasons


@pytest.mark.parametrize('value',[True,False,1,Decimal('1'),'1',object()])
def test_strict_slot_type_overrides_missing_and_nonfinite(value):
    with pytest.raises(EmpiricalTenthError) as caught:
        run((None,float('nan'),value),4)
    assert caught.value.code=='BINARY64_REQUIRED'
    assert str(caught.value)=='BINARY64_REQUIRED'


@pytest.mark.parametrize('value',[True,0,-1,1.,'2',None])
def test_limit_type_and_order(value):
    with pytest.raises(EmpiricalTenthError,match='INVALID_MAX_ROWS'):
        lower_empirical_tenth([],expected_count=False,max_rows=value)
    with pytest.raises(EmpiricalTenthError,match='INVALID_EXPECTED_COUNT'):
        lower_empirical_tenth([],expected_count=value,max_rows=2)


@pytest.mark.parametrize('values',[[],[1.],1.,'private-input',True])
def test_shape_precedes_count_domain_and_no_payload_echo(values):
    with pytest.raises(EmpiricalTenthError) as caught:
        lower_empirical_tenth(values,expected_count=10,max_rows=1)
    assert caught.value.code=='IMMUTABLE_TUPLE_REQUIRED' and 'private' not in str(caught.value)


def test_never_consume_generator_or_arbitrary_iterable():
    def forbidden():
        raise AssertionError('ITERATION_FORBIDDEN')
        yield 1.
    iterator=forbidden()
    with pytest.raises(EmpiricalTenthError,match='IMMUTABLE_TUPLE_REQUIRED'):
        run(iterator,1)


def test_count_domain_before_absent_and_excess_before_slot_scan():
    for values in (None, (True,)*3):
        with pytest.raises(EmpiricalTenthError,match='CALL_DOMAIN_EXCEEDED'):
            run(values,3,2)
    with pytest.raises(EmpiricalTenthError,match='CALL_DOMAIN_EXCEEDED'):
        run((True,)*3,1,2)
    with pytest.raises(EmpiricalTenthError,match='UNEXPECTED_EXTRA_OBSERVATIONS'):
        run((True,1.),1,2)


def test_subclasses_not_coerced():
    class T(tuple):pass
    class F(float):pass
    class I(int):pass
    with pytest.raises(EmpiricalTenthError,match='IMMUTABLE_TUPLE_REQUIRED'):
        run(T((1.,)),1)
    with pytest.raises(EmpiricalTenthError,match='BINARY64_REQUIRED'):
        run((F(1),),1)
    with pytest.raises(EmpiricalTenthError,match='INVALID_EXPECTED_COUNT'):
        run((1.,),I(1))


def test_finite_extremes_and_decimal_context_independence():
    assert sys.float_info.radix==2 and sys.float_info.mant_dig==53
    values=(-sys.float_info.max,sys.float_info.max)
    expected=run(values,2)
    with localcontext() as ctx:
        ctx.prec=1;ctx.Emax=0;ctx.Emin=0
        for key in ctx.traps:ctx.traps[key]=True
        ctx.clear_flags()
        assert run(values,2)==expected and not any(ctx.flags.values())
    assert expected.q==-sys.float_info.max
