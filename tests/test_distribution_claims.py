"""Independent invented arithmetic controls; no market source or engine inputs."""
from dataclasses import asdict, replace, FrozenInstanceError
from decimal import localcontext
from fractions import Fraction
import json
import pytest
from polar.distribution_claims import (Action, State, Phase, ClaimError, recognize, pay,
    settled_snapshot, split, valuation, record, restore, transition, verify)

DATES=('2020-01-02','2020-01-03','2020-01-06','2020-01-07','2020-01-08')


def action(**kw):
    return Action(**dict(event_id='INVENTED-D1', instrument='INVENTED', source_ref='invented-source',
                        raw_pointer='/invented/actions/0', ex_date=DATES[0], payment_date=DATES[1],
                        amount_token='0.125', reference_dates=DATES, **kw)) if not kw else replace(action(), **kw)


def state(q=10, cash=0):
    return State('2020-01-01', Phase.CLOSE_SETTLED, cash, (('INVENTED', q),))


def test_entitlement_and_delayed_payment_conserve_nav_without_new_gain():
    before=state(); due=recognize(before, action(), DATES[0])
    assert due.claims[0].cents == 125 and due.claims[0].entitled_quantity == 10
    assert valuation(before, {'INVENTED':20000})['nav_cents'] == 20000
    assert valuation(due, {'INVENTED':19875})['nav_cents'] == 20000
    assert due.available_cash_cents == 0
    for d in DATES[:2]:
        with pytest.raises(ClaimError, match='AVAILABILITY'): pay(due, 'INVENTED-D1', d)
    paid=pay(due, 'INVENTED-D1', DATES[2])
    assert paid.available_cash_cents == 125 and paid.claims[0].status == 'PAID'
    assert valuation(paid, {'INVENTED':19875})['nav_cents'] == 20000
    with pytest.raises(ClaimError, match='DOUBLE_PAYMENT'): pay(paid, 'INVENTED-D1', DATES[2])
    with pytest.raises(ClaimError, match='UNKNOWN_EVENT'): pay(due, 'missing', DATES[2])


def test_ex_close_buy_no_entitlement_and_sell_keeps_claim_zero_recorded():
    due=recognize(state(), action(), DATES[0])
    sold=settled_snapshot(due, DATES[0], (('INVENTED',0),), 19875)
    assert sold.claims == due.claims and valuation(sold, {'INVENTED':0}, terminal=True)['nav_cents'] == 20000
    terminal=valuation(sold, {'INVENTED':0}, terminal=True)
    assert terminal['claim_status'] == 'TERMINAL_OUTSTANDING' and not terminal['cash_only_terminal']
    assert terminal['outstanding_count'] == 1
    paid=pay(sold, 'INVENTED-D1', DATES[2])
    assert valuation(paid, {'INVENTED':0}, terminal=True)['cash_only_terminal']
    zero=recognize(state(0,20000), action(), DATES[0])
    bought=settled_snapshot(zero, DATES[0], (('INVENTED',10),), 125)
    assert bought.claims[0].cents == 0 and bought.claims[0].entitled_quantity == 0
    with pytest.raises(ClaimError): recognize(bought, action(), DATES[0])
    with pytest.raises(ClaimError, match='DUPLICATE'): recognize(zero, action(), DATES[0])
    with pytest.raises(ClaimError, match='ORDER'): recognize(sold, action(event_id='D2'), DATES[0])


@pytest.mark.parametrize('amount,q,cents,residue',[
    ('0.005',1,0,(1,2)), ('0.015',1,2,(-1,2)),
    ('0.0000000000000000000000000000000000000001',3,0,(3,10**38)),
    ('0.0166666666666666666666666666666666666667',3,5,(1,10**38))])
def test_single_half_even_with_arbitrary_decimal_precision(amount,q,cents,residue):
    with localcontext() as ctx:
        ctx.prec=2
        c=recognize(state(q), action(amount_token=amount), DATES[0]).claims[0]
    assert c.cents == cents and c.residue == residue
    assert Fraction(c.cents)+Fraction(*c.residue) == q*Fraction(amount)*100


def test_integer_split_conserves_raw_value_and_existing_claim():
    due=recognize(state(), action(), DATES[0])
    changed=split(due,'INVENTED',2,1,DATES[1],same_day_ex=False)
    assert dict(changed.holdings)['INVENTED'] == 20 and changed.claims == due.claims
    assert valuation(changed,{'INVENTED':20000}) == valuation(due,{'INVENTED':20000})
    assert 10*20000000 == 20*10000000  # reciprocal raw quote scale, no loader
    with pytest.raises(ClaimError, match='FRACTIONAL'): split(state(1),'INVENTED',1,2,DATES[0],same_day_ex=False)
    with pytest.raises(ClaimError, match='AMBIGUOUS'): split(state(),'INVENTED',2,1,DATES[0],same_day_ex=True)
    with pytest.raises(ClaimError, match='AMBIGUOUS'): split(due,'INVENTED',2,1,DATES[0],same_day_ex=False)


@pytest.mark.parametrize('kw',[{'currency':'EUR'},{'basis':'ADJUSTED'}, {'payment_date':'2019-12-31'},
    {'amount_token':'NaN'}, {'amount_token':'1e-4'}, {'amount_token':'-1'},
    {'reference_dates':('2020-01-02',)}, {'reference_dates':tuple(reversed(DATES))}])
def test_invalid_descriptor_rejected(kw):
    with pytest.raises(ClaimError): action(**kw)


def test_strict_quantities_and_frozen_results():
    for q in [True,-1,1.5]:
        with pytest.raises(ClaimError): state(q)
    due=recognize(state(),action(),DATES[0])
    with pytest.raises(FrozenInstanceError): due.available_cash_cents=42
    with pytest.raises(ClaimError,match='PHASE'): recognize(state(),action(),DATES[0],Phase.CLOSE_SETTLED)
    with pytest.raises(ClaimError,match='FLAT_MARK'): valuation(state(0),{'INVENTED':1})


def test_json_saved_consistency_and_transition_tamper_controls():
    before=state()
    due,e=transition('recognize',before,{'action':asdict(action()),'session_date':DATES[0]})
    assert verify(e) == due and restore(json.loads(json.dumps(record(due)))) == due
    paid,p=transition('pay',due,{'event_id':'INVENTED-D1','session_date':DATES[2]})
    assert verify(p) == paid
    corrupt=json.loads(e.after_json);corrupt['available_cash_cents']=125
    with pytest.raises(ClaimError,match='MISMATCH'):verify(replace(e,after_json=json.dumps(corrupt,sort_keys=True,separators=(',',':'))))
    corrupt=json.loads(e.after_json);corrupt['claims'][0]['cents']+=1
    with pytest.raises(ClaimError,match='AMOUNT_EVIDENCE'):restore(corrupt)
    corrupt=json.loads(e.after_json);corrupt['claims'][0]['residue']=[1,2]
    with pytest.raises(ClaimError,match='AMOUNT_EVIDENCE'):restore(corrupt)
    corrupt=json.loads(p.after_json);corrupt['claims'][0]['paid_at']=DATES[1]
    with pytest.raises(ClaimError,match='PAYMENT_EVIDENCE'):restore(corrupt)
    with pytest.raises(ClaimError):verify(replace(p,inputs_json='{}'))
