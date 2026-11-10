"""Prospective invented literals only; author has NOT invoked these controls."""
from fractions import Fraction
import pytest

from polar.obs158_math import (Obs158Error,microprice,cent_round_micro,settled_fill,
                               marked_account,snapshot_targets,forward_unit)


@pytest.mark.parametrize('token,expected',[('1.234567',1234567),('0.000001',1),('10.00',10000000)])
def test_lossless_microprice(token,expected):assert microprice(token)==expected


@pytest.mark.parametrize('token',['0','NaN','1.0000001','1e0','-1',' 1'])
def test_invalid_or_nonliteral_price_rejected(token):
    with pytest.raises(Obs158Error):microprice(token)


@pytest.mark.parametrize('micro,cents',[(1005000,100),(1015000,102),(-1005000,-100)])
def test_half_even_after_notional_multiplication(micro,cents):assert cent_round_micro(micro)==cents


def test_position_rounding_is_separate_from_aggregate():
    result=marked_account(0,{'A':1,'B':1},{'A':1005000,'B':1005000},['A','B'])
    assert result['price_ledger_value_cents']=='200'
    assert cent_round_micro(2010000)==201


def test_buy_maximum_rounded_fee_aware_quantity():
    result=settled_fill('BUY',3,0,200,1005000)
    assert result['filled_quantity']=='1' and result['cash_after_cents']=='0'
    assert result['fee_cents']=='100'
    assert result['epsilon_USD']=={'numerator':'-1','denominator':'200'}
    assert result['signed_cash_rounding_USD']=={'numerator':'1','denominator':'200'}


def test_sell_fee_shortfall_and_zero_orders_have_no_fee():
    result=settled_fill('SELL',1,1,0,100000)
    assert result['filled_quantity']=='0' and result['fee_cents']=='0'
    assert result['reasons']==['SELL_FEE_CASH_SHORTFALL']
    assert settled_fill('BUY',0,0,10000,1000000)['fee_cents']=='0'


def test_depth_and_holdings_caps_remain_explicit():
    result=settled_fill('SELL',1000001,2,1000,1000000)
    assert result['filled_quantity']=='2' and result['unrouted_quantity']=='999999'
    assert result['reasons']==['MODEL_DEPTH_CAP','HELD_QUANTITY_CAP']


def test_zero_positions_need_no_source_mark():
    result=marked_account(10000,{'A':0},{},['A'])
    assert result['price_ledger_value_cents']=='10000'
    with pytest.raises(Obs158Error,match='MISSING_POSITION_MARK'):
        marked_account(10000,{'A':1},{},['A'])


def test_exact_target_floor_uses158_and_snapshot_closes():
    aliases=['X'+str(i) for i in range(158)]
    assert set(snapshot_targets(15800,{s:1000000 for s in aliases},aliases).values())=={1}


def test_forward_only_unit_and_rounded_position_equivalence():
    assert forward_unit(4,25000001,4)=={'native_quantity':'1','native_mark_micro':'100000004',
        'physical_quantity':'4','factor':4,'position_cents':'10000'}
    with pytest.raises(Obs158Error):forward_unit(3,25000001,4)
