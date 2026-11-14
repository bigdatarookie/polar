from fractions import Fraction as F
import pytest
from polar.signed_execution_terms import OrderFees,execution_quote,SideQuote


def test_ceiling_fractional_cent_and_no_unfilled_flat():
    fees=OrderFees(100,10)
    assert fees.orders=={}
    charge=fees.fill('one',1,F(1,100))
    assert (charge['flat_cents'],charge['bps_cents'],charge['total_cents'])==(100,1,101)


def test_partial_order_flat_once_cumulative_ceiling_independent_close_open():
    fees=OrderFees(100,10)
    a=fees.fill('open',1,F(1,100));b=fees.fill('open',2,F(2,100))
    assert a['total_cents']+b['total_cents']==101 and b['flat_cents']==b['bps_cents']==0
    assert fees.fill('close',1,F(1,100))['total_cents']==101
    assert fees.fill('reopen',1,F(1,100))['total_cents']==101
    # Cumulative 10 USD exact at10bps is one cent, then a positive
    # fractional-cent increment crosses to two, independently of partition.
    whole=OrderFees(100,10);split=OrderFees(100,10)
    expected=whole.fill('o',3,F(10001,3000))['total_cents']
    actual=sum(split.fill('o',1,F(10001,3000))['total_cents'] for _ in range(3))
    assert actual==expected==102


def test_explicit_side_quote_keeps_reference_and_eight_place_execution():
    q=execution_quote('AAPL','source-row','PATH7',F(1234567,1000000),adverse=True)
    assert q.reference==F(1234567,1000000)
    assert q.price('BUY')==q.reference*F(101,100) and q.price('SELL')==q.reference*F(99,100)
    assert (q.ask*10**6).denominator!=1 and (q.ask*10**8).denominator==1
    assert execution_quote('AMZN','r','BASE',F(1)).bid==F(1)


@pytest.mark.parametrize('flat,bps',[(True,10),(100,True),(-1,10),(100,10001)])
def test_fee_parameters_strict(flat,bps):
    with pytest.raises(Exception):OrderFees(flat,bps)


@pytest.mark.parametrize('qty,price',[(0,F(1)),(True,F(1)),(1,1.0),(1,F(0))])
def test_fee_fill_is_exact_positive_actual_operand(qty,price):
    with pytest.raises(Exception):OrderFees(100,10).fill('o',qty,price)
