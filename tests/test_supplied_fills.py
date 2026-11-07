"""Controlled literals, atomicity and bounds; no service jobs or market data."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, Inexact, Rounded, localcontext

import pytest

from polar.allocation import Position
from polar.supplied_fills import LedgerError, LedgerSnapshot, SuppliedFill, apply_supplied_fills

AT = datetime(2026, 11, 7, 5, tzinfo=timezone.utc)
CUTOFF = AT + timedelta(seconds=10)


def snapshot(cash='100', positions=(), history=()):
    return LedgerSnapshot(D(cash), 'USD', AT, tuple(Position(k,q) for k,q in positions), history)


def fill(fid='f1', name='A', quantity=2, price='10', fee='1', sequence=1, execution=1, receipt=None):
    return SuppliedFill(fid,name,quantity,D(price),D(fee),'USD',AT+timedelta(seconds=execution),
                        AT+timedelta(seconds=execution if receipt is None else receipt),sequence)


def apply(s, events=(), **kwargs):
    return apply_supplied_fills(s,events,CUTOFF,max_names=kwargs.get('max_names',3),max_events=kwargs.get('max_events',10))


def test_predeclared_contract_chain_every_receipt():
    s=snapshot(history=('old',))
    events=(fill(),fill('f2','A',-1,'12','1',2,2),fill('f3','B',1,'20','0',3,3))
    r=apply(s,events)
    assert r.snapshot.cash == D('70')
    assert r.snapshot.positions == (Position('A',1),Position('B',1))
    assert r.total_fees == D('2')
    assert [(x.cash_before,x.cash_after) for x in r.receipts] == [(D('100'),D('79')),(D('79'),D('90')),(D('90'),D('70'))]
    assert [(x.position_before,x.position_after) for x in r.receipts] == [(0,2),(2,1),(0,1)]
    assert r.snapshot.applied_fill_ids == ('old','f1','f2','f3')
    assert r.snapshot.as_of == events[-1].receipt_at
    for original,receipt in zip(events,r.receipts):
        for field in ('fill_id','instrument_id','quantity','price','fee','currency','execution_at','receipt_at','sequence'):
            assert getattr(receipt,field) == getattr(original,field)
    assert r.method == 'SUPPLIED_FILL_ACCOUNTING' and r.financial_verdict == 'NOT_RUN'
    assert s == snapshot(history=('old',))
    with pytest.raises(FrozenInstanceError): s.cash=D('1')
    with pytest.raises(FrozenInstanceError): r.snapshot.positions[0].quantity=99
    with pytest.raises(FrozenInstanceError): r.receipts[0].cash_after=D('0')


def test_partial_positions_and_stable_id_order():
    events=(fill('sell','A',-2,'4','1',1),fill('buy','B',1,'5','2',2,2))
    r=apply(snapshot('15',(('B',2),('A',3))),events)
    assert [(x.cash_before,x.cash_after) for x in r.receipts] == [(D('15'),D('22')),(D('22'),D('15'))]
    assert r.snapshot.positions == (Position('A',1),Position('B',3))
    assert r.total_fees == D('3')
    assert r == apply(snapshot('15',(('A',3),('B',2))),events)


def test_same_clock_economic_order_and_batch_atomicity():
    s=snapshot('0',(('A',1),))
    sell=fill('sell','A',-1,'10','0',1,0)
    buy=fill('buy','B',1,'10','0',2,0)
    r=apply(s,(sell,buy))
    assert r.snapshot.cash == 0 and r.snapshot.positions == (Position('A',0),Position('B',1))
    with pytest.raises(LedgerError,match='^INSUFFICIENT_CASH$'):
        apply(s,(replace(buy,sequence=1),replace(sell,sequence=2)))
    with pytest.raises(LedgerError,match='^UNORDERED_FILLS$'):
        apply(s,(buy,sell))
    # First step succeeds locally, second is insolvent: caller state stays intact.
    initial=snapshot()
    with pytest.raises(LedgerError,match='^INSUFFICIENT_CASH$'):
        apply(initial,(fill(),fill('later','B',10,'100','0',2,2)))
    assert initial == snapshot() and s == snapshot('0',(('A',1),))
    with pytest.raises(LedgerError,match='^INSUFFICIENT_POSITION$'):
        apply(s,(fill('sell','A',-2,'10','0'),))


def test_receipt_order_does_not_reorder_and_cutoff_does_not_advance():
    s=snapshot()
    first=fill(receipt=9)
    second=fill('f2','B',1,'1','0',99,2,3)
    r=apply(s,(first,second))
    assert tuple(x.fill_id for x in r.receipts) == ('f1','f2')
    assert r.snapshot.cash == D('78') and r.snapshot.as_of == AT+timedelta(seconds=9)
    assert apply(s).snapshot == s and apply(s).receipts == () and apply(s).total_fees == 0
    assert apply(r.snapshot).snapshot.as_of == r.snapshot.as_of
    with pytest.raises(LedgerError,match='^INVALID_FILL_TIME$'):
        apply(r.snapshot,(fill('f3',execution=4),))


def test_derived_output_unclipped_but_resubmission_bounded_even_empty():
    r=apply(snapshot('0',(('A',10**12),)),(fill(quantity=-(10**12),price='1e12',fee='0'),))
    assert r.snapshot.cash == D('1e24') and r.snapshot.positions == (Position('A',0),)
    with pytest.raises(LedgerError,match='^DECIMAL_OUT_OF_BOUNDS$'): apply(r.snapshot)
    r=apply(snapshot('1e12',(('A',10**12),)),(fill(quantity=1,price='1',fee='0'),))
    assert r.snapshot.positions == (Position('A',10**12+1),)
    with pytest.raises(LedgerError,match='^INVALID_POSITION_QUANTITY$'): apply(r.snapshot)


def test_precision_and_flags_independent_no_fee_hidden():
    s=snapshot('0.000000000003')
    event=fill(quantity=1,price='0.000000000001',fee='0.000000000001')
    with localcontext() as ctx:
        ctx.prec=2;ctx.Emax=2;ctx.Emin=-2;ctx.traps[Inexact]=ctx.traps[Rounded]=True;ctx.clear_flags()
        result=apply(s,(event,))
        with pytest.raises(LedgerError,match='^INSUFFICIENT_CASH$'):
            apply(s,(event,replace(event,fill_id='f2',sequence=2)))
        assert ctx.prec == 2 and ctx.Emax == 2 and not any(ctx.flags.values())
    assert result.snapshot.cash == D('0.000000000001')
    assert result.total_fees == D('0.000000000001')
    zero=D('0E+999999999')
    source=replace(snapshot('0',(('A',1),)),cash=zero)
    assert apply(source,(fill(quantity=-1,price='1',fee='0'),)).snapshot.cash == D('1')
    assert str(source.cash) == str(zero)


@pytest.mark.parametrize('case,events,code',[
    (replace(snapshot(),cash=D('-1')),(),'NEGATIVE_CASH'),
    (snapshot(positions=(('A',-1),)),(),'INVALID_POSITION_QUANTITY'),
    (snapshot(positions=(('A',True),)),(),'INVALID_POSITION_QUANTITY'),
    (snapshot(positions=(('A',D('1')),)),(),'INVALID_POSITION_QUANTITY'),
    (snapshot(positions=(('A',1),('A',2))),(),'DUPLICATE_POSITION'),
    (snapshot(history=('old','old')),(),'DUPLICATE_FILL_ID'),
    (snapshot(history=('f1',)),(fill(),),'DUPLICATE_FILL_ID'),
    (snapshot(),(fill(),replace(fill(),sequence=2)),'DUPLICATE_FILL_ID'),
    (snapshot(),(fill(quantity=0),),'INVALID_FILL_QUANTITY'),
    (snapshot(),(replace(fill(),quantity=1.5),),'INVALID_FILL_QUANTITY'),
    (snapshot(),(replace(fill(),quantity=D('1')),),'INVALID_FILL_QUANTITY'),
    (snapshot(),(replace(fill(),quantity=True),),'INVALID_FILL_QUANTITY'),
    (snapshot(),(fill(quantity=10**12+1),),'INVALID_FILL_QUANTITY'),
    (snapshot(),(fill(price='0'),),'NONPOSITIVE_PRICE'),
    (snapshot(),(fill(price='-1'),),'NONPOSITIVE_PRICE'),
    (snapshot(),(fill(fee='-1'),),'NEGATIVE_FEE'),
    (replace(snapshot(),currency='usd'),(),'INVALID_CURRENCY'),
    (snapshot(),(replace(fill(),currency='EUR'),),'CURRENCY_MISMATCH'),
    (snapshot(),(replace(fill(),sequence=True),),'INVALID_SEQUENCE'),
    (snapshot(),(replace(fill(),sequence=-1),),'INVALID_SEQUENCE'),
    (snapshot(),(replace(fill(),sequence=10**12+1),),'INVALID_SEQUENCE'),
    (snapshot(),(fill(execution=-1),),'INVALID_FILL_TIME'),
    (snapshot(),(fill(execution=3,receipt=2),),'INVALID_FILL_TIME'),
    (snapshot(),(fill(receipt=11),),'INVALID_FILL_TIME'),
    (snapshot(),(fill(execution=2),fill('f2',sequence=2,execution=1)),'UNORDERED_FILLS'),
    (replace(snapshot(),as_of=AT.replace(tzinfo=None)),(),'UTC_REQUIRED'),
    (snapshot(),(replace(fill(),execution_at=AT.replace(tzinfo=None)),),'UTC_REQUIRED'),
    (snapshot(),(replace(fill(),receipt_at=AT.astimezone(timezone(timedelta(hours=1)))),),'UTC_REQUIRED'),
    (snapshot(history=('private payload',)),(),'INVALID_ID'),
    (snapshot(),(fill(fid=' x'),),'INVALID_ID'),
    (snapshot(),(fill(name='\u0410'),),'INVALID_ID'),
    (replace(snapshot(),positions=[]),(),'IMMUTABLE_TUPLE_REQUIRED'),
    (replace(snapshot(),applied_fill_ids=[]),(),'IMMUTABLE_TUPLE_REQUIRED'),
    (snapshot(),[fill()],'IMMUTABLE_TUPLE_REQUIRED'),
    (replace(snapshot(),positions=('A',)),(),'INVALID_POSITION'),
    (snapshot(),('not a fill',),'INVALID_FILL'),
])
def test_rejection_codes_and_no_mutation(case,events,code):
    before=repr(case),repr(events)
    with pytest.raises(LedgerError) as exc: apply(case,events)
    assert str(exc.value) == exc.value.code == code
    assert (repr(case),repr(events)) == before


@pytest.mark.parametrize('value,code',[(1,'DECIMAL_REQUIRED'),(1.0,'DECIMAL_REQUIRED'),(True,'DECIMAL_REQUIRED'),('1','DECIMAL_REQUIRED'),
    (D('NaN'),'DECIMAL_OUT_OF_BOUNDS'),(D('sNaN'),'DECIMAL_OUT_OF_BOUNDS'),(D('Infinity'),'DECIMAL_OUT_OF_BOUNDS'),
    (D('1000000000001'),'DECIMAL_OUT_OF_BOUNDS'),(D('0.0000000000001'),'DECIMAL_OUT_OF_BOUNDS')])
@pytest.mark.parametrize('field',['cash','price','fee'])
def test_decimal_input_contract(value,code,field):
    s=snapshot();event=fill()
    if field=='cash':s=replace(s,cash=value)
    else:event=replace(event,**{field:value})
    with pytest.raises(LedgerError,match='^'+code+'$'):apply(s,(event,))


@pytest.mark.parametrize('limit',[0,-1,1001,True,1.5,'10',None])
@pytest.mark.parametrize('name',['max_names','max_events'])
def test_explicit_limits(limit,name):
    with pytest.raises(LedgerError,match='^INVALID_LIMIT$'):apply(snapshot(),**{name:limit})


def test_history_and_name_limits_cover_retained_view():
    with pytest.raises(LedgerError,match='^EVENT_LIMIT$'):
        apply(snapshot(history=('old1','old2')),(fill(),),max_events=2)
    with pytest.raises(LedgerError,match='^NAME_LIMIT$'):
        apply(snapshot(positions=(('B',0),)),(fill(),),max_names=1)
    s=snapshot(history=tuple('old'+str(i) for i in range(999)))
    assert len(apply(s,(fill(),),max_events=1000).snapshot.applied_fill_ids) == 1000
    s=snapshot(positions=tuple(('A'+str(i),0) for i in range(1000)))
    assert len(apply(s,max_names=1000,max_events=1).snapshot.positions) == 1000
    with pytest.raises(LedgerError,match='^INVALID_SNAPSHOT$'):apply(None)
    with pytest.raises(LedgerError,match='^CUTOFF_BEFORE_SNAPSHOT$'):
        apply_supplied_fills(snapshot(),(),AT-timedelta(seconds=1),max_names=1,max_events=1)


def test_full_batch_exact_fee_sum_and_inclusive_snapshot_clock():
    s=snapshot('0',tuple(('A'+str(i),1) for i in range(1000)))
    events=tuple(fill('f'+str(i),'A'+str(i),-1,'1e12','1e12',i,0) for i in range(1000))
    r=apply_supplied_fills(s,events,AT,max_names=1000,max_events=1000)
    assert len(r.receipts) == len(r.snapshot.applied_fill_ids) == 1000
    assert r.snapshot.applied_fill_ids[0] == 'f0' and r.snapshot.applied_fill_ids[-1] == 'f999'
    assert r.snapshot.cash == 0 and all(p.quantity==0 for p in r.snapshot.positions)
    assert r.total_fees == D('1e15') and r.snapshot.as_of == AT
    assert all(x.cash_before==x.cash_after==0 for x in r.receipts)
    assert apply_supplied_fills(r.snapshot,(),CUTOFF,max_names=1000,max_events=1000).total_fees == 0
