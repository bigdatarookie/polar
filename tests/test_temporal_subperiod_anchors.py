"""Prospective NAV-anchor mapping; no retained data or producer/native call."""
from copy import deepcopy
from decimal import Decimal
import pytest

from test_scheduled_diagnostics import tape,schedule
from polar.scheduled_diagnostics import diagnose,diagnose_temporal_anchors,evaluate_segment
from polar.scheduled_service import diagnose_phase

DAYS=['2022-12-30','2023-01-03','2024-12-30','2024-12-31','2025-01-02','2026-11-06']


def ledger():
    t=tape([10000,10100,10200,10300,10400,10500],days=DAYS)
    for i,row in enumerate(t['nav']):
        row.update(flat_cents=i*10,bps_cents=i*5)
        t['fills'].append({'at_ns':row['nominal_ns'],'q':1,'exact_notional_micro':(i+1)*1000000,
                           'settled_cents':(i+1)*100})
    return t


def test_first_and_interior_anchors_map_to_next_saved_return_and_carry_costs():
    t=ledger();before=deepcopy(t)
    result=diagnose_temporal_anchors(t,schedule(DAYS),subperiods=[(DAYS[0],DAYS[3]),(DAYS[3],DAYS[-1])])
    assert result['schema']=='polar.temporal-saved-diagnostics/2'
    first,second=result['subperiods']
    assert (first['initial_date'],first['first_return_date'],first['last_return_date'],first['intervals'])==(DAYS[0],DAYS[1],DAYS[3],3)
    assert (second['initial_date'],second['first_return_date'],second['last_return_date'],second['intervals'])==(DAYS[3],DAYS[4],DAYS[5],2)
    assert first['requested_initial_anchor']==DAYS[0] and second['requested_initial_anchor']==DAYS[3]
    assert first['metrics']['initial_nav_cents']=='10000' and second['metrics']['initial_nav_cents']=='10300'
    assert first['costs']['total_fee_usd']['value']=='0.45'
    assert second['costs']['total_fee_usd']['value']=='0.3'
    assert first['costs']['positive_fill_count']['value']=='3'
    assert second['costs']['positive_fill_count']['value']=='2'
    assert first['costs']['gross_exact_notional_usd']['value']=='9'
    assert second['costs']['gross_exact_notional_usd']['value']=='11'
    # Fill at shared anchor belongs to the first segment, excluded from the second.
    assert first['account_treatment']==second['account_treatment']=='CARRIED_SAVED_HOLDINGS_NO_RESET_NO_EXTRA_LIQUIDATION'
    assert t==before


@pytest.mark.parametrize('anchor,end,reason',[
    ('2024-01-01',DAYS[-1],'SAVED_NAV_ANCHOR_MISSING'),
    (DAYS[0],'2024-01-01','SUBPERIOD_BOUNDARY_MISSING'),
    (DAYS[-1],DAYS[-1],'NO_RETURN_AFTER_SAVED_NAV_ANCHOR'),
    (DAYS[3],DAYS[2],'SAVED_NAV_ANCHOR_AFTER_END'),
])
def test_missing_or_empty_boundaries_are_unavailable_not_fake_zero(anchor,end,reason):
    r=diagnose_temporal_anchors(ledger(),[],subperiods=[(anchor,end)])['subperiods'][0]
    assert r['status']=='UNAVAILABLE' and r['reason']==reason and r['value'] is None
    assert r['requested_initial_anchor']==anchor
    assert 'metrics' not in r and 'intervals' not in r


def test_legacy_return_date_helper_and_other_profile_dispatch_remain_unchanged():
    t=ledger();legacy=evaluate_segment(t,DAYS[3],DAYS[-1])
    assert legacy['initial_date']==DAYS[2] and legacy['first_return_date']==DAYS[3] and legacy['intervals']==3
    assert evaluate_segment(t,DAYS[0],DAYS[3])['reason']=='PRECEDING_REFERENCE_CLOSE_MISSING'
    before=diagnose(t,[],subperiods=[(DAYS[3],DAYS[-1])])
    assert diagnose_phase(t,[],{'schema':'polar.scheduled-reference-profile/1'},None,
                          subperiods=[(DAYS[3],DAYS[-1])])==before
    temporal=diagnose_phase(t,[],{'schema':'polar.scheduled-reference-profile/6'},None,
                           subperiods=[(DAYS[3],DAYS[-1])])
    assert temporal['subperiods'][0]['initial_date']==DAYS[3]
    assert temporal['subperiods'][0]['intervals']==2
    assert evaluate_segment(t,DAYS[3],DAYS[-1])==legacy


def test_anchor_adapter_preserves_latest_equal_high_episode_and_empty_stress():
    t=tape([100,100,80,100],days=DAYS[:4])
    d=diagnose_temporal_anchors(t,[],subperiods=[(DAYS[0],DAYS[3])])
    assert d['drawdown']['peak']['date']==DAYS[1]
    assert d['subperiods'][0]['drawdown']['peak']['date']==DAYS[1]
    assert diagnose_temporal_anchors(t,[],subperiods=())['subperiods']==[]
