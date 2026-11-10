"""Pinned timer-loop model and static adapter joins; no Nautilus import/run."""
import ast
import heapq
import json
from pathlib import Path

import pytest

from polar.capability_native import settlement_boundaries,failure_context
from polar.capability_contract import OPEN_DATES,SYMBOLS,ns


def process(routes,boundaries):
    """Model engine.pyx pop/settle/callback/re-advance, including last settlement.

    Clocks' newly-created alerts are separate from the accumulated handler heap.
    Capturing clocks after callbacks does not capture alerts created by the
    final settle after the loop. No prices/cash/allocations are modelled here.
    """
    accumulator=[];clock=[];pending=False;awaiting=False;events=[]
    def schedule(timestamp,kind):clock.append((timestamp,kind))
    def capture(until):
        for event in list(clock):
            if event[0]<=until:heapq.heappush(accumulator,event);clock.remove(event)
    def settle(timestamp):
        nonlocal pending,awaiting
        if pending:
            pending=False;awaiting=True;events.append(('fill',timestamp));schedule(timestamp+1,'balance')
    def callback(timestamp,kind):
        nonlocal pending,awaiting
        if kind=='snapshot':
            for ordinal in range(1,routes+1):schedule(1000*(ordinal+1),'route')
        elif kind=='route':
            assert not pending and not awaiting,'PENDING_ORDER'
            pending=True;events.append(('route',timestamp))
        elif kind=='balance':
            assert awaiting and not pending
            awaiting=False;events.append(('balance',timestamp))
        elif kind=='terminal':assert not pending and not awaiting,'PENDING_ORDER'
    def loop(until,inclusive):
        last=0
        while accumulator and accumulator[0][0] <= until-int(not inclusive):
            timestamp,kind=heapq.heappop(accumulator)
            if timestamp!=last and last:settle(last)
            last=timestamp;callback(timestamp,kind);capture(until)
        if last:settle(last)
    schedule(1000,'snapshot');schedule(10000,'terminal')
    for timestamp in sorted(set(boundaries)|{10000}):
        capture(timestamp);loop(timestamp,False)
        settle(timestamp)  # Main loop processes the price-free data item.
        loop(timestamp,True)
    return events


def test_without_data_barrier_fill_created_balance_is_not_captured_before_terminal():
    with pytest.raises(AssertionError,match='PENDING_ORDER'):process(1,[])


@pytest.mark.parametrize('routes',[1,2,3,4])
def test_price_free_barriers_clear_balance_before_next_route_or_terminal(routes):
    events=process(routes,[1000*(ordinal+1)+1 for ordinal in range(1,5)])
    assert [kind for kind,_ in events]==['route','fill','balance']*routes
    assert [t for kind,t in events if kind=='route']==[1000*(ordinal+1) for ordinal in range(1,routes+1)]
    assert [t for kind,t in events if kind=='balance']==[1000*(ordinal+1)+1 for ordinal in range(1,routes+1)]


def test_exact_source_grid_preserves_price_and_logical_event_construction():
    times=settlement_boundaries()
    assert len(times)==2*len(SYMBOLS)==8 and len(set(times))==8
    assert times==tuple(ns(day+'T14:30:00.000000Z')+1000*(r+1)+1 for day in OPEN_DATES for r in range(1,5))
    for day in OPEN_DATES:
        Q=ns(day+'T14:30:00.000000Z')
        assert Q+1000 < Q+2001 < Q+3000 and Q+5001 < Q+10000
    source=Path(__file__).parents[1]/'src/polar/capability_native.py'
    tree=ast.parse(source.read_text())
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='add_data']
    controls=[n for n in calls if any(isinstance(x,ast.Name) and x.id=='CustomData' for x in ast.walk(n))]
    assert len(controls)==1
    assert not any(isinstance(x,ast.Name) and x.id in ('QuoteTick','MarkPriceUpdate','Price') for x in ast.walk(controls[0]))
    # Economic source rows and route/sample timestamps remain the existing expressions.
    text=source.read_text()
    assert 'Q+1000*(route+1)' in text and 'event.ts_event+1,self.balance' in text
    assert 'not self.pending and self.awaiting_balance is None' in text


def test_failure_context_is_bounded_and_contains_no_expected_value_payload():
    pending={str(i).zfill(3)+'x'*200:{'private_expected':'must-not-copy'} for i in range(100)}
    value=failure_context('PENDING_ORDER',pending,{'logical_order_id':'test/exit/1','private_expected':1},'sample-6',123)
    assert value['pending_count']==100 and len(value['pending_ids'])==16
    assert all(len(s)<=128 for s in value['pending_ids'])
    assert value['awaiting_logical_id']=='test/exit/1' and value['callback_kind']=='sample-6'
    assert value['callback_ns']=='123' and len(json.dumps(value).encode())<4096
    assert 'private_expected' not in json.dumps(value)
