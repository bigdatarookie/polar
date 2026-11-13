"""Invented saved NAVs only: B9 era pairs are anchors, not return dates."""
from copy import deepcopy
import pytest
from test_scheduled_diagnostics import tape, schedule
from polar.scheduled_service import diagnose_phase
from polar.scheduled_fixed import diagnose_fixed


def saved_case(leg='BIL_FULL'):
    days=['2020-12-29','2020-12-30','2020-12-31','2021-01-04','2021-01-05']
    t=tape([10000,11000,12000,10800,12000],days=days);t['id']=leg
    for i,row in enumerate(t['nav']):
        row.update(flat_cents=i*100,bps_cents=i*10,cash_cents=row['nav_cents']-100,
                   positions={'AAA':1},position_cents={'AAA':100})
        if i:t['fills'].append({'at_ns':row['nominal_ns']+500,'q':1,
            'exact_notional_micro':1000000,'settled_cents':100})
    return t,schedule(days),{d:{'AAA':{'close_micro':1000000}} for d in days}


@pytest.mark.parametrize('leg',['BIL_FULL','SHY_FULL','CASH'])
def test_profile12_era_uses_next_saved_return_and_carried_anchor(leg):
    t,rows,prices=saved_case(leg);before=deepcopy(t)
    spans=[['2020-12-29','2020-12-31'],['2020-12-31','2021-01-05']]
    got=diagnose_phase(t,rows,{'schema':'polar.scheduled-reference-profile/12'},
                       {'prices':prices},subperiods=spans)
    a,b=got['subperiods']
    assert (a['initial_date'],a['first_return_date'],a['intervals'])==('2020-12-29','2020-12-30',2)
    assert (b['initial_date'],b['first_return_date'],b['intervals'])==('2020-12-31','2021-01-04',2)
    assert b['requested_initial_anchor']=='2020-12-31'
    assert b['initial_holdings']['positions']=={'AAA':'1'}
    assert b['metrics']['initial_nav_cents']=='12000'
    assert b['costs']['flat_cents']['value']=='200' and b['costs']['bps_cents']['value']=='20'
    assert b['costs']['positive_fill_count']['value']=='2'  # anchor fill excluded
    # Preserve fixed recipe/earliest equal peak, not temporal latest-equal rule.
    baseline=diagnose_fixed(t,rows,prices)
    assert {k:v for k,v in got.items() if k not in ('subperiods','subperiod_semantics')}=={k:v for k,v in baseline.items() if k!='subperiods'}
    assert t==before


@pytest.mark.parametrize('pair,reason',[
    (['2020-12-28','2021-01-05'],'SAVED_NAV_ANCHOR_MISSING'),
    (['2020-12-31','2021-01-06'],'SUBPERIOD_BOUNDARY_MISSING'),
    (['2021-01-05','2021-01-05'],'NO_RETURN_AFTER_SAVED_NAV_ANCHOR'),
    (['2021-01-05','2020-12-31'],'SAVED_NAV_ANCHOR_AFTER_END')])
def test_anchor_unavailable_never_guesses_adjacent_date(pair,reason):
    t,rows,prices=saved_case()
    out=diagnose_phase(t,rows,{'schema':'polar.scheduled-reference-profile/12'},
                       {'prices':prices},subperiods=[pair])['subperiods'][0]
    assert out['status']=='UNAVAILABLE' and out['reason']==reason
    assert out['requested_initial_anchor']==pair[0]


@pytest.mark.parametrize('version',[5,8,9,10])
def test_legacy_fixed_profile_first_return_convention_unchanged(version):
    t,rows,prices=saved_case();spans=[['2020-12-31','2021-01-05']]
    got=diagnose_phase(t,rows,{'schema':f'polar.scheduled-reference-profile/{version}'},
                       {'prices':prices},subperiods=spans)
    assert got==diagnose_fixed(t,rows,prices,subperiods=spans)
    assert got['subperiods'][0]['initial_date']=='2020-12-30'
    assert got['subperiods'][0]['intervals']==3


def test_profile12_no_requested_stress_eras_remains_empty():
    t,rows,prices=saved_case()
    assert diagnose_phase(t,rows,{'schema':'polar.scheduled-reference-profile/12'},
                          {'prices':prices})['subperiods']==[]
